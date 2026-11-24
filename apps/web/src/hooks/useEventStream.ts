import { appPath } from '../appPath';
import { syncBrowserState } from '../utils/browserState';
import { useEffect, useRef, useState } from 'react';

import type { ServerEvent } from '@chives/server/protocol';

export const SERVER_EVENT_TYPES = [
  'message.created',
  'task.started',
  'task.updated',
  'task.closed',
  'tool.started',
  'tool.ended',
  'draft.reset',
  'draft.delta',
  'draft.commit',
  'usage',
  'bot.status',
  'bot.updated',
  'roster.changed',
  'delegation.updated',
  'deliverable.created',
  'memory.updated',
  'approval.requested',
  'error'
] as const;

export type EventStreamStatus = 'connecting' | 'open' | 'reconnecting';

interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
  close(): void;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
}

type EventSourceFactory = (url: string) => EventSourceLike;

function parseEvent(raw: string): ServerEvent | null {
  try {
    const value = (JSON.parse(raw) as unknown) as Partial<ServerEvent>;
    if (typeof value.id !== 'number' || typeof value.type !== 'string' || typeof value.botId !== 'string') {
      return null;
    }
    return value as ServerEvent;
  } catch {
    return null;
  }
}

export interface EventStreamOptions {
  url?: string;
  factory?: EventSourceFactory;
  retryBaseMs?: number;
  retryMaxMs?: number;
  setTimeoutFn?: (handler: () => void, delay: number) => ReturnType<typeof setTimeout>;
  clearTimeoutFn?: (handle: ReturnType<typeof setTimeout>) => void;
}

/**
 * One EventSource for the whole app. The connection survives bot switches;
 * consumers route events by `event.botId`. On a dropped connection we reopen
 * with `?since=<last id>` so the server can replay what was missed.
 */
export function useEventStream(
  onEvent: (event: ServerEvent) => void,
  options: EventStreamOptions = {}
): EventStreamStatus {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const [status, setStatus] = useState<EventStreamStatus>('connecting');

  const url = options.url ?? eventStreamUrl(null);
  const retryBaseMs = options.retryBaseMs ?? 1000;
  const retryMaxMs = options.retryMaxMs ?? 5000;
  const factory = options.factory;
  const setTimeoutFn = options.setTimeoutFn ?? setTimeout;
  const clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout;

  useEffect(() => {
    let closed = false;
    let source: EventSourceLike | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let lastId = 0;
    let attempt = 0;

    const connect = (): void => {
      if (closed) return;
      const target = lastId > 0 ? eventStreamUrl(lastId) : url;
      let next: EventSourceLike;
      try {
        next = factory === undefined ? (new EventSource(target) as unknown as EventSourceLike) : factory(target);
      } catch {
        setStatus('reconnecting');
        retryTimer = scheduleReconnect();
        return;
      }
      source = next;
      next.onopen = () => {
        if (attempt > 0 && factory === undefined) {
          void syncBrowserState().then(changed => {
            if (changed && !closed) window.location.reload();
          });
        }
        attempt = 0;
        setStatus('open');
      };
      next.onerror = () => {
        if (closed) return;
        next.close();
        if (source === next) source = null;
        setStatus('reconnecting');
        retryTimer = scheduleReconnect();
      };
      for (const type of SERVER_EVENT_TYPES) {
        next.addEventListener(type, (message) => {
          const event = parseEvent(message.data);
          if (event === null) return;
          lastId = Math.max(lastId, event.id);
          onEventRef.current(event);
        });
      }
    };

    const scheduleReconnect = (): ReturnType<typeof setTimeout> => {
      const delay = Math.min(retryBaseMs * 2 ** attempt, retryMaxMs);
      attempt += 1;
      return setTimeoutFn(() => {
        connect();
      }, delay);
    };

    connect();

    return () => {
      closed = true;
      if (retryTimer !== undefined) clearTimeoutFn(retryTimer);
      if (source !== null) source.close();
    };
  }, [url, retryBaseMs, retryMaxMs, factory, setTimeoutFn, clearTimeoutFn]);

  return status;
}

export function eventStreamUrl(lastEventId: number | null): string {
  return appPath(lastEventId === null || lastEventId <= 0 ? '/api/events' : `/api/events?since=${lastEventId}`);
}
