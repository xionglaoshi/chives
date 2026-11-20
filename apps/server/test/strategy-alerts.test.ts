import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { AlertService, type AlertsConfig } from '../src/alerts/index.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { Orchestrator } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import { makeRegistry, repoRoot, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

const config: AlertsConfig = {
  sources: [
    {
      name: 'strategy-hub',
      url: 'http://127.0.0.1:8869',
      enabled: true,
      cursorParam: 'since_id',
      batchLimit: 500
    }
  ],
  routes: [],
  limits: {
    cooldownSeconds: 1800,
    maxAlertAgeSeconds: 300,
    runTimeoutSeconds: 600,
    batchSize: 5,
    pollSeconds: 1,
    observeOnly: false
  }
};

interface Engine {
  alerts: Array<Record<string, unknown>>;
  calls: string[];
}

function strategyAlert(
  id: number,
  now: Date,
  overrides: Record<string, unknown> = {}
): Record<string, unknown> {
  return {
    id,
    strategy_id: 'zhushenglang',
    rule_id: 'zhushenglang:优先级一确定',
    code: '600519.SH',
    name: '贵州茅台',
    level: 'important',
    event: '优先级一确定',
    event_date: '2026-11-17',
    title: '贵州茅台 600519.SH 优先级一确定',
    detail: JSON.stringify({ strategy_id: 'zhushenglang', event: '优先级一确定' }),
    created_at: now.toISOString(),
    ...overrides
  };
}

async function setup(engine: Engine, limits: Partial<AlertsConfig['limits']> = {}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-strategy-alert-'));
  const store = Store.open(dataDir);
  const orchestrator = new Orchestrator({
    registry: makeRegistry(),
    store,
    bus: new EventBus(),
    driver: new FakeDriver(),
    now: () => holder.now,
    dataDir
  });
  orchestrator.start();
  const fetchImpl = (async (url: string | URL | Request) => {
    engine.calls.push(String(url));
    return new Response(JSON.stringify({ alerts: engine.alerts }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  }) as typeof fetch;
  const service = new AlertService({
    config: { ...config, limits: { ...config.limits, ...limits } },
    store,
    registry: makeRegistry(),
    orchestrator,
    now: () => holder.now,
    dataDir,
    repoRoot,
    fetchImpl,
    log: () => undefined
  });
  cleanups.push(async () => {
    service.close();
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, service };
}

const holder = { now: new Date('2026-11-17T07:35:00.000Z') };

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

function tasks(store: Store): Array<{ id: string; origin: string | null }> {
  return store.db.prepare('SELECT id, origin FROM tasks ORDER BY rowid').all() as unknown as Array<{
    id: string;
    origin: string | null;
  }>;
}

describe('strategy-hub alerts', () => {
  it('merges one trading day of important events into a single wake and lists every event', async () => {
    const engine: Engine = { alerts: [], calls: [] };
    const { store, service } = await setup(engine);
    await service.tick();

    engine.alerts.push(
      strategyAlert(1, holder.now, { code: '600519.SH', name: '贵州茅台' }),
      strategyAlert(2, holder.now, {
        code: '000001.SZ',
        name: '平安银行',
        event: '入主升浪池',
        rule_id: 'zhushenglang:入主升浪池',
        title: '平安银行 000001.SZ 入主升浪池'
      }),
      strategyAlert(3, holder.now, {
        level: 'info',
        event: 'MA10跌破',
        rule_id: 'zhushenglang:MA10跌破',
        code: '600519.SH'
      })
    );
    await service.tick();
    await waitFor(() => store.tasks.findRunning('zhushenglang') === undefined);

    const rows = tasks(store);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.origin).toBe('alert');
    const messages = store.messages.listByTask(rows[0]?.id ?? '');
    const text = messages.map((message) => message.content).join('\n');
    expect(text).toContain('策略事件');
    expect(text).toContain('贵州茅台');
    expect(text).toContain('平安银行');
    expect(text).toContain('2 条');
    expect(text).toContain('strategy_pools');
    expect(text).toContain('strategy_round');
    expect(text).toContain('600519.SH');
    expect(text).toContain('000001.SZ');
    expect(text).not.toContain('MA10跌破');

    const events = store.alertEvents.list(20);
    expect(events.filter((event) => event.status === 'started')).toHaveLength(2);
    expect(events.find((event) => event.alertId === 3)?.reason).toBe('not_important');
  });

  it('does not wake any bot when nobody subscribes, and does not wake twice on the same day', async () => {
    const engine: Engine = { alerts: [], calls: [] };
    const { store, service } = await setup(engine);
    await service.tick();

    engine.alerts.push(
      strategyAlert(1, holder.now, {
        strategy_id: 'other',
        rule_id: 'other:优先级一确定',
        code: '000002.SZ'
      })
    );
    await service.tick();
    await waitFor(() => tasks(store).length === 0);
    expect(store.alertEvents.list(10).find((event) => event.alertId === 1)?.reason).toBe(
      'not_subscribed'
    );

    engine.alerts.push(strategyAlert(2, holder.now));
    await service.tick();
    await waitFor(() => store.tasks.findRunning('zhushenglang') === undefined);
    expect(tasks(store)).toHaveLength(1);

    engine.alerts.push(
      strategyAlert(3, holder.now, {
        code: '601318.SH',
        name: '中国平安',
        event: '主升浪移出',
        rule_id: 'zhushenglang:主升浪移出'
      })
    );
    await service.tick();
    expect(store.tasks.findRunning('zhushenglang')).toBeUndefined();
    expect(tasks(store)).toHaveLength(1);
    expect(store.alertEvents.list(20).find((event) => event.alertId === 3)?.reason).toBe(
      'already_woken_today'
    );
  });

  it('ignores an old positive daily cap after more than twenty analyses', async () => {
    const engine: Engine = { alerts: [], calls: [] };
    const { store, service } = await setup(engine);
    await service.tick();
    store.settings.set('proactive', { enabled: true, dailyLimit: 1, observeOnly: false });
    for (let i=0;i<25;i++) store.tasks.create({
      botId: 'expert',
      title: 'already used today',
      startedAt: holder.now.toISOString(),
      depth: 0,
      delegated: false,
      origin: 'alert'
    });
    engine.alerts.push(strategyAlert(1, holder.now));
    await service.tick();
    expect(store.alertEvents.list(10).find((event) => event.alertId === 1)?.status).toBe('started');
  });
});
