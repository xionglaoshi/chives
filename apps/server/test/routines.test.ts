import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import type { ServerEvent } from '../src/api/protocol.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { Orchestrator } from '../src/orchestrator.js';
import {
  RoutineService,
  computeNextRun,
  describeSchedule,
  loadTradingDays,
  nextCronRun,
  validateCron,
} from '../src/routines/index.js';
import { Store } from '../src/store/index.js';
import { makeRegistry, repoRoot, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

async function setup(options: {
  clock: { now: Date };
  tradingDays?: ReadonlySet<string>;
  start?: () => Date;
}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-routine-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: ServerEvent[] = [];
  bus.subscribe((event) => events.push(event));
  const driver = new FakeDriver();
  const orchestrator = new Orchestrator({
    registry: makeRegistry(),
    store,
    bus,
    driver,
    now: () => clock(options.clock),
  });
  orchestrator.start();
  const service = new RoutineService({
    registry: makeRegistry(),
    store,
    orchestrator,
    now: () => options.clock.now,
    repoRoot,
    log: () => undefined,
    ...(options.tradingDays === undefined ? {} : { tradingDays: options.tradingDays }),
  });
  cleanups.push(async () => {
    service.stop();
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, events, orchestrator, service, dataDir };
}

function clock(holder: { now: Date }): Date {
  return holder.now;
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('cron', () => {
  it('finds the next weekday 08:30 in Asia/Shanghai across the weekend', () => {
    const parsed = validateCron('30 8 * * 1-5');
    const next = nextCronRun(parsed, 'Asia/Shanghai', new Date('2026-11-13T01:00:00.000Z'));
    expect(next.toISOString()).toBe('2026-11-16T00:30:00.000Z');
    expect(describeSchedule({ kind: 'cron', expression: '30 8 * * 1-5', tz: 'Asia/Shanghai' })).toBe(
      '工作日 08:30（北京时间）',
    );
  });

  it('supports */15, ranges, month/day crossing and UTC', () => {
    expect(
      nextCronRun(
        validateCron('*/15 * * * *'),
        'UTC',
        new Date('2026-11-16T10:07:30.000Z'),
      ).toISOString(),
    ).toBe('2026-11-16T10:15:00.000Z');
    expect(
      nextCronRun(validateCron('0 0 * * *'), 'UTC', new Date('2026-11-16T23:59:00.000Z')).toISOString(),
    ).toBe('2026-11-17T00:00:00.000Z');
    expect(
      nextCronRun(validateCron('0 9 1-5 * *'), 'UTC', new Date('2026-11-06T09:01:00.000Z')).toISOString(),
    ).toBe('2026-12-01T09:00:00.000Z');
  });

  it('rejects malformed expressions and computes every/once schedules', () => {
    expect(() => validateCron('30 8 * *')).toThrow(/5 space-separated/);
    expect(() => validateCron('61 8 * * *')).toThrow(/minute/);
    expect(validateCron('0 7 * * 0').weekday.has(0)).toBe(true);
    expect(
      computeNextRun({ kind: 'every', minutes: 15 }, new Date('2026-11-16T10:07:00.000Z'))?.toISOString(),
    ).toBe('2026-11-16T10:15:00.000Z');
    expect(computeNextRun({ kind: 'once', at: '2026-11-16T10:00:00.000Z' }, new Date())).toBeNull();
  });

  it('loads the real trade calendar', () => {
    const days = loadTradingDays(repoRoot);
    expect(days.size).toBeGreaterThan(100);
    expect(days.has('2026-11-16')).toBe(true);
  });
});

describe('RoutineService', () => {
  it('skips a scheduled run in observation mode and resumes at the next occurrence', async () => {
    const holder = {now:new Date('2026-11-16T00:00:00Z')};
    const ctx = await setup({clock:holder,tradingDays:new Set(['2026-11-16','2026-11-17'])});
    ctx.service.syncManifest();
    ctx.store.settings.set('proactive',{observeOnly:true});
    holder.now = new Date('2026-11-16T00:30:02Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();
    ctx.store.settings.set('proactive',{observeOnly:false});
    holder.now = new Date('2026-11-17T00:30:02Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')?.origin).toBe('routine');
  });

  it('syncs the built-in premarket routine disabled/enabled state and runs it at 08:30', async () => {
    const holder = { now: new Date('2026-11-16T00:00:00.000Z') };
    const ctx = await setup({
      clock: holder,
      tradingDays: new Set(['2026-11-16']),
    });
    ctx.service.syncManifest();
    const routines = ctx.store.routines.listByBot('expert');
    const premarket = routines.find((routine) => routine.title === '盘前简报');
    expect(premarket?.source).toBe('manifest');
    expect(premarket?.enabled).toBe(true);
    expect(premarket?.schedule).toEqual({ kind: 'cron', expression: '30 8 * * 1-5', tz: 'Asia/Shanghai' });

    holder.now = new Date('2026-11-16T00:30:05.000Z');
    await ctx.service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);

    const created = ctx.store.tasks.latestForBot('expert');
    expect(created?.origin).toBe('routine');
    const messages = ctx.store.messages.listByTask(created?.id ?? '');
    expect(messages[0]?.kind).toBe('proactive');
    expect(messages[0]?.content).toBe('主动消息 · 08:30 · 盘前简报');
    expect(messages.some((message) => message.role === 'bot' && message.content.includes('按 morning-note 技能出盘前简报'))).toBe(true);
    expect(ctx.events.some((event) => event.type === 'message.created' && event.message.kind === 'proactive')).toBe(true);

    const after = ctx.store.routines.get(premarket?.id ?? '');
    expect(after?.lastRunAt).toBe('2026-11-16T00:30:05.000Z');
    expect(after?.nextRunAt).toBe('2026-11-17T00:30:00.000Z');
  });

  it('does not run when disabled, on a non-trading day, or when the occurrence is more than 15 minutes late', async () => {
    const holder = { now: new Date('2026-11-16T00:00:00.000Z') };
    const ctx = await setup({ clock: holder, tradingDays: new Set(['2026-11-17']) });
    ctx.service.syncManifest();
    const premarket = ctx.store.routines.listByBot('expert').find((entry) => entry.title === '盘前简报');
    if (premarket === undefined) throw new Error('missing premarket routine');

    holder.now = new Date('2026-11-16T00:30:05.000Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();
    expect(ctx.store.routines.get(premarket.id)?.lastRunAt).toBeNull();

    ctx.store.routines.setEnabled(premarket.id, false);
    ctx.service.syncManifest();
    expect(ctx.store.routines.get(premarket.id)?.enabled).toBe(false);

    holder.now = new Date('2026-11-17T00:00:00.000Z');
    ctx.service.syncManifest();
    holder.now = new Date('2026-11-17T00:30:10.000Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();

    ctx.store.routines.setEnabled(premarket.id, true);
    holder.now = new Date('2026-11-17T00:50:00.000Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();
    expect(ctx.store.routines.get(premarket.id)?.nextRunAt).toBe('2026-11-18T00:30:00.000Z');
  });

  it('replays only the most recent occurrence when it is less than 15 minutes late', async () => {
    const holder = { now: new Date('2026-11-16T00:00:00.000Z') };
    const ctx = await setup({ clock: holder, tradingDays: new Set(['2026-11-16']) });
    ctx.service.syncManifest();

    holder.now = new Date('2026-11-16T00:40:00.000Z');
    await ctx.service.tick();
    await waitFor(() => ctx.store.tasks.findRunning('expert') === undefined);
    expect(ctx.store.tasks.latestForBot('expert')?.origin).toBe('routine');

    const second = { now: new Date('2026-11-17T00:00:00.000Z') };
    const late = await setup({ clock: second, tradingDays: new Set(['2026-11-17']) });
    late.service.syncManifest();
    second.now = new Date('2026-11-17T00:50:00.000Z');
    await late.service.tick();
    expect(late.store.tasks.latestForBot('expert')).toBeUndefined();
    const routine = late.store.routines.listByBot('expert').find((entry) => entry.title === '盘前简报');
    expect(late.store.routines.get(routine?.id ?? '')?.nextRunAt).toBe('2026-11-18T00:30:00.000Z');
  });

  it('creates user routines disabled by default and honours the automatic analysis permission', async () => {
    const holder = { now: new Date('2026-11-16T02:00:00.000Z') };
    const ctx = await setup({ clock: holder, tradingDays: new Set(['2026-11-16']) });
    const created = ctx.service.createForBot('expert', {
      title: '盯一下',
      schedule: { every_minutes: 30 },
      prompt: '看看自选股',
    });
    expect(created.source).toBe('user');
    expect(created.enabled).toBe(false);
    expect(created.nextRunAt).toBe('2026-11-16T02:30:00.000Z');

    ctx.service.setEnabled(created.id, true);
    await ctx.store.settings.set('proactive', { enabled: true, autoAnalysis: false, observeOnly: false });
    holder.now = new Date('2026-11-16T02:30:01.000Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();

    await ctx.store.settings.set('proactive', { enabled: false, dailyLimit: 20, observeOnly: false });
    holder.now = new Date('2026-11-16T03:00:01.000Z');
    await ctx.service.tick();
    expect(ctx.store.tasks.latestForBot('expert')).toBeUndefined();
    ctx.store.settings.set('proactive', {enabled: true, autoAnalysis: false});
    const manual = await ctx.service.runNow(created.id);
    expect(ctx.store.tasks.latestForBot('expert')?.id).toBe(manual.taskId);
  });
});
