/**
 * Cross-panel draft bridge. The watch panel has no input actions (its `main`
 * slot receives none), so it asks the Chives shell to open the conversation and
 * leave a pending draft; the composer dock consumes it through the official
 * `inputActions.setDraft`, never `submit`.
 */

export const ASK_EVENT = 'chives:ask'
export const PENDING_KEY = 'chives.pendingDraft'
export const MAX_DRAFT_LENGTH = 2_000

export interface DraftStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

let pending: string | null = null

function normalize(text: unknown): string | null {
  if (typeof text !== 'string') return null
  const trimmed = text.trim()
  if (trimmed === '') return null
  return trimmed.slice(0, MAX_DRAFT_LENGTH)
}

function defaultStorage(): DraftStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function read(storage: DraftStorage | null): string | null {
  if (!storage) return null
  try {
    return normalize(storage.getItem(PENDING_KEY))
  } catch {
    return null
  }
}

/** Store a draft that will be applied when the composer is next mounted. */
export function requestDraft(text: unknown, storage: DraftStorage | null = defaultStorage()): string | null {
  const value = normalize(text)
  if (value === null) return null
  pending = value
  try {
    storage?.setItem(PENDING_KEY, value)
  } catch {
    // Storage can be unavailable; the in-memory value still works in this session.
  }
  return value
}

/** Read and clear the pending draft, memory first. */
export function takePending(storage: DraftStorage | null = defaultStorage()): string | null {
  const value = pending ?? read(storage)
  pending = null
  try {
    storage?.removeItem(PENDING_KEY)
  } catch {
    // Ignore storage failures.
  }
  return normalize(value)
}

/** Clear a pending draft without applying it. */
export function clearPending(storage: DraftStorage | null = defaultStorage()): void {
  pending = null
  try {
    storage?.removeItem(PENDING_KEY)
  } catch {
    // Ignore storage failures.
  }
}

/**
 * Listen for the shell's `chives:ask` event; returns a disposer. In a non-browser
 * environment (unit tests of the registration body) it is a no-op.
 */
export function installAskListener(
  handler: (text: string, persist: boolean) => void,
  target: EventTarget | null = typeof window === 'undefined' ? null : window,
): () => void {
  if (!target) return () => {}
  const listener = (event: Event): void => {
    const detail = (event as CustomEvent).detail
    if (!detail || typeof detail !== 'object') return
    const text = normalize((detail as { text?: unknown }).text)
    // Portfolio-derived prompts set `persist:false` so the draft stays in memory
    // only; plain questions keep the cross-reload storage behaviour.
    const persist = (detail as { persist?: unknown }).persist !== false
    if (text !== null) handler(text, persist)
  }
  target.addEventListener(ASK_EVENT, listener)
  return () => target.removeEventListener(ASK_EVENT, listener)
}
