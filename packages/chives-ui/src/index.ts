/**
 * Host half: one authenticated, read-only GET route that proxies the local
 * chives-radar engine's `/health`. The browser never learns the engine address and
 * the route accepts no query parameters; the address comes from CHIVES_ENGINE
 * (or WATCH_PANEL_ENGINE, so both panels can share one deployment) and must be
 * a loopback host.
 */
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-connection'

export const name = 'chives-ui'
export const inject = ['connection']

const DEFAULT_ENGINE = 'http://127.0.0.1:8865'
const ENGINE_ENV = 'CHIVES_ENGINE'
const FALLBACK_ENGINE_ENV = 'WATCH_PANEL_ENGINE'
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]'])
const ROUTE = '/api/chives/health'
const TIMEOUT_MS = 3000
const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' }

/** Resolve the engine base and refuse anything that is not a loopback host. */
function engineBase(): string {
  const raw = process.env[ENGINE_ENV]?.trim()
    || process.env[FALLBACK_ENGINE_ENV]?.trim()
    || DEFAULT_ENGINE
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new Error(`${ENGINE_ENV} is not a valid URL`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${ENGINE_ENV} must use http or https`)
  }
  if (!LOOPBACK_HOSTS.has(parsed.hostname)) {
    throw new Error(`${ENGINE_ENV} must point at a loopback host, got ${parsed.hostname}`)
  }
  return raw.replace(/\/+$/, '')
}

function jsonResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: JSON_HEADERS })
}

function failureDetail(error: unknown): string {
  if (error instanceof Error) {
    if (error.name === 'TimeoutError') return 'timeout'
    return error.name === 'TypeError' ? 'connect_failed' : error.name
  }
  return 'unknown'
}

async function health(base: string, request: Request): Promise<Response> {
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return jsonResponse(JSON.stringify({ error: 'bad_request' }), 400)
  }
  if (url.searchParams.size !== 0) return jsonResponse(JSON.stringify({ error: 'bad_request' }), 400)
  try {
    const upstream = await fetch(`${base}/health`, {
      method: 'GET',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
    return jsonResponse(await upstream.text(), upstream.status)
  } catch (error) {
    return jsonResponse(JSON.stringify({ error: 'engine_unreachable', detail: failureDetail(error) }), 502)
  }
}

export function apply(ctx: Context): void {
  const base = engineBase()
  ctx.effect(() => ctx.connection.fetch.register({
    path: ROUTE,
    methods: ['GET'],
    requestBody: 'buffered',
    fetch: (request: Request): Promise<Response> => health(base, request),
  }), `chives-ui: ${ROUTE}`)
}
