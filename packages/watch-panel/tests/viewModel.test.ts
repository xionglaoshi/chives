import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  classifyHealth,
  classifySession,
  describeRule,
  formatAmount,
  formatClock,
  formatLag,
  formatPct,
  formatPrice,
  mergeAlerts,
  nextAfterId,
  quoteRows,
  ruleRows,
  sortAlerts,
} from '../src/client/viewModel.ts'

test('classifyHealth prefers stale and falls back to unreachable', () => {
  assert.equal(classifyHealth({ health: 'ok', stale: false }, false), 'ok')
  assert.equal(classifyHealth({ health: 'degraded' }, false), 'degraded')
  assert.equal(classifyHealth({ health: 'down' }, false), 'down')
  assert.equal(classifyHealth({ health: 'ok', stale: true }, false), 'stale')
  assert.equal(classifyHealth({ health: 'stale', stale: true }, false), 'stale')
  assert.equal(classifyHealth({ health: 'ok' }, true), 'unreachable')
  assert.equal(classifyHealth(null, false), 'unreachable')
  assert.equal(classifyHealth(undefined, true), 'unreachable')
  assert.equal(classifyHealth({ health: 'odd' }, false), 'unreachable')
})

test('classifySession accepts the five known sessions and rejects anything else', () => {
  for (const value of ['open', 'pre_open', 'break', 'after_hours', 'non_trading_day'] as const) {
    assert.equal(classifySession(value), value)
  }
  assert.equal(classifySession('lunch'), 'unknown')
  assert.equal(classifySession(''), 'unknown')
  assert.equal(classifySession(null), 'unknown')
  assert.equal(classifySession(undefined), 'unknown')
  assert.equal(classifySession(42), 'unknown')
})

test('formatLag renders seconds and minute forms', () => {
  assert.equal(formatLag(null), '\u2014')
  assert.equal(formatLag(undefined), '\u2014')
  assert.equal(formatLag(3), '3.0s')
  assert.equal(formatLag(0), '0.0s')
  assert.equal(formatLag(9.5), '9.5s')
  assert.equal(formatLag(-2), '0.0s')
  assert.equal(formatLag(40), '40s')
  assert.equal(formatLag(40.4), '40s')
  assert.equal(formatLag(59.6), '1m00s')
  assert.equal(formatLag(60), '1m00s')
  assert.equal(formatLag(125), '2m05s')
  assert.equal(formatLag(3600), '60m00s')
})

test('formatPct is signed, fixed width and unsigned when rounded to zero', () => {
  assert.equal(formatPct(3.1333), '+3.13%')
  assert.equal(formatPct(-0.5), '-0.50%')
  assert.equal(formatPct(0), '0.00%')
  assert.equal(formatPct(-0.004), '0.00%')
  assert.equal(formatPct(0.004), '0.00%')
  assert.equal(formatPct(2.5, 1), '+2.5%')
  assert.equal(formatPct(null), '\u2014')
  assert.equal(formatPct(NaN), '\u2014')
})

test('formatPrice keeps two decimals', () => {
  assert.equal(formatPrice(15.47), '15.47')
  assert.equal(formatPrice(15), '15.00')
  assert.equal(formatPrice(null), '\u2014')
  assert.equal(formatPrice(undefined), '\u2014')
})

test('formatAmount switches at 1e4 and 1e8', () => {
  assert.equal(formatAmount(12360530), '1236.05\u4e07')
  assert.equal(formatAmount(150000000), '1.50\u4ebf')
  assert.equal(formatAmount(99999999), '10000.00\u4e07')
  assert.equal(formatAmount(10000), '1.00\u4e07')
  assert.equal(formatAmount(9999), '9999\u5143')
  assert.equal(formatAmount(0), '0\u5143')
  assert.equal(formatAmount(null), '\u2014')
})

test('formatClock takes the time part without timezone conversion', () => {
  assert.equal(formatClock('2026-11-03T09:35:00+08:00'), '09:35:00')
  assert.equal(formatClock('2026-11-03T09:35:00.123456+08:00'), '09:35:00')
  assert.equal(formatClock('2026-11-03 09:35:00'), '\u2014')
  assert.equal(formatClock(null), '\u2014')
  assert.equal(formatClock(''), '\u2014')
  assert.equal(formatClock('garbage'), '\u2014')
})

test('sortAlerts sorts descending without mutating the input', () => {
  const input = [{ id: 1 }, { id: 3 }, { id: 2 }]
  assert.deepEqual(sortAlerts(input).map((row) => row.id), [3, 2, 1])
  assert.deepEqual(input.map((row) => row.id), [1, 3, 2])
  assert.deepEqual(sortAlerts(null), [])
})

test('mergeAlerts dedupes by id, incoming wins and the cap keeps the newest', () => {
  const merged = mergeAlerts([{ id: 1, value: 'a' }, { id: 2 }], [{ id: 2, value: 'b' }, { id: 3 }], 2)
  assert.deepEqual(merged.map((row) => row.id), [3, 2])
  assert.equal(merged[1]?.value, 'b')
  const big = mergeAlerts([], Array.from({ length: 250 }, (_, index) => ({ id: index + 1 })))
  assert.equal(big.length, 200)
  assert.equal(big[0]?.id, 250)
  assert.equal(big[199]?.id, 51)
})

test('nextAfterId returns zero for an empty list', () => {
  assert.equal(nextAfterId([]), 0)
  assert.equal(nextAfterId(null), 0)
  assert.equal(nextAfterId([{ id: 4 }, { id: 9 }, { id: 2 }]), 9)
})

test('quoteRows maps fields, sorts by code and appends missing rows', () => {
  const quote = {
    name: '宁德时代',
    price: 15.47,
    prev_close: 15,
    open: 15,
    high: 15.6,
    low: 15,
    volume_lots: 7990,
    amount_yuan: 12360530,
    exch_time: '2026-11-03T09:41:39+08:00',
    limit_up: 16.5,
    limit_down: 13.5,
    change_pct: 3.1333,
    vwap: 15.47,
    vwap_dev_pct: 0.5,
  }
  const rows = quoteRows({
    quotes: { '300750.SZ': quote, '002553.SZ': { ...quote, name: '南方精工' } },
    missing: ['600000.SH'],
  })
  assert.deepEqual(rows.map((row) => row.code), ['002553.SZ', '300750.SZ', '600000.SH'])
  assert.equal(rows[0]?.name, '南方精工')
  assert.equal(rows[0]?.changePct, 3.1333)
  assert.equal(rows[0]?.vwapDevPct, 0.5)
  assert.equal(rows[0]?.amountYuan, 12360530)
  assert.equal(rows[0]?.missing, false)
  assert.equal(rows[2]?.missing, true)
  assert.equal(rows[2]?.name, '')
  assert.equal(rows[2]?.price, null)
  assert.equal(rows[2]?.high, null)
  assert.deepEqual(quoteRows(null), [])
  assert.deepEqual(quoteRows({}), [])
})

test('describeRule covers every rule type and the unknown fallback', () => {
  assert.equal(describeRule({ id: 'a', type: 'pct_change', direction: 'up', threshold_pct: 3 }), '涨幅 ≥ 3%')
  assert.equal(describeRule({ id: 'a', type: 'pct_change', direction: 'down', threshold_pct: 2.5 }), '跌幅 ≥ 2.5%')
  assert.equal(describeRule({ id: 'a', type: 'vwap_deviation', threshold_pct: 2 }), '偏离 VWAP ≥ 2%')
  assert.equal(describeRule({ id: 'a', type: 'limit_proximity', side: 'up', within_pct: 0.5 }), '距涨停 ≤ 0.5%')
  assert.equal(describeRule({ id: 'a', type: 'limit_proximity', side: 'down', within_pct: 0.5 }), '距跌停 ≤ 0.5%')
  assert.equal(describeRule({ id: 'a', type: 'price_cross', level: 16, direction: 'up' }), '上穿 16.00')
  assert.equal(describeRule({ id: 'a', type: 'price_cross', level: 15.5, direction: 'down' }), '下穿 15.50')
  assert.equal(describeRule({ id: 'a', type: 'volume_surge', window_seconds: 60, multiple: 3 }), '60 秒放量 ≥ 3 倍')
  assert.equal(describeRule({ id: 'a', type: 'weird' }), 'weird')
})

test('ruleRows keeps engine order and falls back to the rule id', () => {
  const state = {
    rules: [
      { code: '300750.SZ', rule_id: 'cross_16', armed: false, last_fired: '2026-11-03T09:40:03+08:00', fired_count: 2 },
      { code: '002553.SZ', rule_id: 'pct_up_3', armed: true, last_fired: null, fired_count: 0 },
      { code: '002553.SZ', rule_id: 'gone', armed: true, last_fired: null, fired_count: 0 },
    ],
  }
  const config = {
    rules: [
      { id: 'pct_up_3', type: 'pct_change', direction: 'up', threshold_pct: 3 },
      { id: 'cross_16', type: 'price_cross', level: 16, direction: 'up' },
    ],
    count: 2,
  }
  const rows = ruleRows(state, config)
  assert.deepEqual(rows.map((row) => row.ruleId), ['cross_16', 'pct_up_3', 'gone'])
  assert.equal(rows[0]?.description, '上穿 16.00')
  assert.equal(rows[0]?.armed, false)
  assert.equal(rows[0]?.firedCount, 2)
  assert.equal(rows[1]?.description, '涨幅 ≥ 3%')
  assert.equal(rows[2]?.description, 'gone')
  assert.deepEqual(ruleRows(null, config), [])
  assert.deepEqual(ruleRows(state, null), [])
})

test('continuesFrom: same newest alert continues; restarted ids do not', async () => {
  const { continuesFrom } = await import('../src/client/viewModel.ts')
  const known = { id: 7, ts: '2026-11-03T09:35:00+08:00', dedupe_key: 'a|r|7' }
  assert.equal(continuesFrom(null, []), true)
  assert.equal(continuesFrom(known, [known, { id: 8 }]), true)
  assert.equal(continuesFrom(known, []), false)
  assert.equal(continuesFrom(known, [{ id: 7, ts: '2026-11-04T09:31:00+08:00', dedupe_key: 'a|r|7' }]), false)
  assert.equal(continuesFrom(known, [{ id: 1, ts: '2026-11-04T09:31:00+08:00' }]), false)
})
