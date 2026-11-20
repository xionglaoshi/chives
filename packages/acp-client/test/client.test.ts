import { afterEach, describe, expect, it } from 'vitest';

import {
  AcpClient,
  AcpProcessExitedError,
  AcpUnsupportedError,
  DraftTracker,
  STREAM_SOCKET_ENV,
  StreamChannel,
  type AcpClientOptions,
  type AcpEvent,
  type DraftEvent,
  type InitializeResult,
  type PermissionRequest,
} from '../src/index.js';
import { fakeSpawnSpec, makeLog, waitFor, type LogContext } from './helpers.js';

interface ClientContext {
  client: AcpClient;
  log: LogContext;
  initialized: InitializeResult;
}

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

async function start(
  scenario: string,
  options: AcpClientOptions = {},
  env: Record<string, string | undefined> = {},
): Promise<ClientContext> {
  const log = await makeLog();
  const client = new AcpClient(
    fakeSpawnSpec({ scenario, logPath: log.logPath, env }),
    { requestTimeoutMs: 3000, closeGraceMs: 1000, ...options },
  );
  cleanups.push(async () => {
    await client.close();
    await log.cleanup();
  });
  const initialized = await client.initialize();
  return { client, log, initialized };
}

function methodMessages(log: LogContext): Promise<Record<string, unknown>[]> {
  return log.read();
}

describe('AcpClient typed methods', () => {
  it('performs the full session lifecycle with the expected request shapes', async () => {
    const { client, log, initialized } = await start('normal');
    expect(initialized).toMatchObject({
      protocolVersion: 1,
      agentCapabilities: { sessionCapabilities: { list: {}, resume: {}, close: {} } },
    });

    const events: AcpEvent[] = [];
    client.onEvent((event) => events.push(event));
    const mcpServers = [
      { name: 'cn_extra', command: '/usr/bin/python3', args: ['-m', 'cn_extra_mcp'], env: [{ name: 'A', value: 'B' }] },
      { type: 'http' as const, name: 'remote', url: 'https://example.test/mcp', headers: [{ name: 'X-Test', value: '1' }] },
    ];
    const session = await client.newSession({ cwd: '/tmp', mcpServers });
    expect(session.sessionId).toMatch(/^sess-/);
    expect(session.configOptions?.length).toBe(2);

    const list = await client.listSessions({ cwd: '/tmp' });
    expect(list.sessions.map((entry) => entry.sessionId)).toContain(session.sessionId);

    const resumed = await client.resumeSession({
      sessionId: session.sessionId,
      cwd: '/tmp',
      mcpServers,
    });
    expect(resumed.configOptions?.length).toBe(2);

    const configs = await client.setConfigOption(session.sessionId, 'reasoning_effort', 'high');
    expect(configs.find((option) => option.id === 'reasoning_effort')?.currentValue).toBe('high');

    const result = await client.prompt(session.sessionId, [{ type: 'text', text: 'hello' }]);
    expect(result.stopReason).toBe('end_turn');
    expect(events.some((event) => event.type === 'message' && event.text === 'reply:hello')).toBe(true);
    expect(events.some((event) => event.type === 'thought')).toBe(true);

    await client.closeSession(session.sessionId);

    const messages = await methodMessages(log);
    const newSession = messages.find((entry) => entry.method === 'session/new');
    expect(newSession?.params).toMatchObject({ cwd: '/tmp', mcpServers });
    const prompt = messages.find((entry) => entry.method === 'session/prompt');
    expect(prompt?.params).toMatchObject({
      sessionId: session.sessionId,
      prompt: [{ type: 'text', text: 'hello' }],
    });
    expect(messages.some((entry) => entry.method === 'session/close')).toBe(true);
    const resume = messages.find((entry) => entry.method === 'session/resume');
    expect(resume?.params).toMatchObject({ sessionId: session.sessionId, cwd: '/tmp', mcpServers });
  });

  it('returns stopReason cancelled after a cancel notification', async () => {
    const { client, log } = await start('cancel');
    const session = await client.newSession({ cwd: '/tmp' });
    const pending = client.prompt(session.sessionId, [{ type: 'text', text: 'wait' }]);
    await new Promise((resolve) => {
      setTimeout(resolve, 30);
    });
    client.cancel(session.sessionId);
    await expect(pending).resolves.toMatchObject({ stopReason: 'cancelled' });
    const messages = await log.read();
    expect(messages.some((entry) => entry.method === 'session/cancel')).toBe(true);
  });

  it('rejects unsupported optional methods with AcpUnsupportedError', async () => {
    const { client } = await start('minimal');
    await expect(client.listSessions()).rejects.toBeInstanceOf(AcpUnsupportedError);
    await expect(client.resumeSession({ sessionId: 'sess-1', cwd: '/tmp' })).rejects.toBeInstanceOf(AcpUnsupportedError);
    await expect(client.closeSession('sess-1')).rejects.toBeInstanceOf(AcpUnsupportedError);
  });

  it('answers an unknown agent request with -32601', async () => {
    const { client, log } = await start('unknown-request');
    const events: AcpEvent[] = [];
    client.onEvent((event) => events.push(event));
    const session = await client.newSession({ cwd: '/tmp' });
    await client.prompt(session.sessionId, [{ type: 'text', text: 'go' }]);
    expect(events.some((event) => event.type === 'message' && event.text === 'error:-32601')).toBe(true);
    const messages = await log.read();
    expect(messages.some((entry) => {
      const error = entry.error;
      return typeof error === 'object' && error !== null && (error as { code?: unknown }).code === -32601;
    })).toBe(true);
  });

  it('fails a prompt when the process crashes', async () => {
    const { client } = await start('crash');
    const session = await client.newSession({ cwd: '/tmp' });
    await expect(client.prompt(session.sessionId, [{ type: 'text', text: 'go' }]))
      .rejects.toBeInstanceOf(AcpProcessExitedError);
  });
});

describe('permissions', () => {
  it('allows once and correlates rawInput from the preceding tool_start', async () => {
    const { client, log } = await start('permission');
    const requests: PermissionRequest[] = [];
    const events: AcpEvent[] = [];
    client.onEvent((event) => events.push(event));
    client.onPermission((request) => {
      requests.push(request);
      return 'allow';
    });
    const session = await client.newSession({ cwd: '/tmp' });
    await client.prompt(session.sessionId, [{ type: 'text', text: 'order' }]);

    expect(requests).toHaveLength(1);
    expect(requests[0]).toMatchObject({
      sessionId: session.sessionId,
      toolCallId: 'tool-p',
      title: 'paper_place_order',
      rawInput: { symbol: '600519.SH', quantity: 100 },
    });
    expect(events.find((event) => event.type === 'tool_end')).toMatchObject({
      toolCallId: 'tool-p',
      status: 'completed',
      output: 'permission:allow-once',
    });
    const messages = await log.read();
    expect(messages.some((entry) => {
      const result = entry.result;
      return typeof result === 'object' && result !== null
        && (result as { outcome?: { optionId?: unknown } }).outcome?.optionId === 'allow-once';
    })).toBe(true);
  });

  it('rejects on handler rejection and on handler throw', async () => {
    for (const mode of ['reject', 'throw'] as const) {
      const { client } = await start('permission');
      client.onPermission(() => {
        if (mode === 'throw') throw new Error('denied');
        return 'reject';
      });
      const session = await client.newSession({ cwd: '/tmp' });
      const events: AcpEvent[] = [];
      client.onEvent((event) => events.push(event));
      await client.prompt(session.sessionId, [{ type: 'text', text: 'order' }]);
      expect(events.find((event) => event.type === 'tool_end')).toMatchObject({
        status: 'failed',
        output: 'permission:reject-once',
      });
      await client.close();
    }
  });

  it('treats a handler timeout as reject', async () => {
    const { client } = await start('permission', { permissionTimeoutMs: 30 });
    client.onPermission(() => new Promise(() => undefined));
    const session = await client.newSession({ cwd: '/tmp' });
    const events: AcpEvent[] = [];
    client.onEvent((event) => events.push(event));
    await client.prompt(session.sessionId, [{ type: 'text', text: 'order' }]);
    expect(events.find((event) => event.type === 'tool_end')).toMatchObject({
      status: 'failed',
      output: 'permission:reject-once',
    });
  });
});

describe('streaming', () => {
  it('reports streamingObserved=false when a message arrives without deltas', async () => {
    const { client } = await start('normal', { streaming: true });
    expect(client.streaming).toBe(true);
    const session = await client.newSession({ cwd: '/tmp' });
    await client.prompt(session.sessionId, [{ type: 'text', text: 'hello' }]);
    expect(client.streamingObserved).toBe(false);
  });

  it('commits the retried attempt and discards the old draft', async () => {
    const channel = new StreamChannel();
    const socketPath = await channel.start();
    cleanups.push(async () => {
      await channel.close();
    });
    const { client } = await start('stream', { streaming: true }, { [STREAM_SOCKET_ENV]: socketPath });
    const drafts: DraftEvent[] = [];
    const tracker = new DraftTracker((event) => drafts.push(event));
    channel.onFrame((frame) => {
      client.markDraftActivity();
      tracker.handleFrame(frame);
    });
    client.onEvent((event) => {
      if (event.type === 'message') tracker.handleCommitted(event.sessionId, event.text);
    });
    const session = await client.newSession({ cwd: '/tmp' });
    await client.prompt(session.sessionId, [{ type: 'text', text: 'stream' }]);
    await waitFor(() => drafts.some((event) => event.type === 'draft_commit'));

    const resets = drafts.filter((event) => event.type === 'draft_reset');
    expect(resets.map((event) => (event.type === 'draft_reset' ? event.attemptId : undefined)))
      .toEqual(['attempt-1', 'attempt-2']);
    const commit = drafts.find((event) => event.type === 'draft_commit');
    expect(commit).toMatchObject({ type: 'draft_commit', text: 'NEW TEXT' });
    expect(drafts.some((event) => event.type === 'draft_commit' && event.text === 'OLD DRAFT')).toBe(false);
    expect(client.streamingObserved).toBe(true);
  });
});
