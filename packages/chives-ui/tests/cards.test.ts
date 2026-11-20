import assert from 'node:assert/strict'
import test from 'node:test'
import { CARD_STAGGER_MS, QUICK_CARDS } from '../src/client/cards.ts'
import { en, zh } from '../src/client/locales.ts'

test('exactly six cards, in the designed order', () => {
  assert.equal(QUICK_CARDS.length, 6)
  assert.deepEqual(QUICK_CARDS.map(card => card.id), ['review', 'research', 'portfolio', 'watchlist', 'filings', 'setup'])
})

test('card ids are unique', () => {
  assert.equal(new Set(QUICK_CARDS.map(card => card.id)).size, 6)
})

test('every prompt exists in both dictionaries', () => {
  for (const card of QUICK_CARDS) {
    assert.ok(zh[card.prompt].length > 0, card.prompt)
    assert.ok(en[card.prompt].length > 0, card.prompt)
  }
})

test('the six Chinese prompts are the fixed product copy', () => {
  const prompts = QUICK_CARDS.map(card => zh[card.prompt])
  assert.ok(prompts[0]!.includes('复盘今天的盘面'))
  assert.ok(prompts[1]!.includes('深度研究一只股票'))
  assert.ok(prompts[2]!.includes('诊断我的持仓'))
  assert.ok(prompts[3]!.includes('我盯的票'))
  assert.ok(prompts[4]!.includes('财报'))
  assert.ok(prompts[5]!.includes('设置盯盘'))
})

test('stagger stays at 40ms and the last card settles within 400ms', () => {
  assert.equal(CARD_STAGGER_MS, 40)
  const total = CARD_STAGGER_MS * (QUICK_CARDS.length - 1) + 200
  assert.ok(total <= 400, String(total))
})
