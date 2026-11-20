import { createServer, type Server } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { toTaskDto } from '../src/api/dto.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import type { BotManifest } from '../src/bots/index.js';
import { NotificationService } from '../src/notifications/index.js';
import type { Orchestrator } from '../src/orchestrator.js';
import { Orchestrator as OrchestratorClass } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import { WatchService, WatchValidationError } from '../src/watches/index.js';
import { AlertService } from '../src/alerts/service.js';
import type { AlertView } from '../src/alerts/service.js';
import type { AlertsConfig } from '../src/alerts/index.js';
import { closeServer, listen, makeRegistry, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

interface EngineCall {
  path: string;
  body: Record<string, unknown> | null;
}

interface FakeEngine {
  server: Server;
  url: string;
  calls: EngineCall[];
  plans: Map<string, Record<string, unknown>>;
  alerts: Array<Record<string, unknown>>;
  fail: boolean;
  reject: { code: string; message: string; field: string } | null;
}

async function fakeEngine(): Promise<FakeEngine> {
  const state: FakeEngine = {
    server: createServer(),
    url: '',
    calls: [],
    plans: new Map(),
    alerts: [],
    fail: false,
    reject: null,
  };
  state.server.on('request', (request, response) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8');
      const body = text === '' ? null : (JSON.parse(text) as Record<string, unknown>);
      state.calls.push({ path: request.url ?? '', body });
      if (state.fail) {
        response.destroy();
        return;
      }
      const send = (status: number, payload: unknown): void => {
        response.writeHead(status, { 'content-type': 'application/json' });
        response.end(JSON.stringify(payload));
      };
      if (request.url === '/plans' && request.method === 'GET') {
        send(200, {
          ok: true,
          as_of: new Date().toISOString(),
          plans: [...state.plans.values()],
        });
        return;
      }
      if (request.url === '/plans/upsert' && request.method === 'POST' && body !== null) {
        if (state.reject !== null) {
          send(400, { ok: false, ...state.reject });
          return;
        }
        const id = String(body.id);
        state.plans.set(id, {
          id,
          code: body.code,
          label: body.label,
          state: 'observe',
          since: new Date().toISOString(),
          last_price: 10.25,
          expires_at: body.expires_at,
          active: true,
        });
        send(200, { ok: true, status: 'created', plan: state.plans.get(id) });
        return;
      }
      if (request.url === '/plans/remove' && request.method === 'POST' && body !== null) {
        const id = String(body.id);
        if (!state.plans.has(id)) {
          send(404, { ok: false, code: 'not_found', message: '计划不存在' });
          return;
        }
        state.plans.delete(id);
        send(200, { ok: true, status: 'removed', id });
        return;
      }
      if (request.url?.startsWith('/alerts')) {
        send(200, { ok: true, alerts: state.alerts });
        return;
      }
      send(404, { ok: false, code: 'not_found', message: 'not found' });
    });
  });
  state.url = await listen(state.server);
  cleanups.push(() => closeServer(state.server));
  return state;
}

class CapturingDriver extends FakeDriver {
  readonly prompts: string[] = [];

  override async prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: Parameters<FakeDriver['prompt']>[3],
  ): Promise<Awaited<ReturnType<FakeDriver['prompt']>>> {
    this.prompts.push(text);
    return super.prompt(bot, sessionId, text, sink);
  }
}

async function setup(options: { engine: FakeEngine; now?: { value: Date } }) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-watch-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const driver = new CapturingDriver();
  const registry = makeRegistry();
  const now = (): Date => options.now?.value ?? new Date('2026-11-17T02:00:00.000Z');
  const orchestrator: Orchestrator = new OrchestratorClass({
    registry,
    store,
    bus,
    driver,
    now,
    dataDir,
  });
  orchestrator.start();
  const osCalls: Array<{ file: string; args: string[] }> = [];
  const notifications = new NotificationService({
    store,
    bus,
    now,
    platform: 'darwin',
    execFile: (file, args, _options, callback) => {
      osCalls.push({ file, args: [...args] });
      callback(null);
    },
    log: () => undefined,
  });
  const watches = new WatchService({
    store,
    registry,
    orchestrator,
    bus,
    notifications,
    now,
    cnWatchUrl: options.engine.url,
    log: () => undefined,
  });
  cleanups.push(async () => {
    watches.stop();
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, registry, orchestrator, notifications, watches, driver, osCalls, now };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

const baseInput = {
  code: '000528.SZ',
  label: '柳工回踩',
  when: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
  note: '跌破支撑先看量能',
};

function alertFor(planId: string, overrides: Record<string, unknown> = {}): AlertView {
  const now = new Date('2026-11-17T02:00:00.000Z');
  const detail = {
    plan_id: planId,
    from: 'observe',
    to: 'execute',
    reason: '价格突破',
    label: '柳工回踩',
    ...overrides,
  };
  return {
    id: 1,
    ts: now.toISOString(),
    code: '000528.SZ',
    name: '柳工',
    ruleId: `plan:${planId}`,
    ruleType: 'plan',
    title: '柳工 价格突破',
    raw: {
      id: 1,
      ts: now.toISOString(),
      code: '000528.SZ',
      name: '柳工',
      rule_id: `plan:${planId}`,
      rule_type: 'plan',
      price: 8.7,
      detail,
    },
  };
}

describe('watch plans', () => {
  it('creates the Plan JSON cn-watch expects and a timeline card without confirmation', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    expect(watch.id).toMatch(/^[a-z0-9]{24}$/);
    expect(watch.status).toBe('active');
    expect(watch.conditionText).toContain('000528.SZ');
    expect(watch.conditionText).toContain('跌破 7.71');
    const plan = engine.calls.find((call) => call.path === '/plans/upsert')?.body;
    expect(plan).toMatchObject({
      id: `chives-${watch.id}`,
      code: '000528.SZ',
      market: [],
      sector: [],
      stock: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
      policy: 'any',
      giveup: [],
      stop_price: null,
      held: false,
      label: '柳工回踩',
    });
    expect(typeof plan?.['expires_at']).toBe('string');
    expect(watch.expiresAt.slice(0, 10)).toBe('2026-11-22');
    const cards = ctx.store.messages.listByKind('approval');
    expect(cards).toHaveLength(1);
    expect(cards[0]?.meta?.['approvalKind']).toBe('watch');
    expect(cards[0]?.meta?.['watchAction']).toBe('created');
  });

  it('overwrites the same id on edit and records before/after in the history', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const result = await ctx.watches.update('expert', null, watch.id, {
      when: [{ type: 'price_cross', direction: 'up', level: 8.69 }],
      note: '站上确认',
    });
    expect(result.diff).toContain('站上 8.69');
    const upserts = engine.calls.filter((call) => call.path === '/plans/upsert');
    expect(upserts).toHaveLength(2);
    expect(upserts[1]?.body?.['id']).toBe(`chives-${watch.id}`);
    expect(upserts[1]?.body?.['stock']).toEqual([
      { type: 'price_cross', direction: 'up', level: 8.69 },
    ]);
    const events = ctx.store.watches.events(watch.id);
    const edit = events.find((event) => event.kind === 'updated');
    expect(edit?.before?.['stock']).toEqual([
      { type: 'price_cross', direction: 'down', level: 7.71 },
    ]);
    expect(edit?.after?.['stock']).toEqual([
      { type: 'price_cross', direction: 'up', level: 8.69 },
    ]);
    expect(edit?.detail).toContain('8.69');
  });

  it('removes the plan and soft-deletes on delete', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const deleted = await ctx.watches.cancelByBot('expert', null, watch.id);
    expect(deleted.status).toBe('cancelled');
    expect(deleted.cancelledBy).toBe('bot');
    expect(engine.calls.some((call) => call.path === '/plans/remove')).toBe(true);
    expect(ctx.store.watches.events(watch.id).map((event) => event.kind)).toContain('cancelled');
  });

  it('rejects Beijing codes, index codes, out-of-range values and background bots locally', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const invalid = [
      { code: '430047.BJ' },
      { code: '000300.SH' },
      { code: '399001.SZ' },
      { when: [{ type: 'price_cross', direction: 'down', level: -1 }] },
      { when: [{ type: 'pct_change', direction: 'up', threshold_pct: 0 }] },
      { when: [] },
      { expiresInDays: 31 },
      { expiresInDays: 0 },
      { label: 'x'.repeat(41) },
      { note: 'x'.repeat(201) },
      { when: [{ type: 'sector_change', sector_code: 'BK0433', op: '>=', value: 1 }] },
    ];
    for (const patch of invalid) {
      await expect(
        ctx.watches.create('expert', null, { ...baseInput, ...patch } as never),
      ).rejects.toBeInstanceOf(WatchValidationError);
    }
    await expect(
      ctx.watches.create('report-builder', null, baseInput),
    ).rejects.toMatchObject({ code: 'background_bot' });
    expect(engine.calls.some((call) => call.path === '/plans/upsert')).toBe(false);
  });

  it('enforces 20 active watches per bot and 25 chives plans in total', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    for (let index = 0; index < 20; index += 1) {
      await ctx.watches.create('expert', null, {
        ...baseInput,
        code: `6005${String(index).padStart(2, '0')}.SH`,
        label: `w${index}`,
      });
    }
    await expect(ctx.watches.create('expert', null, baseInput)).rejects.toMatchObject({
      code: 'too_many_watches',
    });
    for (let index = 0; index < 5; index += 1) {
      await ctx.watches.create('equity-analyst', null, {
        ...baseInput,
        code: `6006${String(index).padStart(2, '0')}.SH`,
        label: `x${index}`,
      });
    }
    await expect(ctx.watches.create('research', null, baseInput)).rejects.toMatchObject({
      code: 'too_many_watches',
    });
  });

  it('rolls back when cn-watch rejects a create and returns its Chinese reason', async () => {
    const engine = await fakeEngine();
    engine.reject = { code: 'invalid_condition', message: 'price_cross.level 超出范围', field: 'stock[0].level' };
    const ctx = await setup({ engine });
    await expect(ctx.watches.create('expert', null, baseInput)).rejects.toMatchObject({
      code: 'invalid_condition',
      message: expect.stringContaining('price_cross.level'),
    });
    expect(ctx.store.watches.list()).toHaveLength(0);
  });

  it('keeps active with sync_error while the engine is down and later pushes', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    engine.fail = true;
    await ctx.watches.tick();
    expect(ctx.store.watches.get(watch.id)?.status).toBe('active');
    expect(ctx.store.watches.get(watch.id)?.syncError).toBe('engine_unreachable');
    engine.fail = false;
    await ctx.watches.tick();
    expect(ctx.store.watches.get(watch.id)?.syncError).toBeNull();
    expect(ctx.store.watches.get(watch.id)?.lastPrice).toBe(10.25);
  });

  it('reconciles extra chives plans but never touches card- plans', async () => {
    const engine = await fakeEngine();
    engine.plans.set('card-42', {
      id: 'card-42',
      code: '600519.SH',
      label: 'hub',
      state: 'observe',
      since: new Date().toISOString(),
      last_price: 1,
      expires_at: null,
      active: true,
    });
    engine.plans.set('chives-stale', {
      id: 'chives-stale',
      code: '600519.SH',
      label: 'stale',
      state: 'observe',
      since: new Date().toISOString(),
      last_price: 1,
      expires_at: null,
      active: true,
    });
    const ctx = await setup({ engine });
    await ctx.watches.tick();
    expect(engine.plans.has('chives-stale')).toBe(false);
    expect(engine.plans.has('card-42')).toBe(true);
  });

  it('expires due watches and removes them from the engine', async () => {
    const engine = await fakeEngine();
    const holder = { value: new Date('2026-11-17T02:00:00.000Z') };
    const ctx = await setup({ engine, now: holder });
    const watch = await ctx.watches.create('expert', null, { ...baseInput, expiresInDays: 1 });
    holder.value = new Date('2026-11-18T02:00:01.000Z');
    await ctx.watches.tick();
    expect(ctx.store.watches.get(watch.id)?.status).toBe('expired');
    expect(engine.plans.has(`chives-${watch.id}`)).toBe(false);
  });
});

describe('watch triggers', () => {
  it('wakes the owning bot with the required prompt pieces and removes a one-shot plan', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const result = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: ctx.now(),
    });
    expect(result.status).toBe('started');
    const task = ctx.store.tasks.get((result as { taskId: string }).taskId);
    expect(task?.origin).toBe('alert');
    expect(task?.title).toBe('盯盘触发 · 柳工 · 跌破 7.71');
    const separator = ctx.store.messages.listByTask(task?.id ?? '')[0];
    expect(separator?.content).toContain('盯盘触发');
    const prompt = ctx.driver.prompts[0] ?? '';
    expect(prompt).toContain('先取实时数据核对');
    expect(prompt).toContain('notify_user');
    expect(prompt).toContain('watch_plan_update');
    expect(prompt).toContain('不下单');
    expect(prompt).toContain('设置理由：跌破支撑先看量能');
    expect(prompt).toContain('observe → execute');
    expect(prompt).toContain('8.7');
    expect(ctx.store.watches.get(watch.id)?.status).toBe('triggered');
    expect(engine.plans.has(`chives-${watch.id}`)).toBe(false);
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
  });

  it('queues a trigger while the bot is busy and wakes it when that task ends', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    ctx.watches.start();
    const busy = ctx.store.tasks.create({
      botId: 'expert',
      title: '用户正在对话',
      startedAt: ctx.now().toISOString(),
      depth: 0,
      delegated: false,
    });
    const queued = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: ctx.now(),
    });
    expect(queued).toEqual({ status: 'skipped', reason: 'bot_busy_queued' });
    expect(ctx.watches.pendingWatchIds()).toEqual([watch.id]);
    expect(ctx.store.watches.get(watch.id)?.status).toBe('active');
    expect(ctx.store.watches.events(watch.id).map((event) => event.kind)).toContain('trigger_queued');

    const done = ctx.store.tasks.finish(busy.id, 'done', ctx.now().toISOString());
    ctx.bus.publish({ type: 'task.updated', botId: 'expert', taskId: busy.id, task: toTaskDto(done) });
    await waitFor(() => ctx.store.watches.get(watch.id)?.status === 'triggered');
    const triggered = ctx.store.watches.get(watch.id);
    expect(triggered?.triggerTaskId).not.toBeNull();
    expect(ctx.store.tasks.get(triggered?.triggerTaskId ?? '')?.title).toBe('盯盘触发 · 柳工 · 跌破 7.71');
    expect(ctx.watches.pendingWatchIds()).toEqual([]);
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
  });

  it('catches up a one-shot watch the engine already shows as triggered', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const plan = engine.plans.get(`chives-${watch.id}`);
    if (plan === undefined) throw new Error('plan missing');
    plan.state = 'execute';
    await ctx.watches.tick();
    await waitFor(() => ctx.store.watches.get(watch.id)?.status === 'triggered');
    const prompt = ctx.driver.prompts[0] ?? '';
    expect(prompt).toContain('补触发');
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
  });

  it('gives up a trigger queued for over 30 minutes and notifies the user instead', async () => {
    const engine = await fakeEngine();
    const clock = { value: new Date('2026-11-17T02:00:00.000Z') };
    const ctx = await setup({ engine, now: clock });
    const watch = await ctx.watches.create('expert', null, baseInput);
    ctx.store.tasks.create({
      botId: 'expert',
      title: '长任务',
      startedAt: clock.value.toISOString(),
      depth: 0,
      delegated: false,
    });
    await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: clock.value,
    });
    clock.value = new Date('2026-11-17T02:31:00.000Z');
    await ctx.watches.flushPending();
    expect(ctx.store.watches.get(watch.id)?.status).toBe('triggered');
    expect(ctx.store.watches.get(watch.id)?.triggerTaskId).toBeNull();
    const notes = ctx.store.notifications.list({ unreadOnly: true, limit: 10 });
    expect(notes.some((note) => note.body.includes('bot 一直在忙'))).toBe(true);
    expect(ctx.watches.pendingWatchIds()).toEqual([]);
  });

  it('keeps repeat watches active but suppresses a wake-up within 30 minutes', async () => {
    const engine = await fakeEngine();
    const holder = { value: new Date('2026-11-17T02:00:00.000Z') };
    const ctx = await setup({ engine, now: holder });
    const watch = await ctx.watches.create('expert', null, { ...baseInput, repeat: true });
    const first = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: holder.value,
    });
    expect(first.status).toBe('started');
    expect(ctx.store.watches.get(watch.id)?.status).toBe('active');
    holder.value = new Date('2026-11-17T02:10:00.000Z');
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
    const second = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: holder.value,
    });
    expect(second).toEqual({ status: 'skipped', reason: 'repeat_cooldown' });
    holder.value = new Date('2026-11-17T02:40:00.000Z');
    const third = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: holder.value,
    });
    expect(third.status).toBe('started');
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
  });

  it('only mirrors engine_state for await_confirm', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const result = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`, { to: 'await_confirm' }),
      now: ctx.now(),
    });
    expect(result).toEqual({ status: 'skipped', reason: 'await_confirm' });
    expect(ctx.store.watches.get(watch.id)?.engineState).toBe('await_confirm');
    expect(ctx.store.tasks.listWithErrorCode(10)).toHaveLength(0);
  });

  it('notifies directly, writes a notice and still marks triggered with automatic analysis disabled', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    ctx.store.settings.set('proactive', { enabled: true, dailyLimit: 0, observeOnly: false });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const result = await ctx.watches.handleTrigger({
      planId: `chives-${watch.id}`,
      alert: alertFor(`chives-${watch.id}`),
      now: ctx.now(),
    });
    expect(result).toEqual({ status: 'skipped', reason: 'auto_analysis_disabled' });
    const rows = ctx.store.notifications.list({ limit: 10 });
    expect(rows).toHaveLength(1);
    expect(rows[0]?.level).toBe('important');
    expect(rows[0]?.title).toContain('盯盘已触发');
    expect(rows[0]?.body).toContain('自动分析已关闭');
    expect(ctx.store.messages.listByKind('notice').some((message) => message.meta?.['code'] === 'auto_analysis_disabled')).toBe(true);
    expect(ctx.store.watches.get(watch.id)?.status).toBe('triggered');
  });

  it('rejects edits and deletes of another bot’s watch', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    await expect(
      ctx.watches.update('research', null, watch.id, { note: 'x' }),
    ).rejects.toMatchObject({ code: 'not_found' });
    await expect(ctx.watches.cancelByBot('research', null, watch.id)).rejects.toMatchObject({
      code: 'not_found',
    });
  });
});


describe('alert routing', () => {
  it('routes chives- plan alerts to the owning bot and keeps card- alerts skipped', async () => {
    const engine = await fakeEngine();
    const ctx = await setup({ engine });
    const watch = await ctx.watches.create('expert', null, baseInput);
    const alertsConfig: AlertsConfig = {
      sources: [
        {
          name: 'cn-watch',
          url: engine.url,
          enabled: true,
          cursorParam: 'after_id',
          batchLimit: 100,
        },
      ],
      routes: [{ source: 'cn-watch', ruleId: '*', code: '*', bot: 'expert' }],
      limits: {
        cooldownSeconds: 1800,
        maxAlertAgeSeconds: 300,
        runTimeoutSeconds: 600,
        batchSize: 5,
        pollSeconds: 1,
        observeOnly: false,
      },
    };
    const service = new AlertService({
      config: alertsConfig,
      store: ctx.store,
      registry: ctx.registry,
      orchestrator: ctx.orchestrator,
      now: ctx.now,
      dataDir: join(tmpdir(), 'chives-watch-alert-data'),
      repoRoot: join(process.cwd(), '..', '..'),
      watches: ctx.watches,
      fetchImpl: fetch,
      log: () => undefined,
    });
    cleanups.push(async () => service.close());
    await service.tick();
    engine.alerts.push({
      ...alertFor(`chives-${watch.id}`).raw,
      id: 2,
    });
    await service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
    const started = ctx.store.tasks.listWithErrorCode(10);
    expect(started).toHaveLength(0);
    const events = ctx.store.alertEvents.list(10);
    expect(events.some((event) => event.status === 'started')).toBe(true);

    engine.alerts.push({
      id: 3,
      ts: new Date().toISOString(),
      code: '600519.SH',
      name: '贵州茅台',
      rule_id: 'plan:card-42',
      rule_type: 'plan',
      detail: { plan_id: 'card-42', from: 'observe', to: 'execute', reason: 'hub' },
    });
    await service.tick();
    const skipped = ctx.store.alertEvents.list(10).filter((event) => event.reason === 'plan_alert');
    expect(skipped.length).toBeGreaterThan(0);
  });
});
