import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

import type { AcpSpawnSpec } from '@chives/acp-client';

import type { ServerEvent } from '../src/api/protocol.js';
import { BotRegistry, type BotManifest } from '../src/bots/index.js';
import { EventBus } from '../src/events/index.js';
import { Orchestrator } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import { makeBot, waitFor } from './support.js';

const fakeAgentPath = fileURLToPath(
  new URL('../../../packages/acp-client/test/fake-agent.mjs', import.meta.url),
);

function spawnFor(scenario: string): AcpSpawnSpec {
  return {
    command: process.execPath,
    args: [fakeAgentPath],
    env: { ...process.env, FAKE_AGENT_SCENARIO: scenario },
  };
}

const cleanups: Array<() => Promise<void>> = [];

interface SetupOptions {
  approvalTimeoutMs?: number;
  bots?: BotManifest[];
}

async function setup(scenario: () => string, options: SetupOptions = {}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-harness-int-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: ServerEvent[] = [];
  bus.subscribe((event) => events.push(event));
  const bots = options.bots ?? [makeBot()];
  const registry = new BotRegistry(
    bots,
    new Map(bots.map((bot) => [bot.id, 'persona'])),
    'shared rules',
  );
  const orchestrator = new Orchestrator({
    registry,
    store,
    bus,
    ...(options.approvalTimeoutMs === undefined
      ? {}
      : { approvalTimeoutMs: options.approvalTimeoutMs }),
    driverOptions: {
      dataDir,
      dshHome: join(dataDir, 'dsh-home'),
      modelOverlay: join(dataDir, 'overlay.yml'),
      personaTextFor: () => 'persona',
      spawnSpecFor: () => spawnFor(scenario()),
      maxProcesses: 2,
      idleMs: 60_000,
    },
  });
  orchestrator.start();
  cleanups.push(async () => {
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, events, orchestrator, bots };
}

function requestedApprovalId(events: readonly ServerEvent[]): string {
  const requested = events.find((event) => event.type === 'approval.requested');
  if (requested === undefined || requested.type !== 'approval.requested') {
    throw new Error('no approval.requested event');
  }
  return requested.approvalId;
}

function statusOf(error: unknown): number | undefined {
  return typeof error === 'object' && error !== null && 'status' in error
    ? (error as { status?: number }).status
    : undefined;
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('orchestrator + DshDriver approvals', () => {
  it('allows a permission request and returns the allow option to the harness', async () => {
    const { store, events, orchestrator, bots } = await setup(() => 'permission');
    const botId = bots[0]?.id ?? 'test-bot';
    const accepted = await orchestrator.submitMessage(botId, '下单');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));

    expect(orchestrator.status(botId)).toBe('awaiting_approval');
    const approvalId = requestedApprovalId(events);
    const pending = store.approvals.listPending();
    expect(pending).toHaveLength(1);
    expect(pending[0]?.request).toMatchObject({
      toolCallId: 'tool-p',
      title: 'paper_place_order',
      botId,
      taskId: accepted.taskId,
    });

    const decided = orchestrator.decideApproval(approvalId, 'allow');
    expect(decided).toMatchObject({ decision: 'allow', decidedBy: 'user' });
    expect(store.approvals.get(approvalId)?.decision).toBe('allow');
    expect(() => orchestrator.decideApproval(approvalId, 'reject')).toThrowError(/already been decided/);

    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');
    const botMessage = store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.role === 'bot');
    expect(botMessage?.content).toBe('permission:allow-once');
    const tool = store.toolEvents
      .listByTask(accepted.taskId)
      .find((event) => event.toolCallId === 'tool-p');
    expect(tool?.status).toBe('completed');
    const approvalMessage = store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.kind === 'approval');
    expect(approvalMessage?.meta).toMatchObject({ decision: 'allow', approvalId });
    expect(events.some((event) => event.type === 'approval.decided')).toBe(true);
    await waitFor(() => orchestrator.status(botId) === 'idle');
  });

  it('rejects a permission request when the user rejects', async () => {
    const { store, events, orchestrator, bots } = await setup(() => 'permission');
    const botId = bots[0]?.id ?? 'test-bot';
    const accepted = await orchestrator.submitMessage(botId, '下单');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));
    const approvalId = requestedApprovalId(events);

    orchestrator.decideApproval(approvalId, 'reject');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');
    const botMessage = store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.role === 'bot');
    expect(botMessage?.content).toBe('permission:reject-once');
    const tool = store.toolEvents
      .listByTask(accepted.taskId)
      .find((event) => event.toolCallId === 'tool-p');
    expect(tool?.status).toBe('failed');
  });

  it('treats a timeout as a rejection and records decidedBy=timeout', async () => {
    const { store, events, orchestrator, bots } = await setup(() => 'permission', {
      approvalTimeoutMs: 100,
    });
    const botId = bots[0]?.id ?? 'test-bot';
    const accepted = await orchestrator.submitMessage(botId, '下单');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));
    const approvalId = requestedApprovalId(events);

    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done', 5000);
    const approval = store.approvals.get(approvalId);
    expect(approval).toMatchObject({ decision: 'reject', decidedBy: 'timeout' });
    const botMessage = store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.role === 'bot');
    expect(botMessage?.content).toBe('permission:reject-once');
  });

  it('cancels a pending approval when the task is cancelled', async () => {
    const { store, events, orchestrator, bots } = await setup(() => 'permission');
    const botId = bots[0]?.id ?? 'test-bot';
    const accepted = await orchestrator.submitMessage(botId, '下单');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));
    const approvalId = requestedApprovalId(events);

    orchestrator.cancel(botId);
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'cancelled');
    expect(store.approvals.get(approvalId)).toMatchObject({
      decision: 'cancelled',
      decidedBy: 'system',
    });
  });

  it('routes a delegated child approval to the root initiator', async () => {
    const parent = makeBot({ id: 'expert', name: '投资专家', can_delegate_to: ['data-prep'] });
    const child = makeBot({ id: 'data-prep', name: '数据员' });
    const { store, events, orchestrator } = await setup(() => 'permission', {
      bots: [parent, child],
    });
    const root = store.tasks.create({
      id: 'root-task',
      botId: parent.id,
      title: 'root',
      startedAt: new Date().toISOString(),
      depth: 0,
      delegated: false,
    });
    const childTask = store.tasks.create({
      botId: child.id,
      title: 'child',
      startedAt: new Date().toISOString(),
      parentTaskId: root.id,
      depth: 1,
      delegated: true,
      brief: 'buy',
    });
    orchestrator.startDelegatedTask(childTask, 'buy');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));

    const requested = events.find((event) => event.type === 'approval.requested');
    expect(requested).toMatchObject({
      botId: parent.id,
      taskId: root.id,
      approval: {
        delegated: true,
        sourceBotId: child.id,
        sourceBotName: '数据员',
        rootBotId: parent.id,
        rootTaskId: root.id,
      },
    });
    expect(orchestrator.pendingApprovalCounts()).toEqual({ [parent.id]: 1 });
    const approvalMessage = store.messages
      .listPage(parent.id, null, 50)
      .messages.find((message) => message.kind === 'approval');
    expect(approvalMessage?.meta).toMatchObject({
      delegated: true,
      sourceBotName: '数据员',
      rootTaskId: root.id,
    });

    const approvalId = requestedApprovalId(events);
    orchestrator.decideApproval(approvalId, 'allow');
    await waitFor(() => store.tasks.get(childTask.id)?.status === 'done');
    expect(orchestrator.pendingApprovalCounts()).toEqual({});
  });

  it('returns 410 for an approval whose task already ended', async () => {
    const { store, events, orchestrator, bots } = await setup(() => 'permission');
    const botId = bots[0]?.id ?? 'test-bot';
    const accepted = await orchestrator.submitMessage(botId, '下单');
    await waitFor(() => events.some((event) => event.type === 'approval.requested'));
    const approvalId = requestedApprovalId(events);
    orchestrator.decideApproval(approvalId, 'allow');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');

    try {
      orchestrator.decideApproval(approvalId, 'reject');
      throw new Error('expected a 410');
    } catch (error) {
      expect(statusOf(error)).toBe(410);
    }
  });

  it('fails the current task on a crash and restarts the process for the next message', async () => {
    let calls = 0;
    const { store, events, orchestrator, bots } = await setup(() => {
      calls += 1;
      return calls === 1 ? 'crash' : 'normal';
    });
    const botId = bots[0]?.id ?? 'test-bot';
    const first = await orchestrator.submitMessage(botId, 'first');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'failed');
    const firstMessages = store.messages.listByTask(first.taskId);
    const notices = firstMessages.filter((message) => message.kind === 'notice');
    expect(notices).toHaveLength(1);
    expect(notices[0]?.content).toContain('异常退出');
    expect(events.some((event) => event.type === 'error')).toBe(true);
    expect(orchestrator.status(botId)).toBe('idle');

    const second = await orchestrator.submitMessage(botId, 'second');
    expect(second.taskId).toBe(first.taskId);
    await waitFor(() => store.tasks.get(second.taskId)?.status === 'done');
    expect(store.messages.listByTask(second.taskId).some((message) => message.role === 'bot')).toBe(
      true,
    );
  });
});
