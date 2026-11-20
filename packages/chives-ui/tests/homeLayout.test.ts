import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const styles = readFileSync(join(import.meta.dirname, '..', 'src', 'client', 'styles.ts'), 'utf8')

function rule(selector: string): string {
  const index = styles.indexOf(`${selector} {`)
  assert.ok(index >= 0, `missing rule ${selector}`)
  return styles.slice(index, styles.indexOf('}', index) + 1)
}

test('the index strip fits six cards in a 1440px shell without scrolling', () => {
  const strip = rule('.chives-home-indexbar')
  assert.match(strip, /display: grid/)
  assert.match(strip, /repeat\(auto-fit, minmax\(\d+px, 1fr\)\)/)
  assert.doesNotMatch(strip, /overflow-x/)
  const min = Number(strip.match(/minmax\((\d+)px/)![1])
  // 1440 viewport - 280px sidebar - 48px page padding - 15px scrollbar.
  assert.ok(6 * min + 5 * 8 <= 1097, `six ${min}px cards plus gaps must fit the 1440px shell`)
  assert.ok(6 * min + 5 * 8 <= 1200, `six ${min}px cards plus gaps must fit a 1200px content area`)
})

test('the table toggle lives in a wrapping section head, not in the strip', () => {
  assert.match(rule('.chives-home-section-head'), /flex-wrap: wrap/)
  assert.match(rule('.chives-home-section-head'), /justify-content: space-between/)
  assert.match(rule('.chives-home-toggle'), /flex: 0 0 auto/)
  assert.ok(!styles.includes('.chives-home-tablebar'))
  assert.ok(!/\.chives-home-toggle[^}]*position: (absolute|sticky)/.test(styles))
})

test('an empty spark keeps the line height instead of collapsing the card', () => {
  const empty = rule('.chives-home-spark-empty')
  assert.match(empty, /display: block/)
  assert.match(empty, /height: 30px/)
})

test('home blocks declare min-width zero so they can shrink inside the grid', () => {
  for (const selector of ['.chives-home-grid > *', '.chives-panel', '.chives-panel-head', '.chives-breadth', '.chives-kv > div', '.chives-sector-lists', '.chives-feed-item']) {
    assert.match(rule(selector), /min-width: 0/, selector)
  }
})

test('the narrow layout wraps the watchlist and keeps the strip inside the page', () => {
  const mobile = styles.slice(styles.indexOf('@media (max-width: 767px)'))
  assert.match(mobile, /\.chives-home-indexbar \{ grid-template-columns: repeat\(auto-fit, minmax\(148px, 1fr\)\); \}/)
  assert.doesNotMatch(mobile, /margin: 0 -14px/)
  assert.match(mobile, /\.chives-home-table td:first-child[^}]*white-space: normal/)
  assert.match(mobile, /\.chives-home-code \{ display: block; margin-left: 0; \}/)
})
