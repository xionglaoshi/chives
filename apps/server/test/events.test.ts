import { createServer } from 'node:http';
import type { Server } from 'node:http';
import { afterEach, describe, expect, it } from 'vitest';

import type { ServerEvent } from '../src/api/protocol.js';
import { EventBus, SseHub } from '../src/events/index.js';
import { closeServer, listen, waitFor } from './support.js';

interface OpenSse {
  events: ServerEvent[];
  status: number;
  close: () => void;
}

async function openSse(url: string, headers: Record<string, string> = {}): Promise<OpenSse> {
  const controller = new AbortController();
  const response = await fetch(url, { headers, signal: controller.signal });
  const events: ServerEvent[] = [];
  if (response.status !== 200 || response.body === null) {
    return { events, status: response.status, close: () => controller.abort() };
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  void (async () => {
    let buffer = '';
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) return;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf('\n\n');
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = block
            .split('\n')
            .filter((line) => line.startsWith('data: '))
            .map((line) => line.slice(6))
            .join('\n');
          if (data !== '') events.push(JSON.parse(data) as ServerEvent);
          boundary = buffer.indexOf('\n\n');
        }
      }
    } catch {
      // aborted by the test
    }
  })();
  return { events, status: response.status, close: () => controller.abort() };
}

const servers: Server[] = [];

async function sseServer(bus: EventBus): Promise<{ url: string; sse: SseHub }> {
  const sse = new SseHub(bus, { heartbeatMs: 10_000 });
  const server = createServer((request, response) => {
    sse.handle(request, response, new URL(request.url ?? '/', 'http://127.0.0.1'));
  });
  servers.push(server);
  const base = await listen(server);
  return { url: `${base}/api/events`, sse };
}

afterEach(async () => {
  for (const server of servers.splice(0)) await closeServer(server);
});

describe('EventBus', () => {
  it('assigns monotonic ids and keeps only the newest events', () => {
    const bus = new EventBus({ capacity: 2 });
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'idle', runningTaskId: null });
    const second = bus.publish({ type: 'bot.status', botId: 'expert', status: 'working', runningTaskId: 't1' });
    const third = bus.publish({ type: 'error', botId: 'expert', message: 'boom' });
    expect(second.id).toBe(2);
    expect(third.id).toBe(3);
    expect(bus.lastId).toBe(3);
    expect(bus.replay(0).map((event) => event.id)).toEqual([2, 3]);
    expect(bus.replay(2).map((event) => event.id)).toEqual([3]);
  });

  it('isolates throwing listeners', () => {
    const bus = new EventBus();
    const seen: number[] = [];
    bus.subscribe(() => {
      throw new Error('listener failed');
    });
    bus.subscribe((event) => seen.push(event.id));
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'idle', runningTaskId: null });
    expect(seen).toEqual([1]);
  });
});

describe('SSE', () => {
  it('replays buffered events after ?since and streams live events', async () => {
    const bus = new EventBus();
    const { url } = await sseServer(bus);
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'idle', runningTaskId: null });
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'working', runningTaskId: 't1' });
    bus.publish({ type: 'error', botId: 'expert', message: 'first' });

    const client = await openSse(`${url}?since=1`);
    await waitFor(() => client.events.length === 2);
    expect(client.events.map((event) => event.id)).toEqual([2, 3]);

    bus.publish({ type: 'error', botId: 'expert', message: 'live' });
    await waitFor(() => client.events.length === 3);
    expect(client.events[2]?.type).toBe('error');
    client.close();
  });

  it('honours Last-Event-ID', async () => {
    const bus = new EventBus();
    const { url } = await sseServer(bus);
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'idle', runningTaskId: null });
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'working', runningTaskId: 't1' });
    const client = await openSse(url, { 'Last-Event-ID': '1' });
    await waitFor(() => client.events.length === 1);
    expect(client.events[0]?.id).toBe(2);
    client.close();
  });

  it('treats an id from an older server epoch as live-only', async () => {
    const bus = new EventBus();
    const { url } = await sseServer(bus);
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'idle', runningTaskId: null });
    bus.publish({ type: 'bot.status', botId: 'expert', status: 'working', runningTaskId: 't1' });
    const client = await openSse(url, { 'Last-Event-ID': '99' });
    bus.publish({ type: 'error', botId: 'expert', message: 'after restart' });
    await waitFor(() => client.events.length === 1);
    expect(client.events[0]?.id).toBe(3);
    client.close();
  });

  it('rejects a malformed since value', async () => {
    const bus = new EventBus();
    const { url } = await sseServer(bus);
    const response = await fetch(`${url}?since=not-a-number`);
    expect(response.status).toBe(400);
    const body = (await response.json()) as { error: { code: string } };
    expect(body.error.code).toBe('bad_request');
  });
});
