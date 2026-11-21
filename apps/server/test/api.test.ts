import { request as httpRequest } from 'node:http';
import { access, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { ApprovalDto, MessageAccepted, ServerEvent, TimelinePage } from '../src/api/protocol.js';
import { DshDriver } from '../src/harness/dsh-driver.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

interface Harness {
  app: ChivesApp;
  baseUrl: string;
  port: number;
}

const harnesses: Harness[] = [];
const directories: string[] = [];

async function startApp(
  dataDir?: string,
  driver = new FakeDriver(),
  engineHealth?: (port: number) => Promise<boolean>,
): Promise<Harness> {
  const directory = dataDir ?? (await mkdtemp(join(tmpdir(), 'chives-api-')));
  if (dataDir === undefined) directories.push(directory);
  const app = createApp({
    config: testConfig(directory),
    driver,
    ...(engineHealth === undefined ? {} : { engineHealth }),
  });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl, port: Number(new URL(baseUrl).port) };
  harnesses.push(harness);
  return harness;
}

async function stopApp(harness: Harness): Promise<void> {
  const index = harnesses.indexOf(harness);
  if (index >= 0) harnesses.splice(index, 1);
  harness.app.sse.closeAll();
  await closeServer(harness.app.server);
  await harness.app.close();
}

afterEach(async () => {
  for (const harness of harnesses.splice(0)) await stopApp(harness);
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

interface OpenSse {
  events: ServerEvent[];
  close: () => void;
}

async function openSse(url: string): Promise<OpenSse> {
  const controller = new AbortController();
  const response = await fetch(url, { signal: controller.signal });
  const events: ServerEvent[] = [];
  const reader = response.body?.getReader();
  if (reader !== undefined) {
    const decoder = new TextDecoder();
    void (async () => {
      let buffer = '';
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) return;
          buffer += decoder.decode(value, { stream: true });
          let boundary = buffer.indexOf('\n\n');
          while (boundary >= 0) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const data = block
              .split('\n')
              .filter((line) => line.startsWith('data: '))
              .map((line) => line.slice(6))
              .join('\n');
            if (data !== '') events.push(JSON.parse(data) as ServerEvent);
            boundary = buffer.indexOf('\n\n');
          }
        }
      } catch {
        // aborted by the test
      }
    })();
  }
  return { events, close: () => controller.abort() };
}

function rawGet(port: number, path: string, host: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const request = httpRequest(
      { host: '127.0.0.1', port, path, method: 'GET', headers: { host } },
      (response) => {
        let body = '';
        response.setEncoding('utf8');
        response.on('data', (chunk: string) => {
          body += chunk;
        });
        response.on('end', () => {
          resolve({ status: response.statusCode ?? 0, body });
        });
      },
    );
    request.on('error', reject);
    request.end();
  });
}

it('keeps an old installation from starting with an empty database', async () => {
  const root = await mkdtemp(join(tmpdir(), 'chives-legacy-data-'));
  directories.push(root);
  const legacy = join(root, '.chives');
  const dataDir = join(root, 'data');
  await mkdir(legacy);
  await writeFile(join(legacy, 'chives.sqlite'), '');
  expect(() => createApp({ config: { ...testConfig(dataDir), repoRoot: root } }))
    .toThrow('检测到旧版数据库');
  await expect(access(dataDir)).rejects.toMatchObject({ code: 'ENOENT' });
});

describe('HTTP API', () => {
  it('serves health, bots, timeline, and task detail', async () => {
    const { baseUrl } = await startApp();
    const health = await fetch(`${baseUrl}/api/health`);
    expect(health.status).toBe(200);
    await expect(health.json()).resolves.toEqual({ ok: true });

    const bots = (await (await fetch(`${baseUrl}/api/bots`)).json()) as Array<{
      id: string;
      status: string;
    }>;
    expect(bots).toHaveLength(5);
    expect(bots.find((bot) => bot.id === 'expert')?.status).toBe('idle');

    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 'hello' }),
      })
    ).json()) as MessageAccepted;
    expect(accepted.taskId).toBeTruthy();

    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      const page = (await (await fetch(`${baseUrl}/api/bots/expert/timeline`)).json()) as TimelinePage;
      if (page.messages.some((message) => message.role === 'bot')) break;
      await new Promise((resolve) => {
        setTimeout(resolve, 10);
      });
    }
    const page = (await (await fetch(`${baseUrl}/api/bots/expert/timeline`)).json()) as TimelinePage;
    expect(page.messages.map((message) => message.role)).toEqual(['user', 'bot']);
    expect(page.tasks[0]?.status).toBe('done');
    expect(page.toolEvents).toHaveLength(1);
    expect(page.hasMore).toBe(false);

    const detail = (await (
      await fetch(`${baseUrl}/api/tasks/${accepted.taskId}`)
    ).json()) as { task: { status: string }; usage: unknown[]; toolEvents: unknown[] };
    expect(detail.task.status).toBe('done');
    expect(detail.usage).toHaveLength(1);
    expect(detail.toolEvents).toHaveLength(1);
  });

  it('keeps the execution route on the task and out of conversation messages', async () => {
    const { app, baseUrl } = await startApp();
    const response = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: 'hello' })
    });
    const { taskId } = await response.json() as MessageAccepted;
    await waitFor(() => app.store.tasks.get(taskId)?.status === 'done');
    expect(app.store.tasks.get(taskId)?.contextMeta?.execution).toEqual(
      expect.objectContaining({kernel: expect.any(String), model: expect.any(String)}));
    expect(app.store.messages.listByTask(taskId).map(message => message.role)).toEqual(['user','bot']);
  });

  it('rejects non-loopback Host headers', async () => {
    const { port } = await startApp();
    const rejected = await rawGet(port, '/api/health', 'evil.com');
    expect(rejected.status).toBe(403);
    expect(JSON.parse(rejected.body)).toEqual({
      error: { code: 'host_not_allowed', message: expect.any(String) },
    });
    const accepted = await rawGet(port, '/api/health', `127.0.0.1:${port}`);
    expect(accepted.status).toBe(200);
    const localhost = await rawGet(port, '/api/health', `localhost:${port}`);
    expect(localhost.status).toBe(200);
  });

  it('validates timeline parameters and message bodies', async () => {
    const { baseUrl } = await startApp();
    expect((await fetch(`${baseUrl}/api/bots/nope/timeline`)).status).toBe(404);
    expect((await fetch(`${baseUrl}/api/bots/expert/timeline?limit=500`)).status).toBe(400);
    expect((await fetch(`${baseUrl}/api/bots/expert/timeline?limit=0`)).status).toBe(400);
    expect((await fetch(`${baseUrl}/api/bots/expert/timeline?beforeSeq=x`)).status).toBe(400);

    const empty = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '   ' }),
    });
    expect(empty.status).toBe(400);
    expect(((await empty.json()) as { error: { code: string } }).error.code).toBe('validation_error');

    const invalid = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{',
    });
    expect(invalid.status).toBe(400);

    const unknown = await fetch(`${baseUrl}/api/bots/nope/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: 'hi' }),
    });
    expect(unknown.status).toBe(404);

    expect((await fetch(`${baseUrl}/api/bots/expert/cancel`, { method: 'POST' })).status).toBe(409);
    expect((await fetch(`${baseUrl}/api/tasks/nope`)).status).toBe(404);
    expect((await fetch(`${baseUrl}/api/bots/expert/messages`)).status).toBe(405);
  });

  it('returns 413 for bodies over 1 MB', async () => {
    const { baseUrl } = await startApp();
    const response = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: 'x'.repeat(1024 * 1024 + 32) }),
    });
    expect(response.status).toBe(413);
    const body = (await response.json()) as { error: { code: string } };
    expect(body.error.code).toBe('payload_too_large');
  });

  it.each(['queue','interrupt'])('schedules a follow-up while busy with %s policy',async mode=>{
    const {app,baseUrl}=await startApp(undefined,new FakeDriver({script:[{type:'delay',ms:220}]}));
    const endpoint=baseUrl+'/api/settings/desk/prefs';
    expect((await fetch(endpoint)).status).toBe(403);
    const local={'content-type':'application/json','X-Chives-Kernel-Manager':'local'};
    expect((await fetch(endpoint,{method:'PATCH',headers:local,body:JSON.stringify({busyMode:mode})})).status).toBe(200);
    const send=(text:string)=>fetch(baseUrl+'/api/bots/expert/messages',{method:'POST',headers:local,body:JSON.stringify({text,deferIfBusy:true})});
    expect((await send('first')).status).toBe(202);
    const follow=await (await send('follow')).json();
    expect(follow.queued).toBe(true);
    await waitFor(()=>app.store.messages.get(follow.messageId)?.content==='follow');
    expect(app.store.messages.listAll().filter(m=>m.content==='follow')).toHaveLength(1);
  });
  it('conflicts when the bot already has a running task', async () => {
    const { app, baseUrl } = await startApp(
      undefined,
      new FakeDriver({ script: [{ type: 'delay', ms: 120 }] }),
    );
    const first = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: 'one' }),
    });
    expect(first.status).toBe(202);
    const accepted = (await first.json()) as MessageAccepted;
    const second = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: 'two' }),
    });
    expect(second.status).toBe(409);
    const body = (await second.json()) as { error: { code: string } };
    expect(body.error.code).toBe('bot_busy');
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
  });
});

describe('approvals API', () => {
  async function seedPendingApproval(app: ChivesApp): Promise<{ taskId: string; approvalId: string }> {
    const task = app.store.tasks.create({
      botId: 'expert',
      title: 'approval task',
      startedAt: new Date().toISOString(),
      depth: 0,
      delegated: false,
    });
    const approvalId = 'approval-api-1';
    app.store.approvals.add({
      id: approvalId,
      taskId: task.id,
      toolCallId: 'tool-p',
      request: {
        toolCallId: 'tool-p',
        title: 'paper_place_order',
        rawInput: { symbol: '600519.SH', side: 'buy', qty: 100 },
        options: [
          { optionId: 'allow-once', name: 'Allow once', kind: 'allow_once' },
          { optionId: 'reject-once', name: 'Reject', kind: 'reject_once' },
        ],
        botId: 'expert',
        taskId: task.id,
      },
      decision: null,
      decidedAt: null,
      decidedBy: null,
    });
    app.store.messages.append({
      id: 'approval-api-message-1',
      botId: 'expert',
      taskId: task.id,
      role: 'system',
      kind: 'approval',
      content: '需要你批准：paper_place_order',
      meta: {
        approvalId,
        title: 'paper_place_order',
        rawInput: { symbol: '600519.SH', side: 'buy', qty: 100 },
        sourceBotId: 'expert',
        sourceBotName: '投资专家',
        rootTaskId: task.id,
        rootBotId: 'expert',
        delegated: false,
        decision: null,
        decidedAt: null,
        decidedBy: null,
      },
      createdAt: new Date().toISOString(),
    });
    return { taskId: task.id, approvalId };
  }

  it('lists pending approvals, counts them per bot, and decides once', async () => {
    const harness = await startApp();
    const { taskId, approvalId } = await seedPendingApproval(harness.app);

    const pending = (await (
      await fetch(`${harness.baseUrl}/api/approvals?status=pending`)
    ).json()) as ApprovalDto[];
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({
      id: approvalId,
      taskId,
      title: 'paper_place_order',
      decision: null,
      rootBotId: 'expert',
    });

    const bots = (await (await fetch(`${harness.baseUrl}/api/bots`)).json()) as Array<{
      id: string;
      pendingApprovals: number;
    }>;
    expect(bots.find((bot) => bot.id === 'expert')?.pendingApprovals).toBe(1);

    const allowResponse = await fetch(`${harness.baseUrl}/api/approvals/${approvalId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'allow' }),
    });
    expect(allowResponse.status).toBe(200);
    const decided = (await allowResponse.json()) as ApprovalDto;
    expect(decided).toMatchObject({ decision: 'allow', decidedBy: 'user' });
    expect(harness.app.store.approvals.get(approvalId)?.decision).toBe('allow');
    const message = harness.app.store.messages
      .listByTask(taskId)
      .find((entry) => entry.kind === 'approval');
    expect(message?.meta).toMatchObject({ decision: 'allow' });

    const duplicate = await fetch(`${harness.baseUrl}/api/approvals/${approvalId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'reject' }),
    });
    expect(duplicate.status).toBe(409);

    harness.app.store.tasks.finish(taskId, 'done', new Date().toISOString());
    const ended = await fetch(`${harness.baseUrl}/api/approvals/${approvalId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'reject' }),
    });
    expect(ended.status).toBe(410);

    const empty = (await (
      await fetch(`${harness.baseUrl}/api/approvals?status=pending`)
    ).json()) as ApprovalDto[];
    expect(empty).toHaveLength(0);
  });

  it('validates approval decisions', async () => {
    const harness = await startApp();
    const { approvalId } = await seedPendingApproval(harness.app);
    const invalid = await fetch(`${harness.baseUrl}/api/approvals/${approvalId}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'maybe' }),
    });
    expect(invalid.status).toBe(400);
    const missing = await fetch(`${harness.baseUrl}/api/approvals/nope`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'allow' }),
    });
    expect(missing.status).toBe(404);
  });
});

describe('approval end to end over HTTP', () => {
  it('allows a fake agent permission request through POST /api/approvals/:id', async () => {
    const fakeAgentPath = fileURLToPath(
      new URL('../../../packages/acp-client/test/fake-agent.mjs', import.meta.url),
    );
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-approval-e2e-'));
    directories.push(dataDir);

    const appRef: { app?: ChivesApp } = {};
    const driver = new DshDriver({
      dataDir,
      dshHome: join(dataDir, 'dsh-home'),
      modelOverlay: join(dataDir, 'overlay.yml'),
      personaTextFor: () => 'persona',
      approvalTimeoutMs: 5000,
      maxProcesses: 2,
      idleMs: 60_000,
      spawnSpecFor: () => ({
        command: process.execPath,
        args: [fakeAgentPath],
        env: { ...process.env, FAKE_AGENT_SCENARIO: 'permission' },
      }),
      onPermission: (bot, request, task) =>
        appRef.app!.orchestrator.handlePermissionRequest(bot, request, task),
    });
    const app = createApp({ config: testConfig(dataDir), driver });
    appRef.app = app;
    const baseUrl = await listen(app.server);
    harnesses.push({ app, baseUrl, port: Number(new URL(baseUrl).port) });

    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '下单一手茅台' }),
      })
    ).json()) as MessageAccepted;

    await waitFor(() => app.store.approvals.listPending().length === 1);
    const pending = app.store.approvals.listPending()[0];
    expect(pending).toBeDefined();
    const decisions = (await (
      await fetch(`${baseUrl}/api/approvals?status=pending`)
    ).json()) as ApprovalDto[];
    expect(decisions.map((entry) => entry.id)).toEqual([pending?.id]);

    const response = await fetch(`${baseUrl}/api/approvals/${pending?.id}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ decision: 'allow' }),
    });
    expect(response.status).toBe(200);
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    const botMessage = app.store.messages
      .listByTask(accepted.taskId)
      .find((message) => message.role === 'bot');
    expect(botMessage?.content).toBe('permission:allow-once');
    const tool = app.store.toolEvents
      .listByTask(accepted.taskId)
      .find((event) => event.toolCallId === 'tool-p');
    expect(tool?.status).toBe('completed');
  });
});

describe('fake harness end to end', () => {
  it('streams a turn over SSE and keeps the timeline after restart', async () => {
    const first = await startApp();
    const client = await openSse(`${first.baseUrl}/api/events`);
    const accepted = (await (
      await fetch(`${first.baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '茅台怎么样' }),
      })
    ).json()) as MessageAccepted;

    await waitFor(() => {
      const done = client.events.some(
        (event) =>
          event.type === 'task.updated' &&
          event.taskId === accepted.taskId &&
          event.task.status === 'done',
      );
      const failed = client.events.some(
        (event) => event.type === 'task.updated' && event.task.status === 'failed',
      );
      return done || failed;
    });

    const types = client.events.map((event) => event.type);
    expect(types).toContain('task.started');
    expect(types).toContain('draft.delta');
    expect(types).toContain('tool.started');
    expect(types).toContain('tool.ended');
    expect(types).toContain('usage');
    const botMessageIndex = client.events.findIndex(
      (event) => event.type === 'message.created' && event.message.role === 'bot',
    );
    const taskDoneIndex = client.events.findIndex(
      (event) => event.type === 'task.updated' && event.task.status === 'done',
    );
    expect(botMessageIndex).toBeGreaterThan(-1);
    expect(taskDoneIndex).toBeGreaterThan(botMessageIndex);
    expect(client.events.filter((event) => event.type === 'task.updated').at(-1)).toMatchObject({
      task: { status: 'done' },
    });
    client.close();

    const before = (await (
      await fetch(`${first.baseUrl}/api/bots/expert/timeline`)
    ).json()) as TimelinePage;
    expect(before.messages.map((message) => message.role)).toEqual(['user', 'bot']);
    await stopApp(first);

    const second = await startApp(first.app.config.dataDir);
    const after = (await (
      await fetch(`${second.baseUrl}/api/bots/expert/timeline`)
    ).json()) as TimelinePage;
    expect(after.messages).toEqual(before.messages);
    expect(after.toolEvents).toEqual(before.toolEvents);
    expect(after.tasks[0]?.status).toBe('done');
  });

  it('summarizes harness, engines, network, and model errors in /api/status', async () => {
    const failing = new FakeDriver({
      script: [{ type: 'fail', message: '429 rate limit: insufficient quota' }],
    });
    const { baseUrl, app } = await startApp(
      undefined,
      failing,
      async (port) => port === 8865,
    );
    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '查一下额度' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'failed');

    const status = (await (await fetch(`${baseUrl}/api/status`)).json()) as {
      ok: boolean;
      harness: { connected: boolean; lastError: unknown };
      engines: Array<{ port: number; name: string; healthy: boolean }>;
      network: { lastError: unknown };
      lastModelError: { code: string; taskId: string; message: string } | null;
    };
    expect(status.ok).toBe(true);
    expect(status.engines).toEqual([
      { port: 8865, name: 'cn-watch', healthy: true },
      { port: 8866, name: 'market-watch', healthy: false },
      { port: 8867, name: 'chives-hub', healthy: false },
    ]);
    expect(status.lastModelError).toMatchObject({
      code: 'model_quota',
      taskId: accepted.taskId,
    });
    expect(status.lastModelError?.message).toContain('模型额度用尽或被限流');
    expect(status.network.lastError).toBeNull();
  });

  it('retries the last user message of a task without adding a duplicate bubble', async () => {
    const { baseUrl, app } = await startApp();
    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '再来一次' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    const retry = await fetch(`${baseUrl}/api/tasks/${accepted.taskId}/retry`, {
      method: 'POST',
    });
    expect(retry.status).toBe(202);
    await expect(retry.json()).resolves.toMatchObject({ taskId: accepted.taskId });
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
    const users = app.store.messages
      .listByTask(accepted.taskId)
      .filter((message) => message.role === 'user');
    expect(users).toHaveLength(1);
  });

  it('marks a task left running by a killed process as interrupted and writes a notice', async () => {
    const first = await startApp();
    const task = first.app.store.tasks.create({
      botId: 'expert',
      title: 'left running',
      startedAt: new Date().toISOString(),
    });
    await stopApp(first);

    const second = await startApp(first.app.config.dataDir);
    const page = (await (
      await fetch(`${second.baseUrl}/api/bots/expert/timeline`)
    ).json()) as TimelinePage;
    expect(page.tasks.find((entry) => entry.id === task.id)?.status).toBe('interrupted');
    expect(page.messages.some((message) => message.kind === 'notice')).toBe(true);
  });
});
