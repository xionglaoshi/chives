import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

import type { AcpSpawnSpec, PermissionRequest } from '@chives/acp-client';

import { DshDriver } from '../src/harness/dsh-driver.js';
import type { HarnessEvent } from '../src/harness/types.js';
import { Store } from '../src/store/index.js';
import { makeBot, waitFor } from './support.js';

const fakeAgentPath = fileURLToPath(
  new URL('../../../packages/acp-client/test/fake-agent.mjs', import.meta.url),
);

function spawnFor(scenario: string, logPath: string): AcpSpawnSpec {
  return {
    command: process.execPath,
    args: [fakeAgentPath],
    env: { ...process.env, FAKE_AGENT_SCENARIO: scenario, FAKE_AGENT_LOG: logPath },
  };
}

const cleanups: Array<() => Promise<void>> = [];

async function setup(scenario: string, options: { sessionCredentialFor?: (bot: { id: string }) => string } = {}) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-dsh-'));
  const store = Store.open(dataDir);
  const notices: string[] = [];
  const permissions: PermissionRequest[] = [];
  const logPath = join(dataDir, 'acp.ndjson');
  let crashed = false;
  const driver = new DshDriver({
    dataDir,
    dshHome: join(dataDir, 'dsh-home'),
    modelOverlay: join(dataDir, 'overlay.yml'),
    personaTextFor: () => 'persona',
    spawnSpecFor: () => spawnFor(scenario, logPath),
    ...(options.sessionCredentialFor === undefined ? {} : { sessionCredentialFor: options.sessionCredentialFor }),
    onNotice: (_bot, _task, text) => notices.push(text),
    onPermission: (_bot, request) => permissions.push(request),
    onCrash: () => {
      crashed = true;
    },
  });
  cleanups.push(async () => {
    await driver.shutdown();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, driver, notices, permissions, logPath, crashed: () => crashed };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('DshDriver', () => {
  it('creates a temporary session without MCP and applies reasoning_effort', async () => {
    const { driver, logPath } = await setup('normal');
    const bot = makeBot({ mcp: ['cn_data'] });
    const reply = await driver.temporaryPrompt(bot, 'answer continue or new', {
      timeoutMs: 2000,
      config: { reasoning_effort: 'low' },
    });
    expect(reply).toBe('reply:answer continue or new');

    const lines = (await readFile(logPath, 'utf8'))
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => JSON.parse(line) as {
        method?: string;
        params?: { mcpServers?: unknown[]; configId?: string; value?: string };
      });
    expect(lines.find((line) => line.method === 'session/new')?.params?.mcpServers).toEqual([]);
    expect(lines.find((line) => line.method === 'session/set_config_option')?.params).toMatchObject({
      configId: 'reasoning_effort',
      value: 'low',
    });
    expect(lines.some((line) => line.method === 'session/close')).toBe(true);
  });

  it('runs a hidden prompt in the task session and returns its committed text', async () => {
    const { store, driver } = await setup('normal');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const sessionId = await driver.ensureSession(bot, task);
    store.tasks.setHarnessSession(task.id, sessionId);
    const stored = store.tasks.get(task.id);
    if (stored === undefined) throw new Error('missing task');

    const reply = await driver.hiddenPrompt(bot, stored, '[Chives 任务小结] only json', 2000);
    expect(reply).toBe('reply:[Chives 任务小结] only json');
  });

  it('rejects permission requests raised during a hidden prompt', async () => {
    const { store, driver, permissions } = await setup('permission');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const sessionId = await driver.ensureSession(bot, task);
    store.tasks.setHarnessSession(task.id, sessionId);
    const stored = store.tasks.get(task.id);
    if (stored === undefined) throw new Error('missing task');

    const reply = await driver.hiddenPrompt(bot, stored, '[Chives 任务小结] json please', 2000);
    expect(reply).toContain('permission:reject-once');
    expect(permissions).toHaveLength(0);
  });

  it('suppresses the resume-failure notice for a silent session', async () => {
    const { store, driver, notices } = await setup('resume-fail');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    store.tasks.setHarnessSession(task.id, 'missing-session');
    const stale = store.tasks.get(task.id);
    if (stale === undefined) throw new Error('missing task');

    const sessionId = await driver.ensureSession(bot, stale, { silent: true });
    expect(sessionId).toBe('sess-1');
    expect(notices).toHaveLength(0);
  });

  it('falls back to a new session and reports a notice when resume fails', async () => {
    const { store, driver, notices, logPath } = await setup('resume-fail');
    const bot = makeBot({ mcp: ['cn_data'] });
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    store.tasks.setHarnessSession(task.id, 'missing-session');
    const stale = store.tasks.get(task.id);
    if (stale === undefined) throw new Error('missing task');

    const sessionId = await driver.ensureSession(bot, stale);
    expect(sessionId).toBe('sess-1');
    expect(notices).toHaveLength(1);
    expect(notices[0]).toContain('无法恢复');

    const lines = (await readFile(logPath, 'utf8'))
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => JSON.parse(line) as { method?: string; params?: { mcpServers?: Array<{ name: string }> } });
    const resume = lines.find((line) => line.method === 'session/resume');
    expect(resume?.params?.mcpServers?.map((server) => server.name)).toEqual(['cn_data', 'chives']);
  });

  it('issues a session token into the built-in chives MCP declaration', async () => {
    const { store, driver, logPath } = await setup('resume-fail', {
      sessionCredentialFor: () => 'issued-session-token',
    });
    const bot = makeBot({ mcp: ['cn_data'], panels: ['market', 'portfolio', 'watches'] });
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    store.tasks.setHarnessSession(task.id, 'missing-session');
    const stale = store.tasks.get(task.id);
    if (stale === undefined) throw new Error('missing task');
    await driver.ensureSession(bot, stale);

    const lines = (await readFile(logPath, 'utf8'))
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => JSON.parse(line) as {
        method?: string;
        params?: { mcpServers?: Array<{ name: string; env?: Array<{ name: string; value: string }> }> };
      });
    const created = lines.find((line) => line.method === 'session/new');
    const chives = created?.params?.mcpServers?.find((server) => server.name === 'chives');
    expect(chives?.env).toContainEqual({ name: 'CHIVES_SESSION_TOKEN', value: 'issued-session-token' });
    expect(chives?.env).toContainEqual({ name: 'CHIVES_API', value: 'http://127.0.0.1:8880' });
    expect(chives?.env).toContainEqual({ name: 'CHIVES_FEATURES', value: 'watches' });
  });

  it('reuses a session already live in the same process without resuming it again', async () => {
    const { store, driver, notices, logPath } = await setup('tools');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const first = await driver.ensureSession(bot, task);
    store.tasks.setHarnessSession(task.id, first);
    const continued = store.tasks.get(task.id);
    if (continued === undefined) throw new Error('missing task');

    expect(await driver.ensureSession(bot, continued)).toBe(first);
    expect(notices).toHaveLength(0);
    const methods = (await readFile(logPath, 'utf8'))
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => (JSON.parse(line) as { method?: string }).method);
    expect(methods.filter((method) => method === 'session/resume')).toHaveLength(0);
    expect(methods.filter((method) => method === 'session/new')).toHaveLength(1);
  });

  it('maps ACP messages, tool calls, and usage into sink events', async () => {
    const { store, driver } = await setup('tools');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const sessionId = await driver.ensureSession(bot, task);
    const events: HarnessEvent[] = [];
    const result = await driver.prompt(bot, sessionId, 'hi', (event) => events.push(event));
    expect(result.stopReason).toBe('end_turn');
    expect(events.map((event) => event.type)).toEqual(['tool_start', 'tool_end', 'draft_commit', 'message']);
  });

  it('rejects permission requests in M1 and reports them to the orchestrator', async () => {
    const { store, driver, permissions } = await setup('permission');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const sessionId = await driver.ensureSession(bot, task);
    const messages: string[] = [];
    await driver.prompt(bot, sessionId, 'order', (event) => {
      if (event.type === 'message') messages.push(event.text);
    });
    expect(permissions).toHaveLength(1);
    expect(permissions[0]?.title).toBe('paper_place_order');
    expect(messages.join('')).toContain('reject-once');
  });

  it('reports a crashed process and rejects the prompt', async () => {
    const { store, driver, crashed } = await setup('crash');
    const bot = makeBot();
    const task = store.tasks.create({ botId: bot.id, startedAt: new Date().toISOString() });
    const sessionId = await driver.ensureSession(bot, task);
    await expect(driver.prompt(bot, sessionId, 'crash', () => undefined)).rejects.toThrow();
    await waitFor(() => crashed());
    expect(crashed()).toBe(true);
  });
});
