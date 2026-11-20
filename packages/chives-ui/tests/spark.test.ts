import assert from 'node:assert/strict'
import { test } from 'node:test'
import { normalizeSparks, sparkGeometry, sparkPath } from '../src/client/myPageModel.ts'

test('sparkPath dedupes, keeps only SH/SZ codes and caps at 30', () => {
  assert.equal(sparkPath(['600519.SH', '600519.SH', '300750.SZ', '00700.HK', 'abc']), '/api/hub/spark?codes=600519.SH,300750.SZ')
  assert.equal(sparkPath([]), null)
  assert.equal(sparkPath(['00700.HK']), null)
  const many = Array.from({ length: 40 }, (_, i) => `${600000 + i}.SH`)
  assert.equal(sparkPath(many)!.split('=')[1]!.split(',').length, 30)
})

test('normalizeSparks keeps valid rows and drops short or malformed ones', () => {
  const out = normalizeSparks({ ok: true, sparks: {
    '600519.SH': { points: [1, 2, 3], prev_close: 1.5, change_pct: 100 },
    '000001.SZ': { points: [1] },
    '000002.SZ': { points: 'x' },
    '000003.SZ': { points: [1, null, 'a', 2] },
  } })
  assert.deepEqual(Object.keys(out).sort(), ['000003.SZ', '600519.SH'])
  assert.deepEqual(out['000003.SZ']!.points, [1, 2])
  assert.deepEqual(normalizeSparks(null), {})
  assert.deepEqual(normalizeSparks({ sparks: 5 }), {})
})

test('sparkGeometry colours by last vs previous close and stays inside the box', () => {
  const up = sparkGeometry({ points: [10, 10.2, 10.5], prevClose: 10, changePct: 5 }, 60, 20)!
  assert.equal(up.side, 'up')
  const down = sparkGeometry({ points: [10, 9.8, 9.5], prevClose: 10, changePct: -5 }, 60, 20)!
  assert.equal(down.side, 'down')
  const flat = sparkGeometry({ points: [10, 10.1, 10], prevClose: 10, changePct: 0 }, 60, 20)!
  assert.equal(flat.side, 'flat')
  assert.match(up.line, /^M0\.0,/)
  const ys = [...up.line.matchAll(/,([\d.]+)/g)].map((m) => Number(m[1]))
  assert.ok(ys.every((value) => value >= 0 && value <= 20))
  assert.equal(sparkGeometry({ points: [1], prevClose: null, changePct: null }), null)
  const constant = sparkGeometry({ points: [5, 5, 5], prevClose: null, changePct: null })!
  assert.ok(Number.isFinite(constant.baseY!))
})
