import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { Store, currentVersion } from '../src/store/index.js';

const directories: string[] = [];

async function tempDir(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-store-'));
  directories.push(directory);
  return directory;
}

afterEach(async () => {
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

describe('store', () => {
  it('applies migrations idempotently and enables WAL/foreign keys', async () => {
    const directory = await tempDir();
    const first = Store.open(directory);
    expect(currentVersion(first.db)).toBe(10);
    first.close();

    const second = Store.open(directory);
    expect(currentVersion(second.db)).toBe(10);
    const journal = second.db.prepare('PRAGMA journal_mode').get() as { journal_mode: string };
    const foreignKeys = second.db.prepare('PRAGMA foreign_keys').get() as { foreign_keys: number };
    expect(journal.journal_mode).toBe('wal');
    expect(foreignKeys.foreign_keys).toBe(1);
    second.close();
  });

  it('keeps seq monotonic per bot and pages backwards in ascending order', async () => {
    const directory = await tempDir();
    const store = Store.open(directory);
    const task = store.tasks.create({ botId: 'expert', title: 't', startedAt: new Date().toISOString() });
    for (let index = 0; index < 12; index += 1) {
      store.messages.append({
        id: `m-${index}`,
        botId: 'expert',
        taskId: task.id,
        role: index % 2 === 0 ? 'user' : 'bot',
        kind: 'text',
        content: `message ${index}`,
        createdAt: new Date(Date.now() + index).toISOString(),
      });
    }
    store.messages.append({
      id: 'other-1',
      botId: 'research',
      taskId: null,
      role: 'user',
      kind: 'text',
      content: 'other bot',
      createdAt: new Date().toISOString(),
    });

    expect(store.messages.get('m-0')?.seq).toBe(1);
    expect(store.messages.get('other-1')?.seq).toBe(1);

    const firstPage = store.messages.listPage('expert', null, 5);
    expect(firstPage.messages.map((message) => message.seq)).toEqual([8, 9, 10, 11, 12]);
    expect(firstPage.hasMore).toBe(true);
    expect(firstPage.nextBeforeSeq).toBe(8);

    const secondPage = store.messages.listPage('expert', firstPage.nextBeforeSeq, 5);
    expect(secondPage.messages.map((message) => message.seq)).toEqual([3, 4, 5, 6, 7]);
    expect(secondPage.hasMore).toBe(true);

    const thirdPage = store.messages.listPage('expert', secondPage.nextBeforeSeq, 5);
    expect(thirdPage.messages.map((message) => message.seq)).toEqual([1, 2]);
    expect(thirdPage.hasMore).toBe(false);
    expect(thirdPage.nextBeforeSeq).toBeNull();
    store.close();
  });

  it('records tasks, tool events, usage, overrides, and settings', async () => {
    const directory = await tempDir();
    const store = Store.open(directory);
    const startedAt = new Date('2026-11-16T01:00:00.000Z');
    const task = store.tasks.create({ botId: 'expert', startedAt: startedAt.toISOString() });
    expect(store.tasks.findRunning('expert')?.id).toBe(task.id);

    const tool = store.toolEvents.start({
      id: 'tool-1',
      taskId: task.id,
      toolCallId: 'call-1',
      title: 'Quote',
      kind: 'read',
      rawInput: { symbol: '600519.SH' },
      startedAt: startedAt.toISOString(),
    });
    expect(tool.status).toBe('running');
    const ended = store.toolEvents.finish(
      task.id,
      'call-1',
      'completed',
      'ok',
      new Date('2026-11-16T01:00:01.000Z').toISOString(),
    );
    expect(ended?.status).toBe('completed');
    expect(ended?.output).toBe('ok');
    expect(store.toolEvents.finish(task.id, 'missing', 'failed', '', startedAt.toISOString())).toBeUndefined();

    store.usage.add(task.id, 100, 1000, startedAt);
    expect(store.usage.latestForTask(task.id)?.used).toBe(100);

    const finished = store.tasks.finish(task.id, 'done', new Date('2026-11-16T01:01:00.000Z').toISOString());
    expect(finished.status).toBe('done');
    expect(store.tasks.findRunning('expert')).toBeUndefined();
    expect(store.tasks.latestForBot('expert')?.id).toBe(task.id);

    const first = store.bots.upsert('expert', { displayName: '老师' }, startedAt);
    expect(first.displayName).toBe('老师');
    const second = store.bots.upsert('expert', { avatarEmblem: 'lens' }, startedAt);
    expect(second.displayName).toBe('老师');
    expect(second.avatarEmblem).toBe('lens');

    store.settings.set('theme', { dark: true });
    expect(store.settings.get('theme')).toEqual({ dark: true });
    expect(store.settings.list()).toEqual({ theme: { dark: true } });
    store.close();
  });

  it('interrupts running tasks with a terminal status', async () => {
    const directory = await tempDir();
    const store = Store.open(directory);
    const first = store.tasks.create({ botId: 'expert', startedAt: new Date().toISOString() });
    store.tasks.create({ botId: 'research', startedAt: new Date().toISOString() });
    const interrupted = store.tasks.interruptRunning(new Date().toISOString());
    expect(interrupted.map((task) => task.botId).sort()).toEqual(['expert', 'research']);
    expect(store.tasks.get(first.id)?.status).toBe('interrupted');
    expect(store.tasks.listRunning()).toEqual([]);
    store.close();
  });
});
