import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const CLIENT = join(import.meta.dirname, '..', 'src', 'client')
const SRC = join(import.meta.dirname, '..', 'src')
const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/

function walk(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) files.push(...walk(path))
    else files.push(path)
  }
  return files
}

const clientFiles = walk(CLIENT)

test('no literal colour appears in watch-panel client source', () => {
  const offenders: string[] = []
  for (const file of clientFiles) {
    if (!/\.(ts|tsx|css)$/.test(file)) continue
    readFileSync(file, 'utf8').split('\n').forEach((line, index) => {
      if (COLOR.test(line)) offenders.push(`${file}:${index + 1}`)
    })
  }
  assert.deepEqual(offenders, [])
})

test('up/down colours come from the swap-aware tokens', () => {
  const all = clientFiles.map((file) => readFileSync(file, 'utf8')).join('\n')
  assert.ok(all.includes('var(--chives-up)'))
  assert.ok(all.includes('var(--chives-down)'))
  assert.ok(all.includes('var(--chives-up)'))
  assert.ok(all.includes('var(--chives-down)'))
  assert.ok(all.includes('var(--chives-diverging-mid)'))
})

test('reduced motion disables animation, transition and transforms', () => {
  const css = readFileSync(join(CLIENT, 'styles.ts'), 'utf8')
  assert.ok(css.includes('@media (prefers-reduced-motion: reduce)'))
  assert.ok(css.includes('animation: none !important'))
  assert.ok(css.includes('transition: none !important'))
  assert.ok(css.includes('transform: none !important'))
})

test('no external URL is referenced by the package source', () => {
  const offenders: string[] = []
  for (const file of walk(SRC)) {
    if (!/\.(ts|tsx|css)$/.test(file)) continue
    const source = readFileSync(file, 'utf8')
    if (/https?:\/\/(?!127\.0\.0\.1|localhost|\[::1\])/.test(source)) offenders.push(file)
  }
  assert.deepEqual(offenders, [])
})

test('the panel never renders an order-entry affordance', () => {
  const all = clientFiles.map((file) => readFileSync(file, 'utf8')).join('\n')
  for (const word of ['\u4e0b\u5355', '\u4e70\u5165', '\u5356\u51fa', '\u59d4\u6258']) assert.ok(!all.includes(word), word)
})

test('all five sections and their key labels exist in both dictionaries', () => {
  const locales = readFileSync(join(CLIENT, 'locales.ts'), 'utf8')
  for (const word of ['\u4e2a\u80a1', '\u677f\u5757', '\u544a\u8b66', '\u89c4\u5219', '\u5206\u6790', '\u5df2\u5206\u6790', '\u5206\u6790\u4e2d', '\u5df2\u8df3\u8fc7', '\u6837\u672c\u5c11', '\u6570\u636e\u9648\u65e7']) {
    assert.ok(locales.includes(word), word)
  }
})

test('heat map transitions area and fill instead of hard switching', () => {
  const css = readFileSync(join(CLIENT, 'styles.ts'), 'utf8')
  assert.match(css, /\.chives-tile \{[^}]*transition:[^}]*width 320ms/)
  assert.match(css, /background-color 320ms/)
  assert.ok(readFileSync(join(CLIENT, 'charts.tsx'), 'utf8').includes('viewTransitionName'))
})

test('alerts animate in and settle after thirty seconds', () => {
  const css = readFileSync(join(CLIENT, 'styles.ts'), 'utf8')
  assert.match(css, /chives-alert-in /)
  assert.match(css, /chives-alert-glow 30s/)
  assert.match(css, /chives-flow 1800ms/)
})

test('sector view buttons stay in the wrapping section head', () => {
  const css = readFileSync(join(CLIENT, 'styles.ts'), 'utf8')
  assert.match(css, /\.chives-wb-section-head \{[^}]*flex-wrap: wrap/)
  assert.match(css, /\.chives-wb-switch[^{]*\{[^}]*flex-wrap: wrap/)
  assert.doesNotMatch(css, /\.chives-wb-switch[^{]*\{[^}]*position: (absolute|sticky)/)
  assert.match(css, /\.chives-alert \{[^}]*grid-template-columns: 62px 74px minmax\(0, 1fr\) auto/)
  const workbench = readFileSync(join(CLIENT, 'workbench.tsx'), 'utf8')
  assert.match(workbench, /className="chives-wb-switch"/)
})
