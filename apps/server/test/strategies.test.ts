import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { StrategyPoolsDto } from '../src/api/protocol.js';
import { StrategyService } from '../src/strategies/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig } from './support.js';

const POOLS: StrategyPoolsDto = {
  strategy: 'zhushenglang',
  name: '主升浪',
  date: '2026-11-17',
  latest_date: '2026-11-17',
  status: '已计算',
  counts: { first: 1, main: 1 },
  pools: {
    first: [{ code: '600519.SH', name: '贵州茅台', score: 85, k: 12, status: '优先级一', priority: 'p1' }],
    main: [{ code: '600519.SH', name: '贵州茅台', score: 90, gain: 0.12, drawdown: 0.01, ma10_count: 1 }]
  }
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body
  } as Response;
}

describe('StrategyService', () => {
  it('caches one strategy/date for 60 seconds and merges concurrent loads', async () => {
    let now = 1_000;
    const fetchMock = vi.fn(async () => jsonResponse(POOLS));
    const service = new StrategyService({
      baseUrl: 'http://127.0.0.1:8869',
      fetchImpl: fetchMock as unknown as typeof fetch,
      now: () => now
    });
    const first = await service.pools('zhushenglang', '2026-11-17');
    const second = await service.pools('zhushenglang', '2026-11-17');
    expect(first).toEqual({ status: 200, body: POOLS });
    expect(second).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      'http://127.0.0.1:8869/v1/zhushenglang/pools?date=2026-11-17'
    );

    now += 60_001;
    await service.pools('zhushenglang', '2026-11-17');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('returns the hub Chinese error instead of inventing data', async () => {
    const service = new StrategyService({
      baseUrl: 'http://127.0.0.1:8869',
      fetchImpl: (async () =>
        jsonResponse({ ok: false, message: '策略还没有计算过任何交易日' }, 503)) as unknown as typeof fetch
    });
    await expect(service.pools('zhushenglang')).resolves.toEqual({
      status: 503,
      body: { ok: false, message: '策略还没有计算过任何交易日' }
    });
  });
});

describe('GET /api/strategies/:id/pools', () => {
  let app: ChivesApp;
  let baseUrl: string;
  let dataDir: string;
  const pools = vi.fn(async () => ({ status: 200, body: POOLS }));

  beforeEach(async () => {
    dataDir = await mkdtemp(join(tmpdir(), 'chives-strategy-api-'));
    const strategies = { pools } as unknown as StrategyService;
    app = createApp({
      config: testConfig(dataDir),
      driver: new FakeDriver(),
      strategies
    });
    baseUrl = await listen(app.server);
  });

  afterEach(async () => {
    await closeServer(app.server);
    await app.close();
    await rm(dataDir, { recursive: true, force: true });
    pools.mockClear();
  });

  it('forwards for a bot that subscribes to the strategy', async () => {
    const response = await fetch(
      `${baseUrl}/api/strategies/zhushenglang/pools?botId=zhushenglang&date=2026-11-17`
    );
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('no-store');
    await expect(response.json()).resolves.toEqual(POOLS);
    expect(pools).toHaveBeenCalledWith('zhushenglang', '2026-11-17');
  });

  it('rejects a bot without the strategy, a missing botId and an unknown bot', async () => {
    const forbidden = await fetch(
      `${baseUrl}/api/strategies/zhushenglang/pools?botId=expert`
    );
    expect(forbidden.status).toBe(403);
    await expect(forbidden.json()).resolves.toMatchObject({
      error: { message: '这个 bot 没有订阅该策略' }
    });

    const missing = await fetch(`${baseUrl}/api/strategies/zhushenglang/pools`);
    expect(missing.status).toBe(400);

    const unknown = await fetch(`${baseUrl}/api/strategies/zhushenglang/pools?botId=ghost`);
    expect(unknown.status).toBe(404);
    expect(pools).not.toHaveBeenCalled();
  });

  it('rejects non-GET requests', async () => {
    const response = await fetch(
      `${baseUrl}/api/strategies/zhushenglang/pools?botId=zhushenglang`,
      { method: 'POST' }
    );
    expect(response.status).toBe(405);
  });
});
