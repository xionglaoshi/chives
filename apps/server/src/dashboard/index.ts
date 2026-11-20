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
  private readonly portfolioCache: CoalescedTtlCache<PortfolioDashboardDto>;

  constructor(options: DashboardOptions) {
    this.gateway = options.gateway;
    this.snapshot = options.snapshot;
    this.now = options.now ?? (() => new Date());
    this.marketCache = new CoalescedTtlCache<MarketDashboardDto>(() => this.now().getTime());
    this.portfolioCache = new CoalescedTtlCache<PortfolioDashboardDto>(() => this.now().getTime());
  }

  private readonly boardCaches = new Map<string, CoalescedTtlCache<unknown>>();

  async board(part: 'gainers' | 'active' | 'sectors' | 'world'): Promise<DashboardResult> {
    const cache = this.boardCaches.get(part) ?? new CoalescedTtlCache<unknown>(() => this.now().getTime());
    this.boardCaches.set(part, cache);
    try {
      const body = await cache.get(30_000, async () => {
        if (part === 'world') return worldIndices();
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
