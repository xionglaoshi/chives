import type { ReactElement } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { MarketDashboardDto, PortfolioDashboardDto } from '@chives/server/protocol';
import { useSidePanelState } from '../src/components/ExpertSidebar';
import { refreshIntervalMs } from '../src/components/ExpertSidebarData';
import { SidePanel } from '../src/components/SidePanel';
import { jsonResponse } from './testUtils';

function marketDto(overrides: Partial<MarketDashboardDto> = {}): MarketDashboardDto {
  return {
    indexes: [
      {
        code: '000001.SH',
        name: '上证指数',
        price: 3580.1,
        changePct: 0.62,
        amountYuan: 681622296204,
        spark: [3570, 3575, 3580]
      },
      {
        code: '399001.SZ',
        name: '深证成指',
        price: 10647.7,
        changePct: -0.4,
        amountYuan: 759832962733,
        spark: []
      },
      { code: '399006.SZ', name: '创业板指', price: 2295.2, changePct: -1.07, amountYuan: null, spark: [] },
      { code: '000300.SH', name: '沪深300', price: 3972.64, changePct: -0.18, amountYuan: null, spark: [] },
      { code: '000688.SH', name: '科创50', price: 1221.24, changePct: 0.42, amountYuan: null, spark: [] }
    ],
    amountYuan: 1441455258937,
    breadth: { up: 1236, down: 3930, upRatioPct: 23.93 },
    limit: { limitUp: 37, limitDown: 70 },
    asOf: '2026-11-17T15:00:00+08:00',
    session: 'trading',
    stale: false,
    ...overrides
  };
}

function portfolioDto(overrides: Partial<PortfolioDashboardDto> = {}): PortfolioDashboardDto {
  return {
    asOf: '2026-11-17T10:30:00+08:00',
    cash: 5000,
    summary: {
      positionCount: 1,
      pricedCount: 1,
      unpricedCount: 0,
      totalMarketValue: 10000,
      totalPnl: 2000,
      totalPnlPct: 25,
      todayPnl: 1000,
      todayPnlPct: 12.5
    },
    positions: [
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
        priceAvailable: true
      }
    ],
    unpriced: [],
    empty: false,
    warnings: [],
    ...overrides
  };
}

interface FetchHandlers {
  market?: () => Promise<Response> | Response;
  portfolio?: () => Promise<Response> | Response;
}

function stubDashboardFetch(handlers: FetchHandlers = {}): {
  market: ReturnType<typeof vi.fn>;
  portfolio: ReturnType<typeof vi.fn>;
} {
  const market = vi.fn(async () =>
    handlers.market === undefined ? jsonResponse(marketDto()) : await handlers.market()
  );
  const portfolio = vi.fn(async () =>
    handlers.portfolio === undefined ? jsonResponse(portfolioDto()) : await handlers.portfolio()
  );
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/dashboard/market') return market();
      if (url === '/api/dashboard/portfolio') return portfolio();
      return jsonResponse({ error: { code: 'not_found', message: 'not found' } }, 404);
    })
  );
  return { market, portfolio };
}

function renderPanel(
  panel: 'market' | 'portfolio',
  taskClosedToken = 0
): { onPickName: ReturnType<typeof vi.fn>; ui: ReturnType<typeof render> } {
  const onPickName = vi.fn();
  const ui = render(
    <SidePanel
      botId="expert"
      panels={[panel]}
      taskClosedToken={taskClosedToken}
      watchRevision={0}
      narrow={false}
      onPickName={onPickName}
      onEditWatch={() => undefined}
      onLocateTask={() => undefined}
      onCancelWatch={async () => undefined}
    />
  );
  return { onPickName, ui };
}

beforeEach(() => {
  window.localStorage.clear();
  // A returning user who closed every panel; the first-visit default is tested on its own.
  for (const bot of ['expert', 'research', 'zhushenglang']) window.localStorage.setItem(`chives.panel.v2.${bot}`, '');
  window.innerWidth = 1400;
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('SidePanel market', () => {
  it('renders the market card and does not load the portfolio', async () => {
    const { market, portfolio } = stubDashboardFetch();
    renderPanel('market');

    expect(await screen.findByText('上证指数')).toBeTruthy();
    expect(screen.getByText('+0.62%').className).toContain('expert-sidebar__price--up');
    expect(screen.getByText('-0.40%').className).toContain('expert-sidebar__price--down');
    expect(screen.getByText('1.44 万亿')).toBeTruthy();
    expect(screen.getByText(/交易中/)).toBeTruthy();
    expect(screen.getByLabelText('行情面板')).toBeTruthy();
    expect(screen.getByText('行情')).toBeTruthy();
    expect(market).toHaveBeenCalledTimes(1);
    expect(portfolio).not.toHaveBeenCalled();
  });

  it('shows the error state only for the market request', async () => {
    stubDashboardFetch({ market: () => Promise.reject(new Error('blank')) });
    renderPanel('market');
    expect(await screen.findByText('暂时取不到，稍后自动重试')).toBeTruthy();
    expect(screen.queryByText('上证指数')).toBeNull();
  });
});

describe('SidePanel portfolio', () => {
  it('renders holdings, hides amounts and does not load the market', async () => {
    const { market, portfolio } = stubDashboardFetch();
    renderPanel('portfolio');

    expect(await screen.findByText('浦发银行')).toBeTruthy();
    expect(screen.getByText('持仓')).toBeTruthy();
    expect(screen.getAllByText('+25.00%').length).toBeGreaterThan(0);
    expect(screen.getByText(/现价 10.00/)).toBeTruthy();
    expect(market).not.toHaveBeenCalled();
    expect(portfolio).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('switch', { name: '隐藏金额', checked: false }));
    expect(screen.getByRole('switch', { name: '隐藏金额', checked: true })).toBeTruthy();
    expect(screen.getAllByText('****').length).toBeGreaterThan(0);
    expect(screen.getAllByText('+25.00%').length).toBeGreaterThan(0);
    expect(window.localStorage.getItem('chives.expertSidebar.hideAmounts')).toBe('1');
  });

  it('shows a friendly empty state and fills the composer when a holding is clicked', async () => {
    stubDashboardFetch({
      portfolio: () =>
        jsonResponse(
          portfolioDto({
            cash: null,
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
            empty: true
          })
        )
    });
    const { onPickName } = renderPanel('portfolio');
    expect(await screen.findByText(/还没有记录持仓/)).toBeTruthy();
    expect(screen.getByText('未设置')).toBeTruthy();
    expect(onPickName).not.toHaveBeenCalled();
  });

  it('fills the composer text when a holding is clicked', async () => {
    stubDashboardFetch();
    const { onPickName } = renderPanel('portfolio');

    fireEvent.click(await screen.findByRole('button', { name: '看看浦发银行' }));
    expect(onPickName).toHaveBeenCalledWith('浦发银行');
  });
});

describe('SidePanel refresh', () => {
  it('maps trading and the call auction to 10s, pre-open to 1 minute, anything else to 5 minutes', () => {
    expect(refreshIntervalMs('trading')).toBe(10_000);
    expect(refreshIntervalMs('auction')).toBe(10_000);
    expect(refreshIntervalMs('pre_open')).toBe(60_000);
    expect(refreshIntervalMs('lunch_break')).toBe(300_000);
    expect(refreshIntervalMs('closed')).toBe(300_000);
    expect(refreshIntervalMs('holiday')).toBe(300_000);
    expect(refreshIntervalMs(null)).toBe(300_000);
  });

  it('refreshes only the open panel every 10s while trading', async () => {
    vi.useFakeTimers();
    const { market, portfolio } = stubDashboardFetch();
    renderPanel('market');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(market).toHaveBeenCalledTimes(1);
    expect(portfolio).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(market).toHaveBeenCalledTimes(2);
    expect(portfolio).not.toHaveBeenCalled();
  });

  it('pauses while the page is hidden and refreshes once when visible', async () => {
    vi.useFakeTimers();
    const { market } = stubDashboardFetch();
    renderPanel('market');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(market).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(market).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    document.dispatchEvent(new Event('visibilitychange'));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(market).toHaveBeenCalledTimes(2);
  });

  it('refreshes once when the bot task ends', async () => {
    const { market } = stubDashboardFetch();
    const { ui } = renderPanel('market', 0);
    await screen.findByText('上证指数');
    expect(market).toHaveBeenCalledTimes(1);

    ui.rerender(
      <SidePanel
        botId="expert"
        panels={['market']}
        taskClosedToken={1}
        watchRevision={0}
        narrow={false}
        onPickName={() => undefined}
        onEditWatch={() => undefined}
        onLocateTask={() => undefined}
        onCancelWatch={async () => undefined}
      />
    );
    await waitFor(() => expect(market).toHaveBeenCalledTimes(2));
  });
});

describe('useSidePanelState', () => {
  function Harness({ botId }: { botId: string }): ReactElement {
    const state = useSidePanelState(botId);
    return (
      <>
        <button type="button" onClick={() => state.toggle('market')}>
          market
        </button>
        <button type="button" onClick={() => state.toggle('portfolio')}>
          portfolio
        </button>
        <span data-testid="open">{state.open.length === 0 ? 'none' : state.open.join(',')}</span>
        <span data-testid="narrow">{state.narrow ? 'yes' : 'no'}</span>
      </>
    );
  }

  it('opens several panels at once in configured order and closes each on a second click', () => {
    render(<Harness botId="expert" />);
    fireEvent.click(screen.getByRole('button', { name: 'portfolio' }));
    expect(screen.getByTestId('open').textContent).toBe('portfolio');
    fireEvent.click(screen.getByRole('button', { name: 'market' }));
    expect(screen.getByTestId('open').textContent).toBe('portfolio,market');
    expect(window.localStorage.getItem('chives.panel.v2.expert')).toBe('');

    fireEvent.click(screen.getByRole('button', { name: 'market' }));
    expect(screen.getByTestId('open').textContent).toBe('portfolio');
    fireEvent.click(screen.getByRole('button', { name: 'portfolio' }));
    expect(screen.getByTestId('open').textContent).toBe('none');
    expect(window.localStorage.getItem('chives.panel.v2.expert')).toBe('');
  });

  it('starts every bot closed even when an older build stored open panels', () => {
    window.localStorage.setItem('chives.panel.v2.expert', 'watches');
    window.localStorage.setItem('chives.panel.v2.research', 'market');
    const { rerender } = render(<Harness botId="expert" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
    fireEvent.click(screen.getByRole('button', {name:'market'}));
    rerender(<Harness botId="research" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
    rerender(<Harness botId="expert" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
  });

  it('closes every panel on the first visit to a bot', () => {
    window.localStorage.clear();
    render(<Harness botId="expert" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
  });

  it('ignores choices stored by older builds on a laptop-width window', () => {
    window.localStorage.clear();
    window.localStorage.setItem('chives.panel.expert', 'watches');
    window.innerWidth = 1100;
    render(<Harness botId="expert" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
  });

  it('starts closed on a narrow window', () => {
    window.innerWidth = 800;
    window.localStorage.setItem('chives.panel.v2.expert', 'market');
    render(<Harness botId="expert" />);
    expect(screen.getByTestId('open').textContent).toBe('none');
    expect(screen.getByTestId('narrow').textContent).toBe('yes');
  });
});
