import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { StrategyPoolsDto } from '@chives/server/protocol';

import { StrategyPanel } from '../src/components/StrategyPanel';
import { jsonResponse } from './testUtils';

const POOLS: StrategyPoolsDto = {
  strategy: 'zhushenglang',
  name: '主升浪',
  date: '2026-11-17',
  latest_date: '2026-11-17',
  status: '已计算',
  counts: { first: 2, main: 1 },
  pools: {
    first: [
      {
        code: '003021.SZ',
        name: '兆威机电',
        priority: 'p1',
        score: 85,
        k: 21,
        status: '优先级一'
      },
      {
        code: '600506.SH',
        name: '香梨股份',
        priority: 'p2',
        score: 100,
        k: 17,
        status: '优先级二'
      }
    ],
    main: [
      {
        code: '601188.SH',
        name: '龙江交通',
        score: 90,
        gain: 0.2811,
        drawdown: 0,
        ma10_count: 1,
        ma10_obs_left: 2
      }
    ]
  }
};

function renderPanel(onPickName = vi.fn()): ReturnType<typeof render> {
  return render(
    <StrategyPanel
      botId="zhushenglang"
      strategyId="zhushenglang"
      taskClosedToken={0}
      onPickName={onPickName}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('StrategyPanel', () => {
  it('lists the candidate pool by rating and switches to the main-wave pool', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(POOLS)));
    renderPanel();
    expect(await screen.findByLabelText('主升浪策略面板')).toBeTruthy();
    expect(screen.getByText('计算日 2026-11-17 · 已计算')).toBeTruthy();
    expect(screen.getByText('兆威机电')).toBeTruthy();
    expect(screen.getByText('优先一')).toBeTruthy();
    expect(screen.getByText('香梨股份')).toBeTruthy();
    expect(screen.getByText('优先二')).toBeTruthy();
    expect(screen.queryByText('龙江交通')).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: /主升浪池/ }));
    expect(screen.getByText('龙江交通')).toBeTruthy();
    expect(screen.getByText(/28\.11%/)).toBeTruthy();
    expect(screen.getByText((text) => text.includes('MA10') && text.includes('观察中'))).toBeTruthy();
  });

  it('fills the composer text through onPickName without sending', async () => {
    const onPickName = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(POOLS)));
    renderPanel(onPickName);
    fireEvent.click(await screen.findByRole('button', { name: '查看兆威机电的主升浪轮次' }));
    expect(onPickName).toHaveBeenCalledWith('兆威机电的主升浪轮次');
  });

  it('shows the server error and an empty state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse({ error: { code: 'strategy_unavailable', message: '策略服务没有启动' } }, 503))
    );
    renderPanel();
    expect(await screen.findByText('策略服务没有启动')).toBeTruthy();

    cleanup();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          ...POOLS,
          counts: { first: 0, main: 0 },
          pools: { first: [], main: [] }
        })
      )
    );
    renderPanel();
    expect(await screen.findByText('候选池为空。')).toBeTruthy();
  });
});
