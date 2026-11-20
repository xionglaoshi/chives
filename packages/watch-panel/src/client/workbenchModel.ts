/**
 * Pure view model for the single-page workbench (T97).
 *
 * It owns everything the page needs to decide without touching React or the
 * DOM: contract normalisation for `/movers` and `/summary`, contract-query
 * building, layout/order rules driven by the trading state, the drawer state
 * machine, the watchlist-by-stock aggregation, the merged event feed and the
 * ask-bar context sentence. Loaded directly by Node in tests, so it stays free
 * of React, `@deepseek-ai/*`, DOM access and non-erasable TypeScript syntax.
 */
import { DASH, formatMove, formatMoney } from './market.ts'
import type { MarketAlert, SparkPoint, TimelineItem, TradingState } from './market.ts'
import { distanceToLimit } from './market.ts'
import type { LimitDistance } from './market.ts'
import type { AlertPayload, AnalysisRecord, QuoteRow } from './viewModel.ts'
import { formatPct, formatPrice } from './viewModel.ts'
import type { Signal } from './signals.ts'

export type MoversKind = 'gainers' | 'losers' | 'active'

export interface MoversFilters {
  includeSt: boolean
  includeNew: boolean
  includeBj: boolean
}

export const DEFAULT_MOVERS_FILTERS: MoversFilters = { includeSt: false, includeNew: false, includeBj: false }
export const MOVERS_PAGE_LIMIT = 8
export const MOVERS_MAX_LIMIT = 20
export const MOVERS_MIN_LIMIT = 5

export interface MoverRow {
  rank: number | null
  code: string
  name: string
  price: number | null
  changePct: number | null
  amountYuan: number | null
  turnoverPct: number | null
  industry: string
}

export interface MoversPayload {
  ok: boolean
  error: string | null
  asOf: string | null
  kind: MoversKind
  rows: MoverRow[]
  filters: MoversFilters
  source: string | null
  stale: boolean
  stateNote: string | null
  reason: string | null
}

export type SummaryTone = 'up' | 'down' | 'neutral' | 'warn'

export interface SummaryRef {
  type: 'index' | 'sector' | 'stock'
  code: string
  name: string
}

export interface SummaryHeadline {
  id: string
  tone: SummaryTone
  title: string
  body: string
  refs: SummaryRef[]
}

export interface SummaryPayload {
  ok: boolean
  error: string | null
  asOf: string | null
  generatedBy: string | null
  headlines: SummaryHeadline[]
  note: string | null
  stale: boolean
  reason: string | null
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

function isMoversKind(value: unknown): value is MoversKind {
  return value === 'gainers' || value === 'losers' || value === 'active'
}

export function normalizeMoverFilters(value: unknown): MoversFilters {
  const row = pick(value)
  return { includeSt: bool(row.include_st), includeNew: bool(row.include_new), includeBj: bool(row.include_bj) }
}

export function normalizeMoverRow(value: unknown): MoverRow {
  const row = pick(value)
  return {
    rank: int(row.rank),
    code: text(row.code),
    name: text(row.name),
    price: num(row.price),
    changePct: num(row.change_pct),
    amountYuan: num(row.amount_yuan),
    turnoverPct: num(row.turnover_pct),
    industry: text(row.industry),
  }
}

export function normalizeMovers(value: unknown): MoversPayload {
  const row = pick(value)
  const kind = isMoversKind(row.kind) ? row.kind : 'gainers'
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'market_error' : null,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    kind,
    rows: list(row.rows).map(normalizeMoverRow).filter((entry) => entry.code !== ''),
    filters: normalizeMoverFilters(row.filters),
    source: typeof row.source === 'string' ? row.source : null,
    stale: bool(row.stale),
    stateNote: note(row.state_note),
    reason: note(row.reason),
  }
}

/** Query string (no leading `?`) for the Host proxy; values are clamped and whitelisted. */
export function moversQuery(
  kind: MoversKind,
  filters: MoversFilters,
  limit: number = MOVERS_PAGE_LIMIT,
): string {
  const safeKind: MoversKind = isMoversKind(kind) ? kind : 'gainers'
  const safeLimit = Number.isInteger(limit) ? Math.min(MOVERS_MAX_LIMIT, Math.max(MOVERS_MIN_LIMIT, limit)) : MOVERS_PAGE_LIMIT
  const flag = (value: boolean): string => (value ? '1' : '0')
  return [
    `kind=${safeKind}`,
    `limit=${safeLimit}`,
    `include_st=${flag(filters.includeSt)}`,
    `include_new=${flag(filters.includeNew)}`,
    `include_bj=${flag(filters.includeBj)}`,
  ].join('&')
}

export function moversPath(kind: MoversKind, filters: MoversFilters, limit: number = MOVERS_PAGE_LIMIT): string {
  return `/api/market/movers?${moversQuery(kind, filters, limit)}`
}

function isSummaryTone(value: unknown): value is SummaryTone {
  return value === 'up' || value === 'down' || value === 'neutral' || value === 'warn'
}

function isSummaryRef(value: unknown): value is SummaryRef {
  const row = pick(value)
  const type = row.type
  return (type === 'index' || type === 'sector' || type === 'stock') && text(row.code) !== ''
}

export function normalizeSummaryHeadline(value: unknown, index: number): SummaryHeadline {
  const row = pick(value)
  const id = text(row.id) || `h${index + 1}`
  return {
    id,
    tone: isSummaryTone(row.tone) ? row.tone : 'neutral',
    title: text(row.title),
    body: text(row.body),
    refs: list(row.refs).filter(isSummaryRef).map((entry) => {
      const ref = pick(entry)
      return {
        type: ref.type as SummaryRef['type'],
        code: text(ref.code),
        name: text(ref.name) || text(ref.code),
      }
    }),
  }
}

export function normalizeSummary(value: unknown): SummaryPayload {
  const row = pick(value)
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'market_error' : null,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    generatedBy: typeof row.generated_by === 'string' ? row.generated_by : null,
    headlines: list(row.headlines).map(normalizeSummaryHeadline).filter((entry) => entry.title !== ''),
    note: note(row.note),
    stale: bool(row.stale),
    reason: note(row.reason),
  }
}

/** Whole minutes between an ISO timestamp and `now`; null when unusable or in the future. */
export function relativeMinutes(iso: string | null | undefined, nowMs: number): number | null {
  if (typeof iso !== 'string') return null
  const then = Date.parse(iso)
  if (!Number.isFinite(then) || !Number.isFinite(nowMs)) return null
  const diff = nowMs - then
  if (diff < 0) return null
  return Math.floor(diff / 60_000)
}

/** Human relative time; the block head uses `N 分钟前`, older stamps fall back to hours/days. */
export function relativeTime(iso: string | null | undefined, nowMs: number): string {
  const minutes = relativeMinutes(iso, nowMs)
  if (minutes === null) return DASH
  if (minutes < 1) return '\u521a\u521a'
  if (minutes < 60) return `${minutes} \u5206\u949f\u524d`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} \u5c0f\u65f6\u524d`
  return `${Math.floor(hours / 24)} \u5929\u524d`
}

export type SparkKind = 'intraday' | 'daily' | null

export function sparkKind(value: unknown): SparkKind {
  return value === 'intraday' || value === 'daily' ? value : null
}

export interface MiniPath {
  path: string
  lastX: number
  lastY: number
  count: number
}

/** Inline-SVG path for a sparkline; fewer than two finite points carries no line. */
export function miniPath(points: readonly SparkPoint[], width = 132, height = 34, pad = 4): MiniPath | null {
  const series = points.filter((point) => Number.isFinite(point.p))
  if (series.length < 2) return null
  const values = series.map((point) => point.p)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const usable = Math.max(1, height - pad * 2)
  const coords = series.map((point, index) => ({
    x: (index / (series.length - 1)) * width,
    y: pad + (1 - (point.p - min) / span) * usable,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
  const last = coords[coords.length - 1]!
  return { path, lastX: last.x, lastY: last.y, count: series.length }
}

export type LayoutMode = 'two-column' | 'single'

/** ≥1280px keeps the two-column market/mine layout; anything narrower is one column. */
export function layoutMode(width: number): LayoutMode {
  return Number.isFinite(width) && width >= 1280 ? 'two-column' : 'single'
}

/** Six index cards per row from 1200px up, otherwise a two-row grid of three. */
export function indexColumns(width: number): 3 | 6 {
  return Number.isFinite(width) && width >= 1200 ? 6 : 3
}

/** The pulse band shrinks to a single line once the page has scrolled past its cards. */
export function pulseCollapsed(scrollTop: number): boolean {
  return Number.isFinite(scrollTop) && scrollTop > 48
}

export type SectionId = 'map' | 'movers' | 'focus' | 'feed'
export type ColumnId = 'market' | 'mine'

/** Fixed reading order on <1280px (T100 §12.2): decide, watchlist, signals, market, done last. */
export type SectionKey = 'decide' | 'focus' | 'signals' | 'map' | 'movers' | 'flows' | 'done'

export const SINGLE_SECTION_ORDER: Record<SectionKey, number> = {
  decide: 1,
  focus: 2,
  signals: 3,
  map: 4,
  movers: 5,
  flows: 6,
  done: 7,
}

/** Reading order inside the single-column layout; only order and emphasis change. */
export function sectionOrder(state: TradingState): SectionId[] {
  if (state === 'open') return ['focus', 'feed', 'map', 'movers']
  if (state === 'pre_open') return ['focus', 'map', 'movers', 'feed']
  return ['map', 'movers', 'focus', 'feed']
}

/** Which column comes first on ≥1280px: the watchlist while trading, the market otherwise. */
export function columnOrder(state: TradingState): ColumnId[] {
  return state === 'open' || state === 'pre_open' ? ['mine', 'market'] : ['market', 'mine']
}

/** After the close the feed collapses into a short "today in review" block. */
export function feedCollapsed(state: TradingState): boolean {
  return state === 'closed' || state === 'holiday'
}

/** Focus rows are emphasised (gold edge, triggered on top) while the market is live. */
export function focusEmphasis(state: TradingState): boolean {
  return state === 'open' || state === 'pre_open'
}

export function preOpenFocusTitle(state: TradingState): 'today' | 'focus' {
  return state === 'pre_open' ? 'today' : 'focus'
}

export interface BreadthSegments {
  up: number
  down: number
  flat: number
  total: number
}

/** Percentage widths for the breadth bar; an empty market is a neutral full bar. */
export function breadthSegments(up: number | null, down: number | null, flat: number | null): BreadthSegments {
  const safeUp = Math.max(0, up ?? 0)
  const safeDown = Math.max(0, down ?? 0)
  const safeFlat = Math.max(0, flat ?? 0)
  const total = safeUp + safeDown + safeFlat
  if (total <= 0) return { up: 0, down: 0, flat: 100, total: 0 }
  return { up: (safeUp / total) * 100, down: (safeDown / total) * 100, flat: (safeFlat / total) * 100, total }
}

export function sealRatioText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH
  return `${(value * 100).toFixed(1)}%`
}

export type DrawerKind = 'sector' | 'stock' | 'analysis' | 'rules' | 'index' | 'signal'

export interface DrawerState {
  kind: DrawerKind | null
  code: string
  id: number | null
}

export const CLOSED_DRAWER: DrawerState = { kind: null, code: '', id: null }

export type DrawerAction =
  | { type: 'open'; kind: DrawerKind; code?: string; id?: number | null }
  | { type: 'close' }
  | { type: 'toggle'; kind: DrawerKind; code?: string; id?: number | null }

const SECTOR_CODE = /^BK[0-9]{4}$/

function validDrawerTarget(kind: DrawerKind, code: string, id: number | null): boolean {
  if (kind === 'sector') return SECTOR_CODE.test(code)
  if (kind === 'stock') return code !== ''
  if (kind === 'index') return code !== ''
  if (kind === 'analysis' || kind === 'signal') return id !== null && Number.isInteger(id) && id > 0
  return true
}

/** One drawer at a time: open replaces, close clears, toggle closes the same target. */
export function drawerReducer(state: DrawerState, action: DrawerAction): DrawerState {
  if (action.type === 'close') return CLOSED_DRAWER
  const code = action.code ?? ''
  const id = action.id ?? null
  if (!validDrawerTarget(action.kind, code, id)) return state
  if (action.type === 'toggle' && state.kind === action.kind && state.code === code && state.id === id) {
    return CLOSED_DRAWER
  }
  return { kind: action.kind, code, id }
}

export function drawerFromRef(ref: SummaryRef): DrawerState {
  if (ref.type === 'sector') return { kind: 'sector', code: ref.code, id: null }
  if (ref.type === 'stock') return { kind: 'stock', code: ref.code, id: null }
  return { kind: 'index', code: ref.code, id: null }
}

export interface FocusLatest {
  key: string
  ts: string | null
  ruleId: string
  summary: string
  status: TimelineItem['status']
  reason: string
}

export interface FocusRule {
  ruleId: string
  description: string
  armed: boolean
  fired: boolean
}

export interface FocusRow {
  code: string
  name: string
  price: number | null
  changePct: number | null
  amountYuan: number | null
  limit: LimitDistance
  rules: FocusRule[]
  latest: FocusLatest | null
  signal: Signal | null
  missing: boolean
}

function latestFor(items: readonly TimelineItem[], code: string): TimelineItem | null {
  for (const item of items) {
    if (item.objectType === 'stock' && item.objectCode === code) return item
  }
  return null
}

function focusLatest(item: TimelineItem | null): FocusLatest | null {
  if (!item) return null
  return {
    key: item.key,
    ts: item.ts,
    ruleId: item.ruleId,
    summary: item.detail || item.title,
    status: item.status,
    reason: item.reason,
  }
}

/**
 * One row per watchlist stock: quote, distance to the nearer limit, armed rules
 * and that stock's newest alert/analysis line. While the market is live, rows
 * with armed or fired rules move to the top; the relative order is otherwise kept.
 */
/** Newest hub signal for one stock code, if any (active list only). */
export function latestSignalFor(signals: readonly Signal[] | null | undefined, code: string): Signal | null {
  if (code === '') return null
  let latest: Signal | null = null
  for (const signal of signals ?? []) {
    if (signal.object.type !== 'stock' || signal.object.code !== code) continue
    if (latest === null || (signal.ts !== null && (latest.ts === null || signal.ts > latest.ts))) latest = signal
  }
  return latest
}

export function buildFocusRows(
  quotes: readonly QuoteRow[],
  rulesByCode: ReadonlyMap<string, readonly FocusRule[]> | null | undefined,
  items: readonly TimelineItem[] | null | undefined,
  triggeredFirst: boolean,
  signals: readonly Signal[] | null | undefined = [],
): FocusRow[] {
  const rows = quotes.map((quote) => {
    const rules = [...(rulesByCode?.get(quote.code) ?? [])]
    return {
      code: quote.code,
      name: quote.name || quote.code,
      price: quote.price,
      changePct: quote.changePct,
      amountYuan: quote.amountYuan,
      limit: distanceToLimit(quote.price, quote.limitUp, quote.limitDown),
      rules,
      latest: focusLatest(latestFor(items ?? [], quote.code)),
      signal: latestSignalFor(signals, quote.code),
      missing: quote.missing,
    }
  })
  if (!triggeredFirst) return rows
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const leftActive = left.row.rules.some((rule) => rule.fired) || left.row.signal !== null ? 0 : 1
    const rightActive = right.row.rules.some((rule) => rule.fired) || right.row.signal !== null ? 0 : 1
    return leftActive - rightActive || left.index - right.index
  }).map((entry) => entry.row)
}

export type FeedChip = 'mine' | 'sector' | 'all'

/** Chip filter applied before aggregation: mine = stock alerts on the watchlist. */
export function filterFeed(items: readonly TimelineItem[], chip: FeedChip, mineCodes: ReadonlySet<string>): TimelineItem[] {
  if (chip === 'all') return [...items]
  if (chip === 'sector') return items.filter((item) => item.objectType === 'sector')
  return items.filter((item) => item.objectType === 'stock' && mineCodes.has(item.objectCode))
}

const SEVERITY_RANK: Record<'L1' | 'L2' | 'L3', number> = { L1: 1, L2: 2, L3: 3 }

export interface FeedRow {
  key: string
  ts: string | null
  ruleId: string
  severity: 'L1' | 'L2' | 'L3' | null
  objectType: TimelineItem['objectType']
  objectNames: string[]
  codes: string[]
  title: string
  status: TimelineItem['status']
  reason: string
  analysisId: number | null
  count: number
  items: TimelineItem[]
}

/** Merge items that share an exact timestamp and rule into one row. */
export function aggregateTimeline(items: readonly TimelineItem[]): FeedRow[] {
  const groups = new Map<string, TimelineItem[]>()
  const order: string[] = []
  for (const item of items) {
    const key = `${item.ts ?? ''}|${item.ruleId}|${item.objectType}`
    const bucket = groups.get(key)
    if (bucket) bucket.push(item)
    else {
      groups.set(key, [item])
      order.push(key)
    }
  }
  return order.map((key) => {
    const rows = groups.get(key)!
    const first = rows[0]!
    let severity: FeedRow['severity'] = null
    for (const row of rows) {
      if (row.severity !== null && (severity === null || SEVERITY_RANK[row.severity] > SEVERITY_RANK[severity])) severity = row.severity
    }
    const analyzing = rows.find((row) => row.status === 'analyzing')
    const analyzed = rows.find((row) => row.analysisId !== null)
    return {
      key: `agg:${key}`,
      ts: first.ts,
      ruleId: first.ruleId,
      severity,
      objectType: first.objectType,
      objectNames: rows.map((row) => row.objectName || row.objectCode),
      codes: rows.map((row) => row.objectCode),
      title: rows.length > 1 ? `${first.title} \u7b49 ${rows.length} \u4e2a` : first.title,
      status: analyzing?.status ?? first.status,
      reason: rows.find((row) => row.reason !== '')?.reason ?? '',
      analysisId: analyzed?.analysisId ?? null,
      count: rows.length,
      items: rows,
    }
  })
}

export function feedRows(items: readonly TimelineItem[], chip: FeedChip, mineCodes: ReadonlySet<string>): FeedRow[] {
  return aggregateTimeline(filterFeed(items, chip, mineCodes))
}

export interface FeedCounts {
  all: number
  mine: number
  sector: number
}

export function feedCounts(items: readonly TimelineItem[], mineCodes: ReadonlySet<string>): FeedCounts {
  return {
    all: items.length,
    mine: filterFeed(items, 'mine', mineCodes).length,
    sector: filterFeed(items, 'sector', mineCodes).length,
  }
}

/** Latest rows for the after-hours "today in review" summary, newest first. */
export function reviewRows(items: readonly TimelineItem[], limit = 3): TimelineItem[] {
  return [...items].slice(0, Math.max(0, limit))
}

export interface AskContextInput {
  stateLabel: string
  indexName?: string | null
  indexChangePct?: number | null
  watchNames?: readonly string[]
}

/** The one public sentence prepended to a question; never holdings or profile data. */
export function askContext(input: AskContextInput): string {
  const parts: string[] = [`\u4ea4\u6613\u72b6\u6001 ${input.stateLabel || '\u672a\u77e5'}`]
  const indexName = (input.indexName ?? '').trim()
  if (indexName !== '') parts.push(`${indexName} ${formatMove(input.indexChangePct ?? null)}`)
  const names = (input.watchNames ?? []).filter((name) => typeof name === 'string' && name.trim() !== '')
  if (names.length === 0) parts.push('\u6211\u7684\u81ea\u9009\uff1a\u65e0')
  else if (names.length <= 5) parts.push(`\u6211\u7684\u81ea\u9009\uff1a${names.join('\u3001')}`)
  else parts.push(`\u6211\u7684\u81ea\u9009\uff1a${names.slice(0, 5).join('\u3001')} \u7b49 ${names.length} \u53ea`)
  return `\uff08\u5f53\u524d\u76ef\u76d8\uff1a${parts.join('\uff1b')}\uff09`
}

export const MAX_ASK_LENGTH = 2000

/** Question with its public context in front; empty input sends nothing. */
export function composeAsk(question: string, context: string): string | null {
  const trimmed = question.trim()
  if (trimmed === '') return null
  const prefix = context.trim() === '' ? '' : `${context.trim()}\n`
  return `${prefix}${trimmed}`.slice(0, MAX_ASK_LENGTH)
}

/** Top-bar search: enter asks the agent to introduce the symbol. */
export function searchAsk(text: string): string | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  return `\u4ecb\u7ecd\u4e00\u4e0b ${trimmed}`.slice(0, MAX_ASK_LENGTH)
}

export function moverAmount(row: MoverRow): string {
  return formatMoney(row.amountYuan)
}

export function moverPrice(row: MoverRow): string {
  return formatPrice(row.price)
}

export function moverChange(row: MoverRow): string {
  return formatMove(row.changePct)
}

export function moverTurnover(row: MoverRow): string {
  return row.turnoverPct === null ? DASH : `${row.turnoverPct.toFixed(2)}%`
}

/** Sort key helper used by the UI to keep the two lists tied to their contract kind. */
export function moversByKind(payloads: Partial<Record<MoversKind, MoversPayload>>, kind: MoversKind): MoverRow[] {
  return payloads[kind]?.rows ?? []
}

export function latestMoverAsOf(payloads: Partial<Record<MoversKind, MoversPayload>>): string | null {
  let latest: string | null = null
  for (const payload of Object.values(payloads)) {
    if (payload?.asOf && (latest === null || payload.asOf > latest)) latest = payload.asOf
  }
  return latest
}

/** Convert a raw market alert into a synthetic timeline item (tests / adapters). */
export function marketAlertItem(alert: MarketAlert): TimelineItem | null {
  if (!Number.isFinite(alert.id) || alert.id <= 0) return null
  return {
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
    status: alert.analysisId !== null ? 'analyzing' : 'pending',
    reason: '',
    analysisId: alert.analysisId,
    raw: alert.raw,
  }
}

export function watchAlertItem(alert: AlertPayload, record: AnalysisRecord | undefined): TimelineItem | null {
  if (typeof alert.id !== 'number' || !Number.isFinite(alert.id)) return null
  return {
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
    detail: '',
    status: record?.status === 'done' ? 'analyzed' : record?.status === 'skipped' ? 'skipped' : record ? 'analyzing' : 'pending',
    reason: record?.reason ?? '',
    analysisId: alert.id,
    raw: alert,
  }
}

/** Signed percent for the summary body references; kept exported for tests. */
export function pctText(value: number | null | undefined): string {
  return formatPct(value)
}
