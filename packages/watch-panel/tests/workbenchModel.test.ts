import assert from 'node:assert/strict'
import { test } from 'node:test'
import { buildTimeline } from '../src/client/market.ts'
import type { MarketAlert, SparkPoint, TimelineItem } from '../src/client/market.ts'
import type { QuoteRow } from '../src/client/viewModel.ts'
import {
  CLOSED_DRAWER,
  DEFAULT_MOVERS_FILTERS,
  MAX_ASK_LENGTH,
  aggregateTimeline,
  askContext,
  breadthSegments,
  buildFocusRows,
  columnOrder,
  composeAsk,
  drawerFromRef,
  drawerReducer,
  feedCollapsed,
  feedCounts,
  feedRows,
  filterFeed,
  focusEmphasis,
  indexColumns,
  latestMoverAsOf,
  layoutMode,
  marketAlertItem,
  miniPath,
  moverAmount,
  moverChange,
  moverPrice,
  moverTurnover,
  moversByKind,
  moversPath,
  moversQuery,
  normalizeMovers,
  normalizeSummary,
  preOpenFocusTitle,
  pulseCollapsed,
  relativeMinutes,
  relativeTime,
  reviewRows,
  searchAsk,
  sealRatioText,
  sectionOrder,
  SINGLE_SECTION_ORDER,
  sparkKind,
  watchAlertItem,
} from '../src/client/workbenchModel.ts'

const rawMovers = {
  ok: true,
  as_of: '2026-11-03T15:00:00+08:00',
  kind: 'losers',
  rows: [
    { rank: 1, code: '600000.SH', name: '浦发银行', price: 10.5, change_pct: -3.2, amount_yuan: 1.2e9, turnover_pct: 1.5, industry: '银行' },
    { rank: 2, code: '', name: 'bad row' },
  ],
  filters: { include_st: true, include_new: false, include_bj: true },
  source: 'eastmoney',
  stale: true,
  state_note: '休市',
  reason: 'partial',
}

test('normalizeMovers maps the contract, filters and drops rows without a code', () => {
  const parsed = normalizeMovers(rawMovers)
  assert.equal(parsed.ok, true)
  assert.equal(parsed.kind, 'losers')
  assert.equal(parsed.asOf, '2026-11-03T15:00:00+08:00')
  assert.equal(parsed.rows.length, 1)
  assert.deepEqual(parsed.rows[0], {
    rank: 1, code: '600000.SH', name: '浦发银行', price: 10.5, changePct: -3.2,
    amountYuan: 1.2e9, turnoverPct: 1.5, industry: '银行',
  })
  assert.deepEqual(parsed.filters, { includeSt: true, includeNew: false, includeBj: true })
  assert.equal(parsed.source, 'eastmoney')
  assert.equal(parsed.stale, true)
  assert.equal(parsed.stateNote, '休市')
  assert.equal(parsed.reason, 'partial')
})

test('normalizeMovers survives a business error and an unknown kind', () => {
  const parsed = normalizeMovers({ ok: false, error: { code: 'engine_unreachable' }, kind: 'weird', rows: [] })
  assert.equal(parsed.ok, false)
  assert.equal(parsed.error, 'engine_unreachable')
  assert.equal(parsed.kind, 'gainers')
  assert.deepEqual(parsed.rows, [])
  assert.deepEqual(parsed.filters, DEFAULT_MOVERS_FILTERS)
})

test('normalizeMovers rejects non-numeric fields without inventing values', () => {
  const parsed = normalizeMovers({ rows: [{ code: 'X', price: '10', change_pct: null, rank: 1.9 }] })
  assert.equal(parsed.rows[0]!.price, null)
  assert.equal(parsed.rows[0]!.changePct, null)
  assert.equal(parsed.rows[0]!.rank, 1)
})

test('moversQuery writes the whitelist in a stable order with 0/1 flags', () => {
  assert.equal(moversQuery('gainers', DEFAULT_MOVERS_FILTERS), 'kind=gainers&limit=8&include_st=0&include_new=0&include_bj=0')
  assert.equal(
    moversQuery('active', { includeSt: true, includeNew: true, includeBj: false }, 20),
    'kind=active&limit=20&include_st=1&include_new=1&include_bj=0',
  )
})

test('moversQuery clamps the limit into the 5-20 contract range', () => {
  assert.match(moversQuery('losers', DEFAULT_MOVERS_FILTERS, 1), /limit=5/)
  assert.match(moversQuery('losers', DEFAULT_MOVERS_FILTERS, 999), /limit=20/)
  assert.match(moversQuery('losers', DEFAULT_MOVERS_FILTERS, 7), /limit=7/)
  assert.match(moversQuery('losers', DEFAULT_MOVERS_FILTERS, Number.NaN), /limit=8/)
})

test('moversQuery ignores an unknown kind instead of forwarding it', () => {
  assert.match(moversQuery('bogus' as never, DEFAULT_MOVERS_FILTERS), /kind=gainers/)
})

test('moversPath targets the same-origin market route with a query', () => {
  assert.match(moversPath('gainers', DEFAULT_MOVERS_FILTERS), /^\/api\/market\/movers\?kind=gainers/)
})

test('normalizeSummary accepts only known tones and well-formed refs', () => {
  const parsed = normalizeSummary({
    ok: true,
    as_of: '2026-11-03T14:55:00+08:00',
    generated_by: 'engine',
    headlines: [
      { id: 'h1', tone: 'up', title: 'A', body: 'B', refs: [{ type: 'sector', code: 'BK0433', name: '农林牧渔' }, { type: 'bogus', code: 'x' }, { type: 'stock', code: '' }] },
      { id: '', tone: 'alarm', title: 'C', body: '' },
      { id: 'h3', title: '' },
    ],
    note: 'n',
    stale: true,
    reason: 'r',
  })
  assert.equal(parsed.headlines.length, 2)
  assert.equal(parsed.headlines[0]!.tone, 'up')
  assert.deepEqual(parsed.headlines[0]!.refs, [{ type: 'sector', code: 'BK0433', name: '农林牧渔' }])
  assert.equal(parsed.headlines[0]!.id, 'h1')
  assert.equal(parsed.headlines[1]!.tone, 'neutral')
  assert.equal(parsed.headlines[1]!.id, 'h2')
  assert.equal(parsed.generatedBy, 'engine')
  assert.equal(parsed.stale, true)
  assert.equal(parsed.reason, 'r')
})

test('normalizeSummary surfaces a business error', () => {
  const parsed = normalizeSummary({ ok: false, error: { code: 'no_data' } })
  assert.equal(parsed.ok, false)
  assert.equal(parsed.error, 'no_data')
  assert.deepEqual(parsed.headlines, [])
})

test('relativeMinutes and relativeTime use whole minutes and never go negative', () => {
  const now = Date.parse('2026-11-03T10:00:00+08:00')
  assert.equal(relativeMinutes('2026-11-03T09:59:40+08:00', now), 0)
  assert.equal(relativeMinutes('2026-11-03T09:35:00+08:00', now), 25)
  assert.equal(relativeMinutes('2026-11-03T10:01:00+08:00', now), null)
  assert.equal(relativeMinutes(null, now), null)
  assert.equal(relativeMinutes('not-a-date', now), null)
})

test('relativeTime renders 刚刚, minutes, hours and days', () => {
  const now = Date.parse('2026-11-03T12:00:00+08:00')
  assert.equal(relativeTime('2026-11-03T11:59:30+08:00', now), '刚刚')
  assert.equal(relativeTime('2026-11-03T11:55:00+08:00', now), '5 分钟前')
  assert.equal(relativeTime('2026-11-03T09:00:00+08:00', now), '3 小时前')
  assert.equal(relativeTime('2026-10-30T12:00:00+08:00', now), '4 天前')
  assert.equal(relativeTime(null, now), '—')
})

test('sparkKind accepts the two contract values and rejects everything else', () => {
  assert.equal(sparkKind('intraday'), 'intraday')
  assert.equal(sparkKind('daily'), 'daily')
  assert.equal(sparkKind('weekly'), null)
  assert.equal(sparkKind(undefined), null)
})

test('miniPath returns null for an empty or single-point series', () => {
  assert.equal(miniPath([]), null)
  assert.equal(miniPath([{ t: 'a', p: 1 }]), null)
  assert.equal(miniPath([{ t: 'a', p: Number.NaN }, { t: 'b', p: 2 }]), null)
})

test('miniPath draws a finite path from left to right and reports the last point', () => {
  const points: SparkPoint[] = [{ t: 'a', p: 1 }, { t: 'b', p: 3 }, { t: 'c', p: 2 }]
  const path = miniPath(points, 100, 40, 4)!
  assert.match(path.path, /^M0\.00 /)
  assert.match(path.path, /L100\.00 /)
  assert.equal(path.lastX, 100)
  assert.equal(path.count, 3)
  assert.ok(path.lastY >= 4 && path.lastY <= 36)
})

test('a flat series still produces a centre line instead of dividing by zero', () => {
  const path = miniPath([{ t: 'a', p: 5 }, { t: 'b', p: 5 }], 10, 10, 2)!
  assert.ok(Number.isFinite(path.lastY))
  assert.doesNotMatch(path.path, /NaN/)
})

test('layoutMode switches at the 1280px contract breakpoint', () => {
  assert.equal(layoutMode(1440), 'two-column')
  assert.equal(layoutMode(1280), 'two-column')
  assert.equal(layoutMode(1279), 'single')
  assert.equal(layoutMode(Number.NaN), 'single')
})

test('indexColumns keeps six cards from 1200px and three below', () => {
  assert.equal(indexColumns(1200), 6)
  assert.equal(indexColumns(1920), 6)
  assert.equal(indexColumns(1199), 3)
})

test('pulseCollapsed shrinks the band only after a real scroll', () => {
  assert.equal(pulseCollapsed(0), false)
  assert.equal(pulseCollapsed(48), false)
  assert.equal(pulseCollapsed(49), true)
})

test('section order brings the watchlist and feed first while trading', () => {
  assert.deepEqual(sectionOrder('open'), ['focus', 'feed', 'map', 'movers'])
  assert.deepEqual(sectionOrder('pre_open'), ['focus', 'map', 'movers', 'feed'])
  assert.deepEqual(sectionOrder('closed'), ['map', 'movers', 'focus', 'feed'])
  assert.deepEqual(sectionOrder('holiday'), ['map', 'movers', 'focus', 'feed'])
  assert.deepEqual(sectionOrder('lunch'), ['map', 'movers', 'focus', 'feed'])
  assert.deepEqual(sectionOrder('unknown'), ['map', 'movers', 'focus', 'feed'])
})

test('the T100 single-column order puts decided signals first and done last', () => {
  assert.deepEqual(SINGLE_SECTION_ORDER, { decide: 1, focus: 2, signals: 3, map: 4, movers: 5, flows: 6, done: 7 })
  assert.ok(SINGLE_SECTION_ORDER.decide < SINGLE_SECTION_ORDER.focus)
  assert.ok(SINGLE_SECTION_ORDER.flows < SINGLE_SECTION_ORDER.done)
})

test('columnOrder puts the personal column first only around the session', () => {
  assert.deepEqual(columnOrder('open'), ['mine', 'market'])
  assert.deepEqual(columnOrder('pre_open'), ['mine', 'market'])
  assert.deepEqual(columnOrder('closed'), ['market', 'mine'])
  assert.deepEqual(columnOrder('lunch'), ['market', 'mine'])
})

test('feedCollapsed and focusEmphasis follow the same trading state rules', () => {
  assert.equal(feedCollapsed('closed'), true)
  assert.equal(feedCollapsed('holiday'), true)
  assert.equal(feedCollapsed('open'), false)
  assert.equal(focusEmphasis('open'), true)
  assert.equal(focusEmphasis('pre_open'), true)
  assert.equal(focusEmphasis('closed'), false)
  assert.equal(preOpenFocusTitle('pre_open'), 'today')
  assert.equal(preOpenFocusTitle('open'), 'focus')
})

test('breadthSegments returns percentages that add up to 100', () => {
  const segments = breadthSegments(50, 30, 20)
  assert.equal(segments.total, 100)
  assert.ok(Math.abs(segments.up + segments.down + segments.flat - 100) < 1e-9)
  assert.equal(segments.up, 50)
})

test('an empty breadth is a neutral full bar rather than a division by zero', () => {
  assert.deepEqual(breadthSegments(null, null, null), { up: 0, down: 0, flat: 100, total: 0 })
})

test('sealRatioText renders a percentage or a dash', () => {
  assert.equal(sealRatioText(0.583), '58.3%')
  assert.equal(sealRatioText(null), '—')
})

test('the drawer state machine opens one target at a time', () => {
  let state = CLOSED_DRAWER
  state = drawerReducer(state, { type: 'open', kind: 'sector', code: 'BK0433' })
  assert.deepEqual(state, { kind: 'sector', code: 'BK0433', id: null })
  state = drawerReducer(state, { type: 'open', kind: 'stock', code: '600000' })
  assert.deepEqual(state, { kind: 'stock', code: '600000', id: null })
  state = drawerReducer(state, { type: 'close' })
  assert.deepEqual(state, CLOSED_DRAWER)
})

test('the drawer rejects malformed targets instead of rendering an empty panel', () => {
  assert.deepEqual(drawerReducer(CLOSED_DRAWER, { type: 'open', kind: 'sector', code: '801010' }), CLOSED_DRAWER)
  assert.deepEqual(drawerReducer(CLOSED_DRAWER, { type: 'open', kind: 'stock', code: '' }), CLOSED_DRAWER)
  assert.deepEqual(drawerReducer(CLOSED_DRAWER, { type: 'open', kind: 'analysis', id: 0 }), CLOSED_DRAWER)
  assert.deepEqual(drawerReducer(CLOSED_DRAWER, { type: 'open', kind: 'analysis', id: 1.5 }), CLOSED_DRAWER)
})

test('toggling the same target closes it, another target replaces it', () => {
  const open = drawerReducer(CLOSED_DRAWER, { type: 'open', kind: 'analysis', id: 7 })
  assert.deepEqual(drawerReducer(open, { type: 'toggle', kind: 'analysis', id: 7 }), CLOSED_DRAWER)
  assert.deepEqual(drawerReducer(open, { type: 'toggle', kind: 'analysis', id: 8 }), { kind: 'analysis', code: '', id: 8 })
})

test('summary refs map to the matching drawer kinds', () => {
  assert.deepEqual(drawerFromRef({ type: 'sector', code: 'BK0433', name: 'x' }), { kind: 'sector', code: 'BK0433', id: null })
  assert.deepEqual(drawerFromRef({ type: 'stock', code: '600000', name: 'x' }), { kind: 'stock', code: '600000', id: null })
  assert.deepEqual(drawerFromRef({ type: 'index', code: '000001.SH', name: 'x' }), { kind: 'index', code: '000001.SH', id: null })
})

const quote = (code: string, name: string, price: number, changePct: number): QuoteRow => ({
  code, name, price, changePct, vwap: null, vwapDevPct: null, high: null, low: null,
  limitUp: price * 1.1, limitDown: price * 0.9, amountYuan: 1e8, exchTime: null, missing: false,
})

const alertItem = (id: number, code: string, ts: string, ruleId = 'pct_up_3'): TimelineItem => buildTimeline(
  [{ id, ts, code, name: code, rule_id: ruleId }], [], [],
)[0]!

test('buildFocusRows joins quotes, limits, armed rules and the newest alert line', () => {
  const rows = buildFocusRows(
    [quote('600000', '浦发银行', 10, 2)],
    new Map([['600000', [{ ruleId: 'pct_up_3', description: '涨幅 ≥ 3%', armed: true, fired: true }]]]),
    [alertItem(2, '600000', '2026-11-03T14:50:00+08:00'), alertItem(1, '600000', '2026-11-03T10:00:00+08:00')],
    true,
  )
  assert.equal(rows.length, 1)
  assert.equal(rows[0]!.name, '浦发银行')
  assert.equal(rows[0]!.limit.side, 'up')
  assert.equal(rows[0]!.rules[0]!.ruleId, 'pct_up_3')
  assert.equal(rows[0]!.latest!.key, 'watch:2')
})

test('while trading, triggered stocks move to the top and keep their relative order', () => {
  const rows = buildFocusRows(
    [quote('A', '甲', 10, 1), quote('B', '乙', 10, 2), quote('C', '丙', 10, 3)],
    new Map([['C', [{ ruleId: 'r', description: 'd', armed: true, fired: true }]]]),
    [],
    true,
  )
  assert.deepEqual(rows.map((row) => row.code), ['C', 'A', 'B'])
})

test('outside the session the watchlist keeps its original order', () => {
  const rows = buildFocusRows(
    [quote('A', '甲', 10, 1), quote('B', '乙', 10, 2)],
    new Map([['B', [{ ruleId: 'r', description: 'd', armed: true, fired: true }]]]),
    [],
    false,
  )
  assert.deepEqual(rows.map((row) => row.code), ['A', 'B'])
})

test('a missing quote still becomes a row with dashes', () => {
  const rows = buildFocusRows([{ ...quote('600000', '', 0, 0), price: null, changePct: null, limitUp: null, limitDown: null, missing: true }], new Map(), [], false)
  assert.equal(rows[0]!.missing, true)
  assert.equal(rows[0]!.name, '600000')
  assert.equal(rows[0]!.limit.pct, null)
})

test('filterFeed implements my-stocks, sector and all chips', () => {
  const items = [
    alertItem(1, '600000', '2026-11-03T10:00:00+08:00'),
    buildTimeline([], [{ id: 2, ts: '2026-11-03T10:01:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0433', objectName: '农林', severity: 'L1', title: 't', detail: '', status: 'new', analysisId: null, payload: {}, raw: {} }], [])[0]!,
  ]
  const mine = new Set(['600000'])
  assert.deepEqual(filterFeed(items, 'all', mine).length, 2)
  assert.deepEqual(filterFeed(items, 'mine', mine).map((item) => item.key), ['watch:1'])
  assert.deepEqual(filterFeed(items, 'sector', mine).map((item) => item.key), ['market:2'])
})

test('aggregateTimeline merges one timestamp and rule into a single row', () => {
  const items: TimelineItem[] = [
    { key: 'market:2', source: 'market', id: 2, ts: '2026-11-03T10:00:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0433', objectName: '农林', severity: 'L1', title: '板块跃升', detail: '', status: 'pending', reason: '', analysisId: null, raw: {} },
    { key: 'market:1', source: 'market', id: 1, ts: '2026-11-03T10:00:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0434', objectName: '煤炭', severity: 'L3', title: '板块跃升', detail: '', status: 'pending', reason: '', analysisId: null, raw: {} },
    { key: 'market:3', source: 'market', id: 3, ts: '2026-11-03T10:05:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0435', objectName: '钢铁', severity: null, title: 'x', detail: '', status: 'pending', reason: '', analysisId: null, raw: {} },
  ]
  const rows = aggregateTimeline(items)
  assert.equal(rows.length, 2)
  assert.equal(rows[0]!.count, 2)
  assert.deepEqual(rows[0]!.objectNames, ['农林', '煤炭'])
  assert.equal(rows[0]!.severity, 'L3')
  assert.match(rows[0]!.title, /等 2 个/)
})

test('aggregation keeps the analyzing status and the first analysis id', () => {
  const base = { source: 'market' as const, ts: '2026-11-03T10:00:00+08:00', ruleId: 'R4', objectType: 'sector' as const, severity: 'L2' as const, title: 't', detail: '', raw: {} }
  const rows = aggregateTimeline([
    { ...base, key: 'market:1', id: 1, objectCode: 'BK0433', objectName: '农林', status: 'pending', reason: '', analysisId: null },
    { ...base, key: 'market:2', id: 2, objectCode: 'BK0434', objectName: '煤炭', status: 'analyzing', reason: '', analysisId: 9 },
  ])
  assert.equal(rows.length, 1)
  assert.equal(rows[0]!.status, 'analyzing')
  assert.equal(rows[0]!.analysisId, 9)
})

test('feedRows and feedCounts apply the chip before aggregation', () => {
  const items = [
    alertItem(1, '600000', '2026-11-03T10:00:00+08:00'),
    alertItem(2, '000001', '2026-11-03T10:01:00+08:00'),
  ]
  const mine = new Set(['600000'])
  assert.deepEqual(feedCounts(items, mine), { all: 2, mine: 1, sector: 0 })
  assert.equal(feedRows(items, 'mine', mine).length, 1)
  assert.equal(feedRows(items, 'all', mine).length, 2)
})

test('reviewRows keeps only the newest rows for the after-hours card', () => {
  const items = [4, 3, 2, 1].map((id) => alertItem(id, '600000', `2026-11-03T1${id}:00:00+08:00`))
  assert.deepEqual(reviewRows(items).map((item) => item.id), [4, 3, 2])
  assert.deepEqual(reviewRows(items, 0), [])
})

test('askContext carries only the trading state, one index and watchlist names', () => {
  const context = askContext({ stateLabel: '交易中', indexName: '上证指数', indexChangePct: -0.82, watchNames: ['南方精工', '太平洋'] })
  assert.match(context, /当前盯盘/)
  assert.match(context, /交易状态 交易中/)
  assert.match(context, /上证指数 ▼ -0.82%/)
  assert.match(context, /我的自选：南方精工、太平洋/)
  assert.doesNotMatch(context, /持仓|仓位|资金|成本|画像|风险偏好/)
})

test('askContext caps the watchlist at five names and reports the total', () => {
  const context = askContext({ stateLabel: '休市', watchNames: ['一', '二', '三', '四', '五', '六', '七'] })
  assert.match(context, /我的自选：一、二、三、四、五 等 7 只/)
})

test('askContext says 无 when the watchlist is empty and omits a missing index', () => {
  const context = askContext({ stateLabel: '盘前', watchNames: [] })
  assert.match(context, /我的自选：无/)
  assert.doesNotMatch(context, /undefined|NaN/)
})

test('composeAsk prepends the public context and refuses empty input', () => {
  assert.equal(composeAsk('  ', '（上下文）'), null)
  assert.equal(composeAsk('今天哪个行业最强？', '（上下文）'), '（上下文）\n今天哪个行业最强？')
  assert.equal(composeAsk('问题', ''), '问题')
})

test('composeAsk enforces the shared draft length cap', () => {
  const payload = composeAsk('x'.repeat(MAX_ASK_LENGTH * 2), '（上下文）')
  assert.equal(payload!.length, MAX_ASK_LENGTH)
})

test('searchAsk turns the top-bar query into an introduction request', () => {
  assert.equal(searchAsk('  贵州茅台 '), '介绍一下 贵州茅台')
  assert.equal(searchAsk('   '), null)
})

test('mover display helpers keep units and signed percentages', () => {
  const row = normalizeMovers(rawMovers).rows[0]!
  assert.equal(moverPrice(row), '10.50')
  assert.equal(moverChange(row), '▼ -3.20%')
  assert.equal(moverAmount(row), '12.00 亿元')
  assert.equal(moverTurnover(row), '1.50%')
})

test('moversByKind and latestMoverAsOf read the per-kind cache', () => {
  const payloads = {
    gainers: normalizeMovers({ ...rawMovers, kind: 'gainers', as_of: '2026-11-03T14:00:00+08:00' }),
    losers: normalizeMovers(rawMovers),
  }
  assert.equal(moversByKind(payloads, 'gainers').length, 1)
  assert.deepEqual(moversByKind(payloads, 'active'), [])
  assert.equal(latestMoverAsOf(payloads), '2026-11-03T15:00:00+08:00')
})

test('marketAlertItem and watchAlertItem adapt the two alert sources', () => {
  const market: MarketAlert = {
    id: 5, ts: '2026-11-03T10:00:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0433', objectName: '农林',
    severity: 'L2', title: 't', detail: 'd', status: 'skipped', analysisId: null, payload: {}, raw: {},
  }
  const marketItem = marketAlertItem(market)!
  assert.equal(marketItem.key, 'market:5')
  assert.equal(marketItem.objectType, 'sector')
  const watch = watchAlertItem({ id: 3, ts: '2026-11-03T10:00:00+08:00', code: '600000', name: '浦发', rule_id: 'pct_up_3' }, { alert_id: 3, status: 'done' })!
  assert.equal(watch.key, 'watch:3')
  assert.equal(watch.status, 'analyzed')
  assert.equal(marketAlertItem({ ...market, id: 0 }), null)
})
