import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  handleMarketRequest,
  isCalendarDate,
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

function fakeFetch(hits: Hit[], status = 200, body = '{"ok":true}'): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(body, { status, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } })
  }
}

function call(path: string, query = '', hits: Hit[] = [], init?: RequestInit) {
  return handleMarketRequest(route(path), BASE, new Request(`http://localhost${path}${query}`, init), { fetchImpl: fakeFetch(hits) })
}

function target(path: string, query: string): string | null {
  return upstreamTarget(route(path), new URL(`http://x${path}${query}`))
}

const BAD_DATES = [
  '',
  '2026-11-4',
  '2026-1-04',
  '2026-11-04 ',
  ' 2026-11-04',
  '2026-11-04\n',
  '2026-13-01',
  '2026-00-10',
  '2026-02-30',
  '2025-02-29',
  '2026-11-00',
  '2026-11-32',
  '20261104',
  '2026/11/04',
  '../2026-11-04',
  '2026-11-04T00:00',
  '%2e%2e',
  '2026-11-04%00',
]

test('the review data layer adds exactly seven fixed read routes', () => {
  const added = marketRouteTable().filter((entry) => entry.path.startsWith('/api/market/pool') || entry.path === '/api/market/breadth-series' || entry.path === '/api/market/themes')
  assert.deepEqual(added.map((entry) => entry.path), [
    '/api/market/pool',
    '/api/market/pool-ladder',
    '/api/market/pool-history',
    '/api/market/pool-yesterday',
    '/api/market/pool-by-industry',
    '/api/market/breadth-series',
    '/api/market/themes',
  ])
  assert.deepEqual(added.map((entry) => entry.upstream), [
    '/pool',
    '/pool/ladder',
    '/pool/history',
    '/pool/yesterday',
    '/pool/by-industry',
    '/breadth/series',
    '/themes',
  ])
})

test('no generated or banned market path is registered', () => {
  const paths = marketRouteTable().map((entry) => entry.path)
  for (const banned of [
    '/api/market/*',
    '/api/market/pool/zt',
    '/api/market/pool/history',
    '/api/market/pool-history/10',
    '/api/market/review-data',
    '/api/market/themes/BK0001',
    '/api/market/breadth-series/2026-11-04',
  ]) {
    assert.equal(paths.includes(banned), false, banned)
  }
  assert.equal(marketRouteTable().length, 18)
})

test('calendar validation is real, strict and leap-year aware', () => {
  for (const value of ['2026-11-04', '2024-02-29', '2000-02-29', '2026-01-01', '2026-12-31']) {
    assert.equal(isCalendarDate(value), true, value)
  }
  for (const value of BAD_DATES) assert.equal(isCalendarDate(value), false, JSON.stringify(value))
})

test('pool defaults to kind=zt and limit=200', () => {
  assert.equal(target('/api/market/pool', ''), '/pool?kind=zt&limit=200')
})

test('pool forwards the whitelisted kind, date and limit', () => {
  assert.equal(target('/api/market/pool', '?kind=zb&date=2026-11-04&limit=50'), '/pool?kind=zb&limit=50&date=2026-11-04')
  assert.equal(target('/api/market/pool', '?kind=dt&limit=1'), '/pool?kind=dt&limit=1')
  assert.equal(target('/api/market/pool', '?limit=200&kind=zt'), '/pool?kind=zt&limit=200')
})

test('pool rejects any kind outside zt/zb/dt', () => {
  for (const query of ['?kind=', '?kind=ZT', '?kind=zt%20', '?kind=all', '?kind=zt%00', '?kind=zb&kind=dt']) {
    assert.equal(target('/api/market/pool', query), null, query)
  }
})

test('pool limit boundaries are 1 and 200', () => {
  assert.equal(target('/api/market/pool', '?limit=1'), '/pool?kind=zt&limit=1')
  assert.equal(target('/api/market/pool', '?limit=200'), '/pool?kind=zt&limit=200')
})

test('pool rejects malformed or out-of-range limits', () => {
  for (const query of ['?limit=0', '?limit=201', '?limit=-1', '?limit=1.5', '?limit=010', '?limit=abc', '?limit=', '?limit=1e2', '?limit=+5', '?limit=99999999999999999999']) {
    assert.equal(target('/api/market/pool', query), null, query)
  }
})

test('pool accepts real dates and rejects the rest', () => {
  assert.equal(target('/api/market/pool', '?date=2024-02-29'), '/pool?kind=zt&limit=200&date=2024-02-29')
  for (const date of BAD_DATES) assert.equal(target('/api/market/pool', `?date=${encodeURIComponent(date)}`), null, date)
})

test('pool rejects duplicate and unknown parameters', () => {
  for (const query of ['?kind=zt&kind=zb', '?date=2026-11-04&date=2026-11-05', '?limit=10&limit=20', '?x=1', '?kind=zt&x=1']) {
    assert.equal(target('/api/market/pool', query), null, query)
  }
})

test('pool-ladder takes only the optional date', () => {
  assert.equal(target('/api/market/pool-ladder', ''), '/pool/ladder')
  assert.equal(target('/api/market/pool-ladder', '?date=2026-11-04'), '/pool/ladder?date=2026-11-04')
  for (const query of ['?date=2026-02-30', '?date=2026-11-04&date=2026-11-05', '?x=1', '?date=']) {
    assert.equal(target('/api/market/pool-ladder', query), null, query)
  }
})

test('pool-history defaults to twenty trading days', () => {
  assert.equal(target('/api/market/pool-history', ''), '/pool/history?days=20')
})

test('pool-history accepts exactly 10 through 30 days', () => {
  assert.equal(target('/api/market/pool-history', '?days=10'), '/pool/history?days=10')
  assert.equal(target('/api/market/pool-history', '?days=30'), '/pool/history?days=30')
  for (const query of ['?days=9', '?days=31', '?days=0', '?days=abc', '?days=10.0', '?days=010', '?days=', '?days=10&days=20', '?x=1']) {
    assert.equal(target('/api/market/pool-history', query), null, query)
  }
})

test('pool-yesterday accepts no parameter at all', () => {
  assert.equal(target('/api/market/pool-yesterday', ''), '/pool/yesterday')
  for (const query of ['?date=2026-11-04', '?x=1', '?kind=zt']) {
    assert.equal(target('/api/market/pool-yesterday', query), null, query)
  }
})

test('pool-by-industry takes only the optional date', () => {
  assert.equal(target('/api/market/pool-by-industry', ''), '/pool/by-industry')
  assert.equal(target('/api/market/pool-by-industry', '?date=2026-11-04'), '/pool/by-industry?date=2026-11-04')
  assert.equal(target('/api/market/pool-by-industry', '?date=2026-11-4'), null)
  assert.equal(target('/api/market/pool-by-industry', '?date=2026-11-04&kind=zt'), null)
})

test('breadth-series takes only the optional date', () => {
  assert.equal(target('/api/market/breadth-series', ''), '/breadth/series')
  assert.equal(target('/api/market/breadth-series', '?date=2026-11-04'), '/breadth/series?date=2026-11-04')
  assert.equal(target('/api/market/breadth-series', '?date=2026-13-01'), null)
  assert.equal(target('/api/market/breadth-series', '?date=2026-11-04&date=2026-11-05'), null)
})

test('themes defaults to the concept board with 20 rows sorted by change', () => {
  assert.equal(target('/api/market/themes', ''), '/themes?kind=concept&limit=20&sort=change')
})

test('themes accepts only concept and its bounds', () => {
  assert.equal(target('/api/market/themes', '?kind=concept&limit=5&sort=amount'), '/themes?kind=concept&limit=5&sort=amount')
  assert.equal(target('/api/market/themes', '?limit=30&sort=change'), '/themes?kind=concept&limit=30&sort=change')
})

test('themes rejects other kinds, sorts and out-of-range limits', () => {
  for (const query of [
    '?kind=industry',
    '?kind=',
    '?kind=CONCEPT',
    '?sort=foo',
    '?sort=',
    '?sort=amount&sort=change',
    '?limit=4',
    '?limit=31',
    '?limit=020',
    '?limit=abc',
    '?x=1',
    '?kind=concept&x=1',
  ]) {
    assert.equal(target('/api/market/themes', query), null, query)
  }
})

test('injection shapes are refused before any upstream call', () => {
  const cases = [
    '/api/market/pool?kind=zt%0d%0aX-Injected:1',
    '/api/market/pool?date=2026-11-04%0a',
    '/api/market/pool?limit=10%00',
    '/api/market/pool?kind=zt%26limit=999',
    '/api/market/pool?date=../../etc/passwd',
    '/api/market/themes?kind=concept/../pool',
    '/api/market/pool-history?days=10;drop',
    '/api/market/pool-ladder?date=%2e%2e%2f',
  ]
  for (const path of cases) {
    const [pathname, query] = path.split('?')
    const found = marketRouteTable().find((entry) => entry.path === pathname)!
    assert.equal(upstreamTarget(found, new URL(`http://x${path}`)), null, path)
    assert.equal(query === undefined, false)
  }
})

test('a valid review-layer request reaches only the canonical upstream URL', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/themes', '?kind=concept&limit=10&sort=amount', hits)
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.url, `${BASE}/themes?kind=concept&limit=10&sort=amount`)
  assert.equal(hits[0]!.init?.method, 'GET')
})

test('new reads forward GET + accept only, never cookies or authorization', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/pool', '?kind=zt', hits, {
    headers: { cookie: 'dsh=SECRET', authorization: 'Bearer SECRET', 'x-forwarded-for': '1.2.3.4' },
  })
  assert.equal(response.status, 200)
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
  assert.equal(hits[0]!.init?.redirect, 'manual')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('malformed new-read queries return 400 and never reach upstream', async () => {
  const bad: [string, string][] = [
    ['/api/market/pool', '?kind=all'],
    ['/api/market/pool', '?date=2026-02-30'],
    ['/api/market/pool', '?limit=201'],
    ['/api/market/pool', '?x=1'],
    ['/api/market/pool-ladder', '?date=2026-1-1'],
    ['/api/market/pool-history', '?days=9'],
    ['/api/market/pool-history', '?days=31'],
    ['/api/market/pool-yesterday', '?date=2026-11-04'],
    ['/api/market/pool-by-industry', '?x=1'],
    ['/api/market/breadth-series', '?date=%2e%2e'],
    ['/api/market/themes', '?kind=industry'],
    ['/api/market/themes', '?sort=foo'],
  ]
  for (const [path, query] of bad) {
    const hits: Hit[] = []
    const response = await call(path, query, hits)
    assert.equal(response.status, 400, `${path}${query}`)
    assert.equal(hits.length, 0, `${path}${query}`)
    const body = await response.json() as { ok: boolean; error: { code: string } }
    assert.equal(body.ok, false)
    assert.equal(body.error.code, 'bad_request')
  }
})

test('an unreachable engine still returns the contract 502 for a new read', async () => {
  const response = await handleMarketRequest(route('/api/market/pool'), 'http://127.0.0.1:1', new Request('http://localhost/api/market/pool'), {
    fetchImpl: async () => { throw new TypeError('fetch failed') },
  })
  assert.equal(response.status, 502)
  assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'engine_unreachable')
})

test('new reads keep the existing cache policy (no cache-control header)', async () => {
  for (const [path, query] of [['/api/market/pool', ''], ['/api/market/breadth-series', ''], ['/api/market/themes', '']]) {
    const response = await call(path, query)
    assert.equal(response.status, 200)
    assert.equal(response.headers.get('cache-control'), null, path)
  }
})

test('a POST is never proxied by a new read route', async () => {
  const hits: Hit[] = []
  const response = await call('/api/market/pool', '', hits, { method: 'POST', body: 'x' })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})
