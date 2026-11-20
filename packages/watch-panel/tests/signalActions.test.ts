import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  isSignalActionType,
  optimisticSignals,
  performSignalAction,
  planActionBody,
  presetIso,
  primaryIntent,
  signalActionBody,
  snoozeLabel,
  statusAfter,
  toastFor,
  type ActionResult,
  type SignalAction,
} from '../src/client/signalActions.ts'
import type { Signal } from '../src/client/signals.ts'

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 5,
    ts: '2026-11-03T10:00:00+08:00',
    kind: 'plan_entry',
    kindLabel: '计划触发 · 进场',
    decide: true,
    severity: 'L3',
    status: 'new',
    snoozeUntil: null,
    object: { type: 'stock', code: '600000', name: '浦发银行' },
    title: 't',
    direction: 'bull',
    directionLabel: '偏多',
    conclusion: 'c',
    brief: 'b',
    context: null,
    source: { label: 's', alertIds: [], analysisId: null, planId: 77, ruleId: null },
    mergedCount: 1,
    primary: { label: '查看分析', action: 'open' },
    detailAvailable: true,
    ...overrides,
  }
}

function ports(result: ActionResult, calls: unknown[] = [], now = Date.parse('2026-11-03T10:00:00+08:00')) {
  return {
    now: () => now,
    post: async (body: unknown): Promise<ActionResult> => { calls.push(body); return result },
  }
}

test('signal action bodies carry only the whitelisted action', () => {
  assert.deepEqual(signalActionBody({ type: 'ack', id: 5 }), { id: 5, action: 'ack' })
  assert.deepEqual(signalActionBody({ type: 'ignore', id: 5 }), { id: 5, action: 'ignore' })
  assert.deepEqual(signalActionBody({ type: 'reopen', id: 5 }), { id: 5, action: 'reopen' })
  assert.deepEqual(signalActionBody({ type: 'done', id: 5 }), { id: 5, action: 'done' })
})

test('snooze bodies keep the contract preset', () => {
  assert.deepEqual(signalActionBody({ type: 'snooze', id: 5, until: '30m' }), { id: 5, action: 'snooze', until: '30m' })
  assert.deepEqual(signalActionBody({ type: 'snooze', id: 5, until: 'next_open' }), { id: 5, action: 'snooze', until: 'next_open' })
})

test('invalid ids and presets never produce a body', () => {
  assert.equal(signalActionBody({ type: 'ack', id: 0 }), null)
  assert.equal(signalActionBody({ type: 'ack', id: -3 }), null)
  assert.equal(signalActionBody({ type: 'ack', id: 1.5 }), null)
  assert.equal(signalActionBody({ type: 'snooze', id: 5, until: '45m' as never }), null)
})

test('isSignalActionType accepts the six contract actions only', () => {
  for (const action of ['ack', 'ignore', 'snooze', 'unsnooze', 'done', 'reopen']) assert.equal(isSignalActionType(action), true, action)
  for (const action of ['delete', 'ACK', '', null]) assert.equal(isSignalActionType(action), false, String(action))
})

test('ack clears the new dot and keeps the card in the active list', () => {
  const next = optimisticSignals([signal()], { type: 'ack', id: 5 })
  assert.equal(next[0]!.status, 'seen')
})

test('ignore marks the card done', () => {
  const next = optimisticSignals([signal()], { type: 'ignore', id: 5 })
  assert.equal(next[0]!.status, 'done')
})

test('snooze stores a local until timestamp and the snoozed status', () => {
  const next = optimisticSignals([signal()], { type: 'snooze', id: 5, until: '30m' }, Date.parse('2026-11-03T10:00:00+08:00'))
  assert.equal(next[0]!.status, 'snoozed')
  assert.ok(next[0]!.snoozeUntil)
  assert.equal(Date.parse(next[0]!.snoozeUntil!), Date.parse('2026-11-03T10:30:00+08:00'))
})

test('reopen and unsnooze restore the card and clear its snooze stamp', () => {
  for (const action of [{ type: 'reopen', id: 5 }, { type: 'unsnooze', id: 5 }] as SignalAction[]) {
    const next = optimisticSignals([signal({ status: 'done', snoozeUntil: '2026-11-03T10:30:00.000Z' })], action)
    assert.equal(next[0]!.status, 'new')
    assert.equal(next[0]!.snoozeUntil, null)
  }
})

test('an action only touches the matching id', () => {
  const rows = [signal({ id: 1 }), signal({ id: 2 })]
  const next = optimisticSignals(rows, { type: 'ignore', id: 2 })
  assert.equal(next[0]!.status, 'new')
  assert.equal(next[1]!.status, 'done')
})

test('a successful action keeps the optimistic state', async () => {
  const calls: unknown[] = []
  const outcome = await performSignalAction([signal()], { type: 'ignore', id: 5 }, ports({ ok: true, code: null }, calls))
  assert.equal(outcome.ok, true)
  assert.equal(outcome.signals[0]!.status, 'done')
  assert.deepEqual(calls, [{ id: 5, action: 'ignore' }])
})

test('a rejected action rolls the list back to the exact snapshot', async () => {
  const before = [signal()]
  const outcome = await performSignalAction(before, { type: 'ignore', id: 5 }, ports({ ok: false, code: 'hub_error' }))
  assert.equal(outcome.ok, false)
  assert.equal(outcome.error, 'hub_error')
  assert.deepEqual(outcome.signals, before)
  assert.equal(outcome.signals[0]!.status, 'new')
})

test('a network throw rolls back and reports hub_unreachable', async () => {
  const before = [signal()]
  const outcome = await performSignalAction(before, { type: 'snooze', id: 5, until: 'close' }, {
    now: () => Date.now(),
    post: async () => { throw new TypeError('fetch failed') },
  })
  assert.equal(outcome.ok, false)
  assert.equal(outcome.error, 'hub_unreachable')
  assert.deepEqual(outcome.signals, before)
})

test('an invalid action never reaches the post port', async () => {
  const calls: unknown[] = []
  const outcome = await performSignalAction([signal()], { type: 'ack', id: 0 }, ports({ ok: true, code: null }, calls))
  assert.equal(outcome.ok, false)
  assert.equal(outcome.error, 'invalid_action')
  assert.equal(calls.length, 0)
})

test('primaryIntent routes open, plan, ack and ask primaries', () => {
  assert.deepEqual(primaryIntent(signal()), { kind: 'open' })
  assert.deepEqual(primaryIntent(signal({ primary: { label: '确认启用', action: 'confirm_plan' } })), { kind: 'plan', planId: 77 })
  assert.deepEqual(primaryIntent(signal({ primary: { label: '知道了', action: 'ack' } })), { kind: 'signal', action: { type: 'ack', id: 5 } })
  assert.deepEqual(primaryIntent(signal({ primary: { label: '研究', action: 'research' } })), { kind: 'ask' })
  assert.deepEqual(primaryIntent(signal({ primary: { label: '移出', action: 'remove_watch' } })), { kind: 'ask' })
})

test('confirm and cancel plan bodies carry nothing else', () => {
  assert.deepEqual(planActionBody(77, 'confirm'), { id: 77, action: 'confirm' })
  assert.deepEqual(planActionBody(77, 'cancel'), { id: 77, action: 'cancel' })
})

test('extend requires an ISO expiry and rejects malformed dates', () => {
  assert.deepEqual(planActionBody(77, 'extend', '2026-11-10T15:00:00+08:00'), { id: 77, action: 'extend', expires_at: '2026-11-10T15:00:00+08:00' })
  assert.equal(planActionBody(77, 'extend'), null)
  assert.equal(planActionBody(77, 'extend', 'not-a-date'), null)
  assert.equal(planActionBody(77, 'extend', '2026-11-10T15:00:00+08:00x'), null)
})

test('plan ids are positive 32-bit integers', () => {
  assert.equal(planActionBody(0, 'confirm'), null)
  assert.deepEqual(planActionBody(2 ** 31, 'confirm'), { id: 2 ** 31, action: 'confirm' })
  assert.equal(planActionBody(2 ** 31 + 1, 'confirm'), null)
  assert.deepEqual(planActionBody(2 ** 31 - 1, 'confirm'), { id: 2 ** 31 - 1, action: 'confirm' })
})

test('ignore offers an undo that reopens the card', () => {
  const toast = toastFor({ type: 'ignore', id: 5 }, 1)
  assert.ok(toast)
  assert.match(toast!.text, /已忽略/)
  assert.deepEqual(toast!.undo, { type: 'reopen', id: 5 })
})

test('snooze offers an undo that clears the snooze', () => {
  const toast = toastFor({ type: 'snooze', id: 5, until: 'close' }, 2)
  assert.ok(toast)
  assert.match(toast!.text, /收盘前/)
  assert.deepEqual(toast!.undo, { type: 'unsnooze', id: 5 })
})

test('ack and reopen produce no toast or no undo respectively', () => {
  assert.equal(toastFor({ type: 'ack', id: 5 }), null)
  const reopen = toastFor({ type: 'reopen', id: 5 }, 3)
  assert.ok(reopen)
  assert.equal(reopen!.undo, null)
})

test('snooze labels match the menu', () => {
  assert.equal(snoozeLabel('30m'), '30 分钟后')
  assert.equal(snoozeLabel('close'), '收盘前')
  assert.equal(snoozeLabel('next_open'), '明天开盘')
})

test('30m snooze resolves thirty minutes ahead', () => {
  const iso = presetIso('30m', Date.parse('2026-11-03T10:00:00+08:00'))
  assert.equal(Date.parse(iso), Date.parse('2026-11-03T10:30:00+08:00'))
})

test('close and next-open presets resolve to local 14:30 and 09:30', () => {
  const close = new Date(presetIso('close', Date.parse('2026-11-03T10:00:00+08:00')))
  assert.equal(close.getHours(), 14)
  assert.equal(close.getMinutes(), 30)
  const open = new Date(presetIso('next_open', Date.parse('2026-11-03T10:00:00+08:00')))
  assert.equal(open.getHours(), 9)
  assert.equal(open.getMinutes(), 30)
})

test('statusAfter mirrors the optimistic transition', () => {
  assert.equal(statusAfter({ type: 'ack', id: 1 }), 'seen')
  assert.equal(statusAfter({ type: 'ignore', id: 1 }), 'done')
  assert.equal(statusAfter({ type: 'snooze', id: 1, until: '30m' }), 'snoozed')
  assert.equal(statusAfter({ type: 'reopen', id: 1 }), 'new')
})

// Integration: whatever the client builds must pass the Host proxy's validator (a mismatch once made every card action fail).
test('every client action body is accepted by the hub proxy validator', async () => {
  const { validateSignalAction } = await import('../src/hubProxy.ts')
  const actions = [
    { type: 'ack', id: 5 }, { type: 'ignore', id: 5 }, { type: 'reopen', id: 5 }, { type: 'done', id: 5 }, { type: 'unsnooze', id: 5 },
    { type: 'snooze', id: 5, until: '30m' }, { type: 'snooze', id: 5, until: 'close' }, { type: 'snooze', id: 5, until: 'next_open' },
  ] as const
  for (const action of actions) {
    const body = signalActionBody(action as never)
    assert.ok(body, JSON.stringify(action))
    assert.notEqual(validateSignalAction(body), null, `proxy rejected ${JSON.stringify(body)}`)
  }
})
