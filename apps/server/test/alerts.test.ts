import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { loadAlertsConfig, parseAlertsConfig, isLoopbackUrl } from '../src/alerts/index.js';
import { AlertService, type AlertsConfig } from '../src/alerts/index.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { Orchestrator } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import { makeRegistry, repoRoot, testConfig, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

interface Engine {
  alerts: Array<Record<string, unknown>>;
  calls: string[];
  fail: boolean;
}

const baseConfig: AlertsConfig = {
  sources: [{ name: 'cn-watch', url: 'http://127.0.0.1:8865', enabled: true, cursorParam: 'after_id', batchLimit: 100 }],
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

function alert(id: number, now: Date, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id,
    ts: now.toISOString(),
    code: '600519.SH',
    name: '贵州茅台',
    rule_id: 'pct_up_3',
    rule_type: 'pct_change',
    price: 1500,
    change_pct: 3.2,
    ...overrides,
  };
}

async function setup(options: {
  holder: { now: Date };
  engine: Engine;
  config?: AlertsConfig;
}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-alert-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const orchestrator = new Orchestrator({
    registry: makeRegistry(),
    store,
    bus,
    driver: new FakeDriver(),
    now: () => options.holder.now,
    dataDir,
  });
  orchestrator.start();
  const fetchImpl = (async (url: string | URL | Request) => {
    options.engine.calls.push(String(url));
    if (options.engine.fail) throw new Error('connect ECONNREFUSED');
    return new Response(JSON.stringify({ alerts: options.engine.alerts }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof fetch;
  const service = new AlertService({
    config: options.config ?? baseConfig,
    store,
    registry: makeRegistry(),
    orchestrator,
    now: () => options.holder.now,
    dataDir,
    repoRoot,
    fetchImpl,
    log: () => undefined,
  });
  cleanups.push(async () => {
    service.close();
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, orchestrator, service, dataDir, engine: options.engine };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

function tasks(store: Store): Array<{ origin: string | null; id: string }> {
  return store.db.prepare('SELECT id, origin FROM tasks ORDER BY rowid').all() as unknown as Array<{
    origin: string | null;
    id: string;
  }>;
}

describe('alert config', () => {
  it('accepts loopback only and builds defaults when the file is absent', () => {
    expect(isLoopbackUrl('http://127.0.0.1:8865')).toBe(true);
    expect(isLoopbackUrl('http://localhost:8865')).toBe(true);
    expect(isLoopbackUrl('http://127.0.0.1.evil.com:8865')).toBe(false);
    expect(isLoopbackUrl('http://user:pass@127.0.0.1:8865')).toBe(false);
    expect(() => parseAlertsConfig('sources:\n  cn-watch:\n    url: http://10.0.0.1:1\n')).toThrow(/loopback/);
    expect(parseAlertsConfig('limits:\n  batch_size: 2\n').limits.batchSize).toBe(2);
    expect(loadAlertsConfig(repoRoot).routes.length).toBeGreaterThan(0);
  });
});

describe('AlertService', () => {
  it('baselines on first poll, then starts a proactive task with a proactive separator', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const engine: Engine = { alerts: [alert(1, holder.now), alert(2, holder.now)], calls: [], fail: false };
    const ctx = await setup({ holder, engine });

    await ctx.service.tick();
    expect(tasks(ctx.store)).toHaveLength(0);
    expect(ctx.store.alertEvents.list(10)).toHaveLength(0);

    holder.now = new Date('2026-11-16T02:01:00.000Z');
    engine.alerts.push(alert(3, holder.now, { name: '贵州茅台<b>' }));
    await ctx.service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);

    const rows = tasks(ctx.store);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.origin).toBe('alert');
    const messages = ctx.store.messages.listByTask(rows[0]?.id ?? '');
    expect(messages[0]?.kind).toBe('proactive');
    expect(messages[0]?.content).toMatch(/^盯盘告警 · 10:01 · 贵州茅台/);
    expect(messages.some((message) => message.role === 'bot' && message.content.includes('<alert_data>'))).toBe(
      true,
    );
    expect(messages.some((message) => message.role === 'bot' && message.content.includes('\\u003c'))).toBe(true);

    const events = ctx.store.alertEvents.list(10);
    expect(events[0]?.status).toBe('started');
    expect(events[0]?.source).toBe('cn-watch');
    expect(events[0]?.taskId).toBe(rows[0]?.id);
  });

  it('skips plan alerts, stale alerts, cooldowns, disabled automatic analysis and observe mode', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const engine: Engine = { alerts: [alert(1, holder.now)], calls: [], fail: false };
    const ctx = await setup({ holder, engine });
    await ctx.service.tick();

    holder.now = new Date('2026-11-16T02:01:00.000Z');
    engine.alerts.push(
      alert(2, holder.now, { rule_id: 'plan:card-1', rule_type: 'plan' }),
      alert(3, new Date('2026-11-16T01:00:00.000Z')),
      alert(4, holder.now),
    );
    await ctx.service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
    let events = ctx.store.alertEvents.list(10);
    expect(events.find((event) => event.alertId === 2)?.reason).toBe('plan_alert');
    expect(events.find((event) => event.alertId === 3)?.reason).toBe('stale_alert');
    expect(events.find((event) => event.alertId === 4)?.status).toBe('started');

    holder.now = new Date('2026-11-16T02:02:00.000Z');
    engine.alerts.push(alert(5, holder.now));
    await ctx.service.tick();
    events = ctx.store.alertEvents.list(10);
    expect(events.find((event) => event.alertId === 5)?.reason).toBe('cooldown');

    ctx.store.settings.set('proactive', { enabled: true, autoAnalysis: false, observeOnly: false });
    holder.now = new Date('2026-11-16T02:03:00.000Z');
    engine.alerts.push(alert(6, holder.now, { code: '300750.SZ' }));
    await ctx.service.tick();
    expect(ctx.store.alertEvents.list(20).find((event) => event.alertId === 6)?.reason).toBe('auto_analysis_disabled');

    ctx.store.settings.set('proactive', { enabled: true, dailyLimit: 20, observeOnly: true });
    holder.now = new Date('2026-11-16T02:04:00.000Z');
    engine.alerts.push(alert(7, holder.now, { code: '601099.SH' }));
    await ctx.service.tick();
    expect(ctx.store.alertEvents.list(20).find((event) => event.alertId === 7)?.reason).toBe('observe_only');
  });

  it('honours STOP, the master switch, queue overflow, and batch order', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const engine: Engine = { alerts: [alert(1, holder.now)], calls: [], fail: false };
    const config = { ...baseConfig, limits: { ...baseConfig.limits, batchSize: 2 } };
    const ctx = await setup({ holder, engine, config });
    await ctx.service.tick();

    holder.now = new Date('2026-11-16T02:01:00.000Z');
    engine.alerts.push(
      alert(2, holder.now, { code: '000001.SZ' }),
      alert(3, holder.now, { code: '000002.SZ' }),
      alert(4, holder.now, { code: '000003.SZ' }),
      alert(5, holder.now, { code: '000004.SZ' }),
    );
    await ctx.service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
    const events = ctx.store.alertEvents.list(10);
    expect(events.find((event) => event.alertId === 2)?.reason).toBe('queue_overflow');
    expect(events.find((event) => event.alertId === 3)?.reason).toBe('queue_overflow');
    expect(events.find((event) => event.alertId === 4)?.status).toBe('started');
    expect(events.find((event) => event.alertId === 5)?.reason).toBe('bot_busy');

    await writeFile(join(ctx.dataDir, 'STOP'), '');
    holder.now = new Date('2026-11-16T02:02:00.000Z');
    engine.alerts.push(alert(6, holder.now, { code: '000005.SZ' }));
    await ctx.service.tick();
    expect(ctx.store.alertEvents.list(20).find((event) => event.alertId === 6)?.reason).toBe('kill_switch');

    await rm(join(ctx.dataDir, 'STOP'));
    ctx.store.settings.set('proactive', { enabled: false, dailyLimit: 20, observeOnly: false });
    holder.now = new Date('2026-11-16T02:03:00.000Z');
    engine.alerts.push(alert(7, holder.now, { code: '000006.SZ' }));
    await ctx.service.tick();
    expect(ctx.store.alertEvents.list(20).find((event) => event.alertId === 7)?.reason).toBe('disabled');
  });

  it('backs off exponentially when an engine is unreachable', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const engine: Engine = { alerts: [], calls: [], fail: true };
    const ctx = await setup({ holder, engine });
    await ctx.service.tick();
    expect(engine.calls).toHaveLength(1);
    await ctx.service.tick();
    expect(engine.calls).toHaveLength(1);
    holder.now = new Date('2026-11-16T02:00:03.000Z');
    await ctx.service.tick();
    expect(engine.calls).toHaveLength(2);
  });

  it('cancels a task that outlives the run timeout', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const engine: Engine = { alerts: [alert(1, holder.now)], calls: [], fail: false };
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-alert-timeout-'));
    const store = Store.open(dataDir);
    const cancelled: string[] = [];
    const timers: Array<{ fn: () => void }> = [];
    const fakeOrchestrator = {
      submitProactive: async () => ({ messageId: 'm1', taskId: 'task-1' }),
      cancelTask: (id: string) => {
        cancelled.push(id);
        return { taskId: id };
      },
    };
    store.tasks.create({ id: 'task-1', botId: 'expert', startedAt: holder.now.toISOString() });
    const service = new AlertService({
      config: baseConfig,
      store,
      registry: makeRegistry(),
      orchestrator: fakeOrchestrator as unknown as Orchestrator,
      now: () => holder.now,
      dataDir,
      repoRoot,
      fetchImpl: (async () => new Response(JSON.stringify({ alerts: engine.alerts }), { status: 200 })) as typeof fetch,
      log: () => undefined,
      scheduleTimeout: (fn) => {
        timers.push({ fn });
        return { unref: () => undefined };
      },
      clearScheduledTimeout: () => undefined,
    });
    cleanups.push(async () => {
      service.close();
      store.close();
      await rm(dataDir, { recursive: true, force: true });
    });
    await service.tick();
    engine.alerts.push(alert(2, holder.now, { code: '300750.SZ' }));
    await service.tick();
    expect(timers.length).toBeGreaterThan(0);
    timers.at(-1)?.fn();
    expect(cancelled).toEqual(['task-1']);
  });

  it('polls two real fake HTTP engines with their own cursor parameter', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const cn: Engine = { alerts: [], calls: [], fail: false };
    const market: Engine = { alerts: [], calls: [], fail: false };
    const servers: Server[] = [];
    const boot = async (engine: Engine): Promise<string> => {
      const server = createServer((request, response) => {
        engine.calls.push(request.url ?? '');
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ ok: true, alerts: engine.alerts }));
      });
      servers.push(server);
      await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
      return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    };
    const cnUrl = await boot(cn);
    const marketUrl = await boot(market);
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-alert-http-'));
    const store = Store.open(dataDir);
    const orchestrator = new Orchestrator({
      registry: makeRegistry(),
      store,
      bus: new EventBus(),
      driver: new FakeDriver(),
      now: () => holder.now,
      dataDir,
    });
    orchestrator.start();
    const config: AlertsConfig = {
      sources: [
        { name: 'cn-watch', url: cnUrl, enabled: true, cursorParam: 'after_id', batchLimit: 100 },
        { name: 'market-watch', url: marketUrl, enabled: true, cursorParam: 'since_id', batchLimit: 50 },
      ],
      routes: [
        { source: 'cn-watch', ruleId: '*', code: '*', bot: 'expert' },
        { source: 'market-watch', ruleId: '*', code: '*', bot: 'research' },
      ],
      limits: { ...baseConfig.limits, batchSize: 5 },
    };
    const service = new AlertService({
      config,
      store,
      registry: makeRegistry(),
      orchestrator,
      now: () => holder.now,
      dataDir,
      repoRoot,
      log: () => undefined,
    });
    cleanups.push(async () => {
      service.close();
      await orchestrator.close();
      store.close();
      for (const server of servers) {
        await new Promise<void>((resolve) => server.close(() => resolve()));
      }
      await rm(dataDir, { recursive: true, force: true });
    });

    await service.tick();
    expect(cn.calls[0]).toContain('after_id=0');
    expect(market.calls[0]).toContain('since_id=0');

    holder.now = new Date('2026-11-16T02:01:00.000Z');
    cn.alerts.push(alert(1, holder.now, { code: '600519.SH' }));
    market.alerts.push({
      id: 1,
      ts: holder.now.toISOString(),
      rule_id: 'R1',
      title: '沪深300 快速下跌',
      object: { type: 'index', code: '000300.SH', name: '沪深300' },
    });
    await service.tick();
    await waitFor(
      () =>
        store.tasks.findRunning('expert') === undefined &&
        store.tasks.findRunning('research') === undefined,
    );
    const events = store.alertEvents.list(10);
    expect(events.filter((event) => event.status === 'started')).toHaveLength(2);
    expect(events.map((event) => event.source).sort()).toEqual(['cn-watch', 'market-watch']);
    expect(cn.calls[1]).toContain('after_id=0');
    expect(market.calls[1]).toContain('since_id=0');
    expect(store.tasks.latestForBot('expert')?.origin).toBe('alert');
    expect(store.tasks.latestForBot('research')?.origin).toBe('alert');
  });

  it('uses the real test config for the app wiring', () => {
    expect(testConfig('/tmp/x').harness).toBe('fake');
  });
});
