/**
 * Host half of the chives-hub proxy (T100).
 *
 * Read routes are a fixed table under `/api/hub`; the only writes are five
 * restricted POST routes that change signal/plan/settings/discipline/card
 * state. Every request is validated against a strict whitelist, then rebuilt
 * from the validated values before it reaches the hub: browser headers
 * (cookies included), unknown query parameters, extra body fields and
 * oversized bodies never travel upstream. The hub only listens on loopback,
 * and its private portfolio routes are deliberately not proxied here.
 * `/spark` is public quote data, but it is still a fixed read-only route with
 * its own code whitelist.
 */

export const HUB_ENGINE_ENV = 'WATCH_PANEL_HUB_ENGINE'
export const HUB_DEFAULT_ENGINE = 'http://127.0.0.1:8867'
export const HUB_TIMEOUT_MS = 5_000
export const HUB_MAX_BYTES = 2 * 1024 * 1024
export const HUB_MAX_ACTION_BYTES = 4 * 1024
export const HUB_MAX_ID = 2 ** 31
export const PORTFOLIO_HISTORY_MIN_DAYS = 7
export const PORTFOLIO_HISTORY_MAX_DAYS = 365
export const PORTFOLIO_HISTORY_DEFAULT_DAYS = 90
export const HUB_SPARK_MAX_CODES = 30
export const HUB_SPARK_MAX_QUERY = 4096

const SPARK_CODE_RE = /^[0-9]{6}\.(?:SH|SZ)$/

export const SIGNAL_STATUSES = ['active', 'snoozed', 'done', 'all'] as const
export const SIGNAL_OBJECTS = ['stock', 'sector', 'market'] as const
export const PLAN_STATUSES = ['proposed', 'active', 'triggered', 'expired', 'cancelled', 'all'] as const
export const SIGNAL_ACTIONS = ['ack', 'ignore', 'snooze', 'unsnooze', 'done', 'reopen'] as const
export const PLAN_ACTIONS = ['confirm', 'cancel', 'extend'] as const
export const SNOOZE_UNTILS = ['30m', 'close', 'next_open'] as const
/** Contract v1.1 review layer. */
export const REVIEW_KINDS = ['evening', 'premarket'] as const
export const REVIEW_DEFAULT_LIMIT = 20
export const REVIEW_MIN_LIMIT = 1
export const REVIEW_MAX_LIMIT = 50
export const CARD_STATUSES = ['proposed', 'active', 'closed', 'all'] as const
export const CARD_ACTIONS = ['confirm', 'cancel', 'tighten_stop', 'set_state'] as const
export const CARD_STATES = ['abandon', 'exit'] as const
export const CANDIDATE_STATS_DEFAULT_DAYS = 20
export const CANDIDATE_STATS_MIN_DAYS = 5
export const CANDIDATE_STATS_MAX_DAYS = 60
export const DISCIPLINE_SLOTS = ['pre', 'mid', 'post'] as const
export const DISCIPLINE_LEVELS = ['calm', 'volatile', 'unfit'] as const
export const MOOD_NOTE_MAX_CHARS = 60
export const LOSS_STREAK_ACTIONS = ['add', 'reset'] as const
export const SETTING_KEYS = [
  'total_cap_strong_pct',
  'total_cap_neutral_pct',
  'total_cap_weak_pct',
  'single_stock_cap_pct',
  'theme_cap_pct',
  'per_trade_risk_pct',
  'pause_day_drawdown_pct',
  'pause_total_loss_pct',
  'pause_loss_streak',
  'emergency_index_drop_pct',
  'emergency_limit_down_count',
] as const
export const SETTING_ACTIONS = ['adopt', 'set', 'clear', 'dismiss'] as const

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]'])
const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' }

export type HubRouteKind =
  | 'signals'
  | 'signal'
  | 'plans'
  | 'signal-action'
  | 'plan-action'
  | 'portfolio-overview'
  | 'portfolio-history'
  | 'spark'
  | 'settings'
  | 'discipline'
  | 'reviews'
  | 'review'
  | 'cards'
  | 'card'
  | 'candidates-stats'
  | 'guidance'
  | 'setting-action'
  | 'discipline-action'
  | 'card-action'

export interface HubRoute {
  readonly path: string
  readonly kind: HubRouteKind
  readonly methods: readonly ('GET' | 'POST')[]
}

export interface HubProxyOptions {
  readonly timeoutMs?: number
  readonly maxBytes?: number
  readonly fetchImpl?: typeof fetch
}

/** Resolve the hub base and refuse anything that is not loopback. */
export function hubEngineBase(raw: string | undefined): string {
  const value = raw?.trim() || HUB_DEFAULT_ENGINE
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`${HUB_ENGINE_ENV} is not a valid URL`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${HUB_ENGINE_ENV} must use http or https`)
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) {
    throw new Error(`${HUB_ENGINE_ENV} must point at a loopback host, got ${parsed.hostname}`)
  }
  return value.replace(/\/+$/, '')
}

/**
 * Review layer switch (2026-11-16): the review / battle-card / settings / discipline / guidance entry points are
 * taken offline while that feature is redesigned. The route definitions and validators below are kept; with the
 * switch off they are simply not registered, so the Host answers 404 for them. Set to true to bring them back.
 */
export const HUB_REVIEW_LAYER_ENABLED = false

const CORE_ROUTES: readonly HubRoute[] = Object.freeze([
  { path: '/api/hub/signals', kind: 'signals', methods: ['GET'] },
  { path: '/api/hub/signal', kind: 'signal', methods: ['GET'] },
  { path: '/api/hub/plans', kind: 'plans', methods: ['GET'] },
  { path: '/api/hub/signal-action', kind: 'signal-action', methods: ['POST'] },
  { path: '/api/hub/plan-action', kind: 'plan-action', methods: ['POST'] },
  // Private reads: fixed paths only, never a generic `/portfolio/*` proxy.
  { path: '/api/hub/portfolio-overview', kind: 'portfolio-overview', methods: ['GET'] },
  { path: '/api/hub/portfolio-history', kind: 'portfolio-history', methods: ['GET'] },
  // Public quote data, fixed read-only route; `codes` is the only parameter.
  { path: '/api/hub/spark', kind: 'spark', methods: ['GET'] },
])

// hub v1.1 review layer: fixed reads and three restricted writes.
const REVIEW_ROUTES: readonly HubRoute[] = Object.freeze([
  { path: '/api/hub/settings', kind: 'settings', methods: ['GET'] },
  { path: '/api/hub/discipline', kind: 'discipline', methods: ['GET'] },
  { path: '/api/hub/reviews', kind: 'reviews', methods: ['GET'] },
  { path: '/api/hub/review', kind: 'review', methods: ['GET'] },
  { path: '/api/hub/cards', kind: 'cards', methods: ['GET'] },
  { path: '/api/hub/card', kind: 'card', methods: ['GET'] },
  { path: '/api/hub/candidates-stats', kind: 'candidates-stats', methods: ['GET'] },
  { path: '/api/hub/guidance', kind: 'guidance', methods: ['GET'] },
  { path: '/api/hub/setting-action', kind: 'setting-action', methods: ['POST'] },
  { path: '/api/hub/discipline-action', kind: 'discipline-action', methods: ['POST'] },
  { path: '/api/hub/card-action', kind: 'card-action', methods: ['POST'] },
])

const ALL_ROUTES: readonly HubRoute[] = Object.freeze([...CORE_ROUTES, ...REVIEW_ROUTES])

/** Routes the Host registers. `review` overrides the switch (tests exercise the kept review handlers with it). */
export function hubRouteTable(options: { review?: boolean } = {}): readonly HubRoute[] {
  return (options.review ?? HUB_REVIEW_LAYER_ENABLED) ? ALL_ROUTES : CORE_ROUTES
}

function jsonResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: JSON_HEADERS })
}

export function hubError(code: string, message: string, status = 400): Response {
  return jsonResponse(JSON.stringify({ ok: false, error: { code, message } }), status)
}

/** Exact body required by the contract for an unreachable hub. */
export function hubUnreachable(): Response {
  return jsonResponse(JSON.stringify({ ok: false, error: { code: 'hub_unreachable' } }), 502)
}

function canonicalId(raw: string | null): number | null {
  if (raw === null || !/^[1-9][0-9]{0,9}$/.test(raw)) return null
  const value = Number(raw)
  return Number.isInteger(value) && value <= HUB_MAX_ID ? value : null
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

/** Canonical, deduped spark codes, or null when the query must be refused. */
export function normalizeSparkCodes(raw: string | null): string[] | null {
  if (raw === null || raw === '' || raw.length > HUB_SPARK_MAX_QUERY) return null
  const codes: string[] = []
  const seen = new Set<string>()
  for (const token of raw.split(',')) {
    if (token.length !== 9 || !SPARK_CODE_RE.test(token)) return null
    if (!seen.has(token)) {
      seen.add(token)
      codes.push(token)
    }
  }
  if (codes.length === 0 || codes.length > HUB_SPARK_MAX_CODES) return null
  return codes
}

/** Canonical upstream target for a GET route, or null for 400. */
export function hubUpstreamTarget(route: HubRoute, url: URL): string | null {
  const params = url.searchParams
  if (route.kind === 'signals') {
    const allowed = new Set(['status', 'decide', 'object', 'limit', 'since_id'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const status = params.get('status') ?? 'active'
    if (!(SIGNAL_STATUSES as readonly string[]).includes(status)) return null
    const decide = params.get('decide')
    if (decide !== null && decide !== '0' && decide !== '1') return null
    const object = params.get('object')
    if (object !== null && !(SIGNAL_OBJECTS as readonly string[]).includes(object)) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null ? 50 : /^(?:[1-9][0-9]?|100)$/.test(rawLimit) ? Number(rawLimit) : Number.NaN
    if (!Number.isInteger(limit) || limit < 1 || limit > 100) return null
    const sinceRaw = params.get('since_id')
    const since = sinceRaw === null ? null : Number(sinceRaw)
    if (sinceRaw !== null && (since === null || !/^(?:0|[1-9][0-9]{0,9})$/.test(sinceRaw) || !Number.isInteger(since) || since < 0 || since > HUB_MAX_ID)) return null
    const query = new URLSearchParams()
    query.set('status', status)
    if (decide !== null) query.set('decide', decide)
    if (object !== null) query.set('object', object)
    query.set('limit', String(limit))
    if (since !== null) query.set('since_id', String(since))
    return `${'/signals'}?${query.toString()}`
  }
  if (route.kind === 'signal') {
    for (const key of params.keys()) if (key !== 'id') return null
    if (params.getAll('id').length !== 1) return null
    const id = canonicalId(params.get('id'))
    return id === null ? null : `/signals/${id}`
  }
  if (route.kind === 'plans') {
    for (const key of params.keys()) if (key !== 'status') return null
    if (params.getAll('status').length > 1) return null
    const status = params.get('status')
    if (status === null) return '/plans'
    if (!(PLAN_STATUSES as readonly string[]).includes(status)) return null
    return `/plans?status=${status}`
  }
  if (route.kind === 'portfolio-overview') {
    return params.size === 0 ? '/portfolio/overview' : null
  }
  if (route.kind === 'portfolio-history') {
    for (const key of params.keys()) if (key !== 'days') return null
    if (params.getAll('days').length > 1) return null
    const raw = params.get('days')
    if (raw === null) return `/portfolio/history?days=${PORTFOLIO_HISTORY_DEFAULT_DAYS}`
    if (!/^\d+$/.test(raw)) return null
    const days = Number(raw)
    if (!Number.isInteger(days) || String(days) !== raw) return null
    if (days < PORTFOLIO_HISTORY_MIN_DAYS || days > PORTFOLIO_HISTORY_MAX_DAYS) return null
    return `/portfolio/history?days=${days}`
  }
  if (route.kind === 'spark') {
    for (const key of params.keys()) if (key !== 'codes') return null
    if (params.getAll('codes').length !== 1) return null
    const codes = normalizeSparkCodes(params.get('codes'))
    if (codes === null) return null
    const query = new URLSearchParams()
    query.set('codes', codes.join(','))
    return `/spark?${query.toString()}`
  }
  if (route.kind === 'settings' || route.kind === 'discipline') {
    return params.size === 0 ? `/${route.kind}` : null
  }
  if (route.kind === 'reviews') {
    const allowed = new Set(['limit', 'kind'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const rawLimit = params.get('limit')
    const limit = rawLimit === null ? REVIEW_DEFAULT_LIMIT : canonicalInt(rawLimit, REVIEW_MIN_LIMIT, REVIEW_MAX_LIMIT)
    if (limit === null) return null
    const kind = params.get('kind')
    if (kind !== null && !(REVIEW_KINDS as readonly string[]).includes(kind)) return null
    const query = new URLSearchParams({ limit: String(limit) })
    if (kind !== null) query.set('kind', kind)
    return `/reviews?${query.toString()}`
  }
  if (route.kind === 'review') {
    for (const key of params.keys()) if (key !== 'date' && key !== 'kind') return null
    if (params.getAll('date').length !== 1 || params.getAll('kind').length !== 1) return null
    const date = params.get('date')
    const kind = params.get('kind')
    if (date === null || !isCalendarDate(date)) return null
    if (kind === null || !(REVIEW_KINDS as readonly string[]).includes(kind)) return null
    return `/reviews/${date}?kind=${kind}`
  }
  if (route.kind === 'cards') {
    const allowed = new Set(['status', 'date'])
    for (const key of params.keys()) if (!allowed.has(key)) return null
    for (const key of allowed) if (params.getAll(key).length > 1) return null
    const status = params.get('status')
    if (status !== null && !(CARD_STATUSES as readonly string[]).includes(status)) return null
    const date = params.get('date')
    if (date !== null && !isCalendarDate(date)) return null
    const query = new URLSearchParams()
    if (status !== null) query.set('status', status)
    if (date !== null) query.set('date', date)
    const encoded = query.toString()
    return encoded ? `/cards?${encoded}` : '/cards'
  }
  if (route.kind === 'card') {
    for (const key of params.keys()) if (key !== 'id') return null
    if (params.getAll('id').length !== 1) return null
    const id = canonicalId(params.get('id'))
    return id === null ? null : `/cards/${id}`
  }
  if (route.kind === 'candidates-stats') {
    for (const key of params.keys()) if (key !== 'days') return null
    if (params.getAll('days').length > 1) return null
    const raw = params.get('days')
    const days = raw === null
      ? CANDIDATE_STATS_DEFAULT_DAYS
      : canonicalInt(raw, CANDIDATE_STATS_MIN_DAYS, CANDIDATE_STATS_MAX_DAYS)
    if (days === null) return null
    return `/candidates/stats?days=${days}`
  }
  if (route.kind === 'guidance') {
    for (const key of params.keys()) if (key !== 'date') return null
    if (params.getAll('date').length > 1) return null
    const date = params.get('date')
    if (date === null) return '/guidance'
    if (!isCalendarDate(date)) return null
    return `/guidance?date=${date}`
  }
  return null
}

function isPrivatePortfolioRoute(route: HubRoute): boolean {
  return route.kind === 'portfolio-overview' || route.kind === 'portfolio-history'
}

const PRIVATE_READ_KINDS = new Set<HubRouteKind>([
  'settings',
  'discipline',
  'reviews',
  'review',
  'cards',
  'card',
  'candidates-stats',
  'guidance',
])

function needsNoStore(route: HubRoute): boolean {
  return isPrivatePortfolioRoute(route) || route.kind === 'spark' || PRIVATE_READ_KINDS.has(route.kind)
}

function isJsonContentType(value: string | null): boolean {
  if (value === null) return false
  return /^application\/json(?:;\s*charset=utf-8)?$/i.test(value.trim())
}

interface ReadResult {
  text: string | null
  tooLarge: boolean
}

async function readBody(request: Request, limit: number): Promise<ReadResult> {
  const length = Number(request.headers.get('content-length'))
  if (Number.isFinite(length) && length > limit) return { text: null, tooLarge: true }
  const body = await request.text()
  if (new TextEncoder().encode(body).byteLength > limit) return { text: null, tooLarge: true }
  return { text: body, tooLarge: false }
}

function isIso(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 64 && Number.isFinite(Date.parse(value))
}

function isActionId(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= HUB_MAX_ID
}

function exactKeys(row: Record<string, unknown>, allowed: readonly string[]): boolean {
  const keys = Object.keys(row)
  return keys.length === allowed.length && keys.every((key) => allowed.includes(key))
}

export interface ValidatedAction {
  id: number
  body: Record<string, unknown>
}

/** Strict signal-action body: exact fields, whitelisted action and until. */
export function validateSignalAction(value: unknown): ValidatedAction | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const action = row.action
  if (!(SIGNAL_ACTIONS as readonly string[]).includes(typeof action === 'string' ? action : '')) return null
  if (!isActionId(row.id)) return null
  if (action === 'snooze') {
    if (!exactKeys(row, ['id', 'action', 'until'])) return null
    const until = row.until
    const preset = typeof until === 'string' && (SNOOZE_UNTILS as readonly string[]).includes(until)
    if (!preset && !isIso(until)) return null
    return { id: row.id, body: { action, until } }
  }
  if (!exactKeys(row, ['id', 'action'])) return null
  return { id: row.id, body: { action } }
}

/** Strict plan-action body: `expires_at` exists only for `extend`. */
export function validatePlanAction(value: unknown): ValidatedAction | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const action = row.action
  if (!(PLAN_ACTIONS as readonly string[]).includes(typeof action === 'string' ? action : '')) return null
  if (!isActionId(row.id)) return null
  if (action === 'extend') {
    if (!exactKeys(row, ['id', 'action', 'expires_at']) || !isIso(row.expires_at)) return null
    return { id: row.id, body: { action, expires_at: row.expires_at } }
  }
  if (!exactKeys(row, ['id', 'action'])) return null
  return { id: row.id, body: { action } }
}

export interface ValidatedWrite {
  readonly target: string
  readonly body: Record<string, unknown>
}

/** Strict settings write: `key` goes into the upstream path, never the body. */
export function validateSettingAction(value: unknown): ValidatedWrite | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const key = row.key
  if (typeof key !== 'string' || !(SETTING_KEYS as readonly string[]).includes(key)) return null
  const action = row.action
  if (!(SETTING_ACTIONS as readonly string[]).includes(typeof action === 'string' ? action : '')) return null
  if (action === 'set') {
    if (!exactKeys(row, ['key', 'action', 'value'])) return null
    const amount = row.value
    if (typeof amount !== 'number' || !Number.isFinite(amount)) return null
    return { target: `/settings/${key}/action`, body: { action, value: amount } }
  }
  if (!exactKeys(row, ['key', 'action'])) return null
  return { target: `/settings/${key}/action`, body: { action } }
}

/** Strict discipline write: loss-streak vs mood are disjoint shapes. */
export function validateDisciplineAction(value: unknown): ValidatedWrite | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const kind = row.kind
  if (kind === 'loss-streak') {
    if (!exactKeys(row, ['kind', 'action'])) return null
    const action = row.action
    if (!(LOSS_STREAK_ACTIONS as readonly string[]).includes(typeof action === 'string' ? action : '')) return null
    return { target: '/discipline/loss-streak', body: { action } }
  }
  if (kind !== 'mood') return null
  const slot = row.slot
  const level = row.level
  if (!(DISCIPLINE_SLOTS as readonly string[]).includes(typeof slot === 'string' ? slot : '')) return null
  if (!(DISCIPLINE_LEVELS as readonly string[]).includes(typeof level === 'string' ? level : '')) return null
  const hasNote = Object.prototype.hasOwnProperty.call(row, 'note')
  if (!exactKeys(row, hasNote ? ['kind', 'slot', 'level', 'note'] : ['kind', 'slot', 'level'])) return null
  const body: Record<string, unknown> = { slot, level }
  if (hasNote) {
    const note = row.note
    if (typeof note !== 'string' || Array.from(note).length > MOOD_NOTE_MAX_CHARS) return null
    body.note = note
  }
  return { target: '/discipline/mood', body }
}

/** Strict card write: `id` goes into the upstream path; stop/state are exclusive. */
export function validateCardAction(value: unknown): ValidatedWrite | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const id = row.id
  if (!isActionId(id)) return null
  const action = row.action
  if (!(CARD_ACTIONS as readonly string[]).includes(typeof action === 'string' ? action : '')) return null
  if (action === 'tighten_stop') {
    if (!exactKeys(row, ['id', 'action', 'stop'])) return null
    const stop = row.stop
    if (typeof stop !== 'number' || !Number.isFinite(stop) || stop <= 0) return null
    return { target: `/cards/${id}/action`, body: { action, stop } }
  }
  if (action === 'set_state') {
    if (!exactKeys(row, ['id', 'action', 'state'])) return null
    const state = row.state
    if (!(CARD_STATES as readonly string[]).includes(typeof state === 'string' ? state : '')) return null
    return { target: `/cards/${id}/action`, body: { action, state } }
  }
  if (!exactKeys(row, ['id', 'action'])) return null
  return { target: `/cards/${id}/action`, body: { action } }
}

/** Map a write route to its canonical upstream target and body, or null for 400. */
export function validateHubWrite(kind: HubRouteKind, value: unknown): ValidatedWrite | null {
  if (kind === 'signal-action') {
    const valid = validateSignalAction(value)
    return valid === null ? null : { target: `/signals/${valid.id}/action`, body: valid.body }
  }
  if (kind === 'plan-action') {
    const valid = validatePlanAction(value)
    return valid === null ? null : { target: `/plans/${valid.id}/action`, body: valid.body }
  }
  if (kind === 'setting-action') return validateSettingAction(value)
  if (kind === 'discipline-action') return validateDisciplineAction(value)
  if (kind === 'card-action') return validateCardAction(value)
  return null
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

/**
 * Proxy one hub request. `POST` requires `x-chives-action: 1`, a JSON content
 * type and a body within 4 KB; GET routes never accept a body. The two private
 * portfolio reads and the public spark read always answer with `Cache-Control:
 * no-store`.
 */
export async function handleHubRequest(
  route: HubRoute,
  base: string,
  request: Request,
  options: HubProxyOptions = {},
): Promise<Response> {
  const response = await handleHubRequestInner(route, base, request, options)
  if (!needsNoStore(route)) return response
  const headers = new Headers(response.headers)
  headers.set('cache-control', 'no-store')
  return new Response(await response.text(), { status: response.status, headers })
}

async function handleHubRequestInner(
  route: HubRoute,
  base: string,
  request: Request,
  options: HubProxyOptions = {},
): Promise<Response> {
  const timeoutMs = options.timeoutMs ?? HUB_TIMEOUT_MS
  const maxBytes = options.maxBytes ?? HUB_MAX_BYTES
  const doFetch = options.fetchImpl ?? fetch
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return hubError('bad_request', 'invalid request url')
  }

  let target: string | null = null
  let method: 'GET' | 'POST' = 'GET'
  let payload: string | null = null
  if (route.methods.includes('POST')) {
    method = 'POST'
    if (request.method !== 'POST') return hubError('bad_request', 'only POST is allowed')
    if (url.searchParams.size !== 0) return hubError('bad_request', 'query not allowed')
    if (request.headers.get('x-chives-action') !== '1') return hubError('bad_request', 'missing csrf header')
    if (!isJsonContentType(request.headers.get('content-type'))) return hubError('bad_request', 'content type must be application/json')
    let read: ReadResult
    try {
      read = await readBody(request, HUB_MAX_ACTION_BYTES)
    } catch {
      return hubError('bad_request', 'invalid request body')
    }
    if (read.tooLarge) return hubError('payload_too_large', `body exceeds ${HUB_MAX_ACTION_BYTES} bytes`)
    let parsed: unknown
    try {
      parsed = JSON.parse(read.text ?? '')
    } catch {
      return hubError('bad_request', 'body must be JSON')
    }
    const validated = validateHubWrite(route.kind, parsed)
    if (validated === null) return hubError('bad_request', 'body failed validation')
    target = validated.target
    payload = JSON.stringify(validated.body)
  } else {
    if (request.method !== 'GET') return hubError('bad_request', 'only GET is allowed')
    target = hubUpstreamTarget(route, url)
    if (target === null) return hubError('bad_request', 'query not allowed')
  }

  const headers: Record<string, string> = { accept: 'application/json' }
  if (payload !== null) headers['content-type'] = 'application/json'
  let upstream: Response
  try {
    upstream = await doFetch(`${base}${target}`, {
      method,
      headers,
      body: payload ?? undefined,
      redirect: 'manual',
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    return hubUnreachable()
  }
  let body: string | null
  try {
    body = await readCapped(upstream, maxBytes)
  } catch {
    return hubUnreachable()
  }
  if (body === null) return hubError('response_too_large', `response exceeds ${maxBytes} bytes`, 502)
  if (upstream.status >= 300 && upstream.status < 400) return hubError('hub_redirect', 'upstream redirect was not followed', 502)
  if (upstream.status >= 500) return hubError('hub_error', `upstream status ${upstream.status}`, 502)
  return jsonResponse(body, upstream.status)
}

export interface HubRouteHandler {
  readonly path: string
  readonly methods: readonly ('GET' | 'POST')[]
  readonly requestBody: 'buffered'
  readonly handle: (request: Request) => Promise<Response>
}

/** Exact-route handlers for the dsh connection registry. */
export function hubRouteHandlers(base: string, options: HubProxyOptions = {}): HubRouteHandler[] {
  return hubRouteTable().map((route) => ({
    path: route.path,
    methods: route.methods,
    requestBody: 'buffered',
    handle: (request: Request): Promise<Response> => handleHubRequest(route, base, request, options),
  }))
}
