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

test('flows without a query get the documented sector-inflow defaults', () => {
  assert.equal(
    upstreamTarget(route('/api/market/flows'), new URL('http://x/api/market/flows')),
    '/flows?kind=sector_in&limit=10&include_st=0&include_new=0&include_bj=0',
  )
})

test('flows forward every allowed kind, limit and flag in canonical order', () => {
  const cases = [
    { query: '?kind=sector_out&limit=8', target: '/flows?kind=sector_out&limit=8&include_st=0&include_new=0&include_bj=0' },
    { query: '?kind=stock_in&limit=5&include_st=1', target: '/flows?kind=stock_in&limit=5&include_st=1&include_new=0&include_bj=0' },
    { query: '?include_bj=1&limit=20&kind=stock_out', target: '/flows?kind=stock_out&limit=20&include_st=0&include_new=0&include_bj=1' },
  ]
  for (const entry of cases) {
    assert.equal(upstreamTarget(route('/api/market/flows'), new URL(`http://x/api/market/flows${entry.query}`)), entry.target, entry.query)
  }
})

const BAD_FLOWS = [
  '?kind',
  '?kind=',
  '?kind=sector',
  '?kind=SECTOR_IN',
  '?kind=sector_in&kind=sector_out',
  '?limit=',
  '?limit=4',
  '?limit=21',
  '?limit=05',
  '?limit=5.0',
  '?limit=-5',
  '?limit=8&limit=9',
  '?include_st=',
  '?include_st=2',
  '?include_st=true',
  '?include_new=-1',
  '?include_bj=%201',
  '?include_st=0&include_st=1',
  '?x=1',
  '?kind=sector_in&x=1',
  '?kind[]=sector_in',
  '?limit=8%00',
]

test('malformed flow queries return 400 and never reach the upstream', async () => {
  assert.ok(BAD_FLOWS.length >= 15)
  for (const query of BAD_FLOWS) {
    const hits: Hit[] = []
    const response = await call('/api/market/flows', query, hits)
    assert.equal(response.status, 400, query)
    assert.equal(hits.length, 0, query)
    assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'bad_request')
  }
})

test('northbound accepts no query at all', () => {
  assert.equal(upstreamTarget(route('/api/market/flows-northbound'), new URL('http://x/api/market/flows-northbound')), '/flows/northbound')
  for (const query of ['?x=1', '?available=1', '?limit=10']) {
    assert.equal(upstreamTarget(route('/api/market/flows-northbound'), new URL(`http://x/api/market/flows-northbound${query}`)), null, query)
  }
})

test('a malformed northbound query stops before the upstream', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/flows-northbound', '?x=1', hits)
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a valid flows request hits only the canonical upstream path', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/flows', '?kind=stock_out&limit=8', hits, { ok: true, available: true })
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.url, `${BASE}/flows?kind=stock_out&limit=8&include_st=0&include_new=0&include_bj=0`)
  assert.deepEqual(await response.json(), { ok: true, available: true })
})

test('the flows proxy still drops browser cookies and set-cookie', async () => {
  const hits: Hit[] = []
  const response = await handleMarketRequest(route('/api/market/flows'), BASE, new Request('http://localhost/api/market/flows', {
    headers: { cookie: 'dsh=SECRET', authorization: 'Bearer SECRET' },
  }), { fetchImpl: fakeFetch(hits, { ok: true }) })
  assert.equal(response.status, 200)
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
  assert.equal(response.headers.get('set-cookie'), null)
})

test('the flows routes are part of the fixed table', () => {
  assert.ok(marketRouteTable().some((entry) => entry.path === '/api/market/flows' && entry.upstream === '/flows'))
  assert.ok(marketRouteTable().some((entry) => entry.path === '/api/market/flows-northbound' && entry.upstream === '/flows/northbound'))
})
