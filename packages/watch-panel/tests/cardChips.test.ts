import assert from 'node:assert/strict'
import { test } from 'node:test'
import { normalizeCardChips } from '../src/client/market.ts'

test('chips: only live cards count, the most urgent state wins per stock, junk is ignored', () => {
  const out = normalizeCardChips({ cards: [
    { id: 1, code: '601099.SH', status: 'active', state: 'observe' },
    { id: 2, code: '601099.SH', status: 'active', state: 'execute' },
    { id: 3, code: '002553.SZ', status: 'proposed', state: 'observe' },
    { id: 4, code: '600000.SH', status: 'cancelled', state: 'execute' },
    { id: 5, code: '600001.SH', status: 'closed', state: 'exit' },
    { id: 'x', code: '600002.SH', status: 'active' },
    { id: 6, code: '', status: 'active' },
    { id: 7, code: '600003.SH', status: 'active', state: 'bogus' },
  ] })
  assert.deepEqual(Object.keys(out).sort(), ['002553.SZ', '600003.SH', '601099.SH'])
  assert.deepEqual(out['601099.SH'], { cardId: 2, state: 'execute' })
  assert.equal(out['002553.SZ']!.state, 'proposed')
  assert.equal(out['600003.SH']!.state, 'observe')
  assert.deepEqual(normalizeCardChips(null), {})
  assert.deepEqual(normalizeCardChips({ cards: 5 }), {})
})
