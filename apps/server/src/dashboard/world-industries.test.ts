import { afterEach, describe, expect, it, vi } from 'vitest';
import { worldIndustries } from './world.js';

afterEach(() => vi.unstubAllGlobals());

describe('US industry heatmap', () => {
  it('excludes OTC outliers from the industry average, turnover and leading stock', async () => {
    const data = [
      {s: 'NASDAQ:A', d: ['A', 'Semiconductors', 6, 100_000, 'USD']},
      {s: 'NYSE:B', d: ['B', 'Semiconductors', -2, 200_000, 'USD']},
      {s: 'OTC:C', d: ['C', 'Semiconductors', 19_900, 900_000, 'USD']},
    ];
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({totalCount: data.length, data}));
    vi.stubGlobal('fetch', fetchMock);
    const result = await worldIndustries('us');
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body)).filter).toContainEqual({
      left: 'exchange', operation: 'in_range', right: ['NASDAQ', 'NYSE', 'AMEX'],
    });
    expect(result.rows).toEqual([{name: '半导体', change_pct: 2, amount: 300_000, leader: {code: 'A', name: 'A', change_pct: 6, amount: 100_000},
      leaders: [{code: 'A', name: 'A', change_pct: 6, amount: 100_000}, {code: 'B', name: 'B', change_pct: -2, amount: 200_000}]}]);
  });
});
