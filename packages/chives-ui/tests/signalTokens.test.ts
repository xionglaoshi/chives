import assert from 'node:assert/strict'
import test from 'node:test'
import { CHIVES_TOKENS, chivesTokenCss } from '../src/client/tokens.ts'
import { en, zh } from '../src/client/locales.ts'

const SIGNAL_TOKENS = [
  '--chives-sig-plan',
  '--chives-sig-opp',
  '--chives-sig-risk',
  '--chives-sig-sector',
  '--chives-sig-info',
] as const

test('both schemes define the five signal type tokens', () => {
  for (const scheme of ['light', 'dark'] as const) {
    for (const name of SIGNAL_TOKENS) {
      assert.ok(name in CHIVES_TOKENS[scheme], `${scheme} ${name}`)
      assert.ok(CHIVES_TOKENS[scheme][name].length > 0, `${scheme} ${name}`)
    }
  }
})

test('signal type colours are distinct from each other and from up/down', () => {
  for (const scheme of ['light', 'dark'] as const) {
    const values = SIGNAL_TOKENS.map((name) => CHIVES_TOKENS[scheme][name])
    assert.equal(new Set(values).size, values.length, scheme)
    const up = CHIVES_TOKENS[scheme]['--chives-up']
    const down = CHIVES_TOKENS[scheme]['--chives-down']
    for (const value of values) {
      assert.notEqual(value, up)
      assert.notEqual(value, down)
    }
  }
})

test('the token stylesheet publishes every signal type in both scheme blocks', () => {
  const css = chivesTokenCss()
  const [light, dark] = css.split('body[data-ds-dark-theme]')
  for (const name of SIGNAL_TOKENS) {
    assert.ok(light!.includes(name), name)
    assert.ok(dark!.includes(name), name)
  }
})

test('the sidebar entry is named 盯盘 in Chinese and Watch in English', () => {
  assert.equal(zh.panelWorkbench, '盯盘')
  assert.equal(en.panelWorkbench, 'Watch')
  assert.equal(zh.homeTitle, '盯盘')
  assert.equal(en.homeTitle, 'Watch')
})

test('no chives-ui copy still calls the page 工作台', () => {
  assert.doesNotMatch(Object.values(zh).join('|'), /工作台/)
  assert.doesNotMatch(Object.values(en).join('|'), /Workbench/)
})
