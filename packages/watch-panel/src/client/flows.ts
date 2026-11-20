/**
 * Pure view model for the fund-flow block (T100, contract v1.3).
 *
 * Units are always 亿元 on screen; the API sends yuan. Direction is separate
 * from the value so the ▲/▼ glyph and the red/green token can swap with
 * `data-chives-updown` without changing the number.
 */
import { DASH, formatMove } from './market.ts'

export type FlowKind = 'sector_in' | 'sector_out' | 'stock_in' | 'stock_out'

export const FLOW_KINDS: readonly FlowKind[] = ['sector_in', 'sector_out', 'stock_in', 'stock_out']

export const FLOW_COLUMNS: readonly FlowKind[] = ['sector_in', 'sector_out', 'stock_in']

export const FLOW_LABEL: Record<FlowKind, string> = {
  sector_in: '\u884c\u4e1a\u51c0\u6d41\u5165',
  sector_out: '\u884c\u4e1a\u51c0\u6d41\u51fa',
  stock_in: '\u4e2a\u80a1\u51c0\u6d41\u5165',
  stock_out: '\u4e2a\u80a1\u51c0\u6d41\u51fa',
}

export const FLOW_DEFAULT_LIMIT = 8
export const FLOW_MIN_LIMIT = 5
export const FLOW_MAX_LIMIT = 20
export const FLOW_DEFINITION = '\u4e1c\u8d22\u4e3b\u529b\u53e3\u5f84\u00b7\u4ec5\u4f5c\u8f85\u52a9\u53c2\u8003'

export interface FlowRow {
  rank: number | null
  code: string
  name: string
  mainNetYuan: number | null
  mainNetPct: number | null
  changePct: number | null
  amountYuan: number | null
}

export interface FlowsPayload {
  ok: boolean
  error: string | null
  asOf: string | null
  kind: FlowKind
  rows: FlowRow[]
  definition: string
  source: string | null
  stale: boolean
  stateNote: string | null
  reason: string | null
}

export interface NorthboundPayload {
  ok: boolean
  available: boolean
  reason: string | null
  asOf: string | null
  netYuan: number | null
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

export function isFlowKind(value: unknown): value is FlowKind {
  return typeof value === 'string' && (FLOW_KINDS as readonly string[]).includes(value)
}

export function normalizeFlowRow(value: unknown): FlowRow {
  const row = pick(value)
  return {
    rank: int(row.rank),
    code: text(row.code),
    name: text(row.name),
    mainNetYuan: num(row.main_net_yuan),
    mainNetPct: num(row.main_net_pct),
    changePct: num(row.change_pct),
    amountYuan: num(row.amount_yuan),
  }
}

export function normalizeFlows(value: unknown, fallbackKind: FlowKind = 'sector_in'): FlowsPayload {
  const row = pick(value)
  const kind = isFlowKind(row.kind) ? row.kind : fallbackKind
  return {
    ok: row.ok !== false,
    error: isRecord(row.error) ? text(row.error.code) || 'market_error' : null,
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    kind,
    rows: list(row.rows).map(normalizeFlowRow).filter((entry) => entry.code !== ''),
    definition: text(row.definition) || FLOW_DEFINITION,
    source: typeof row.source === 'string' ? row.source : null,
    stale: bool(row.stale),
    stateNote: note(row.state_note),
    reason: note(row.reason),
  }
}

export function normalizeNorthbound(value: unknown): NorthboundPayload {
  const row = pick(value)
  return {
    ok: row.ok !== false,
    available: row.available === true,
    reason: note(row.reason),
    asOf: typeof row.as_of === 'string' ? row.as_of : null,
    netYuan: num(row.net_yuan),
  }
}

export interface FlowFilters {
  includeSt: boolean
  includeNew: boolean
  includeBj: boolean
}

export const DEFAULT_FLOW_FILTERS: FlowFilters = { includeSt: false, includeNew: false, includeBj: false }

/** Query string for the Host proxy; values are clamped and whitelisted. */
export function flowsQuery(
  kind: FlowKind,
  filters: FlowFilters = DEFAULT_FLOW_FILTERS,
  limit: number = FLOW_DEFAULT_LIMIT,
): string {
  const safeKind: FlowKind = isFlowKind(kind) ? kind : 'sector_in'
  const safeLimit = Number.isInteger(limit) ? Math.min(FLOW_MAX_LIMIT, Math.max(FLOW_MIN_LIMIT, limit)) : FLOW_DEFAULT_LIMIT
  const flag = (value: boolean): string => (value ? '1' : '0')
  return [
    `kind=${safeKind}`,
    `limit=${safeLimit}`,
    `include_st=${flag(filters.includeSt)}`,
    `include_new=${flag(filters.includeNew)}`,
    `include_bj=${flag(filters.includeBj)}`,
  ].join('&')
}

export function flowsPath(kind: FlowKind, filters: FlowFilters = DEFAULT_FLOW_FILTERS, limit: number = FLOW_DEFAULT_LIMIT): string {
  return `/api/market/flows?${flowsQuery(kind, filters, limit)}`
}

/** Three columns by default; the fourth (stock outflow) only after "更多". */
export function flowColumns(showStockOut: boolean): FlowKind[] {
  return showStockOut ? [...FLOW_COLUMNS, 'stock_out'] : [...FLOW_COLUMNS]
}

export type FlowSide = 'up' | 'down' | 'flat'

export function flowSide(yuan: number | null | undefined): FlowSide {
  if (typeof yuan !== 'number' || !Number.isFinite(yuan) || yuan === 0) return 'flat'
  return yuan > 0 ? 'up' : 'down'
}

export function flowGlyph(yuan: number | null | undefined): string {
  const side = flowSide(yuan)
  return side === 'up' ? '\u25b2' : side === 'down' ? '\u25bc' : '\u2014'
}

/** Absolute amount in 亿元 with two decimals; the glyph carries the direction. */
export function flowAmount(yuan: number | null | undefined): string {
  if (typeof yuan !== 'number' || !Number.isFinite(yuan)) return DASH
  return `${(Math.abs(yuan) / 1e8).toFixed(2)} \u4ebf\u5143`
}

export function flowChange(value: number | null | undefined): string {
  return formatMove(value)
}

export function northboundVisible(payload: NorthboundPayload | null | undefined): boolean {
  return Boolean(payload && payload.ok && payload.available && typeof payload.netYuan === 'number' && Number.isFinite(payload.netYuan))
}

/** Header text only when a usable northbound number exists; otherwise nothing. */
export function northboundText(payload: NorthboundPayload | null | undefined): string | null {
  if (!northboundVisible(payload) || !payload) return null
  return `\u5317\u5411\u51c0\u6d41\u5165 ${flowGlyph(payload.netYuan)} ${flowAmount(payload.netYuan)}`
}

export function flowsProblem(payload: FlowsPayload | null | undefined, failed: boolean): string | null {
  if (failed) return '\u8d44\u91d1\u6d41\u5411\u6570\u636e\u4e0d\u53ef\u7528'
  if (!payload) return null
  if (payload.stale) return payload.reason ?? '\u6570\u636e\u9648\u65e7'
  return payload.reason
}

/** Rows shown in one column, capped at the contract limit even if the hub sends more. */
export function flowRows(payload: FlowsPayload | null | undefined, limit = FLOW_DEFAULT_LIMIT): FlowRow[] {
  return (payload?.rows ?? []).slice(0, Math.max(0, limit))
}
