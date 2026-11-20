import { execFile } from 'node:child_process';

import { describe, expect, it, vi } from 'vitest';

import { DashboardService } from '../src/dashboard/index.js';
import {
  createSnapshotRunner,
  parseSnapshot,
  PortfolioError,
} from '../src/dashboard/portfolio.js';

const SNAPSHOT = {
  status: 'ready',
  as_of: '2026-11-17T10:30:00+08:00',
  cash: 5000.0,
  summary: {
    position_count: 1,
    priced_count: 1,
    unpriced_count: 0,
    total_market_value: 10000.0,
    total_cost: 8000.0,
    total_pnl: 2000.0,
    total_pnl_pct: 25.0,
    today_pnl: 1000.0,
    today_pnl_pct: 12.5,
  },
  positions: [
    {
      code: '600000.SH',
      name: '浦发银行',
      qty: 1000,
      cost_price: 8.0,
      price: 10.0,
      prev_close: 9.0,
      change_pct: 11.11,
      market_value: 10000.0,
      pnl: 2000.0,
      pnl_pct: 25.0,
      today_pnl: 1000.0,
      price_available: true,
    },
  ],
  unpriced: [],
  warnings: [{ code: 'stale_quote', message: '非交易时段' }],
};

describe('parseSnapshot', () => {
  it('maps the CLI JSON to the dashboard DTO', () => {
    const dto = parseSnapshot(JSON.stringify(SNAPSHOT));

    expect(dto.asOf).toBe('2026-11-17T10:30:00+08:00');
    expect(dto.cash).toBe(5000);
    expect(dto.empty).toBe(false);
    expect(dto.positions).toEqual([
      {
        code: '600000.SH',
        name: '浦发银行',
        qty: 1000,
        costPrice: 8,
        price: 10,
        prevClose: 9,
        changePct: 11.11,
        marketValue: 10000,
        pnl: 2000,
        pnlPct: 25,
        todayPnl: 1000,
        priceAvailable: true,
      },
    ]);
    expect(dto.summary.todayPnl).toBe(1000);
    expect(dto.summary.todayPnlPct).toBe(12.5);
    expect(dto.warnings).toEqual([{ code: 'stale_quote', message: '非交易时段' }]);
  });

  it('keeps an unset cash value and an empty book as null/empty', () => {
    const dto = parseSnapshot(
      JSON.stringify({
        status: 'empty',
        as_of: null,
        cash: null,
        summary: {},
        positions: [],
        unpriced: [],
        warnings: [],
      }),
    );
    expect(dto.cash).toBeNull();
    expect(dto.empty).toBe(true);
    expect(dto.positions).toEqual([]);
    expect(dto.summary.positionCount).toBe(0);
  });

  it('rejects non-JSON and error payloads', () => {
    expect(() => parseSnapshot('not json')).toThrow(PortfolioError);
    expect(() => parseSnapshot(JSON.stringify({ status: 'error' }))).toThrow(PortfolioError);
  });
});

describe('createSnapshotRunner', () => {
  it('runs the venv python with only DSH_HOME, PATH and HOME', async () => {
    const calls: Array<{
      file: string;
      args: string[];
      options: { cwd?: string; env?: NodeJS.ProcessEnv; timeout?: number };
    }> = [];
    const exec = ((
      file: string,
      args: string[],
      options: { cwd?: string; env?: NodeJS.ProcessEnv; timeout?: number },
      callback: (error: Error | null, stdout: string) => void,
    ) => {
      calls.push({ file, args, options });
      callback(null, '{"status":"empty"}');
    }) as unknown as typeof execFile;

    const runner = createSnapshotRunner({
      repoRoot: '/repo',
      dshHome: '/tmp/dsh-home',
      exec,
    });
    await expect(runner()).resolves.toBe('{"status":"empty"}');

    expect(calls).toHaveLength(1);
    expect(calls[0]?.file).toBe('/repo/packages/portfolio-mcp/.venv/bin/python');
    expect(calls[0]?.args).toEqual(['-m', 'portfolio_mcp', 'snapshot']);
    expect(calls[0]?.options.cwd).toBe('/repo/packages/portfolio-mcp');
    expect(Object.keys(calls[0]?.options.env ?? {}).sort()).toEqual(['DSH_HOME', 'HOME', 'PATH']);
    expect(calls[0]?.options.env?.['DSH_HOME']).toBe('/tmp/dsh-home');
    expect(calls[0]?.options.timeout).toBe(15_000);
  });

  it('turns a timeout or non-zero exit into PortfolioError', async () => {
    const exec = ((
      _file: string,
      _args: string[],
      _options: unknown,
      callback: (error: Error | null, stdout: string) => void,
    ) => {
      const error = Object.assign(new Error('Command failed: killed'), { killed: true });
      callback(error, '');
    }) as unknown as typeof execFile;

    const runner = createSnapshotRunner({ repoRoot: '/repo', dshHome: '/tmp', exec });
    await expect(runner()).rejects.toBeInstanceOf(PortfolioError);
  });
});

describe('DashboardService.portfolio', () => {
  function makeService(snapshot: () => Promise<string>, clock: () => Date): DashboardService {
    return new DashboardService({
      gateway: { baseUrl: 'http://127.0.0.1:1' },
      snapshot,
      now: clock,
    });
  }

  it('caches the snapshot for 15 seconds and merges concurrent loads', async () => {
    const snapshot = vi.fn(async () => JSON.stringify(SNAPSHOT));
    let clock = new Date('2026-11-17T02:00:00Z');
    const service = makeService(snapshot, () => clock);

    const [first, second] = await Promise.all([service.portfolio(), service.portfolio()]);
    expect(first.status).toBe(200);
    expect(second.status).toBe(200);
    expect(snapshot).toHaveBeenCalledTimes(1);

    clock = new Date(clock.getTime() + 14_000);
    await service.portfolio();
    expect(snapshot).toHaveBeenCalledTimes(1);
    clock = new Date(clock.getTime() + 2_000);
    await service.portfolio();
    expect(snapshot).toHaveBeenCalledTimes(2);
  });

  it('answers 503 when the snapshot command fails', async () => {
    const service = makeService(async () => {
      throw new PortfolioError('持仓暂时取不到，稍后再试');
    }, () => new Date('2026-11-17T02:00:00Z'));

    const result = await service.portfolio();
    expect(result.status).toBe(503);
    expect(result.body).toEqual({
      error: { code: 'portfolio_unavailable', message: '持仓暂时取不到，稍后再试' },
    });
  });
});
