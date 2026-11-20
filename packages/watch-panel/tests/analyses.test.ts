import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { after, test } from 'node:test'
import { apply } from '../src/index.ts'

interface RouteSpec {
  path: string
  methods: string[]
  fetch: (request: Request) => Promise<Response>
}

let engineHits = 0
const engine = http.createServer((_request, response) => {
  engineHits += 1
  response.writeHead(200, { 'content-type': 'application/json' })
  response.end('{}')
})
await new Promise<void>((resolve) => engine.listen(0, '127.0.0.1', resolve))
const address = engine.address()
const port = typeof address === 'object' && address !== null ? address.port : 0
process.env.WATCH_PANEL_ENGINE = `http://127.0.0.1:${port}`

const dir = fs.mkdtempSync(path.join(import.meta.dirname, 'tmp-analyses-'))
const record = (id: number, status: string, extra: Record<string, unknown> = {}): string =>
  JSON.stringify({ alert_id: id, code: '002553.SZ', rule_id: 'pct_up_3', status, ...extra })
fs.writeFileSync(path.join(dir, 'analyses.jsonl'), [
  record(1, 'skipped', { reason: 'cooldown' }),
  'THIS IS NOT JSON',
  record(2, 'done', { session_id: 's2' }),
  record(3, 'failed'),
  record(2, 'skipped', { reason: 'daily_limit' }),
  '{"truncated json',
  record(5, 'done'),
  record(4, 'timeout'),
  '',
].join('\n'))
fs.writeFileSync(path.join(dir, 'analysis-3.md'), '# 告警分析 3\n\n正文：<script>alert(1)</script>\n')
fs.writeFileSync(path.join(dir, 'analysis-9.md'), 'x'.repeat(300 * 1024))
process.env.WATCH_PANEL_ANALYSES_DIR = dir

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

function call(path: string, query = ''): Promise<Response> {
  return route(path).fetch(new Request(`http://localhost:3081/api/watch${path}${query}`))
}

after(() => {
  engine.close()
  fs.rmSync(dir, { recursive: true, force: true })
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
  const hub = specs.filter((spec) => spec.path.startsWith('/api/hub/')).map((spec) => spec.path).sort()
  assert.deepEqual(hub, [
    '/api/hub/plan-action',
    '/api/hub/plans',
    '/api/hub/portfolio-history',
    '/api/hub/portfolio-overview',
    '/api/hub/signal',
    '/api/hub/signal-action',
    '/api/hub/signals',
    '/api/hub/spark',
  ])
  assert.deepEqual(specs.find((spec) => spec.path === '/api/hub/signal-action')?.methods, ['POST'])
  assert.deepEqual(specs.find((spec) => spec.path === '/api/hub/plan-action')?.methods, ['POST'])
})

test('analyses: newest first, bad lines skipped, the last record per alert wins', async () => {
  const response = await call('/analyses')
  assert.equal(response.status, 200)
  const body = await response.json() as { records: { alert_id: number; status: string }[]; count: number }
  assert.deepEqual(body.records.map((row) => row.alert_id), [5, 4, 3, 2, 1])
  assert.equal(body.count, 5)
  assert.equal(body.records.find((row) => row.alert_id === 2)?.status, 'skipped')
  assert.match(response.headers.get('content-type') ?? '', /application\/json/)
})

test('analyses: limit and default are enforced', async () => {
  const limited = await call('/analyses', '?limit=2')
  const body = await limited.json() as { records: { alert_id: number }[]; count: number }
  assert.deepEqual(body.records.map((row) => row.alert_id), [5, 4])
  assert.equal(body.count, 2)
  const defaults = await call('/analyses')
  assert.equal((await defaults.json() as { count: number }).count, 5)
})

test('analyses: invalid query strings are 400', async () => {
  for (const query of ['?limit=0', '?limit=201', '?limit=abc', '?limit=1.5', '?limit=-1', '?foo=1', '?limit=1&limit=2', '?limit=']) {
    const response = await call('/analyses', query)
    assert.equal(response.status, 400, query)
    assert.equal((await response.json() as { error: string }).error, 'bad_request')
  }
})

test('analysis: returns markdown as data and flags no truncation', async () => {
  const response = await call('/analysis', '?id=3')
  assert.equal(response.status, 200)
  const body = await response.json() as { id: number; markdown: string; truncated: boolean }
  assert.equal(body.id, 3)
  assert.ok(body.markdown.includes('<script>alert(1)</script>'))
  assert.equal(body.truncated, false)
})

test('analysis: content over 200 KB is capped and flagged', async () => {
  const response = await call('/analysis', '?id=9')
  assert.equal(response.status, 200)
  const body = await response.json() as { markdown: string; truncated: boolean }
  assert.equal(body.truncated, true)
  assert.ok(Buffer.byteLength(body.markdown) <= 200 * 1024 + 4, `got ${Buffer.byteLength(body.markdown)} bytes`)
})

test('analysis: missing file is 404 not_found', async () => {
  const response = await call('/analysis', '?id=77')
  assert.equal(response.status, 404)
  assert.equal((await response.json() as { error: string }).error, 'not_found')
})

test('analysis: illegal ids and path traversal attempts are 400', async () => {
  for (const query of ['?id=abc', '?id=0', '?id=-1', '?id=3.5', '?id=../analyses', '?id=3/../../x', '?id=%2e%2e%2fanalyses', '?id=', '', '?id=01', '?id=12345678901', '?id=3&id=4', '?id=3&x=1']) {
    const response = await call('/analysis', query)
    assert.equal(response.status, 400, query || '(no id)')
    assert.equal((await response.json() as { error: string }).error, 'bad_request')
  }
})

test('analysis routes never touch the engine', () => {
  assert.equal(engineHits, 0)
})

test('a relative WATCH_PANEL_ANALYSES_DIR refuses to load', () => {
  process.env.WATCH_PANEL_ANALYSES_DIR = 'relative/dir'
  try {
    assert.throws(() => apply(ctx as never), /absolute path/)
  } finally {
    process.env.WATCH_PANEL_ANALYSES_DIR = dir
  }
})
