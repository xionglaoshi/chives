/**
 * Startup-prologue bookkeeping for the hero brand mark.
 *
 * `localStorage` access throws in some privacy modes and is absent during
 * server rendering, so every touch is wrapped: a broken store degrades to
 * "do not animate" instead of crashing the welcome page.
 */

export const PROLOGUE_KEY = 'chives.hero.prologue'
export const PROLOGUE_REPEAT_MS = 7 * 24 * 60 * 60 * 1000

/** The tiny slice of the Storage API used here, so tests can inject a fake. */
export interface KeyValueStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

/** Browser storage when reachable, otherwise null; never throws. */
export function safeLocalStorage(): KeyValueStore | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null
    return window.localStorage
  } catch {
    return null
  }
}

/** True when the prologue has not played within the last week. Never throws. */
export function shouldPlayPrologue(
  now: number = Date.now(),
  store: KeyValueStore | null = safeLocalStorage(),
): boolean {
  if (!store) return false
  try {
    const raw = store.getItem(PROLOGUE_KEY)
    if (raw === null) return true
    const playedAt = Number(raw)
    if (!Number.isFinite(playedAt) || playedAt <= 0) return true
    if (playedAt > now) return true
    return now - playedAt >= PROLOGUE_REPEAT_MS
  } catch {
    return false
  }
}

/** Record that the prologue played; a failing store is ignored. */
export function markProloguePlayed(
  now: number = Date.now(),
  store: KeyValueStore | null = safeLocalStorage(),
): void {
  if (!store) return
  try {
    store.setItem(PROLOGUE_KEY, String(now))
  } catch {
    // Storage full or read-only: the animation simply plays again next visit.
  }
}
