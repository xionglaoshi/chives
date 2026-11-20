import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { DashboardOptions } from '../src/dashboard/index.js';
import { DashboardService } from '../src/dashboard/index.js';
import {
  clearSparkCache,
  loadMarket,
  marketCacheTtlMs,
  marketSession
} from '../src/dashboard/market.js';

beforeEach(() => {
  clearSparkCache();
});

const OVERVIEW = {
  status: 'ok',
  as_of: '2026-11-17T15:00:00+08:00',
  data: {
    indexes: [
      { code: '000001.SH', name: '上证指数', price: 3580.1, change_pct: -0.62, amount_yuan: 681622296204 },
      { code: '399001.SZ', name: '深证成指', price: 10647.7, change_pct: -0.4, amount_yuan: 759832962733 },
      { code: '399006.SZ', name: '创业板指', price: 2295.2, change_pct: -1.07, amount_yuan: 362237150547 },
      { code: '000300.SH', name: '沪深300', price: 3972.64, change_pct: -0.18, amount_yuan: 403051162644 },
      { code: '000688.SH', name: '科创50', price: 1221.24, change_pct: 0.62, amount_yuan: 95664155764 },
    ],
    breadth: { up_count: 1236, down_count: 3930, up_ratio_pct: 23.93 },
    limit: { limit_up_count: 37, limit_down_count: 70 },
    amount_yuan: 1441455258937,
  },
  stale: false,
};

function barsFor(code: string): unknown {
  return {
    status: 'ok',
    as_of: '2026-11-17T15:00:00+08:00',
    data: {
      code,
      interval: '5m',
      bars: [
        { time: '2026-11-17T09:35:00+08:00', close: 3572.87 },
        { time: '2026-11-17T09:40:00+08:00', close: 3584.39 },
      ],
    },
  };
}

function fakeGateway(
  handler?: (tool: string) => unknown,
): { fetchImpl: typeof fetch; tools: string[] } {
  const tools: string[] = [];
  const fetchImpl = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body)) as { tool: string; args: Record<string, unknown> };
    tools.push(body.tool);
    const fallback =
      body.tool === 'market_overview' ? OVERVIEW : barsFor(String(body.args['code']));
    const payload = handler === undefined ? fallback : (handler(body.tool) ?? fallback);
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as unknown as typeof fetch;
  return { fetchImpl, tools };
}

describe('marketSession', () => {
  const at = (iso: string): Date => new Date(iso);

  it('covers the A-share trading windows in Asia/Shanghai', () => {
    expect(marketSession(at('2026-11-17T01:14:00Z'))).toBe('pre_open'); // 09:14
    expect(marketSession(at('2026-11-17T01:15:00Z'))).toBe('auction'); // 09:15
    expect(marketSession(at('2026-11-17T01:29:00Z'))).toBe('auction'); // 09:29
    expect(marketSession(at('2026-11-17T01:30:00Z'))).toBe('trading'); // 09:30
    expect(marketSession(at('2026-11-17T03:30:00Z'))).toBe('trading'); // 11:30
    expect(marketSession(at('2026-11-17T03:31:00Z'))).toBe('lunch_break'); // 11:31
    expect(marketSession(at('2026-11-17T04:59:00Z'))).toBe('lunch_break'); // 12:59
    expect(marketSession(at('2026-11-17T05:00:00Z'))).toBe('trading'); // 13:00
    expect(marketSession(at('2026-11-17T07:00:00Z'))).toBe('trading'); // 15:00
    expect(marketSession(at('2026-11-17T07:01:00Z'))).toBe('closed'); // 15:01
  });

  it('treats weekends as holidays', () => {
    expect(marketSession(at('2026-11-21T02:00:00Z'))).toBe('holiday');
  });

  it('keeps 20s during trading and 5 minutes otherwise', () => {
    expect(marketCacheTtlMs('trading')).toBe(8_000);
    expect(marketCacheTtlMs('auction')).toBe(8_000);
    expect(marketCacheTtlMs('pre_open')).toBe(60_000);
    expect(marketCacheTtlMs('lunch_break')).toBe(300_000);
    expect(marketCacheTtlMs('closed')).toBe(300_000);
    expect(marketCacheTtlMs('holiday')).toBe(300_000);
  });
});

describe('loadMarket', () => {
  it('keeps the five sidebar indices in order with their sparkline', async () => {
    const { fetchImpl } = fakeGateway();
    const now = new Date('2026-11-17T05:00:00Z');
    const dto = await loadMarket({ baseUrl: 'http://127.0.0.1:8868', fetchImpl }, now);

    expect(dto.indexes.map((row) => row.code)).toEqual([
      '000001.SH',
      '399001.SZ',
      '399006.SZ',
      '000300.SH',
      '000688.SH',
    ]);
    expect(dto.indexes[0]).toEqual({
      code: '000001.SH',
      name: '上证指数',
      price: 3580.1,
      changePct: -0.62,
      amountYuan: 681622296204,
      spark: [3572.87, 3584.39],
    });
    expect(dto.amountYuan).toBe(1441455258937);
    expect(dto.breadth).toEqual({ up: 1236, down: 3930, upRatioPct: 23.93 });
    expect(dto.limit).toEqual({ limitUp: 37, limitDown: 70 });
    expect(dto.asOf).toBe('2026-11-17T15:00:00+08:00');
    expect(dto.session).toBe('trading');
    expect(dto.stale).toBe(false);
  });

  it('keeps the panel when the mini chart cannot be fetched', async () => {
    const { fetchImpl } = fakeGateway((tool) => {
      if (tool === 'market_bars') throw new Error('bars down');
      return undefined;
    });
    const dto = await loadMarket(
      { baseUrl: 'http://127.0.0.1:8868', fetchImpl },
      new Date('2026-11-17T05:00:00Z'),
    );
    expect(dto.indexes).toHaveLength(5);
    expect(dto.indexes.every((row) => row.spark.length === 0)).toBe(true);
  });
});

describe('DashboardService.market', () => {
  function makeService(
    fetchImpl: typeof fetch,
    clock: () => Date,
  ): DashboardService {
    const options: DashboardOptions = {
      gateway: { baseUrl: 'http://127.0.0.1:8868', fetchImpl },
      snapshot: async () => '',
      now: clock,
    };
    return new DashboardService(options);
  }

  it('coalesces concurrent requests into one gateway round', async () => {
    const { fetchImpl, tools } = fakeGateway();
    const service = makeService(fetchImpl, () => new Date('2026-11-17T05:00:00Z'));

    const [first, second] = await Promise.all([service.market(), service.market()]);

    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(tools.filter((tool) => tool === 'market_overview')).toHaveLength(1);
    expect(tools.filter((tool) => tool === 'market_bars')).toHaveLength(5);
  });

  it('caches quotes for 8s while trading, mini charts for a minute, and 5 minutes otherwise', async () => {
    const { fetchImpl, tools } = fakeGateway();
    let clock = new Date('2026-11-17T05:00:00Z'); // 13:00 Shanghai, trading
    const service = makeService(fetchImpl, () => clock);

    await service.market();
    expect(tools).toHaveLength(6);
    clock = new Date(clock.getTime() + 7_000);
    await service.market();
    expect(tools).toHaveLength(6);
    // Quotes refresh after 8s; the five mini charts stay cached for a minute.
    clock = new Date(clock.getTime() + 2_000);
    await service.market();
    expect(tools).toHaveLength(7);
    clock = new Date(clock.getTime() + 60_000);
    await service.market();
    expect(tools).toHaveLength(13);

    // 16:00 Shanghai: five-minute cache.
    clock = new Date('2026-11-17T08:00:00Z');
    await service.market();
    expect(tools).toHaveLength(19);
    clock = new Date(clock.getTime() + 60_000);
    await service.market();
    expect(tools).toHaveLength(19);
  });

  it('answers 503 with a Chinese message when the gateway is unreachable', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const service = makeService(fetchImpl, () => new Date('2026-11-17T05:00:00Z'));

    const result = await service.market();

    expect(result.status).toBe(503);
    expect(result.body).toMatchObject({
      error: { code: 'market_unavailable', message: expect.stringContaining('cn-market-gateway') },
    });
  });
});
