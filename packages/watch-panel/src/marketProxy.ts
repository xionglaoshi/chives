/**
 * Host half of the market-watch proxy. Kept free of the dsh connection API so
 * the routing, whitelist, loopback and size/timeout rules can be unit-tested
 * directly against a fake upstream.
 *
 * dsh's exact Fetch route registry matches on the pathname only, so the proxy
 * exposes a fixed set of eighteen paths. Sector codes are carried in a `code`
 * query parameter, validated against `^BK[0-9]{4}$`, and only the validated
 * value is interpolated into the upstream path; the browser query string is
 * never forwarded verbatim.
 */

export const MARKET_ENGINE_ENV = 'WATCH_PANEL_MARKET_ENGINE'
export const MARKET_DEFAULT_ENGINE = 'http://127.0.0.1:8866'
export const MARKET_TIMEOUT_MS = 5_000
export const MARKET_MAX_BYTES = 2 * 1024 * 1024

/** Contract v1.1 sector ids: Eastmoney board codes such as BK0433. */
export const SECTOR_CODE = /^BK[0-9]{4}$/
export const SECTOR_LEVELS = ['sw1', 'industry'] as const
export const MOVER_KINDS = ['gainers', 'losers', 'active'] as const
export const MOVER_DEFAULT_LIMIT = 10
export const MOVER_MIN_LIMIT = 5
export const MOVER_MAX_LIMIT = 20
export const FLOW_KINDS = ['sector_in', 'sector_out', 'stock_in', 'stock_out'] as const
export const FLOW_DEFAULT_LIMIT = 10
export const FLOW_MIN_LIMIT = 5
export const FLOW_MAX_LIMIT = 20
export const POOL_KINDS = ['zt', 'zb', 'dt'] as const
export const POOL_DEFAULT_KIND = 'zt'
export const POOL_DEFAULT_LIMIT = 200
export const POOL_MIN_LIMIT = 1
export const POOL_MAX_LIMIT = 200
export const POOL_HISTORY_DEFAULT_DAYS = 20
export const POOL_HISTORY_MIN_DAYS = 10
export const POOL_HISTORY_MAX_DAYS = 30
export const THEME_KINDS = ['concept'] as const
export const THEME_SORTS = ['change', 'amount'] as const
export const THEME_DEFAULT_LIMIT = 20
export const THEME_MIN_LIMIT = 5
export const THEME_MAX_LIMIT = 30

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]'])
const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' }

export type MarketKind =
  | 'fixed'
  | 'sectors'
  | 'alerts'
  | 'sector'
  | 'sector-members'
  | 'movers'
  | 'summary'
  | 'flows'
  | 'flows-northbound'
  | 'pool'
  | 'pool-ladder'
  | 'pool-history'
  | 'pool-yesterday'
  | 'pool-by-industry'
  | 'breadth-series'
  | 'themes'

export interface MarketRoute {
  /** Browser-facing exact pathname. */
  readonly path: string
  /** Upstream contract path; `{code}` is replaced with a validated sector id. */
  readonly upstream: string
  readonly kind: MarketKind
}

export interface MarketProxyOptions {
  readonly timeoutMs?: number
  readonly maxBytes?: number
  readonly fetchImpl?: typeof fetch
}

/** Resolve the market engine base and refuse anything that is not loopback. */
export function marketEngineBase(raw: string | undefined): string {
  const value = raw?.trim() || MARKET_DEFAULT_ENGINE
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`${MARKET_ENGINE_ENV} is not a valid URL`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${MARKET_ENGINE_ENV} must use http or https`)
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) {
    throw new Error(`${MARKET_ENGINE_ENV} must point at a loopback host, got ${parsed.hostname}`)
  }
  return value.replace(/\/+$/, '')
}

const ROUTES: readonly MarketRoute[] = Object.freeze([
  { path: '/api/market/health', upstream: '/health', kind: 'fixed' },
  { path: '/api/market/overview', upstream: '/overview', kind: 'fixed' },
  { path: '/api/market/sectors', upstream: '/sectors', kind: 'sectors' },
  { path: '/api/market/alerts', upstream: '/alerts', kind: 'alerts' },
  { path: '/api/market/rules', upstream: '/rules', kind: 'fixed' },
  { path: '/api/market/sector', upstream: '/sectors/{code}', kind: 'sector' },
  { path: '/api/market/sector-members', upstream: '/sectors/{code}/members', kind: 'sector-members' },
  { path: '/api/market/movers', upstream: '/movers', kind: 'movers' },
  { path: '/api/market/summary', upstream: '/summary', kind: 'summary' },
  { path: '/api/market/flows', upstream: '/flows', kind: 'flows' },
  { path: '/api/market/flows-northbound', upstream: '/flows/northbound', kind: 'flows-northbound' },
  // Contract v1.4 review data layer; every path is fixed and read-only.
  { path: '/api/market/pool', upstream: '/pool', kind: 'pool' },
  { path: '/api/market/pool-ladder', upstream: '/pool/ladder', kind: 'pool-ladder' },
  { path: '/api/market/pool-history', upstream: '/pool/history', kind: 'pool-history' },
  { path: '/api/market/pool-yesterday', upstream: '/pool/yesterday', kind: 'pool-yesterday' },
  { path: '/api/market/pool-by-industry', upstream: '/pool/by-industry', kind: 'pool-by-industry' },
  { path: '/api/market/breadth-series', upstream: '/breadth/series', kind: 'breadth-series' },
  { path: '/api/market/themes', upstream: '/themes', kind: 'themes' },
])

/** Every route the proxy owns: eighteen fixed pathnames, no generated table. */
export function marketRouteTable(): readonly MarketRoute[] {
  return ROUTES
}

/** True only for a syntactically valid Eastmoney board id. */
export function isSectorCode(code: string): boolean {
  return code.length === 6 && SECTOR_CODE.test(code)
}

/** Strict `YYYY-MM-DD` that also exists on the real calendar. */
export function isCalendarDate(value: string): boolean {
  const match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value)
  if (match === null) return false
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1) return false
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0
  const monthDays = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day <= monthDays[month - 1]!
}

/** Canonical decimal integer within [min, max]; rejects leading zeroes. */
function canonicalInt(raw: string, min: number, max: number): number | null {
  if (!/^[0-9]+$/.test(raw)) return null
  const value = Number(raw)
  if (!Number.isInteger(value) || String(value) !== raw || value < min || value > max) return null
  return value
}

/**
 * `code` must appear exactly once, as the only parameter, and its decoded
 * value must match the sector-id grammar. Null means 400.
 */
export function sectorCode(url: URL): string | null {
  const params = url.searchParams
  for (const key of params.keys()) if (key !== 'code') return null
  if (params.getAll('code').length !== 1) return null
  const code = params.get('code')
  return code !== null && isSectorCode(code) ? code : null
}

function jsonResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: JSON_HEADERS })
}

function errorResponse(code: string, message: string, status = 400): Response {
  return jsonResponse(JSON.stringify({ ok: false, error: { code, message } }), status)
}

/**
 * Canonical upstream target (path plus whitelisted query), or null when the
 * browser query is not allowed. Returns a target built from validated values.
 */
export function upstreamTarget(route: MarketRoute, url: URL): string | null {
  const params = url.searchParams
  if (route.kind === 'fixed') return params.size === 0 ? route.upstream : null
  if (route.kind === 'sector' || route.kind === 'sector-members') {
    const code = sectorCode(url)
    return code === null ? null : route.upstream.replace('{code}', code)
  }
  if (route.kind === 'summary') return params.size === 0 ? route.upstream : null
  if (route.kind === 'movers') {
    const allowed = new Set(['kind', 'limit', 'include_st', 'include_new', 'include_bj'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const kind = params.get('kind') ?? 'gainers'
    if (!(MOVER_KINDS as readonly string[]).includes(kind)) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null
      ? MOVER_DEFAULT_LIMIT
      : /^(?:[5-9]|1[0-9]|20)$/.test(rawLimit) ? Number(rawLimit) : Number.NaN
    if (!Number.isInteger(limit) || limit < MOVER_MIN_LIMIT || limit > MOVER_MAX_LIMIT) return null
    const flag = (name: string): string | null => {
      const raw = params.get(name)
      if (raw === null) return '0'
      return raw === '0' || raw === '1' ? raw : null
    }
    const st = flag('include_st')
    const fresh = flag('include_new')
    const bj = flag('include_bj')
    if (st === null || fresh === null || bj === null) return null
    return `${route.upstream}?kind=${kind}&limit=${limit}&include_st=${st}&include_new=${fresh}&include_bj=${bj}`
  }
  if (route.kind === 'flows-northbound') return params.size === 0 ? route.upstream : null
  if (route.kind === 'flows') {
    const allowed = new Set(['kind', 'limit', 'include_st', 'include_new', 'include_bj'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const kind = params.get('kind') ?? 'sector_in'
    if (!(FLOW_KINDS as readonly string[]).includes(kind)) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null
      ? FLOW_DEFAULT_LIMIT
      : /^(?:[5-9]|1[0-9]|20)$/.test(rawLimit) ? Number(rawLimit) : Number.NaN
    if (!Number.isInteger(limit) || limit < FLOW_MIN_LIMIT || limit > FLOW_MAX_LIMIT) return null
    const flag = (name: string): string | null => {
      const raw = params.get(name)
      if (raw === null) return '0'
      return raw === '0' || raw === '1' ? raw : null
    }
    const st = flag('include_st')
    const fresh = flag('include_new')
    const bj = flag('include_bj')
    if (st === null || fresh === null || bj === null) return null
    return `${route.upstream}?kind=${kind}&limit=${limit}&include_st=${st}&include_new=${fresh}&include_bj=${bj}`
  }
  if (route.kind === 'pool') {
    const allowed = new Set(['kind', 'date', 'limit'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const kind = params.get('kind') ?? POOL_DEFAULT_KIND
    if (!(POOL_KINDS as readonly string[]).includes(kind)) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null ? POOL_DEFAULT_LIMIT : canonicalInt(rawLimit, POOL_MIN_LIMIT, POOL_MAX_LIMIT)
    if (limit === null) return null
    const date = params.get('date')
    if (date !== null && !isCalendarDate(date)) return null
    const query = new URLSearchParams({ kind, limit: String(limit) })
    if (date !== null) query.set('date', date)
    return `${route.upstream}?${query.toString()}`
  }
  if (route.kind === 'pool-ladder' || route.kind === 'pool-by-industry' || route.kind === 'breadth-series') {
    for (const key of params.keys()) if (key !== 'date') return null
    if (params.getAll('date').length > 1) return null
    const date = params.get('date')
    if (date === null) return route.upstream
    if (!isCalendarDate(date)) return null
    return `${route.upstream}?date=${date}`
  }
  if (route.kind === 'pool-history') {
    for (const key of params.keys()) if (key !== 'days') return null
    if (params.getAll('days').length > 1) return null
    const raw = params.get('days')
    const days = raw === null ? POOL_HISTORY_DEFAULT_DAYS : canonicalInt(raw, POOL_HISTORY_MIN_DAYS, POOL_HISTORY_MAX_DAYS)
    if (days === null) return null
    return `${route.upstream}?days=${days}`
  }
  if (route.kind === 'pool-yesterday') return params.size === 0 ? route.upstream : null
  if (route.kind === 'themes') {
    const allowed = new Set(['kind', 'limit', 'sort'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const kind = params.get('kind') ?? 'concept'
    if (!(THEME_KINDS as readonly string[]).includes(kind)) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null ? THEME_DEFAULT_LIMIT : canonicalInt(rawLimit, THEME_MIN_LIMIT, THEME_MAX_LIMIT)
    if (limit === null) return null
    const sort = params.get('sort') ?? 'change'
    if (!(THEME_SORTS as readonly string[]).includes(sort)) return null
    return `${route.upstream}?kind=${kind}&limit=${limit}&sort=${sort}`
  }
  if (route.kind === 'sectors') {
    for (const key of params.keys()) if (key !== 'level') return null
    if (params.getAll('level').length !== 1) return null
    const level = params.get('level')
    if (level === null || !(SECTOR_LEVELS as readonly string[]).includes(level)) return null
    return `${route.upstream}?level=${level}`
  }
  for (const key of params.keys()) {
    if (key !== 'since_id' && key !== 'limit') return null
  }
  const since = params.get('since_id')
  const limit = params.get('limit')
  if (params.getAll('since_id').length > 1 || params.getAll('limit').length > 1) return null
  if (since !== null && (!/^[0-9]+$/.test(since) || since.length > 15)) return null
  if (limit !== null) {
    if (!/^[0-9]+$/.test(limit)) return null
    const value = Number(limit)
    if (!Number.isInteger(value) || value < 1 || value > 200) return null
  }
  const forwarded = new URLSearchParams()
  if (since !== null) forwarded.set('since_id', String(Number(since)))
  if (limit !== null) forwarded.set('limit', String(Number(limit)))
  const query = forwarded.toString()
  return query ? `${route.upstream}?${query}` : route.upstream
}

async function readCapped(upstream: Response, maxBytes: number): Promise<string | null> {
  const length = Number(upstream.headers.get('content-length'))
  if (Number.isFinite(length) && length > maxBytes) {
    await upstream.body?.cancel()
    return null
  }
  if (!upstream.body) return ''
  const reader = upstream.body.getReader()
  const chunks: Uint8Array[] = []
  let total = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    if (!value) continue
    total += value.byteLength
    if (total > maxBytes) {
      await reader.cancel()
      return null
    }
    chunks.push(value)
  }
  const merged = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    merged.set(chunk, offset)
    offset += chunk.byteLength
  }
  return new TextDecoder('utf-8').decode(merged)
}

/** Proxy one whitelisted request; browser headers and cookies are never forwarded. */
export async function handleMarketRequest(
  route: MarketRoute,
  base: string,
  request: Request,
  options: MarketProxyOptions = {},
): Promise<Response> {
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return errorResponse('bad_request', 'invalid request url')
  }
  const target = upstreamTarget(route, url)
  if (target === null) return errorResponse('bad_request', 'query not allowed')
  if (request.method !== 'GET') return errorResponse('bad_request', 'only GET is allowed')
  const timeoutMs = options.timeoutMs ?? MARKET_TIMEOUT_MS
  const maxBytes = options.maxBytes ?? MARKET_MAX_BYTES
  const doFetch = options.fetchImpl ?? fetch
  let upstream: Response
  try {
    upstream = await doFetch(`${base}${target}`, {
      method: 'GET',
      headers: { accept: 'application/json' },
      redirect: 'manual',
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    return errorResponse('engine_unreachable', 'engine_unreachable', 502)
  }
  let body: string | null
  try {
    body = await readCapped(upstream, maxBytes)
  } catch {
    return errorResponse('engine_unreachable', 'engine_unreachable', 502)
  }
  if (body === null) return errorResponse('response_too_large', `response exceeds ${maxBytes} bytes`, 502)
  if (upstream.status >= 300 && upstream.status < 400) return errorResponse('engine_redirect', 'upstream redirect was not followed', 502)
  if (upstream.status >= 500) return errorResponse('engine_error', `upstream status ${upstream.status}`, 502)
  return jsonResponse(body, upstream.status)
}

interface MarketRouteHandler {
  readonly path: string
  handle(request: Request): Promise<Response>
}

/** Exact-route handlers for the dsh connection registry. */
export function marketRouteHandlers(base: string, options: MarketProxyOptions = {}): MarketRouteHandler[] {
  return marketRouteTable().map((route) => ({
    path: route.path,
    handle: (request: Request): Promise<Response> => handleMarketRequest(route, base, request, options),
  }))
}
