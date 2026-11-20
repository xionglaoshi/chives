import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  HUB_SPARK_MAX_CODES,
  handleHubRequest,
  hubRouteTable,
  hubUpstreamTarget,
  normalizeSparkCodes,
} from '../src/hubProxy.ts'

const BASE = 'http://127.0.0.1:8867'
const SPARK = '/api/hub/spark'

interface Hit {
  url: string
  init: RequestInit | undefined
}

function route(path: string) {
  const found = hubRouteTable().find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function fakeFetch(hits: Hit[], body: unknown = { ok: true, sparks: {}, missing: [] }, status = 200): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } })
  }
}

async function get(query: string, hits: Hit[], init: RequestInit = {}, body?: unknown) {
  return await handleHubRequest(route(SPARK), BASE, new Request(`http://localhost${SPARK}${query}`, init), {
    fetchImpl: fakeFetch(hits, body),
  })
}

function codes(count: number): string {
  return Array.from({ length: count }, (_, index) => `${600000 + index}.SH`).join(',')
}

test('normalizeSparkCodes accepts canonical codes, dedupes and preserves order', () => {
  assert.deepEqual(normalizeSparkCodes('600519.SH,300750.SZ,600519.SH'), ['600519.SH', '300750.SZ'])
  assert.deepEqual(normalizeSparkCodes('600519.SH'), ['600519.SH'])
})

test('normalizeSparkCodes refuses non-canonical shapes', () => {
  for (const raw of [
    null,
    '',
    '600519',
    '600519.HK',
    '600519.sh',
    '600519.SH,',
    ' 600519.SH',
    '600519.SH ',
    '600519.SH\n',
    '600519.SH%0d%0a',
    '../etc/passwd',
    'abcdef.SH',
  ]) {
    assert.equal(normalizeSparkCodes(raw), null, String(raw))
  }
})

test('the spark route is a single GET-only entry in the fixed table', () => {
  const spark = route(SPARK)
  assert.deepEqual([...spark.methods], ['GET'])
  assert.equal(hubRouteTable().length, 8)
  assert.equal(hubRouteTable({ review: true }).length, 19)
  assert.equal(hubRouteTable().filter((entry) => entry.path === SPARK).length, 1)
  assert.ok(!hubRouteTable().some((entry) => /portfolio\/|spark\/|\*/.test(entry.path)))
})

test('valid codes are rebuilt canonically and deduped before forwarding', () => {
  assert.equal(
    hubUpstreamTarget(route(SPARK), new URL(`http://x${SPARK}?codes=600519.SH,300750.SZ,600519.SH`)),
    `/spark?codes=${encodeURIComponent('600519.SH,300750.SZ')}`,
  )
})

test('a valid call forwards once, drops cookies/auth and sets no-store', async () => {
  const hits: Hit[] = []
  const response = await get('?codes=600519.SH,300750.SZ', hits, {
    headers: { cookie: 'dsh=SECRET', authorization: 'Bearer X' },
  })
  assert.equal(response.status, 200)
  assert.match(response.headers.get('cache-control') ?? '', /no-store/)
  assert.equal(response.headers.get('set-cookie'), null)
  assert.equal(hits.length, 1)
  assert.equal(hits[0].url, `${BASE}/spark?codes=${encodeURIComponent('600519.SH,300750.SZ')}`)
  assert.equal((hits[0].init?.headers as Record<string, string>).cookie, undefined)
  assert.equal((hits[0].init?.headers as Record<string, string>).authorization, undefined)
})

test('30 codes are accepted, 31 never reach the hub', async () => {
  const hits: Hit[] = []
  assert.equal((await get(`?codes=${codes(HUB_SPARK_MAX_CODES)}`, hits)).status, 200)
  assert.equal(hits.length, 1)
  hits.length = 0
  assert.equal((await get(`?codes=${codes(HUB_SPARK_MAX_CODES + 1)}`, hits)).status, 400)
  assert.equal(hits.length, 0)
})

test('bad queries are rejected locally', async () => {
  for (const query of [
    '',
    '?codes=',
    '?codes=600519',
    '?codes=600519.HK',
    '?codes=abc.SH',
    '?codes=600519.SH,',
    `?codes=${codes(31)}`,
    '?codes=600519.SH&x=1',
    '?x=1',
    '?codes=600519.SH&codes=300750.SZ',
  ]) {
    const hits: Hit[] = []
    assert.equal((await get(query, hits)).status, 400, query)
    assert.equal(hits.length, 0, query)
  }
})

test('POST is not forwarded for the read-only spark route', async () => {
  const hits: Hit[] = []
  const response = await get('?codes=600519.SH', hits, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1' },
    body: '{}',
  })
  assert.notEqual(response.status, 200)
  assert.equal(hits.length, 0)
})

test('unreachable hub returns the exact contract body', async () => {
  const response = await handleHubRequest(
    route(SPARK),
    'http://127.0.0.1:1',
    new Request(`http://localhost${SPARK}?codes=600519.SH`),
    {},
  )
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_unreachable' } })
})

test('hub errors and oversized bodies are not passed through', async () => {
  const hits: Hit[] = []
  const errors = await handleHubRequest(route(SPARK), BASE, new Request(`http://localhost${SPARK}?codes=600519.SH`), {
    fetchImpl: fakeFetch(hits, { ok: false }, 500),
  })
  assert.equal(errors.status, 502)
  const huge = await handleHubRequest(route(SPARK), BASE, new Request(`http://localhost${SPARK}?codes=600519.SH`), {
    fetchImpl: fakeFetch(hits, { ok: true, pad: 'x'.repeat(64) }),
    maxBytes: 16,
  })
  assert.equal(huge.status, 502)
  assert.match(await huge.text(), /response_too_large/)
})
