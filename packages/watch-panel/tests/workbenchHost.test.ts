import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  handleMarketRequest,
  marketRouteTable,
  upstreamTarget,
} from '../src/marketProxy.ts'

interface Hit {
  url: string
  init: RequestInit | undefined
}

const BASE = 'http://127.0.0.1:8866'

function route(path: string) {
  const found = marketRouteTable().find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function fakeFetch(hits: Hit[], body: unknown = { ok: true }): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } })
  }
}

async function call(path: string, query: string, hits: Hit[], body: unknown = { ok: true }) {
  return await handleMarketRequest(route(path), BASE, new Request(`http://localhost${path}${query}`), { fetchImpl: fakeFetch(hits, body) })
}

test('the new routes stay inside the small fixed table', () => {
  const table = marketRouteTable()
  assert.ok(table.length < 20)
  assert.ok(table.some((entry) => entry.path === '/api/market/movers' && entry.upstream === '/movers'))
  assert.ok(table.some((entry) => entry.path === '/api/market/summary' && entry.upstream === '/summary'))
  assert.equal(new Set(table.map((entry) => entry.path)).size, table.length)
})

test('summary accepts no query at all', () => {
  assert.equal(upstreamTarget(route('/api/market/summary'), new URL('http://x/api/market/summary')), '/summary')
  for (const query of ['?x=1', '?kind=gainers', '?limit=10']) {
    assert.equal(upstreamTarget(route('/api/market/summary'), new URL(`http://x/api/market/summary${query}`)), null, query)
  }
})

test('movers without a query gets the documented defaults', () => {
  const target = upstreamTarget(route('/api/market/movers'), new URL('http://x/api/market/movers'))
  assert.equal(target, '/movers?kind=gainers&limit=10&include_st=0&include_new=0&include_bj=0')
})

test('movers forwards every allowed kind, limit and flag in canonical order', () => {
  const cases = [
    { query: '?kind=gainers&limit=8', target: '/movers?kind=gainers&limit=8&include_st=0&include_new=0&include_bj=0' },
    { query: '?kind=losers&limit=5&include_st=1', target: '/movers?kind=losers&limit=5&include_st=1&include_new=0&include_bj=0' },
    { query: '?kind=active&limit=20&include_st=1&include_new=1&include_bj=1', target: '/movers?kind=active&limit=20&include_st=1&include_new=1&include_bj=1' },
    { query: '?include_bj=1&limit=6&kind=gainers', target: '/movers?kind=gainers&limit=6&include_st=0&include_new=0&include_bj=1' },
  ]
  for (const entry of cases) {
    assert.equal(upstreamTarget(route('/api/market/movers'), new URL(`http://x/api/market/movers${entry.query}`)), entry.target, entry.query)
  }
})

const BAD_MOVERS = [
  '?kind',
  '?kind=',
  '?kind=gainer',
  '?kind=GAINERS',
  '?kind=losers&kind=gainers',
  '?limit=',
  '?limit=4',
  '?limit=21',
  '?limit=5.0',
  '?limit=05',
  '?limit=-5',
  '?limit=%2B5',
  '?limit=abc',
  '?limit=8&limit=9',
  '?limit=999999999999999999999',
  '?include_st=',
  '?include_st=2',
  '?include_st=true',
  '?include_st=01',
  '?include_new=-1',
  '?include_bj=%201',
  '?include_st=0&include_st=1',
  '?x=1',
  '?kind=gainers&x=1',
  '?kind=gainers%26limit=99',
  '?kind[]=gainers',
  '?kind=gainers;limit=9',
  '?limit=8%00',
]

test('malformed movers queries return 400 and never reach the upstream', async () => {
  for (const query of BAD_MOVERS) {
    const hits: Hit[] = []
    const response = await call('/api/market/movers', query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
    const payload = await response.json() as { ok: boolean; error: { code: string } }
    assert.equal(payload.ok, false)
    assert.equal(payload.error.code, 'bad_request')
  }
})

test('a malformed summary query also stops before the upstream', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/summary', '?limit=10', hits)
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('valid movers requests hit the canonical upstream path only', async () => {
  const hits: Hit[] = []
  await call('/api/market/movers', '?kind=losers&limit=8&include_st=1', hits)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.url, `${BASE}/movers?kind=losers&limit=8&include_st=1&include_new=0&include_bj=0`)
})

test('browser cookies and authorization never travel upstream', async () => {
  const hits: Hit[] = []
  const response = await handleMarketRequest(
    route('/api/market/movers'),
    BASE,
    new Request('http://localhost/api/market/movers?kind=gainers', {
      headers: { cookie: 'dsh=SECRET', authorization: 'Bearer SECRET', 'x-forwarded-for': '1.2.3.4' },
    }),
    { fetchImpl: fakeFetch(hits) },
  )
  assert.equal(response.status, 200)
  const headers = hits[0]!.init?.headers as Record<string, string>
  assert.deepEqual(headers, { accept: 'application/json' })
  assert.equal(hits[0]!.init?.method, 'GET')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('summary proxies the engine body and status', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/summary', '', hits, { ok: true, headlines: [] })
  assert.equal(response.status, 200)
  assert.deepEqual(await response.json(), { ok: true, headlines: [] })
  assert.equal(hits[0]!.url, `${BASE}/summary`)
})

test('an upstream 5xx becomes a structured 502', async () => {
  const response = await handleMarketRequest(
    route('/api/market/movers'),
    BASE,
    new Request('http://localhost/api/market/movers'),
    { fetchImpl: async () => new Response('boom', { status: 503 }) },
  )
  assert.equal(response.status, 502)
  const payload = await response.json() as { ok: boolean; error: { code: string } }
  assert.equal(payload.ok, false)
  assert.equal(payload.error.code, 'engine_error')
})

test('a network failure becomes engine_unreachable', async () => {
  const response = await handleMarketRequest(
    route('/api/market/summary'),
    BASE,
    new Request('http://localhost/api/market/summary'),
    { fetchImpl: async () => { throw new TypeError('fetch failed') } },
  )
  assert.equal(response.status, 502)
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'engine_unreachable')
})
