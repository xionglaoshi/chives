/** Server-sent events endpoint with replay, heartbeats, and clean disconnect. */

import type { IncomingMessage, ServerResponse } from 'node:http';

import type { ServerEvent } from '../api/protocol.js';
import type { EventBus } from './bus.js';

export const DEFAULT_HEARTBEAT_MS = 15_000;

export interface SseHubOptions {
  heartbeatMs?: number;
}

function parseSince(request: IncomingMessage, url: URL): number | undefined {
  const header = request.headers['last-event-id'];
  const raw = (Array.isArray(header) ? header[0] : header) ?? url.searchParams.get('since') ?? undefined;
  if (raw === undefined || raw.trim() === '') return undefined;
  const value = Number(raw);
  return Number.isInteger(value) && value >= 0 ? value : Number.NaN;
}

/** Tracks open SSE responses so shutdown can end them instead of hanging. */
export class SseHub {
  private readonly clients = new Set<() => void>();
  private readonly heartbeatMs: number;

  constructor(
    private readonly bus: EventBus,
    options: SseHubOptions = {},
  ) {
    this.heartbeatMs = options.heartbeatMs ?? DEFAULT_HEARTBEAT_MS;
  }

  get size(): number {
    return this.clients.size;
  }

  /** Returns false when it already answered with an error (bad `since`). */
  handle(request: IncomingMessage, response: ServerResponse, url: URL): boolean {
    const since = parseSince(request, url);
    if (Number.isNaN(since)) {
      response.writeHead(400, { 'content-type': 'application/json' });
      response.end(JSON.stringify({ error: { code: 'bad_request', message: 'invalid Last-Event-ID / since' } }));
      return false;
    }

    response.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    });
    response.flushHeaders();
    response.write('retry: 3000\n\n');

    // Event ids restart with the process. A Last-Event-ID from an earlier
    // server epoch may exceed the current counter; treat it as "live only"
    // instead of silently dropping every new event.
    let lastSent = since ?? this.bus.lastId;
    if (lastSent > this.bus.lastId) lastSent = this.bus.lastId;
    let caughtUp = false;
    const pending: ServerEvent[] = [];

    const write = (event: ServerEvent): void => {
      if (event.id <= lastSent) return;
      lastSent = event.id;
      try {
        response.write(`id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
      } catch {
        // The socket may be gone; the close handler below cleans up.
      }
    };

    const unsubscribe = this.bus.subscribe((event) => {
      if (caughtUp) write(event);
      else pending.push(event);
    });

    for (const event of this.bus.replay(lastSent)) write(event);
    caughtUp = true;
    for (const event of pending) write(event);

    const heartbeat = setInterval(() => {
      try {
        response.write(': heartbeat\n\n');
      } catch {
        // Ignored; close cleanup follows.
      }
    }, this.heartbeatMs);
    heartbeat.unref();

    let cleaned = false;
    const cleanup = (): void => {
      if (cleaned) return;
      cleaned = true;
      clearInterval(heartbeat);
      unsubscribe();
      this.clients.delete(cleanup);
      try {
        response.end();
      } catch {
        // Already closed.
      }
    };
    this.clients.add(cleanup);
    response.on('close', cleanup);
    request.socket.on('close', cleanup);
    return true;
  }

  closeAll(): void {
    for (const cleanup of [...this.clients]) cleanup();
  }
}
