/**
 * Pure view-model helpers for the watch panel.
 *
 * This module is loaded directly by Node (type stripping) in tests, so it must stay
 * free of react, `@deepseek-ai/*`, DOM access and non-erasable TypeScript syntax.
 */

export type HealthLevel = 'ok' | 'stale' | 'degraded' | 'down' | 'unreachable'

export interface HealthPayload {
  status?: string
  health?: string
  mode?: string
  next_interval?: number | null
  consecutive_failures?: number | null
  last_poll_ts?: string | null
  last_exchange_time?: string | null
  stale?: boolean
  lag_seconds?: number | null
  max_lag_seconds?: number | null
  session?: string
  last_rule_eval_ts?: string | null
}

export interface QuotePayload {
  code?: string
  name?: string
  price?: number | null
  prev_close?: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  volume_lots?: number | null
  amount_yuan?: number | null
  exch_time?: string | null
  limit_up?: number | null
  limit_down?: number | null
  change_pct?: number | null
  vwap?: number | null
  vwap_dev_pct?: number | null
}

export interface StatePayload {
  quotes?: Record<string, QuotePayload>
  missing?: string[]
  rules?: RuleStatePayload[]
  health?: string
  mode?: string
  next_interval?: number | null
  consecutive_failures?: number | null
  stale?: boolean
  lag_seconds?: number | null
  updated_at?: string | null
  session?: string
  last_rule_eval_ts?: string | null
}

export interface AlertPayload {
  id: number
  ts?: string | null
  code?: string
  name?: string
  rule_id?: string
  rule_type?: string
  direction?: string | null
  price?: number | null
  prev_close?: number | null
  change_pct?: number | null
  vwap?: number | null
  limit_up?: number | null
  limit_down?: number | null
  detail?: unknown
  dedupe_key?: string
}

export interface RuleConfig {
  id?: string
  type?: string
  direction?: string | null
  threshold_pct?: number | null
  min_amount_yuan?: number | null
  side?: string | null
  within_pct?: number | null
  level?: number | null
  window_seconds?: number | null
  multiple?: number | null
  min_window_amount_yuan?: number | null
  codes?: string[]
}

export interface RulesPayload {
  rules?: RuleConfig[]
  count?: number
}

export interface RuleStatePayload {
  code?: string
  rule_id?: string
  armed?: boolean
  last_fired?: string | null
  fired_count?: number
}

export interface QuoteRow {
  code: string
  name: string
  price: number | null
  changePct: number | null
  vwap: number | null
  vwapDevPct: number | null
  high: number | null
  low: number | null
  limitUp: number | null
  limitDown: number | null
  amountYuan: number | null
  exchTime: string | null
  missing: boolean
}

export interface RuleRow {
  code: string
  ruleId: string
  description: string
  armed: boolean
  firedCount: number
  lastFired: string | null
}

const DASH = '\u2014'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** Health state, preferring the explicit `stale` flag over the reported health. */
export function classifyHealth(health: HealthPayload | null | undefined, fetchFailed: boolean): HealthLevel {
  if (fetchFailed || !health) return 'unreachable'
  if (health.stale === true) return 'stale'
  const level = health.health
  if (level === 'ok' || level === 'degraded' || level === 'down' || level === 'stale') return level
  return 'unreachable'
}

export type SessionLevel = 'open' | 'pre_open' | 'break' | 'after_hours' | 'non_trading_day' | 'unknown'

/** Trading session reported by the engine; old engines without `session` are `unknown`. */
export function classifySession(session: unknown): SessionLevel {
  switch (session) {
    case 'open':
    case 'pre_open':
    case 'break':
    case 'after_hours':
    case 'non_trading_day':
      return session
    default:
      return 'unknown'
  }
}

/** Data lag in seconds; `—` when unknown, minute form from 60 seconds up. */
export function formatLag(lag: number | null | undefined): string {
  if (typeof lag !== 'number' || !Number.isFinite(lag)) return DASH
  const value = Math.max(0, lag)
  if (value < 10) return `${value.toFixed(1)}s`
  const total = Math.round(value)
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}m${String(seconds).padStart(2, '0')}s`
}

/** Signed percentage with a fixed number of decimals; rounded zero carries no sign. */
export function formatPct(x: number | null | undefined, digits = 2): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return DASH
  const rounded = x.toFixed(digits)
  const value = Number(rounded)
  const fixed = value === 0 ? (0).toFixed(digits) : rounded
  const sign = value > 0 ? '+' : ''
  return `${sign}${fixed}%`
}

export function formatPrice(x: number | null | undefined): string {
  if (typeof x !== 'number' || !Number.isFinite(x)) return DASH
  return x.toFixed(2)
}

export function formatAmount(yuan: number | null | undefined): string {
  if (typeof yuan !== 'number' || !Number.isFinite(yuan)) return DASH
  if (yuan >= 1e8) return `${(yuan / 1e8).toFixed(2)}\u4ebf`
  if (yuan >= 1e4) return `${(yuan / 1e4).toFixed(2)}\u4e07`
  return `${Math.round(yuan)}\u5143`
}

/** Clock part of an ISO timestamp, no timezone conversion. */
export function formatClock(iso: string | null | undefined): string {
  if (typeof iso !== 'string') return DASH
  const match = iso.match(/T(\d{2}:\d{2}:\d{2})/)
  return match ? match[1]! : DASH
}

function idOf(alert: { id?: number }): number {
  return typeof alert.id === 'number' && Number.isFinite(alert.id) ? alert.id : 0
}

/** Newest-first copy; the input array is never mutated. */
export function sortAlerts<T extends { id?: number }>(alerts: readonly T[] | null | undefined): T[] {
  if (!Array.isArray(alerts)) return []
  return [...alerts].sort((left, right) => idOf(right) - idOf(left))
}

/** Merge incremental alert pages by id (`incoming` wins), newest first, capped. */
export function mergeAlerts<T extends { id?: number }>(
  existing: readonly T[] | null | undefined,
  incoming: readonly T[] | null | undefined,
  cap = 200,
): T[] {
  const byId = new Map<number, T>()
  for (const alert of existing ?? []) byId.set(idOf(alert), alert)
  for (const alert of incoming ?? []) byId.set(idOf(alert), alert)
  return [...byId.values()].sort((left, right) => idOf(right) - idOf(left)).slice(0, Math.max(0, cap))
}

/**
 * Index the loaded alerts by id so one analysis row can show the name of its alert.
 * Names are third-party text: only non-empty strings are kept, everything else is
 * treated as unknown. Alerts that scrolled out of the window are simply absent.
 */
export function alertNameById(
  alerts: readonly { id?: unknown; name?: unknown }[] | null | undefined,
): Record<string, string> {
  const result: Record<string, string> = {}
  if (!Array.isArray(alerts)) return result
  for (const alert of alerts) {
    if (typeof alert?.id !== 'number' || !Number.isFinite(alert.id)) continue
    if (typeof alert.name !== 'string' || alert.name === '') continue
    result[String(alert.id)] = alert.name
  }
  return result
}

export function nextAfterId(alerts: readonly { id?: number }[] | null | undefined): number {
  let max = 0
  for (const alert of alerts ?? []) {
    const id = idOf(alert)
    if (id > max) max = id
  }
  return max
}

/**
 * Did the server's page, fetched with `after_id = known.id - 1`, start with the alert we already hold?
 * `false` means the engine's id sequence restarted (or the log was replaced) and the cached alerts must be dropped.
 */
export function continuesFrom(
  known: { id?: number; ts?: string | null; dedupe_key?: string } | null | undefined,
  rows: readonly { id?: number; ts?: string | null; dedupe_key?: string }[] | null | undefined,
): boolean {
  if (!known || idOf(known) <= 0) return true
  const first = rows?.[0]
  if (!first) return false
  return idOf(first) === idOf(known) && (first.ts ?? null) === (known.ts ?? null) && (first.dedupe_key ?? null) === (known.dedupe_key ?? null)
}

function quoteRow(code: string, quote: QuotePayload): QuoteRow {
  return {
    code,
    name: text(quote.name),
    price: num(quote.price),
    changePct: num(quote.change_pct),
    vwap: num(quote.vwap),
    vwapDevPct: num(quote.vwap_dev_pct),
    high: num(quote.high),
    low: num(quote.low),
    limitUp: num(quote.limit_up),
    limitDown: num(quote.limit_down),
    amountYuan: num(quote.amount_yuan),
    exchTime: typeof quote.exch_time === 'string' ? quote.exch_time : null,
    missing: false,
  }
}

function missingRow(code: string): QuoteRow {
  return {
    code,
    name: '',
    price: null,
    changePct: null,
    vwap: null,
    vwapDevPct: null,
    high: null,
    low: null,
    limitUp: null,
    limitDown: null,
    amountYuan: null,
    exchTime: null,
    missing: true,
  }
}

/** Quote table rows in ascending code order, followed by explicit missing codes. */
export function quoteRows(state: StatePayload | null | undefined): QuoteRow[] {
  if (!state || !isRecord(state.quotes)) return []
  const quotes = state.quotes
  const codes = Object.keys(quotes).sort((left, right) => left.localeCompare(right))
  const rows = codes.map((code) => quoteRow(code, quotes[code] ?? {}))
  const seen = new Set(codes)
  const missing = Array.isArray(state.missing) ? state.missing : []
  for (const code of [...missing].sort((left, right) => left.localeCompare(right))) {
    if (typeof code !== 'string' || seen.has(code)) continue
    seen.add(code)
    rows.push(missingRow(code))
  }
  return rows
}

function numberText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '?'
}

/** Human description of one rule configuration. */
export function describeRule(rule: RuleConfig): string {
  switch (rule.type) {
    case 'pct_change':
      return `${rule.direction === 'down' ? '\u8dcc\u5e45' : '\u6da8\u5e45'} \u2265 ${numberText(rule.threshold_pct)}%`
    case 'vwap_deviation':
      return `\u504f\u79bb VWAP \u2265 ${numberText(rule.threshold_pct)}%`
    case 'limit_proximity':
      return `${rule.side === 'down' ? '\u8ddd\u8dcc\u505c' : '\u8ddd\u6da8\u505c'} \u2264 ${numberText(rule.within_pct)}%`
    case 'price_cross':
      return `${rule.direction === 'down' ? '\u4e0b\u7a7f' : '\u4e0a\u7a7f'} ${(num(rule.level) ?? 0).toFixed(2)}`
    case 'volume_surge':
      return `${numberText(rule.window_seconds)} \u79d2\u653e\u91cf \u2265 ${numberText(rule.multiple)} \u500d`
    default:
      return text(rule.type)
  }
}

/** Rule configurations indexed by id, either as a `Map` or as a plain object. */
export type RuleIndex = ReadonlyMap<string, RuleConfig> | Readonly<Record<string, RuleConfig>>

function lookupRule(ruleById: RuleIndex | null | undefined, id: string): RuleConfig | undefined {
  if (!ruleById) return undefined
  const asMap = ruleById as ReadonlyMap<string, RuleConfig>
  if (typeof asMap.get === 'function') return asMap.get(id)
  const asRecord = ruleById as Readonly<Record<string, RuleConfig>>
  return Object.prototype.hasOwnProperty.call(asRecord, id) ? asRecord[id] : undefined
}

/**
 * Label for one rule id: the same description the alert list shows when the config
 * is known, otherwise the raw id (the rule may have been changed or removed).
 */
export function ruleLabel(ruleId: unknown, ruleById: RuleIndex | null | undefined): string {
  const id = text(ruleId)
  if (id === '') return DASH
  const config = lookupRule(ruleById, id)
  return (config ? describeRule(config) : '') || id
}

/** Rule status rows in the engine's original order, descriptions joined by rule id. */
export function ruleRows(
  state: StatePayload | null | undefined,
  rulesResponse: RulesPayload | null | undefined,
): RuleRow[] {
  if (!state || !Array.isArray(state.rules)) return []
  if (!rulesResponse || !Array.isArray(rulesResponse.rules)) return []
  const configs = new Map<string, RuleConfig>()
  for (const config of rulesResponse.rules) {
    if (config && typeof config.id === 'string') configs.set(config.id, config)
  }
  return state.rules.map((entry) => {
    const ruleId = text(entry.rule_id)
    const config = configs.get(ruleId)
    return {
      code: text(entry.code),
      ruleId,
      description: config ? describeRule(config) : ruleId,
      armed: entry.armed === true,
      firedCount: typeof entry.fired_count === 'number' && Number.isFinite(entry.fired_count) ? entry.fired_count : 0,
      lastFired: typeof entry.last_fired === 'string' ? entry.last_fired : null,
    }
  })
}

export type AnalysisStatus = 'done' | 'failed' | 'timeout' | 'skipped' | 'unknown'

export interface AnalysisRecord {
  alert_id: number
  code?: string
  rule_id?: string
  status?: string
  reason?: string | null
  started_at?: string | null
  finished_at?: string | null
  session_id?: string | null
  file?: string | null
}

export interface AnalysisDetail {
  id: number
  markdown: string
  truncated: boolean
}

const ANALYSIS_BADGES: readonly AnalysisStatus[] = ['done', 'failed', 'timeout', 'skipped']

const SKIP_REASONS: Record<string, string> = {
  not_selected: '\u672a\u9009\u4e2d\u7684\u89c4\u5219',
  cooldown: '\u51b7\u5374\u4e2d',
  daily_limit: '\u5df2\u8fbe\u5f53\u65e5\u4e0a\u9650',
  stale_alert: '\u544a\u8b66\u5df2\u8fc7\u671f',
  queue_overflow: '\u961f\u5217\u5df2\u6ee1',
  kill_switch: '\u7194\u65ad\u4e2d',
  dry_run: '\u5e72\u8dd1',
}

/** Badge for one analysis record; anything unfamiliar is `unknown`. */
export function analysisBadge(record: { status?: unknown } | null | undefined): AnalysisStatus {
  const status = record?.status
  return typeof status === 'string' && (ANALYSIS_BADGES as readonly string[]).includes(status)
    ? status as AnalysisStatus
    : 'unknown'
}

/**
 * Does expanding this analysis row need `/api/watch/analysis`?
 * A skipped record never has an analysis file, so the panel must not request one.
 */
export function shouldFetchAnalysis(record: { status?: unknown } | null | undefined): boolean {
  return analysisBadge(record) !== 'skipped'
}

export type AlertAnalysisMarker = 'analyzed' | 'failed' | null

/**
 * Marker next to one alert. Only a genuinely finished analysis counts as
 * `analyzed`; skipped (e.g. cooldown), unknown or missing records get no marker.
 */
export function alertAnalysisMarker(record: { status?: unknown } | null | undefined): AlertAnalysisMarker {
  const status = record?.status
  if (status === 'done') return 'analyzed'
  if (status === 'failed' || status === 'timeout') return 'failed'
  return null
}

/** Human skip reason; unknown non-empty strings pass through, empty/null become ''. */
export function describeSkipReason(reason: unknown): string {
  if (typeof reason !== 'string' || reason === '') return ''
  return SKIP_REASONS[reason] ?? reason
}

function analysisIdOf(record: { alert_id?: number } | null | undefined): number {
  return typeof record?.alert_id === 'number' && Number.isFinite(record.alert_id) ? record.alert_id : 0
}

/** Newest-first copy; the input array is never mutated. */
export function sortAnalyses<T extends { alert_id?: number }>(records: readonly T[] | null | undefined): T[] {
  if (!Array.isArray(records)) return []
  return [...records].sort((left, right) => analysisIdOf(right) - analysisIdOf(left))
}

/** Merge records by alert_id (`incoming` wins), newest first, capped. */
export function mergeAnalyses<T extends { alert_id?: number }>(
  existing: readonly T[] | null | undefined,
  incoming: readonly T[] | null | undefined,
  cap = 200,
): T[] {
  const byId = new Map<number, T>()
  for (const record of existing ?? []) byId.set(analysisIdOf(record), record)
  for (const record of incoming ?? []) byId.set(analysisIdOf(record), record)
  return [...byId.values()].sort((left, right) => analysisIdOf(right) - analysisIdOf(left)).slice(0, Math.max(0, cap))
}

/** Index by alert_id; a later record for the same alert overwrites the earlier one. */
export function analysisByAlert(records: readonly AnalysisRecord[] | null | undefined): Record<string, AnalysisRecord> {
  const result: Record<string, AnalysisRecord> = {}
  for (const record of records ?? []) {
    if (typeof record?.alert_id !== 'number' || !Number.isFinite(record.alert_id)) continue
    result[String(record.alert_id)] = record
  }
  return result
}
