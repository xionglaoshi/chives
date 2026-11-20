import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ALIAS_TOKENS,
  CHIVES_TOKENS,
  OVERRIDE_SOURCE,
  THEME_DARK_ID,
  THEME_LIGHT_ID,
  aliasTokenPairs,
  aliasTokens,
  chivesTokenCss,
} from '../src/client/tokens.ts'

const lightNames = Object.keys(CHIVES_TOKENS.light)
const darkNames = Object.keys(CHIVES_TOKENS.dark)

test('light and dark token sets define the same names', () => {
  assert.deepEqual([...lightNames].sort(), [...darkNames].sort())
})

test('every token has a non-empty value in both schemes', () => {
  for (const name of lightNames) {
    assert.ok(CHIVES_TOKENS.light[name as keyof typeof CHIVES_TOKENS.light].length > 0, name)
    assert.ok(CHIVES_TOKENS.dark[name as keyof typeof CHIVES_TOKENS.dark].length > 0, name)
  }
})

test('required public tokens exist', () => {
  for (const name of ['--chives-up', '--chives-down', '--chives-gold', '--chives-hairline', '--chives-ease',
    '--chives-dur-fast', '--chives-dur-base', '--chives-dur-slow', '--chives-hairline-color', '--chives-font-serif']) {
    assert.ok(lightNames.includes(name), name)
  }
})

test('surface, three text tiers, status and diverging tokens exist', () => {
  for (const name of ['--chives-surface-base', '--chives-surface-panel', '--chives-text-primary',
    '--chives-text-secondary', '--chives-text-tertiary', '--chives-state-healthy', '--chives-state-warn',
    '--chives-state-critical', '--chives-state-idle', '--chives-diverging-neg', '--chives-diverging-mid',
    '--chives-diverging-pos']) {
    assert.ok(lightNames.includes(name), name)
  }
})

test('categorical colours are a fixed 1..8 order', () => {
  for (let index = 1; index <= 8; index += 1) {
    assert.ok(lightNames.includes(`--chives-cat-${index}`))
  }
  assert.ok(!lightNames.includes('--chives-cat-9'))
})

test('status colours never reuse the up/down tokens', () => {
  for (const scheme of ['light', 'dark'] as const) {
    const values = Object.values(CHIVES_TOKENS[scheme])
    const up = CHIVES_TOKENS[scheme]['--chives-up']
    const down = CHIVES_TOKENS[scheme]['--chives-down']
    const status = [
      CHIVES_TOKENS[scheme]['--chives-state-healthy'],
      CHIVES_TOKENS[scheme]['--chives-state-warn'],
      CHIVES_TOKENS[scheme]['--chives-state-critical'],
    ]
    for (const value of status) {
      assert.notEqual(value, up)
      assert.notEqual(value, down)
      assert.ok(!value.includes('--chives-up'))
      assert.ok(!value.includes('--chives-down'))
    }
    assert.ok(values.length > 0)
  }
})

test('hairline is a half-pixel and durations sit in the 120-600ms band', () => {
  assert.equal(CHIVES_TOKENS.light['--chives-hairline'], '0.5px')
  for (const name of ['--chives-dur-fast', '--chives-dur-base', '--chives-dur-slow'] as const) {
    const ms = Number(CHIVES_TOKENS.light[name].replace('ms', ''))
    assert.ok(ms >= 120 && ms <= 600, `${name}=${ms}`)
  }
})

test('the easing curve is a single cubic-bezier token', () => {
  assert.match(CHIVES_TOKENS.light['--chives-ease'], /^cubic-bezier\(/)
  assert.equal(CHIVES_TOKENS.light['--chives-ease'], CHIVES_TOKENS.dark['--chives-ease'])
})

test('the serif stack is local-only (no URL, no download)', () => {
  const stack = CHIVES_TOKENS.light['--chives-font-serif']
  assert.match(stack, /Georgia/)
  assert.ok(!/https?:|url\(/.test(stack))
})

test('alias maps cover the same dsh tokens in both schemes', () => {
  assert.deepEqual(Object.keys(ALIAS_TOKENS.light).sort(), Object.keys(ALIAS_TOKENS.dark).sort())
  assert.ok(Object.keys(ALIAS_TOKENS.light).length >= 15)
})

test('alias values only reference Chives tokens', () => {
  for (const scheme of ['light', 'dark'] as const) {
    for (const [name, value] of Object.entries(ALIAS_TOKENS[scheme])) {
      assert.match(name, /^--dsw-alias-/)
      assert.match(value, /^var\(--chives-[a-z0-9-]+\)$/)
    }
  }
})

test('override pairs carry both schemes for every alias', () => {
  const pairs = aliasTokenPairs()
  assert.deepEqual(Object.keys(pairs).sort(), Object.keys(ALIAS_TOKENS.light).sort())
  for (const pair of Object.values(pairs)) {
    assert.match(pair.light, /^var\(--chives-/)
    assert.match(pair.dark, /^var\(--chives-/)
  }
})

test('registered themes cover light and dark with distinct ids', () => {
  assert.equal(THEME_DARK_ID, 'chives')
  assert.equal(THEME_LIGHT_ID, 'chives-light')
  assert.notEqual(THEME_DARK_ID, THEME_LIGHT_ID)
  assert.notEqual(THEME_DARK_ID, 'system')
  assert.notEqual(OVERRIDE_SOURCE, THEME_DARK_ID)
})

test('theme token payloads are the alias maps', () => {
  assert.deepEqual(aliasTokens('dark'), ALIAS_TOKENS.dark)
  assert.notEqual(aliasTokens('dark'), ALIAS_TOKENS.dark)
})

test('token CSS publishes light on :root and dark under the theme attribute', () => {
  const css = chivesTokenCss()
  assert.ok(css.startsWith(':root{'))
  assert.ok(css.includes('body[data-ds-dark-theme]'))
  assert.ok(css.includes('html[data-ds-dark-theme]'))
})

test('token CSS defines every token in both scheme blocks', () => {
  const css = chivesTokenCss()
  const [lightBlock, darkBlock] = css.split('body[data-ds-dark-theme]')
  for (const name of lightNames) {
    assert.ok(lightBlock!.includes(`${name}:`), `light ${name}`)
    assert.ok(darkBlock!.includes(`${name}:`), `dark ${name}`)
  }
})

test('green-up swap flips up/down and is opt-in', () => {
  const css = chivesTokenCss()
  assert.ok(css.includes('[data-chives-updown="green-up"]'))
  assert.ok(css.includes('--chives-up: var(--chives-green)'))
  assert.ok(css.includes('--chives-down: var(--chives-red)'))
})
