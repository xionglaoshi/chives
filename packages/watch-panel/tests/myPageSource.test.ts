import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { HUB_PORTFOLIO_HISTORY_PATH, HUB_PORTFOLIO_OVERVIEW_PATH, portfolioHistoryPath } from '../src/client/api.ts'

const WATCH = join(import.meta.dirname, '..', 'src', 'client')
const CHIVES = join(import.meta.dirname, '..', '..', 'chives-ui', 'src', 'client')
const PAGE = join(CHIVES, 'myPage.tsx')
const MODEL = join(CHIVES, 'myPageModel.ts')
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

test('the page modules carry no literal colour', () => {
  for (const path of [PAGE, MODEL, join(CHIVES, 'myPageFormat.ts')]) {
    assert.ok(!COLOR.test(readFileSync(path, 'utf8')), path)
  }
})

test('localStorage is touched only through the guarded model helper', () => {
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(!page.includes('localStorage'))
  const model = readFileSync(MODEL, 'utf8')
  assert.ok(model.includes('STORAGE_PROP'))
  assert.ok(model.includes('try {') && model.includes('catch'))
})

test('no sessionStorage or portfolio payload is persisted anywhere in either client', () => {
  for (const dir of [WATCH, CHIVES]) {
    for (const file of walk(dir)) {
      if (!/\.(ts|tsx)$/.test(file)) continue
      const text = readFileSync(file, 'utf8')
      assert.ok(!text.includes('sessionStorage'), file)
      assert.ok(!/localStorage\.setItem\([^)]*portfolio/i.test(text), file)
    }
  }
  const model = readFileSync(MODEL, 'utf8')
  assert.ok(model.includes("HIDDEN_STORAGE_KEY = 'chives.my.hidden'"))
  assert.ok(!model.includes('portfolio.positions]'))
})

test('the page never fetches an absolute or third-party URL', () => {
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(!/https?:\/\//.test(page))
  const format = readFileSync(join(CHIVES, 'myPageFormat.ts'), 'utf8')
  assert.ok(!/https?:\/\//.test(format))
  assert.match(page, /getHubJson/)
  assert.match(page, /STATE_PATH/)
})

test('the proxy paths are the two fixed private reads', () => {
  assert.equal(HUB_PORTFOLIO_OVERVIEW_PATH, '/api/hub/portfolio-overview')
  assert.equal(HUB_PORTFOLIO_HISTORY_PATH, '/api/hub/portfolio-history')
  assert.equal(portfolioHistoryPath(90), '/api/hub/portfolio-history?days=90')
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(!page.includes('/portfolio/overview'))
  assert.ok(!page.includes('/portfolio/history'))
})

test('reduced motion covers the mine page subtree', () => {
  const styles = readFileSync(join(CHIVES, 'styles.ts'), 'utf8')
  assert.ok(styles.includes('.chives-my *'))
  assert.ok(styles.includes('@media (prefers-reduced-motion: reduce)'))
  assert.ok(styles.includes('animation: none !important'))
  assert.ok(styles.includes('transform: none !important'))
})

test('there is no order-entry copy in the page source', () => {
  for (const path of [PAGE, MODEL, join(CHIVES, 'locales.ts')]) {
    const text = readFileSync(path, 'utf8')
    assert.ok(!text.includes('买入'), path)
    assert.ok(!text.includes('卖出'), path)
    assert.ok(!text.includes('下单'), path)
  }
})

test('the page stores only the hidden-amount flag, never a holding', () => {
  const model = readFileSync(MODEL, 'utf8')
  assert.equal((model.match(/storage\?\.setItem\(/g) ?? []).length, 1)
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(!page.includes('JSON.stringify'))
})

test('watch-panel registers the watch panel; chives-ui registers the mine panel', () => {
  const watch = readFileSync(join(WATCH, 'index.tsx'), 'utf8')
  assert.match(watch, /key: PANEL_ID/)
  assert.ok(!watch.includes('MyPage'))
  const chives = readFileSync(join(CHIVES, 'apply.ts'), 'utf8')
  assert.match(chives, /key: MY_PAGE_PANEL/)
  assert.match(chives, /ui\.MyPage/)
})

test('the page offers the three fixed ask prompts and no direct send', () => {
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(page.includes('ASK_EVENT'))
  assert.ok(!page.includes('.submit('))
  assert.ok(page.includes('askStockPrompt(position)'))
  assert.ok(page.includes('IMPORT_PROMPT'))
  assert.ok(page.includes('DIAGNOSE_PROMPT'))
})

test('the page asks chives-ui to keep portfolio drafts in memory', () => {
  const page = readFileSync(PAGE, 'utf8')
  assert.ok(page.includes('persist: false'))
  const bridge = readFileSync(join(CHIVES, 'draftBridge.ts'), 'utf8')
  assert.ok(bridge.includes('persist'))
  assert.ok(bridge.includes('requestDraft(text, null)') || bridge.includes('handler(text, persist)'))
})
