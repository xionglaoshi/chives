/** Rule-first task segmentation; the model is only asked when this returns `uncertain`. */

import { extractUserSymbols, normalizeSymbolCode } from '../symbols.js';

export type SegmentKind = 'continue' | 'new' | 'uncertain';

export interface SegmentDecision {
  kind: SegmentKind;
  /** Stable machine-readable reason, persisted as `tasks.segment_reason`. */
  reason: string;
  detail?: string;
}

export interface SegmentPrevious {
  id: string;
  title: string | null;
  /** Set once the segment ended; a closed segment always starts a new one. */
  closedAt: string | null;
  /** Symbols collected for the segment while it was still open. */
  symbols: readonly { code: string; name: string | null }[];
}

export interface SegmentInput {
  previous: SegmentPrevious | undefined;
  /** Last message in the previous task (falls back to its start time in the service). */
  lastMessageAt: string | null | undefined;
  text: string;
  now: Date;
  /** Name -> code accumulated from earlier bot replies and summaries; no network lookup. */
  symbolNames?: Readonly<Record<string, string>>;
}

export const SIX_HOURS_MS = 6 * 60 * 60_000;
export const TEN_MINUTES_MS = 10 * 60_000;
export const TWO_HOURS_MS = 2 * 60 * 60_000;

const NEW_TOPIC_PREFIXES = ['另外', '换个', '新问题', '再问一个'] as const;
const CONTINUE_PREFIXES = ['接着', '继续', '刚才', '上面', '这个', '它', '那'] as const;
const CONTINUE_PHRASES = ['上一个', '之前那个'] as const;

function gapMs(input: SegmentInput): number | undefined {
  if (input.lastMessageAt === null || input.lastMessageAt === undefined) return undefined;
  const last = Date.parse(input.lastMessageAt);
  if (!Number.isFinite(last)) return undefined;
  return Math.max(0, input.now.getTime() - last);
}

function startsWithAny(text: string, prefixes: readonly string[]): boolean {
  const trimmed = text.trimStart();
  return prefixes.some((prefix) => trimmed.startsWith(prefix));
}

/** Suffix-insensitive key: `600519` and `600519.SH` refer to the same A-share. */
function codeKey(code: string): string {
  return normalizeSymbolCode(code).slice(0, 6);
}

/** A-share codes (6 digits, optional exchange suffix) plus names from the accumulated table. */
export function extractSymbols(
  text: string,
  symbolNames: Readonly<Record<string, string>> = {},
): string[] {
  return extractUserSymbols(text, symbolNames).map((symbol) => symbol.code);
}

/**
 * Rules in the order fixed by T132. `lastMessageAt` absent means the gap is
 * unknown, which is treated like "too long ago" (new segment).
 */
export function decideSegment(input: SegmentInput): SegmentDecision {
  const previous = input.previous;
  if (previous === undefined) return { kind: 'new', reason: 'no_previous' };
  if (previous.closedAt !== null) return { kind: 'new', reason: 'previous_closed' };

  const gap = gapMs(input);

  if (startsWithAny(input.text, NEW_TOPIC_PREFIXES)) {
    return { kind: 'new', reason: 'explicit_new_topic' };
  }
  const continuationWording =
    startsWithAny(input.text, CONTINUE_PREFIXES) ||
    CONTINUE_PHRASES.some((phrase) => input.text.includes(phrase));
  if (continuationWording && gap !== undefined && gap < SIX_HOURS_MS) {
    return { kind: 'continue', reason: 'explicit_continue' };
  }

  if (gap === undefined) return { kind: 'new', reason: 'gap_unknown' };
  if (gap >= SIX_HOURS_MS) {
    return { kind: 'new', reason: 'gap_over_6h', detail: `${Math.round(gap / 60_000)}m` };
  }

  const previousCodes = new Set(previous.symbols.map((symbol) => codeKey(symbol.code)));
  const nextCodes = extractSymbols(input.text, input.symbolNames);
  if (nextCodes.length > 0 && previousCodes.size > 0) {
    const overlap = nextCodes.some((code) => previousCodes.has(codeKey(code)));
    return overlap
      ? { kind: 'continue', reason: 'symbols_overlap', detail: nextCodes.join(',') }
      : { kind: 'new', reason: 'symbols_disjoint', detail: nextCodes.join(',') };
  }

  if (gap < TEN_MINUTES_MS) {
    return { kind: 'continue', reason: 'gap_under_10m', detail: `${Math.round(gap / 60_000)}m` };
  }

  return { kind: 'uncertain', reason: 'rules_uncertain', detail: `${Math.round(gap / 60_000)}m` };
}

/** Backward-friendly alias used by the service. */
export const decide = decideSegment;
