import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { zh } from '../src/client/locales.ts'
import { normalizeHistory, normalizePortfolioOverview, DEFAULT_SORT } from '../src/client/myPageModel.ts'
import type { MyPageViewProps } from '../src/client/myPage.tsx'
import { loadClientModule } from './tsx.ts'

type Component = (props: never) => ReactElement
const mod = await loadClientModule('myPage.tsx')
const MyPageView = mod.MyPageView as Component

const t = (key: keyof typeof zh, params?: Record<string, unknown>): string => {
  let value: string = zh[key]
  for (const [name, replacement] of Object.entries(params ?? {})) value = value.replace(`{${name}}`, String(replacement))
  return value
}

const rawOverview = (overrides: Record<string, unknown> = {}) => ({
  ok: true,
  private: true,
  as_of: '2026-11-04T15:00:00+08:00',
  quote_time: '2026-11-04T14:59:58+08:00',
  empty: false,
  totals: {
    cash_cny: 20000,
    total_assets_cny: 70000,
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
  ...overrides,
})

const history = normalizeHistory({
  ok: true,
  points: [
    { date: '2026-11-01', total_assets_cny: 66000, market_value_cny: 46000, pnl_cny: 3000, day_pnl_cny: -200 },
    { date: '2026-11-02', total_assets_cny: 67000, market_value_cny: 47000, pnl_cny: 4000, day_pnl_cny: 100 },
    { date: '2026-11-03', total_assets_cny: 68000, market_value_cny: 48000, pnl_cny: 5000, day_pnl_cny: 300 },
  ],
})

const overview = normalizePortfolioOverview(rawOverview())

const baseProps = (overrides: Partial<MyPageViewProps> = {}): MyPageViewProps => ({
  t,
  width: 1440,
  session: 'open',
  overview,
  history,
  quotes: [
    { code: '600000', name: '浦发银行', price: 10, changePct: 2.04, vwap: null, vwapDevPct: null, high: null, low: null, limitUp: null, limitDown: null, amountYuan: null, exchTime: null, missing: false },
    { code: '000002', name: '万科A', price: 8, changePct: -1.2, vwap: null, vwapDevPct: null, high: null, low: null, limitUp: null, limitDown: null, amountYuan: null, exchTime: null, missing: false },
  ],
  failures: { overview: false, history: false, watch: false },
  range: '90',
  onRange: () => {},
  sort: DEFAULT_SORT,
  onSort: () => {},
  expanded: null,
  onExpand: () => {},
  highlight: null,
  onHighlight: () => {},
  hidden: false,
  onHidden: () => {},
  askText: '',
  onAskText: () => {},
  onAsk: () => {},
  onAskStock: () => {},
  onImport: () => {},
  onDiagnose: () => {},
  onOpenWatch: () => {},
  onRetry: () => {},
  asked: false,
  ...overrides,
})

const render = (overrides: Partial<MyPageViewProps> = {}): string => renderToStaticMarkup(createElement(MyPageView, baseProps(overrides) as never))

test('the top bar carries the title, data time, quote time, session and three controls', () => {
  const html = render()
  assert.match(html, />我的</)
  assert.match(html, /数据时间 11-04 15:00/)
  assert.match(html, /行情时间 11-04 14:59/)
  assert.match(html, /交易中/)
  assert.match(html, /导入持仓/)
  assert.match(html, /诊断持仓/)
  assert.match(html, /aria-pressed="false"/)
})

test('the overview card renders six labelled cells with formatted values', () => {
  const html = render()
  const plain = html.replace(/<[^>]+>/g, '')
  for (const label of ['总资产', '持仓市值', '今日盈亏', '累计浮盈', '仓位', '现金']) assert.match(plain, new RegExp(label))
  assert.match(plain, /7\.00 万元/)
  assert.match(plain, /5\.00 万元/)
  assert.match(plain, /2200 元/)
  assert.match(plain, /71\.4%/)
  assert.match(plain, /2\.00 万元/)
})

test('the holdings table has the eight required columns and one row per position', () => {
  const html = render()
  const headers = ['名称', '持仓（股）', '成本', '现价', '今日盈亏', '累计盈亏', '占比', '标记']
  for (const header of headers) assert.match(html, new RegExp(`>${header}<`))
  assert.match(html, /浦发银行/)
  assert.match(html, /600000/)
  assert.match(html, /宁德时代/)
  assert.match(html, /平安银行/)
})

test('the default order is weight descending and the weight header announces it', () => {
  const html = render()
  assert.match(html, /aria-sort="descending"/)
  assert.ok(html.indexOf('宁德时代') < html.indexOf('浦发银行'))
})

test('a price-unavailable row shows the quote-missing flag', () => {
  const html = render()
  assert.match(html, /行情缺失/)
  assert.match(html, /is-missing/)
})

test('T+1 and limit flags are rendered as pills', () => {
  const html = render()
  assert.match(html, /T\+1 不可卖/)
  const limit = normalizePortfolioOverview(rawOverview({
    positions: [
      { code: '600000', name: '浦发银行', qty: 1000, cost_price_cny: 8, price_cny: 10.5, prev_close_cny: 9.5, change_pct: 10.5, market_value_cny: 10500, pnl_cny: 2500, weight_pct: 50, sellable_today: true, price_unavailable: false },
    ],
  }))
  assert.match(render({ overview: limit }), /涨停/)
})

test('expanding a row shows cost, sellable quantity, asset share and the ask button', () => {
  const html = render({ expanded: '600000' })
  assert.match(html, /chives-my-detail/)
  assert.match(html, /成本价/)
  assert.match(html, /可卖数量/)
  assert.match(html, /占总资产/)
  assert.match(html, /问 Chives 这只票/)
})

test('the risk card lists five metrics with plain-language notes', () => {
  const html = render()
  for (const label of ['年化波动率', '最大回撤', 'Beta', '第一大持仓', '有效 N']) assert.match(html, new RegExp(label))
  assert.match(html, /18\.42%/)
  assert.match(html, /-12\.50%/)
  assert.match(html, /1\.07/)
  assert.match(html, /57\.14%/)
  assert.match(html, /2\.4/)
  assert.match(html, /波动越大/)
})

test('null risk shows the pending copy and the reason instead of a blank card', () => {
  const pending = normalizePortfolioOverview(rawOverview({ risk: null, risk_pending: true, risk_reason: '需要 20 个交易日' }))
  const html = render({ overview: pending })
  assert.match(html, /风险指标计算中/)
  assert.match(html, /需要 20 个交易日/)
  const unavailable = normalizePortfolioOverview(rawOverview({ risk: null, risk_pending: false }))
  assert.match(render({ overview: unavailable }), /风险指标暂不可用/)
})

test('fewer than two history points shows the snapshot count and the no-backfill note', () => {
  const html = render({ history: { ok: true, points: [], note: null } })
  assert.match(html, /已记录 0 天快照/)
  assert.match(html, /不回补历史/)
})

test('two or more history points draw the area line and keep the range switch', () => {
  const html = render()
  assert.match(html, /chives-my-chart is-up/)
  assert.match(html, /chives-my-area/)
  assert.match(html, /chives-my-line/)
  assert.match(html, /30 天/)
  assert.match(html, /90 天/)
  assert.match(html, /全部/)
  assert.match(html, /aria-pressed="true"[^>]*>90 天/)
})

test('allocation renders top holdings plus other and avoids red/green categorical hues', () => {
  const many = Array.from({ length: 7 }, (_, index) => ({
    code: `60000${index}`,
    name: `股票${index}`,
    qty: 100,
    cost_price_cny: 1,
    price_cny: 1,
    prev_close_cny: 1,
    change_pct: 0,
    market_value_cny: 100,
    pnl_cny: 0,
    day_pnl_cny: 0,
    weight_pct: 10,
    sellable_today: true,
    price_unavailable: false,
  }))
  const html = render({ overview: normalizePortfolioOverview(rawOverview({ positions: many })) })
  assert.match(html, /持仓结构/)
  assert.match(html, /其他/)
  assert.ok(!html.includes('cat-2'))
  assert.ok(!html.includes('cat-7'))
})

test('the watchlist marks held names and offers the watch-page link', () => {
  const html = render()
  assert.match(html, /关注清单/)
  assert.match(html, />持有</)
  assert.match(html, /去盯盘页看信号/)
  assert.match(html, /万科A/)
})

test('an empty portfolio shows the guide, dims the overview and highlights import', () => {
  const empty = normalizePortfolioOverview(rawOverview({ positions: [], totals: {} }))
  const html = render({ overview: empty })
  assert.match(html, /还没有持仓/)
  assert.match(html, /把券商导出的持仓表粘贴给 Chives/)
  assert.match(html, /导入持仓/)
  assert.match(html, /data-my="empty"/)
  const overviewHtml = html.slice(html.indexOf('data-my="overview"'), html.indexOf('data-my="empty"'))
  assert.ok(!/••••|chives-my-pill|0\.00%/.test(overviewHtml), 'empty overview shows dashes only')
  assert.ok(!html.includes('chives-my-table'))
})

test('hub unreachable renders the service-down state and a retry button', () => {
  const html = render({ overview: null, failures: { overview: true, history: true, watch: true } })
  assert.match(html, /数据服务未启动/)
  assert.match(html, /重试/)
  assert.match(html, /data-my="hubdown"/)
})

test('hidden amounts mask money but percentages and directions stay visible', () => {
  const html = render({ hidden: true })
  assert.match(html, /data-hidden="true"/)
  assert.match(html, /••••/)
  assert.match(html, /\+13\.64%/)
  assert.match(html, /71\.4%/)
  assert.match(html, /▲ \+2\.04%/)
})

test('hidden mode also masks share counts (table and expanded sellable quantity)', () => {
  const html = render({ hidden: true, expanded: '300750' })
  const cells = [...html.matchAll(/<td class="chives-my-num">([^<]*)<\/td>/g)].map((match) => match[1] ?? '')
  assert.ok(cells.length > 0)
  assert.ok(!cells.some((cell) => /^(1000|200|500)$/.test(cell)), cells.join('|'))
  assert.ok(!/可卖数量[^<]*<\/em>\s*200/.test(html))
})

test('stale data keeps the old values and shows a stale banner', () => {
  const html = render({ failures: { overview: true, history: true, watch: false } })
  assert.match(html, /数据陈旧/)
  assert.match(html, /宁德时代/)
})

test('the page exposes no trade or order entry', () => {
  const html = render({ expanded: '600000' })
  const buttons = [...html.matchAll(/<button[^>]*>(.*?)<\/button>/g)].map((match) => match[1] ?? '')
  for (const label of buttons) {
    assert.ok(!/买入|卖出|下单|交易|buy|sell/i.test(label), label)
  }
})
