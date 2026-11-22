import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  BotSummary,
  MarketDashboardDto,
  PortfolioDashboardDto,
  StrategyPoolsDto,
  WatchDto
} from '@chives/server/protocol';

import { App } from '../src/App';
import { SidePanel } from '../src/components/SidePanel';
import { jsonResponse, makeBot, MockEventSource, resetEventSources } from './testUtils';

function watchDto(overrides: Partial<WatchDto> = {}): WatchDto {
  return {
    id: 'w1',
    botId: 'expert',
    code: '000528.SZ',
    name: '柳工',
    label: '柳工回踩',
    note: '跌破支撑',
    conditionText: '柳工 000528.SZ：跌破 7.71 时唤醒投资专家，至 11-22',
    giveUpText: '',
    repeat: false,
    status: 'active',
    engineState: 'observe',
    lastPrice: 8.1,
    syncError: null,
    createdTaskId: 'task-0',
    updatedTaskId: null,
    createdAt: '2026-11-17T02:00:00.000Z',
    updatedAt: '2026-11-17T02:00:00.000Z',
    expiresAt: '2026-11-22T02:00:00.000Z',
    triggeredAt: null,
    triggerTaskId: null,
    cancelledBy: null,
    ...overrides
  };
}

const market: MarketDashboardDto = {
  indexes: [
    {
      code: '000001.SH',
      name: '上证指数',
      price: 3580.1,
      changePct: 0.62,
      amountYuan: 681622296204,
      spark: [3570, 3580]
    }
  ],
  amountYuan: 681622296204,
  breadth: { up: 1236, down: 3930, upRatioPct: 23.93 },
  limit: { limitUp: 37, limitDown: 70 },
  asOf: '2026-11-17T15:00:00+08:00',
  session: 'trading',
  stale: false
};

const strategyPools: StrategyPoolsDto = {
  strategy: 'zhushenglang',
  name: '主升浪',
  date: '2026-11-17',
  latest_date: '2026-11-17',
  status: '已计算',
  counts: { first: 1, main: 1 },
  pools: {
    first: [{ code: '003021.SZ', name: '兆威机电', priority: 'p1', score: 85, k: 21, status: '优先级一' }],
    main: [{ code: '601188.SH', name: '龙江交通', score: 90, gain: 0.1, drawdown: 0, ma10_count: 0 }]
  }
};

const portfolio: PortfolioDashboardDto = {
  asOf: '2026-11-17T10:30:00+08:00',
  cash: 5000,
  summary: {
    positionCount: 0,
    pricedCount: 0,
    unpricedCount: 0,
    totalMarketValue: 0,
    totalPnl: 0,
    totalPnlPct: 0,
    todayPnl: null,
    todayPnlPct: null
  },
  positions: [],
  unpriced: [],
  empty: true,
  warnings: []
};

function renderWatches(watches: WatchDto[], revision = 0): {
  onEditWatch: ReturnType<typeof vi.fn>;
  onLocateTask: ReturnType<typeof vi.fn>;
  onCancelWatch: ReturnType<typeof vi.fn>;
  fetchMock: ReturnType<typeof vi.fn>;
  ui: ReturnType<typeof render>;
} {
  const fetchMock = vi.fn(async () => jsonResponse(watches));
  vi.stubGlobal('fetch', fetchMock);
  const onEditWatch = vi.fn();
  const onLocateTask = vi.fn();
  const onCancelWatch = vi.fn(async () => undefined);
  const ui = render(
    <SidePanel
      botId="expert"
      panels={['watches']}
      taskClosedToken={0}
      watchRevision={revision}
      narrow={false}
      onPickName={() => undefined}
      onEditWatch={onEditWatch}
      onLocateTask={onLocateTask}
      onCancelWatch={onCancelWatch}
    />
  );
  return { onEditWatch, onLocateTask, onCancelWatch, fetchMock, ui };
}

function appFetch(bot: BotSummary, watches: WatchDto[] = []) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === '/api/bots') return jsonResponse([bot]);
    if (url === '/api/dashboard/market') return jsonResponse(market);
    if (url === '/api/dashboard/portfolio') return jsonResponse(portfolio);
    if (url.startsWith('/api/strategies/')) return jsonResponse(strategyPools);
    if (url.startsWith('/api/watches')) return jsonResponse(watches);
    if (url.includes('/timeline')) {
      return jsonResponse({ messages: [], tasks: [], toolEvents: [], hasMore: false, nextBeforeSeq: null });
    }
    return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
  });
}

beforeEach(() => {
  resetEventSources();
  vi.stubGlobal('EventSource', MockEventSource);
  window.history.replaceState(null, '', '/#/bot/expert');
  window.localStorage.clear();
  window.innerWidth = 1400;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('WatchesPanel', () => {
  it('lists active watches with condition, engine state, price distance and expiry', async () => {
    renderWatches([
      watchDto({
        syncError: 'engine_unreachable',
        engineState: 'await_confirm'
      })
    ]);
    expect(await screen.findByText('柳工回踩')).toBeTruthy();
    expect(screen.getByText('跌破 7.71 时唤醒投资专家')).toBeTruthy();
    expect(screen.getByText('部分满足')).toBeTruthy();
    expect(screen.getByText('最近价 8.1')).toBeTruthy();
    expect(screen.getByText('距触发价 +5.06%')).toBeTruthy();
    expect(screen.getByText('至 2026-11-22')).toBeTruthy();
    expect(screen.getByText('盯盘引擎没有启动，启动后自动生效')).toBeTruthy();
  });

  it('deletes only after a second click and falls back to the empty state', async () => {
    const { onCancelWatch } = renderWatches([watchDto()]);
    expect(await screen.findByText('柳工回踩')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '删除' }));
    expect(onCancelWatch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }));
    await waitFor(() => expect(onCancelWatch).toHaveBeenCalledWith('w1'));
    expect(
      await screen.findByText("还没有盯盘。直接在对话里说，如'柳工跌破 7.7 叫我'。")
    ).toBeTruthy();
  });

  it('fills the modify prompt without sending', async () => {
    const { onEditWatch } = renderWatches([watchDto()]);
    fireEvent.click(await screen.findByRole('button', { name: '修改' }));
    expect(onEditWatch).toHaveBeenCalledWith('柳工回踩', 'expert');
  });

  it('lists recent triggers and jumps to their analysis task', async () => {
    const triggeredAt = new Date(Date.now() - 3_600_000).toISOString();
    const { onLocateTask } = renderWatches([
      watchDto({
        id: 'w2',
        status: 'triggered',
        engineState: 'execute',
        triggeredAt,
        triggerTaskId: 'task-9'
      })
    ]);
    expect(await screen.findByText('最近触发')).toBeTruthy();
    expect(screen.getByText('达到执行条件')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /柳工回踩/ }));
    expect(onLocateTask).toHaveBeenCalledWith('task-9', 'expert');
  });

  it('refreshes when a watch SSE revision arrives', async () => {
    const { fetchMock, ui } = renderWatches([watchDto()]);
    await screen.findByText('柳工回踩');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    ui.rerender(
      <SidePanel
        botId="expert"
        panels={['watches']}
        taskClosedToken={0}
        watchRevision={1}
        narrow={false}
        onPickName={() => undefined}
        onEditWatch={() => undefined}
        onLocateTask={() => undefined}
        onCancelWatch={async () => undefined}
      />
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});

describe('App side panels', () => {
  it('renders one header button per panel, opens several at once in toolbar order', { timeout: 20000 }, async () => {
    vi.stubGlobal(
      'fetch',
      appFetch(makeBot({ panels: ['market', 'portfolio', 'watches'] }))
    );
    render(<App />);

    const marketButton = await screen.findByRole('button', { name: '行情' }, { timeout: 5000 });
    expect(screen.getByRole('button', { name: '持仓' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '盯盘' })).toBeTruthy();
    expect(screen.queryByText(/^盯盘 \d+$/)).toBeNull();

    fireEvent.click(marketButton);
    expect(await screen.findByLabelText('行情面板', {}, { timeout: 5000 })).toBeTruthy();
    expect(await screen.findByText('上证指数', {}, { timeout: 5000 })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '持仓' }));
    expect(await screen.findByLabelText('持仓面板', {}, { timeout: 5000 })).toBeTruthy();
    expect(screen.getByLabelText('行情面板')).toBeTruthy();
    expect(Array.from(document.querySelectorAll('.expert-sidebar__title'), node=>node.textContent)).toEqual(['持仓','行情']);

    fireEvent.click(screen.getByRole('button', { name: '行情' }));
    expect(screen.queryByLabelText('行情面板')).toBeNull();
    expect(screen.getByLabelText('持仓面板')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '持仓' }));
    expect(screen.queryByLabelText('持仓面板')).toBeNull();
    expect(window.localStorage.getItem('chives.panel.v2.expert')).toBeNull();
  });

  it('ignores the remembered panel for that bot', async () => {
    window.localStorage.setItem('chives.panel.v2.expert', 'portfolio');
    vi.stubGlobal('fetch', appFetch(makeBot({ panels: ['market', 'portfolio'] })));
    render(<App />);
    expect(await screen.findByRole('button',{name:'持仓'})).toBeTruthy();
    expect(screen.queryByLabelText('持仓面板')).toBeNull();
    expect(window.localStorage.getItem('chives.panel.v2.expert')).toBe('portfolio');
  });

  it('starts closed on a narrow window and floats the opened panel', { timeout: 15000 }, async () => {
    window.innerWidth = 800;
    window.localStorage.setItem('chives.panel.v2.expert', 'market');
    vi.stubGlobal('fetch', appFetch(makeBot({ panels: ['market', 'portfolio'] })));
    render(<App />);

    // Rendering the whole App is slow when the suite runs in parallel; allow more than 1 s.
    const button = await screen.findByRole('button', { name: '行情' }, { timeout: 5000 });
    expect(screen.queryByLabelText('行情面板')).toBeNull();
    fireEvent.click(button);
    expect(await screen.findByLabelText('行情面板', {}, { timeout: 5000 })).toBeTruthy();
    expect(document.querySelector('.expert-sidebar--overlay')).not.toBeNull();
  });

  it('fills and focuses the composer from the watches panel without sending', async () => {
    window.history.replaceState(null, '', '/#/workspace/strategies');
    const fetchMock = appFetch(makeBot({ panels: ['market', 'portfolio', 'watches'] }), [
      watchDto()
    ]);
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    fireEvent.click(await screen.findByRole('button', { name:'盯盘'}));
    fireEvent.click(await screen.findByRole('button', { name: '修改' }));
    const textarea = await screen.findByLabelText('给 Bot 发消息') as HTMLTextAreaElement;
    expect(textarea.value).toBe('修改盯盘「柳工回踩」：');
    await waitFor(() => expect(document.activeElement).toBe(textarea));
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) =>
          String(input) === '/api/bots/expert/messages' &&
          (init as RequestInit | undefined)?.method === 'POST'
      )
    ).toBe(false);
  });

  it.each([['research', []], ['zhushenglang', ['strategy:zhushenglang']]] as const)(
    'offers the same global shortcuts for %s', async (id, panels) => {
      window.history.replaceState(null, '', '/#/bot/'+id);
      vi.stubGlobal('fetch', appFetch(makeBot({id, panels:[...panels]})));
      render(<App/>);
      const controls = await screen.findByRole('group',{name:'右侧面板快捷按钮'});
      expect(Array.from(controls.querySelectorAll('button'), item=>item.getAttribute('aria-label')))
        .toEqual(['盯盘','持仓','行情']);
      expect(screen.queryByLabelText('右侧面板')).toBeNull();
    });
});
