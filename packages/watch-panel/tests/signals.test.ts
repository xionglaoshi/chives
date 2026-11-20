import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  activeSignals,
  compareSignals,
  conclusionText,
  directionMeta,
  doneRows,
  doneStats,
  fillPrompt,
  filterSignals,
  isSignalKind,
  isSignalStatus,
  isSnoozePreset,
  mergedLabel,
  normalizeSections,
  normalizeSignal,
  normalizeSignals,
  normalizeSignalDetail,
  partitionSignals,
  rangeGeometry,
  rankGeometry,
  recheckPrompt,
  removeWatchPrompt,
  researchPrompt,
  signalKindLabel,
  signalObjectLabel,
  signalTone,
  signalToneToken,
  SNOOZE_OPTIONS,
  sparkGeometry,
  type Signal,
  type SignalKind,
} from '../src/client/signals.ts'
import { latestSignalFor } from '../src/client/workbenchModel.ts'

function signal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 1,
    ts: '2026-11-03T10:12:00+08:00',
    kind: 'plan_entry',
    kindLabel: '计划触发 · 进场',
    decide: true,
    severity: 'L3',
    status: 'new',
    snoozeUntil: null,
    object: { type: 'stock', code: '002553.SZ', name: '南方精工' },
    title: '回到了你设的进场位',
    direction: 'bull',
    directionLabel: '偏多',
    conclusion: '现价 15.83 进入 15.60 – 15.85。',
    brief: '缩量回踩。',
    context: null,
    source: { label: '计划 P-0312', alertIds: [], analysisId: null, planId: 312, ruleId: null },
    mergedCount: 1,
    primary: { label: '查看分析', action: 'open' },
    detailAvailable: true,
    ...overrides,
  }
}

test('normalizeSignal reads the hub contract into camelCase fields', () => {
  const parsed = normalizeSignal({
    id: 7,
    ts: '2026-11-03T09:41:00+08:00',
    kind: 'risk',
    kind_label: '风险 · 市场',
    decide: true,
    severity: 'L2',
    status: 'seen',
    object: { type: 'market', code: '', name: '市场' },
    title: '宽度恶化',
    direction: 'bear',
    direction_label: '偏空',
    conclusion: '上涨占比 0.31',
    brief: '赚钱效应弱',
    context: { type: 'rank', from: 25, to: 3, share_pct: 4.1, spark: [1, 2, 3] },
    source: { label: 'R2', alert_ids: [1, 2], analysis_id: 9, plan_id: null, rule_id: 'R2' },
    merged_count: 4,
    primary: { label: '查看分析', action: 'open' },
    detail_available: true,
  })
  assert.ok(parsed)
  assert.equal(parsed.id, 7)
  assert.equal(parsed.kindLabel, '风险 · 市场')
  assert.equal(parsed.object.type, 'market')
  assert.equal(parsed.directionLabel, '偏空')
  assert.equal(parsed.mergedCount, 4)
  assert.equal(parsed.source.analysisId, 9)
  assert.equal(parsed.context?.type, 'rank')
  assert.equal(parsed.detailAvailable, true)
})

test('normalizeSignal rejects ids that cannot key a card', () => {
  for (const value of [null, {}, { id: 0 }, { id: -1 }, { id: 1.5 }, { id: '3' }, { id: Number.NaN }]) {
    assert.equal(normalizeSignal(value), null, JSON.stringify(value))
  }
})

test('normalizeSignal falls back to safe defaults for unknown contract values', () => {
  const parsed = normalizeSignal({ id: 3, kind: 'surprise', status: '???', direction: 'sideways' })
  assert.ok(parsed)
  assert.equal(parsed.kind, 'info')
  assert.equal(parsed.status, 'new')
  assert.equal(parsed.direction, 'neutral')
  assert.equal(parsed.decide, false)
  assert.equal(parsed.severity, null)
  assert.equal(parsed.mergedCount, 1)
  assert.equal(parsed.primary.action, 'open')
  assert.equal(parsed.context, null)
})

test('unknown context variants become null instead of throwing', () => {
  assert.equal(normalizeSignal({ id: 1, context: { type: 'radar' } })?.context, null)
  assert.equal(normalizeSignal({ id: 1, context: 'range' })?.context, null)
})

test('every kind maps to one of the five type colour families', () => {
  const expected: Record<SignalKind, string> = {
    plan_proposal: 'plan',
    plan_entry: 'plan',
    plan_giveup: 'plan',
    plan_other: 'plan',
    opportunity: 'opp',
    risk: 'risk',
    sector: 'sector',
    info: 'info',
  }
  for (const [kind, tone] of Object.entries(expected)) {
    assert.equal(signalTone(kind as SignalKind), tone, kind)
    assert.equal(signalToneToken(kind as SignalKind), `var(--chives-sig-${tone})`, kind)
  }
})

test('type colour families stay off the red/green up-down tokens', () => {
  for (const kind of ['plan_entry', 'opportunity', 'risk', 'sector', 'info'] as SignalKind[]) {
    const token = signalToneToken(kind)
    assert.doesNotMatch(token, /--chives-(up|down)\)/, kind)
  }
})

test('kind labels come from the hub when present and default otherwise', () => {
  assert.equal(signalKindLabel('plan_entry', ''), '计划触发 · 进场')
  assert.equal(signalKindLabel('risk', '风险 · 个股'), '风险 · 个股')
  assert.equal(signalKindLabel('info', '   '), '信息')
})

test('direction pills carry a glyph, a label and a tone', () => {
  assert.deepEqual(directionMeta('bull'), { tone: 'bull', glyph: '▲', label: '偏多' })
  assert.deepEqual(directionMeta('bear'), { tone: 'bear', glyph: '▼', label: '偏空' })
  assert.deepEqual(directionMeta('neutral'), { tone: 'flat', glyph: '—', label: '中性' })
  assert.equal(directionMeta('bull', '偏多（强）').label, '偏多（强）')
})

test('partition puts at most three decide signals in the hero area', () => {
  const signals = [
    signal({ id: 1, severity: 'L1', ts: '2026-11-03T10:00:00+08:00' }),
    signal({ id: 2, severity: 'L3', ts: '2026-11-03T09:00:00+08:00' }),
    signal({ id: 3, severity: 'L2', ts: '2026-11-03T11:00:00+08:00' }),
    signal({ id: 4, severity: 'L3', ts: '2026-11-03T10:30:00+08:00' }),
  ]
  const partition = partitionSignals(signals)
  assert.deepEqual(partition.decide.map((entry) => entry.id), [4, 2, 3])
  assert.deepEqual(partition.rail.map((entry) => entry.id), [1])
})

test('a fourth decide signal falls into the ordinary rail', () => {
  const signals = [1, 2, 3, 4].map((id) => signal({ id, severity: 'L2', ts: `2026-11-03T1${id}:00:00+08:00` }))
  const partition = partitionSignals(signals)
  assert.equal(partition.decide.length, 3)
  assert.deepEqual(partition.rail.map((entry) => entry.id), [1])
})

test('non-decide signals never enter the hero area', () => {
  const partition = partitionSignals([signal({ id: 1, decide: false })])
  assert.deepEqual(partition.decide, [])
  assert.deepEqual(partition.rail.map((entry) => entry.id), [1])
})

test('done, ignored and snoozed cards stay out of both active lists', () => {
  const partition = partitionSignals([
    signal({ id: 1, status: 'done' }),
    signal({ id: 2, status: 'ignored' }),
    signal({ id: 3, status: 'snoozed' }),
    signal({ id: 4, status: 'seen' }),
  ])
  assert.deepEqual(partition.decide.map((entry) => entry.id), [4])
  assert.deepEqual(partition.rail, [])
})

test('activeSignals keeps new and seen only', () => {
  const rows = activeSignals([
    signal({ id: 1, status: 'new' }),
    signal({ id: 2, status: 'seen' }),
    signal({ id: 3, status: 'done' }),
    signal({ id: 4, status: 'snoozed' }),
  ])
  assert.deepEqual(rows.map((entry) => entry.id), [1, 2])
})

test('compareSignals orders by severity, then newest, then id', () => {
  const rows = [
    signal({ id: 1, severity: 'L1', ts: '2026-11-03T12:00:00+08:00' }),
    signal({ id: 2, severity: 'L3', ts: '2026-11-03T09:00:00+08:00' }),
    signal({ id: 3, severity: 'L3', ts: '2026-11-03T10:00:00+08:00' }),
    signal({ id: 4, severity: null, ts: '2026-11-03T11:00:00+08:00' }),
  ].sort(compareSignals)
  assert.deepEqual(rows.map((row) => row.id), [3, 2, 1, 4])
  assert.ok(compareSignals(signal({ id: 5, ts: null }), signal({ id: 6, ts: '2026-11-03T10:00:00+08:00' })) > 0)
})

test('filterSignals implements all, decide, my stocks and sectors', () => {
  const rows = [
    signal({ id: 1, decide: true }),
    signal({ id: 2, decide: false, object: { type: 'sector', code: 'BK0433', name: '农林牧渔' } }),
    signal({ id: 3, decide: false, object: { type: 'market', code: '', name: '市场' } }),
  ]
  assert.deepEqual(filterSignals(rows, 'all').map((row) => row.id), [1, 2, 3])
  assert.deepEqual(filterSignals(rows, 'decide').map((row) => row.id), [1])
  assert.deepEqual(filterSignals(rows, 'stock').map((row) => row.id), [1])
  assert.deepEqual(filterSignals(rows, 'sector').map((row) => row.id), [2])
})

test('doneStats counts handled cards and the extra merged events', () => {
  const stats = doneStats([
    signal({ id: 1, status: 'done', mergedCount: 3 }),
    signal({ id: 2, status: 'ignored', mergedCount: 1 }),
    signal({ id: 3, status: 'new', mergedCount: 9 }),
  ])
  assert.deepEqual(stats, { count: 2, merged: 2 })
})

test('doneRows returns the newest handled cards capped at twenty', () => {
  const rows = Array.from({ length: 25 }, (_, index) => signal({
    id: index + 1,
    status: 'done',
    severity: 'L1',
    ts: `2026-11-03T${String(index % 10).padStart(2, '0')}:00:00+08:00`,
  }))
  assert.equal(doneRows(rows).length, 20)
  const ordered = doneRows([
    signal({ id: 1, status: 'done', severity: 'L3', ts: '2026-11-03T09:00:00+08:00' }),
    signal({ id: 2, status: 'done', severity: 'L1', ts: '2026-11-03T11:00:00+08:00' }),
  ])
  assert.deepEqual(ordered.map((row) => row.id), [2, 1])
  assert.equal(doneRows([signal({ id: 1, status: 'new' })]).length, 0)
})

test('range geometry places the zone, marker and price on the track', () => {
  const geometry = rangeGeometry({ type: 'range', levelLo: 15.6, levelHi: 15.85, stop: 14.5, price: 15.83, min: 14.2, max: 16.3, giveup: false })
  assert.equal(geometry.label, '现价 vs 进场区间')
  assert.ok(Math.abs(geometry.zoneLeft! - 66.67) < 0.1)
  assert.ok(Math.abs(geometry.zoneWidth! - 11.9) < 0.2)
  assert.ok(Math.abs(geometry.markerLeft! - 14.29) < 0.1)
  assert.ok(Math.abs(geometry.priceLeft - 77.62) < 0.1)
  assert.equal(geometry.priceText, '15.83')
  assert.match(geometry.markerText, /止损 14\.50/)
  assert.match(geometry.zoneText, /15\.60 – 15\.85/)
})

test('give-up geometry uses the lower level as marker and drops the zone', () => {
  const geometry = rangeGeometry({ type: 'range', levelLo: 3.5, levelHi: 3.5, stop: 3.4, price: 3.47, min: 3.35, max: 3.7, giveup: true })
  assert.equal(geometry.giveup, true)
  assert.equal(geometry.zoneLeft, null)
  assert.equal(geometry.zoneWidth, null)
  assert.equal(geometry.zoneText, '')
  assert.match(geometry.markerText, /放弃位 3\.50/)
})

test('out-of-range prices clamp to the ends instead of leaving the track', () => {
  const low = rangeGeometry({ type: 'range', levelLo: 10, levelHi: 11, stop: 9, price: 1, min: 9, max: 12, giveup: false })
  const high = rangeGeometry({ type: 'range', levelLo: 10, levelHi: 11, stop: 9, price: 99, min: 9, max: 12, giveup: false })
  assert.equal(low.priceLeft, 0)
  assert.equal(high.priceLeft, 100)
})

test('a degenerate range pins everything to the middle', () => {
  const geometry = rangeGeometry({ type: 'range', levelLo: 10, levelHi: 10, stop: null, price: 10, min: 10, max: 10, giveup: false })
  assert.equal(geometry.priceLeft, 50)
  assert.equal(geometry.markerLeft, null)
  assert.equal(geometry.zoneLeft, null)
})

test('missing price renders a dash and no dot position beyond zero', () => {
  const geometry = rangeGeometry({ type: 'range', levelLo: 10, levelHi: 11, stop: null, price: null, min: 9, max: 12, giveup: false })
  assert.equal(geometry.priceText, '—')
  assert.equal(geometry.priceLeft, 0)
})

test('rank geometry reports the move, the share and a spark path', () => {
  const geometry = rankGeometry({ type: 'rank', from: 25, to: 3, sharePct: 4.1, spark: [3, 4, 5, 7] })
  assert.equal(geometry.from, '25')
  assert.equal(geometry.to, '3')
  assert.equal(geometry.shareText, '4.1%')
  assert.ok(geometry.spark)
  assert.equal(geometry.spark!.count, 4)
  assert.match(geometry.spark!.path, /^M0\.0 /)
})

test('rank geometry copes with missing values and a short spark', () => {
  const geometry = rankGeometry({ type: 'rank', from: null, to: null, sharePct: null, spark: [1] })
  assert.equal(geometry.from, '—')
  assert.equal(geometry.shareText, '—')
  assert.equal(geometry.spark, null)
})

test('spark geometry keeps a flat series on the middle line', () => {
  const geometry = sparkGeometry([5, 5, 5])
  assert.ok(geometry)
  assert.equal(geometry!.path, 'M0.0 18.0 L50.0 18.0 L100.0 18.0')
})

test('spark geometry needs at least two finite points', () => {
  assert.equal(sparkGeometry([1]), null)
  assert.equal(sparkGeometry([1, Number.NaN]), null)
  assert.equal(sparkGeometry([]), null)
})

test('the snooze menu offers exactly the three contract presets', () => {
  assert.deepEqual(SNOOZE_OPTIONS.map((option) => option.value), ['30m', 'close', 'next_open'])
  assert.deepEqual(SNOOZE_OPTIONS.map((option) => option.label), ['30 分钟后', '收盘前', '明天开盘'])
  assert.equal(isSnoozePreset('30m'), true)
  assert.equal(isSnoozePreset('45m'), false)
  assert.equal(isSnoozePreset(null), false)
})

test('recheck, research and remove prompts quote the object and the event', () => {
  const entry = signal()
  assert.equal(recheckPrompt(entry), '请重新分析 南方精工（002553.SZ） 的信号：回到了你设的进场位')
  assert.match(researchPrompt(entry), /^帮我研究一下 南方精工（002553\.SZ） 的这个信号：/)
  assert.match(removeWatchPrompt(entry), /从自选和盯盘里移除/)
})

test('fillPrompt only fills for research and remove-watch primaries', () => {
  assert.equal(fillPrompt(signal()), null)
  assert.equal(fillPrompt(signal({ primary: { label: '知道了', action: 'ack' } })), null)
  assert.match(fillPrompt(signal({ primary: { label: '研究', action: 'research' } }))!, /帮我研究/)
  assert.match(fillPrompt(signal({ primary: { label: '移出', action: 'remove_watch' } }))!, /移除/)
})

test('mergedLabel only appears above one merged event', () => {
  assert.equal(mergedLabel(signal()), null)
  assert.equal(mergedLabel(signal({ mergedCount: 4 })), '已合并 4 条同类')
})

test('conclusionText prefers the conclusion, then the brief, then a dash', () => {
  assert.equal(conclusionText(signal()), '现价 15.83 进入 15.60 – 15.85。')
  assert.equal(conclusionText(signal({ conclusion: '  ', brief: '简析' })), '简析')
  assert.equal(conclusionText(signal({ conclusion: '', brief: '' })), '—')
})

test('signalObjectLabel joins a name and a code, never duplicating them', () => {
  assert.equal(signalObjectLabel(signal()), '南方精工（002553.SZ）')
  assert.equal(signalObjectLabel(signal({ object: { type: 'market', code: '', name: '市场' } })), '市场')
  assert.equal(signalObjectLabel(signal({ object: { type: 'stock', code: '600000', name: '600000' } })), '600000')
})

test('normalizeSignals reports counts, merged total and next id', () => {
  const payload = normalizeSignals({
    ok: true,
    as_of: '2026-11-03T10:00:00+08:00',
    counts: { decide: 2, active: 5, snoozed: 1, done: 12 },
    merged_today: 19,
    next_id: 44,
    signals: [{ id: 1 }, { id: 2, status: 'done' }],
  })
  assert.deepEqual(payload.counts, { decide: 2, active: 5, snoozed: 1, done: 12 })
  assert.equal(payload.mergedToday, 19)
  assert.equal(payload.nextId, 44)
  assert.equal(payload.signals.length, 2)
  assert.equal(payload.ok, true)
})

test('a hub business error keeps the payload shape and flags not-ok', () => {
  const payload = normalizeSignals({ ok: false, error: { code: 'db_locked' } })
  assert.equal(payload.ok, false)
  assert.equal(payload.error, 'db_locked')
  assert.deepEqual(payload.signals, [])
})

test('signal detail normalises the analysis sections and markdown', () => {
  const detail = normalizeSignalDetail({
    signal: { id: 1, title: 't' },
    analysis: {
      markdown: '## 结论\n\n正文',
      truncated: true,
      sections: { conclusion: '结论', direction: '偏多', points: ['一', { text: '二' }, ''], detail: '细节' },
    },
  }, null)
  assert.equal(detail.signal?.id, 1)
  assert.equal(detail.markdown, '## 结论\n\n正文')
  assert.equal(detail.truncated, true)
  assert.deepEqual(detail.sections.points, ['一', '二'])
})

test('signal detail falls back to the card when the payload has no signal', () => {
  const detail = normalizeSignalDetail({ analysis: { markdown: 'x' } }, signal({ id: 8 }))
  assert.equal(detail.signal?.id, 8)
  assert.equal(detail.markdown, 'x')
})

test('kind/status guards accept only contract values', () => {
  for (const kind of ['plan_proposal', 'plan_entry', 'plan_giveup', 'plan_other', 'sector', 'risk', 'opportunity', 'info']) {
    assert.equal(isSignalKind(kind), true, kind)
  }
  for (const kind of ['PLAN', 'entry', '', null, 1]) assert.equal(isSignalKind(kind), false, String(kind))
  for (const status of ['new', 'seen', 'snoozed', 'done', 'ignored']) assert.equal(isSignalStatus(status), true, status)
  assert.equal(isSignalStatus('archived'), false)
})

test('latestSignalFor matches the code and keeps the newest timestamp', () => {
  const rows = [
    signal({ id: 1, ts: '2026-11-03T09:00:00+08:00' }),
    signal({ id: 2, ts: '2026-11-03T10:00:00+08:00' }),
    signal({ id: 3, object: { type: 'sector', code: 'BK0433', name: '农林' } }),
  ]
  assert.equal(latestSignalFor(rows, '002553.SZ')?.id, 2)
  assert.equal(latestSignalFor(rows, '600000'), null)
  assert.equal(latestSignalFor(rows, ''), null)
  assert.equal(latestSignalFor(null, '002553.SZ'), null)
})

test('normalizeSection strips blank points and defaults to empty strings', () => {
  assert.deepEqual(normalizeSections({ points: ['a', '', 'b'] }), { conclusion: '', direction: '', points: ['a', 'b'], detail: '' })
  assert.deepEqual(normalizeSections(null), { conclusion: '', direction: '', points: [], detail: '' })
})
