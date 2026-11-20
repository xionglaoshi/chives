import assert from 'node:assert/strict'
import { test } from 'node:test'
import { DOCUMENT_TITLE, installDocumentBrand } from '../src/client/documentBrand.ts'

function fakeDoc(existing: boolean) {
  const attrs: Record<string, string>[] = existing ? [{ rel: 'icon', href: 'favicon.svg', media: '(prefers-color-scheme: dark)' }] : []
  const toEl = (a: Record<string, string>) => ({
    setAttribute: (k: string, v: string) => { a[k] = v },
    removeAttribute: (k: string) => { delete a[k] },
    getAttribute: (k: string) => a[k] ?? null,
  })
  return {
    attrs,
    doc: {
      title: 'DeepSeek Harness',
      head: { appendChild: (el: { __a: Record<string, string> }) => { attrs.push(el.__a) } } as unknown as Element,
      querySelectorAll: () => attrs.map(toEl) as unknown as Element[],
      createElement: () => { const a: Record<string, string> = {}; return Object.assign(toEl(a), { __a: a }) as unknown as Element },
    },
  }
}

test('sets the Chives title and replaces an existing favicon', () => {
  const { doc, attrs } = fakeDoc(true)
  installDocumentBrand(doc)()
  assert.equal(doc.title, DOCUMENT_TITLE)
  assert.match(attrs[0]!.href!, /^data:image\/svg\+xml,/)
  assert.equal(attrs[0]!.media, undefined)
})

test('adds a favicon when the page has none', () => {
  const { doc, attrs } = fakeDoc(false)
  installDocumentBrand(doc)()
  assert.equal(attrs.length, 1)
  assert.equal(attrs[0]!.rel, 'icon')
})

test('no document: harmless', () => {
  assert.doesNotThrow(() => installDocumentBrand(undefined as never)())
})
