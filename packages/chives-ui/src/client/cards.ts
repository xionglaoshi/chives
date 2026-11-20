/** The six welcome-page quick-start cards; order is the stagger order. */
import type { ChivesKey } from './locales.ts'

export interface QuickCard {
  /** Stable cell id (also used by tests and future analytics). */
  readonly id: string
  /** Dictionary key holding the prompt that is inserted into the composer. */
  readonly prompt: ChivesKey
}

/** Six fixed prompts; clicking fills the draft, it never submits. */
export const QUICK_CARDS: readonly QuickCard[] = [
  { id: 'review', prompt: 'cardReview' },
  { id: 'research', prompt: 'cardResearch' },
  { id: 'portfolio', prompt: 'cardPortfolio' },
  { id: 'watchlist', prompt: 'cardWatchlist' },
  { id: 'filings', prompt: 'cardFilings' },
  { id: 'setup', prompt: 'cardSetup' },
]

/** Per-card entrance offset: 40 ms each, last card settles at 200 + 200 ms. */
export const CARD_STAGGER_MS = 40
