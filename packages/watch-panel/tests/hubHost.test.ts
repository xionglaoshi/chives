import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  HUB_DEFAULT_ENGINE,
  HUB_ENGINE_ENV,
  HUB_MAX_ID,
  handleHubRequest,
  hubEngineBase,
  hubRouteHandlers,
  hubRouteTable,
  hubUpstreamTarget,
  validatePlanAction,
  validateSignalAction,
} from '../src/hubProxy.ts'
import { apply } from '../src/index.ts'

interface Hit {
  url: string
  init: RequestInit | undefined
}

const BASE = 'http://127.0.0.1:8867'

function route(path: string) {
  const found = hubRouteTable().find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function fakeFetch(hits: Hit[], body: unknown = { ok: true }, status = 200): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } })
  }
}

async function get(path: string, query: string, hits: Hit[], body: unknown = { ok: true }) {
  return await handleHubRequest(route(path), BASE, new Request(`http://localhost${path}${query}`), { fetchImpl: fakeFetch(hits, body) })
}

interface PostOptions {
  headers?: Record<string, string>
  method?: string
  status?: number
  response?: unknown
}

async function post(path: string, body: unknown, hits: Hit[], options: PostOptions = {}) {
  const raw = typeof body === 'string' ? body : JSON.stringify(body)
  const headers = {
    'content-type': 'application/json',
    'x-chives-action': '1',
    ...options.headers,
  }
  return await handleHubRequest(route(path), BASE, new Request(`http://localhost${path}`, {
    method: options.method ?? 'POST',
    headers,
    body: options.method === 'GET' ? undefined : raw,
  }), { fetchImpl: fakeFetch(hits, options.response ?? { ok: true }, options.status ?? 200) })
}

test('hubEngineBase defaults to loopback and rejects anything else', () => {
  assert.equal(hubEngineBase(undefined), HUB_DEFAULT_ENGINE)
  assert.equal(hubEngineBase('http://localhost:9000/'), 'http://localhost:9000')
  assert.equal(hubEngineBase('http://[::1]:8867'), 'http://[::1]:8867')
  assert.throws(() => hubEngineBase('http://10.0.0.2:8867'), /loopback/)
  assert.throws(() => hubEngineBase('ftp://127.0.0.1:8867'), /http/)
  assert.throws(() => hubEngineBase('not a url'), /valid URL/)
})

test('with the review layer offline the Host registers only the eight core hub paths', () => {
  const table = hubRouteTable()
  assert.equal(table.length, 8)
  assert.ok(!table.some((entry) => /settings|discipline|review|card|candidates|guidance|setting-action/.test(entry.path)))
  assert.deepEqual(table.filter((entry) => entry.methods.includes('POST')).map((entry) => entry.path), ['/api/hub/signal-action', '/api/hub/plan-action'])
})

test('the full hub table (review layer on) has nineteen exact paths: five writes, two private portfolio reads and the fixed reads', () => {
  const table = hubRouteTable({ review: true })
  assert.equal(table.length, 19)
  assert.deepEqual(table.map((entry) => entry.path), [
    '/api/hub/signals',
    '/api/hub/signal',
    '/api/hub/plans',
    '/api/hub/signal-action',
    '/api/hub/plan-action',
    '/api/hub/portfolio-overview',
    '/api/hub/portfolio-history',
    '/api/hub/spark',
    '/api/hub/settings',
    '/api/hub/discipline',
    '/api/hub/reviews',
    '/api/hub/review',
    '/api/hub/cards',
    '/api/hub/card',
    '/api/hub/candidates-stats',
    '/api/hub/guidance',
    '/api/hub/setting-action',
    '/api/hub/discipline-action',
    '/api/hub/card-action',
  ])
  assert.deepEqual(table.filter((entry) => entry.methods.includes('POST')).map((entry) => entry.path), [
    '/api/hub/signal-action',
    '/api/hub/plan-action',
    '/api/hub/setting-action',
    '/api/hub/discipline-action',
    '/api/hub/card-action',
  ])
  assert.deepEqual(table.filter((entry) => entry.path.includes('portfolio')).map((entry) => entry.path), [
    '/api/hub/portfolio-overview',
    '/api/hub/portfolio-history',
  ])
})

test('the full registration stays below fifty routes', () => {
  const specs: { path: string; methods: string[] }[] = []
  const ctx = {
    effect: (fn: () => unknown) => { fn(); return () => {} },
    connection: { fetch: { register: (spec: { path: string; methods: string[] }) => { specs.push(spec); return () => {} } } },
  }
  apply(ctx as never)
  assert.ok(specs.length < 50, String(specs.length))
  assert.equal(specs.filter((spec) => spec.path.startsWith('/api/hub/')).length, 8)
  assert.equal(new Set(specs.map((spec) => spec.path)).size, specs.length)
})

test('signals without a query use status=active and limit=50', () => {
  assert.equal(hubUpstreamTarget(route('/api/hub/signals'), new URL('http://x/api/hub/signals')), '/signals?status=active&limit=50')
})

test('signals forward every allowed parameter in canonical order', () => {
  assert.equal(
    hubUpstreamTarget(route('/api/hub/signals'), new URL('http://x/api/hub/signals?status=done&decide=0&object=stock&limit=20&since_id=5')),
    '/signals?status=done&decide=0&object=stock&limit=20&since_id=5',
  )
  assert.equal(
    hubUpstreamTarget(route('/api/hub/signals'), new URL('http://x/api/hub/signals?limit=100&status=all&object=sector')),
    '/signals?status=all&object=sector&limit=100',
  )
})

const BAD_SIGNALS = [
  '?status',
  '?status=',
  '?status=archived',
  '?status=ACTIVE',
  '?status=active&status=done',
  '?decide',
  '?decide=2',
  '?decide=true',
  '?decide=-1',
  '?object',
  '?object=index',
  '?object=STOCK',
  '?limit=0',
  '?limit=101',
  '?limit=05',
  '?limit=5.0',
  '?limit=+5',
  '?limit=abc',
  '?limit=50&limit=20',
  '?since_id=-1',
  '?since_id=01',
  '?since_id=1.5',
  '?since_id=abc',
  '?since_id=99999999999999999999',
  '?x=1',
  '?status=active&x=1',
  '?status=active%26limit=999',
]

test('malformed signal queries return 400 and never reach the hub', async () => {
  assert.ok(BAD_SIGNALS.length >= 15)
  for (const query of BAD_SIGNALS) {
    const hits: Hit[] = []
    const response = await get('/api/hub/signals', query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
    const payload = await response.json() as { ok: boolean; error: { code: string } }
    assert.equal(payload.ok, false)
    assert.equal(payload.error.code, 'bad_request')
  }
})

test('malformed single-signal ids are rejected before any upstream call', async () => {
  for (const query of ['', '?id', '?id=', '?id=0', '?id=-1', '?id=1.5', '?id=abc', '?id=1&id=2', `?id=${HUB_MAX_ID + 1}`, '?x=1']) {
    const hits: Hit[] = []
    const response = await get('/api/hub/signal', query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
  }
})

test('valid signal ids resolve to the numeric upstream path', () => {
  assert.equal(hubUpstreamTarget(route('/api/hub/signal'), new URL('http://x/api/hub/signal?id=42')), '/signals/42')
  assert.equal(hubUpstreamTarget(route('/api/hub/signal'), new URL(`http://x/api/hub/signal?id=${HUB_MAX_ID}`)), `/signals/${HUB_MAX_ID}`)
})

test('plan status is a strict whitelist', () => {
  assert.equal(hubUpstreamTarget(route('/api/hub/plans'), new URL('http://x/api/hub/plans')), '/plans')
  assert.equal(hubUpstreamTarget(route('/api/hub/plans'), new URL('http://x/api/hub/plans?status=active')), '/plans?status=active')
  for (const query of ['?status=', '?status=pending', '?status=active&status=all', '?x=1']) {
    assert.equal(hubUpstreamTarget(route('/api/hub/plans'), new URL(`http://x/api/hub/plans${query}`)), null, query)
  }
})

test('a valid signals request reaches only the canonical upstream URL', async () => {
  const hits: Hit[] = []
  const response = await get('/api/hub/signals', '?status=snoozed&limit=10', hits, { ok: true, signals: [{ id: 1 }] })
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.url, `${BASE}/signals?status=snoozed&limit=10`)
  assert.equal(hits[0]!.init?.method, 'GET')
})

test('GET requests forward no browser headers, cookies or set-cookie', async () => {
  const hits: Hit[] = []
  const response = await handleHubRequest(route('/api/hub/signals'), BASE, new Request('http://localhost/api/hub/signals', {
    headers: { cookie: 'dsh=SECRET', authorization: 'Bearer SECRET', 'x-forwarded-for': '1.2.3.4' },
  }), { fetchImpl: fakeFetch(hits) })
  assert.equal(response.status, 200)
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
  assert.equal(hits[0]!.init?.redirect, 'manual')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('an upstream redirect is not followed', async () => {
  const response = await handleHubRequest(route('/api/hub/plans'), BASE, new Request('http://localhost/api/hub/plans'), {
    fetchImpl: async () => new Response('', { status: 302, headers: { location: 'http://evil.example/' } }),
  })
  assert.equal(response.status, 502)
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'hub_redirect')
})

test('an upstream 5xx becomes a structured 502', async () => {
  const response = await handleHubRequest(route('/api/hub/plans'), BASE, new Request('http://localhost/api/hub/plans'), {
    fetchImpl: async () => new Response('boom', { status: 503 }),
  })
  assert.equal(response.status, 502)
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'hub_error')
})

test('an unreachable hub returns the exact contract body', async () => {
  const response = await handleHubRequest(route('/api/hub/signals'), BASE, new Request('http://localhost/api/hub/signals'), {
    fetchImpl: async () => { throw new TypeError('fetch failed') },
  })
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_unreachable' } })
})

test('a POST without the action header is rejected before the hub', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/signal-action', { id: 1, action: 'ack' }, hits, { headers: { 'x-chives-action': '' } })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a POST with a non-JSON content type is rejected', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/signal-action', { id: 1, action: 'ack' }, hits, { headers: { 'content-type': 'text/plain' } })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a GET on a write route is rejected without an upstream call', async () => {
  const hits: Hit[] = []
  for (const path of ['/api/hub/signal-action', '/api/hub/plan-action']) {
    const response = await post(path, '', hits, { method: 'GET' })
    assert.equal(response.status, 400, path)
  }
  assert.equal(hits.length, 0)
})

test('a valid ack is rebuilt and sent as a canonical JSON body', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/signal-action', { id: 7, action: 'ack' }, hits, { response: { ok: true, signal: { id: 7 } } })
  assert.equal(response.status, 200)
  assert.equal(hits[0]!.url, `${BASE}/signals/7/action`)
  assert.equal(hits[0]!.init?.method, 'POST')
  assert.equal(hits[0]!.init?.body, '{"action":"ack"}')
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json', 'content-type': 'application/json' })
})

test('a valid snooze keeps a preset or an ISO timestamp only', async () => {
  const preset: Hit[] = []
  await post('/api/hub/signal-action', { id: 7, action: 'snooze', until: 'next_open' }, preset)
  assert.equal(preset[0]!.init?.body, '{"action":"snooze","until":"next_open"}')
  const iso: Hit[] = []
  await post('/api/hub/signal-action', { id: 7, action: 'snooze', until: '2026-11-04T09:30:00+08:00' }, iso)
  assert.equal(iso[0]!.init?.body, '{"action":"snooze","until":"2026-11-04T09:30:00+08:00"}')
})

test('extra body fields, bad ids and bad actions are all rejected', async () => {
  const cases: unknown[] = [
    { id: 1, action: 'ack', extra: true },
    { id: 0, action: 'ack' },
    { id: -1, action: 'ack' },
    { id: 1.5, action: 'ack' },
    { id: '1', action: 'ack' },
    { id: 1, action: 'delete' },
    { id: 1, action: 'ACK' },
    { id: 1, action: 'snooze' },
    { id: 1, action: 'snooze', until: '45m' },
    { id: 1, action: 'snooze', until: 'tomorrow' },
    { id: 1, action: 'ack', until: '30m' },
    { action: 'ack' },
    [],
    'null',
    null,
  ]
  for (const body of cases) {
    const hits: Hit[] = []
    const response = await post('/api/hub/signal-action', body, hits)
    assert.equal(response.status, 400, JSON.stringify(body))
    assert.equal(hits.length, 0, JSON.stringify(body))
  }
})

test('a body over four kilobytes is rejected before reaching the hub', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/signal-action', JSON.stringify({ id: 1, action: 'ack', pad: 'x'.repeat(5000) }), hits)
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a write never forwards cookies or the raw browser body', async () => {
  const hits: Hit[] = []
  const response = await handleHubRequest(route('/api/hub/signal-action'), BASE, new Request('http://localhost/api/hub/signal-action', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1', cookie: 'dsh=SECRET', 'user-agent': 'browser' },
    body: JSON.stringify({ id: 3, action: 'ignore' }),
  }), { fetchImpl: fakeFetch(hits, { ok: true }) })
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.init?.body, '{"action":"ignore"}')
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json', 'content-type': 'application/json' })
})

test('a query string on a write route is rejected', async () => {
  const hits: Hit[] = []
  const response = await handleHubRequest(route('/api/hub/signal-action'), BASE, new Request('http://localhost/api/hub/signal-action?x=1', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1' },
    body: JSON.stringify({ id: 1, action: 'ack' }),
  }), { fetchImpl: fakeFetch(hits) })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('valid plan actions confirm, cancel and extend', async () => {
  const confirm: Hit[] = []
  await post('/api/hub/plan-action', { id: 77, action: 'confirm' }, confirm)
  assert.equal(confirm[0]!.url, `${BASE}/plans/77/action`)
  assert.equal(confirm[0]!.init?.body, '{"action":"confirm"}')
  const extend: Hit[] = []
  await post('/api/hub/plan-action', { id: 77, action: 'extend', expires_at: '2026-11-10T15:00:00+08:00' }, extend)
  assert.equal(extend[0]!.init?.body, '{"action":"extend","expires_at":"2026-11-10T15:00:00+08:00"}')
})

test('plan extend requires an ISO expiry, other actions reject one', async () => {
  for (const body of [
    { id: 77, action: 'extend' },
    { id: 77, action: 'extend', expires_at: 'soon' },
    { id: 77, action: 'confirm', expires_at: '2026-11-10T15:00:00+08:00' },
    { id: 77, action: 'cancel', extra: 1 },
  ]) {
    assert.equal(validatePlanAction(body), null, JSON.stringify(body))
  }
  assert.deepEqual(validatePlanAction({ id: 1, action: 'cancel' }), { id: 1, body: { action: 'cancel' } })
})

test('signal action validation is strict about exact keys', () => {
  assert.deepEqual(validateSignalAction({ id: 2, action: 'reopen' }), { id: 2, body: { action: 'reopen' } })
  assert.equal(validateSignalAction({ id: 2, action: 'ignore', until: null }), null)
  assert.equal(validateSignalAction({ id: 2, action: 'snooze', until: 'close', extra: 1 }), null)
})

test('handlers expose the five paths with their declared methods', () => {
  const handlers = hubRouteHandlers(BASE)
  assert.deepEqual(handlers.map((handler) => handler.path), hubRouteTable().map((entry) => entry.path))
  assert.deepEqual(handlers.find((handler) => handler.path === '/api/hub/signals')?.methods, ['GET'])
  assert.deepEqual(handlers.find((handler) => handler.path === '/api/hub/signal-action')?.methods, ['POST'])
  assert.ok(handlers.every((handler) => handler.requestBody === 'buffered'))
})
