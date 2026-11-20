import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const PATCH = readFileSync(join(import.meta.dirname, '..', 'cordis.patch.yml'), 'utf8')
const LINES = PATCH.split('\n')

test('the patch inserts chives-ui as a bundle row', () => {
  assert.match(PATCH, /- insert:\n {4}- id: chives-ui\n {6}name: chives-ui/)
})

test('every disabled row is a shipped consumer we checked in core/dsh', () => {
  const disabled = [...PATCH.matchAll(/^- id: (\S+)\n {2}disabled: true$/gm)].map(match => match[1])
  assert.deepEqual(disabled, ['ui-brand-official', 'ui-plugin-manager', 'entry-customization', 'ui-agent-preset'])
})

test('the patch has no JS-tag expressions that break safe_load', () => {
  assert.ok(!PATCH.includes('!!js'))
  assert.ok(!PATCH.includes('!js'))
})

test('the patch stays a flat list of mapping rows', () => {
  assert.equal(LINES[0]!.startsWith('#'), true)
  let depth = 0
  for (const line of LINES) {
    if (line.trim() === '' || line.trimStart().startsWith('#')) continue
    const indent = line.length - line.trimStart().length
    assert.ok(indent === 0 || indent === 2 || indent === 4 || indent === 6, `unexpected indent: ${line}`)
    if (indent === 0) assert.ok(line.startsWith('- '), `top-level row: ${line}`)
    depth += 1
  }
  assert.ok(depth > 0)
})

test('no tabs and no trailing whitespace', () => {
  for (const line of LINES) {
    assert.ok(!line.includes('\t'))
    assert.equal(line, line.trimEnd())
  }
})

test('each disabled row carries an explanatory comment', () => {
  for (const id of ['ui-brand-official', 'ui-plugin-manager', 'entry-customization', 'ui-agent-preset']) {
    assert.ok(PATCH.includes(id))
  }
  assert.ok(PATCH.includes('Every disabled row was checked in core/dsh first'))
})

test('the official brand row yields both single brand cells to Chives', () => {
  assert.match(PATCH, /- id: ui-brand-official\n {2}disabled: true/)
})

test('the patch does not disable a structural layout row', () => {
  for (const forbidden of ['ui-layout', 'ui-sidebar', 'ui-conversation', 'ui-theme', 'ui-settings-general']) {
    assert.ok(!PATCH.includes(`- id: ${forbidden}`), forbidden)
  }
})
