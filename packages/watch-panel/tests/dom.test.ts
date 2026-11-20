import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { zh } from '../src/client/locales.ts'
import { buildTimeline } from '../src/client/market.ts'
import type { MarketIndex, Overview, SectorRow, TimelineItem } from '../src/client/market.ts'
import type { QuoteRow } from '../src/client/viewModel.ts'
import type { Signal } from '../src/client/signals.ts'
import type { WorkbenchData, WorkbenchViewProps } from '../src/client/workbench.tsx'
import { CLOSED_DRAWER, DEFAULT_MOVERS_FILTERS } from '../src/client/workbenchModel.ts'
import { loadClientModule } from './tsx.ts'

type Component = (props: never) => ReactElement
const mod = await loadClientModule('workbench.tsx')
const WorkbenchView = mod.WorkbenchView as Component

const t = (key: keyof typeof zh, params?: Record<string, unknown>): string => {
  let text: string = zh[key]
  for (const [name, value] of Object.entries(params ?? {})) text = text.replace(`{${name}}`, String(value))
  return text
}

const indexes: MarketIndex[] = [
  { code: '000001.SH', name: '上证指数', price: 3120.5, prevClose: 3146.2, changePct: -0.82, amountYuan: 5.2e11, volumeRatio: 1.1, spark: [{ t: '09:30', p: 3140 }, { t: '10:00', p: 3120.5 }], sparkKind: 'daily', asOf: '2026-11-03T15:00:00+08:00', stale: false, reason: null },
  ...['深证成指', '创业板指', '沪深300', '中证1000', '科创50'].map((name, index) => ({
    code: `39900${index}.SZ`, name, price: 10000 + index, prevClose: 10000, changePct: index / 2, amountYuan: 3e11, volumeRatio: null,
    spark: [], sparkKind: null as null, asOf: '2026-11-03T15:00:00+08:00', stale: false, reason: null,
  })),
]

const overview: Overview = {
  ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', tradingState: 'open', stateNote: null,
  indexes,
  breadth: { up: 2067, down: 3065, flat: 120, upRatio: 0.4, limitUp: 48, limitDown: 17, broken: 34, sealRatio: 0.58, maxStreak: 6, amountYuan: 1.7e12, asOf: '2026-11-03T15:00:00+08:00', stale: false, reason: null },
  regime: { label: 'risk_off', reasons: ['宽度偏弱'] },
}

const sector: SectorRow = {
  code: 'BK0433', name: '农林牧渔', changePct: 2.5, amountYuan: 5e9, amountShareRatio: 0.03,
  rel300Pct: 1.2, upCount: 30, downCount: 5, limitUpCount: 2, memberCount: 40, rank: 1, rankChange30m: 2,
  leaders: [{ code: '600000', name: '浦发银行', changePct: 6.2 }], laggards: [], ret5dPct: 1.1, ret20dPct: null,
  asOf: '2026-11-03T15:00:00+08:00', stale: false, small: false, reason: null,
}

const quote: QuoteRow = {
  code: '600000', name: '浦发银行', price: 10.5, changePct: 3.2, vwap: 10.2, vwapDevPct: 2.9,
  high: 10.8, low: 10.0, limitUp: 11.55, limitDown: 9.45, amountYuan: 1.2e9, exchTime: '2026-11-03T14:57:31+08:00', missing: false,
}

const timeline: TimelineItem[] = buildTimeline(
  [{ id: 1, ts: '2026-11-03T14:50:00+08:00', code: '600000', name: '浦发银行', rule_id: 'pct_up_3', price: 10.5, change_pct: 3.2 }],
  [{ id: 2, ts: '2026-11-03T14:51:00+08:00', ruleId: 'R3', objectType: 'sector', objectCode: 'BK0433', objectName: '农林牧渔', severity: 'L2', title: '板块跃升', detail: '排名上升', status: 'skipped', analysisId: null, payload: { reason: 'cooldown' }, raw: {} }],
  [{ alert_id: 1, code: '600000', rule_id: 'pct_up_3', status: 'done', started_at: '2026-11-03T14:51:00+08:00', reason: null }],
)

const signal = (overrides: Partial<Signal> = {}): Signal => ({
  id: 1,
  ts: '2026-11-03T10:12:00+08:00',
  kind: 'plan_entry',
  kindLabel: '计划触发 · 进场',
  decide: true,
  severity: 'L3',
  status: 'new',
  snoozeUntil: null,
  object: { type: 'stock', code: '600000', name: '浦发银行' },
  title: '浦发银行 回到了进场位',
  direction: 'bull',
  directionLabel: '偏多',
  conclusion: '现价 10.50 进入进场区间 10.20 – 10.60，缩量回踩。',
  brief: '成交额为昨日同时点的 64%。',
  context: { type: 'range', levelLo: 10.2, levelHi: 10.6, stop: 9.5, price: 10.5, min: 9.2, max: 11.2, giveup: false },
  source: { label: '来自 11-03 10:00 的分析 · 计划 P-1', alertIds: [1], analysisId: 1, planId: 1, ruleId: null },
  mergedCount: 1,
  primary: { label: '查看分析', action: 'open' },
  detailAvailable: true,
  ...overrides,
})

const data: WorkbenchData = {
  overview,
  health: null,
  watchHealth: null,
  quotes: [quote],
  rulesByCode: new Map([['600000', [
    { ruleId: 'pct_up_3', description: '涨幅 ≥ 3%', armed: true, fired: true },
    { ruleId: 'vol_2x', description: '放量 2 倍', armed: true, fired: false },
  ]]]),
  ruleIndex: new Map([['pct_up_3', '涨幅 ≥ 3%'], ['vol_2x', '放量 2 倍']]),
  alertNames: { 1: '浦发银行' },
  alertTsById: new Map([[1, '2026-11-03T14:50:00+08:00']]),
  ruleById: new Map(),
  timeline,
  analyses: [{ alert_id: 1, code: '600000', rule_id: 'pct_up_3', status: 'done', started_at: '2026-11-03T14:51:00+08:00' }],
  stockRules: [
    { code: '600000', ruleId: 'pct_up_3', description: '涨幅 ≥ 3%', armed: true, firedCount: 2, lastFired: '2026-11-03T14:50:00+08:00' },
    { code: '600000', ruleId: 'vol_2x', description: '放量 2 倍', armed: true, firedCount: 0, lastFired: null },
  ],
  marketRules: [{ id: 'R3', name: '板块排名跃升', enabled: true, level: 'L2', confirm: 2, cooldownMinutes: 30, params: { delta: 5 } }],
  sectors: [sector],
  sectorsAsOf: '2026-11-03T15:00:00+08:00',
  sectorsNote: null,
  summary: {
    ok: true, error: null, asOf: '2026-11-03T14:55:00+08:00', generatedBy: 'engine',
    headlines: [{ id: 'h1', tone: 'down', title: '高位科技退潮', body: '成交额 1.70 万亿，', refs: [{ type: 'sector', code: 'BK0433', name: '农林牧渔' }] }],
    note: null, stale: false, reason: null,
  },
  movers: {
    gainers: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'gainers', rows: [{ rank: 1, code: '600000', name: '浦发银行', price: 10.5, changePct: 3.2, amountYuan: 1.2e9, turnoverPct: 1.2, industry: '银行' }], filters: DEFAULT_MOVERS_FILTERS, source: 'eastmoney', stale: false, stateNote: null, reason: null },
    losers: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'losers', rows: [{ rank: 1, code: '000001', name: '平安银行', price: 9.8, changePct: -3.1, amountYuan: 8e8, turnoverPct: 1.1, industry: '银行' }], filters: DEFAULT_MOVERS_FILTERS, source: 'eastmoney', stale: false, stateNote: null, reason: null },
    active: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'active', rows: [{ rank: 1, code: '600519', name: '贵州茅台', price: 1500, changePct: 0.5, amountYuan: 9e9, turnoverPct: 0.4, industry: '食品饮料' }], filters: DEFAULT_MOVERS_FILTERS, source: 'eastmoney', stale: false, stateNote: null, reason: null },
  },
  sectorDetail: { ...sector, trend: [{ t: '09:30', changePct: 0.1 }, { t: '14:00', changePct: 2.5 }], history: { ret5dPct: 1.1, ret20dPct: null, rank5d: 3, rank20d: null }, stateNote: null },
  sectorMembers: [{ code: '600000', name: '浦发银行', price: 10.5, changePct: 3.2, amountYuan: 1e8, weightPct: 4.5, limitUp: false, limitDown: false }],
  analysis: { id: 1, markdown: '## 结论\n\n放量突破。', truncated: false },
  history: [{ ts: '2026-11-01T09:00:00+08:00', action: 'update', rule_id: 'pct_up_3', actor: 'agent' }],
  signals: [signal()],
  doneSignals: [signal({ id: 9, kind: 'info', kindLabel: '信息 · 已归并', decide: false, status: 'done', mergedCount: 4, title: '早盘误报', primary: { label: '重新打开', action: 'ack' } })],
  doneCount: 12,
  mergedToday: 19,
  signalDetail: {
    signal: signal(),
    markdown: '## 结论\n\n放量突破。',
    truncated: false,
    sections: { conclusion: '进入进场区间，条件成立。', direction: '偏多', points: ['回踩 5 日线', '缩量'], detail: '上方压力 11.00。' },
  },
  flows: {
    sector_in: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'sector_in', rows: [{ rank: 1, code: 'BK0433', name: '农林牧渔', mainNetYuan: 3.2e8, mainNetPct: 2.5, changePct: 2.5, amountYuan: 5e9 }], definition: '东财主力口径·仅作辅助参考', source: 'eastmoney', stale: false, stateNote: null, reason: null },
    sector_out: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'sector_out', rows: [{ rank: 1, code: 'BK0434', name: '煤炭', mainNetYuan: -2.1e8, mainNetPct: -1.2, changePct: -1.2, amountYuan: 4e9 }], definition: '东财主力口径·仅作辅助参考', source: 'eastmoney', stale: false, stateNote: null, reason: null },
    stock_in: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'stock_in', rows: [{ rank: 1, code: '600000', name: '浦发银行', mainNetYuan: 1.5e8, mainNetPct: 1.1, changePct: 3.2, amountYuan: 1.2e9 }], definition: '东财主力口径·仅作辅助参考', source: 'eastmoney', stale: false, stateNote: null, reason: null },
    stock_out: { ok: true, error: null, asOf: '2026-11-03T15:00:00+08:00', kind: 'stock_out', rows: [{ rank: 1, code: '000001', name: '平安银行', mainNetYuan: -9e7, mainNetPct: -0.8, changePct: -3.1, amountYuan: 8e8 }], definition: '东财主力口径·仅作辅助参考', source: 'eastmoney', stale: false, stateNote: null, reason: null },
  },
  northbound: { ok: true, available: true, reason: null, asOf: '2026-11-03T15:00:00+08:00', netYuan: 5.6e9 },
}

const baseProps = (overrides: Partial<WorkbenchViewProps> = {}): WorkbenchViewProps => ({
  t,
  now: Date.parse('2026-11-03T15:00:00+08:00'),
  width: 1440,
  collapsed: false,
  data,
  failures: { overview: false, marketHealth: false, watch: false, sectors: false, summary: false, movers: false, hub: false, flows: false },
  pulse: 'healthy',
  sectorView: 'heat',
  onSectorView: () => {},
  areaBasis: 'sqrt',
  onAreaBasis: () => {},
  moversFilters: DEFAULT_MOVERS_FILTERS,
  onMoversFilters: () => {},
  activeOpen: false,
  onActiveOpen: () => {},
  signalFilter: 'all',
  onSignalFilter: () => {},
  doneOpen: false,
  onDoneOpen: () => {},
  flowsMore: false,
  onFlowsMore: () => {},
  onSignal: () => {},
  toast: null,
  onUndo: () => {},
  pulsing: new Set(),
  moverPulse: new Set(),
  drawer: CLOSED_DRAWER,
  onDrawer: () => {},
  signalLoading: false,
  signalError: false,
  analysisLoading: false,
  analysisError: false,
  sectorDetailError: false,
  sectorMembersError: false,
  historyError: false,
  onHistory: () => {},
  askText: '',
  onAskText: () => {},
  onAsk: () => {},
  onSearch: () => {},
  onAddWatch: () => {},
  asked: false,
  ...overrides,
})

const render = (overrides: Partial<WorkbenchViewProps> = {}): string => renderToStaticMarkup(createElement(WorkbenchView, baseProps(overrides) as never))

test('pulse renders six index cards, the right-side move badge, the daily caption and the breadth bar', () => {
  const html = render()
  assert.equal((html.match(/class="chives-wb-index(?:\s|")/g) ?? []).length, 6)
  assert.match(html, /上证指数/)
  assert.match(html, /000001\.SH/)
  assert.match(html, /▼ -0\.82%/)
  assert.match(html, /日线/)
  assert.match(html, /chives-wb-index-price/)
  assert.match(html, /5200\.00 亿元/)
  assert.match(html, /chives-wb-breadth-track/)
  assert.match(html, /封板率 58%/)
})

test('an empty spark renders a dash instead of an empty hole', () => {
  const html = render()
  assert.match(html, /chives-wb-spark-empty/)
  assert.match(html, /—/)
})

test('engine summary shows the bold title, body, clickable refs and the relative update time', () => {
  const html = render()
  assert.match(html, /高位科技退潮/)
  assert.match(html, /更新于 5 分钟前/)
  assert.match(html, /chives-wb-ref/)
  assert.match(html, /农林牧渔/)
})

test('map module keeps the heat/rank switch plus the area-basis switch, defaulting to turnover', () => {
  const heat = render()
  assert.match(heat, /chives-treemap/)
  assert.match(heat, /行业图/)
  assert.match(heat, /成交额\(√\)/)
  assert.match(heat, /等权/)
  assert.match(heat, /aria-pressed="true"[^>]*>成交额\(√\)/)
  const table = render({ sectorView: 'table' })
  assert.match(table, /chives-wb-rank/)
  assert.match(table, /相对沪深300/)
})

test('the treemap always renders a tile name even for the smallest sector', () => {
  const html = render()
  assert.match(html, /chives-tile-name[^>]*>农林牧渔/)
})

test('gainers and losers sit side by side and the turnover board stays folded by default', () => {
  const html = render()
  assert.match(html, /涨幅榜/)
  assert.match(html, /跌幅榜/)
  assert.doesNotMatch(html, /贵州茅台/)
  const open = render({ activeOpen: true })
  assert.match(open, /贵州茅台/)
  assert.match(open, /成交额榜/)
})

test('a mover whose price changed gets the gold row pulse', () => {
  const html = render({ moverPulse: new Set(['600000']) })
  assert.match(html, /chives-wb-mover-row chives-row-pulse chives-up/)
})

test('mover rows show rank, name, price, signed change and amount', () => {
  const html = render()
  assert.match(html, /浦发银行/)
  assert.match(html, /▲ \+3\.20%/)
  assert.match(html, /12\.00 亿元/)
})

test('the focus block folds rules into a count badge, highlights only fired rules and shows the latest signal', () => {
  const html = render()
  assert.match(html, /我的盯盘/)
  assert.match(html, /2 条规则/)
  assert.match(html, /chives-chip is-triggered[^>]*>pct_up_3/)
  assert.doesNotMatch(html, /chives-chip is-triggered[^>]*>vol_2x/)
  assert.match(html, /进入进场区间/)
  assert.match(html, /is-triggered/)
  assert.match(html, /距涨停 10\.00%/)
  assert.match(html, /＋加自选/)
})

test('the rule popup lists every rule with its description and state', () => {
  const html = render()
  assert.match(html, /chives-wb-rules-pop/)
  assert.match(html, /放量 2 倍/)
  assert.match(html, /已武装/)
})

test('the portfolio card is present, folded, and reads no holdings data', () => {
  const html = render()
  assert.match(html, /<details class="chives-wb-portfolio">/)
  assert.match(html, /持仓页建设中/)
  assert.doesNotMatch(html, /总市值/)
})

test('the signal filter bar offers all four chips and filters both lists', () => {
  const html = render()
  assert.match(html, /待你决策/)
  assert.match(html, /我的票/)
  assert.match(html, /板块/)
  assert.match(html, /全部/)
  assert.match(html, /浦发银行 回到了进场位/)
})

test('the decide block holds the large card and the rail holds the rest', () => {
  const html = render({
    data: {
      ...data,
      signals: [
        signal(),
        signal({ id: 2, kind: 'risk', kindLabel: '风险 · 市场', decide: false, severity: 'L2', title: '宽度恶化', object: { type: 'market', code: '', name: '市场' }, context: null, primary: { label: '查看分析', action: 'open' } }),
      ],
    },
  })
  assert.match(html, /chives-sig-card is-plan is-hero/)
  assert.match(html, /宽度恶化/)
  assert.match(html, /chives-sig-rail/)
})

test('signal cards of every type carry their type class and a direction pill', () => {
  const html = render({
    data: {
      ...data,
      signals: [
        signal({ id: 1, kind: 'plan_entry', decide: false }),
        signal({ id: 2, kind: 'opportunity', decide: false, direction: 'neutral', directionLabel: '中性', title: '机会候选' }),
        signal({ id: 3, kind: 'risk', decide: false, direction: 'bear', directionLabel: '偏空', title: '风险提示' }),
        signal({ id: 4, kind: 'sector', decide: false, title: '板块异动' }),
        signal({ id: 5, kind: 'info', decide: false, title: '信息归并' }),
      ],
    },
  })
  for (const tone of ['plan', 'opp', 'risk', 'sector', 'info']) assert.match(html, new RegExp(`chives-sig-card is-${tone}`))
  assert.match(html, /▲ 偏多/)
  assert.match(html, /▼ 偏空/)
  assert.match(html, /— 中性/)
})

test('the range widget positions the zone, stop marker and price dot', () => {
  const html = render()
  assert.match(html, /data-ctx="range"/)
  assert.match(html, /chives-sig-zone/)
  assert.match(html, /止损/)
  assert.match(html, /chives-sig-price/)
})

test('the done fold reports today counts and hides the rows until expanded', () => {
  const folded = render()
  assert.match(folded, /今天已处理 12 条 · 已合并 19 条同类/)
  assert.doesNotMatch(folded, /早盘误报/)
  const open = render({ doneOpen: true })
  assert.match(open, /早盘误报/)
  assert.match(open, /重新打开/)
})

test('the fund-flow block renders three columns, the vendor note and northbound money', () => {
  const html = render()
  assert.match(html, /资金流向/)
  assert.match(html, /行业净流入榜/)
  assert.match(html, /行业净流出榜/)
  assert.match(html, /个股净流入榜/)
  assert.doesNotMatch(html, /个股净流出榜/)
  assert.match(html, /东财主力口径·仅作辅助参考/)
  assert.match(html, /北向净流入/)
  assert.match(html, /3\.20 亿元/)
  assert.match(html, /▲/)
})

test('the stock-out column appears only after "更多"', () => {
  const html = render({ flowsMore: true })
  assert.match(html, /个股净流出榜/)
  assert.match(html, /平安银行/)
})

test('northbound hides silently when the source says it is unavailable', () => {
  const html = render({ data: { ...data, northbound: { ok: true, available: false, reason: 'no source', asOf: null, netYuan: null } } })
  assert.doesNotMatch(html, /北向净流入/)
})

test('when the hub is down both signal areas show the empty state and raw alerts appear', () => {
  const html = render({ failures: { ...baseProps().failures, hub: true }, data: { ...data, signals: [], doneSignals: [] } })
  assert.match(html, /信号服务未启动/)
  assert.match(html, /原始告警/)
  assert.match(html, /板块跃升/)
})

test('the stock drawer shows quote, distance, rules and the analyses table', () => {
  const html = render({ drawer: { kind: 'stock', code: '600000', id: null } })
  assert.match(html, /个股详情/)
  assert.match(html, /该股规则/)
  assert.match(html, /最近分析/)
  assert.match(html, /已分析/)
})

test('the signal drawer shows sections and markdown as inert text', () => {
  const html = render({ drawer: { kind: 'signal', code: '', id: 1 } })
  assert.match(html, /信号详情/)
  assert.match(html, /进入进场区间，条件成立/)
  assert.match(html, /回踩 5 日线/)
  assert.match(html, /放量突破/)
  assert.doesNotMatch(html, /<h2[^>]*>结论/)
})

test('the rules drawer lists stock and R1-R6 rules plus the change history', () => {
  const html = render({ drawer: { kind: 'rules', code: '', id: null } })
  assert.match(html, /个股规则/)
  assert.match(html, /行业板块规则/)
  assert.match(html, /板块排名跃升/)
  assert.match(html, /变更历史/)
  assert.match(html, /agent/)
})

test('the analysis drawer renders plain text, not HTML', () => {
  const html = render({ drawer: { kind: 'analysis', code: '', id: 1 } })
  assert.match(html, /放量突破/)
  assert.match(html, /chives-mono/)
  assert.doesNotMatch(html, /<h2[^>]*>结论/)
})

test('the ask bar is present with the placeholder and a send affordance', () => {
  const html = render()
  assert.match(html, /问 Chives/)
  assert.match(html, /今天哪个行业最强/)
  assert.match(html, /chives-wb-ask/)
})

test('a toast offers undo only when the action can be reversed', () => {
  const html = render({ toast: { text: '已忽略，已记入「已处理」', undo: { type: 'reopen', id: 1 }, key: 1 } })
  assert.match(html, /chives-sig-toast/)
  assert.match(html, /撤销/)
  const plain = render({ toast: { text: '已启用计划', undo: null, key: 2 } })
  assert.match(plain, /已启用计划/)
  assert.doesNotMatch(plain, /撤销/)
})

test('narrow layouts declare the single column mode', () => {
  const html = render({ width: 1024 })
  assert.match(html, /data-layout="single"/)
})

test('rank and spark context widgets render their geometry', () => {
  const html = render({
    data: {
      ...data,
      signals: [
        signal({ id: 1, kind: 'sector', decide: true, context: { type: 'rank', from: 25, to: 3, sharePct: 4.1, spark: [1, 2, 3, 5] } }),
        signal({ id: 2, kind: 'opportunity', decide: false, context: { type: 'spark', points: [1, 2, 1.5, 3], label: '成交额' } }),
      ],
    },
  })
  assert.match(html, /data-ctx="rank"/)
  assert.match(html, /排名/)
  assert.match(html, /25 <span class="chives-sig-arrow">→<\/span> 3/)
  assert.match(html, /成交额占比 4\.1%/)
  assert.match(html, /data-ctx="spark"/)
  assert.match(html, /chives-sig-spark/)
})

test('merged cards carry the merged-similar tag', () => {
  const html = render({ data: { ...data, signals: [signal({ mergedCount: 7, decide: false })] } })
  assert.match(html, /已合并 7 条同类/)
})

test('each card exposes the primary, recheck, snooze and ignore actions', () => {
  const html = render()
  assert.match(html, /查看分析/)
  assert.match(html, /让 Chives 重看/)
  assert.match(html, /稍后提醒/)
  assert.match(html, /忽略/)
  assert.match(html, /30 分钟后/)
  assert.match(html, /收盘前/)
  assert.match(html, /明天开盘/)
})

test('a new card carries the breathing dot class and a seen card does not', () => {
  const fresh = render({ data: { ...data, signals: [signal({ status: 'new' })] } })
  assert.match(fresh, /chives-sig-new/)
  const seen = render({ data: { ...data, signals: [signal({ status: 'seen' })] } })
  assert.doesNotMatch(seen, /chives-sig-new/)
})

test('a stale flow payload shows its reason next to the data time', () => {
  const html = render({
    data: {
      ...data,
      flows: {
        ...data.flows,
        sector_in: { ...data.flows.sector_in!, stale: true, reason: '上游延迟 3 分钟' },
      },
    },
  })
  assert.match(html, /上游延迟 3 分钟/)
  assert.match(html, /chives-wb-meta is-stale/)
})
