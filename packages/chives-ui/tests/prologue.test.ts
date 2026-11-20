import assert from 'node:assert/strict'
import test from 'node:test'
import {
  PROLOGUE_KEY,
  PROLOGUE_REPEAT_MS,
  markProloguePlayed,
  shouldPlayPrologue,
} from '../src/client/prologue.ts'
import type { KeyValueStore } from '../src/client/prologue.ts'

class MemoryStore implements KeyValueStore {
  readonly data = new Map<string, string>()
  getItem(key: string): string | null { return this.data.get(key) ?? null }
  setItem(key: string, value: string): void { this.data.set(key, value) }
}

const NOW = 1_700_000_000_000

test('a missing store never animates and never throws', () => {
  assert.equal(shouldPlayPrologue(NOW, null), false)
  markProloguePlayed(NOW, null)
})

test('first visit plays the prologue', () => {
  assert.equal(shouldPlayPrologue(NOW, new MemoryStore()), true)
})

test('a visit inside the week does not replay', () => {
  const store = new MemoryStore()
  store.setItem(PROLOGUE_KEY, String(NOW - PROLOGUE_REPEAT_MS + 1))
  assert.equal(shouldPlayPrologue(NOW, store), false)
})

test('exactly one week later replays', () => {
  const store = new MemoryStore()
  store.setItem(PROLOGUE_KEY, String(NOW - PROLOGUE_REPEAT_MS))
  assert.equal(shouldPlayPrologue(NOW, store), true)
})

test('malformed timestamps fall back to playing', () => {
  const store = new MemoryStore()
  for (const raw of ['nope', '', '0', '-5', 'NaN']) {
    store.setItem(PROLOGUE_KEY, raw)
    assert.equal(shouldPlayPrologue(NOW, store), true, raw)
  }
})

test('a future timestamp (clock moved back) plays once more', () => {
  const store = new MemoryStore()
  store.setItem(PROLOGUE_KEY, String(NOW + 1_000))
  assert.equal(shouldPlayPrologue(NOW, store), true)
})

test('a throwing store degrades to no animation', () => {
  const store: KeyValueStore = {
    getItem() { throw new Error('blocked') },
    setItem() { throw new Error('blocked') },
  }
  assert.equal(shouldPlayPrologue(NOW, store), false)
  assert.doesNotThrow(() => { markProloguePlayed(NOW, store) })
})

test('marking records the moment and makes the next call static', () => {
  const store = new MemoryStore()
  markProloguePlayed(NOW, store)
  assert.equal(store.getItem(PROLOGUE_KEY), String(NOW))
  assert.equal(shouldPlayPrologue(NOW + 1000, store), false)
})
