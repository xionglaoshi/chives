/** Small formatting/quote helpers for the "mine" page (kept local to chives-ui). */
export const DASH = '\u2014'
export const UP_SYMBOL = '\u25b2'
export const DOWN_SYMBOL = '\u25bc'

export type SessionLevel = 'open' | 'pre_open' | 'break' | 'after_hours' | 'non_trading_day' | 'unknown'

export interface QuotePayload {
  code?: string
  name?: string
  price?: number | null
  prev_close?: number | null
  change_pct?: number | null
  exch_time?: string | null
  missing?: boolean
}

export interface QuoteRow {
  code: string
  name: string
  price: number | null
  changePct: number | null
  missing: boolean
}

export interface StatePayload {
  quotes?: Record<string, QuotePayload>
  missing?: string[]
  session?: string
  updated_at?: string | null
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH
  const rounded = value.toFixed(digits)
  const parsed = Number(rounded)
  const fixed = parsed === 0 ? (0).toFixed(digits) : rounded
  return `${parsed > 0 ? '+' : ''}${fixed}%`
}

export function formatPrice(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH
  return value.toFixed(2)
}

export function formatMoney(yuan: number | null | undefined): string {
  if (typeof yuan !== 'number' || !Number.isFinite(yuan)) return DASH
  const absolute = Math.abs(yuan)
  if (absolute >= 1e8) return `${(yuan / 1e8).toFixed(2)} \u4ebf\u5143`
  if (absolute >= 1e4) return `${(yuan / 1e4).toFixed(2)} \u4e07\u5143`
  return `${Math.round(yuan)} \u5143`
}

export function formatMove(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return DASH
  const rounded = Number(value.toFixed(digits))
  if (rounded === 0) return formatPct(0, digits)
  return `${rounded > 0 ? UP_SYMBOL : DOWN_SYMBOL} ${formatPct(rounded, digits)}`
}

export function formatStamp(iso: string | null | undefined): string {
  if (typeof iso !== 'string') return DASH
  const match = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})/)
  return match ? `${match[2]}-${match[3]} ${match[4]}` : DASH
}

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

function quoteRow(code: string, quote: QuotePayload, missing: boolean): QuoteRow {
  return {
    code,
    name: text(quote.name),
    price: num(quote.price),
    changePct: num(quote.change_pct),
    missing,
  }
}

/** Quote rows in ascending code order, then explicit missing codes. */
export function quoteRows(state: StatePayload | null | undefined): QuoteRow[] {
  if (!state || typeof state.quotes !== 'object' || state.quotes === null) return []
  const quotes = state.quotes
  const codes = Object.keys(quotes).sort((left, right) => left.localeCompare(right))
  const rows = codes.map((code) => quoteRow(code, quotes[code] ?? {}, false))
  const seen = new Set(codes)
  for (const code of [...(Array.isArray(state.missing) ? state.missing : [])].sort((left, right) => left.localeCompare(right))) {
    if (typeof code !== 'string' || seen.has(code)) continue
    seen.add(code)
    rows.push(quoteRow(code, {}, true))
  }
  return rows
}
