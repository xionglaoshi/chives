/** A-share symbol parsing shared by segmentation and incremental task symbols. */

import type { SummarySymbol } from './store/types.js';

const CODE_PATTERN = /(?<!\d)(\d{6})(?:\.(SH|SZ|BJ))?(?!\d)/gi;
const CODE_ONLY_PATTERN = /^(\d{6})(?:\.(SH|SZ|BJ))?$/i;
/** Bot replies such as `贵州茅台（600519）`, `宁德时代(300750.SZ)` or `比亚迪（002594.SZ）`. */
const BOT_PAIR_PATTERN =
  /([\u4e00-\u9fffA-B]{2,8})\s*[（(]\s*(\d{6}(?:\.(?:SH|SZ|BJ))?)\s*[)）]/gi;

/** Infers the exchange suffix when the user omitted it; an explicit suffix wins. */
export function normalizeSymbolCode(code: string): string {
  const trimmed = code.trim();
  const match = CODE_ONLY_PATTERN.exec(trimmed);
  if (match === null) return trimmed.toUpperCase();
  const digits = match[1] ?? '';
  const explicit = match[2]?.toUpperCase();
  if (explicit !== undefined) return `${digits}.${explicit}`;
  switch (digits[0]) {
    case '6':
      return `${digits}.SH`;
    case '0':
    case '3':
      return `${digits}.SZ`;
    case '4':
    case '8':
    case '9':
      return `${digits}.BJ`;
    default:
      return digits;
  }
}

/** User text: literal 6-digit codes plus names already present in `symbol_names`. */
export function extractUserSymbols(
  text: string,
  symbolNames: Readonly<Record<string, string>> = {},
): SummarySymbol[] {
  const found = new Map<string, string>();
  for (const match of text.matchAll(CODE_PATTERN)) {
    const raw = match[0];
    if (raw === undefined) continue;
    const code = normalizeSymbolCode(raw);
    if (!found.has(code)) found.set(code, '');
  }
  for (const [name, code] of Object.entries(symbolNames)) {
    if (name === '' || !text.includes(name)) continue;
    const normalized = normalizeSymbolCode(code);
    found.set(normalized, name);
  }
  return [...found].map(([code, name]) => ({ code, name }));
}

/** Bot replies: `中文名（代码）` pairs, which also teach the name table. */
export function extractBotSymbols(text: string): SummarySymbol[] {
  const found = new Map<string, string>();
  for (const match of text.matchAll(BOT_PAIR_PATTERN)) {
    const name = match[1];
    const rawCode = match[2];
    if (name === undefined || rawCode === undefined) continue;
    found.set(normalizeSymbolCode(rawCode), name);
  }
  return [...found].map(([code, name]) => ({ code, name }));
}
