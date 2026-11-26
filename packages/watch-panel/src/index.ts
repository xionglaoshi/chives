/**
 * Host half: authenticated Fetch routes under /api (reads plus two restricted hub writes). `/api/watch/*`
 * proxies the local chives-radar engine, serves the analyses written by the trigger
 * and exposes the engine's rule audit log; `/api/market/*` proxies the local
 * market-watch engine through the fixed route table in `marketProxy.ts`, and
 * the chives-hub service through `hubProxy.ts` (reads plus two restricted
 * writes). The browser never learns any service address or a filesystem path:
 * every base must be loopback, requests carry no browser headers upstream, and
 * analysis files are named solely from a validated integer id.
 */
import { readFile } from 'node:fs/promises'
import { isAbsolute, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-connection'
import {
  MARKET_ENGINE_ENV,
  marketEngineBase,
  marketRouteHandlers,
} from './marketProxy.ts'
import {
  HUB_ENGINE_ENV,
  hubEngineBase,
  hubRouteHandlers,
} from './hubProxy.ts'

export const name = 'watch-panel'
export const inject = ['connection']

const DEFAULT_ENGINE = 'http://127.0.0.1:8865'
const ENGINE_ENV = 'WATCH_PANEL_ENGINE'
const ANALYSES_ENV = 'WATCH_PANEL_ANALYSES_DIR'
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]'])
const ROUTES = ['/health', '/state', '/alerts', '/rules', '/rules/history'] as const
const ALERT_PARAMS = ['after_id', 'limit'] as const
const TIMEOUT_MS = 3000
const DEFAULT_ANALYSES_LIMIT = 50
const MAX_ANALYSES_LIMIT = 200
const MAX_ANALYSIS_BYTES = 200 * 1024

const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' }

type Route = (typeof ROUTES)[number]

interface AnalysisRecord {
  alert_id: number
  [key: string]: unknown
}

/** Resolve the engine base and refuse anything that is not a loopback host. */
function engineBase(): string {
  const raw = process.env[ENGINE_ENV]?.trim() || DEFAULT_ENGINE
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

/** Absolute analyses directory: env override, else <repo>/runtime/watch/analyses. */
function analysesDir(): string {
  const raw = process.env[ANALYSES_ENV]?.trim()
  if (raw) {
    if (!isAbsolute(raw)) throw new Error(`${ANALYSES_ENV} must be an absolute path`)
    return raw
  }
  return fileURLToPath(new URL('../../../runtime/watch/analyses', import.meta.url))
}

function jsonResponse(body: string, status: number): Response {
  return new Response(body, { status, headers: JSON_HEADERS })
}

function badRequest(): Response {
  return jsonResponse(JSON.stringify({ error: 'bad_request' }), 400)
}

function failureDetail(error: unknown): string {
  if (error instanceof Error) {
    if (error.name === 'TimeoutError') return 'timeout'
    return error.name === 'TypeError' ? 'connect_failed' : error.name
  }
  return 'unknown'
}

/** Validate the query string; returns the canonical upstream search or null for 400. */
function upstreamSearch(route: Route, url: URL): string | null {
  const params = url.searchParams
  if (route === '/rules/history') {
    for (const key of params.keys()) if (key !== 'limit') return null
    if (params.getAll('limit').length > 1) return null
    const raw = params.get('limit')
    if (raw === null) return ''
    if (!/^\d+$/.test(raw)) return null
    const value = Number(raw)
    if (!Number.isInteger(value) || value < 0 || value > 500) return null
    return `?limit=${value}`
  }
  if (route !== '/alerts') return params.size === 0 ? '' : null
  for (const key of params.keys()) {
    if (!(ALERT_PARAMS as readonly string[]).includes(key)) return null
  }
  for (const key of ALERT_PARAMS) {
    if (params.getAll(key).length > 1) return null
  }
  const afterId = params.get('after_id')
  if (afterId !== null && !/^\d+$/.test(afterId)) return null
  const limit = params.get('limit')
  if (limit !== null) {
    if (!/^\d+$/.test(limit)) return null
    const value = Number(limit)
    if (value < 1 || value > 500) return null
  }
  const forwarded = new URLSearchParams()
  if (afterId !== null) forwarded.set('after_id', String(Number(afterId)))
  if (limit !== null) forwarded.set('limit', String(Number(limit)))
  const query = forwarded.toString()
  return query ? `?${query}` : ''
}

async function proxy(base: string, route: Route, request: Request): Promise<Response> {
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return badRequest()
  }
  const search = upstreamSearch(route, url)
  if (search === null) return badRequest()
  try {
    const upstream = await fetch(`${base}${route}${search}`, {
      method: 'GET',
      headers: { accept: 'application/json' },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
    return jsonResponse(await upstream.text(), upstream.status)
  } catch (error) {
    return jsonResponse(JSON.stringify({ error: 'engine_unreachable', detail: failureDetail(error) }), 502)
  }
}

/** `limit` is 1–200, at most once; absent means 50. Null means 400. */
function analysesLimit(url: URL): number | null {
  for (const key of url.searchParams.keys()) {
    if (key !== 'limit') return null
  }
  if (url.searchParams.getAll('limit').length > 1) return null
  const raw = url.searchParams.get('limit')
  if (raw === null) return DEFAULT_ANALYSES_LIMIT
  if (!/^\d+$/.test(raw)) return null
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > MAX_ANALYSES_LIMIT) return null
  return value
}

/** `id` is exactly one positive integer of at most 10 digits; null means 400. */
function analysisId(url: URL): number | null {
  for (const key of url.searchParams.keys()) {
    if (key !== 'id') return null
  }
  if (url.searchParams.getAll('id').length !== 1) return null
  const raw = url.searchParams.get('id') ?? ''
  if (!/^[1-9][0-9]{0,9}$/.test(raw)) return null
  return Number(raw)
}

function isMissingFile(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === 'ENOENT'
}

/** Read analyses.jsonl, skip bad lines and dedupe by alert_id with the last row winning. */
async function readAnalyses(dir: string, limit: number): Promise<AnalysisRecord[]> {
  let content: string
  try {
    content = await readFile(join(dir, 'analyses.jsonl'), 'utf8')
  } catch (error) {
    if (isMissingFile(error)) return []
    throw error
  }
  const byId = new Map<number, AnalysisRecord>()
  for (const line of content.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    let parsed: unknown
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      continue
    }
    if (typeof parsed !== 'object' || parsed === null) continue
    const record = parsed as { alert_id?: unknown }
    const id = record.alert_id
    if (typeof id !== 'number' || !Number.isInteger(id) || id <= 0) continue
    byId.set(id, parsed as AnalysisRecord)
  }
  return [...byId.values()].sort((left, right) => right.alert_id - left.alert_id).slice(0, limit)
}

async function serveAnalyses(dir: string, request: Request): Promise<Response> {
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return badRequest()
  }
  const limit = analysesLimit(url)
  if (limit === null) return badRequest()
  try {
    const records = await readAnalyses(dir, limit)
    return jsonResponse(JSON.stringify({ records, count: records.length }), 200)
  } catch {
    return jsonResponse(JSON.stringify({ error: 'internal' }), 500)
  }
}

/** Decode at most 200 KB, backing off continuation bytes so a character is never split. */
function decodeCapped(buffer: Buffer): { markdown: string; truncated: boolean } {
  if (buffer.length <= MAX_ANALYSIS_BYTES) {
    return { markdown: buffer.toString('utf8'), truncated: false }
  }
  let end = MAX_ANALYSIS_BYTES
  while (end > 0 && (buffer[end]! & 0xc0) === 0x80) end -= 1
  return { markdown: buffer.subarray(0, end).toString('utf8'), truncated: true }
}

async function serveAnalysis(dir: string, request: Request): Promise<Response> {
  let url: URL
  try {
    url = new URL(request.url)
  } catch {
    return badRequest()
  }
  const id = analysisId(url)
  if (id === null) return badRequest()
  let buffer: Buffer
  try {
    buffer = await readFile(join(dir, `analysis-${id}.md`))
  } catch (error) {
    if (isMissingFile(error)) return jsonResponse(JSON.stringify({ error: 'not_found' }), 404)
    return jsonResponse(JSON.stringify({ error: 'internal' }), 500)
  }
  const { markdown, truncated } = decodeCapped(buffer)
  return jsonResponse(JSON.stringify({ id, markdown, truncated }), 200)
}

export function apply(ctx: Context): void {
  const base = engineBase()
  const marketBase = marketEngineBase(process.env[MARKET_ENGINE_ENV])
  const hubBase = hubEngineBase(process.env[HUB_ENGINE_ENV])
  const dir = analysesDir()
  for (const route of ROUTES) {
    ctx.effect(() => ctx.connection.fetch.register({
      path: `/api/watch${route}`,
      methods: ['GET'],
      requestBody: 'buffered',
      fetch: (request: Request): Promise<Response> => proxy(base, route, request),
    }), `watch-panel: /api/watch${route}`)
  }
  ctx.effect(() => ctx.connection.fetch.register({
    path: '/api/watch/analyses',
    methods: ['GET'],
    requestBody: 'buffered',
    fetch: (request: Request): Promise<Response> => serveAnalyses(dir, request),
  }), 'watch-panel: /api/watch/analyses')
  ctx.effect(() => ctx.connection.fetch.register({
    path: '/api/watch/analysis',
    methods: ['GET'],
    requestBody: 'buffered',
    fetch: (request: Request): Promise<Response> => serveAnalysis(dir, request),
  }), 'watch-panel: /api/watch/analysis')
  for (const route of marketRouteHandlers(marketBase)) {
    ctx.effect(() => ctx.connection.fetch.register({
      path: route.path,
      methods: ['GET'],
      requestBody: 'buffered',
      fetch: route.handle,
    }), `watch-panel: ${route.path}`)
  }
  for (const route of hubRouteHandlers(hubBase)) {
    ctx.effect(() => ctx.connection.fetch.register({
      path: route.path,
      methods: [...route.methods],
      requestBody: route.requestBody,
      fetch: route.handle,
    }), `watch-panel: ${route.path}`)
  }
}
