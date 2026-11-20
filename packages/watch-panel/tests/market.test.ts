import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DASH,
  DOWN_SYMBOL,
  UP_SYMBOL,
  buildTimeline,
  direction,
  directionSymbol,
  distanceToLimit,
  avatarGlyph,
  avatarTone,
  divergingColor,
  heatFill,
  heatTier,
  tileFontScale,
  filterObjects,
  filterRules,
  filterTimeline,
  formatMoney,
  formatMove,
  formatStamp,
  marketAlertStatus,
  marketPulse,
  marketRuleName,
  isSectorCode,
  marketRuleParams,
  maxAbsChange,
  missingReason,
  newTimelineKeys,
  normalizeMarketAlerts,
  normalizeMarketHealth,
  normalizeMarketRules,
  normalizeMembers,
  normalizeOverview,
  normalizeSectorDetail,
  normalizeSectors,
  rankArrow,
  timelineNovelty,
  topBottomSectors,
  watchAlertStatus,
} from '../src/client/market.ts'

test('formatMoney switches yuan, wan and yi with an explicit unit', () => {
  assert.equal(formatMoney(999), '999 \u5143')
  assert.equal(formatMoney(10_000), '1.00 \u4e07\u5143')
  assert.equal(formatMoney(123_605_300), '1.24 \u4ebf\u5143')
  assert.equal(formatMoney(-12_000), '-1.20 \u4e07\u5143')
  assert.equal(formatMoney(null), DASH)
  assert.equal(formatMoney(Number.NaN), DASH)
})

test('formatMove carries a direction glyph and a percent sign', () => {
  assert.equal(formatMove(2.345), `${UP_SYMBOL} +2.35%`)
  assert.equal(formatMove(-0.5), `${DOWN_SYMBOL} -0.50%`)
  assert.equal(formatMove(0), '0.00%')
  assert.equal(formatMove(null), DASH)
})

test('direction and directionSymbol keep zero neutral', () => {
  assert.equal(direction(1), 'up')
  assert.equal(direction(-1), 'down')
  assert.equal(direction(0), 'flat')
  assert.equal(direction(null), 'flat')
  assert.equal(directionSymbol(2), UP_SYMBOL)
  assert.equal(directionSymbol(-2), DOWN_SYMBOL)
  assert.equal(directionSymbol(0), DASH)
})

test('divergingColor is tiered: fixed absolute edges, neutral midpoint, token color-mix', () => {
  assert.equal(divergingColor(0, 5), 'var(--chives-diverging-mid)')
  assert.equal(divergingColor(null, 5), 'var(--chives-diverging-mid)')
  assert.equal(divergingColor(0.2, 5), 'var(--chives-diverging-mid)')
  assert.match(divergingColor(0.5, 5), /chives-up\) 28%/)
  assert.match(divergingColor(1.5, 5), /chives-up\) 48%/)
  assert.match(divergingColor(2.5, 5), /chives-up\) 70%/)
  assert.match(divergingColor(9, 5), /chives-up\) 92%/)
  assert.match(divergingColor(-1, 5), /chives-down\) 48%/)
  assert.equal(divergingColor(2.5, 5), divergingColor(2.5, 50), 'maxAbs no longer changes the fill')
})

test('heatTier edges and heatFill', () => {
  assert.deepEqual([0, 0.29, 0.3, 0.99, 1, 1.99, 2, 2.99, 3, 8].map(heatTier), [0, 0, 1, 1, 2, 2, 3, 3, 4, 4])
  assert.equal(heatTier(null), 0)
  assert.equal(heatTier(-3.2), 4)
  assert.equal(heatFill(0, 'up'), 'var(--chives-diverging-mid)')
  assert.match(heatFill(4, 'down'), /chives-down\) 92%/)
})

test('tileFontScale grows with the tile, keeps the name, drops move then amount', () => {
  const big = tileFontScale(400, 300), mid = tileFontScale(160, 100), tiny = tileFontScale(50, 30)
  assert.ok(big.cqw > mid.cqw)
  assert.equal(big.showText, true)
  assert.equal(tiny.showText, true)
  assert.equal(big.showMove, true)
  assert.equal(tiny.showMove, false)
  assert.equal(mid.showAmount, true)
  assert.equal(tileFontScale(100, 60).showAmount, false)
  assert.ok(big.cqw <= 2.6 && tiny.cqw >= 1.05)
})

test('avatarTone is stable and avatarGlyph skips ST/N prefixes', () => {
  assert.equal(avatarTone('002553.SZ'), avatarTone('002553.SZ'))
  assert.ok([0, 1, 2, 3, 4, 5].includes(avatarTone('601099.SH')))
  assert.equal(avatarGlyph('南方精工'), '南')
  assert.equal(avatarGlyph('*ST开元'), '开')
  assert.equal(avatarGlyph('N皇冠新材'), '皇')
  assert.equal(avatarGlyph(''), '?')
})

test('distanceToLimit picks the nearer limit and never goes negative', () => {
  assert.deepEqual(distanceToLimit(10, 11, 9), { side: 'up', pct: 10 })
  assert.equal(distanceToLimit(10, 13, 9.8).side, 'down')
  assert.ok(Math.abs(distanceToLimit(10, 13, 9.8).pct! - 2) < 1e-9)
  assert.deepEqual(distanceToLimit(10, 11, null), { side: 'up', pct: 10 })
  assert.deepEqual(distanceToLimit(10, null, 9), { side: 'down', pct: 10 })
  assert.deepEqual(distanceToLimit(10, 9, 11), { side: 'up', pct: 0 })
  assert.deepEqual(distanceToLimit(0, 11, 9), { side: null, pct: null })
  assert.deepEqual(distanceToLimit(null, 11, 9), { side: null, pct: null })
})

test('rankArrow treats a positive delta as a move up', () => {
  assert.deepEqual(rankArrow(3), { direction: 'up', symbol: UP_SYMBOL })
  assert.deepEqual(rankArrow(-2), { direction: 'down', symbol: DOWN_SYMBOL })
  assert.deepEqual(rankArrow(0), { direction: 'flat', symbol: DASH })
  assert.deepEqual(rankArrow(null), { direction: 'flat', symbol: DASH })
})

test('formatStamp keeps the source timezone and omits the year', () => {
  assert.equal(formatStamp('2026-11-03T14:57:31+08:00'), '11-03 14:57:31')
  assert.equal(formatStamp('nope'), DASH)
  assert.equal(formatStamp(null), DASH)
})

test('normalizeOverview extracts indexes, breadth and regime safely', () => {
  const overview = normalizeOverview({
    ok: true,
    as_of: '2026-11-03T14:57:31+08:00',
    trading_state: 'open',
    indexes: [{ code: '000001.SH', name: '\u4e0a\u8bc1', price: 3300, change_pct: 1.2, amount_yuan: 1e8, spark: [{ t: '09:30', p: 1 }, { t: '09:31', p: 2 }], stale: false }],
    breadth: { up: 3000, down: 2000, flat: 100, up_ratio: 0.6, limit_up: 50, limit_down: 2, broken: 5, seal_ratio: 0.9, max_streak: 4, amount_yuan: 9e11, stale: true, reason: 'late' },
    regime: { label: 'risk_on', reasons: ['breadth good'] },
  })
  assert.equal(overview.ok, true)
  assert.equal(overview.tradingState, 'open')
  assert.equal(overview.indexes[0]!.code, '000001.SH')
  assert.equal(overview.indexes[0]!.spark.length, 2)
  assert.equal(overview.breadth.up, 3000)
  assert.equal(overview.breadth.stale, true)
  assert.equal(overview.regime.label, 'risk_on')
  assert.deepEqual(overview.regime.reasons, ['breadth good'])
})

test('normalizeOverview keeps the closed-session state_note separate from stale', () => {
  const overview = normalizeOverview({
    ok: true,
    as_of: '2026-11-03T15:00:00+08:00',
    trading_state: 'closed',
    state_note: '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c',
    indexes: [{ code: '000001.SH', name: 'x', stale: false }],
    breadth: { up: 1, stale: false },
  })
  assert.equal(overview.tradingState, 'closed')
  assert.equal(overview.stateNote, '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c')
  assert.equal(overview.indexes[0]!.stale, false)
  assert.equal(normalizeOverview({ trading_state: 'open', state_note: '   ' }).stateNote, null)
})

test('normalizeOverview tolerates an error payload and unknown values', () => {
  const overview = normalizeOverview({ ok: false, error: { code: 'engine_unreachable' }, trading_state: 'weird' })
  assert.equal(overview.ok, false)
  assert.equal(overview.error, 'engine_unreachable')
  assert.equal(overview.tradingState, 'unknown')
  assert.deepEqual(overview.indexes, [])
  assert.equal(overview.breadth.up, null)
  assert.equal(overview.regime.label, 'unknown')
})

test('normalizeSectors marks small industries and keeps leaders', () => {
  const payload = normalizeSectors({
    ok: true,
    as_of: '2026-11-03T14:57:31+08:00',
    rows: [{
      code: 'BK0433', name: '\u519c\u6797\u7267\u6e14', change_pct: 2.1, amount_yuan: 5e9,
      amount_share_ratio: 0.03, rel_300_pct: 1.5, up_count: 30, down_count: 5, limit_up_count: 2,
      member_count: 40, rank: 3, rank_change_30m: 2, leaders: [{ code: '000001', name: 'x', change_pct: 9 }],
      laggards: [], as_of: '2026-11-03T14:57:00+08:00', stale: true,
    }, { code: 'BK0434', name: '\u91c7\u6398', change_pct: 8, member_count: 4 }],
  })
  assert.equal(payload.ok, true)
  assert.equal(payload.rows.length, 2)
  assert.equal(payload.rows[0]!.rel300Pct, 1.5)
  assert.equal(payload.rows[0]!.leaders[0]!.name, 'x')
  assert.equal(payload.rows[0]!.small, false)
  assert.equal(payload.rows[1]!.small, true)
  assert.equal(payload.rows[0]!.stale, true)
})

test('normalizeSectors keeps the state_note and client sector ids stay BK-only', () => {
  const payload = normalizeSectors({ ok: true, state_note: '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c', rows: [{ code: 'BK0433', name: 'x' }] })
  assert.equal(payload.stateNote, '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c')
  assert.equal(isSectorCode('BK0433'), true)
  assert.equal(isSectorCode('801010'), false)
  assert.equal(isSectorCode('bk0433'), false)
  assert.equal(isSectorCode('BK12345'), false)
})

test('normalizeSectorDetail merges history and trend points', () => {
  const detail = normalizeSectorDetail({
    code: 'BK0433', name: 'x', change_pct: 1.2, member_count: 20,
    state_note: '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c',
    trend: [{ t: '09:30', change_pct: 0.1 }, { t: '09:31', change_pct: 0.2 }],
    history: { ret_5d_pct: 3.4, ret_20d_pct: -1.2, rank_5d: 4, rank_20d: 9 },
  })
  assert.equal(detail.history.ret5dPct, 3.4)
  assert.equal(detail.history.rank20d, 9)
  assert.equal(detail.trend.length, 2)
  assert.equal(detail.stateNote, '\u4f11\u5e02\uff0c\u663e\u793a\u4e0a\u4e00\u4ea4\u6613\u65f6\u6bb5\u6700\u540e\u503c')
})

test('normalizeMembers keeps numeric fields and limit flags', () => {
  const rows = normalizeMembers({ rows: [{ code: '600000', name: 'x', price: 10, change_pct: 1, amount_yuan: 1e7, weight_pct: 2.2, limit_up: true }] })
  assert.equal(rows[0]!.weightPct, 2.2)
  assert.equal(rows[0]!.limitUp, true)
  assert.equal(rows[0]!.limitDown, false)
})

test('normalizeMarketRules exposes id, name, params and thresholds', () => {
  const rules = normalizeMarketRules({ rules: [{ id: 'R1', name: '\u6307\u6570\u653e\u91cf\u4e0b\u8dcc', enabled: true, params: { r_idx: -1, vr: 1.5 }, confirm: 2, cooldown_minutes: 60, level: 'L2' }] })
  assert.equal(rules[0]!.id, 'R1')
  assert.equal(rules[0]!.confirm, 2)
  assert.equal(marketRuleName(rules[0]!), '\u6307\u6570\u653e\u91cf\u4e0b\u8dcc')
  assert.equal(marketRuleParams(rules[0]!), 'r_idx=-1 \u00b7 vr=1.5')
})

test('normalizeMarketAlerts drops malformed rows and keeps object fields', () => {
  const payload = normalizeMarketAlerts({
    ok: true,
    alerts: [
      { id: 4, ts: '2026-11-03T10:00:00+08:00', rule_id: 'R3', object: { type: 'sector', code: 'BK0433', name: 'x' }, severity: 'L1', title: 't', status: 'new', analysis_id: 7 },
      { id: 'bad' },
    ],
    next_id: 5,
  })
  assert.equal(payload.alerts.length, 1)
  assert.equal(payload.alerts[0]!.objectType, 'sector')
  assert.equal(payload.alerts[0]!.analysisId, 7)
  assert.equal(payload.nextId, 5)
  assert.equal(marketAlertStatus(payload.alerts[0]!), 'analyzing')
})

test('marketAlertStatus maps skipped and analyzed', () => {
  const base = { status: 'skipped', analysisId: null, payload: { reason: 'cooldown' }, raw: {} }
  assert.equal(marketAlertStatus({ ...base, id: 1, ts: null, ruleId: '', objectType: 'stock', objectCode: '', objectName: '', severity: null, title: '', detail: '' } as never), 'skipped')
  assert.equal(watchAlertStatus({ alert_id: 1, status: 'done' }), 'analyzed')
  assert.equal(watchAlertStatus({ alert_id: 1, status: 'skipped', reason: 'cooldown' }), 'skipped')
  assert.equal(watchAlertStatus({ alert_id: 1, status: 'failed' }), 'failed')
  assert.equal(watchAlertStatus(undefined), 'pending')
})

test('buildTimeline merges both engines newest-first and keys by source', () => {
  const items = buildTimeline(
    [{ id: 2, ts: '2026-11-03T10:00:00+08:00', code: '600000', name: '\u6d66\u53d1', rule_id: 'pct_up_3', price: 10, change_pct: 3 }],
    [{ id: 2, ts: '2026-11-03T10:05:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0433', objectName: '\u519c\u6797', severity: 'L1', title: 't', detail: 'd', status: 'new', analysisId: null, payload: {}, raw: {} }],
    [],
  )
  assert.deepEqual(items.map((item) => item.key), ['market:2', 'watch:2'])
  assert.equal(items[0]!.title, 't')
  assert.equal(items[1]!.status, 'pending')
})

test('buildTimeline shows the skip reason only for skipped records', () => {
  const items = buildTimeline(
    [{ id: 1, ts: '2026-11-03T10:00:00+08:00', code: '600000', name: 'x', rule_id: 'r' }, { id: 2, ts: '2026-11-03T10:01:00+08:00', code: '600001', name: 'y', rule_id: 'r' }],
    [],
    [{ alert_id: 1, status: 'skipped', reason: 'cooldown' }, { alert_id: 2, status: 'done' }],
  )
  const skipped = items.find((item) => item.id === 1)!
  assert.equal(skipped.status, 'skipped')
  assert.equal(skipped.reason, 'cooldown')
  assert.equal(items.find((item) => item.id === 2)!.status, 'analyzed')
})

test('filterTimeline filters by rule and object and keeps the rest', () => {
  const items = buildTimeline(
    [{ id: 1, ts: '2026-11-03T10:00:00+08:00', code: '600000', name: 'x', rule_id: 'a' }],
    [{ id: 2, ts: '2026-11-03T10:01:00+08:00', ruleId: 'R1', objectType: 'sector', objectCode: 'BK0433', objectName: 'y', severity: 'L1', title: 't', detail: '', status: 'new', analysisId: null, payload: {}, raw: {} }],
    [],
  )
  assert.equal(filterTimeline(items, { rule: 'R1', object: '' }).length, 1)
  assert.equal(filterTimeline(items, { rule: '', object: 'stock:600000' }).length, 1)
  assert.equal(filterTimeline(items, { rule: 'none', object: '' }).length, 0)
  assert.deepEqual(filterRules(items), ['R1', 'a'])
  assert.deepEqual(filterObjects(items).map((entry) => entry.key), ['sector:BK0433', 'stock:600000'])
})

test('newTimelineKeys reports only additions', () => {
  const items = buildTimeline([{ id: 1, ts: null, code: 'x', name: 'x', rule_id: 'r' }], [], [])
  assert.deepEqual(newTimelineKeys(new Set(), items), ['watch:1'])
  assert.deepEqual(newTimelineKeys(new Set(['watch:1']), items), [])
})

test('timelineNovelty waits for the first load and treats it as history', () => {
  const items = buildTimeline([{ id: 1, ts: null, code: 'x', name: 'x', rule_id: 'r' }], [], [])
  const early = timelineNovelty(null, items, false)
  assert.equal(early.known, null)
  assert.deepEqual(early.fresh, [])
  const first = timelineNovelty(null, items, true)
  assert.deepEqual(first.fresh, [])
  assert.deepEqual([...(first.known ?? [])], ['watch:1'])
})

test('timelineNovelty flags only alerts added after the baseline', () => {
  const first = buildTimeline([{ id: 1, ts: null, code: 'x', name: 'x', rule_id: 'r' }], [], [])
  const baseline = timelineNovelty(null, first, true)
  const later = buildTimeline([{ id: 1, ts: null, code: 'x', name: 'x', rule_id: 'r' }, { id: 2, ts: null, code: 'y', name: 'y', rule_id: 'r' }], [], [])
  const next = timelineNovelty(baseline.known, later, true)
  assert.deepEqual(next.fresh, ['watch:2'])
  assert.deepEqual([...(next.known ?? [])].sort(), ['watch:1', 'watch:2'])
  assert.deepEqual(timelineNovelty(next.known, later, true).fresh, [])
})

test('timelineNovelty baselines an empty first load so a later alert is new', () => {
  const empty = timelineNovelty(null, [], true)
  assert.deepEqual(empty.fresh, [])
  assert.deepEqual([...(empty.known ?? [])], [])
  const next = timelineNovelty(empty.known, buildTimeline([{ id: 7, ts: null, code: 'x', name: 'x', rule_id: 'r' }], [], []), true)
  assert.deepEqual(next.fresh, ['watch:7'])
})

test('topBottomSectors keeps five on each side and breaks ties by code', () => {
  const rows = Array.from({ length: 12 }, (_, index) => ({ code: `BK${String(index).padStart(4, '0')}`, name: `s${index}`, changePct: index - 6 }) as never)
  const { top, bottom } = topBottomSectors(rows, 5)
  assert.equal(top.length, 5)
  assert.equal(bottom.length, 5)
  assert.equal(top[0]!.changePct, 5)
  assert.equal(bottom[0]!.changePct, -2)
  assert.equal(bottom[4]!.changePct, -6)
})

test('maxAbsChange ignores null values', () => {
  assert.equal(maxAbsChange([{ changePct: 2 } as never, { changePct: -5 } as never, { changePct: null } as never]), 5)
  assert.equal(maxAbsChange([]), 0)
})

test('missingReason never invents a value', () => {
  assert.equal(missingReason(null), '\u6570\u636e\u672a\u63d0\u4f9b')
  assert.equal(missingReason(''), '\u6570\u636e\u672a\u63d0\u4f9b')
  assert.equal(missingReason('late'), 'late')
})

test('normalizeMarketHealth indexes sources and derives the three-state pulse', () => {
  const health = normalizeMarketHealth({
    ok: true,
    as_of: '2026-11-03T10:00:00+08:00',
    trading_state: 'open',
    sources: { tencent: { ok: true, age_s: 3 }, sw_l1: { ok: false, age_s: 900, last_error: 'x' } },
    rules: { enabled: ['R1', 'R3'] },
  })
  assert.equal(health.sources.sw_l1.ok, false)
  assert.deepEqual(health.enabledRules, ['R1', 'R3'])
  assert.equal(marketPulse(health, false), 'warn')
  assert.equal(marketPulse(null, true), 'unreachable')
  assert.equal(marketPulse({ ...health, tradingState: 'closed', sources: {} }, false), 'idle')
  assert.equal(marketPulse({ ...health, sources: {} }, false), 'healthy')
})
