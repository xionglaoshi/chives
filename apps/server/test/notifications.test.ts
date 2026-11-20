import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { EventBus } from '../src/events/index.js';
import { NotificationService } from '../src/notifications/index.js';
import { Store } from '../src/store/index.js';

const cleanups: Array<() => Promise<void>> = [];

async function setup() {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-notify-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: string[] = [];
  bus.subscribe((event) => events.push(event.type));
  const calls: Array<{ file: string; args: string[] }> = [];
  const now = new Date('2026-11-17T02:00:00.000Z');
  const service = new NotificationService({
    store,
    bus,
    now: () => now,
    platform: 'darwin',
    execFile: (file, args, _options, callback) => {
      calls.push({ file, args: [...args] });
      callback(null);
    },
    log: () => undefined,
  });
  const userTask = store.tasks.create({
    botId: 'expert',
    title: '用户任务',
    startedAt: now.toISOString(),
  });
  const proactive = store.tasks.create({
    botId: 'expert',
    title: '盯盘触发',
    startedAt: now.toISOString(),
    origin: 'alert',
  });
  cleanups.push(async () => {
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, events, calls, service, userTask, proactive };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('notify_user', () => {
  it('persists a notification and a distinct timeline row, and does not pop up for a foreground turn', async () => {
    const ctx = await setup();
    const result = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.userTask.id,
      title: '柳工放量',
      body: '现价 8.62，量比 2.1，10:31',
      level: 'important',
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.notification.readAt).toBeNull();
    const messages = ctx.store.messages.listByTask(ctx.userTask.id);
    const notice = messages.find((message) => message.kind === 'notice');
    expect(notice?.meta?.['notification']).toBe(true);
    expect(notice?.content).toContain('柳工放量');
    expect(ctx.events).toContain('notification.created');
    expect(ctx.calls).toHaveLength(0);
  });

  it('calls osascript with a properly escaped argument array for a proactive task', async () => {
    const ctx = await setup();
    const result = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: '他说"跌破"',
      body: '路径 C:\\tmp\\x 与 "引号"',
      level: 'urgent',
    });
    expect(result.ok).toBe(true);
    expect(ctx.calls).toHaveLength(1);
    expect(ctx.calls[0]?.file).toBe('osascript');
    const script = ctx.calls[0]?.args[1] ?? '';
    expect(ctx.calls[0]?.args).toEqual(['-e', script]);
    expect(script).toBe(
      'display notification "路径 C:\\\\tmp\\\\x 与 \\"引号\\"" with title "他说\\"跌破\\""',
    );
  });

  it('rate-limits two notifications per task and six per bot per hour', async () => {
    const ctx = await setup();
    const first = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: 'a',
      body: 'b',
      level: 'info',
    });
    const second = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: 'a',
      body: 'b',
      level: 'info',
    });
    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    const third = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: 'a',
      body: 'b',
      level: 'info',
    });
    expect(third).toMatchObject({ ok: false, code: 'rate_limited' });

    for (let index = 0; index < 4; index += 1) {
      const task = ctx.store.tasks.create({
        botId: 'expert',
        title: `t${index}`,
        startedAt: new Date().toISOString(),
        origin: 'alert',
      });
      expect(
        ctx.service.notify({
          botId: 'expert',
          taskId: task.id,
          title: 'c',
          body: 'd',
          level: 'info',
        }).ok,
      ).toBe(true);
    }
    const otherTask = ctx.store.tasks.create({
      botId: 'expert',
      title: 'later',
      startedAt: new Date().toISOString(),
      origin: 'alert',
    });
    expect(
      ctx.service.notify({
        botId: 'expert',
        taskId: otherTask.id,
        title: 'e',
        body: 'f',
        level: 'info',
      }),
    ).toMatchObject({ ok: false, code: 'rate_limited' });
  });

  it('honours "important and above": info never calls the system notifier', async () => {
    const ctx = await setup();
    ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: '普通消息',
      body: '只进铃铛',
      level: 'info',
    });
    expect(ctx.calls).toHaveLength(0);
    ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: '重要消息',
      body: '可以弹',
      level: 'important',
    });
    expect(ctx.calls).toHaveLength(1);
  });

  it('validates title/body lengths and supports mark read', async () => {
    const ctx = await setup();
    expect(
      ctx.service.notify({
        botId: 'expert',
        taskId: ctx.proactive.id,
        title: 'x'.repeat(41),
        body: 'b',
        level: 'important',
      }),
    ).toMatchObject({ ok: false, code: 'invalid_arguments' });
    expect(
      ctx.service.notify({
        botId: 'expert',
        taskId: ctx.proactive.id,
        title: 't',
        body: 'x'.repeat(301),
        level: 'important',
      }),
    ).toMatchObject({ ok: false, code: 'invalid_arguments' });
    const result = ctx.service.notify({
      botId: 'expert',
      taskId: ctx.proactive.id,
      title: 't',
      body: 'b',
      level: 'info',
    });
    if (!result.ok) throw new Error('expected ok');
    const read = ctx.service.markRead(result.notification.id);
    expect(read?.readAt).not.toBeNull();
    expect(ctx.service.unreadCounts()['expert']).toBeUndefined();
  });
});
