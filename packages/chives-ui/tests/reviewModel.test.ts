import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  cardActionBody, describeCondition, groupSettings, lossStreakBody, moodBody, normalizeBreadthSeries, normalizeCard, normalizeDiscipline,
  normalizeLadder, normalizePoolHistory, normalizeReview, normalizeReviewList, normalizeSettings, normalizeThemes, normalizeCandidateStats,
  parseSettingInput, pendingSuggestionCount, regimeToEnv, reviewOverdue, seriesGeometry, settingBody, sizingText, sortCards, SETTING_RANGES,
} from '../src/client/reviewModel.ts'
import {
  validateCardAction, validateDisciplineAction, validateSettingAction,
} from '../../watch-panel/src/hubProxy.ts'

test('regime maps to the review vocabulary', () => {
  assert.equal(regimeToEnv('risk_on'), 'strong')
  assert.equal(regimeToEnv('risk_off'), 'weak')
  assert.equal(regimeToEnv('neutral'), 'neutral')
  assert.equal(regimeToEnv('x'), null)
})

test('settings: unknown keys dropped, suggestions kept, groups ordered', () => {
  const rows = normalizeSettings({ settings: [
    { key: 'per_trade_risk_pct', label: '单笔风险', unit: '%', value: null, source: 'unset', suggestion: { value: 1, basis: '按波动估算，未经回测', backtested: false, suggested_at: 't' } },
    { key: 'single_stock_cap_pct', label: '单票上限', unit: '%', value: 20, source: 'user_set', suggestion: null },
    { key: 'evil', value: 1 },
  ] })
  assert.deepEqual(rows.map((row) => row.key), ['per_trade_risk_pct', 'single_stock_cap_pct'])
  assert.equal(rows[0]!.suggestion!.value, 1)
  assert.equal(rows[1]!.source, 'user_set')
  assert.equal(pendingSuggestionCount(rows), 1)
  assert.deepEqual(groupSettings(rows).map((group) => group.id), ['position', 'risk'])
})

test('setting input parsing enforces the contract ranges and integers', () => {
  assert.equal(parseSettingInput('per_trade_risk_pct', '1.5'), 1.5)
  assert.equal(parseSettingInput('per_trade_risk_pct', '11'), null)
  assert.equal(parseSettingInput('per_trade_risk_pct', ''), null)
  assert.equal(parseSettingInput('per_trade_risk_pct', '-1'), null)
  assert.equal(parseSettingInput('per_trade_risk_pct', '1e1'), null)
  assert.equal(parseSettingInput('pause_loss_streak', '3'), 3)
  assert.equal(parseSettingInput('pause_loss_streak', '3.5'), null)
  assert.equal(parseSettingInput('emergency_index_drop_pct', '0.4'), null)
  assert.equal(parseSettingInput('nope', '1'), null)
  assert.equal(Object.keys(SETTING_RANGES).length, 11)
})

test('discipline normaliser reads the contract shape', () => {
  const d = normalizeDiscipline({ paused: true, reasons: [{ rule: 'loss_streak', value: 3, threshold: 3, text: '连亏' }], metrics: { day_drawdown_pct: 1.2, total_loss_pct: null, loss_streak: 3 },
    mood_today: { pre: 'calm', mid: null, post: { level: 'unfit' } }, headroom: { total_cap_pct: 60, top_theme: { name: '银行', weight_pct: 25 } } })
  assert.equal(d.paused, true)
  assert.equal(d.lossStreak, 3)
  assert.deepEqual(d.mood, { pre: 'calm', mid: null, post: 'unfit' })
  assert.equal(d.headroom.topTheme!.name, '银行')
  assert.equal(normalizeDiscipline(null).paused, false)
})

test('every condition type has Chinese wording', () => {
  const cases: Array<[unknown, RegExp]> = [
    [{ type: 'regime', values: ['strong', 'neutral'] }, /偏强 \/ 中性/],
    [{ type: 'index_pct', code: '000001.SH', op: '>=', value: 0.5 }, /000001\.SH 涨跌幅 ≥ 0\.5%/],
    [{ type: 'sector_change', sector_code: 'BK1000', op: '>=', value: 1 }, /板块 BK1000 涨幅 ≥ 1%/],
    [{ type: 'sector_rank', sector_code: 'BK1000', op: '<=', value: 5 }, /排名 ≤ 5/],
    [{ type: 'price_cross', direction: 'down', level: 8.5 }, /下破 8\.5/],
    [{ type: 'price_in_range', lo: 9, hi: 9.5 }, /进入 9–9\.5/],
    [{ type: 'pct_change', direction: 'up', threshold_pct: 3 }, /上行达 3%/],
    [{ type: 'open_pct', op: '>=', value: 2 }, /开盘涨幅 ≥ 2%/],
    [{ type: 'volume_ratio', op: '>=', value: 1.5 }, /量能倍数 ≥ 1\.5/],
  ]
  for (const [cond, re] of cases) assert.match(describeCondition(cond).text, re)
  assert.equal(describeCondition({ type: 'weird' }).text, 'weird')
})

test('card normaliser, sizing wording and ordering', () => {
  const raw = (id: number, status: string, state: string) => ({ id, code: '600000.SH', name: '浦发银行', status, state, thesis: 't', risk: { stop_price: 8.6, exit_rules: ['破位离场'] },
    stock_conditions: [{ type: 'price_in_range', lo: 9, hi: 9.5 }], giveup: [{ type: 'price_cross', direction: 'down', level: 8.5 }],
    sizing: { risk_budget_cny: 1000, final_position_cny: 25000, final_qty_shares: 2700, capped_by: 'single_stock_cap', note: '' }, tags: { streak: 2, theme: '银行', env: 'strong' }, locked_at: '2026-11-04T09:25:00+08:00' })
  const cards = [raw(3, 'active', 'observe'), raw(2, 'active', 'execute'), raw(1, 'proposed', 'observe')].map(normalizeCard)
  assert.ok(cards.every((card) => card !== null))
  const sorted = sortCards(cards as never)
  assert.deepEqual(sorted.map((card) => card.id), [1, 2, 3])
  assert.equal(sorted[0]!.locked, true)
  assert.match(sizingText(sorted[0]!.sizing), /2\.50万（约 2700 股）/)
  assert.equal(sizingText(null), '—')
  assert.equal(normalizeCard({ foo: 1 }), null)
  assert.equal(normalizeCard({ id: 1, state: 'bogus' })!.state, 'observe')
})

test('reviews: list, detail, overdue rule', () => {
  const list = normalizeReviewList({ reviews: [{ date: '2026-11-04', kind: 'evening', env: { label: 'strong' }, candidates: [1, 2], pending: ['x'], revision: 2 }, { date: 'bad' }] })
  assert.equal(list.length, 1)
  assert.equal(list[0]!.candidates, 2)
  const detail = normalizeReview({ review: { date: '2026-11-04', kind: 'evening', env: { label: 'weak', evidence: ['a'], differs_from_rule: true }, mainline: { name: '电子', note: 'n' },
    candidates: [{ code: '600000.SH', reason: 'r', card_id: 7, tags: { streak: 2 } }], checklist: [{ item: 'i', ok: true }], body_markdown: '## x' } })
  assert.equal(detail!.envLabel, 'weak')
  assert.equal(detail!.candidates[0]!.cardId, 7)
  assert.equal(normalizeReview({ review: { date: 'x' } }), null)
  const evening = (h: number, day = 4) => new Date(2026, 10, day, h, 0, 0) // Nov 4 2026 is a Wednesday
  assert.equal(reviewOverdue(evening(19), []), false)
  assert.equal(reviewOverdue(evening(20), []), true)
  assert.equal(reviewOverdue(evening(21), list), false)
  assert.equal(reviewOverdue(evening(21, 7), []), false) // Saturday
})

test('market normalisers keep gaps and drop malformed rows', () => {
  const days = normalizePoolHistory({ days: [{ date: '2026-10-14', available: false }, { date: '2026-10-15', available: true, zt: 36, zb: 7, seal_ratio_pct: 83.7 }, { date: 'bad' }] })
  assert.equal(days.length, 2)
  assert.equal(days[0]!.available, false)
  assert.equal(days[1]!.sealRatioPct, 83.7)
  const ladder = normalizeLadder({ max_streak: 3, tiers: [{ streak: 3, count: 2, rows: [{ name: 'A' }, { name: 'B' }] }, { streak: 0 }] })
  assert.deepEqual(ladder.tiers.map((tier) => tier.names.length), [2])
  assert.equal(normalizeThemes({ rows: [{ code: 'BK1', name: 'x', change_pct: 1 }] })[0]!.rank, 1)
  const series = normalizeBreadthSeries({ points: [{ t: '09:31', up: 1, down: 2 }, { t: 'x', up: 1, down: 1 }], gaps: true })
  assert.equal(series.points.length, 1)
  assert.equal(series.gaps, true)
  assert.equal(normalizeCandidateStats({ n: 3 }).insufficient, true)
})

test('seriesGeometry breaks lines at missing values instead of interpolating', () => {
  const g = seriesGeometry([[1, 2, null, 4, 5]], 100, 20)!
  assert.equal((g.paths[0]!.match(/M/g) ?? []).length, 2)
  assert.ok(g.paths[0]!.startsWith('M0.0,'))
  assert.equal(seriesGeometry([[null, null]], 100, 20), null)
  assert.equal(seriesGeometry([[1]], 100, 20), null)
  const flat = seriesGeometry([[5, 5, 5]], 100, 20)!
  assert.ok(Number.isFinite(flat.min) && flat.max > flat.min)
})

test('every action body the page can send is accepted by the Host proxy validators', () => {
  for (const key of Object.keys(SETTING_RANGES)) {
    for (const body of [settingBody(key, 'adopt'), settingBody(key, 'clear'), settingBody(key, 'dismiss'), settingBody(key, 'set', SETTING_RANGES[key]![0] + 1)]) {
      assert.ok(validateSettingAction(body) !== null, JSON.stringify(body))
    }
  }
  for (const body of [lossStreakBody('add'), lossStreakBody('reset'), moodBody('pre', 'calm'), moodBody('mid', 'volatile'), moodBody('post', 'unfit')]) {
    assert.ok(validateDisciplineAction(body) !== null, JSON.stringify(body))
  }
  for (const body of [cardActionBody(7, 'confirm'), cardActionBody(7, 'cancel'), cardActionBody(7, 'tighten_stop', 8.8), cardActionBody(7, 'set_state', 'abandon'), cardActionBody(7, 'set_state', 'exit')]) {
    assert.ok(validateCardAction(body) !== null, JSON.stringify(body))
  }
})

test('condition lights come from the engine `conds` arrays and are absent when it has not reported', () => {
  const base = { id: 1, stock_conditions: [{ type: 'price_in_range', lo: 9, hi: 9.5 }, { type: 'pct_change', direction: 'up', threshold_pct: 3 }], market_conditions: [{ type: 'regime', values: ['strong'] }], giveup: [{ type: 'price_cross', direction: 'down', level: 8.5 }] }
  const lit = normalizeCard({ ...base, conds: { market: [true], stock: [true, null], giveup: [false], sector: [] } })!
  assert.deepEqual(lit.stock.map((c) => c.ok), [true, null])
  assert.equal(lit.market[0]!.ok, true)
  assert.equal(lit.giveup[0]!.ok, false)
  const dark = normalizeCard(base)!
  assert.ok(dark.stock.every((c) => c.ok === undefined) && dark.market[0]!.ok === undefined)
  const short = normalizeCard({ ...base, conds: { stock: [true] } })!
  assert.deepEqual(short.stock.map((c) => c.ok), [true, undefined])
})
