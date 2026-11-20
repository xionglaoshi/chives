import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ALLOCATION_COLORS,
  DEFAULT_SORT,
  DIAGNOSE_PROMPT,
  HIDDEN_STORAGE_KEY,
  HISTORY_RANGE_DAYS,
  IMPORT_PROMPT,
  MASK,
  allocationSegments,
  askStockPrompt,
  buildWatchRows,
  flagText,
  historyDays,
  historyGeometry,
  historyPointAt,
  historyRangeSlice,
  historyReadiness,
  historyValue,
  limitFlag,
  moneyText,
  moveText,
  normalizeHistory,
  normalizePortfolioOverview,
  pctText,
  positionFlags,
  priceText,
  quantityText,
  ratioText,
  readHidden,
  riskMetrics,
  riskState,
  sideOf,
  sortPositions,
  toggleSort,
  writeHidden,
} from '../../chives-ui/src/client/myPageModel.ts'
import type { PortfolioPosition } from '../../chives-ui/src/client/myPageModel.ts'

const rawOverview = () => ({
  ok: true,
  private: true,
  as_of: '2026-11-04T15:00:00+08:00',
  quote_time: '2026-11-04T14:59:58+08:00',
  empty: false,
  totals: {
    market_value_cny: 999999,
    cost_cny: 1,
    pnl_cny: 1,
    pnl_pct: 1,
    day_pnl_cny: 1,
    day_pnl_pct: 1,
    cash_cny: 20000,
    total_assets_cny: 70000,
    position_ratio_pct: 1,
  },
  positions: [
    { code: '600000', name: '浦发银行', qty: 1000, cost_price_cny: 8, price_cny: 10, prev_close_cny: 9.8, change_pct: 2.04, market_value_cny: 10000, pnl_cny: 2000, pnl_pct: 25, day_pnl_cny: 200, weight_pct: 14.29, sellable_today: false, price_unavailable: false },
    { code: '300750', name: '宁德时代', qty: 200, cost_price_cny: 180, price_cny: 200, prev_close_cny: 190, change_pct: 5.26, market_value_cny: 40000, pnl_cny: 4000, pnl_pct: 11.11, day_pnl_cny: 2000, weight_pct: 57.14, sellable_today: true, price_unavailable: false },
    { code: '000001', name: '平安银行', qty: 500, cost_price_cny: 12, price_cny: null, prev_close_cny: 11, change_pct: null, market_value_cny: null, pnl_cny: null, pnl_pct: null, day_pnl_cny: null, weight_pct: null, sellable_today: true, price_unavailable: true },
  ],
  risk: { annualized_vol_pct: 18.42, beta: 1.07, max_drawdown_pct: -12.5, top1_weight_pct: 57.14, effective_n: 2.4 },
  risk_pending: false,
  risk_reason: null,
  history_days: 12,
})

const rawHistory = () => ({
  ok: true,
  points: [
    { date: '2026-11-03', total_assets_cny: 68000, market_value_cny: 48000, pnl_cny: 5000, day_pnl_cny: 300 },
    { date: '2026-11-01', total_assets_cny: 66000, market_value_cny: 46000, pnl_cny: 3000, day_pnl_cny: -200 },
    { date: '2026-11-02', total_assets_cny: 67000, market_value_cny: 47000, pnl_cny: 4000, day_pnl_cny: 100 },
    { date: '2026-11-02', total_assets_cny: 67500, market_value_cny: 47500, pnl_cny: 4500, day_pnl_cny: 150 },
  ],
})

const position = (overrides: Partial<PortfolioPosition> = {}): PortfolioPosition => ({
  code: '600000',
  name: '浦发银行',
  qty: 1000,
  costPriceCny: 8,
  priceCny: 10,
  prevCloseCny: 9.8,
  changePct: 2.04,
  marketValueCny: 10000,
  pnlCny: 2000,
  pnlPct: 25,
  dayPnlCny: 200,
  weightPct: 20,
  sellableToday: true,
  priceUnavailable: false,
  ...overrides,
})

test('overview normalises ok, timestamps, empty and history days', () => {
  const overview = normalizePortfolioOverview(rawOverview())
  assert.equal(overview.ok, true)
  assert.equal(overview.asOf, '2026-11-04T15:00:00+08:00')
  assert.equal(overview.quoteTime, '2026-11-04T14:59:58+08:00')
  assert.equal(overview.empty, false)
  assert.equal(overview.historyDays, 12)
  assert.equal(overview.positions.length, 3)
})

test('price-unavailable rows are excluded from market value', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).totals.marketValueCny, 50000)
})

test('cost basis is recomputed from cost price times quantity', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).totals.costCny, 44000)
})

test('total P&L sums only valued rows', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).totals.pnlCny, 6000)
})

test('day P&L sums only valued rows', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).totals.dayPnlCny, 2200)
})

test('P&L percentage is derived from the recomputed cost', () => {
  const pct = normalizePortfolioOverview(rawOverview()).totals.pnlPct
  assert.ok(pct !== null && Math.abs(pct - (6000 / 44000) * 100) < 0.001)
})

test('total assets keeps the hub value (not just market value plus cash)', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).totals.totalAssetsCny, 70000)
})

test('position ratio is market value over total assets', () => {
  const ratio = normalizePortfolioOverview(rawOverview()).totals.positionRatioPct
  assert.ok(ratio !== null && Math.abs(ratio - (50000 / 70000) * 100) < 0.001)
})

test('cash is known when the hub reports it', () => {
  const totals = normalizePortfolioOverview(rawOverview()).totals
  assert.equal(totals.cashKnown, true)
  assert.equal(totals.cashCny, 20000)
})

test('missing cash and total assets stay null instead of becoming zero', () => {
  const raw = rawOverview()
  raw.totals.cash_cny = null as never
  raw.totals.total_assets_cny = null as never
  const totals = normalizePortfolioOverview(raw).totals
  assert.equal(totals.cashKnown, false)
  assert.equal(totals.cashCny, null)
  assert.equal(totals.totalAssetsCny, null)
  assert.equal(totals.positionRatioPct, null)
})

test('cash plus market value is a fallback when total assets is missing', () => {
  const raw = rawOverview()
  raw.totals.total_assets_cny = null as never
  assert.equal(normalizePortfolioOverview(raw).totals.totalAssetsCny, 70000)
})

test('empty is implied by a position-less overview', () => {
  const overview = normalizePortfolioOverview({ ok: true, positions: [] })
  assert.equal(overview.empty, true)
})

test('missing sellable_today defaults to sellable', () => {
  const raw = rawOverview()
  delete (raw.positions[1] as Record<string, unknown>).sellable_today
  const overview = normalizePortfolioOverview(raw)
  assert.equal(overview.positions[1]!.sellableToday, true)
})

test('sellable_today=false is preserved', () => {
  assert.equal(normalizePortfolioOverview(rawOverview()).positions[0]!.sellableToday, false)
})

test('missing change_pct is computed from price and previous close', () => {
  const raw = rawOverview()
  delete (raw.positions[0] as Record<string, unknown>).change_pct
  const row = normalizePortfolioOverview(raw).positions[0]!
  assert.ok(row.changePct !== null && Math.abs(row.changePct - 2.0408) < 0.01)
})

test('missing market value is computed from price times quantity', () => {
  const raw = rawOverview()
  delete (raw.positions[1] as Record<string, unknown>).market_value_cny
  assert.equal(normalizePortfolioOverview(raw).positions[1]!.marketValueCny, 40000)
})

test('missing P&L is computed from market value minus cost basis', () => {
  const raw = rawOverview()
  delete (raw.positions[1] as Record<string, unknown>).pnl_cny
  assert.equal(normalizePortfolioOverview(raw).positions[1]!.pnlCny, 4000)
})

test('missing day P&L is computed from price minus previous close', () => {
  const raw = rawOverview()
  delete (raw.positions[1] as Record<string, unknown>).day_pnl_cny
  assert.equal(normalizePortfolioOverview(raw).positions[1]!.dayPnlCny, 2000)
})

test('missing weight falls back to market value over total assets', () => {
  const raw = rawOverview()
  delete (raw.positions[0] as Record<string, unknown>).weight_pct
  const row = normalizePortfolioOverview(raw).positions[0]!
  assert.ok(row.weightPct !== null && Math.abs(row.weightPct - (10000 / 70000) * 100) < 0.001)
})

test('risk metrics normalise every contract field', () => {
  const risk = normalizePortfolioOverview(rawOverview()).risk
  assert.deepEqual(risk, { annualizedVolPct: 18.42, beta: 1.07, maxDrawdownPct: -12.5, top1WeightPct: 57.14, effectiveN: 2.4 })
})

test('null risk keeps its pending flag and reason', () => {
  const raw = rawOverview()
  raw.risk = null as never
  raw.risk_pending = true
  raw.risk_reason = '需要至少 20 个交易日'
  const overview = normalizePortfolioOverview(raw)
  assert.equal(overview.risk, null)
  assert.equal(overview.riskState ?? riskState(overview), 'pending')
  assert.equal(overview.riskReason, '需要至少 20 个交易日')
})

test('risk without pending is unavailable', () => {
  const raw = rawOverview()
  raw.risk = null as never
  raw.risk_pending = false
  assert.equal(riskState(normalizePortfolioOverview(raw)), 'unavailable')
})

test('risk metrics expose five rows in display order', () => {
  assert.deepEqual(riskMetrics(normalizePortfolioOverview(rawOverview()).risk!).map((metric) => metric.key), ['vol', 'drawdown', 'beta', 'top1', 'effectiveN'])
})

test('history points sort by date and the last duplicate wins', () => {
  const history = normalizeHistory(rawHistory())
  assert.deepEqual(history.points.map((point) => point.date), ['2026-11-01', '2026-11-02', '2026-11-03'])
  assert.equal(history.points[1]!.totalAssetsCny, 67500)
})

test('historyRangeSlice keeps the last 30 points', () => {
  const points = Array.from({ length: 40 }, (_, index) => ({ date: `2026-10-${String(index + 1).padStart(2, '0')}`, marketValueCny: index, totalAssetsCny: null, pnlCny: null, dayPnlCny: null }))
  assert.equal(historyRangeSlice(points, '30').length, 30)
  assert.equal(historyRangeSlice(points, '30')[0]!.date, '2026-10-11')
})

test('historyRangeSlice keeps every point for all', () => {
  const points = historyRangeSlice(normalizeHistory(rawHistory()).points, 'all')
  assert.equal(points.length, 3)
})

test('historyDays maps ranges to the proxy whitelist', () => {
  assert.deepEqual(HISTORY_RANGE_DAYS, { '30': 30, '90': 90, all: 365 })
  assert.equal(historyDays('30'), 30)
  assert.equal(historyDays('90'), 90)
  assert.equal(historyDays('all'), 365)
})

test('history readiness counts usable values and needs two', () => {
  assert.deepEqual(historyReadiness(normalizeHistory(rawHistory()).points), { count: 3, enough: true })
  assert.deepEqual(historyReadiness([]), { count: 0, enough: false })
})

test('historyValue falls back to market value when total assets is null', () => {
  assert.equal(historyValue({ date: '2026-11-01', totalAssetsCny: null, marketValueCny: 123, pnlCny: null, dayPnlCny: null }), 123)
})

test('history geometry draws an area and a rising side', () => {
  const geometry = historyGeometry(normalizeHistory(rawHistory()).points)!
  assert.match(geometry.path, /^M[0-9.]+ [0-9.]+ L/)
  assert.match(geometry.area, / Z$/)
  assert.equal(geometry.side, 'up')
  assert.equal(geometry.coords.length, 3)
  assert.ok(geometry.change > 0)
})

test('history geometry flags a falling side', () => {
  const points = [
    { date: '2026-11-01', totalAssetsCny: 100, marketValueCny: null, pnlCny: null, dayPnlCny: null },
    { date: '2026-11-02', totalAssetsCny: 90, marketValueCny: null, pnlCny: null, dayPnlCny: null },
  ]
  assert.equal(historyGeometry(points)!.side, 'down')
})

test('history geometry returns null with fewer than two usable points', () => {
  const points = [{ date: '2026-11-01', totalAssetsCny: 100, marketValueCny: null, pnlCny: null, dayPnlCny: null }]
  assert.equal(historyGeometry(points), null)
})

test('historyPointAt clamps the hover ratio to the nearest point', () => {
  const geometry = historyGeometry(normalizeHistory(rawHistory()).points)!
  assert.equal(historyPointAt(geometry, -1), 0)
  assert.equal(historyPointAt(geometry, 2), 2)
  assert.equal(historyPointAt(geometry, 0.5), 1)
  assert.equal(historyPointAt(null, 0.5), null)
})

const rows = [
  position({ code: 'A', name: '甲公司', qty: 300, weightPct: 30, pnlCny: 300, dayPnlCny: 30, priceCny: 3, costPriceCny: 2 }),
  position({ code: 'B', name: '乙公司', qty: 100, weightPct: 10, pnlCny: 100, dayPnlCny: 10, priceCny: 1, costPriceCny: 0.5 }),
  position({ code: 'C', name: '丙公司', qty: 200, weightPct: 20, pnlCny: 200, dayPnlCny: 20, priceCny: 2, costPriceCny: 1 }),
]

test('default sort is weight descending', () => {
  assert.deepEqual(DEFAULT_SORT, { key: 'weight', dir: 'desc' })
  assert.deepEqual(sortPositions(rows, DEFAULT_SORT).map((row) => row.code), ['A', 'C', 'B'])
})

test('sort by name ascending uses a stable ordering', () => {
  assert.deepEqual(sortPositions(rows, { key: 'name', dir: 'asc' }).map((row) => row.code), ['C', 'B', 'A'])
})

test('sort by quantity desc and asc', () => {
  assert.deepEqual(sortPositions(rows, { key: 'qty', dir: 'desc' }).map((row) => row.code), ['A', 'C', 'B'])
  assert.deepEqual(sortPositions(rows, { key: 'qty', dir: 'asc' }).map((row) => row.code), ['B', 'C', 'A'])
})

test('missing values always trail regardless of direction', () => {
  const withMissing = [...rows, position({ code: 'D', name: '丁公司', qty: null, weightPct: null })]
  assert.deepEqual(sortPositions(withMissing, { key: 'weight', dir: 'desc' }).map((row) => row.code), ['A', 'C', 'B', 'D'])
  assert.deepEqual(sortPositions(withMissing, { key: 'weight', dir: 'asc' }).map((row) => row.code), ['B', 'C', 'A', 'D'])
})

test('clicking the active header flips direction', () => {
  assert.deepEqual(toggleSort({ key: 'weight', dir: 'desc' }, 'weight'), { key: 'weight', dir: 'asc' })
  assert.deepEqual(toggleSort({ key: 'weight', dir: 'asc' }, 'weight'), { key: 'weight', dir: 'desc' })
})

test('a new numeric column starts descending and a new name column ascending', () => {
  assert.deepEqual(toggleSort({ key: 'weight', dir: 'desc' }, 'pnl'), { key: 'pnl', dir: 'desc' })
  assert.deepEqual(toggleSort({ key: 'weight', dir: 'desc' }, 'name'), { key: 'name', dir: 'asc' })
})

test('main-board limit flags use the 10% band', () => {
  assert.equal(limitFlag('600000', 10.01), 'limit_up')
  assert.equal(limitFlag('600000', -10.01), 'limit_down')
  assert.equal(limitFlag('600000', 9.4), null)
})

test('ChiNext and STAR flags use the 20% band', () => {
  assert.equal(limitFlag('300750', 20), 'limit_up')
  assert.equal(limitFlag('688981', -19.9), 'limit_down')
  assert.equal(limitFlag('300750', 10.5), null)
})

test('Beijing flags use the 30% band', () => {
  assert.equal(limitFlag('830799', 29.9), 'limit_up')
  assert.equal(limitFlag('430047', -30), 'limit_down')
})

test('position flags cover T+1, limit up/down and missing quotes', () => {
  assert.deepEqual(positionFlags(position({ sellableToday: false })), ['t1'])
  assert.deepEqual(positionFlags(position({ changePct: 10.5 })), ['limit_up'])
  assert.deepEqual(positionFlags(position({ changePct: -10.5 })), ['limit_down'])
  assert.deepEqual(positionFlags(position({ priceUnavailable: true })), ['missing'])
})

test('flag labels are explicit', () => {
  assert.equal(flagText('t1'), 'T+1 不可卖')
  assert.equal(flagText('limit_up'), '涨停')
  assert.equal(flagText('limit_down'), '跌停')
  assert.equal(flagText('missing'), '行情缺失')
})

test('allocation takes the top five plus an aggregated other segment', () => {
  const many = Array.from({ length: 7 }, (_, index) => position({
    code: `60000${index}`,
    name: `股票${index}`,
    weightPct: 30 - index * 3,
  }))
  const segments = allocationSegments(many)
  assert.equal(segments.length, 6)
  assert.equal(segments[segments.length - 1]!.key, 'other')
})

test('allocation percentages add up to 100', () => {
  const segments = allocationSegments(rows)
  const sum = segments.reduce((total, segment) => total + segment.pct, 0)
  assert.ok(Math.abs(sum - 100) < 0.001, String(sum))
})

test('allocation colours avoid the red/green categorical hues', () => {
  const segments = allocationSegments(rows)
  for (const segment of segments) {
    assert.ok(!segment.color.includes('cat-2'), segment.color)
    assert.ok(!segment.color.includes('cat-7'), segment.color)
    assert.ok(ALLOCATION_COLORS.includes(segment.color))
  }
  assert.equal(new Set(segments.map((segment) => segment.color)).size, segments.length)
})

test('allocation is empty without valued positions', () => {
  assert.deepEqual(allocationSegments([]), [])
  assert.deepEqual(allocationSegments([position({ priceUnavailable: true, weightPct: 10 })]), [])
})

test('watch rows mark overlap with holdings', () => {
  const watch = buildWatchRows([
    { code: '600000', name: '浦发银行', price: 10, changePct: 2, missing: false },
    { code: '000002', name: '万科A', price: 8, changePct: -1, missing: false },
  ], [position({ code: '600000' }) ])
  assert.deepEqual(watch.map((row) => [row.code, row.held]), [['600000', true], ['000002', false]])
})

test('watch rows drop missing and empty codes', () => {
  const watch = buildWatchRows([
    { code: '600000', name: '浦发银行', price: 10, changePct: 2, missing: true },
    { code: '', name: '', price: null, changePct: null, missing: false },
  ], rows)
  assert.deepEqual(watch, [])
})

test('the stock prompt contains only that stock name, code, price and cost', () => {
  const prompt = askStockPrompt({ name: '浦发银行', code: '600000', priceCny: 10, costPriceCny: 8 })
  assert.equal(prompt, '请分析我持有的 浦发银行（600000）：现价 10.00，成本 8.00')
  assert.ok(!prompt.includes('宁德时代'))
  assert.ok(!prompt.includes('300750'))
  assert.ok(!prompt.includes('1000'))
})

test('import and diagnosis prompts match the fixed copy', () => {
  assert.ok(IMPORT_PROMPT.startsWith('我要导入持仓。'))
  assert.ok(IMPORT_PROMPT.includes('我确认后再保存'))
  assert.equal(DIAGNOSE_PROMPT, '请用 portfolio-diagnosis 技能诊断我的持仓。')
})

test('hidden amount helper masks money but keeps percentages', () => {
  assert.equal(moneyText(12345, true), MASK)
  assert.equal(moneyText(12345, false), '1.23 万元')
  assert.equal(pctText(12.34), '+12.34%')
  assert.equal(priceText(10.5, true), MASK)
  assert.equal(quantityText(1000), '1000')
  assert.equal(ratioText(12.34), '12.3%')
})

test('hidden storage reads and writes the single allowed key', () => {
  const store = new Map<string, string>()
  const storage = { getItem: (key: string) => store.get(key) ?? null, setItem: (key: string, value: string) => { store.set(key, value) } }
  assert.equal(readHidden(storage), false)
  writeHidden(true, storage)
  assert.equal(store.get(HIDDEN_STORAGE_KEY), '1')
  assert.equal(readHidden(storage), true)
  writeHidden(false, storage)
  assert.equal(readHidden(storage), false)
})

test('hidden storage failures fall back to visible', () => {
  const broken = {
    getItem(): string | null { throw new Error('denied') },
    setItem(): void { throw new Error('denied') },
  }
  assert.equal(readHidden(broken), false)
  writeHidden(true, broken)
  assert.equal(readHidden(null), false)
})

test('direction helpers keep flat separate', () => {
  assert.equal(sideOf(1), 'up')
  assert.equal(sideOf(-1), 'down')
  assert.equal(sideOf(0), 'flat')
  assert.equal(moveText(2.5), '▲ +2.50%')
  assert.equal(moveText(-2.5), '▼ -2.50%')
})

test('price, cost and P&L columns sort both ways', () => {
  assert.deepEqual(sortPositions(rows, { key: 'price', dir: 'desc' }).map((row) => row.code), ['A', 'C', 'B'])
  assert.deepEqual(sortPositions(rows, { key: 'cost', dir: 'asc' }).map((row) => row.code), ['B', 'C', 'A'])
  assert.deepEqual(sortPositions(rows, { key: 'dayPnl', dir: 'desc' }).map((row) => row.code), ['A', 'C', 'B'])
  assert.deepEqual(sortPositions(rows, { key: 'pnl', dir: 'asc' }).map((row) => row.code), ['B', 'C', 'A'])
})

test('history ranges 30 and all keep the expected slices and switch active copy', () => {
  const points = normalizeHistory(rawHistory()).points
  assert.equal(historyRangeSlice(points, '30').length, 3)
  assert.equal(historyRangeSlice(points, 'all').length, 3)
  assert.equal(historyRangeSlice(points, '90').length, 3)
})

test('the five risk metrics keep a null value instead of inventing a number', () => {
  const metrics = riskMetrics({ annualizedVolPct: null, beta: 1, maxDrawdownPct: null, top1WeightPct: 20, effectiveN: 1 })
  assert.equal(metrics[0]!.value, null)
  assert.equal(metrics[4]!.value, 1)
})
