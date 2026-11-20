/**
 * Pure view model for hub signal cards (T100).
 *
 * Everything the signal card, the "待你决策" partition, the done fold and the
 * detail drawer need is decided here without React or DOM access, so the rules
 * can be loaded directly by Node in tests. Labels default to the strings in the
 * design mockup; the hub may override them with `kind_label` / `direction_label`.
 */
import { DASH, formatMoney, formatMove } from './market.ts'
import { formatClock, formatPrice } from './viewModel.ts'

export type SignalKind =
  | 'plan_proposal' | 'plan_entry' | 'plan_giveup' | 'plan_other'
  | 'sector' | 'risk' | 'opportunity' | 'info'

export type SignalTone = 'plan' | 'opp' | 'risk' | 'sector' | 'info'

export type SignalStatus = 'new' | 'seen' | 'snoozed' | 'done' | 'ignored'

export type SignalDirection = 'bull' | 'bear' | 'neutral'

export type SignalObjectType = 'stock' | 'sector' | 'market' | 'index'

export type SignalSeverity = 'L1' | 'L2' | 'L3'

export type PrimaryAction = 'open' | 'remove_watch' | 'research' | 'confirm_plan' | 'ack'

export type SignalFilter = 'all' | 'decide' | 'stock' | 'sector'

export interface RangeContext {
  type: 'range'
  levelLo: number | null
  levelHi: number | null
  stop: number | null
  price: number | null
  min: number
  max: number
  giveup: boolean
}

export interface RankContext {
  type: 'rank'
  from: number | null
  to: number | null
  sharePct: number | null
  spark: number[]
}

export interface SparkContext {
  type: 'spark'
  points: number[]
  label: string
}

export type SignalContext = RangeContext | RankContext | SparkContext | null

export interface SignalObject {
  type: SignalObjectType
  code: string
  name: string
}

export interface SignalSource {
  label: string
  alertIds: number[]
  analysisId: number | null
  planId: number | null
  ruleId: string | null
}

export interface SignalPrimary {
  label: string
  action: PrimaryAction
}

export interface Signal {
  id: number
  ts: string | null
  kind: SignalKind
  kindLabel: string
  decide: boolean
  severity: SignalSeverity | null
  status: SignalStatus
  snoozeUntil: string | null
  object: SignalObject
  title: string
  direction: SignalDirection
  directionLabel: string
  conclusion: string
  brief: string
  context: SignalContext
  source: SignalSource
  mergedCount: number
  primary: SignalPrimary
  detailAvailable: boolean
}

export interface SignalsPayload {
  ok: boolean
  error: string | null
  asOf: string | null
  signals: Signal[]
  counts: { decide: number; active: number; snoozed: number; done: number }
  mergedToday: number
  nextId: number | null
}

export interface SignalSection {
  conclusion: string
  direction: string
  points: string[]
  detail: string
}

export interface SignalDetail {
  signal: Signal | null
  markdown: string
  truncated: boolean
  sections: SignalSection
}

const KIND_TONE: Record<SignalKind, SignalTone> = {
  plan_proposal: 'plan',
  plan_entry: 'plan',
  plan_giveup: 'plan',
  plan_other: 'plan',
  opportunity: 'opp',
  risk: 'risk',
  sector: 'sector',
  info: 'info',
}

const TONE_TOKEN: Record<SignalTone, string> = {
  plan: 'var(--chives-sig-plan)',
  opp: 'var(--chives-sig-opp)',
  risk: 'var(--chives-sig-risk)',
  sector: 'var(--chives-sig-sector)',
  info: 'var(--chives-sig-info)',
}

const KIND_LABEL: Record<SignalKind, string> = {
  plan_proposal: '\u8ba1\u5212\u5f85\u786e\u8ba4',
  plan_entry: '\u8ba1\u5212\u89e6\u53d1 \u00b7 \u8fdb\u573a',
  plan_giveup: '\u8ba1\u5212\u89e6\u53d1 \u00b7 \u4e0d\u518d\u8ddf',
  plan_other: '\u8ba1\u5212\u89e6\u53d1',
  opportunity: '\u673a\u4f1a',
  risk: '\u98ce\u9669',
  sector: '\u677f\u5757\u5f02\u52a8',
  info: '\u4fe1\u606f',
}

const DIRECTION_LABEL: Record<SignalDirection, string> = {
  bull: '\u504f\u591a',
  bear: '\u504f\u7a7a',
  neutral: '\u4e2d\u6027',
}

const DIRECTION_GLYPH: Record<SignalDirection, string> = {
  bull: '\u25b2',
  bear: '\u25bc',
  neutral: '\u2014',
}

const PRIMARY_ACTIONS: readonly PrimaryAction[] = ['open', 'remove_watch', 'research', 'confirm_plan', 'ack']

const SEVERITY_RANK: Record<SignalSeverity, number> = { L1: 1, L2: 2, L3: 3 }

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

export function isSignalKind(value: unknown): value is SignalKind {
  return typeof value === 'string' && value in KIND_TONE
}

export function isSignalStatus(value: unknown): value is SignalStatus {
  return value === 'new' || value === 'seen' || value === 'snoozed' || value === 'done' || value === 'ignored'
}

export function isSignalDirection(value: unknown): value is SignalDirection {
  return value === 'bull' || value === 'bear' || value === 'neutral'
}

export function isPrimaryAction(value: unknown): value is PrimaryAction {
  return typeof value === 'string' && (PRIMARY_ACTIONS as readonly string[]).includes(value)
}

/** Type colour family: plan gold, opportunity blue, risk orange, sector purple, info grey. */
export function signalTone(kind: SignalKind): SignalTone {
  return KIND_TONE[kind] ?? 'info'
}

/** Token reference for the type colour; components never carry the value itself. */
export function signalToneToken(kind: SignalKind): string {
  return TONE_TOKEN[signalTone(kind)]
}

export function signalKindLabel(kind: SignalKind, provided?: string | null): string {
  const label = (provided ?? '').trim()
  return label === '' ? KIND_LABEL[kind] ?? KIND_LABEL.info : label
}

export interface DirectionMeta {
  tone: 'bull' | 'bear' | 'flat'
  glyph: string
  label: string
}

/** Direction pill: bullish red, bearish green, neutral flat; the glyph is never colour-only. */
export function directionMeta(direction: SignalDirection, provided?: string | null): DirectionMeta {
  const label = (provided ?? '').trim() || DIRECTION_LABEL[direction]
  return {
    tone: direction === 'bull' ? 'bull' : direction === 'bear' ? 'bear' : 'flat',
    glyph: DIRECTION_GLYPH[direction],
    label,
  }
}

function normalizeContext(value: unknown): SignalContext {
  const row = pick(value)
  if (row.type === 'range') {
    const min = num(row.min)
    const max = num(row.max)
    return {
      type: 'range',
      levelLo: num(row.level_lo),
      levelHi: num(row.level_hi),
      stop: num(row.stop),
      price: num(row.price),
      min: min ?? 0,
      max: max ?? 0,
      giveup: bool(row.giveup),
    }
  }
  if (row.type === 'rank') {
    return {
      type: 'rank',
      from: int(row.from),
      to: int(row.to),
      sharePct: num(row.share_pct),
      spark: list(row.spark).map(num).filter((entry): entry is number => entry !== null),
    }
  }
  if (row.type === 'spark') {
    return {
      type: 'spark',
      points: list(row.points).map(num).filter((entry): entry is number => entry !== null),
      label: text(row.label),
    }
  }
  return null
}

function normalizeSource(value: unknown): SignalSource {
  const row = pick(value)
  return {
    label: text(row.label),
    alertIds: list(row.alert_ids).map(int).filter((entry): entry is number => entry !== null),
    analysisId: int(row.analysis_id),
    planId: int(row.plan_id),
    ruleId: note(row.rule_id),
  }
}

function normalizePrimary(value: unknown): SignalPrimary {
  const row = pick(value)
  const action = isPrimaryAction(row.action) ? row.action : 'open'
  return { label: text(row.label) || '\u67e5\u770b\u5206\u6790', action }
}

/** Normalise one hub signal; a non-positive id makes the record unusable (null). */
export function normalizeSignal(value: unknown): Signal | null {
  const row = pick(value)
  const rawId = row.id
  if (typeof rawId !== 'number' || !Number.isInteger(rawId) || rawId <= 0) return null
  const id = rawId
  const kind = isSignalKind(row.kind) ? row.kind : 'info'
  const object = pick(row.object)
  const objectType: SignalObjectType = object.type === 'stock' || object.type === 'sector' || object.type === 'market' || object.type === 'index'
    ? object.type
    : 'stock'
  const direction = isSignalDirection(row.direction) ? row.direction : 'neutral'
  const severity = row.severity === 'L1' || row.severity === 'L2' || row.severity === 'L3' ? row.severity : null
  return {
    id,
    ts: typeof row.ts === 'string' ? row.ts : null,
    kind,
    kindLabel: signalKindLabel(kind, text(row.kind_label)),
    decide: bool(row.decide),
    severity,
    status: isSignalStatus(row.status) ? row.status : 'new',
    snoozeUntil: typeof row.snooze_until === 'string' ? row.snooze_until : null,
    object: { type: objectType, code: text(object.code), name: text(object.name) || text(object.code) },
    title: text(row.title) || KIND_LABEL[kind],
    direction,
    directionLabel: text(row.direction_label) || DIRECTION_LABEL[direction],
    conclusion: text(row.conclusion),
    brief: text(row.brief),
    context: normalizeContext(row.context),
    source: normalizeSource(row.source),
    mergedCount: Math.max(1, int(row.merged_count) ?? 1),
    primary: normalizePrimary(row.primary),
    detailAvailable: bool(row.detail_available),
  }
}

export function normalizeSignals(value: unknown): SignalsPayload {
  const row = pick(value)
  const counts = pick(row.counts)
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'hub_error' : null,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    signals: list(row.signals).map(normalizeSignal).filter((entry): entry is Signal => entry !== null),
    counts: {
      decide: int(counts.decide) ?? 0,
      active: int(counts.active) ?? 0,
      snoozed: int(counts.snoozed) ?? 0,
      done: int(counts.done) ?? 0,
    },
    mergedToday: int(row.merged_today) ?? 0,
    nextId: int(row.next_id),
  }
}

function timeOf(signal: Signal): number {
  return signal.ts === null ? Number.NaN : Date.parse(signal.ts)
}

/** Severity first, then newest, then highest id; invalid timestamps sort last. */
export function compareSignals(left: Signal, right: Signal): number {
  const leftRank = left.severity === null ? 0 : SEVERITY_RANK[left.severity]
  const rightRank = right.severity === null ? 0 : SEVERITY_RANK[right.severity]
  if (leftRank !== rightRank) return rightRank - leftRank
  const leftTime = timeOf(left)
  const rightTime = timeOf(right)
  const leftValid = Number.isFinite(leftTime)
  const rightValid = Number.isFinite(rightTime)
  if (leftValid && rightValid && leftTime !== rightTime) return rightTime - leftTime
  if (leftValid !== rightValid) return leftValid ? -1 : 1
  return right.id - left.id
}

export function rankSignals(signals: readonly Signal[]): Signal[] {
  return [...signals].sort(compareSignals)
}

/** Active = new or seen; done/ignored/snoozed never sit in the two active lists. */
export function activeSignals(signals: readonly Signal[]): Signal[] {
  return signals.filter((signal) => signal.status === 'new' || signal.status === 'seen')
}

export interface SignalPartition {
  decide: Signal[]
  rail: Signal[]
}

/**
 * `decide=true` signals fill "待你决策" (top three by severity/time); the rest,
 * including decide signals beyond the third, fall into the ordinary rail.
 */
export function partitionSignals(signals: readonly Signal[], limit = 3): SignalPartition {
  const active = rankSignals(activeSignals(signals))
  const decide = active.filter((signal) => signal.decide).slice(0, Math.max(0, limit))
  const top = new Set(decide.map((signal) => signal.id))
  return { decide, rail: active.filter((signal) => !top.has(signal.id)) }
}

/** Chip filter applied on the client; the state stays while data refreshes. */
export function filterSignals(signals: readonly Signal[], filter: SignalFilter): Signal[] {
  switch (filter) {
    case 'decide':
      return signals.filter((signal) => signal.decide)
    case 'stock':
      return signals.filter((signal) => signal.object.type === 'stock')
    case 'sector':
      return signals.filter((signal) => signal.object.type === 'sector')
    default:
      return [...signals]
  }
}

export interface DoneStats {
  count: number
  merged: number
}

/** Done/ignored count plus the extra events folded into those cards. */
export function doneStats(signals: readonly Signal[]): DoneStats {
  const done = signals.filter((signal) => signal.status === 'done' || signal.status === 'ignored')
  return {
    count: done.length,
    merged: done.reduce((sum, signal) => sum + Math.max(0, signal.mergedCount - 1), 0),
  }
}

/** Newest 20 done cards shown after expanding the folded row (time order, not severity). */
export function doneRows(signals: readonly Signal[], limit = 20): Signal[] {
  return signals
    .filter((signal) => signal.status === 'done' || signal.status === 'ignored')
    .sort((left, right) => {
      const leftTime = timeOf(left)
      const rightTime = timeOf(right)
      const leftValid = Number.isFinite(leftTime)
      const rightValid = Number.isFinite(rightTime)
      if (leftValid && rightValid && leftTime !== rightTime) return rightTime - leftTime
      if (leftValid !== rightValid) return leftValid ? -1 : 1
      return right.id - left.id
    })
    .slice(0, Math.max(0, limit))
}

export function signalTime(signal: Signal): string {
  return formatClock(signal.ts)
}

export function signalObjectLabel(signal: Signal): string {
  const name = signal.object.name.trim()
  const code = signal.object.code.trim()
  if (name !== '' && code !== '' && name !== code) return `${name}\uff08${code}\uff09`
  return name || code || DASH
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, value))
}

export interface RangeGeometry {
  giveup: boolean
  label: string
  zoneLeft: number | null
  zoneWidth: number | null
  markerLeft: number | null
  priceLeft: number
  priceText: string
  markerText: string
  zoneText: string
}

function positionOf(value: number | null, min: number, max: number): number | null {
  if (value === null) return null
  if (max <= min) return 50
  return clampPercent(((value - min) / (max - min)) * 100)
}

/**
 * Geometry for the entry-range widget: the zone between level_lo/level_hi, a
 * stop or give-up marker and the current-price dot. Values are clamped to the
 * bar so a price outside [min,max] still renders at the edge, never off-track.
 */
export function rangeGeometry(context: RangeContext): RangeGeometry {
  const min = context.min
  const max = context.max
  const priceLeft = positionOf(context.price, min, max) ?? 0
  const zoneLeft = positionOf(context.levelLo, min, max)
  const zoneEnd = positionOf(context.levelHi, min, max)
  const markerValue = context.giveup ? context.levelLo : context.stop
  return {
    giveup: context.giveup,
    label: context.giveup ? '\u73b0\u4ef7 vs \u653e\u5f03\u4f4d' : '\u73b0\u4ef7 vs \u8fdb\u573a\u533a\u95f4',
    zoneLeft: zoneLeft === null || zoneEnd === null || context.levelLo === context.levelHi ? null : Math.min(zoneLeft, zoneEnd),
    zoneWidth: zoneLeft === null || zoneEnd === null || context.levelLo === context.levelHi ? null : Math.abs(zoneEnd - zoneLeft),
    markerLeft: positionOf(markerValue, min, max),
    priceLeft,
    priceText: context.price === null ? DASH : formatPrice(context.price),
    markerText: markerValue === null ? '' : `${context.giveup ? '\u653e\u5f03\u4f4d' : '\u6b62\u635f'} ${formatPrice(markerValue)}`,
    zoneText: context.giveup || context.levelLo === null || context.levelHi === null
      ? ''
      : `${formatPrice(context.levelLo)} \u2013 ${formatPrice(context.levelHi)}`,
  }
}

export interface SparkGeometry {
  path: string
  lastX: number
  lastY: number
  count: number
}

/** Inline-SVG path for the 100x36 context sparkline; flat series sit on the mid line. */
export function sparkGeometry(points: readonly number[], width = 100, height = 36, pad = 4): SparkGeometry | null {
  const series = points.filter((value) => Number.isFinite(value))
  if (series.length < 2) return null
  const min = Math.min(...series)
  const max = Math.max(...series)
  const span = max - min
  const usable = Math.max(1, height - pad * 2)
  const coords = series.map((value, index) => ({
    x: (index / (series.length - 1)) * width,
    y: span === 0 ? height / 2 : pad + (1 - (value - min) / span) * usable,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
  const last = coords[coords.length - 1]!
  return { path, lastX: last.x, lastY: last.y, count: series.length }
}

export interface RankGeometry {
  from: string
  to: string
  shareText: string
  spark: SparkGeometry | null
}

export function rankGeometry(context: RankContext): RankGeometry {
  return {
    from: context.from === null ? DASH : String(context.from),
    to: context.to === null ? DASH : String(context.to),
    shareText: context.sharePct === null ? DASH : `${context.sharePct.toFixed(1)}%`,
    spark: sparkGeometry(context.spark),
  }
}

export interface SnoozeOption {
  value: '30m' | 'close' | 'next_open'
  label: string
}

/** Contract `until` presets offered by the "稍后提醒" menu. */
export const SNOOZE_OPTIONS: readonly SnoozeOption[] = [
  { value: '30m', label: '30 \u5206\u949f\u540e' },
  { value: 'close', label: '\u6536\u76d8\u524d' },
  { value: 'next_open', label: '\u660e\u5929\u5f00\u76d8' },
]

export function isSnoozePreset(value: unknown): value is SnoozeOption['value'] {
  return value === '30m' || value === 'close' || value === 'next_open'
}

export function recheckPrompt(signal: Signal): string {
  return `\u8bf7\u91cd\u65b0\u5206\u6790 ${signalObjectLabel(signal)} \u7684\u4fe1\u53f7\uff1a${signal.title}`
}

export function researchPrompt(signal: Signal): string {
  return `\u5e2e\u6211\u7814\u7a76\u4e00\u4e0b ${signalObjectLabel(signal)} \u7684\u8fd9\u4e2a\u4fe1\u53f7\uff1a${signal.title}`
}

export function removeWatchPrompt(signal: Signal): string {
  return `\u5e2e\u6211\u628a ${signalObjectLabel(signal)} \u4ece\u81ea\u9009\u548c\u76ef\u76d8\u91cc\u79fb\u9664\u3002`
}

/** Text the primary button fills into the ask bar, or null when it opens a drawer/acts. */
export function fillPrompt(signal: Signal): string | null {
  switch (signal.primary.action) {
    case 'remove_watch':
      return removeWatchPrompt(signal)
    case 'research':
      return researchPrompt(signal)
    default:
      return null
  }
}

/** The conclusion is plain text in the card; no markdown/HTML is interpreted. */
export function conclusionText(signal: Signal): string {
  return signal.conclusion.trim() || signal.brief.trim() || DASH
}

export function mergedLabel(signal: Signal): string | null {
  return signal.mergedCount > 1 ? `\u5df2\u5408\u5e76 ${signal.mergedCount} \u6761\u540c\u7c7b` : null
}

export function signalAmount(yuan: number | null | undefined): string {
  return formatMoney(yuan)
}

export function signalMove(pct: number | null | undefined): string {
  return formatMove(pct)
}

function normalizePoints(value: unknown): string[] {
  return list(value).map((entry) => {
    if (typeof entry === 'string') return entry.trim()
    if (isRecord(entry)) return text(entry.text).trim()
    return ''
  }).filter((entry) => entry !== '')
}

export function normalizeSections(value: unknown): SignalSection {
  const row = pick(value)
  return {
    conclusion: text(row.conclusion),
    direction: text(row.direction),
    points: normalizePoints(row.points),
    detail: text(row.detail),
  }
}

/**
 * One detail record: the signal plus the analysis file rendered as inert text.
 * `markdown` is never parsed or injected as HTML by the drawer.
 */
export function normalizeSignalDetail(value: unknown, fallback: Signal | null): SignalDetail {
  const row = pick(value)
  const analysis = pick(row.analysis)
  const signal = normalizeSignal(row.signal ?? row) ?? fallback
  return {
    signal,
    markdown: text(analysis.markdown ?? row.markdown),
    truncated: bool(analysis.truncated ?? row.truncated),
    sections: normalizeSections(analysis.sections ?? row.sections),
  }
}
