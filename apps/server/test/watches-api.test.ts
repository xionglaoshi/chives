import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type {
  BotSummary,
  NotificationDto,
  WatchDetailDto,
  WatchDto,
} from '../src/api/protocol.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig } from './support.js';

interface Harness {
  app: ChivesApp;
  baseUrl: string;
}

const harnesses: Harness[] = [];
const directories: string[] = [];

async function startApp(): Promise<Harness> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-watch-api-'));
  directories.push(directory);
  const app = createApp({
    config: testConfig(directory),
    driver: new FakeDriver(),
    watchEngineUrl: 'http://127.0.0.1:1',
  });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl };
  harnesses.push(harness);
  return harness;
}

afterEach(async () => {
  for (const harness of harnesses.splice(0)) {
    harness.app.sse.closeAll();
    await closeServer(harness.app.server);
    await harness.app.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

async function json<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

function token(app: ChivesApp, botId = 'expert'): string {
  const existing = app.store.tasks.latestForBot(botId);
  const task =
    existing ??
    app.store.tasks.create({
      botId,
      title: 'internal caller',
      startedAt: new Date().toISOString(),
    });
  return app.sessions.issue({ botId, taskId: task.id, depth: 0 });
}

async function internal(
  harness: Harness,
  path: string,
  body: Record<string, unknown>,
  botId = 'expert',
): Promise<Response> {
  return fetch(`${harness.baseUrl}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${token(harness.app, botId)}`,
    },
    body: JSON.stringify(body),
  });
}

describe('watch and notification HTTP API', () => {
  it('creates, lists as active, shows history and cancels a watch', async () => {
    const harness = await startApp();
    const created = await internal(harness, '/api/internal/watch-plans/create', {
      code: '000528.SZ',
      label: '柳工回踩',
      when: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
      expires_in_days: 5,
      note: '跌破支撑先看量能',
    });
    expect(created.status).toBe(200);
    const body = await json<{ ok: boolean; id: string; status: string; sync_error: string; description: string }>(
      created,
    );
    expect(body.ok).toBe(true);
    expect(body.status).toBe('active');
    expect(body.sync_error).toBe('engine_unreachable');
    expect(body.description).toContain('跌破 7.71');

    const list = await json<WatchDto[]>(
      await fetch(`${harness.baseUrl}/api/watches?botId=expert&status=active`),
    );
    expect(list).toHaveLength(1);
    expect(list[0]?.id).toBe(body.id);

    const detail = await json<WatchDetailDto>(
      await fetch(`${harness.baseUrl}/api/watches/${body.id}`),
    );
    expect(detail.watch.id).toBe(body.id);
    expect(detail.history.map((event) => event.kind)).toContain('created');

    const summary = (await json<BotSummary[]>(await fetch(`${harness.baseUrl}/api/bots`))).find(
      (bot) => bot.id === 'expert',
    );
    expect(summary?.watchCount).toBe(1);

    const cancelled = await fetch(`${harness.baseUrl}/api/watches/${body.id}/cancel`, {
      method: 'POST',
    });
    expect(cancelled.status).toBe(200);
    expect((await json<{ watch: WatchDto }>(cancelled)).watch.cancelledBy).toBe('user');
    const after = await json<BotSummary[]>(await fetch(`${harness.baseUrl}/api/bots`));
    expect(after.find((bot) => bot.id === 'expert')?.watchCount).toBe(0);
  });

  it('returns 403 for every watch-plan route when the bot has no watches panel', async () => {
    const harness = await startApp();
    for (const route of ['create', 'update', 'delete', 'list']) {
      const response = await internal(
        harness,
        `/api/internal/watch-plans/${route}`,
        route === 'create'
          ? {
              code: '600519.SH',
              label: '茅台',
              when: [{ type: 'price_cross', direction: 'up', level: 1800 }],
            }
          : {},
        'equity-analyst',
      );
      expect(response.status).toBe(403);
      expect(await json<{ error: { code: string; message: string } }>(response)).toMatchObject({
        error: { code: 'forbidden', message: '这个 bot 没有盯盘能力' },
      });
    }
    expect(harness.app.watches.list(undefined, 'all')).toHaveLength(0);
  });

  it('lists all watches and returns 404 for an unknown id', async () => {
    const harness = await startApp();
    await internal(harness, '/api/internal/watch-plans/create', {
      code: '600519.SH',
      label: '茅台',
      when: [{ type: 'price_cross', direction: 'up', level: 1600 }],
    });
    const all = await json<WatchDto[]>(
      await fetch(`${harness.baseUrl}/api/watches?botId=expert&status=all`),
    );
    expect(all).toHaveLength(1);
    const missing = await fetch(`${harness.baseUrl}/api/watches/nope`);
    expect(missing.status).toBe(404);
  });

  it('validates update/delete/list and hides watches from bots without the feature', async () => {
    const harness = await startApp();
    const created = await json<{ id: string }>(
      await internal(harness, '/api/internal/watch-plans/create', {
        code: '000528.SZ',
        label: '柳工',
        when: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
      }),
    );
    const updated = await internal(harness, '/api/internal/watch-plans/update', {
      id: created.id,
      when: [{ type: 'price_cross', direction: 'up', level: 8.69 }],
      expires_in_days: 7,
    });
    const updateBody = await json<{ ok: boolean; changes: string; watch: WatchDto }>(updated);
    expect(updateBody.ok).toBe(true);
    expect(updateBody.changes).toContain('站上 8.69');

    const foreign = await internal(
      harness,
      '/api/internal/watch-plans/delete',
      { id: created.id },
      'research',
    );
    expect(foreign.status).toBe(403);
    expect(await json<{ error: { code: string; message: string } }>(foreign)).toMatchObject({
      error: { code: 'forbidden', message: '这个 bot 没有盯盘能力' },
    });

    const listed = await internal(harness, '/api/internal/watch-plans/list', {});
    expect(await json<{ count: number }>(listed)).toMatchObject({ count: 1 });
    const removed = await internal(harness, '/api/internal/watch-plans/delete', {
      id: created.id,
    });
    expect(await json<{ ok: boolean; status: string }>(removed)).toMatchObject({
      ok: true,
      status: 'cancelled',
    });
    const empty = await internal(harness, '/api/internal/watch-plans/list', { status: 'all' });
    expect(await json<{ count: number }>(empty)).toMatchObject({ count: 1 });
  });

  it('serves notifications and marks them read', async () => {
    const harness = await startApp();
    const result = await internal(harness, '/api/internal/notifications/notify', {
      title: '柳工放量',
      body: '现价 8.62，量比 2.1，10:31',
      level: 'important',
    });
    const body = await json<{ ok: boolean; notification: NotificationDto }>(result);
    expect(body.ok).toBe(true);
    expect(body.notification.readAt).toBeNull();

    const unread = await json<NotificationDto[]>(
      await fetch(`${harness.baseUrl}/api/notifications?unread=1`),
    );
    expect(unread).toHaveLength(1);
    const summary = (await json<BotSummary[]>(await fetch(`${harness.baseUrl}/api/bots`))).find(
      (bot) => bot.id === 'expert',
    );
    expect(summary?.unreadNotifications).toBe(1);

    const read = await fetch(`${harness.baseUrl}/api/notifications/${body.notification.id}/read`, {
      method: 'POST',
    });
    expect((await json<NotificationDto>(read)).readAt).not.toBeNull();
    const after = await json<NotificationDto[]>(
      await fetch(`${harness.baseUrl}/api/notifications?unread=1`),
    );
    expect(after).toHaveLength(0);
    const all = await fetch(`${harness.baseUrl}/api/notifications/read-all`, { method: 'POST' });
    expect(await json<{ ok: boolean; count: number }>(all)).toMatchObject({ ok: true, count: 0 });
  });

  it('requires a session token on the internal endpoints', async () => {
    const harness = await startApp();
    const response = await fetch(`${harness.baseUrl}/api/internal/watch-plans/list`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{}',
    });
    expect(response.status).toBe(401);
  });
});
