import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  PORTFOLIO_HISTORY_DEFAULT_DAYS,
  PORTFOLIO_HISTORY_MAX_DAYS,
  PORTFOLIO_HISTORY_MIN_DAYS,
  handleHubRequest,
  hubRouteTable,
  hubUpstreamTarget,
} from '../src/hubProxy.ts'
import { apply } from '../src/index.ts'

const BASE = 'http://127.0.0.1:8867'
const OVERVIEW = '/api/hub/portfolio-overview'
const HISTORY = '/api/hub/portfolio-history'

interface Hit {
  url: string
  init: RequestInit | undefined
}

function route(path: string) {
  const found = hubRouteTable().find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function fakeFetch(hits: Hit[], body: unknown = { ok: true, private: true }, status = 200): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' },
    })
  }
}

async function get(path: string, query: string, hits: Hit[] = [], options: {
  headers?: Record<string, string>
  body?: unknown
  status?: number
  fetchImpl?: typeof fetch
} = {}) {
  return await handleHubRequest(route(path), BASE, new Request(`http://localhost${path}${query}`, {
    method: 'GET',
    headers: options.headers,
  }), {
    fetchImpl: options.fetchImpl ?? fakeFetch(hits, options.body, options.status),
  })
}

test('the route table keeps exactly the two private reads plus the public spark read', () => {
  const table = hubRouteTable()
  assert.equal(table.length, 8)
  assert.deepEqual(table.filter((entry) => entry.kind === 'portfolio-overview').map((entry) => entry.path), [OVERVIEW])
  assert.deepEqual(table.filter((entry) => entry.kind === 'portfolio-history').map((entry) => entry.path), [HISTORY])
  for (const path of ['/api/hub/portfolio', '/api/hub/portfolio-holdings', '/api/hub/portfolio-history/../overview', '/api/hub/portfolio-overview/x']) {
    assert.equal(table.some((entry) => entry.path === path), false, path)
  }
})

test('portfolio rows are read-only GET routes', () => {
  const table = hubRouteTable()
  for (const path of [OVERVIEW, HISTORY]) {
    assert.deepEqual(table.find((entry) => entry.path === path)!.methods, ['GET'])
  }
})

test('overview accepts no query at all', () => {
  assert.equal(hubUpstreamTarget(route(OVERVIEW), new URL(`http://x${OVERVIEW}`)), '/portfolio/overview')
  for (const query of ['?x=1', '?days=90', '?id=1', '?days=7&x=1', '?private=true']) {
    assert.equal(hubUpstreamTarget(route(OVERVIEW), new URL(`http://x${OVERVIEW}${query}`)), null, query)
  }
})

test('history defaults to 90 days', () => {
  assert.equal(PORTFOLIO_HISTORY_DEFAULT_DAYS, 90)
  assert.equal(hubUpstreamTarget(route(HISTORY), new URL(`http://x${HISTORY}`)), '/portfolio/history?days=90')
})

test('history forwards only a canonical 7-365 integer', () => {
  assert.equal(PORTFOLIO_HISTORY_MIN_DAYS, 7)
  assert.equal(PORTFOLIO_HISTORY_MAX_DAYS, 365)
  assert.equal(hubUpstreamTarget(route(HISTORY), new URL(`http://x${HISTORY}?days=7`)), '/portfolio/history?days=7')
  assert.equal(hubUpstreamTarget(route(HISTORY), new URL(`http://x${HISTORY}?days=365`)), '/portfolio/history?days=365')
  assert.equal(hubUpstreamTarget(route(HISTORY), new URL(`http://x${HISTORY}?days=90`)), '/portfolio/history?days=90')
})

const BAD_HISTORY = [
  '?days=6',
  '?days=0',
  '?days=-7',
  '?days=366',
  '?days=999',
  '?days=7.0',
  '?days=07',
  '?days=+7',
  '?days=abc',
  '?days=',
  '?days=7&days=8',
  '?days=7&x=1',
  '?x=1',
  '?days=1e2',
  '?days=%2D7',
  '?days=99999999999999999999',
  '?DAYS=7',
  '?days=7%00',
]

test('history rejects every malformed or extra query without an upstream call', async () => {
  for (const query of BAD_HISTORY) {
    const hits: Hit[] = []
    const response = await get(HISTORY, query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
  }
})

test('some malformed queries on overview are also rejected before the network', async () => {
  for (const query of ['?x=1', '?days=90', '?id=1']) {
    const hits: Hit[] = []
    const response = await get(OVERVIEW, query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
  }
})

test('overview proxies the fixed upstream path with a minimal GET', async () => {
  const hits: Hit[] = []
  const response = await get(OVERVIEW, '', hits)
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.url, `${BASE}/portfolio/overview`)
  assert.equal(hits[0]!.init?.method, 'GET')
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
})

test('history proxies the canonical days value', async () => {
  const hits: Hit[] = []
  const response = await get(HISTORY, '?days=30', hits)
  assert.equal(response.status, 200)
  assert.equal(hits[0]!.url, `${BASE}/portfolio/history?days=30`)
})

test('both private reads always answer Cache-Control: no-store', async () => {
  for (const [path, query] of [[OVERVIEW, ''], [HISTORY, '?days=30']] as const) {
    const response = await get(path, query)
    assert.equal(response.headers.get('cache-control'), 'no-store', path)
  }
})

test('no-store is kept on validation errors and upstream failures', async () => {
  const bad = await get(HISTORY, '?days=6')
  assert.equal(bad.status, 400)
  assert.equal(bad.headers.get('cache-control'), 'no-store')
  const down = await get(OVERVIEW, '', [], { fetchImpl: async () => { throw new TypeError('connect failed') } })
  assert.equal(down.status, 502)
  assert.equal(down.headers.get('cache-control'), 'no-store')
})

test('cookies and browser headers never travel upstream', async () => {
  const hits: Hit[] = []
  await get(OVERVIEW, '', hits, {
    headers: { cookie: 'session=secret', authorization: 'Bearer secret', 'user-agent': 'test', origin: 'http://evil' },
  })
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
})

test('set-cookie from the hub is not relayed to the browser', async () => {
  const response = await get(OVERVIEW, '')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('an unreachable hub returns the exact contract body', async () => {
  const response = await get(OVERVIEW, '', [], { fetchImpl: async () => { throw new TypeError('connect failed') } })
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_unreachable' } })
})

test('a hub redirect is not followed and becomes hub_redirect', async () => {
  const response = await get(HISTORY, '?days=30', [], {
    fetchImpl: async () => new Response('', { status: 302, headers: { location: 'http://evil.example/' } }),
  })
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_redirect', message: 'upstream redirect was not followed' } })
  assert.equal(response.headers.get('cache-control'), 'no-store')
})

test('a hub 5xx becomes hub_error without exposing its body', async () => {
  const response = await get(OVERVIEW, '', [], {
    status: 500,
    body: { ok: false, error: { code: 'boom' }, positions: [{ code: '600000' }] },
  })
  assert.equal(response.status, 502)
  const text = await response.text()
  assert.match(text, /hub_error/)
  assert.ok(!text.includes('600000'))
})

test('POST is rejected on both private reads', async () => {
  for (const path of [OVERVIEW, HISTORY]) {
    const hits: Hit[] = []
    const response = await handleHubRequest(route(path), BASE, new Request(`http://localhost${path}`, { method: 'POST' }), { fetchImpl: fakeFetch(hits) })
    assert.equal(response.status, 400)
    assert.equal(hits.length, 0)
  }
})

test('the registered route count stays below fifty and includes the two reads', () => {
  const specs: { path: string; methods: string[] }[] = []
  const ctx = {
    effect: (fn: () => unknown) => { fn(); return () => {} },
    connection: { fetch: { register: (spec: { path: string; methods: string[] }) => { specs.push(spec); return () => {} } } },
  }
  apply(ctx as never)
  assert.ok(specs.length < 50, String(specs.length))
  const hub = specs.filter((spec) => spec.path.startsWith('/api/hub/')).map((spec) => spec.path)
  assert.equal(hub.length, 8)
  assert.ok(hub.includes(OVERVIEW))
  assert.ok(hub.includes(HISTORY))
  assert.equal(new Set(specs.map((spec) => spec.path)).size, specs.length)
})

test('error text never echoes portfolio query content', async () => {
  const response = await get(HISTORY, '?days=secret-token')
  const text = await response.text()
  assert.ok(!text.includes('secret-token'))
  assert.match(text, /bad_request/)
})
