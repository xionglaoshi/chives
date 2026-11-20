import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import type { ServerEvent } from '../src/api/protocol.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import { Orchestrator, chooseTask } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import { makeRegistry, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

async function setup(script: readonly FakeStep[] = [], delayMs = 2) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-orch-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: ServerEvent[] = [];
  bus.subscribe((event) => events.push(event));
  const driver = new FakeDriver({ script, delayMs });
  const orchestrator = new Orchestrator({
    registry: makeRegistry(),
    store,
    bus,
    driver,
  });
  orchestrator.start();
  let closed = false;
  cleanups.push(async () => {
    if (closed) return;
    closed = true;
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, events, orchestrator, dataDir };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('chooseTask', () => {
  const now = new Date('2026-11-16T02:00:00.000Z');
  const base = {
    id: 't1',
    botId: 'expert',
    title: null,
    harnessSessionId: 's1',
    startedAt: '2026-11-16T01:00:00.000Z',
    parentTaskId: null,
  };

  it('continues a finished task inside 30 minutes and starts a new one otherwise', () => {
    expect(chooseTask(undefined, now).kind).toBe('new');
    expect(
      chooseTask(
        { ...base, status: 'done', endedAt: '2026-11-16T01:40:00.000Z' },
        now,
      ).kind,
    ).toBe('continue');
    expect(
      chooseTask(
        { ...base, status: 'done', endedAt: '2026-11-16T01:30:00.000Z' },
        now,
      ).kind,
    ).toBe('new');
    expect(
      chooseTask(
        { ...base, status: 'failed', endedAt: '2026-11-16T01:59:00.000Z' },
        now,
      ).kind,
    ).toBe('new');
    expect(chooseTask({ ...base, status: 'done', endedAt: null }, now).kind).toBe('new');
  });
});

describe('Orchestrator', () => {
  it('persists a full turn and publishes the expected SSE events', async () => {
    const { store, events, orchestrator } = await setup([
      { type: 'draft_reset', attemptId: 'attempt-1' },
      { type: 'draft_delta', text: '思考中', attemptId: 'attempt-1' },
      { type: 'draft_commit', text: '最终' },
      {
        type: 'tool_start',
        toolCallId: 'tool-1',
        title: 'Quote',
        kind: 'read',
        rawInput: { symbol: '600519.SH' },
      },
      { type: 'tool_end', toolCallId: 'tool-1', output: 'ok' },
      { type: 'message', text: '回答：{text}' },
      { type: 'usage', used: 500, size: 1000 },
    ]);
    const accepted = await orchestrator.submitMessage('expert', '看看茅台');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');

    const messages = store.messages.listByTask(accepted.taskId);
    expect(messages.map((message) => message.role)).toEqual(['user', 'bot']);
    expect(messages[1]?.content).toContain('看看茅台');
    expect(messages[1]?.content).toContain('[Chives 上下文');
    expect(store.toolEvents.listByTask(accepted.taskId)).toHaveLength(1);
    expect(store.usage.listByTask(accepted.taskId)).toHaveLength(1);
    expect(orchestrator.status('expert')).toBe('idle');

    const types = events.map((event) => event.type);
    expect(types).toContain('task.started');
    expect(types).toContain('draft.reset');
    expect(types).toContain('draft.delta');
    expect(types).toContain('draft.commit');
    expect(types).toContain('tool.started');
    expect(types).toContain('tool.ended');
    expect(types).toContain('usage');
    expect(types.filter((type) => type === 'message.created')).toHaveLength(2);
    expect(types[types.length - 1]).toBe('bot.status');
    expect(events.filter((event) => event.type === 'task.updated').at(-1)).toMatchObject({
      type: 'task.updated',
      task: { status: 'done' },
    });
  });

  it('rejects a second message while the bot is busy', async () => {
    const { store, orchestrator } = await setup([{ type: 'delay', ms: 100 }]);
    const accepted = await orchestrator.submitMessage('expert', 'first');
    await expect(orchestrator.submitMessage('expert', 'second')).rejects.toThrowError(
      /already has a running task/,
    );
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');
    expect(store.tasks.get(accepted.taskId)?.status).toBe('done');
  });

  it('continues the previous task within the window and reuses its harness session', async () => {
    const { store, orchestrator } = await setup([{ type: 'message', text: 'ok' }]);
    const first = await orchestrator.submitMessage('expert', 'one');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');
    const session = store.tasks.get(first.taskId)?.harnessSessionId;
    expect(session).not.toBeNull();
    const second = await orchestrator.submitMessage('expert', 'two');
    expect(second.taskId).toBe(first.taskId);
    await waitFor(() => store.messages.countForBot('expert') === 4);
    expect(store.tasks.get(first.taskId)?.status).toBe('done');
    expect(store.messages.countForBot('expert')).toBe(4);
  });

  it('cancels the running task', async () => {
    const { store, orchestrator, events } = await setup([
      { type: 'delay', ms: 200 },
      { type: 'message', text: 'late' },
    ]);
    const accepted = await orchestrator.submitMessage('expert', 'stop me');
    const cancelled = orchestrator.cancel('expert');
    expect(cancelled.taskId).toBe(accepted.taskId);
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'cancelled');
    expect(orchestrator.status('expert')).toBe('idle');
    expect(events.filter((event) => event.type === 'message.created')).toHaveLength(1);
  });

  it('marks a failed turn, stores a notice, and publishes an error event', async () => {
    const { store, orchestrator, events } = await setup([
      { type: 'tool_start', toolCallId: 'tool-x', title: 'Broken' },
      { type: 'fail', message: 'harness exploded' },
    ]);
    const accepted = await orchestrator.submitMessage('expert', 'fail please');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'failed');
    const messages = store.messages.listByTask(accepted.taskId);
    expect(messages.some((message) => message.kind === 'notice')).toBe(true);
    const error = events.find((event) => event.type === 'error');
    expect(error).toMatchObject({ type: 'error', code: 'unknown' });
    expect(orchestrator.status('expert')).toBe('idle');
  });

  it('interrupts running tasks on start and writes one notice', async () => {
    const { store } = await setup([]);
    const task = store.tasks.create({ botId: 'research', startedAt: new Date().toISOString() });
    const bus = new EventBus();
    const orchestrator = new Orchestrator({
      registry: makeRegistry(),
      store,
      bus,
      driver: new FakeDriver(),
    });
    orchestrator.start();
    expect(store.tasks.get(task.id)?.status).toBe('interrupted');
    const messages = store.messages.listByTask(task.id);
    expect(messages).toHaveLength(1);
    expect(messages[0]?.kind).toBe('notice');
    await orchestrator.close();
  });

  it('refuses unknown bots and missing running tasks', async () => {
    const { orchestrator } = await setup([]);
    await expect(orchestrator.submitMessage('nope', 'hi')).rejects.toThrowError(/unknown bot/);
    expect(() => orchestrator.cancel('expert')).toThrowError(/no running task/);
  });
});

