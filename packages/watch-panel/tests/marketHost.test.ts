import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  MARKET_DEFAULT_ENGINE,
  MARKET_ENGINE_ENV,
  handleMarketRequest,
  isSectorCode,
  marketEngineBase,
  marketRouteHandlers,
  marketRouteTable,
  sectorCode,
  upstreamTarget,
} from '../src/marketProxy.ts'
import { apply } from '../src/index.ts'

interface Call {
  url: string
  init: RequestInit | undefined
}

const BASE = 'http://127.0.0.1:8866'

/**
 * Malformed browser queries: missing, empty, duplicate, extra parameters,
 * wrong case/width/length, path separators, percent-encoded dots and spaces.
 */
const BAD_QUERIES = [
  '',
  '?code',
  '?code=',
  '?bk0433',
  '?code=bk0433',
  '?code=BK043',
  '?code=BK12345',
  '?code=BK04333',
  '?code=801010',
  '?code=../',
  '?code=%2e',
  '?code=%2e%2e',
  '?code=BK0433%2e',
  '?code=BK0433%2f..',
  '?code=BK0433+',
  '?code=+BK0433',
  '?code=BK0433%20',
  '?code=BK0433%0a',
  '?code=BK0433%00',
  '?code=BK-433',
  '?code=%EF%BC%A2%EF%BC%AB0433',
  '?code=BK0433&code=BK0434',
  '?code=BK0433&x=1',
  '?x=BK0433',
  '?code=BK0433;x',
]

function proxy(calls: Call[], response: () => Promise<Response>): typeof fetch {
  return async (input, init) => {
    calls.push({ url: String(input), init })
    return response()
  }
}

function route(path: string) {
  const found = marketRouteTable().find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function ok(body: unknown = { ok: true }): Promise<Response> {
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } }))
}

test('marketEngineBase defaults to loopback and rejects anything else', () => {
  assert.equal(marketEngineBase(undefined), MARKET_DEFAULT_ENGINE)
  assert.equal(marketEngineBase('http://localhost:9000/'), 'http://localhost:9000')
  assert.equal(marketEngineBase('http://[::1]:8866'), 'http://[::1]:8866')
  assert.throws(() => marketEngineBase('http://10.0.0.2:8866'), /loopback/)
  assert.throws(() => marketEngineBase('ftp://127.0.0.1:8866'), /http/)
  assert.throws(() => marketEngineBase('not a url'), /valid URL/)
})

test('route table has exactly eighteen fixed pathnames and no generated sector paths', () => {
  const table = marketRouteTable()
  assert.equal(table.length, 18)
  assert.equal(new Set(table.map((entry) => entry.path)).size, 18)
  assert.deepEqual(table.map((entry) => entry.path), [
    '/api/market/health',
    '/api/market/overview',
    '/api/market/sectors',
    '/api/market/alerts',
    '/api/market/rules',
    '/api/market/sector',
    '/api/market/sector-members',
    '/api/market/movers',
    '/api/market/summary',
    '/api/market/flows',
    '/api/market/flows-northbound',
    '/api/market/pool',
    '/api/market/pool-ladder',
    '/api/market/pool-history',
    '/api/market/pool-yesterday',
    '/api/market/pool-by-industry',
    '/api/market/breadth-series',
    '/api/market/themes',
  ])
  assert.deepEqual(table.map((entry) => entry.upstream), [
    '/health',
    '/overview',
    '/sectors',
    '/alerts',
    '/rules',
    '/sectors/{code}',
    '/sectors/{code}/members',
    '/movers',
    '/summary',
    '/flows',
    '/flows/northbound',
    '/pool',
    '/pool/ladder',
    '/pool/history',
    '/pool/yesterday',
    '/pool/by-industry',
    '/breadth/series',
    '/themes',
  ])
  assert.equal(table.some((entry) => entry.path.startsWith('/api/market/sectors/BK')), false)
  assert.equal(table.some((entry) => entry.path.includes('801010')), false)
})

test('sector ids are exactly BK plus four digits', () => {
  assert.equal(isSectorCode('BK0433'), true)
  assert.equal(isSectorCode('BK9999'), true)
  for (const code of ['801010', 'bk0433', 'BK12345', 'BK043', 'BK0433%2e', '../BK0433', 'BK0433/', '', 'BK0433\n', 'BK0433 ']) {
    assert.equal(isSectorCode(code), false, code)
  }
})

test('valid codes resolve to the matching upstream path, members included', () => {
  const sector = route('/api/market/sector')
  const members = route('/api/market/sector-members')
  assert.equal(sectorCode(new URL('http://x/api/market/sector?code=BK0433')), 'BK0433')
  assert.equal(upstreamTarget(sector, new URL('http://x/api/market/sector?code=BK0433')), '/sectors/BK0433')
  assert.equal(upstreamTarget(sector, new URL('http://x/api/market/sector?code=BK9999')), '/sectors/BK9999')
  assert.equal(upstreamTarget(members, new URL('http://x/api/market/sector-members?code=BK0433')), '/sectors/BK0433/members')
})

test('malformed sector codes are rejected by the parser before any upstream call', () => {
  assert.ok(BAD_QUERIES.length >= 15, String(BAD_QUERIES.length))
  const sector = route('/api/market/sector')
  const members = route('/api/market/sector-members')
  for (const query of BAD_QUERIES) {
    assert.equal(sectorCode(new URL(`http://x/api/market/sector${query}`)), null, query)
    assert.equal(upstreamTarget(sector, new URL(`http://x/api/market/sector${query}`)), null, query)
    assert.equal(upstreamTarget(members, new URL(`http://x/api/market/sector-members${query}`)), null, query)
  }
})

test('a malformed code returns 400 bad_request and never reaches upstream', async () => {
  const calls: Call[] = []
  const fetchImpl = proxy(calls, () => ok())
  for (const query of BAD_QUERIES) {
    for (const path of ['/api/market/sector', '/api/market/sector-members']) {
      const response = await handleMarketRequest(route(path), BASE, new Request(`http://localhost${path}${query}`), { fetchImpl })
      assert.equal(response.status, 400, `${path}${query}`)
      const body = await response.json() as { ok: boolean; error: { code: string } }
      assert.equal(body.ok, false)
      assert.equal(body.error.code, 'bad_request')
    }
  }
  assert.equal(calls.length, 0)
})

test('a validated code proxies to a URL built from the code, never the raw query', async () => {
  const calls: Call[] = []
  const response = await handleMarketRequest(
    route('/api/market/sector-members'),
    BASE,
    new Request('http://localhost/api/market/sector-members?code=BK0433'),
    { fetchImpl: proxy(calls, () => ok({ ok: true, rows: [] })) },
  )
  assert.equal(response.status, 200)
  assert.equal(calls[0]!.url, 'http://127.0.0.1:8866/sectors/BK0433/members')
  assert.equal(calls[0]!.url.includes('code='), false)
})

test('a validated detail code proxies to the matching upstream path', async () => {
  const calls: Call[] = []
  const response = await handleMarketRequest(
    route('/api/market/sector'),
    BASE,
    new Request('http://localhost/api/market/sector?code=BK0433'),
    { fetchImpl: proxy(calls, () => ok({ ok: true })) },
  )
  assert.equal(response.status, 200)
  assert.equal(calls[0]!.url, 'http://127.0.0.1:8866/sectors/BK0433')
})

test('upstreamTarget accepts sw1/industry and rejects everything else', () => {
  const sectors = route('/api/market/sectors')
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors?level=sw1')), '/sectors?level=sw1')
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors?level=industry')), '/sectors?level=industry')
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors')), null)
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors?level=sw2')), null)
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors?level=sw1&x=1')), null)
  assert.equal(upstreamTarget(sectors, new URL('http://x/api/market/sectors?level=sw1&level=industry')), null)
  const alerts = route('/api/market/alerts')
  assert.equal(upstreamTarget(alerts, new URL('http://x/api/market/alerts?since_id=01&limit=050')), '/alerts?since_id=1&limit=50')
  assert.equal(upstreamTarget(alerts, new URL('http://x/api/market/alerts?since_id=-1')), null)
  assert.equal(upstreamTarget(alerts, new URL('http://x/api/market/alerts?limit=0')), null)
  assert.equal(upstreamTarget(alerts, new URL('http://x/api/market/alerts?limit=201')), null)
  assert.equal(upstreamTarget(route('/api/market/health'), new URL('http://x/api/market/health?x=1')), null)
})

test('forwards GET + accept only and strips upstream headers and cookies', async () => {
  const calls: Call[] = []
  const response = await handleMarketRequest(
    route('/api/market/overview'),
    BASE,
    new Request('http://localhost/api/market/overview', { headers: { cookie: 'dsh=secret', authorization: 'Bearer x' } }),
    { fetchImpl: proxy(calls, () => ok({ ok: true })) },
  )
  assert.equal(response.status, 200)
  assert.equal(calls[0]!.url, 'http://127.0.0.1:8866/overview')
  assert.deepEqual(calls[0]!.init?.headers, { accept: 'application/json' })
  assert.equal(calls[0]!.init?.method, 'GET')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('rejects a bad query before calling upstream', async () => {
  const calls: Call[] = []
  const response = await handleMarketRequest(
    route('/api/market/sectors'),
    BASE,
    new Request('http://localhost/api/market/sectors?level=sw1&evil=1'),
    { fetchImpl: proxy(calls, () => ok()) },
  )
  assert.equal(response.status, 400)
  assert.equal(calls.length, 0)
  const body = await response.json() as { ok: boolean; error: { code: string } }
  assert.equal(body.ok, false)
  assert.equal(body.error.code, 'bad_request')
})

test('passes a business error through with HTTP 200', async () => {
  const response = await handleMarketRequest(
    route('/api/market/overview'),
    BASE,
    new Request('http://localhost/api/market/overview'),
    { fetchImpl: proxy([], () => Promise.resolve(new Response(JSON.stringify({ ok: false, error: { code: 'stale' } }), { status: 200 }))) },
  )
  assert.equal(response.status, 200)
  assert.equal((await response.json() as { ok: boolean }).ok, false)
})

test('unreachable upstream becomes 502 with the contract error body', async () => {
  const response = await handleMarketRequest(
    route('/api/market/health'),
    BASE,
    new Request('http://localhost/api/market/health'),
    { fetchImpl: async () => { throw new TypeError('fetch failed') } },
  )
  assert.equal(response.status, 502)
  const body = await response.json() as { ok: boolean; error: { code: string } }
  assert.equal(body.ok, false)
  assert.equal(body.error.code, 'engine_unreachable')
})

test('a timeout is reported as engine_unreachable, never 500', async () => {
  const response = await handleMarketRequest(
    route('/api/market/health'),
    BASE,
    new Request('http://localhost/api/market/health'),
    { fetchImpl: async () => { throw new DOMException('timed out', 'TimeoutError') } },
  )
  assert.equal(response.status, 502)
  assert.equal((await response.json() as { error: { code: string } }).error.code, 'engine_unreachable')
})

test('an oversized response is cut off with response_too_large', async () => {
  const big = 'x'.repeat(2048)
  const response = await handleMarketRequest(
    route('/api/market/overview'),
    BASE,
    new Request('http://localhost/api/market/overview'),
    { maxBytes: 1000, fetchImpl: proxy([], () => Promise.resolve(new Response(big, { status: 200 }))) },
  )
  assert.equal(response.status, 502)
  assert.equal((await response.json() as { error: { code: string } }).error.code, 'response_too_large')
})

test('an oversized content-length is rejected before reading', async () => {
  const response = await handleMarketRequest(
    route('/api/market/overview'),
    BASE,
    new Request('http://localhost/api/market/overview'),
    { maxBytes: 10, fetchImpl: proxy([], () => Promise.resolve(new Response('{}', { status: 200, headers: { 'content-length': '999' } }))) },
  )
  assert.equal((await response.json() as { error: { code: string } }).error.code, 'response_too_large')
})

test('upstream 5xx is not forwarded as a 500', async () => {
  const response = await handleMarketRequest(
    route('/api/market/overview'),
    BASE,
    new Request('http://localhost/api/market/overview'),
    { fetchImpl: proxy([], () => Promise.resolve(new Response('boom', { status: 500 }))) },
  )
  assert.equal(response.status, 502)
  assert.equal((await response.json() as { error: { code: string } }).error.code, 'engine_error')
})

test('apply registers eighteen market routes as GET and rejects a non-loopback env', () => {
  const specs: { path: string; methods: string[] }[] = []
  const ctx = {
    effect: (fn: () => unknown) => { fn(); return () => {} },
    connection: { fetch: { register: (spec: { path: string; methods: string[] }) => { specs.push(spec); return () => {} } } },
  }
  const previous = process.env[MARKET_ENGINE_ENV]
  const previousWatch = process.env.WATCH_PANEL_ENGINE
  process.env.WATCH_PANEL_ENGINE = 'http://127.0.0.1:8865'
  process.env[MARKET_ENGINE_ENV] = 'http://127.0.0.1:8866'
  try {
    apply(ctx as never)
    const market = specs.filter((spec) => spec.path.startsWith('/api/market/'))
    assert.deepEqual(market.map((spec) => spec.path), [
      '/api/market/health',
      '/api/market/overview',
      '/api/market/sectors',
      '/api/market/alerts',
      '/api/market/rules',
      '/api/market/sector',
      '/api/market/sector-members',
      '/api/market/movers',
      '/api/market/summary',
      '/api/market/flows',
      '/api/market/flows-northbound',
      '/api/market/pool',
      '/api/market/pool-ladder',
      '/api/market/pool-history',
      '/api/market/pool-yesterday',
      '/api/market/pool-by-industry',
      '/api/market/breadth-series',
      '/api/market/themes',
    ])
    assert.ok(market.every((spec) => JSON.stringify(spec.methods) === '["GET"]'))
    assert.ok(specs.some((spec) => spec.path === '/api/watch/rules/history'))
    process.env[MARKET_ENGINE_ENV] = 'http://192.168.1.4:8866'
    assert.throws(() => apply(ctx as never), /loopback/)
  } finally {
    if (previous === undefined) delete process.env[MARKET_ENGINE_ENV]
    else process.env[MARKET_ENGINE_ENV] = previous
    if (previousWatch === undefined) delete process.env.WATCH_PANEL_ENGINE
    else process.env.WATCH_PANEL_ENGINE = previousWatch
  }
})

test('marketRouteHandlers exposes exactly the eighteen fixed paths', () => {
  const handlers = marketRouteHandlers(BASE)
  assert.equal(handlers.length, 18)
  assert.deepEqual(handlers.map((handler) => handler.path), marketRouteTable().map((entry) => entry.path))
})
