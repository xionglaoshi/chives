import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { AlertEventDto, BotSummary, ProactiveSettingsDto, RoutineDto } from '../src/api/protocol.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

interface Harness {
  app: ChivesApp;
  baseUrl: string;
}

const harnesses: Harness[] = [];
const directories: string[] = [];

async function startApp(): Promise<Harness> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-proactive-api-'));
  directories.push(directory);
  const app = createApp({ config: testConfig(directory), driver: new FakeDriver() });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl };
  harnesses.push(harness);
  return harness;
}

afterEach(async () => {
  for (const harness of harnesses.splice(0)) {
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

function internal(app: ChivesApp, path: string, body: unknown, depth = 0): Promise<Response> {
  const token = app.sessions.issue({ botId: 'expert', taskId: `api-${depth}`, depth });
  return fetch(`${harnessUrl(app)}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
}

const urls = new WeakMap<ChivesApp, string>();
function harnessUrl(app: ChivesApp): string {
  const value = urls.get(app);
  if (value === undefined) throw new Error('missing url');
  return value;
}

describe('proactive HTTP API', () => {
  it('lists the built-in routine, creates disabled user routines and confirms the card', async () => {
    const harness = await startApp();
    urls.set(harness.app, harness.baseUrl);

    const listed = await json<RoutineDto[]>(await fetch(`${harness.baseUrl}/api/bots/expert/routines`));
    const premarket = listed.find((routine) => routine.title === '盘前简报');
    expect(premarket?.source).toBe('manifest');
    expect(premarket?.enabled).toBe(true);
    expect(premarket?.scheduleText).toBe('工作日 08:30（北京时间）');
    expect(premarket?.tradingDaysOnly).toBe(true);

    const createdResponse = await internal(harness.app, '/api/internal/routines/create', {
      title: '收盘后复盘',
      schedule: { every_minutes: 60 },
      prompt: '整理今天的盘面',
      trading_days_only: true,
    });
    const created = await json<{ ok: boolean; routine: RoutineDto; messageId: string }>(createdResponse);
    expect(created.ok).toBe(true);
    expect(created.routine.enabled).toBe(false);
    expect(created.routine.scheduleText).toBe('每 60 分钟');

    const card = harness.app.store.messages.get(created.messageId);
    expect(card?.kind).toBe('approval');
    expect(card?.meta?.['approvalKind']).toBe('routine');
    expect(card?.meta?.['decision']).toBeNull();

    const enabledResponse = await fetch(
      `${harness.baseUrl}/api/routines/${encodeURIComponent(created.routine.id)}`,
      { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ enabled: true }) },
    );
    expect(enabledResponse.status).toBe(200);
    expect((await json<RoutineDto>(enabledResponse)).enabled).toBe(true);
    expect(harness.app.store.messages.get(created.messageId)?.meta?.['decision']).toBe('allow');

    const runResponse = await fetch(
      `${harness.baseUrl}/api/routines/${encodeURIComponent(created.routine.id)}/run`,
      { method: 'POST' },
    );
    expect(runResponse.status).toBe(202);
    const run = await json<{ taskId: string }>(runResponse);
    await waitFor(() => harness.app.store.tasks.findRunning('expert') === undefined);
    const task = harness.app.store.tasks.get(run.taskId);
    expect(task?.origin).toBe('routine');
    const separator = harness.app.store.messages.listByTask(run.taskId)[0];
    expect(separator?.kind).toBe('proactive');
    expect(separator?.content).toMatch(/^主动消息 · \d{2}:\d{2} · 收盘后复盘$/);
    expect(separator?.meta?.['manual']).toBe(true);

    const deleteResponse = await fetch(
      `${harness.baseUrl}/api/routines/${encodeURIComponent(created.routine.id)}`,
      { method: 'DELETE' },
    );
    expect(deleteResponse.status).toBe(200);
    expect(harness.app.store.routines.get(created.routine.id)).toBeUndefined();

    const builtinDelete = await fetch(
      `${harness.baseUrl}/api/routines/${encodeURIComponent(premarket?.id ?? '')}`,
      { method: 'DELETE' },
    );
    expect(builtinDelete.status).toBe(403);
  });

  it('rejects routine creation from delegated sessions', async () => {
    const harness = await startApp();
    urls.set(harness.app, harness.baseUrl);
    const response = await internal(
      harness.app,
      '/api/internal/routines/create',
      { title: 'x', schedule: { every_minutes: 30 }, prompt: 'y' },
      1,
    );
    const body = await json<{ error: string }>(response);
    expect(body.error).toBe('forbidden');
  });

  it('serves and updates proactive settings and alert events', async () => {
    const harness = await startApp();
    urls.set(harness.app, harness.baseUrl);

    const defaults = await json<ProactiveSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/proactive`),
    );
    expect(defaults).toEqual({
      enabled: true,
      autoAnalysis: true,
      observeOnly: false,
      browserNotify: true,
      systemNotify: true,
      importantOnly: true,
    });

    const invalid = await fetch(`${harness.baseUrl}/api/settings/proactive`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ autoAnalysis: 'invalid' }),
    });
    expect(invalid.status).toBe(400);

    const saved = await fetch(`${harness.baseUrl}/api/settings/proactive`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ enabled: false, autoAnalysis: false, observeOnly: true }),
    });
    expect(saved.status).toBe(200);
    expect(await json<ProactiveSettingsDto>(saved)).toEqual({
      enabled: false,
      autoAnalysis: false,
      observeOnly: true,
      browserNotify: true,
      systemNotify: true,
      importantOnly: true,
    });

    harness.app.store.alertEvents.add({
      source: 'cn-watch',
      alertId: 9,
      alertTs: new Date().toISOString(),
      code: '600519.SH',
      name: '贵州茅台',
      ruleId: 'pct_up_3',
      status: 'skipped',
      reason: 'cooldown',
      taskId: null,
      createdAt: new Date().toISOString(),
    });
    const events = await json<AlertEventDto[]>(await fetch(`${harness.baseUrl}/api/alerts/events?limit=10`));
    expect(events[0]?.alertId).toBe(9);
    expect(events[0]?.reason).toBe('cooldown');

    const bots = await json<BotSummary[]>(await fetch(`${harness.baseUrl}/api/bots`));
    expect(bots.find((bot) => bot.id === 'expert')?.proactiveCount).toBe(1);
  });
});
