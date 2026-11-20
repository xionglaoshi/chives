/** Builds the right-hand market panel from the cn-market-gateway. */

import type {
  MarketDashboardDto,
  MarketIndexDto,
  MarketSession,
} from '../api/protocol.js';
import { shanghaiDayKey, shanghaiParts } from '../time.js';
import { callGateway, type GatewayOptions } from './gateway.js';

/** The five indices the sidebar always shows, in display order. */
const SIDEBAR_INDEXES: ReadonlyArray<{ code: string; fallbackName: string }> = [
  { code: '000001.SH', fallbackName: '上证指数' },
  { code: '399001.SZ', fallbackName: '深证成指' },
  { code: '399006.SZ', fallbackName: '创业板指' },
  { code: '000300.SH', fallbackName: '沪深300' },
  { code: '000688.SH', fallbackName: '科创50' },
];

interface OverviewData {
  indexes?: unknown;
  breadth?: unknown;
  limit?: unknown;
  amount_yuan?: unknown;
}

interface BarsData {
  bars?: unknown;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {};
}

/** Trading session of the A-share market at `date` (Asia/Shanghai, no DST). */
export function marketSession(date: Date): MarketSession {
  const parts = shanghaiParts(date);
  const weekday = new Date(
    Date.UTC(parts.year, parts.month - 1, parts.day),
  ).getUTCDay();
  if (weekday === 0 || weekday === 6) return 'holiday';
  const minutes = parts.hour * 60 + parts.minute;
  if (minutes < 555) return 'pre_open'; // before 09:15
  if (minutes < 570) return 'auction'; // 09:15–09:30 call auction
  if ((minutes >= 570 && minutes <= 690) || (minutes >= 780 && minutes <= 900)) {
    return 'trading';
  }
  if (minutes > 690 && minutes < 780) return 'lunch_break';
  return 'closed';
}

/** 8s while quotes move (auction and trading), 1 minute before the open, 5 minutes otherwise. */
export function marketCacheTtlMs(session: MarketSession): number {
  if (session === 'trading' || session === 'auction') return 8_000;
  if (session === 'pre_open') return 60_000;
  return 300_000;
}

/** Intraday bars come from a 30-requests-a-minute upstream; keep each series for a minute. */
const SPARK_TTL_MS = 60_000;
const sparkCache = new Map<string, { at: number; closes: number[] }>();

/** Tests start from an empty mini-chart cache. */
export function clearSparkCache(): void {
  sparkCache.clear();
}

async function loadSpark(
  gateway: GatewayOptions,
  code: string,
  day: string,
  now: Date,
): Promise<number[]> {
  const key = `${code}|${day}`;
  const cached = sparkCache.get(key);
  if (cached !== undefined && now.getTime() - cached.at < SPARK_TTL_MS) return cached.closes;
  const closes = await fetchSpark(gateway, code, day);
  if (closes.length > 0) sparkCache.set(key, { at: now.getTime(), closes });
  return closes;
}

async function fetchSpark(
  gateway: GatewayOptions,
  code: string,
  day: string,
): Promise<number[]> {
  try {
    const payload = await callGateway<BarsData>(gateway, 'market_bars', {
      code,
      interval: '5m',
      start: day,
      end: day,
      limit: 60,
    });
    const bars = Array.isArray(payload.data?.bars) ? payload.data.bars : [];
    const closes: number[] = [];
    for (const bar of bars) {
      const close = num(record(bar)['close']);
      if (close !== null) closes.push(close);
    }
    return closes;
  } catch {
    // A missing intraday series only removes the mini chart; the panel still renders.
    return [];
  }
}

export async function loadMarket(
  gateway: GatewayOptions,
  now: Date,
): Promise<MarketDashboardDto> {
  const session = marketSession(now);
  const overview = await callGateway<OverviewData>(gateway, 'market_overview', {});
  const rawIndexes = Array.isArray(overview.data?.indexes) ? overview.data.indexes : [];
  const byCode = new Map<string, Record<string, unknown>>();
  for (const item of rawIndexes) {
    const entry = record(item);
    const code = str(entry['code']);
    if (code !== null) byCode.set(code, entry);
  }

  const day = shanghaiDayKey(now);
  const sparks = await Promise.all(
    SIDEBAR_INDEXES.map((entry) => loadSpark(gateway, entry.code, day, now)),
  );

  const indexes: MarketIndexDto[] = SIDEBAR_INDEXES.map((entry, index) => {
    const quote = byCode.get(entry.code);
    return {
      code: entry.code,
      name: str(quote?.['name']) ?? entry.fallbackName,
      price: num(quote?.['price']),
      changePct: num(quote?.['change_pct']),
      amountYuan: num(quote?.['amount_yuan']),
      spark: sparks[index] ?? [],
    };
  });

  const breadth = record(overview.data?.breadth);
  const limit = record(overview.data?.limit);
  return {
    indexes,
    amountYuan: num(overview.data?.amount_yuan),
    breadth: {
      up: num(breadth['up_count']),
      down: num(breadth['down_count']),
      upRatioPct: num(breadth['up_ratio_pct']),
    },
    limit: {
      limitUp: num(limit['limit_up_count']),
      limitDown: num(limit['limit_down_count']),
    },
    asOf: overview.as_of,
    session,
    stale: overview.stale === true,
  };
}
