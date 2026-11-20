import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  BotPanel,
  MarketDashboardDto,
  MarketSession,
  PortfolioDashboardDto
} from '@chives/server/protocol';

import { fetchDashboardMarket, fetchDashboardPortfolio } from '../api/client';

/** Trading hours refresh fast; other sessions refresh slowly. */
export const TRADING_REFRESH_MS = 10_000;
export const PRE_OPEN_REFRESH_MS = 60_000;
export const IDLE_REFRESH_MS = 300_000;

export type SectionStatus = 'loading' | 'ready' | 'error';

export interface SectionState<T> {
  status: SectionStatus;
  data: T | null;
}

export interface ExpertSidebarData {
  market: SectionState<MarketDashboardDto>;
  portfolio: SectionState<PortfolioDashboardDto>;
}

export function refreshIntervalMs(session: MarketSession | null): number {
  if (session === 'trading' || session === 'auction') return TRADING_REFRESH_MS;
  if (session === 'pre_open') return PRE_OPEN_REFRESH_MS;
  return IDLE_REFRESH_MS;
}

function loading<T>(): SectionState<T> {
  return { status: 'loading', data: null };
}

/**
 * Loads only the open panel, then refreshes it on a session-dependent timer.
 * The timer pauses while the document is hidden and fires once when it becomes
 * visible again. `taskClosedToken` changes after the bot's task ends, forcing
 * one extra refresh. Watches have their own hook and never start this timer.
 */
export function useExpertSidebarData(
  panel: BotPanel | null,
  taskClosedToken: number
): ExpertSidebarData {
  const [market, setMarket] = useState<SectionState<MarketDashboardDto>>(loading);
  const [portfolio, setPortfolio] = useState<SectionState<PortfolioDashboardDto>>(loading);
  const sessionRef = useRef<MarketSession | null>(null);

  const loadMarket = useCallback(async (signal: AbortSignal): Promise<void> => {
    try {
      const data = await fetchDashboardMarket(signal);
      if (signal.aborted) return;
      sessionRef.current = data.session;
      setMarket({ status: 'ready', data });
    } catch {
      if (signal.aborted) return;
      setMarket((current) => ({ status: 'error', data: current.data }));
    }
  }, []);

  const loadPortfolio = useCallback(async (signal: AbortSignal): Promise<void> => {
    try {
      const data = await fetchDashboardPortfolio(signal);
      if (signal.aborted) return;
      setPortfolio({ status: 'ready', data });
    } catch {
      if (signal.aborted) return;
      setPortfolio((current) => ({ status: 'error', data: current.data }));
    }
  }, []);

  useEffect(() => {
    if (panel !== 'market' && panel !== 'portfolio') return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;

    const tick = async (): Promise<void> => {
      if (stopped) return;
      controller = new AbortController();
      if (panel === 'market') await loadMarket(controller.signal);
      else await loadPortfolio(controller.signal);
      if (stopped) return;
      timer = setTimeout(() => {
        void tick();
      }, refreshIntervalMs(sessionRef.current));
    };

    const onVisibility = (): void => {
      if (stopped) return;
      if (document.visibilityState === 'hidden') {
        if (timer !== undefined) clearTimeout(timer);
        timer = undefined;
        controller?.abort();
        return;
      }
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
      void tick();
    };

    document.addEventListener('visibilitychange', onVisibility);
    void tick();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer !== undefined) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [panel, loadMarket, loadPortfolio, taskClosedToken]);

  return { market, portfolio };
}
