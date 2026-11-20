import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  HUB_MAX_ID,
  REVIEW_KINDS,
  SETTING_KEYS,
  handleHubRequest,
  hubRouteTable,
  hubUpstreamTarget,
  isCalendarDate,
  validateCardAction,
  validateDisciplineAction,
  validateSettingAction,
} from '../src/hubProxy.ts'

interface Hit {
  url: string
  init: RequestInit | undefined
}

const BASE = 'http://127.0.0.1:8867'

function route(path: string) {
  const found = hubRouteTable({ review: true }).find((entry) => entry.path === path)
  assert.ok(found, path)
  return found
}

function fakeFetch(hits: Hit[], status = 200, body = '{"ok":true}'): typeof fetch {
  return async (input, init) => {
    hits.push({ url: String(input), init })
    return new Response(body, { status, headers: { 'content-type': 'application/json', 'set-cookie': 'a=1' } })
  }
}

function get(path: string, query = '', hits: Hit[] = [], init?: RequestInit) {
  return handleHubRequest(route(path), BASE, new Request(`http://localhost${path}${query}`, init), { fetchImpl: fakeFetch(hits) })
}

interface PostOptions {
  headers?: Record<string, string>
  method?: string
  status?: number
  response?: unknown
}

function post(path: string, body: unknown, hits: Hit[] = [], options: PostOptions = {}) {
  const raw = typeof body === 'string' ? body : JSON.stringify(body)
  return handleHubRequest(route(path), BASE, new Request(`http://localhost${path}`, {
    method: options.method ?? 'POST',
    headers: {
      'content-type': 'application/json',
      'x-chives-action': '1',
      ...options.headers,
    },
    body: options.method === 'GET' ? undefined : raw,
  }), { fetchImpl: fakeFetch(hits, options.status ?? 200, JSON.stringify(options.response ?? { ok: true })) })
}

function target(path: string, query: string): string | null {
  return hubUpstreamTarget(route(path), new URL(`http://x${path}${query}`))
}

test('the review layer adds exactly eleven fixed routes', () => {
  const added = hubRouteTable({ review: true }).filter((entry) => [
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
  ].includes(entry.path))
  assert.equal(added.length, 11)
  assert.deepEqual(added.filter((entry) => entry.methods.includes('POST')).map((entry) => entry.path), [
    '/api/hub/setting-action',
    '/api/hub/discipline-action',
    '/api/hub/card-action',
  ])
})

test('the forbidden hub proxies are absent from the route table', () => {
  const paths = hubRouteTable({ review: true }).map((entry) => entry.path)
  for (const banned of [
    '/api/hub/review-data',
    '/api/hub/reviews/save',
    '/api/hub/cards/create',
    '/api/hub/settings/per_trade_risk_pct/suggest',
    '/api/hub/triggers',
    '/api/hub/triggers/1/context',
    '/api/hub/triggers/1/judgement',
    '/api/hub/*',
    '/api/hub/portfolio/*',
  ]) {
    assert.equal(paths.includes(banned), false, banned)
  }
})

test('an unknown route kind is denied locally without reaching the hub', async () => {
  const hits: Hit[] = []
  const synthetic = { path: '/api/hub/review-data', kind: 'review-data' as never, methods: ['GET'] as const }
  const response = await handleHubRequest(synthetic, BASE, new Request('http://localhost/api/hub/review-data'), { fetchImpl: fakeFetch(hits) })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('settings and discipline take no query at all', () => {
  assert.equal(target('/api/hub/settings', ''), '/settings')
  assert.equal(target('/api/hub/discipline', ''), '/discipline')
  for (const path of ['/api/hub/settings', '/api/hub/discipline']) {
    for (const query of ['?x=1', '?key=theme_cap_pct', '?limit=1']) {
      assert.equal(target(path, query), null, `${path}${query}`)
    }
  }
})

test('reviews defaults to limit=20 with no kind filter', () => {
  assert.equal(target('/api/hub/reviews', ''), '/reviews?limit=20')
})

test('reviews accepts limits 1 through 50 and both kinds', () => {
  assert.equal(target('/api/hub/reviews', '?limit=1'), '/reviews?limit=1')
  assert.equal(target('/api/hub/reviews', '?limit=50'), '/reviews?limit=50')
  for (const kind of REVIEW_KINDS) {
    assert.equal(target('/api/hub/reviews', `?limit=10&kind=${kind}`), `/reviews?limit=10&kind=${kind}`)
  }
})

test('reviews rejects other limits, kinds and duplicates', () => {
  for (const query of [
    '?limit=0',
    '?limit=51',
    '?limit=05',
    '?limit=abc',
    '?limit=',
    '?kind=',
    '?kind=noon',
    '?kind=EVENING',
    '?limit=10&limit=20',
    '?kind=evening&kind=premarket',
    '?x=1',
    '?limit=10&x=1',
  ]) {
    assert.equal(target('/api/hub/reviews', query), null, query)
  }
})

test('review maps a real date and kind onto the upstream path', () => {
  assert.equal(target('/api/hub/review', '?date=2026-11-04&kind=evening'), '/reviews/2026-11-04?kind=evening')
  assert.equal(target('/api/hub/review', '?kind=premarket&date=2024-02-29'), '/reviews/2024-02-29?kind=premarket')
})

test('review requires both date and kind', () => {
  assert.equal(target('/api/hub/review', ''), null)
  assert.equal(target('/api/hub/review', '?date=2026-11-04'), null)
  assert.equal(target('/api/hub/review', '?kind=evening'), null)
  assert.equal(target('/api/hub/review', '?date=&kind=evening'), null)
  assert.equal(target('/api/hub/review', '?date=2026-11-04&kind='), null)
})

test('review rejects malformed and path-traversal dates', () => {
  for (const date of ['2026-11-4', '2026-02-30', '2026-11-04%0a', '../2026-11-04', '2026-11-04/../x', '2026-11-04%00']) {
    assert.equal(target('/api/hub/review', `?date=${encodeURIComponent(date)}&kind=evening`), null, date)
  }
  assert.equal(target('/api/hub/review', '?date=2026-11-04&kind=evening&x=1'), null)
  assert.equal(target('/api/hub/review', '?date=2026-11-04&date=2026-11-05&kind=evening'), null)
})

test('cards forwards only the parameters the browser sent', () => {
  assert.equal(target('/api/hub/cards', ''), '/cards')
  assert.equal(target('/api/hub/cards', '?date=2026-11-04'), '/cards?date=2026-11-04')
})

test('cards forwards the four statuses and an optional date', () => {
  for (const status of ['proposed', 'active', 'closed', 'all']) {
    assert.equal(target('/api/hub/cards', `?status=${status}`), `/cards?status=${status}`)
  }
  assert.equal(target('/api/hub/cards', '?status=active&date=2026-11-04'), '/cards?status=active&date=2026-11-04')
})

test('cards rejects other statuses, bad dates and extra parameters', () => {
  for (const query of ['?status=', '?status=pending', '?status=ACTIVE', '?date=2026-13-01', '?status=active&date=bad', '?x=1', '?status=active&x=1', '?status=active&status=all']) {
    assert.equal(target('/api/hub/cards', query), null, query)
  }
})

test('card maps a canonical id onto the upstream path', () => {
  assert.equal(target('/api/hub/card', '?id=1'), '/cards/1')
  assert.equal(target('/api/hub/card', `?id=${HUB_MAX_ID}`), `/cards/${HUB_MAX_ID}`)
})

test('card rejects zero, negative, fractional, oversized and duplicated ids', () => {
  for (const query of ['', '?id=', '?id=0', '?id=-1', '?id=1.5', '?id=01', '?id=abc', '?id=1&id=2', `?id=${HUB_MAX_ID + 1}`, '?x=1']) {
    assert.equal(target('/api/hub/card', query), null, query)
  }
})

test('candidates-stats defaults to twenty days', () => {
  assert.equal(target('/api/hub/candidates-stats', ''), '/candidates/stats?days=20')
})

test('candidates-stats accepts 5 through 60 days', () => {
  assert.equal(target('/api/hub/candidates-stats', '?days=5'), '/candidates/stats?days=5')
  assert.equal(target('/api/hub/candidates-stats', '?days=60'), '/candidates/stats?days=60')
})

test('candidates-stats rejects out-of-range and malformed days', () => {
  for (const query of ['?days=4', '?days=61', '?days=0', '?days=020', '?days=5.0', '?days=abc', '?days=', '?days=5&days=10', '?x=1']) {
    assert.equal(target('/api/hub/candidates-stats', query), null, query)
  }
})

test('guidance takes only an optional date', () => {
  assert.equal(target('/api/hub/guidance', ''), '/guidance')
  assert.equal(target('/api/hub/guidance', '?date=2026-11-04'), '/guidance?date=2026-11-04')
})

test('guidance rejects malformed dates and extra parameters', () => {
  for (const query of ['?date=2026-11-4', '?date=2026-02-30', '?date=2026-11-04&x=1', '?date=2026-11-04&date=2026-11-05', '?x=1']) {
    assert.equal(target('/api/hub/guidance', query), null, query)
  }
  assert.equal(isCalendarDate('2024-02-29'), true)
})

test('every new read rejects bad queries with 400 before the hub', async () => {
  const bad: [string, string][] = [
    ['/api/hub/settings', '?x=1'],
    ['/api/hub/discipline', '?x=1'],
    ['/api/hub/reviews', '?limit=51'],
    ['/api/hub/reviews', '?kind=noon'],
    ['/api/hub/review', '?date=2026-11-04'],
    ['/api/hub/review', '?date=2026-02-30&kind=evening'],
    ['/api/hub/cards', '?status=pending'],
    ['/api/hub/card', '?id=0'],
    ['/api/hub/candidates-stats', '?days=4'],
    ['/api/hub/guidance', '?date=2026-11-4'],
  ]
  for (const [path, query] of bad) {
    const hits: Hit[] = []
    const response = await get(path, query, hits)
    assert.equal(response.status, 400, `${path}${query}`)
    assert.equal(hits.length, 0, `${path}${query}`)
    assert.equal(((await response.json()) as { error: { code: string } }).error.code, 'bad_request')
  }
})

test('an unreachable hub returns the exact contract body for a new read', async () => {
  const response = await handleHubRequest(route('/api/hub/settings'), 'http://127.0.0.1:1', new Request('http://localhost/api/hub/settings'), {})
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_unreachable' } })
})

test('new reads never forward cookies, authorization or other browser headers', async () => {
  const hits: Hit[] = []
  const response = await get('/api/hub/settings', '', hits, {
    headers: { cookie: 'dsh=SECRET', authorization: 'Bearer SECRET', 'user-agent': 'browser' },
  })
  assert.equal(response.status, 200)
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json' })
  assert.equal(hits[0]!.init?.redirect, 'manual')
  assert.equal(response.headers.get('set-cookie'), null)
})

test('the eight review-layer reads answer with no-store', async () => {
  const calls: [string, string][] = [
    ['/api/hub/settings', ''],
    ['/api/hub/discipline', ''],
    ['/api/hub/reviews', ''],
    ['/api/hub/review', '?date=2026-11-04&kind=evening'],
    ['/api/hub/cards', ''],
    ['/api/hub/card', '?id=7'],
    ['/api/hub/candidates-stats', ''],
    ['/api/hub/guidance', ''],
  ]
  for (const [path, query] of calls) {
    const response = await get(path, query)
    assert.equal(response.status, 200, path)
    assert.match(response.headers.get('cache-control') ?? '', /no-store/, path)
  }
})

test('no-store survives 400 and 502 responses on the private reads', async () => {
  for (const [path, query] of [
    ['/api/hub/settings', '?x=1'],
    ['/api/hub/reviews', '?limit=0'],
    ['/api/hub/review', '?date=2026-11-04'],
    ['/api/hub/cards', '?status=pending'],
    ['/api/hub/card', '?id=0'],
    ['/api/hub/candidates-stats', '?days=61'],
    ['/api/hub/guidance', '?date=bad'],
  ]) {
    const response = await get(path, query)
    assert.equal(response.status, 400, `${path}${query}`)
    assert.match(response.headers.get('cache-control') ?? '', /no-store/, `${path}${query}`)
  }
  const unreachable = await handleHubRequest(route('/api/hub/settings'), 'http://127.0.0.1:1', new Request('http://localhost/api/hub/settings'), {})
  assert.equal(unreachable.status, 502)
  assert.match(unreachable.headers.get('cache-control') ?? '', /no-store/)
})

test('a setting adopt keeps the key in the path, never in the body', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/setting-action', { key: 'theme_cap_pct', action: 'adopt' }, hits)
  assert.equal(response.status, 200)
  assert.equal(hits[0]!.url, `${BASE}/settings/theme_cap_pct/action`)
  assert.equal(hits[0]!.init?.method, 'POST')
  assert.equal(hits[0]!.init?.body, '{"action":"adopt"}')
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json', 'content-type': 'application/json' })
})

test('a setting set requires a finite numeric value and rebuilds the body', async () => {
  const hits: Hit[] = []
  await post('/api/hub/setting-action', { key: 'per_trade_risk_pct', action: 'set', value: 1.5 }, hits)
  assert.equal(hits[0]!.url, `${BASE}/settings/per_trade_risk_pct/action`)
  assert.equal(hits[0]!.init?.body, '{"action":"set","value":1.5}')
})

test('all eleven setting keys are accepted', () => {
  assert.equal(SETTING_KEYS.length, 11)
  for (const key of SETTING_KEYS) {
    assert.deepEqual(validateSettingAction({ key, action: 'clear' }), { target: `/settings/${key}/action`, body: { action: 'clear' } })
  }
})

test('setting keys outside the contract are rejected', () => {
  for (const key of ['', 'theme_cap', 'THEME_CAP_PCT', '../theme_cap_pct', 'theme_cap_pct%00', 'theme_cap_pct\n', 'a'.repeat(120)]) {
    assert.equal(validateSettingAction({ key, action: 'clear' }), null, JSON.stringify(key))
  }
})

test('setting set rejects a missing, non-numeric or non-finite value', () => {
  for (const body of [
    { key: 'theme_cap_pct', action: 'set' },
    { key: 'theme_cap_pct', action: 'set', value: '5' },
    { key: 'theme_cap_pct', action: 'set', value: null },
    { key: 'theme_cap_pct', action: 'set', value: true },
    { key: 'theme_cap_pct', action: 'set', value: [1] },
  ]) {
    assert.equal(validateSettingAction(body), null, JSON.stringify(body))
  }
})

test('setting actions other than set must not carry a value', () => {
  for (const action of ['adopt', 'clear', 'dismiss']) {
    assert.equal(validateSettingAction({ key: 'theme_cap_pct', action, value: 5 }), null, action)
    assert.deepEqual(validateSettingAction({ key: 'theme_cap_pct', action }), { target: '/settings/theme_cap_pct/action', body: { action } })
  }
})

test('setting writes reject extra fields and bad actions', () => {
  for (const body of [
    { key: 'theme_cap_pct', action: 'clear', extra: 1 },
    { key: 'theme_cap_pct', action: 'remove' },
    { key: 'theme_cap_pct' },
    { action: 'clear' },
    [],
    null,
  ]) {
    assert.equal(validateSettingAction(body), null, JSON.stringify(body))
  }
})

test('loss-streak actions add and reset are canonical', async () => {
  for (const action of ['add', 'reset']) {
    const hits: Hit[] = []
    await post('/api/hub/discipline-action', { kind: 'loss-streak', action }, hits)
    assert.equal(hits[0]!.url, `${BASE}/discipline/loss-streak`)
    assert.equal(hits[0]!.init?.body, JSON.stringify({ action }))
  }
})

test('loss-streak rejects bad actions, missing fields and extra fields', () => {
  for (const body of [
    { kind: 'loss-streak' },
    { kind: 'loss-streak', action: 'clear' },
    { kind: 'loss-streak', action: 'ADD' },
    { kind: 'loss-streak', action: 'add', note: 'x' },
    { kind: 'loss-streak', action: 'add', slot: 'pre' },
  ]) {
    assert.equal(validateDisciplineAction(body), null, JSON.stringify(body))
  }
})

test('mood writes without a note forward only slot and level', async () => {
  const hits: Hit[] = []
  await post('/api/hub/discipline-action', { kind: 'mood', slot: 'pre', level: 'calm' }, hits)
  assert.equal(hits[0]!.url, `${BASE}/discipline/mood`)
  assert.equal(hits[0]!.init?.body, '{"slot":"pre","level":"calm"}')
})

test('a sixty-character mood note is accepted and forwarded', async () => {
  const note = '亏'.repeat(60)
  const hits: Hit[] = []
  await post('/api/hub/discipline-action', { kind: 'mood', slot: 'mid', level: 'volatile', note }, hits)
  assert.equal(hits[0]!.init?.body, JSON.stringify({ slot: 'mid', level: 'volatile', note }))
})

test('a mood note over sixty characters is rejected', () => {
  assert.equal(validateDisciplineAction({ kind: 'mood', slot: 'post', level: 'unfit', note: 'x'.repeat(61) }), null)
  assert.equal(validateDisciplineAction({ kind: 'mood', slot: 'post', level: 'unfit', note: 60 }), null)
})

test('mood rejects bad slots, levels and extra fields', () => {
  for (const body of [
    { kind: 'mood', slot: 'noon', level: 'calm' },
    { kind: 'mood', slot: 'pre', level: 'happy' },
    { kind: 'mood', slot: 'pre' },
    { kind: 'mood', level: 'calm' },
    { kind: 'mood', slot: 'PRE', level: 'calm' },
    { kind: 'mood', slot: 'pre', level: 'calm', action: 'add' },
    { kind: 'mood', slot: 'pre', level: 'calm', extra: 1 },
  ]) {
    assert.equal(validateDisciplineAction(body), null, JSON.stringify(body))
  }
})

test('card confirm and cancel are canonical', async () => {
  for (const action of ['confirm', 'cancel']) {
    const hits: Hit[] = []
    await post('/api/hub/card-action', { id: 7, action }, hits)
    assert.equal(hits[0]!.url, `${BASE}/cards/7/action`)
    assert.equal(hits[0]!.init?.body, JSON.stringify({ action }))
  }
})

test('card tighten_stop requires a finite positive stop', async () => {
  const hits: Hit[] = []
  await post('/api/hub/card-action', { id: 7, action: 'tighten_stop', stop: 12.34 }, hits)
  assert.equal(hits[0]!.init?.body, '{"action":"tighten_stop","stop":12.34}')
  for (const stop of [0, -1, Number.POSITIVE_INFINITY, Number.NaN]) assert.equal(validateCardAction({ id: 7, action: 'tighten_stop', stop }), null, String(stop))
  for (const stop of [undefined, null, '12', true]) assert.equal(validateCardAction({ id: 7, action: 'tighten_stop', stop }), null, String(stop))
})

test('card set_state only allows abandon and exit', () => {
  for (const state of ['abandon', 'exit']) {
    assert.deepEqual(validateCardAction({ id: 7, action: 'set_state', state }), { target: '/cards/7/action', body: { action: 'set_state', state } })
  }
  for (const state of ['execute', 'observe', 'ABANDON', '', null]) {
    assert.equal(validateCardAction({ id: 7, action: 'set_state', state }), null, String(state))
  }
})

test('card actions reject stop/state on the wrong action and mixed fields', () => {
  for (const body of [
    { id: 7, action: 'confirm', stop: 10 },
    { id: 7, action: 'cancel', state: 'exit' },
    { id: 7, action: 'tighten_stop', stop: 10, state: 'exit' },
    { id: 7, action: 'set_state', state: 'exit', stop: 10 },
    { id: 7, action: 'tighten_stop' },
    { id: 7, action: 'set_state' },
    { id: 7, action: 'remove' },
    { id: 7, action: 'CONFIRM' },
  ]) {
    assert.equal(validateCardAction(body), null, JSON.stringify(body))
  }
})

test('card ids follow the same canonical positive-integer rule', () => {
  for (const id of [0, -1, 1.5, '7', null, HUB_MAX_ID + 1, Number.MAX_SAFE_INTEGER]) {
    assert.equal(validateCardAction({ id, action: 'confirm' }), null, String(id))
  }
  assert.deepEqual(validateCardAction({ id: HUB_MAX_ID, action: 'confirm' }), { target: `/cards/${HUB_MAX_ID}/action`, body: { action: 'confirm' } })
})

test('every new write rejects a missing csrf header before the hub', async () => {
  const bodies = [
    ['/api/hub/setting-action', { key: 'theme_cap_pct', action: 'clear' }],
    ['/api/hub/discipline-action', { kind: 'loss-streak', action: 'add' }],
    ['/api/hub/card-action', { id: 7, action: 'confirm' }],
  ] as const
  for (const [path, body] of bodies) {
    const hits: Hit[] = []
    const response = await post(path, body, hits, { headers: { 'x-chives-action': '' } })
    assert.equal(response.status, 400, path)
    assert.equal(hits.length, 0, path)
  }
})

test('every new write rejects a non-JSON content type', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/card-action', { id: 7, action: 'confirm' }, hits, { headers: { 'content-type': 'text/plain' } })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a GET on any new write route is rejected', async () => {
  const hits: Hit[] = []
  for (const path of ['/api/hub/setting-action', '/api/hub/discipline-action', '/api/hub/card-action']) {
    const response = await post(path, '', hits, { method: 'GET' })
    assert.equal(response.status, 400, path)
  }
  assert.equal(hits.length, 0)
})

test('a query string on a new write route is rejected', async () => {
  const hits: Hit[] = []
  const response = await handleHubRequest(route('/api/hub/card-action'), BASE, new Request('http://localhost/api/hub/card-action?x=1', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1' },
    body: JSON.stringify({ id: 7, action: 'confirm' }),
  }), { fetchImpl: fakeFetch(hits) })
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a write body over four kilobytes is rejected', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/card-action', JSON.stringify({ id: 7, action: 'confirm', pad: 'x'.repeat(5000) }), hits)
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('a valid write never forwards cookies or the raw browser body', async () => {
  const hits: Hit[] = []
  const response = await handleHubRequest(route('/api/hub/card-action'), BASE, new Request('http://localhost/api/hub/card-action', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1', cookie: 'dsh=SECRET', 'user-agent': 'browser' },
    body: JSON.stringify({ id: 3, action: 'cancel' }),
  }), { fetchImpl: fakeFetch(hits) })
  assert.equal(response.status, 200)
  assert.equal(hits.length, 1)
  assert.equal(hits[0]!.init?.body, '{"action":"cancel"}')
  assert.deepEqual(hits[0]!.init?.headers, { accept: 'application/json', 'content-type': 'application/json' })
})

test('an unreachable hub on a write returns the exact contract body', async () => {
  const response = await handleHubRequest(route('/api/hub/setting-action'), 'http://127.0.0.1:1', new Request('http://localhost/api/hub/setting-action', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-chives-action': '1' },
    body: JSON.stringify({ key: 'theme_cap_pct', action: 'clear' }),
  }), {})
  assert.equal(response.status, 502)
  assert.deepEqual(await response.json(), { ok: false, error: { code: 'hub_unreachable' } })
})

test('a non-JSON body on a new write is rejected', async () => {
  const hits: Hit[] = []
  const response = await post('/api/hub/setting-action', 'not json{', hits)
  assert.equal(response.status, 400)
  assert.equal(hits.length, 0)
})

test('array and null bodies are rejected on every new write', async () => {
  for (const path of ['/api/hub/setting-action', '/api/hub/discipline-action', '/api/hub/card-action']) {
    for (const body of ['null', '[]', '"x"', '1']) {
      const hits: Hit[] = []
      const response = await post(path, body, hits)
      assert.equal(response.status, 400, `${path} ${body}`)
      assert.equal(hits.length, 0, `${path} ${body}`)
    }
  }
})
