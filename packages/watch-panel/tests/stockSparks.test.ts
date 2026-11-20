import assert from 'node:assert/strict'
import { test } from 'node:test'
import { sparkPath } from '../src/client/api.ts'
import { normalizeStockSparks } from '../src/client/market.ts'

test('sparkPath dedupes, keeps SH/SZ only, caps at 30', () => {
  assert.equal(sparkPath(['002553.SZ', '601099.SH', '601099.SH', '00700.HK']), '/api/hub/spark?codes=002553.SZ,601099.SH')
  assert.equal(sparkPath([]), null)
  assert.equal(sparkPath(Array.from({ length: 45 }, (_, i) => `${600000 + i}.SH`))!.split('=')[1]!.split(',').length, 30)
})

test('normalizeStockSparks drops short or malformed series', () => {
  const out = normalizeStockSparks({ sparks: { '601099.SH': { points: [3.5, 3.6, 3.55], change_pct: -1.1 }, '002553.SZ': { points: [1] }, bad: { points: 'x' } } })
  assert.deepEqual(Object.keys(out), ['601099.SH'])
  assert.equal(out['601099.SH']!.points.length, 3)
  assert.equal(out['601099.SH']!.changePct, -1.1)
  assert.deepEqual(normalizeStockSparks(undefined), {})
})
