import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  ASK_EVENT,
  MAX_DRAFT_LENGTH,
  PENDING_KEY,
  clearPending,
  installAskListener,
  requestDraft,
  takePending,
} from '../src/client/draftBridge.ts'
import type { DraftStorage } from '../src/client/draftBridge.ts'

function storage(): DraftStorage & { map: Map<string, string> } {
  const map = new Map<string, string>()
  return {
    map,
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => { map.set(key, value) },
    removeItem: (key) => { map.delete(key) },
  }
}

test('requestDraft stores the trimmed text in memory and storage', () => {
  const store = storage()
  assert.equal(requestDraft('  hello  ', store), 'hello')
  assert.equal(store.map.get(PENDING_KEY), 'hello')
  assert.equal(takePending(store), 'hello')
  assert.equal(store.map.has(PENDING_KEY), false)
  assert.equal(takePending(store), null)
})

test('empty and non-string drafts are ignored', () => {
  const store = storage()
  assert.equal(requestDraft('   ', store), null)
  assert.equal(requestDraft(null, store), null)
  assert.equal(requestDraft(42, store), null)
  assert.equal(takePending(store), null)
})

test('drafts are capped at the documented length', () => {
  const store = storage()
  const long = 'x'.repeat(MAX_DRAFT_LENGTH + 50)
  assert.equal(requestDraft(long, store)!.length, MAX_DRAFT_LENGTH)
  assert.equal(takePending(store)!.length, MAX_DRAFT_LENGTH)
})

test('takePending falls back to storage when memory is empty', () => {
  const store = storage()
  store.setItem(PENDING_KEY, 'from storage')
  assert.equal(takePending(store), 'from storage')
  assert.equal(store.map.has(PENDING_KEY), false)
})

test('storage failures never break the in-memory bridge', () => {
  const broken: DraftStorage = {
    getItem: () => { throw new Error('no') },
    setItem: () => { throw new Error('no') },
    removeItem: () => { throw new Error('no') },
  }
  assert.equal(requestDraft('still works', broken), 'still works')
  assert.equal(takePending(broken), 'still works')
  clearPending(broken)
})

test('clearPending drops both copies', () => {
  const store = storage()
  requestDraft('x', store)
  clearPending(store)
  assert.equal(store.map.has(PENDING_KEY), false)
  assert.equal(takePending(store), null)
})

test('installAskListener receives valid text and ignores malformed events', () => {
  const target = new EventTarget()
  const seen: string[] = []
  const dispose = installAskListener((text) => seen.push(text), target)
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: '  please continue  ' } }))
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: '   ' } }))
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: null }))
  target.dispatchEvent(new CustomEvent(ASK_EVENT))
  assert.deepEqual(seen, ['please continue'])
  dispose()
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: 'after dispose' } }))
  assert.deepEqual(seen, ['please continue'])
})

test('installAskListener is a no-op without a target', () => {
  assert.equal(typeof installAskListener(() => {}, null), 'function')
})

test('installAskListener forwards persist=false so portfolio drafts stay in memory', () => {
  const target = new EventTarget()
  const seen: Array<[string, boolean]> = []
  const dispose = installAskListener((text, persist) => seen.push([text, persist]), target)
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: 'held stock', persist: false } }))
  target.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: { text: 'public question' } }))
  assert.deepEqual(seen, [['held stock', false], ['public question', true]])
  dispose()
})
