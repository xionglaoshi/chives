import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createElement } from 'react'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { loadClientModule } from './tsx.ts'

type Component = (props: never) => ReactElement
const brand = await loadClientModule('brand.tsx')
const HeroBrandMark = brand.HeroBrandMark as Component
const SidebarBrandName = brand.SidebarBrandName as Component

test('the hero mark seat also renders the Chives headline', () => {
  const html = renderToStaticMarkup(createElement(HeroBrandMark, { size: 34, className: 'fish' } as never))
  assert.match(html, /\u4eca\u5929\u60f3\u7814\u7a76\u4ec0\u4e48\uff1f/)
  assert.ok(!html.includes('\u63a2\u7d22\u672a\u81f3\u4e4b\u5883'))
  assert.ok(html.includes('chives-hero-title'))
  assert.match(html, /aria-label="Chives"/)
})

test('the hero title no longer renders the preview badge copy', () => {
  const html = renderToStaticMarkup(createElement(HeroBrandMark, { size: 34 } as never))
  assert.ok(!html.includes('\u9884\u89c8\u7248'))
  assert.ok(!html.includes('previewBadge'))
})

test('the sidebar name seat carries the serif wordmark and the tagline', () => {
  const html = renderToStaticMarkup(createElement(SidebarBrandName, {} as never))
  assert.match(html, />老韭菜 · Chives</)
  assert.match(html, /让股民享受AI时代红利/)
  assert.ok(html.includes('chives-brand-word'))
  assert.ok(html.includes('chives-brand-sub'))
})
