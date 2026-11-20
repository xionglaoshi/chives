import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { BotSummary, MarketDashboardDto } from '../src/api/protocol.js';
import type { DashboardService } from '../src/dashboard/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig } from './support.js';

const MARKET: MarketDashboardDto = {
  indexes: [],
  amountYuan: null,
  breadth: { up: null, down: null, upRatioPct: null },
  limit: { limitUp: null, limitDown: null },
  asOf: '2026-11-17T15:00:00+08:00',
  session: 'closed',
  stale: false,
};

const PORTFOLIO = {
  asOf: null,
  cash: null,
  summary: {
    positionCount: 0,
    pricedCount: 0,
    unpricedCount: 0,
    totalMarketValue: null,
    totalPnl: null,
    totalPnlPct: null,
    todayPnl: null,
    todayPnlPct: null,
  },
  positions: [],
  unpriced: [],
  empty: true,
  warnings: [],
};

function fakeDashboard(overrides: Partial<DashboardService> = {}): DashboardService {
  return {
    market: vi.fn(async () => ({ status: 200, body: MARKET })),
    portfolio: vi.fn(async () => ({ status: 200, body: PORTFOLIO })),
    ...overrides,
  } as unknown as DashboardService;
}

describe('dashboard routes', () => {
  let app: ChivesApp;
  let baseUrl: string;
  let dataDir: string;
  let dashboard: DashboardService;

  beforeEach(async () => {
    dataDir = await mkdtemp(join(tmpdir(), 'chives-dashboard-'));
    dashboard = fakeDashboard();
    app = createApp({
      config: testConfig(dataDir),
      driver: new FakeDriver(),
      dashboard,
    });
    baseUrl = await listen(app.server);
  });

  afterEach(async () => {
    await closeServer(app.server);
    await app.close();
    await rm(dataDir, { recursive: true, force: true });
  });

  it('serves the market panel without caching', async () => {
    const response = await fetch(`${baseUrl}/api/dashboard/market`);

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toEqual(MARKET);
  });

  it('serves the portfolio panel without caching', async () => {
    const response = await fetch(`${baseUrl}/api/dashboard/portfolio`);

    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toEqual(PORTFOLIO);
  });

  it('rejects non-GET requests', async () => {
    const response = await fetch(`${baseUrl}/api/dashboard/market`, { method: 'POST' });
    expect(response.status).toBe(405);
  });

  it('relays a 503 body from the dashboard service', async () => {
    dashboard = fakeDashboard({
      market: vi.fn(async () => ({
        status: 503,
        body: { error: { code: 'market_unavailable', message: '行情网关连不上' } },
      })),
    });
    await closeServer(app.server);
    await app.close();
    app = createApp({ config: testConfig(dataDir), driver: new FakeDriver(), dashboard });
    baseUrl = await listen(app.server);

    const response = await fetch(`${baseUrl}/api/dashboard/market`);
    expect(response.status).toBe(503);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toEqual({
      error: { code: 'market_unavailable', message: '行情网关连不上' },
    });
  });

  it('passes the panels field through the bot DTO', async () => {
    const response = await fetch(`${baseUrl}/api/bots`);
    const bots = (await response.json()) as BotSummary[];
    const expert = bots.find((bot) => bot.id === 'expert');
    const other = bots.find((bot) => bot.id === 'equity-analyst');

    expect(expert?.panels).toEqual(['market', 'portfolio', 'watches']);
    expect(other?.panels).toEqual([]);
  });
});
