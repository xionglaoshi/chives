import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { DelegationResult, DelegationWaitResult } from '../src/delegations/index.js';
import type { BotManifest } from '../src/bots/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import type { HarnessDriver, HarnessPromptResult, HarnessSink } from '../src/harness/types.js';
import type { TaskRecord } from '../src/store/index.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

/** Routes a separate deterministic script to each bot so a child can fail alone. */
class BotScriptDriver implements HarnessDriver {
  private readonly drivers = new Map<string, FakeDriver>();

  constructor(private readonly scripts: Record<string, readonly FakeStep[]>) {}

  private forBot(bot: BotManifest): FakeDriver {
    let driver = this.drivers.get(bot.id);
    if (driver === undefined) {
      driver = new FakeDriver({ script: this.scripts[bot.id] ?? [{ type: 'message', text: 'ok' }] });
      this.drivers.set(bot.id, driver);
    }
    return driver;
  }

  ensureSession(bot: BotManifest, task: TaskRecord): Promise<string> {
    return this.forBot(bot).ensureSession(bot, task);
  }

  prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    return this.forBot(bot).prompt(bot, sessionId, text, sink);
  }

  cancel(bot: BotManifest, sessionId: string): void {
    this.forBot(bot).cancel(bot, sessionId);
  }

  async shutdown(): Promise<void> {
    for (const driver of this.drivers.values()) await driver.shutdown();
  }
}

interface Harness {
  app: ChivesApp;
  baseUrl: string;
  dataDir: string;
}

const harnesses: Harness[] = [];

async function startApp(
  options: {
    dataDir?: string;
    scripts?: Record<string, readonly FakeStep[]>;
    concurrency?: number;
  } = {},
): Promise<Harness> {
  const dataDir = options.dataDir ?? (await mkdtemp(join(tmpdir(), 'chives-del-')));
  const config = testConfig(dataDir);
  if (options.concurrency !== undefined) config.delegationConcurrency = options.concurrency;
  const driver = new BotScriptDriver(
    options.scripts ?? {
      expert: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'expert answer' }],
      'research': [{ type: 'delay', ms: 10 }, { type: 'message', text: 'dataset ready' }],
    },
  );
  const app = createApp({ config, driver });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl, dataDir };
  harnesses.push(harness);
  return harness;
}

async function stopApp(harness: Harness, remove: boolean, drain = true): Promise<void> {
  const index = harnesses.indexOf(harness);
  if (index >= 0) harnesses.splice(index, 1);
  if (drain) {
    await waitFor(() => harness.app.store.tasks.listRunning().length === 0, 3000).catch(() => undefined);
  }
  harness.app.sse.closeAll();
  await closeServer(harness.app.server);
  await harness.app.close();
  if (remove) await rm(harness.dataDir, { recursive: true, force: true });
}

afterEach(async () => {
  for (const harness of harnesses.splice(0)) await stopApp(harness, true);
});

async function internal(
  harness: Harness,
  path: string,
  token: string | undefined,
  body: unknown,
): Promise<{ status: number; body: unknown }> {
  const response = await fetch(`${harness.baseUrl}${path}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token === undefined ? {} : { authorization: `Bearer ${token}` }),
    },
    body: JSON.stringify(body),
  });
  return { status: response.status, body: (await response.json()) as unknown };
}

function tokenFor(harness: Harness, botId: string, taskId: string, depth = 0): string {
  return harness.app.sessions.issue({ botId, taskId, depth });
}

function asResult(body: unknown): DelegationResult {
  return body as DelegationResult;
}

function asWait(body: unknown): DelegationWaitResult[] {
  return body as DelegationWaitResult[];
}

describe('delegation API', () => {
  it('rejects missing and unknown session tokens with 401', async () => {
    const harness = await startApp();
    expect((await internal(harness, '/api/internal/delegations', undefined, { bot: 'research', brief: 'x' })).status).toBe(401);
    expect((await internal(harness, '/api/internal/delegations', 'nope', { bot: 'research', brief: 'x' })).status).toBe(401);
  });

  it('enforces whitelist, self, depth, busy and the wait cap', async () => {
    const harness = await startApp({
      concurrency: 1,
      scripts: {
        expert: [{ type: 'delay', ms: 500 }, { type: 'message', text: 'expert answer' }],
        'research': [{ type: 'delay', ms: 500 }, { type: 'message', text: 'dataset ready' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const task = accepted.taskId;
    const expertToken = tokenFor(harness, 'expert', task);
    await waitFor(() => harness.app.store.tasks.get(task) !== undefined);

    const self = await internal(harness, '/api/internal/delegations', expertToken, {
      bot: 'expert',
      brief: 'x',
      wait_seconds: 0,
    });
    expect(self.body).toMatchObject({ error: 'self_delegation' });

    const notAllowed = await internal(harness, '/api/internal/delegations', expertToken, {
      bot: 'report-builder',
      brief: 'x',
      wait_seconds: 0,
      report_back: false,
    });
    // report-builder is on expert's whitelist but its own can_delegate_to is empty.
    expect(asResult(notAllowed.body).status).toBe('running');

    const research = harness.app.store.tasks.create({
      botId: 'research',
      startedAt: new Date().toISOString(),
    });
    const researchToken = tokenFor(harness, 'research', research.id);
    const forbidden = await internal(harness, '/api/internal/delegations', researchToken, {
      bot: 'expert',
      brief: 'x',
      wait_seconds: 0,
    });
    expect(forbidden.body).toMatchObject({ error: 'forbidden' });

    const deep = harness.app.store.tasks.create({
      botId: 'equity-analyst',
      startedAt: new Date().toISOString(),
      depth: 2,
      delegated: true,
      parentTaskId: task,
    });
    const deepToken = tokenFor(harness, 'equity-analyst', deep.id, 2);
    const depthExceeded = await internal(harness, '/api/internal/delegations', deepToken, {
      bot: 'research',
      brief: 'x',
      wait_seconds: 0,
    });
    expect(depthExceeded.body).toMatchObject({ error: 'depth_exceeded' });

    const first = await internal(harness, '/api/internal/delegations', expertToken, {
      bot: 'research',
      brief: '第一批',
      wait_seconds: 0,
      report_back: false,
    });
    expect(asResult(first.body).status).toBe('running');
    const second = await internal(harness, '/api/internal/delegations', expertToken, {
      bot: 'research',
      brief: '第二批',
      wait_seconds: 0,
    });
    expect(second.body).toMatchObject({ error: 'busy' });

    harness.app.store.tasks.finish(research.id, 'cancelled', new Date().toISOString());
    harness.app.store.tasks.finish(deep.id, 'cancelled', new Date().toISOString());
    await waitFor(() => harness.app.store.tasks.get(task)?.status === 'done');
  });

  it('runs the end-to-end flow: delegate -> child done -> initiator timeline row is done', async () => {
    const harness = await startApp({
      scripts: {
        expert: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'expert answer' }],
        'research': [
          { type: 'tool_start', toolCallId: 'child-tool-1', title: 'company_financials' },
          { type: 'tool_end', toolCallId: 'child-tool-1', output: 'ok' },
          { type: 'delay', ms: 10 },
          { type: 'message', text: 'dataset ready' },
        ],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '分析茅台');
    const parentTaskId = accepted.taskId;
    const token = tokenFor(harness, 'expert', parentTaskId);

    const started = await internal(harness, '/api/internal/delegations', token, {
      bot: 'research',
      brief: '取三表并落盘',
      wait_seconds: 0,
      report_back: false,
    });
    const child = asResult(started.body);
    expect(child.status).toBe('running');
    expect(child.bot).toBe('research');

    const waited = await internal(harness, '/api/internal/delegations/wait', token, {
      ids: [child.id],
      mode: 'all',
      wait_seconds: 5,
    });
    expect(asWait(waited.body)[0]).toMatchObject({
      id: child.id,
      bot: 'research',
      status: 'done',
      result: 'dataset ready',
    });

    await waitFor(() => {
      const messages = harness.app.store.messages.listByTask(parentTaskId);
      const row = messages.find((message) => message.kind === 'delegation');
      return row?.meta?.status === 'done';
    });

    const row = harness.app.store.messages
      .listByTask(parentTaskId)
      .find((message) => message.kind === 'delegation');
    expect(row?.meta).toMatchObject({
      targetBotId: 'research',
      childTaskId: child.id,
      brief: '取三表并落盘',
      status: 'done',
    });

    // The child ran under research but must not appear in its timeline.
    const targetTimeline = await fetch(`${harness.baseUrl}/api/bots/research/timeline`);
    const targetPage = (await targetTimeline.json()) as {
      messages: Array<{ taskId: string | null }>;
      tasks: Array<{ id: string }>;
    };
    expect(targetPage.messages).toHaveLength(0);
    expect(targetPage.tasks).toHaveLength(0);
    expect((targetPage as { toolEvents?: unknown[] }).toolEvents).toHaveLength(0);

    // GET /api/tasks/:id exposes the child's tools and final message for expansion.
    const detailResponse = await fetch(`${harness.baseUrl}/api/tasks/${child.id}`);
    const detail = (await detailResponse.json()) as {
      task: { delegated: boolean; depth: number; parentTaskId: string };
      messages: Array<{ role: string; content: string }>;
      toolEvents: unknown[];
    };
    expect(detail.task).toMatchObject({ delegated: true, depth: 1, parentTaskId });
    expect(detail.messages.some((message) => message.role === 'bot' && message.content === 'dataset ready')).toBe(true);
    expect(detail.toolEvents).toHaveLength(1);

    await waitFor(() => harness.app.store.tasks.get(parentTaskId)?.status === 'done');
  });

  it('passes a child failure detail back as the tool error', async () => {
    const harness = await startApp({
      scripts: {
        expert: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'expert' }],
        'research': [{ type: 'fail', message: 'upstream 500' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const token = tokenFor(harness, 'expert', accepted.taskId);
    const response = await internal(harness, '/api/internal/delegations', token, {
      bot: 'research',
      brief: '会失败',
      wait_seconds: 5,
      report_back: false,
    });
    expect(asResult(response.body)).toMatchObject({
      bot: 'research',
      status: 'failed',
    });
    expect(asResult(response.body).error).toContain('upstream 500');
    await waitFor(() => harness.app.store.tasks.get(accepted.taskId)?.status === 'done');
  });

  it('cancels running children when the initiator task is cancelled', async () => {
    const harness = await startApp({
      scripts: {
        expert: [{ type: 'delay', ms: 300 }, { type: 'message', text: 'expert' }],
        'research': [{ type: 'delay', ms: 300 }, { type: 'message', text: 'late' }],
      },
    });
    const accepted = await harness.app.orchestrator.submitMessage('expert', '父任务');
    const token = tokenFor(harness, 'expert', accepted.taskId);
    const started = await internal(harness, '/api/internal/delegations', token, {
      bot: 'research',
      brief: '慢任务',
      wait_seconds: 0,
      report_back: false,
    });
    const child = asResult(started.body);
    harness.app.orchestrator.cancel('expert');

    await waitFor(() => harness.app.store.tasks.get(child.id)?.status === 'cancelled', 5000);
    await waitFor(() => harness.app.store.tasks.get(accepted.taskId)?.status === 'cancelled', 5000);
    const row = harness.app.store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.kind === 'delegation');
    expect(row?.meta?.status).toBe('cancelled');
  });

  it('marks in-flight delegations interrupted after a restart', async () => {
    const first = await startApp();
    const parent = first.app.store.tasks.create({
      botId: 'expert',
      startedAt: new Date().toISOString(),
    });
    const child = first.app.store.tasks.create({
      botId: 'research',
      startedAt: new Date().toISOString(),
      parentTaskId: parent.id,
      depth: 1,
      delegated: true,
      brief: '重启时还没完成',
    });
    first.app.store.messages.append({
      id: 'delegation-message',
      botId: 'expert',
      taskId: parent.id,
      role: 'bot',
      kind: 'delegation',
      content: '委派给 研究员：重启时还没完成',
      meta: {
        delegationId: 'delegation-1',
        parentTaskId: parent.id,
        targetBotId: 'research',
        targetBotName: '研究员',
        childTaskId: child.id,
        brief: '重启时还没完成',
        status: 'running',
        startedAt: new Date().toISOString(),
        endedAt: null,
        error: null,
      },
      createdAt: new Date().toISOString(),
    });
    await stopApp(first, false, false);

    const second = await startApp({ dataDir: first.dataDir });
    expect(second.app.store.tasks.get(child.id)?.status).toBe('interrupted');
    const row = second.app.store.messages.get('delegation-message');
    expect(row?.meta?.status).toBe('interrupted');
  });
});
