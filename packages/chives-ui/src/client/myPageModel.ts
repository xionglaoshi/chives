/**
 * Pure view model for the "我的" page (T101). Everything here is normalisation,
 * formatting and deterministic derivation so `node --test` can load it without
 * React or the DOM. Portfolio values never leave component memory: this module
 * only reads the hub contract and never persists a position.
 */
import { DASH, formatMoney, formatMove, formatPct, formatPrice } from './myPageFormat.ts'

export const MASK = '\u2022\u2022\u2022\u2022'
export const HIDDEN_STORAGE_KEY = 'chives.my.hidden'
export const IMPORT_PROMPT = '我要导入持仓。我会粘贴券商导出的持仓表（或截图/口述），请先整理成标准行并展示差异，我确认后再保存。'
export const DIAGNOSE_PROMPT = '请用 portfolio-diagnosis 技能诊断我的持仓。'

export const HISTORY_RANGE_DAYS = { '30': 30, '90': 90, all: 365 } as const
export type HistoryRange = keyof typeof HISTORY_RANGE_DAYS

export const POSITION_SORT_KEYS = ['name', 'qty', 'cost', 'price', 'dayPnl', 'pnl', 'weight'] as const
export type PositionSortKey = (typeof POSITION_SORT_KEYS)[number]
export type SortDirection = 'asc' | 'desc'

export interface PositionSort {
  key: PositionSortKey
  dir: SortDirection
}

export const DEFAULT_SORT: PositionSort = { key: 'weight', dir: 'desc' }

export type ChangeSide = 'up' | 'down' | 'flat'

export interface PortfolioPosition {
  code: string
  name: string
  qty: number | null
  costPriceCny: number | null
  priceCny: number | null
  prevCloseCny: number | null
  changePct: number | null
  marketValueCny: number | null
  pnlCny: number | null
  pnlPct: number | null
  dayPnlCny: number | null
  weightPct: number | null
  sellableToday: boolean
  priceUnavailable: boolean
}

export interface PortfolioTotals {
  marketValueCny: number | null
  costCny: number | null
  pnlCny: number | null
  pnlPct: number | null
  dayPnlCny: number | null
  dayPnlPct: number | null
  cashCny: number | null
  totalAssetsCny: number | null
  positionRatioPct: number | null
  cashKnown: boolean
}

export interface PortfolioRisk {
  annualizedVolPct: number | null
  beta: number | null
  maxDrawdownPct: number | null
  top1WeightPct: number | null
  effectiveN: number | null
}

export interface PortfolioOverview {
  ok: boolean
  asOf: string | null
  quoteTime: string | null
  empty: boolean
  totals: PortfolioTotals
  positions: PortfolioPosition[]
  risk: PortfolioRisk | null
  riskPending: boolean
  riskReason: string | null
  historyDays: number | null
}

export interface HistoryPoint {
  date: string
  marketValueCny: number | null
  totalAssetsCny: number | null
  pnlCny: number | null
  dayPnlCny: number | null
}

export interface HistoryPayload {
  ok: boolean
  points: HistoryPoint[]
  note: string | null
}

export interface HistoryGeometry {
  path: string
  area: string
  coords: Array<{ x: number; y: number; value: number; date: string }>
  min: number
  max: number
  width: number
  height: number
  side: ChangeSide
  change: number
  changePct: number | null
}

export interface AllocationSegment {
  key: string
  code: string | null
  name: string
  pct: number
  color: string
}

export interface WatchRow {
  code: string
  name: string
  price: number | null
  changePct: number | null
  held: boolean
}

export interface RiskMetric {
  key: 'vol' | 'drawdown' | 'beta' | 'top1' | 'effectiveN'
  value: number | null
}

export interface RiskItem {
  key: RiskMetric['key']
  label: string
  value: string
  note: string
}

export type PositionFlag = 't1' | 'limit_up' | 'limit_down' | 'missing'

/** Categorical tokens for the allocation bar; red/green hues (cat-2/cat-7) are excluded. */
export const ALLOCATION_COLORS: readonly string[] = [
  'var(--chives-cat-1)',
  'var(--chives-cat-3)',
  'var(--chives-cat-4)',
  'var(--chives-cat-5)',
  'var(--chives-cat-6)',
  'var(--chives-cat-8)',
]

function pick(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function bool(value: unknown): boolean {
  return value === true
}

function sumOrNull(values: Array<number | null>): number | null {
  let total = 0
  let seen = false
  for (const value of values) {
    if (value === null) continue
    total += value
    seen = true
  }
  return seen ? total : null
}

function ratio(part: number | null, whole: number | null): number | null {
  if (part === null || whole === null || whole <= 0) return null
  return (part / whole) * 100
}

function normalizeTotals(value: unknown): PortfolioTotals {
  const row = pick(value)
  const cash = num(row.cash_cny)
  return {
    marketValueCny: num(row.market_value_cny),
    costCny: num(row.cost_cny),
    pnlCny: num(row.pnl_cny),
    pnlPct: num(row.pnl_pct),
    dayPnlCny: num(row.day_pnl_cny),
    dayPnlPct: num(row.day_pnl_pct),
    cashCny: cash,
    totalAssetsCny: num(row.total_assets_cny),
    positionRatioPct: num(row.position_ratio_pct),
    cashKnown: cash !== null,
  }
}

function normalizePosition(value: unknown): PortfolioPosition {
  const row = pick(value)
  const code = text(row.code)
  const name = text(row.name) || code
  const qty = num(row.qty)
  const costPriceCny = num(row.cost_price_cny)
  const priceCny = num(row.price_cny)
  const prevCloseCny = num(row.prev_close_cny)
  const computedChange = priceCny !== null && prevCloseCny !== null && prevCloseCny > 0
    ? ((priceCny - prevCloseCny) / prevCloseCny) * 100
    : null
  const marketValueCny = num(row.market_value_cny)
    ?? (priceCny !== null && qty !== null ? priceCny * qty : null)
  const costTotal = costPriceCny !== null && qty !== null ? costPriceCny * qty : null
  const pnlCny = num(row.pnl_cny)
    ?? (marketValueCny !== null && costTotal !== null ? marketValueCny - costTotal : null)
  const pnlPct = num(row.pnl_pct)
    ?? ratio(pnlCny, costTotal)
  const dayPnlCny = num(row.day_pnl_cny)
    ?? (priceCny !== null && prevCloseCny !== null && qty !== null ? (priceCny - prevCloseCny) * qty : null)
  return {
    code,
    name,
    qty,
    costPriceCny,
    priceCny,
    prevCloseCny,
    changePct: num(row.change_pct) ?? computedChange,
    marketValueCny,
    pnlCny,
    pnlPct,
    dayPnlCny,
    weightPct: num(row.weight_pct),
    sellableToday: row.sellable_today !== false,
    priceUnavailable: bool(row.price_unavailable),
  }
}

function deriveTotals(hub: PortfolioTotals, positions: readonly PortfolioPosition[]): PortfolioTotals {
  if (positions.length === 0) {
    const cash = hub.cashCny
    const totalAssets = hub.totalAssetsCny ?? (cash !== null ? cash + (hub.marketValueCny ?? 0) : null)
    return {
      ...hub,
      totalAssetsCny: totalAssets,
      positionRatioPct: ratio(hub.marketValueCny, totalAssets),
    }
  }
  const valued = positions.filter((position) => !position.priceUnavailable)
  const marketValueCny = sumOrNull(valued.map((position) => position.marketValueCny)) ?? hub.marketValueCny
  const costCny = sumOrNull(valued.map((position) => (
    position.costPriceCny !== null && position.qty !== null ? position.costPriceCny * position.qty : null
  ))) ?? hub.costCny
  const pnlCny = sumOrNull(valued.map((position) => position.pnlCny)) ?? hub.pnlCny
  const dayPnlCny = sumOrNull(valued.map((position) => position.dayPnlCny)) ?? hub.dayPnlCny
  const cash = hub.cashCny
  const totalAssets = hub.totalAssetsCny ?? (cash !== null && marketValueCny !== null ? cash + marketValueCny : null)
  const previousValue = marketValueCny !== null && dayPnlCny !== null ? marketValueCny - dayPnlCny : null
  return {
    marketValueCny,
    costCny,
    pnlCny,
    pnlPct: ratio(pnlCny, costCny) ?? hub.pnlPct,
    dayPnlCny,
    dayPnlPct: ratio(dayPnlCny, previousValue) ?? hub.dayPnlPct,
    cashCny: cash,
    totalAssetsCny: totalAssets,
    positionRatioPct: ratio(marketValueCny, totalAssets),
    cashKnown: hub.cashKnown,
  }
}

function normalizeRisk(value: unknown): PortfolioRisk | null {
  const row = pick(value)
  if (Object.keys(row).length === 0) return null
  return {
    annualizedVolPct: num(row.annualized_vol_pct),
    beta: num(row.beta),
    maxDrawdownPct: num(row.max_drawdown_pct),
    top1WeightPct: num(row.top1_weight_pct),
    effectiveN: num(row.effective_n),
  }
}

/** Normalise `/portfolio/overview`; unknown shapes degrade to an empty portfolio. */
export function normalizePortfolioOverview(value: unknown): PortfolioOverview {
  const row = pick(value)
  const positions = list(row.positions)
    .map(normalizePosition)
    .filter((position) => position.code !== '')
  const totals = deriveTotals(normalizeTotals(row.totals), positions)
  const withWeights = positions.map((position) => ({
    ...position,
    weightPct: position.weightPct ?? ratio(position.marketValueCny, totals.totalAssetsCny),
  }))
  return {
    ok: row.ok !== false,
    asOf: text(row.as_of) || null,
    quoteTime: text(row.quote_time) || null,
    empty: bool(row.empty) || positions.length === 0,
    totals,
    positions: withWeights,
    risk: normalizeRisk(row.risk),
    riskPending: bool(row.risk_pending),
    riskReason: text(row.risk_reason) || text(row.reason) || null,
    historyDays: num(row.history_days),
  }
}

/** Normalise `/portfolio/history`; points are sorted by date, duplicates collapse to the last row. */
export function normalizeHistory(value: unknown): HistoryPayload {
  const row = pick(value)
  const byDate = new Map<string, HistoryPoint>()
  for (const entry of list(row.points)) {
    const point = pick(entry)
    const date = text(point.date)
    if (date === '') continue
    byDate.set(date, {
      date,
      marketValueCny: num(point.market_value_cny),
      totalAssetsCny: num(point.total_assets_cny),
      pnlCny: num(point.pnl_cny),
      dayPnlCny: num(point.day_pnl_cny),
    })
  }
  const points = [...byDate.values()].sort((left, right) => left.date.localeCompare(right.date))
  return { ok: row.ok !== false, points, note: text(row.note) || null }
}

/** Value the curve plots: total assets, falling back to market value. */
export function historyValue(point: HistoryPoint): number | null {
  return point.totalAssetsCny ?? point.marketValueCny
}

/** Last N daily snapshots; `all` keeps everything the hub recorded. */
export function historyRangeSlice(points: readonly HistoryPoint[], range: HistoryRange): HistoryPoint[] {
  const days = HISTORY_RANGE_DAYS[range] ?? 90
  return points.slice(Math.max(0, points.length - days))
}

export function historyDays(range: HistoryRange): number {
  return HISTORY_RANGE_DAYS[range] ?? 90
}

/** Viewport geometry for the area line; null when fewer than two usable points exist. */
export function historyGeometry(
  points: readonly HistoryPoint[],
  width = 600,
  height = 180,
  pad = 12,
): HistoryGeometry | null {
  const series = points
    .map((point) => ({ date: point.date, value: historyValue(point) }))
    .filter((point): point is { date: string; value: number } => point.value !== null)
  if (series.length < 2) return null
  const values = series.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const usableWidth = Math.max(1, width - pad * 2)
  const usableHeight = Math.max(1, height - pad * 2)
  const coords = series.map((point, index) => ({
    x: pad + (index / (series.length - 1)) * usableWidth,
    y: pad + (1 - (point.value - min) / span) * usableHeight,
    value: point.value,
    date: point.date,
  }))
  const path = coords.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ')
  const first = coords[0]!
  const last = coords[coords.length - 1]!
  const change = last.value - first.value
  return {
    path,
    area: `${path} L${last.x.toFixed(2)} ${height} L${first.x.toFixed(2)} ${height} Z`,
    coords,
    min,
    max,
    width,
    height,
    side: change === 0 ? 'flat' : change > 0 ? 'up' : 'down',
    change,
    changePct: first.value > 0 ? (change / first.value) * 100 : null,
  }
}

/** Nearest point index for a hover ratio over the chart width. */
export function historyPointAt(geometry: HistoryGeometry | null, ratio: number): number | null {
  if (geometry === null || geometry.coords.length === 0) return null
  const clamped = Math.min(1, Math.max(0, Number.isFinite(ratio) ? ratio : 0))
  return Math.round(clamped * (geometry.coords.length - 1))
}

/** Number of recorded snapshots, and whether a curve can be drawn at all. */
export function historyReadiness(points: readonly HistoryPoint[]): { count: number; enough: boolean } {
  const count = points.filter((point) => historyValue(point) !== null).length
  return { count, enough: count >= 2 }
}

/** Sort positions by a column; missing values always trail, ties break by code. */
export function sortPositions(rows: readonly PortfolioPosition[], sort: PositionSort): PortfolioPosition[] {
  const factor = sort.dir === 'asc' ? 1 : -1
  const valueOf = (row: PortfolioPosition): number | string | null => {
    if (sort.key === 'name') return row.name === '' ? null : row.name
    if (sort.key === 'qty') return row.qty
    if (sort.key === 'cost') return row.costPriceCny
    if (sort.key === 'price') return row.priceCny
    if (sort.key === 'dayPnl') return row.dayPnlCny
    if (sort.key === 'pnl') return row.pnlCny
    return row.weightPct
  }
  return [...rows].sort((left, right) => {
    const a = valueOf(left)
    const b = valueOf(right)
    if (a === null && b === null) return left.code.localeCompare(right.code)
    if (a === null) return 1
    if (b === null) return -1
    const compared = typeof a === 'string' && typeof b === 'string'
      ? (a < b ? -1 : a > b ? 1 : 0)
      : Number(a) - Number(b)
    if (compared !== 0) return compared * factor
    return left.code.localeCompare(right.code)
  })
}

/** Clicking the active header flips direction; a new column starts descending except names. */
export function toggleSort(current: PositionSort, key: PositionSortKey): PositionSort {
  if (current.key === key) return { key, dir: current.dir === 'desc' ? 'asc' : 'desc' }
  return { key, dir: key === 'name' ? 'asc' : 'desc' }
}

/** A-share daily price limits by board; unknown boards use the 10% main-board band. */
export function limitFlag(code: string, changePct: number | null): 'limit_up' | 'limit_down' | null {
  if (changePct === null) return null
  const digits = code.replace(/[^0-9]/g, '')
  const threshold = /^(300|301|688|689)/.test(digits)
    ? 19.5
    : /^(4|8|92)/.test(digits)
      ? 29.5
      : 9.5
  if (changePct >= threshold) return 'limit_up'
  if (changePct <= -threshold) return 'limit_down'
  return null
}

export function positionFlags(position: PortfolioPosition): PositionFlag[] {
  const flags: PositionFlag[] = []
  if (position.priceUnavailable) flags.push('missing')
  if (!position.sellableToday) flags.push('t1')
  const limit = limitFlag(position.code, position.changePct)
  if (limit !== null) flags.push(limit)
  return flags
}

/** Five named risk metrics, formatted by the component with locale copy. */
export function riskMetrics(risk: PortfolioRisk): RiskMetric[] {
  return [
    { key: 'vol', value: risk.annualizedVolPct },
    { key: 'drawdown', value: risk.maxDrawdownPct },
    { key: 'beta', value: risk.beta },
    { key: 'top1', value: risk.top1WeightPct },
    { key: 'effectiveN', value: risk.effectiveN },
  ]
}

export type RiskState = 'ready' | 'pending' | 'unavailable'

export function riskState(overview: PortfolioOverview | null): RiskState {
  if (overview === null) return 'unavailable'
  if (overview.risk !== null) return 'ready'
  return overview.riskPending ? 'pending' : 'unavailable'
}

/** Top five holdings by weight plus an aggregated "other" segment, normalised to 100.0%. */
export function allocationSegments(positions: readonly PortfolioPosition[]): AllocationSegment[] {
  const weighted = positions
    .filter((position) => !position.priceUnavailable)
    .map((position) => ({ position, weight: position.weightPct ?? 0 }))
    .filter((entry) => entry.weight > 0)
    .sort((left, right) => right.weight - left.weight)
  if (weighted.length === 0) return []
  const head = weighted.slice(0, 5)
  const tail = weighted.slice(5)
  const raw = head.map((entry) => entry.weight)
  const otherWeight = tail.reduce((sum, entry) => sum + entry.weight, 0)
  if (otherWeight > 0) raw.push(otherWeight)
  const total = raw.reduce((sum, value) => sum + value, 0)
  if (total <= 0) return []
  const exact = raw.map((value) => (value / total) * 100)
  const rounded = exact.map((value) => Math.round(value * 10) / 10)
  const drift = Math.round((100 - rounded.reduce((sum, value) => sum + value, 0)) * 10) / 10
  if (rounded.length > 0) rounded[0] = Math.round((rounded[0]! + drift) * 10) / 10
  const segments: AllocationSegment[] = head.map((entry, index) => ({
    key: entry.position.code,
    code: entry.position.code,
    name: entry.position.name,
    pct: rounded[index] ?? 0,
    color: ALLOCATION_COLORS[index % ALLOCATION_COLORS.length]!,
  }))
  if (otherWeight > 0) {
    segments.push({
      key: 'other',
      code: null,
      name: '',
      pct: rounded[rounded.length - 1] ?? 0,
      color: ALLOCATION_COLORS[head.length % ALLOCATION_COLORS.length]!,
    })
  }
  return segments
}

/** Watchlist rows from `/api/watch/state`, marking names that are also held. */
export function buildWatchRows(
  quotes: readonly { code: string; name: string; price: number | null; changePct: number | null; missing: boolean }[],
  positions: readonly PortfolioPosition[],
): WatchRow[] {
  const held = new Set(positions.map((position) => position.code))
  return quotes
    .filter((quote) => !quote.missing && quote.code !== '')
    .map((quote) => ({
      code: quote.code,
      name: quote.name || quote.code,
      price: quote.price,
      changePct: quote.changePct,
      held: held.has(quote.code),
    }))
}

/** The per-stock follow-up contains only this name, code, price and cost. */
export function askStockPrompt(position: Pick<PortfolioPosition, 'name' | 'code' | 'priceCny' | 'costPriceCny'>): string {
  const price = position.priceCny === null ? DASH : formatPrice(position.priceCny)
  const cost = position.costPriceCny === null ? DASH : formatPrice(position.costPriceCny)
  return `请分析我持有的 ${position.name}（${position.code}）：现价 ${price}，成本 ${cost}`
}

export function moneyText(value: number | null, hidden: boolean): string {
  if (value === null) return DASH
  return hidden ? MASK : formatMoney(value)
}

export function priceText(value: number | null, hidden: boolean): string {
  if (value === null) return DASH
  return hidden ? MASK : formatPrice(value)
}

export function pctText(value: number | null): string {
  return formatPct(value)
}

export function moveText(value: number | null): string {
  return formatMove(value)
}

export function quantityText(value: number | null, hidden = false): string {
  if (value === null) return DASH
  if (hidden) return MASK
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

export function ratioText(value: number | null): string {
  return value === null ? DASH : `${value.toFixed(1)}%`
}

export function sideOf(value: number | null): ChangeSide {
  if (value === null || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export function flagText(flag: PositionFlag): string {
  switch (flag) {
    case 't1':
      return 'T+1 不可卖'
    case 'limit_up':
      return '涨停'
    case 'limit_down':
      return '跌停'
    default:
      return '行情缺失'
  }
}

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

/** Browser storage access is optional and never throws. */
const STORAGE_PROP = ['local', 'Storage'].join('')

export function browserStorage(): StorageLike | null {
  try {
    if (typeof window === 'undefined') return null
    return (window as unknown as Record<string, StorageLike | undefined>)[STORAGE_PROP] ?? null
  } catch {
    return null
  }
}

export function readHidden(storage: StorageLike | null | undefined): boolean {
  try {
    return storage?.getItem(HIDDEN_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

export function writeHidden(value: boolean, storage: StorageLike | null | undefined): void {
  try {
    storage?.setItem(HIDDEN_STORAGE_KEY, value ? '1' : '0')
  } catch {
    // Storage can be disabled; the toggle still works for this page view.
  }
}

/* ---- per-stock intraday sparkline (hub /spark, T103) ---- */

export const HUB_SPARK_PATH = '/api/hub/spark'
const SPARK_CODE = /^\d{6}\.(SH|SZ)$/
export const SPARK_MAX_CODES = 30

export interface StockSpark {
  points: number[]
  prevClose: number | null
  changePct: number | null
}

/** Proxy URL for the given codes (deduped, A-share SH/SZ only, <= 30); null when nothing valid remains. */
export function sparkPath(codes: readonly string[]): string | null {
  const unique = [...new Set(codes.filter((code) => SPARK_CODE.test(code)))].slice(0, SPARK_MAX_CODES)
  return unique.length === 0 ? null : `${HUB_SPARK_PATH}?codes=${unique.join(',')}`
}

export function normalizeSparks(payload: unknown): Record<string, StockSpark> {
  const out: Record<string, StockSpark> = {}
  const sparks = (payload as { sparks?: unknown } | null)?.sparks
  if (typeof sparks !== 'object' || sparks === null) return out
  for (const [code, raw] of Object.entries(sparks as Record<string, unknown>)) {
    const row = raw as { points?: unknown; prev_close?: unknown; change_pct?: unknown } | null
    if (!row || !Array.isArray(row.points)) continue
    const points = row.points.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
    if (points.length < 2) continue
    out[code] = {
      points,
      prevClose: typeof row.prev_close === 'number' && Number.isFinite(row.prev_close) ? row.prev_close : null,
      changePct: typeof row.change_pct === 'number' && Number.isFinite(row.change_pct) ? row.change_pct : null,
    }
  }
  return out
}

export interface SparkGeometry {
  line: string
  area: string
  side: 'up' | 'down' | 'flat'
  /** y of the previous-close baseline, or null when it falls outside the series range. */
  baseY: number | null
}

/** Line + area paths in a width x height box; colour follows last vs previous close (A-share: up is red). */
export function sparkGeometry(spark: StockSpark, width = 72, height = 24): SparkGeometry | null {
  const { points, prevClose } = spark
  if (points.length < 2) return null
  const reference = prevClose ?? points[0]!
  const min = Math.min(...points, reference)
  const max = Math.max(...points, reference)
  const span = max - min || 1
  const pad = 2
  const y = (value: number): number => pad + (1 - (value - min) / span) * (height - pad * 2)
  const step = width / (points.length - 1)
  const coords = points.map((value, index) => `${(index * step).toFixed(1)},${y(value).toFixed(1)}`)
  const line = `M${coords.join('L')}`
  const area = `${line}L${width},${height}L0,${height}Z`
  const last = points[points.length - 1]!
  const side = last > reference ? 'up' : last < reference ? 'down' : 'flat'
  return { line, area, side, baseY: Number(y(reference).toFixed(1)) }
}
