import { describe, expect, it, vi } from 'vitest';
import { DashboardService } from './index.js';

function dashboard(count: number, actual = count) {
  const candidates = Array.from({length: 40}, (_, i) => ({
    code: String(i), name: '股票' + i, change_pct: -20 + i / 3,
  }));
  const fetchImpl = vi.fn<typeof fetch>(async (_url, init) => {
    const { tool, args } = JSON.parse(String(init?.body));
    const data = tool === 'market_movers'
      ? {rows: candidates.slice(0, args.limit)}
      : {quotes: (args.codes as string[]).map(code => ({
        code, price: 10, limit_down: Number(code) < actual ? 10 : 9,
        volume_shares: Number(code) + 1,
      }))};
    return Response.json({status: 'ok', as_of: '2026-11-24T06:00:00Z', data});
  });
  const service = new DashboardService({gateway: {baseUrl: 'http://localhost', fetchImpl}, snapshot: async () => ''});
  vi.spyOn(service, 'market').mockResolvedValue({status: 200, body: {limit: {limitDown: count}}});
  return service;
}

describe('limit-down board', () => {
  it('uses the 20 deepest declines if fewer than 20 stocks hit their limit', async () => {
    const result = await dashboard(6).board('limit-down');
    expect(result).toMatchObject({status: 200, body: {order: 'change',
      rows: Array.from({length: 20}, (_, i) => expect.objectContaining({code: String(i)})),
    }});
  });

  it('keeps all 20 limit-down stocks in decline order when exactly 20 hit', async () => {
    const result = await dashboard(20).board('limit-down');
    expect(result).toMatchObject({status: 200, body: {order: 'change',
      rows: Array.from({length: 20}, (_, i) => expect.objectContaining({code: String(i)})),
    }});
  });

  it('selects the 20 highest volumes among confirmed limit-down stocks', async () => {
    const result = await dashboard(25).board('limit-down');
    expect(result).toMatchObject({status: 200, body: {order: 'volume',
      rows: Array.from({length: 20}, (_, i) => expect.objectContaining({code: String(24 - i)})),
    }});
  });

  it('rejects an incomplete limit-down pool', async () => {
    expect(await dashboard(25, 24).board('limit-down')).toMatchObject({status: 503});
  });
});
