/** `GET /api/dashboard/*`: loopback-only market and portfolio panels for the expert sidebar. */

import type {
  MarketDashboardDto,
  PortfolioDashboardDto,
} from '../api/protocol.js';
import { CoalescedTtlCache } from './cache.js';
import { worldIndices } from './world.js';
import { callGateway, type GatewayOptions } from './gateway.js';
import { loadMarket, marketCacheTtlMs, marketSession } from './market.js';
import { parseSnapshot, PortfolioError, type SnapshotRunner } from './portfolio.js';

export interface DashboardResult {
  status: number;
  body: unknown;
}

export interface DashboardOptions {
  gateway: GatewayOptions;
  snapshot: SnapshotRunner;
  now?: () => Date;
}

const PORTFOLIO_TTL_MS = 15_000;

function failure(code: string, message: string): DashboardResult {
  return { status: 503, body: { error: { code, message } } };
}

export class DashboardService {
  private readonly gateway: GatewayOptions;
  private readonly snapshot: SnapshotRunner;
  private readonly now: () => Date;
  private readonly marketCache: CoalescedTtlCache<MarketDashboardDto>;
  private portfolioCache: CoalescedTtlCache<PortfolioDashboardDto>;

  constructor(options: DashboardOptions) {
    this.gateway = options.gateway;
    this.snapshot = options.snapshot;
    this.now = options.now ?? (() => new Date());
    this.marketCache = new CoalescedTtlCache<MarketDashboardDto>(() => this.now().getTime());
    this.portfolioCache = new CoalescedTtlCache<PortfolioDashboardDto>(() => this.now().getTime());
  }

  private readonly boardCaches = new Map<string, CoalescedTtlCache<unknown>>();

  async board(part: 'gainers' | 'active' | 'sectors' | 'world' | 'limit-up'): Promise<DashboardResult> {
    const cache = this.boardCaches.get(part) ?? new CoalescedTtlCache<unknown>(() => this.now().getTime());
    this.boardCaches.set(part, cache);
    try {
      const body = await cache.get(30_000, async () => {
        if (part === 'world') return worldIndices();
        if (part === 'limit-up') return this.limitUp();
        const sector = part === 'sectors';
        const result = await callGateway<{rows: unknown[]}>(this.gateway,
          sector ? 'market_sectors' : 'market_movers',
          sector ? {kind:'industry',sort:'amount',limit:12} : {kind:part,limit:7});
        return {rows: result.data.rows, asOf: result.as_of, stale: result.stale === true};
      });
      return {status:200,body};
    } catch {
      return failure('market_unavailable','暂时取不到行情，稍后自动重试');
    }
  }

  private async limitUp() {
    type PoolRow = { code: string; name: string; change_pct: number | null };
    type Quote = { code: string; volume_shares: number | null };
    const pool = await callGateway<{ rows: PoolRow[]; count: number; date: string }>(
      this.gateway, 'market_limit_pool', { kind: 'zt', limit: 500 }
    );
    const byCode = new Map(pool.data.rows.map(row => [row.code, row]));
    if (byCode.size < pool.data.count) throw new Error('Incomplete limit-up pool');

    const codes = [...byCode.keys()];
    const volumes = new Map<string, number>();
    let stale = pool.stale === true;
    for (let start = 0; start < codes.length; start += 20) {
      const quotes = await callGateway<{ quotes: Quote[] }>(
        this.gateway, 'market_quote', { codes: codes.slice(start, start + 20) }
      );
      stale ||= quotes.stale === true;
      for (const quote of quotes.data.quotes) {
        if (quote.volume_shares != null) volumes.set(quote.code, quote.volume_shares);
      }
    }
    if (codes.length > 20 && volumes.size !== codes.length) throw new Error('Incomplete trading volumes');

    const rows = [...byCode.values()]
      .map(row => ({...row, volume_shares: volumes.get(row.code) ?? null}))
      .sort((a, b) => (b.volume_shares ?? -1) - (a.volume_shares ?? -1) || a.code.localeCompare(b.code))
      .slice(0, 20);
    return { rows, asOf: pool.as_of, stale, tradingDate: pool.data.date };
  }

  invalidatePortfolio(): void {
    this.portfolioCache = new CoalescedTtlCache<PortfolioDashboardDto>(() => this.now().getTime());
  }

  async market(): Promise<DashboardResult> {
    const ttl = marketCacheTtlMs(marketSession(this.now()));
    try {
      const body = await this.marketCache.get(ttl, () => loadMarket(this.gateway, this.now()));
      return { status: 200, body };
    } catch {
      return failure('market_unavailable', '行情网关连不上，请确认 cn-market-gateway 正在运行');
    }
  }

  async portfolio(): Promise<DashboardResult> {
    try {
      const body = await this.portfolioCache.get(PORTFOLIO_TTL_MS, async () =>
        parseSnapshot(await this.snapshot()),
      );
      return { status: 200, body };
    } catch (error) {
      return failure(
        'portfolio_unavailable',
        error instanceof PortfolioError ? error.message : '持仓暂时取不到，稍后再试',
      );
    }
  }
}
