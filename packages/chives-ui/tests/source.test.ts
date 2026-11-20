import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const CLIENT_DIR = join(import.meta.dirname, '..', 'src', 'client')
const SRC_DIR = join(import.meta.dirname, '..', 'src')

/** Same rule as the acceptance script: colours may only live in the token file. */
const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(/
const TOKEN_FILE = 'tokens.ts'

function walk(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) files.push(...walk(path))
    else files.push(path)
  }
  return files
}

const clientFiles = walk(CLIENT_DIR)

test('the token file exists and owns the palette', () => {
  const tokens = readFileSync(join(CLIENT_DIR, TOKEN_FILE), 'utf8')
  assert.match(tokens, COLOR)
})

test('no literal colour outside the token file', () => {
  const offenders: string[] = []
  for (const file of clientFiles) {
    if (file.endsWith(TOKEN_FILE) || !/\.(ts|tsx|css)$/.test(file)) continue
    const lines = readFileSync(file, 'utf8').split('\n')
    lines.forEach((line, index) => {
      if (COLOR.test(line)) offenders.push(`${file}:${index + 1}`)
    })
  }
  assert.deepEqual(offenders, [])
})

test('no external URL anywhere in the package source', () => {
  const offenders: string[] = []
  for (const file of walk(SRC_DIR)) {
    if (!/\.(ts|tsx)$/.test(file)) continue
    const text = readFileSync(file, 'utf8')
    if (/https?:\/\/(?!127\.0\.0\.1|localhost)/.test(text)) offenders.push(file)
  }
  assert.deepEqual(offenders, [])
})

test('reduced motion is honoured', () => {
  const styles = readFileSync(join(CLIENT_DIR, 'styles.ts'), 'utf8')
  assert.ok(styles.includes('@media (prefers-reduced-motion: reduce)'))
  assert.ok(styles.includes('animation: none !important'))
  assert.ok(styles.includes('transform: none !important'))
})

test('component styles read tokens, never raw values', () => {
  const styles = readFileSync(join(CLIENT_DIR, 'styles.ts'), 'utf8')
  assert.ok(styles.includes('var(--chives-hairline)'))
  assert.ok(styles.includes('var(--chives-ease)'))
  assert.ok(styles.includes('var(--chives-gold-glow)'))
})

test('brand and card copy live in the locale dictionaries', () => {
  const locales = readFileSync(join(CLIENT_DIR, 'locales.ts'), 'utf8')
  for (const text of ['今天想研究什么？', '复盘今天的盘面', '深度研究一只股票', '诊断我的持仓',
    '看看我盯的票今天有什么动静', '解读最新财报或公告', '帮我设置盯盘']) {
    assert.ok(locales.includes(text), text)
  }
})

test('the six card prompts appear in shipped source', () => {
  const source = clientFiles.map(file => readFileSync(file, 'utf8')).join('\n')
  for (const needle of ['复盘今天的盘面', '深度研究一只股票', '诊断我的持仓', '我盯的票', '财报', '设置盯盘']) {
    assert.ok(source.includes(needle), needle)
  }
})

test('localStorage is only touched through the guarded helper', () => {
  const cards = readFileSync(join(CLIENT_DIR, 'cards.tsx'), 'utf8')
  assert.ok(!cards.includes('localStorage'))
  const prologue = readFileSync(join(CLIENT_DIR, 'prologue.ts'), 'utf8')
  assert.ok(prologue.includes('try {') && prologue.includes('catch'))
})

test('the theme uses the registered service, not a DOM attribute hack', () => {
  const apply = readFileSync(join(CLIENT_DIR, 'apply.ts'), 'utf8')
  assert.ok(apply.includes('theme.register'))
  assert.ok(apply.includes('overrideTokens'))
  assert.ok(!apply.includes('data-ds-dark-theme'))
})

test('the entry declares the services it consumes', () => {
  const entry = readFileSync(join(CLIENT_DIR, 'index.tsx'), 'utf8')
  for (const service of ['slots', 'locale', 'theme', 'layout']) {
    assert.ok(entry.includes(`'${service}'`), service)
  }
})

test('welcome cards keep 24px+ from the title and the composer', () => {
  const styles = readFileSync(join(CLIENT_DIR, 'styles.ts'), 'utf8')
  assert.ok(styles.includes('margin: 20px 0 24px'))
  assert.ok(styles.includes('gap: 10px'))
})

test('welcome cards degrade to two then one column on narrow screens', () => {
  const styles = readFileSync(join(CLIENT_DIR, 'styles.ts'), 'utf8')
  const two = styles.indexOf('@media (max-width: 900px)')
  const one = styles.indexOf('@media (max-width: 560px)')
  assert.ok(two > 0)
  assert.ok(one > two)
  assert.ok(styles.slice(two, one).includes('repeat(2, minmax(0, 1fr))'))
  assert.ok(styles.slice(one).includes('grid-template-columns: minmax(0, 1fr)'))
})

test('the shipped headline group and More launcher are hidden by structural selectors', () => {
  const styles = readFileSync(join(CLIENT_DIR, 'styles.ts'), 'utf8')
  assert.ok(styles.includes('[class*="titleGroup"] { display: none !important; }'))
  assert.ok(styles.includes('nav[class*="panelList"] button[aria-haspopup="menu"]'))
})
