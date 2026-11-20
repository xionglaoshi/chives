/**
 * Pure market-watch view model: normalise the v1 contract, format numbers,
 * derive diverging colours/timeline state and merge the two alert sources.
 * This file is loaded directly by Node in tests, so it stays free of React,
 * DOM access, `@deepseek-ai/*` imports and non-erasable TypeScript syntax.
 */
import { formatClock, formatPct, formatPrice } from './viewModel.ts'
import type { AlertPayload, AnalysisRecord } from './viewModel.ts'

export const DASH = '\u2014'
export const UP_SYMBOL = '\u25b2'
export const DOWN_SYMBOL = '\u25bc'
export const SECTOR_CODE = /^BK[0-9]{4}$/

export type TradingState = 'pre_open' | 'open' | 'lunch' | 'closed' | 'holiday' | 'unknown'

/** Contract v1.1 sector ids only; anything else must not reach a detail path. */
export function isSectorCode(code: string): boolean {
  return SECTOR_CODE.test(code)
}
export type AlertStatus = 'analyzed' | 'analyzing' | 'skipped' | 'pending' | 'failed'

export interface SparkPoint {
  t: string
  p: number
}

export interface MarketIndex {
  code: string
  name: string
  price: number | null
  prevClose: number | null
  changePct: number | null
  amountYuan: number | null
  volumeRatio: number | null
  spark: SparkPoint[]
  sparkKind: 'intraday' | 'daily' | null
  asOf: string | null
  stale: boolean
  reason: string | null
}

export interface HealthSource {
  ok: boolean | null
  ageS: number | null
  lastError: string | null
}

export interface MarketHealth {
  ok: boolean
  asOf: string | null
  tradingState: TradingState
  stateNote: string | null
  sources: Record<string, HealthSource>
  enabledRules: string[]
}

export interface Breadth {
  up: number | null
  down: number | null
  flat: number | null
  upRatio: number | null
  limitUp: number | null
  limitDown: number | null
  broken: number | null
  sealRatio: number | null
  maxStreak: number | null
  amountYuan: number | null
  asOf: string | null
  stale: boolean
  reason: string | null
}

export interface Regime {
  label: 'risk_on' | 'neutral' | 'risk_off' | 'unknown'
  reasons: string[]
}

export interface Overview {
  ok: boolean
  error: string | null
  asOf: string | null
  tradingState: TradingState
  stateNote: string | null
  indexes: MarketIndex[]
  breadth: Breadth
  regime: Regime
}

export interface SectorLeader {
  code: string
  name: string
  changePct: number | null
}

export interface SectorRow {
  code: string
  name: string
  changePct: number | null
  amountYuan: number | null
  amountShareRatio: number | null
  rel300Pct: number | null
  upCount: number | null
  downCount: number | null
  limitUpCount: number | null
  memberCount: number | null
  rank: number | null
  rankChange30m: number | null
  leaders: SectorLeader[]
  laggards: SectorLeader[]
  ret5dPct: number | null
  ret20dPct: number | null
  asOf: string | null
  stale: boolean
  small: boolean
  reason: string | null
}

export interface SectorTrendPoint {
  t: string
  changePct: number
}

export interface SectorHistory {
  ret5dPct: number | null
  ret20dPct: number | null
  rank5d: number | null
  rank20d: number | null
}

export interface SectorDetail extends SectorRow {
  stateNote: string | null
  trend: SectorTrendPoint[]
  history: SectorHistory
}

export interface SectorMember {
  code: string
  name: string
  price: number | null
  changePct: number | null
  amountYuan: number | null
  weightPct: number | null
  limitUp: boolean
  limitDown: boolean
}

export interface MarketRule {
  id: string
  name: string
  enabled: boolean
  level: string | null
  confirm: number | null
  cooldownMinutes: number | null
  params: Record<string, unknown>
}

export interface MarketAlert {
  id: number
  ts: string | null
  ruleId: string
  objectType: 'index' | 'sector' | 'stock'
  objectCode: string
  objectName: string
  severity: 'L1' | 'L2' | 'L3' | null
  title: string
  detail: string
  status: string
  analysisId: number | null
  payload: unknown
  raw: unknown
}

export interface MarketAlertsPayload {
  ok: boolean
  error: string | null
  alerts: MarketAlert[]
  nextId: number | null
}

export interface TimelineItem {
  key: string
  source: 'watch' | 'market'
  id: number
  ts: string | null
  ruleId: string
  objectType: 'index' | 'sector' | 'stock'
  objectCode: string
  objectName: string
  severity: 'L1' | 'L2' | 'L3' | null
  title: string
  detail: string
  status: AlertStatus
  reason: string
  analysisId: number | null
  raw: unknown
}

export interface TimelineFilters {
  rule: string
  object: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function pick(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function int(value: unknown): number | null {
  const parsed = num(value)
  return parsed === null ? null : Math.trunc(parsed)
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function note(value: unknown): string | null {
  const parsed = text(value).trim()
  return parsed === '' ? null : parsed
}

function bool(value: unknown): boolean {
  return value === true
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Signed percentage carrying an explicit direction glyph. */
export function formatMove(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) return formatPct(0, digits)
  return `${rounded > 0 ? UP_SYMBOL : DOWN_SYMBOL} ${formatPct(rounded, digits)}`
}

/** Yuan / ten-thousand / hundred-million with an explicit Chinese unit. */
export function formatMoney(yuan: number | null | undefined): string {
  if (typeof yuan !== 'number' || !Number.isFinite(yuan)) return DASH
  const absolute = Math.abs(yuan)
  if (absolute >= 1e8) return `${(yuan / 1e8).toFixed(2)} \u4ebf\u5143`
  if (absolute >= 1e4) return `${(yuan / 1e4).toFixed(2)} \u4e07\u5143`
  return `${Math.round(yuan)} \u5143`
}

export type Direction = 'up' | 'down' | 'flat'

export function direction(value: number | null | undefined): Direction {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export function directionSymbol(value: number | null | undefined): string {
  const side = direction(value)
  return side === 'up' ? UP_SYMBOL : side === 'down' ? DOWN_SYMBOL : DASH
}

/**
 * Heat tiers: the fill is chosen from fixed absolute change
 * thresholds rather than a continuous ramp, so a given colour always means the
 * same move. Tier 0 is neutral; tiers 1-4 mix the up/down token into the
 * neutral midpoint with growing strength.
 */
export const HEAT_TIER_EDGES: readonly number[] = [0.3, 1, 2, 3]
const HEAT_TIER_STRENGTH: readonly number[] = [0, 28, 48, 70, 92]

export function heatTier(value: number | null | undefined): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  const abs = Math.abs(value)
  let tier = 0
  for (const edge of HEAT_TIER_EDGES) if (abs >= edge) tier += 1
  return tier
}

/** Fill for a heat tier of a signed move; `side` follows the move's sign. */
export function heatFill(tier: number, side: 'up' | 'down'): string {
  const strength = HEAT_TIER_STRENGTH[Math.max(0, Math.min(HEAT_TIER_STRENGTH.length - 1, tier))]!
  if (strength === 0) return 'var(--chives-diverging-mid)'
  // A-share convention: positive is red (`--chives-up`), negative green; both swap with data-chives-updown.
  const edge = side === 'up' ? 'var(--chives-up)' : 'var(--chives-down)'
  return `color-mix(in oklab, ${edge} ${strength}%, var(--chives-diverging-mid))`
}

/** Diverging fill for the treemap (tiered). `maxAbs` is kept for API compatibility and no longer used. */
export function divergingColor(value: number | null | undefined, _maxAbs?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'var(--chives-diverging-mid)'
  return heatFill(heatTier(value), value > 0 ? 'up' : 'down')
}

/**
 * Tile label policy from the tile's size in the 1000x600 layout space. The name
 * is always rendered (T100: every tile must carry a name); the change is dropped
 * first when the tile is small, then the amount. Font size grows with the tile.
 */
export function tileFontScale(width: number, height: number): { cqw: number; showText: boolean; showMove: boolean; showAmount: boolean } {
  const side = Math.sqrt(Math.max(0, width) * Math.max(0, height))
  const cqw = Math.max(1.05, Math.min(2.6, side / 130))
  return {
    cqw: Number(cqw.toFixed(2)),
    showText: true,
    showMove: width >= 76 && height >= 40,
    showAmount: width >= 130 && height >= 80,
  }
}

export interface LimitDistance {
  side: 'up' | 'down' | null
  pct: number | null
}

/** Percentage distance from the current price to the nearer price limit. */
export function distanceToLimit(
  price: number | null | undefined,
  limitUp: number | null | undefined,
  limitDown: number | null | undefined,
): LimitDistance {
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) return { side: null, pct: null }
  const up = typeof limitUp === 'number' && Number.isFinite(limitUp)
    ? Math.max(0, ((limitUp - price) / price) * 100)
    : null
  const down = typeof limitDown === 'number' && Number.isFinite(limitDown)
    ? Math.max(0, ((price - limitDown) / price) * 100)
    : null
  if (up === null && down === null) return { side: null, pct: null }
  if (up === null) return { side: 'down', pct: down }
  if (down === null) return { side: 'up', pct: up }
  return up <= down ? { side: 'up', pct: up } : { side: 'down', pct: down }
}

export interface RankArrow {
  direction: 'up' | 'down' | 'flat'
  symbol: string
}

/** Rank delta is previous rank minus current rank: positive means moved up. */
export function rankArrow(delta: number | null | undefined): RankArrow {
  if (typeof delta !== 'number' || !Number.isFinite(delta) || delta === 0) {
    return { direction: 'flat', symbol: DASH }
  }
  return delta > 0
    ? { direction: 'up', symbol: UP_SYMBOL }
    : { direction: 'down', symbol: DOWN_SYMBOL }
}

/** `MM-DD HH:MM:SS` in the source timezone (no conversion). */
export function formatStamp(iso: string | null | undefined): string {
  if (typeof iso !== 'string') return DASH
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})/)
  return match ? `${match[2]}-${match[3]} ${match[4]}` : DASH
}

export function normalizeTradingState(value: unknown): TradingState {
  switch (value) {
    case 'pre_open':
    case 'open':
    case 'lunch':
    case 'closed':
    case 'holiday':
      return value
    default:
      return 'unknown'
  }
}

export function normalizeSpark(value: unknown): SparkPoint[] {
  const points: SparkPoint[] = []
  for (const entry of list(value)) {
    const row = pick(entry)
    const p = num(row.p)
    if (p === null) continue
    const t = typeof row.t === 'string' ? row.t : typeof row.t === 'number' ? String(row.t) : ''
    points.push({ t, p })
  }
  return points
}

export function normalizeIndexes(value: unknown): MarketIndex[] {
  return list(value).map((entry) => {
    const row = pick(entry)
    return {
      code: text(row.code),
      name: text(row.name),
      price: num(row.price),
      prevClose: num(row.prev_close),
      changePct: num(row.change_pct),
      amountYuan: num(row.amount_yuan),
      volumeRatio: num(row.volume_ratio),
      spark: normalizeSpark(row.spark),
      sparkKind: row.spark_kind === 'intraday' || row.spark_kind === 'daily' ? row.spark_kind : null,
      asOf: typeof row.as_of === 'string' ? row.as_of : null,
      stale: bool(row.stale),
      reason: typeof row.reason === 'string' ? row.reason : null,
    }
  })
}

export function normalizeBreadth(value: unknown): Breadth {
  const row = pick(value)
  return {
    up: int(row.up),
    down: int(row.down),
    flat: int(row.flat),
    upRatio: num(row.up_ratio),
    limitUp: int(row.limit_up),
    limitDown: int(row.limit_down),
    broken: int(row.broken),
    sealRatio: num(row.seal_ratio),
    maxStreak: int(row.max_streak),
    amountYuan: num(row.amount_yuan),
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    stale: bool(row.stale),
    reason: typeof row.reason === 'string' ? row.reason : null,
  }
}

export function normalizeRegime(value: unknown): Regime {
  const row = pick(value)
  const label = row.label === 'risk_on' || row.label === 'risk_off' || row.label === 'neutral' ? row.label : 'unknown'
  const reasons = list(row.reasons).filter((entry): entry is string => typeof entry === 'string' && entry !== '')
  return { label, reasons }
}

export function normalizeMarketHealth(value: unknown): MarketHealth {
  const row = pick(value)
  const sources: Record<string, HealthSource> = {}
  for (const [name, raw] of Object.entries(pick(row.sources))) {
    const source = pick(raw)
    sources[name] = {
      ok: typeof source.ok === 'boolean' ? source.ok : null,
      ageS: num(source.age_s),
      lastError: typeof source.last_error === 'string' ? source.last_error : null,
    }
  }
  const rules = pick(row.rules)
  const enabled = list(rules.enabled).filter((entry): entry is string => typeof entry === 'string')
  return {
    ok: row.ok !== false,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    tradingState: normalizeTradingState(row.trading_state),
    stateNote: note(row.state_note),
    sources,
    enabledRules: enabled,
  }
}

export type HealthPulse = 'healthy' | 'warn' | 'idle' | 'unreachable'

/** Three-state pulse: fresh, delayed/degraded, or closed/unreachable. */
export function marketPulse(health: MarketHealth | null, failed: boolean): HealthPulse {
  if (failed || !health) return 'unreachable'
  if (health.tradingState === 'closed' || health.tradingState === 'holiday') return 'idle'
  const values = Object.values(health.sources)
  if (values.some((source) => source.ok === false || (source.ageS !== null && source.ageS > 120))) return 'warn'
  if (!health.ok) return 'warn'
  return 'healthy'
}

export function normalizeOverview(value: unknown): Overview {
  const row = pick(value)
  const ok = row.ok !== false
  const error = isRecord(row.error) ? text(row.error.code) || 'market_error' : null
  return {
    ok,
    error,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    tradingState: normalizeTradingState(row.trading_state),
    stateNote: note(row.state_note),
    indexes: normalizeIndexes(row.indexes),
    breadth: normalizeBreadth(row.breadth),
    regime: normalizeRegime(row.regime),
  }
}

function normalizeLeader(value: unknown): SectorLeader {
  const row = pick(value)
  return { code: text(row.code), name: text(row.name), changePct: num(row.change_pct) }
}

export function normalizeSectorRow(value: unknown): SectorRow {
  const row = pick(value)
  const memberCount = int(row.member_count)
  return {
    code: text(row.code),
    name: text(row.name),
    changePct: num(row.change_pct),
    amountYuan: num(row.amount_yuan),
    amountShareRatio: num(row.amount_share_ratio),
    rel300Pct: num(row.rel_300_pct),
    upCount: int(row.up_count),
    downCount: int(row.down_count),
    limitUpCount: int(row.limit_up_count),
    memberCount,
    rank: int(row.rank),
    rankChange30m: num(row.rank_change_30m),
    leaders: list(row.leaders).map(normalizeLeader),
    laggards: list(row.laggards).map(normalizeLeader),
    ret5dPct: num(row.ret_5d_pct),
    ret20dPct: num(row.ret_20d_pct),
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    stale: bool(row.stale),
    small: bool(row.small) || (memberCount !== null && memberCount < 10),
    reason: typeof row.reason === 'string' ? row.reason : null,
  }
}

export function normalizeSectors(value: unknown): { ok: boolean; error: string | null; asOf: string | null; stateNote: string | null; rows: SectorRow[] } {
  const row = pick(value)
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'market_error' : null,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    stateNote: note(row.state_note),
    rows: list(row.rows).map(normalizeSectorRow),
  }
}

export function normalizeSectorDetail(value: unknown): SectorDetail {
  const row = pick(value)
  const base = normalizeSectorRow(row)
  const history = pick(row.history)
  const trend: SectorTrendPoint[] = []
  for (const entry of list(row.trend)) {
    const point = pick(entry)
    const changePct = num(point.change_pct)
    if (changePct === null) continue
    trend.push({ t: typeof point.t === 'string' ? point.t : '', changePct })
  }
  return {
    ...base,
    stateNote: note(row.state_note),
    trend,
    history: {
      ret5dPct: num(history.ret_5d_pct) ?? base.ret5dPct,
      ret20dPct: num(history.ret_20d_pct) ?? base.ret20dPct,
      rank5d: int(history.rank_5d),
      rank20d: int(history.rank_20d),
    },
  }
}

export function normalizeMembers(value: unknown): SectorMember[] {
  const rows = Array.isArray(value) ? value : list(pick(value).rows)
  return rows.map((entry) => {
    const row = pick(entry)
    return {
      code: text(row.code),
      name: text(row.name),
      price: num(row.price),
      changePct: num(row.change_pct),
      amountYuan: num(row.amount_yuan),
      weightPct: num(row.weight_pct),
      limitUp: bool(row.limit_up),
      limitDown: bool(row.limit_down),
    }
  })
}

export function normalizeMarketRules(value: unknown): MarketRule[] {
  const rows = Array.isArray(value) ? value : list(pick(value).rules)
  return rows.map((entry) => {
    const row = pick(entry)
    return {
      id: text(row.id),
      name: text(row.name),
      enabled: row.enabled !== false,
      level: typeof row.level === 'string' ? row.level : null,
      confirm: int(row.confirm),
      cooldownMinutes: int(row.cooldown_minutes),
      params: isRecord(row.params) ? row.params : {},
    }
  })
}

export function normalizeMarketAlert(value: unknown): MarketAlert | null {
  const row = pick(value)
  const id = int(row.id)
  if (id === null) return null
  const object = pick(row.object)
  const objectType = object.type === 'index' || object.type === 'sector' || object.type === 'stock' ? object.type : 'stock'
  const severity = row.severity === 'L1' || row.severity === 'L2' || row.severity === 'L3' ? row.severity : null
  const detail = isRecord(row.detail) || typeof row.detail === 'string'
    ? typeof row.detail === 'string' ? row.detail : JSON.stringify(row.detail)
    : isRecord(row.payload) ? JSON.stringify(row.payload) : ''
  return {
    id,
    ts: typeof row.ts === 'string' ? row.ts : null,
    ruleId: text(row.rule_id),
    objectType,
    objectCode: text(object.code),
    objectName: text(object.name),
    severity,
    title: text(row.title),
    detail,
    status: text(row.status),
    analysisId: int(row.analysis_id),
    payload: row.payload,
    raw: value,
  }
}

export function normalizeMarketAlerts(value: unknown): MarketAlertsPayload {
  const row = pick(value)
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'market_error' : null,
    alerts: list(row.alerts).map(normalizeMarketAlert).filter((alert): alert is MarketAlert => alert !== null),
    nextId: int(row.next_id),
  }
}

const RULE_NAMES: Record<string, string> = {
  R1: '\u6307\u6570\u653e\u91cf\u4e0b\u8dcc',
  R2: '\u5bbd\u5ea6\u6076\u5316/\u80cc\u79bb',
  R3: '\u677f\u5757\u6392\u540d\u8dc3\u5347',
  R4: '\u677f\u5757\u6da8\u505c\u9aa4\u589e',
  R5: '\u76f8\u5bf9\u5f3a\u5f31\u7a7f\u8d8a',
  R6: '\u4e2a\u80a1-\u677f\u5757\u80cc\u79bb',
}

export function marketRuleName(rule: MarketRule): string {
  return rule.name || RULE_NAMES[rule.id] || rule.id
}

export function marketRuleParams(rule: MarketRule): string {
  const entries = Object.entries(rule.params)
    .filter(([, value]) => typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean')
    .sort(([left], [right]) => left.localeCompare(right))
  return entries.map(([key, value]) => `${key}=${String(value)}`).join(' \u00b7 ')
}

/** Status of a cn-watch alert given its analysis record. */
export function watchAlertStatus(record: AnalysisRecord | undefined): AlertStatus {
  if (!record) return 'pending'
  switch (record.status) {
    case 'done':
      return 'analyzed'
    case 'skipped':
      return 'skipped'
    case 'failed':
    case 'timeout':
      return 'failed'
    case 'running':
      return 'analyzing'
    default:
      return 'pending'
  }
}

export function marketAlertStatus(alert: MarketAlert): AlertStatus {
  if (alert.status === 'analyzed') return 'analyzed'
  if (alert.status === 'skipped') return 'skipped'
  if (alert.status === 'failed') return 'failed'
  if (alert.analysisId !== null) return 'analyzing'
  return 'pending'
}

export function alertReason(alert: MarketAlert): string {
  const payload = pick(alert.payload)
  const detail = pick(alert.raw)
  const reason = payload.reason ?? pick(detail.detail).reason ?? detail.reason
  return typeof reason === 'string' ? reason : ''
}

function watchDetail(alert: AlertPayload): string {
  const parts: string[] = []
  if (typeof alert.price === 'number') parts.push(`\u4ef7\u683c ${formatPrice(alert.price)}`)
  if (typeof alert.change_pct === 'number') parts.push(`\u6da8\u8dcc ${formatPct(alert.change_pct)}`)
  if (typeof alert.vwap === 'number') parts.push(`VWAP ${formatPrice(alert.vwap)}`)
  if (typeof alert.limit_up === 'number') parts.push(`\u6da8\u505c ${formatPrice(alert.limit_up)}`)
  if (typeof alert.limit_down === 'number') parts.push(`\u8dcc\u505c ${formatPrice(alert.limit_down)}`)
  return parts.join(' \u00b7 ')
}

/**
 * Merge cn-watch and market-watch alerts into one newest-first timeline.
 * Timestamps are compared as ISO text; invalid/missing times sort last.
 */
export function buildTimeline(
  watchAlerts: readonly AlertPayload[] | null | undefined,
  marketAlerts: readonly MarketAlert[] | null | undefined,
  analyses: readonly AnalysisRecord[] | null | undefined,
): TimelineItem[] {
  const records = new Map<number, AnalysisRecord>()
  for (const record of analyses ?? []) {
    if (typeof record?.alert_id === 'number') records.set(record.alert_id, record)
  }
  const items: TimelineItem[] = []
  for (const alert of watchAlerts ?? []) {
    if (typeof alert.id !== 'number') continue
    const record = records.get(alert.id)
    const status = watchAlertStatus(record)
    items.push({
      key: `watch:${alert.id}`,
      source: 'watch',
      id: alert.id,
      ts: alert.ts ?? null,
      ruleId: alert.rule_id ?? '',
      objectType: 'stock',
      objectCode: alert.code ?? '',
      objectName: alert.name ?? '',
      severity: null,
      title: alert.name || alert.code || `#${alert.id}`,
      detail: watchDetail(alert),
      status,
      reason: status === 'skipped' ? (record?.reason ?? '') : '',
      analysisId: status === 'analyzed' || status === 'failed' ? alert.id : null,
      raw: alert,
    })
  }
  for (const alert of marketAlerts ?? []) {
    const status = marketAlertStatus(alert)
    items.push({
      key: `market:${alert.id}`,
      source: 'market',
      id: alert.id,
      ts: alert.ts,
      ruleId: alert.ruleId,
      objectType: alert.objectType,
      objectCode: alert.objectCode,
      objectName: alert.objectName,
      severity: alert.severity,
      title: alert.title || alert.objectName || `#${alert.id}`,
      detail: alert.detail,
      status,
      reason: status === 'skipped' ? alertReason(alert) : '',
      analysisId: alert.analysisId,
      raw: alert.raw,
    })
  }
  return items.sort((left, right) => {
    const leftTime = left.ts ? Date.parse(left.ts) : Number.NaN
    const rightTime = right.ts ? Date.parse(right.ts) : Number.NaN
    const leftValid = Number.isFinite(leftTime)
    const rightValid = Number.isFinite(rightTime)
    if (leftValid && rightValid && leftTime !== rightTime) return rightTime - leftTime
    if (leftValid !== rightValid) return leftValid ? -1 : 1
    return right.key.localeCompare(left.key)
  })
}

/** New timeline keys compared with a previous set; used to animate only additions. */
export function newTimelineKeys(previous: ReadonlySet<string>, items: readonly TimelineItem[]): string[] {
  return items.filter((item) => !previous.has(item.key)).map((item) => item.key)
}

/**
 * Timeline novelty with the baseline taken from the first completed load. While
 * `loaded` is false nothing is baselined, so history fetched on page open never
 * gets the "new alert" entrance or glow. An empty first load still baselines.
 */
export function timelineNovelty(
  known: ReadonlySet<string> | null,
  items: readonly TimelineItem[],
  loaded: boolean,
): { known: Set<string> | null; fresh: string[] } {
  if (known === null) {
    if (!loaded) return { known: null, fresh: [] }
    return { known: new Set(items.map((item) => item.key)), fresh: [] }
  }
  return { known: new Set([...known, ...items.map((item) => item.key)]), fresh: newTimelineKeys(known, items) }
}

export function filterTimeline(items: readonly TimelineItem[], filters: TimelineFilters): TimelineItem[] {
  return items.filter((item) => {
    if (filters.rule !== '' && item.ruleId !== filters.rule) return false
    if (filters.object !== '' && `${item.objectType}:${item.objectCode}` !== filters.object) return false
    return true
  })
}

export function filterRules(items: readonly TimelineItem[]): string[] {
  return [...new Set(items.map((item) => item.ruleId).filter((rule) => rule !== ''))].sort()
}

export function filterObjects(items: readonly TimelineItem[]): { key: string; label: string }[] {
  const seen = new Map<string, string>()
  for (const item of items) {
    const key = `${item.objectType}:${item.objectCode}`
    if (!seen.has(key)) seen.set(key, item.objectName || item.objectCode)
  }
  return [...seen].sort(([left], [right]) => left.localeCompare(right)).map(([key, label]) => ({ key, label }))
}

/** Top gainers and bottom losers, ties broken by code. */
export function topBottomSectors(rows: readonly SectorRow[], count = 5): { top: SectorRow[]; bottom: SectorRow[] } {
  const ranked = rows
    .filter((row) => row.changePct !== null && Number.isFinite(row.changePct))
    .sort((left, right) => (right.changePct! - left.changePct!) || left.code.localeCompare(right.code))
  return {
    top: ranked.slice(0, Math.max(0, count)),
    bottom: ranked.slice(Math.max(0, ranked.length - count)),
  }
}

export function maxAbsChange(rows: readonly SectorRow[]): number {
  let max = 0
  for (const row of rows) {
    if (row.changePct !== null && Number.isFinite(row.changePct)) max = Math.max(max, Math.abs(row.changePct))
  }
  return max
}

/** Reason text for a missing value; never invents a value. */
export function missingReason(reason: string | null | undefined): string {
  return reason && reason !== '' ? reason : '\u6570\u636e\u672a\u63d0\u4f9b'
}

export function quoteClock(iso: string | null | undefined): string {
  return formatClock(iso)
}

/** Stable avatar tone 0-5 from a code: the same stock always gets the same hue. */
export function avatarTone(code: string): number {
  let hash = 5381
  for (let i = 0; i < code.length; i += 1) hash = ((hash << 5) + hash + code.charCodeAt(i)) >>> 0
  return hash % 6
}

/** First visible character of a name (skips ST/星 prefixes), used as the avatar glyph. */
export function avatarGlyph(name: string): string {
  const cleaned = name.replace(/^[*]?ST/i, '').replace(/^[NC]\s*/, '').trim() || name.trim()
  const first = Array.from(cleaned)[0]
  return first ?? '?'
}

export interface StockSparkSeries {
  points: readonly SparkPoint[]
  changePct: number | null
}

export function normalizeStockSparks(payload: unknown): Record<string, StockSparkSeries> {
  const out: Record<string, StockSparkSeries> = {}
  const sparks = (payload as { sparks?: unknown } | null)?.sparks
  if (typeof sparks !== 'object' || sparks === null) return out
  for (const [code, raw] of Object.entries(sparks as Record<string, unknown>)) {
    const row = raw as { points?: unknown; change_pct?: unknown } | null
    if (!row || !Array.isArray(row.points)) continue
    const values = row.points.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    if (values.length < 2) continue
    out[code] = {
      points: values.map((p, index) => ({ t: String(index), p })),
      changePct: typeof row.change_pct === 'number' && Number.isFinite(row.change_pct) ? row.change_pct : null,
    }
  }
  return out
}


/** Battle-card state per stock code, for the focus-row chip (hub `/cards`, engine-evaluated). */
export type CardChipState = 'proposed' | 'observe' | 'await_confirm' | 'execute' | 'abandon' | 'exit'

export interface CardChip {
  cardId: number
  state: CardChipState
}

const CHIP_RANK: Record<CardChipState, number> = { execute: 0, exit: 1, abandon: 2, await_confirm: 3, observe: 4, proposed: 5 }

/** Live cards only (proposed or active); when a stock has several, the most urgent state wins. */
export function normalizeCardChips(payload: unknown): Record<string, CardChip> {
  const out: Record<string, CardChip> = {}
  const cards = (payload as { cards?: unknown } | null)?.cards
  if (!Array.isArray(cards)) return out
  for (const raw of cards) {
    const row = (typeof raw === 'object' && raw !== null ? raw : {}) as Record<string, unknown>
    const id = typeof row.id === 'number' && Number.isFinite(row.id) ? row.id : null
    const code = typeof row.code === 'string' ? row.code : ''
    if (id === null || !code) continue
    const status = row.status
    if (status !== 'proposed' && status !== 'active') continue
    const stateRaw = String(row.state)
    const state: CardChipState = status === 'proposed' ? 'proposed'
      : (['observe', 'await_confirm', 'execute', 'abandon', 'exit'] as const).find((item) => item === stateRaw) ?? 'observe'
    const current = out[code]
    if (!current || CHIP_RANK[state] < CHIP_RANK[current.state]) out[code] = { cardId: id, state }
  }
  return out
}
