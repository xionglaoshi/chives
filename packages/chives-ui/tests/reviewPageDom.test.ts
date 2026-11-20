import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { ReactElement } from 'react'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { zh } from '../src/client/locales.ts'
import {
  normalizeBreadthSeries, normalizeCandidateStats, normalizeCards, normalizeDiscipline, normalizeIndustryZt, normalizeLadder, normalizePoolHistory,
  normalizeReview, normalizeReviewList, normalizeSettings, normalizeThemes, normalizeYesterday,
} from '../src/client/reviewModel.ts'
import { loadClientModule } from './tsx.ts'

type Component = (props: never) => ReactElement
const mod = await loadClientModule('reviewPage.tsx')
const ReviewPageView = mod.ReviewPageView as Component

const t = (key: keyof typeof zh, params?: Record<string, unknown>): string => {
  let value: string = zh[key]
  for (const [name, replacement] of Object.entries(params ?? {})) value = value.replace(`{${name}}`, String(replacement))
  return value
}

const rawCard = (id: number, status: string, state: string) => ({
  id, code: '600000.SH', name: '浦发银行', status, state, thesis: '回踩区间观察', last_price: 9.3,
  risk: { stop_price: 8.6, exit_rules: ['破位离场'] },
  stock_conditions: [{ type: 'price_in_range', lo: 9, hi: 9.5 }], giveup: [{ type: 'price_cross', direction: 'down', level: 8.5 }],
  market_conditions: [{ type: 'regime', values: ['strong'] }],
  sizing: { risk_budget_cny: 1000, stop_distance_pct: 4.4, final_position_cny: 25000, final_qty_shares: 2700, capped_by: 'single_stock_cap', note: '' },
  tags: { streak: 2, theme: '银行', env: 'strong' }, judgement: state === 'execute' ? { action: '按预案执行', reason: '板块仍强', next_check: '10:30', risk: '8.6' } : null,
  history: [{ ts: '2026-11-04T09:31:00+08:00', from: 'observe', to: state, reason: '条件到达' }],
})

const base = () => ({
  t,
  now: new Date(2026, 10, 4, 21, 0, 0),
  cards: normalizeCards({ cards: [rawCard(3, 'active', 'observe'), rawCard(2, 'active', 'execute'), rawCard(1, 'proposed', 'observe')] }),
  discipline: normalizeDiscipline({ paused: false, metrics: { loss_streak: 1 }, mood_today: { pre: 'calm' }, headroom: { total_cap_pct: 60, position_ratio_pct: 40, top_weight_pct: 25, single_cap_pct: 30 } }),
  settings: normalizeSettings({ settings: [
    { key: 'per_trade_risk_pct', label: '单笔可承受亏损', unit: '%', value: null, source: 'unset', suggestion: { value: 1, basis: '按组合波动估算', backtested: false } },
    { key: 'single_stock_cap_pct', label: '单票上限', unit: '%', value: 30, source: 'user_set', suggestion: null },
  ] }),
  reviews: normalizeReviewList({ reviews: [{ date: '2026-11-04', kind: 'evening', env: { label: 'strong' }, candidates: [1], pending: [] }] }),
  detail: normalizeReview({ review: { date: '2026-11-04', kind: 'evening', env: { label: 'strong', evidence: ['封板率 78%'] }, mainline: { name: '电子', note: '联动' },
    candidates: [{ code: '600000.SH', reason: '回踩观察' }], pending: ['龙虎榜待确认'], checklist: [{ item: '数据截点', ok: true }], body_markdown: '## 正文', data_cutoff: '19:45', sources: ['market-watch'] } }),
  selected: '2026-11-04|evening',
  onSelect: () => {}, openCard: null, onToggleCard: () => {}, onCardAction: () => {}, onSetting: () => {}, onDiscipline: () => {}, onAsk: () => {},
  busy: false, failed: false, notice: null,
  market: {
    poolHistory: normalizePoolHistory({ days: [{ date: '2026-10-14', available: false }, { date: '2026-10-15', available: true, zt: 36, zb: 7, dt: 3, seal_ratio_pct: 83.7 }, { date: '2026-10-16', available: true, zt: 61, zb: 49, dt: 5, seal_ratio_pct: 55.5, promote_1to2_pct: 13.3 }] }),
    ladder: normalizeLadder({ max_streak: 3, tiers: [{ streak: 3, count: 2, rows: [{ name: '高争民爆' }] }, { streak: 2, count: 9, rows: [] }] }),
    themes: normalizeThemes({ rows: [{ code: 'BK1', name: '芯片', change_pct: 2.5 }] }),
    industry: normalizeIndustryZt({ rows: [{ industry: '电子', zt_count: 12, zb_count: 3 }] }),
    yesterday: normalizeYesterday({ date: '2026-11-04', prev_date: '2026-11-03', rows: [{}], avg_open_pct: 1.75, avg_close_pct: -0.32, win_ratio_pct: 37.5 }),
    breadth: normalizeBreadthSeries({ points: [{ t: '09:31', up: 2000, down: 1000 }, { t: '09:32', up: 2100, down: 900 }] }),
    stats: normalizeCandidateStats({ n: 3 }),
  },
})

const render = (overrides: Record<string, unknown> = {}): string => renderToStaticMarkup(createElement(ReviewPageView as never, { ...base(), ...overrides } as never))

test('cards: proposed first, state chips, conditions only when expanded', () => {
  const html = render()
  assert.ok(html.indexOf('data-card="1"') < html.indexOf('data-card="2"'), 'proposed card comes first')
  assert.match(html, /待你确认/)
  assert.match(html, /按预案执行/)
  assert.match(html, /Chives 判断/)
  assert.match(html, /2\.70万|2\.50万/)
  assert.ok(!html.includes('回踩 9') && !/放弃条件/.test(html), 'conditions are collapsed by default')
  const open = render({ openCard: 2 })
  assert.match(open, /价格进入 9–9\.5/)
  assert.match(open, /价格下破 8\.5/)
  assert.match(open, /市场环境为 偏强/)
})

test('card buttons: confirm only for proposed, tighten only for active', () => {
  const html = render({ openCard: 2 })
  assert.match(html, /确认预案/)
  assert.equal((html.match(/确认预案/g) ?? []).length, 1)
  assert.match(html, /收紧止损/)
})

test('settings: suggestion shows basis, not-backtested warning and adopt/dismiss; adopted values never claim to be suggestions', () => {
  const html = render()
  assert.match(html, /Chives 建议 1%/)
  assert.match(html, /未经回测/)
  assert.match(html, /按组合波动估算/)
  assert.match(html, /采纳/)
  assert.match(html, /忽略/)
  assert.match(html, /自己设置/)
  assert.match(html, /建议不会自动生效/)
})

test('discipline: paused banner, mood buttons and headroom', () => {
  const html = render({ discipline: normalizeDiscipline({ paused: true, reasons: [{ rule: 'loss_streak', text: '连亏 3 笔' }], metrics: { loss_streak: 3 }, mood_today: { pre: 'unfit' } }) })
  assert.match(html, /纪律暂停/)
  assert.match(html, /连亏 3 笔/)
  assert.match(html, /不适合交易/)
  const normal = render()
  assert.ok(!/role="alert"/.test(normal))
  assert.match(normal, /总仓位\/上限/)
})

test('review record shows evidence, candidates, pending items and the checklist; the body is behind a toggle', () => {
  const html = render()
  assert.match(html, /封板率 78%/)
  assert.match(html, /龙虎榜待确认/)
  assert.match(html, /数据截点 19:45/)
  assert.match(html, /查看完整正文/)
  assert.ok(!html.includes('## 正文'), 'the markdown body is collapsed by default')
})

test('overdue banner after 20:00 without an evening review; none once it exists or before 20:00', () => {
  assert.match(render({ reviews: [], detail: null, selected: null }), /今天的晚间复盘还没有生成/)
  assert.ok(!/今天的晚间复盘还没有生成/.test(render()))
  assert.ok(!/今天的晚间复盘还没有生成/.test(render({ now: new Date(2026, 10, 4, 15, 0, 0), reviews: [], detail: null, selected: null })))
})

test('charts: missing days are counted, not drawn; sample-insufficient stats say so', () => {
  const html = render()
  assert.match(html, /1 天无数据/)
  assert.match(html, /封板率与晋级率/)
  assert.match(html, /高争民爆/)
  assert.match(html, /行业口径/)
  assert.match(html, /样本 3 个，不足以下结论/)
  assert.match(html, /昨日涨停今日表现/)
})

test('empty and failing states render without throwing', () => {
  const empty = render({ cards: null, discipline: null, settings: null, reviews: null, detail: null, selected: null, market: {
    poolHistory: null, ladder: null, themes: null, industry: null, yesterday: null, breadth: null, stats: null } })
  assert.match(empty, /加载中/)
  const none = render({ cards: [], settings: [], reviews: [], detail: null, selected: null, failed: true })
  assert.match(none, /还没有作战卡/)
  assert.match(none, /数据暂时取不到/)
})

test('no order entry anywhere on the page', () => {
  const html = render({ openCard: 2 })
  const buttons = [...html.matchAll(/<button[^>]*>(.*?)<\/button>/g)].map((match) => match[1] ?? '')
  for (const label of buttons) assert.ok(!/买入|卖出|下单|交易(?!日)|buy|sell/i.test(label.replace('不适合交易', '')), label)
})

test('expanded cards render a light per condition only when the engine reported', () => {
  const lit = normalizeCards({ cards: [{ ...rawCard(2, 'active', 'execute'), conds: { market: [true], sector: [], stock: [true], giveup: [false] } }] })
  const html = render({ cards: lit, openCard: 2 })
  assert.equal((html.match(/chives-rv-light/g) ?? []).length, 3)
  assert.match(html, /is-met/)
  assert.match(html, /is-unmet/)
  const dark = render({ openCard: 2 })
  assert.ok(!dark.includes('chives-rv-light'))
})
