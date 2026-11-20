import type { MarketSession } from '@chives/server/protocol';

export const SESSION_TEXT: Record<MarketSession, string> = {
  pre_open: '盘前',
  auction: '集合竞价',
  trading: '交易中',
  lunch_break: '午休',
  closed: '盘后',
  holiday: '休市'
};

export type PriceDirection = 'up' | 'down' | 'flat';

export function priceDirection(value: number | null): PriceDirection {
  if (value === null || !Number.isFinite(value) || value === 0) return 'flat';
  return value > 0 ? 'up' : 'down';
}

export function formatPrice(value: number | null, digits = 2): string {
  return value === null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

/** `+0.62%` / `-0.4%`; a missing value is an em dash. */
export function formatPercent(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const text = Math.abs(value).toFixed(digits);
  if (value === 0) return `0.00%`;
  return `${value > 0 ? '+' : '-'}${text}%`;
}

/** Whole-yuan amounts in 万 / 亿 / 万亿. */
export function formatAmount(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)} 万亿`;
  if (abs >= 1e8) return `${(value / 1e8).toFixed(0)} 亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(0)} 万`;
  return value.toFixed(0);
}

/** `HH:MM` of an ISO instant in Beijing time; `—` when unparseable. */
export function formatAsOf(iso: string | null): string {
  if (iso === null || iso === '') return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).format(date);
}

export const HIDDEN = '****';
