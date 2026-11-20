/**
 * "复盘" page view model (pure, no DOM): normalisers for the hub v1.1 and
 * market-watch v1.4 payloads, condition/sizing wording, chart geometry and the
 * exact request bodies the Host proxy accepts (see T109 validators).
 */

export const REVIEW_PANEL_ID = 'chives-review'

export const HUB_SETTINGS_PATH = '/api/hub/settings'
export const HUB_DISCIPLINE_PATH = '/api/hub/discipline'
export const HUB_REVIEWS_PATH = '/api/hub/reviews'
export const HUB_REVIEW_PATH = '/api/hub/review'
export const HUB_CARDS_PATH = '/api/hub/cards'
export const HUB_CANDIDATE_STATS_PATH = '/api/hub/candidates-stats'
export const HUB_SETTING_ACTION_PATH = '/api/hub/setting-action'
export const HUB_DISCIPLINE_ACTION_PATH = '/api/hub/discipline-action'
export const HUB_CARD_ACTION_PATH = '/api/hub/card-action'
export const MARKET_POOL_HISTORY_PATH = '/api/market/pool-history'
export const MARKET_POOL_LADDER_PATH = '/api/market/pool-ladder'
export const MARKET_POOL_YESTERDAY_PATH = '/api/market/pool-yesterday'
export const MARKET_POOL_INDUSTRY_PATH = '/api/market/pool-by-industry'
export const MARKET_BREADTH_SERIES_PATH = '/api/market/breadth-series'
export const MARKET_THEMES_PATH = '/api/market/themes'

export const DASH = '—'

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function obj(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/* ------------------------------------------------------------------ env label */

export type EnvLabel = 'strong' | 'neutral' | 'weak'

export function envLabelOf(value: unknown): EnvLabel | null {
  return value === 'strong' || value === 'neutral' || value === 'weak' ? value : null
}

/** market-watch `regime.label` (risk_on / neutral / risk_off) to the review vocabulary. */
export function regimeToEnv(value: unknown): EnvLabel | null {
  if (value === 'risk_on') return 'strong'
  if (value === 'risk_off') return 'weak'
  if (value === 'neutral') return 'neutral'
  return envLabelOf(value)
}

/* ------------------------------------------------------------------- settings */

export interface SettingSuggestion {
  value: number
  basis: string
  backtested: boolean
  suggestedAt: string | null
}

export type SettingSource = 'unset' | 'adopted' | 'user_set'

export interface SettingRow {
  key: string
  label: string
  unit: string
  value: number | null
  source: SettingSource
  suggestion: SettingSuggestion | null
  updatedAt: string | null
}

export const SETTING_GROUPS: ReadonlyArray<{ id: 'position' | 'risk' | 'pause' | 'emergency'; keys: readonly string[] }> = [
  { id: 'position', keys: ['total_cap_strong_pct', 'total_cap_neutral_pct', 'total_cap_weak_pct', 'single_stock_cap_pct', 'theme_cap_pct'] },
  { id: 'risk', keys: ['per_trade_risk_pct'] },
  { id: 'pause', keys: ['pause_day_drawdown_pct', 'pause_total_loss_pct', 'pause_loss_streak'] },
  { id: 'emergency', keys: ['emergency_index_drop_pct', 'emergency_limit_down_count'] },
]

/** Allowed ranges, mirrored from the contract so the inputs can refuse early. */
export const SETTING_RANGES: Readonly<Record<string, readonly [number, number]>> = {
  total_cap_strong_pct: [0, 100],
  total_cap_neutral_pct: [0, 100],
  total_cap_weak_pct: [0, 100],
  single_stock_cap_pct: [0, 100],
  theme_cap_pct: [0, 100],
  per_trade_risk_pct: [0, 10],
  pause_day_drawdown_pct: [0, 30],
  pause_total_loss_pct: [0, 60],
  pause_loss_streak: [1, 20],
  emergency_index_drop_pct: [0.5, 10],
  emergency_limit_down_count: [5, 500],
}

export function normalizeSettings(payload: unknown): SettingRow[] {
  const rows: SettingRow[] = []
  for (const raw of arr(obj(payload).settings)) {
    const row = obj(raw)
    const key = str(row.key)
    if (!(key in SETTING_RANGES)) continue
    const sourceRaw = str(row.source)
    const source: SettingSource = sourceRaw === 'adopted' || sourceRaw === 'user_set' ? sourceRaw : 'unset'
    const sg = obj(row.suggestion)
    const suggestedValue = num(sg.value)
    rows.push({
      key,
      label: str(row.label) || key,
      unit: str(row.unit),
      value: num(row.value),
      source,
      suggestion: suggestedValue === null ? null : {
        value: suggestedValue,
        basis: str(sg.basis),
        backtested: sg.backtested === true,
        suggestedAt: str(sg.suggested_at) || null,
      },
      updatedAt: str(row.updated_at) || null,
    })
  }
  return rows
}

export function groupSettings(rows: readonly SettingRow[]): Array<{ id: string; rows: SettingRow[] }> {
  const byKey = new Map(rows.map((row) => [row.key, row]))
  return SETTING_GROUPS.map((group) => ({
    id: group.id,
    rows: group.keys.map((key) => byKey.get(key)).filter((row): row is SettingRow => row !== undefined),
  })).filter((group) => group.rows.length > 0)
}

/** Whether the typed text is a legal value for the key (empty is never legal). */
export function parseSettingInput(key: string, text: string): number | null {
  const range = SETTING_RANGES[key]
  if (!range || !/^\d+(\.\d+)?$/.test(text.trim())) return null
  const value = Number(text.trim())
  if (!Number.isFinite(value) || value < range[0] || value > range[1]) return null
  if (key === 'pause_loss_streak' || key === 'emergency_limit_down_count') return Number.isInteger(value) ? value : null
  return value
}

export function pendingSuggestionCount(rows: readonly SettingRow[]): number {
  return rows.filter((row) => row.suggestion !== null).length
}

/* ----------------------------------------------------------------- discipline */

export type MoodSlot = 'pre' | 'mid' | 'post'
export type MoodLevel = 'calm' | 'volatile' | 'unfit'

export interface Discipline {
  paused: boolean
  reasons: Array<{ rule: string; value: number | null; threshold: number | null; text: string }>
  dayDrawdownPct: number | null
  totalLossPct: number | null
  lossStreak: number
  mood: Record<MoodSlot, MoodLevel | null>
  headroom: {
    totalCapPct: number | null
    positionRatioPct: number | null
    totalRoomPct: number | null
    singleCapPct: number | null
    topWeightPct: number | null
    singleRoomPct: number | null
    themeCapPct: number | null
    topTheme: { name: string; weightPct: number | null } | null
    themeRoomPct: number | null
  }
}

function moodOf(value: unknown): MoodLevel | null {
  const raw = typeof value === 'object' && value !== null ? (value as { level?: unknown }).level : value
  return raw === 'calm' || raw === 'volatile' || raw === 'unfit' ? raw : null
}

export function normalizeDiscipline(payload: unknown): Discipline {
  const root = obj(payload)
  const metrics = obj(root.metrics)
  const mood = obj(root.mood_today)
  const head = obj(root.headroom)
  const theme = obj(head.top_theme)
  return {
    paused: root.paused === true,
    reasons: arr(root.reasons).map((item) => {
      const row = obj(item)
      return { rule: str(row.rule), value: num(row.value), threshold: num(row.threshold), text: str(row.text) }
    }),
    dayDrawdownPct: num(metrics.day_drawdown_pct),
    totalLossPct: num(metrics.total_loss_pct),
    lossStreak: Math.max(0, Math.trunc(num(metrics.loss_streak) ?? 0)),
    mood: { pre: moodOf(mood.pre), mid: moodOf(mood.mid), post: moodOf(mood.post) },
    headroom: {
      totalCapPct: num(head.total_cap_pct),
      positionRatioPct: num(head.position_ratio_pct),
      totalRoomPct: num(head.total_room_pct),
      singleCapPct: num(head.single_cap_pct),
      topWeightPct: num(head.top_weight_pct),
      singleRoomPct: num(head.single_room_pct),
      themeCapPct: num(head.theme_cap_pct),
      topTheme: Object.keys(theme).length === 0 ? null : { name: str(theme.name), weightPct: num(theme.weight_pct) },
      themeRoomPct: num(head.theme_room_pct),
    },
  }
}

/* ---------------------------------------------------------------------- cards */

export type CardState = 'observe' | 'await_confirm' | 'execute' | 'abandon' | 'exit'
export type CardStatus = 'proposed' | 'active' | 'expired' | 'cancelled' | 'closed'

export interface CardCondition {
  type: string
  text: string
  /** Live result from the watch engine: true met, false not met, null no data; undefined when the engine has not reported. */
  ok?: boolean | null
}

export interface CardSizing {
  riskBudgetCny: number | null
  stopDistancePct: number | null
  finalPositionCny: number | null
  finalQtyShares: number | null
  cappedBy: string
  note: string
}

export interface CardJudgement {
  action: string
  reason: string
  nextCheck: string
  risk: string
  ts: string | null
}

export interface ReviewCard {
  id: number
  code: string
  name: string
  status: CardStatus
  state: CardState
  thesis: string
  tags: { streak: number | null; theme: string; env: EnvLabel | null }
  market: CardCondition[]
  sector: CardCondition[]
  stock: CardCondition[]
  giveup: CardCondition[]
  stopPrice: number | null
  exitRules: string[]
  sizing: CardSizing | null
  judgement: CardJudgement | null
  history: Array<{ ts: string; from: string; to: string; reason: string }>
  lastPrice: number | null
  expiresAt: string | null
  locked: boolean
  late: boolean
  proposedBy: string
  confirmPolicy: string
}

export const CARD_STATES: readonly CardState[] = ['observe', 'await_confirm', 'execute', 'abandon', 'exit']

function cardState(value: unknown): CardState {
  return (CARD_STATES as readonly string[]).includes(String(value)) ? value as CardState : 'observe'
}

function cardStatus(value: unknown): CardStatus {
  const text = String(value)
  return text === 'proposed' || text === 'active' || text === 'expired' || text === 'cancelled' || text === 'closed' ? text : 'active'
}

const OP_TEXT: Record<string, string> = { '>=': '≥', '<=': '≤' }
const ENV_TEXT: Record<EnvLabel, string> = { strong: '偏强', neutral: '中性', weak: '偏弱' }
export const ENV_ZH = ENV_TEXT

function fmt(value: number | null, digits = 2): string {
  if (value === null) return DASH
  const text = value.toFixed(digits)
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text
}

/** One-line Chinese wording for a condition (whitelisted types only; unknown types are shown verbatim). */
export function describeCondition(raw: unknown): CardCondition {
  const cond = obj(raw)
  const type = str(cond.type)
  const op = OP_TEXT[str(cond.op)] ?? str(cond.op)
  const value = num(cond.value)
  const up = cond.direction === 'up'
  switch (type) {
    case 'regime': {
      const values = arr(cond.values).map((item) => envLabelOf(item)).filter((item): item is EnvLabel => item !== null)
      return { type, text: `市场环境为 ${values.map((item) => ENV_TEXT[item]).join(' / ') || DASH}` }
    }
    case 'index_pct':
      return { type, text: `${str(cond.code)} 涨跌幅 ${op} ${fmt(value)}%` }
    case 'sector_change':
      return { type, text: `板块 ${str(cond.sector_code)} 涨幅 ${op} ${fmt(value)}%` }
    case 'sector_rank':
      return { type, text: `板块 ${str(cond.sector_code)} 排名 ${op} ${fmt(value, 0)}` }
    case 'price_cross':
      return { type, text: `价格${up ? '上穿' : '下破'} ${fmt(num(cond.level))}` }
    case 'price_in_range':
      return { type, text: `价格进入 ${fmt(num(cond.lo))}–${fmt(num(cond.hi))}` }
    case 'pct_change':
      return { type, text: `涨跌幅${up ? '上行' : '下行'}达 ${fmt(num(cond.threshold_pct))}%` }
    case 'open_pct':
      return { type, text: `开盘涨幅 ${op} ${fmt(value)}%` }
    case 'volume_ratio':
      return { type, text: `量能倍数 ${op} ${fmt(value)}` }
    default:
      return { type, text: type || DASH }
  }
}

function lightAt(lights: unknown, index: number): boolean | null | undefined {
  if (!Array.isArray(lights) || index >= lights.length) return undefined
  const value = lights[index]
  return value === true ? true : value === false ? false : null
}

function withLights(items: unknown, lights: unknown): CardCondition[] {
  return arr(items).map((item, index) => {
    const cond = describeCondition(item)
    const ok = lightAt(lights, index)
    return ok === undefined ? cond : { ...cond, ok }
  })
}

export function normalizeCard(raw: unknown): ReviewCard | null {
  const row = obj(raw)
  const conds = obj(row.conds)
  const id = num(row.id)
  if (id === null) return null
  const risk = obj(row.risk)
  const sizing = obj(row.sizing)
  const judgement = obj(row.judgement)
  const tags = obj(row.tags)
  return {
    id,
    code: str(row.code),
    name: str(row.name),
    status: cardStatus(row.status),
    state: cardState(row.state),
    thesis: str(row.thesis),
    tags: { streak: num(tags.streak), theme: str(tags.theme), env: envLabelOf(tags.env) },
    market: withLights(row.market_conditions, conds.market),
    sector: withLights(row.sector_conditions, conds.sector),
    stock: withLights(row.stock_conditions, conds.stock),
    giveup: withLights(row.giveup, conds.giveup),
    stopPrice: num(risk.stop_price),
    exitRules: arr(risk.exit_rules).map((item) => str(item)).filter(Boolean),
    sizing: Object.keys(sizing).length === 0 ? null : {
      riskBudgetCny: num(sizing.risk_budget_cny),
      stopDistancePct: num(sizing.stop_distance_pct),
      finalPositionCny: num(sizing.final_position_cny),
      finalQtyShares: num(sizing.final_qty_shares),
      cappedBy: str(sizing.capped_by),
      note: str(sizing.note),
    },
    judgement: Object.keys(judgement).length === 0 ? null : {
      action: str(judgement.action),
      reason: str(judgement.reason),
      nextCheck: str(judgement.next_check),
      risk: str(judgement.risk),
      ts: str(judgement.ts) || null,
    },
    history: arr(row.history).map((item) => {
      const h = obj(item)
      return { ts: str(h.ts), from: str(h.from), to: str(h.to), reason: str(h.reason) }
    }),
    lastPrice: num(row.last_price),
    expiresAt: str(row.expires_at) || null,
    locked: str(row.locked_at) !== '',
    late: row.late === true,
    proposedBy: str(row.proposed_by),
    confirmPolicy: str(row.confirm_policy) || 'all',
  }
}

export function normalizeCards(payload: unknown): ReviewCard[] {
  return arr(obj(payload).cards).map(normalizeCard).filter((card): card is ReviewCard => card !== null)
}

const STATE_ORDER: Record<CardState, number> = { execute: 0, exit: 1, abandon: 2, await_confirm: 3, observe: 4 }

/** Proposed cards first (they need a decision), then by state urgency, then id. */
export function sortCards(cards: readonly ReviewCard[]): ReviewCard[] {
  return [...cards].sort((a, b) => {
    const pa = a.status === 'proposed' ? 0 : 1
    const pb = b.status === 'proposed' ? 0 : 1
    if (pa !== pb) return pa - pb
    if (STATE_ORDER[a.state] !== STATE_ORDER[b.state]) return STATE_ORDER[a.state] - STATE_ORDER[b.state]
    return a.id - b.id
  })
}

export function sizingText(sizing: CardSizing | null): string {
  if (!sizing || sizing.finalPositionCny === null) return DASH
  const qty = sizing.finalQtyShares === null ? '' : `（约 ${sizing.finalQtyShares} 股）`
  return `${formatCny(sizing.finalPositionCny)}${qty}`
}

export function formatCny(value: number | null): string {
  if (value === null) return DASH
  const abs = Math.abs(value)
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(0)
}

/* -------------------------------------------------------------------- reviews */

export type ReviewKind = 'evening' | 'premarket'

export interface ReviewSummary {
  date: string
  kind: ReviewKind
  envLabel: EnvLabel | null
  candidates: number
  pending: number
  revision: number
  createdAt: string | null
}

export interface ReviewDetail {
  date: string
  kind: ReviewKind
  envLabel: EnvLabel | null
  evidence: string[]
  differsFromRule: boolean
  differsNote: string
  mainline: { name: string; note: string } | null
  themes: Array<{ name: string; note: string }>
  events: Array<{ date: string; target: string; type: string; source: string; uncertain: boolean; note: string }>
  yesterdayFeedback: string
  candidates: Array<{ code: string; reason: string; cardId: number | null; streak: number | null; theme: string }>
  pending: string[]
  checklist: Array<{ item: string; ok: boolean; note: string }>
  dataCutoff: string
  sources: string[]
  lhbNote: string
  ladderNote: string
  bodyMarkdown: string
  revision: number
}

function kindOf(value: unknown): ReviewKind {
  return value === 'premarket' ? 'premarket' : 'evening'
}

export function normalizeReviewList(payload: unknown): ReviewSummary[] {
  return arr(obj(payload).reviews).map((raw) => {
    const row = obj(raw)
    const env = obj(row.env)
    return {
      date: str(row.date),
      kind: kindOf(row.kind),
      envLabel: envLabelOf(env.label ?? row.env_label),
      candidates: Array.isArray(row.candidates) ? row.candidates.length : Math.trunc(num(row.candidates) ?? num(row.candidate_count) ?? 0),
      pending: Array.isArray(row.pending) ? row.pending.length : Math.trunc(num(row.pending) ?? num(row.pending_count) ?? 0),
      revision: Math.trunc(num(row.revision) ?? 1),
      createdAt: str(row.created_at) || str(row.updated_at) || null,
    }
  }).filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date))
}

export function normalizeReview(payload: unknown): ReviewDetail | null {
  const root = obj(payload)
  const row = obj(root.review ?? root)
  const date = str(row.date)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null
  const env = obj(row.env)
  const main = obj(row.mainline)
  return {
    date,
    kind: kindOf(row.kind),
    envLabel: envLabelOf(env.label),
    evidence: arr(env.evidence).map((item) => str(item)).filter(Boolean),
    differsFromRule: env.differs_from_rule === true,
    differsNote: str(env.differs_note),
    mainline: Object.keys(main).length === 0 ? null : { name: str(main.name), note: str(main.note) },
    themes: arr(row.themes).map((item) => ({ name: str(obj(item).name), note: str(obj(item).note) })),
    events: arr(row.events).map((item) => {
      const e = obj(item)
      return { date: str(e.date), target: str(e.target), type: str(e.type), source: str(e.source), uncertain: e.uncertain === true, note: str(e.note) }
    }),
    yesterdayFeedback: str(row.yesterday_feedback),
    candidates: arr(row.candidates).map((item) => {
      const c = obj(item)
      const tags = obj(c.tags)
      return { code: str(c.code), reason: str(c.reason), cardId: num(c.card_id), streak: num(tags.streak), theme: str(tags.theme) }
    }),
    pending: arr(row.pending).map((item) => str(item)).filter(Boolean),
    checklist: arr(row.checklist).map((item) => ({ item: str(obj(item).item), ok: obj(item).ok === true, note: str(obj(item).note) })),
    dataCutoff: str(row.data_cutoff),
    sources: arr(row.sources).map((item) => str(item)).filter(Boolean),
    lhbNote: str(row.lhb_note),
    ladderNote: str(row.ladder_note),
    bodyMarkdown: str(row.body_markdown),
    revision: Math.trunc(num(row.revision) ?? 1),
  }
}

/** True when an evening review for `date` exists in the list. */
export function hasEveningReview(list: readonly ReviewSummary[], date: string): boolean {
  return list.some((row) => row.date === date && row.kind === 'evening')
}

/** After 20:00 on a weekday with no evening review yet, offer a manual run. */
export function reviewOverdue(now: Date, list: readonly ReviewSummary[]): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  if (now.getHours() < 20) return false
  const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  return !hasEveningReview(list, date)
}

/* ---------------------------------------------------------------- market data */

export interface PoolDay {
  date: string
  available: boolean
  zt: number | null
  dt: number | null
  zb: number | null
  sealRatioPct: number | null
  promote12: number | null
  promote23: number | null
  promote3up: number | null
  maxStreak: number | null
}

export function normalizePoolHistory(payload: unknown): PoolDay[] {
  return arr(obj(payload).days).map((raw) => {
    const row = obj(raw)
    return {
      date: str(row.date),
      available: row.available !== false && num(row.zt) !== null,
      zt: num(row.zt),
      dt: num(row.dt),
      zb: num(row.zb),
      sealRatioPct: num(row.seal_ratio_pct),
      promote12: num(row.promote_1to2_pct),
      promote23: num(row.promote_2to3_pct),
      promote3up: num(row.promote_3up_pct),
      maxStreak: num(row.max_streak),
    }
  }).filter((row) => /^\d{4}-\d{2}-\d{2}$/.test(row.date))
}

export interface LadderTier {
  streak: number
  count: number
  names: string[]
}

export function normalizeLadder(payload: unknown): { maxStreak: number; tiers: LadderTier[] } {
  const root = obj(payload)
  return {
    maxStreak: Math.trunc(num(root.max_streak) ?? 0),
    tiers: arr(root.tiers).map((raw) => {
      const row = obj(raw)
      return {
        streak: Math.trunc(num(row.streak) ?? 0),
        count: Math.trunc(num(row.count) ?? 0),
        names: arr(row.rows).map((item) => str(obj(item).name)).filter(Boolean),
      }
    }).filter((tier) => tier.streak > 0),
  }
}

export interface ThemeRow {
  rank: number
  code: string
  name: string
  changePct: number | null
  amountYuan: number | null
  leader: string
}

export function normalizeThemes(payload: unknown): ThemeRow[] {
  return arr(obj(payload).rows).map((raw, index) => {
    const row = obj(raw)
    return {
      rank: Math.trunc(num(row.rank) ?? index + 1),
      code: str(row.code),
      name: str(row.name),
      changePct: num(row.change_pct),
      amountYuan: num(row.amount_yuan),
      leader: str(obj(row.leader).name),
    }
  })
}

export interface IndustryZt {
  industry: string
  zt: number
  zb: number
  maxStreak: number
}

export function normalizeIndustryZt(payload: unknown): IndustryZt[] {
  return arr(obj(payload).rows).map((raw) => {
    const row = obj(raw)
    return { industry: str(row.industry), zt: Math.trunc(num(row.zt_count) ?? 0), zb: Math.trunc(num(row.zb_count) ?? 0), maxStreak: Math.trunc(num(row.max_streak) ?? 0) }
  }).filter((row) => row.industry !== '')
}

export interface YesterdayPerformance {
  date: string
  prevDate: string
  count: number
  avgOpenPct: number | null
  avgHighPct: number | null
  avgClosePct: number | null
  winRatioPct: number | null
  reason: string
}

export function normalizeYesterday(payload: unknown): YesterdayPerformance {
  const root = obj(payload)
  return {
    date: str(root.date),
    prevDate: str(root.prev_date),
    count: arr(root.rows).length,
    avgOpenPct: num(root.avg_open_pct),
    avgHighPct: num(root.avg_high_pct),
    avgClosePct: num(root.avg_close_pct),
    winRatioPct: num(root.win_ratio_pct),
    reason: str(root.reason),
  }
}

export interface BreadthSeries {
  points: Array<{ t: string; up: number; down: number }>
  gaps: boolean
}

export function normalizeBreadthSeries(payload: unknown): BreadthSeries {
  const root = obj(payload)
  return {
    points: arr(root.points).map((raw) => {
      const row = obj(raw)
      return { t: str(row.t), up: num(row.up) ?? NaN, down: num(row.down) ?? NaN }
    }).filter((row) => /^\d\d:\d\d$/.test(row.t) && Number.isFinite(row.up) && Number.isFinite(row.down)),
    gaps: root.gaps === true,
  }
}

export interface CandidateStats {
  n: number
  insufficient: boolean
  triggerRatePct: number | null
  avgOpenPct: number | null
  avgClosePct: number | null
  winRatioPct: number | null
}

export function normalizeCandidateStats(payload: unknown): CandidateStats {
  const root = obj(payload)
  return {
    n: Math.trunc(num(root.n) ?? 0),
    insufficient: root.sample_insufficient !== false,
    triggerRatePct: num(root.trigger_rate_pct),
    avgOpenPct: num(root.avg_open_pct),
    avgClosePct: num(root.avg_close_pct),
    winRatioPct: num(root.win_ratio_pct),
  }
}

/* --------------------------------------------------------------------- charts */

export interface SeriesGeometry {
  /** One path per input series; gaps (null) split a series into several sub-paths. */
  paths: string[]
  min: number
  max: number
}

/**
 * Line paths for several series sharing one y scale. `null`/NaN breaks the line
 * instead of interpolating across it (missing days stay visibly missing).
 */
export function seriesGeometry(
  series: ReadonlyArray<ReadonlyArray<number | null>>,
  width: number,
  height: number,
  options: { pad?: number; floorZero?: boolean } = {},
): SeriesGeometry | null {
  const pad = options.pad ?? 3
  const values = series.flatMap((line) => line.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)))
  if (values.length === 0) return null
  let min = options.floorZero ? Math.min(0, ...values) : Math.min(...values)
  let max = Math.max(...values)
  if (max === min) { max += 1; min -= 1 }
  const length = Math.max(...series.map((line) => line.length))
  if (length < 2) return null
  const step = width / (length - 1)
  const y = (value: number): number => pad + (1 - (value - min) / (max - min)) * (height - pad * 2)
  const paths = series.map((line) => {
    let path = ''
    let pen = false
    line.forEach((value, index) => {
      if (typeof value !== 'number' || !Number.isFinite(value)) { pen = false; return }
      path += `${pen ? 'L' : 'M'}${(index * step).toFixed(1)},${y(value).toFixed(1)}`
      pen = true
    })
    return path
  })
  return { paths, min, max }
}

/* ------------------------------------------------------------ request helpers */

export function reviewPath(date: string, kind: ReviewKind): string {
  return `${HUB_REVIEW_PATH}?date=${encodeURIComponent(date)}&kind=${kind}`
}

export function cardsPath(status: 'proposed' | 'active' | 'closed' | 'all'): string {
  return `${HUB_CARDS_PATH}?status=${status}`
}

export type SettingActionBody = { key: string; action: 'adopt' | 'clear' | 'dismiss' } | { key: string; action: 'set'; value: number }

export function settingBody(key: string, action: 'adopt' | 'clear' | 'dismiss'): SettingActionBody
export function settingBody(key: string, action: 'set', value: number): SettingActionBody
export function settingBody(key: string, action: 'adopt' | 'clear' | 'dismiss' | 'set', value?: number): SettingActionBody {
  return action === 'set' ? { key, action, value: value as number } : { key, action }
}

export function lossStreakBody(action: 'add' | 'reset'): { kind: 'loss-streak'; action: 'add' | 'reset' } {
  return { kind: 'loss-streak', action }
}

export function moodBody(slot: MoodSlot, level: MoodLevel): { kind: 'mood'; slot: MoodSlot; level: MoodLevel } {
  return { kind: 'mood', slot, level }
}

export type CardActionBody =
  | { id: number; action: 'confirm' | 'cancel' }
  | { id: number; action: 'tighten_stop'; stop: number }
  | { id: number; action: 'set_state'; state: 'abandon' | 'exit' }

export function cardActionBody(id: number, action: 'confirm' | 'cancel'): CardActionBody
export function cardActionBody(id: number, action: 'tighten_stop', stop: number): CardActionBody
export function cardActionBody(id: number, action: 'set_state', state: 'abandon' | 'exit'): CardActionBody
export function cardActionBody(id: number, action: string, extra?: number | string): CardActionBody {
  if (action === 'tighten_stop') return { id, action, stop: extra as number }
  if (action === 'set_state') return { id, action, state: extra as 'abandon' | 'exit' }
  return { id, action: action as 'confirm' | 'cancel' }
}

/** The prompts that only fill the ask bar (never send, never create tasks). */
export const REVIEW_PROMPTS = {
  runNow: '现在做一次完整复盘：先判断今天是不是交易日；按环境→主线→涨停结构→个股质量→昨日反馈→次日观察清单的顺序，候选最多 5 只，每只提交作战卡，最后保存复盘。',
  premarket: '做今天的盘前核对：查隔夜公告与外部市场，对昨晚的每张作战卡给出保留/降级/移除的意见，竞价数据没有可靠来源的地方写"待确认"。',
  suggestSettings: '请根据我的持仓、波动和画像，给仓位上限、单笔风险和暂停线逐项提出建议，每项写明依据并标注"未经回测"，建议先不要生效，我在复盘页来采纳。',
  enableSchedule: '我想开启复盘定时任务：工作日 20:00 复盘、08:30 盘前核对。请先把两个任务的内容（时间、提示词、会话方式）展示给我，我确认后再创建。',
} as const
