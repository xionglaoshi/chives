import assert from 'node:assert/strict'
import http from 'node:http'
import { after, test } from 'node:test'
import { apply } from '../src/index.ts'

interface RouteSpec {
  path: string
  methods: string[]
  fetch: (request: Request) => Promise<Response>
}

const seen: { url: string; headers: http.IncomingHttpHeaders }[] = []
let hang = false

const engine = http.createServer((request, response) => {
  seen.push({ url: request.url ?? '', headers: request.headers })
  if (hang) return
  response.writeHead(200, {
    'content-type': 'application/json',
    'set-cookie': 'engine=1',
    'x-engine-secret': 'leak',
  })
  response.end(JSON.stringify({ url: request.url }))
})

await new Promise<void>((resolve) => engine.listen(0, '127.0.0.1', resolve))
const address = engine.address()
const port = typeof address === 'object' && address !== null ? address.port : 0
process.env.WATCH_PANEL_ENGINE = `http://127.0.0.1:${port}`

const specs: RouteSpec[] = []
const ctx = {
  effect: (fn: () => unknown) => {
    fn()
    return () => {}
  },
  connection: { fetch: { register: (spec: RouteSpec) => {
    specs.push(spec)
    return () => {}
  } } },
}
apply(ctx as never)

function route(path: string): RouteSpec {
  const spec = specs.find((item) => item.path === `/api/watch${path}`)
  assert.ok(spec, `missing route ${path}`)
  return spec
}

function call(path: string, query = '', headers: Record<string, string> = {}): Promise<Response> {
  return route(path).fetch(new Request(`http://localhost:3081/api/watch${path}${query}`, { headers }))
}

after(() => {
  engine.closeAllConnections()
  engine.close()
})

test('registers the watch routes plus the market proxy', () => {
  assert.deepEqual(specs.filter((spec) => spec.path.startsWith('/api/watch/')).map((spec) => spec.path).sort(), [
    '/api/watch/alerts',
    '/api/watch/analyses',
    '/api/watch/analysis',
    '/api/watch/health',
    '/api/watch/rules',
    '/api/watch/rules/history',
    '/api/watch/state',
  ])
  assert.ok(specs.some((spec) => spec.path === '/api/market/overview'))
  assert.ok(specs.filter((spec) => spec.path.startsWith('/api/watch/')).every((spec) => JSON.stringify(spec.methods) === '["GET"]'))
  assert.ok(specs.some((spec) => spec.path === '/api/hub/signal-action' && JSON.stringify(spec.methods) === '["POST"]'))
})

test('proxies health and keeps the status and JSON body', async () => {
  const response = await call('/health')
  assert.equal(response.status, 200)
  assert.equal((await response.json() as { url: string }).url, '/health')
  assert.match(response.headers.get('content-type') ?? '', /application\/json/)
})

test('forwards validated alert query parameters', async () => {
  const response = await call('/alerts', '?after_id=5&limit=10')
  assert.equal(response.status, 200)
  const forwarded = new URL(`http://x${(await response.json() as { url: string }).url}`)
  assert.equal(forwarded.pathname, '/alerts')
  assert.equal(forwarded.searchParams.get('after_id'), '5')
  assert.equal(forwarded.searchParams.get('limit'), '10')
})

test('forwards the rule history limit and validates it', async () => {
  const response = await call('/rules/history', '?limit=10')
  assert.equal(response.status, 200)
  const forwarded = new URL(`http://x${(await response.json() as { url: string }).url}`)
  assert.equal(forwarded.pathname, '/rules/history')
  assert.equal(forwarded.searchParams.get('limit'), '10')
  for (const query of ['?limit=-1', '?limit=501', '?limit=1.5', '?foo=1']) {
    assert.equal((await call('/rules/history', query)).status, 400, query)
  }
})

test('rejects bad queries with 400 and never reaches the engine', async () => {
  const before = seen.length
  for (const query of [
    '?after_id=-1',
    '?after_id=abc',
    '?after_id=1.5',
    '?limit=0',
    '?limit=501',
    '?limit=10;x',
    '?after_id=1&after_id=2',
    '?limit=1&limit=2',
    '?foo=1',
  ]) {
    const response = await call('/alerts', query)
    assert.equal(response.status, 400, query)
    assert.equal((await response.json() as { error: string }).error, 'bad_request')
  }
  assert.equal((await call('/health', '?x=1')).status, 400)
  assert.equal(seen.length, before)
})

test('drops browser credentials and never leaks engine headers', async () => {
  const response = await call('/state', '', {
    cookie: 'dsh=secret',
    authorization: 'Bearer abc',
    'x-dsh-token': 'zzz',
  })
  const last = seen[seen.length - 1]
  assert.ok(last)
  assert.equal(last.headers.cookie, undefined)
  assert.equal(last.headers.authorization, undefined)
  assert.equal(last.headers['x-dsh-token'], undefined)
  assert.equal(response.headers.get('set-cookie'), null)
  assert.equal(response.headers.get('x-engine-secret'), null)
})

test('a hanging engine becomes a 502 within the timeout', async () => {
  hang = true
  const started = Date.now()
  const response = await call('/state')
  const elapsed = Date.now() - started
  hang = false
  assert.equal(response.status, 502)
  assert.ok(elapsed < 5000, `took ${elapsed}ms`)
  assert.equal((await response.json() as { error: string }).error, 'engine_unreachable')
})

test('a refused connection becomes a 502', async () => {
  engine.closeAllConnections()
  await new Promise<void>((resolve) => engine.close(() => resolve()))
  const response = await call('/health')
  assert.equal(response.status, 502)
  assert.equal((await response.json() as { error: string }).error, 'engine_unreachable')
})

test('refuses a non-loopback engine address at load time', () => {
  process.env.WATCH_PANEL_ENGINE = 'http://10.1.2.3:8865'
  try {
    assert.throws(() => apply(ctx as never), /loopback/)
  } finally {
    process.env.WATCH_PANEL_ENGINE = `http://127.0.0.1:${port}`
  }
})
