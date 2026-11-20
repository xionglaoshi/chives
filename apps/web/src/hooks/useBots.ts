import { useCallback, useEffect, useRef, useState } from 'react';

import type { BotSummary } from '@chives/server/protocol';

import { listBots } from '../api/client';

export interface BotsState {
  bots: BotSummary[];
  loading: boolean;
  error: string | null;
  setBots: (updater: (bots: BotSummary[]) => BotSummary[]) => void;
  setBotStatus: (botId: string, patch: Partial<Pick<BotSummary, 'status' | 'runningTaskId'>>) => void;
  reload: () => void;
}

const RETRY_MS = 3000;

/** Loads the bot list and keeps retrying while the server is unreachable. */
export function useBots(): BotsState {
  const [bots, setBotsState] = useState<BotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const load = async (): Promise<void> => {
      setLoading(true);
      try {
        const result = await listBots(controller.signal);
        if (!mounted.current) return;
        setBotsState(result);
        setError(null);
        setLoading(false);
      } catch (cause) {
        if (!mounted.current || controller.signal.aborted) return;
        const message = cause instanceof Error ? cause.message : '无法连接 Chives 服务';
        setError(message);
        setLoading(false);
        retryTimer = setTimeout(() => {
          if (mounted.current) setAttempt((value) => value + 1);
        }, RETRY_MS);
      }
    };

    void load();

    return () => {
      mounted.current = false;
      controller.abort();
      if (retryTimer !== undefined) clearTimeout(retryTimer);
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  const setBots = useCallback((updater: (current: BotSummary[]) => BotSummary[]) => {
    setBotsState(updater);
  }, []);

  const setBotStatus = useCallback(
    (botId: string, patch: Partial<Pick<BotSummary, 'status' | 'runningTaskId'>>) => {
      setBotsState((current) =>
        current.map((bot) => (bot.id === botId ? { ...bot, ...patch } : bot))
      );
    },
    []
  );

  return { bots, loading, error, setBots, setBotStatus, reload };
}
