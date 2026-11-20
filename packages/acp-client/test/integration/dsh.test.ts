import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';

import {
  AcpClient,
  DraftTracker,
  StreamChannel,
  pluginPath,
  streamPatchYaml,
  type AcpEvent,
  type DraftEvent,
  type InitializeResult,
  type McpServer,
  type PermissionRequest,
} from '../../src/index.js';

const enabled = process.env.CHIVES_ACP_INTEGRATION === '1';
const suite = enabled ? describe : describe.skip;

const repoRoot = fileURLToPath(new URL('../../../../', import.meta.url));
const personaPath = join(repoRoot, 'fixtures/acp-probe/persona.cordis.yml');
const cnExtraPython = join(repoRoot, 'packages/cn-extra-mcp/.venv/bin/python');
const paperPython = join(repoRoot, 'packages/paper-broker-mcp/.venv/bin/python');
const tradingGuardPath = join(repoRoot, 'overlays/trading-guard.cordis.yml');

interface Rig {
  client: AcpClient;
  channel: StreamChannel;
  initialized: InitializeResult;
  events: AcpEvent[];
  drafts: DraftEvent[];
  endedDrafts: string[];
  dispose: () => Promise<void>;
}

interface RigOptions {
  patches?: readonly string[];
  env?: Record<string, string | undefined>;
}

let root = '';
let workspace1 = '';
let workspace2 = '';
let rig1: Rig | undefined;
let rig2: Rig | undefined;
let rig3: Rig | undefined;
let sessionA = '';

function texts(events: readonly AcpEvent[]): string {
  return events
    .filter((event): event is AcpEvent & { type: 'message' } => event.type === 'message')
    .map((event) => event.text)
    .join('');
}

async function createRig(options: RigOptions = {}): Promise<Rig> {
  const home = process.env.DSH_FINANCE_HOME;
  const overlay = process.env.DSH_FINANCE_OVERLAY;
  if (home === undefined || overlay === undefined) {
    throw new Error('CHIVES_ACP_INTEGRATION requires DSH_FINANCE_HOME and DSH_FINANCE_OVERLAY');
  }
  const channel = new StreamChannel();
  const socketPath = await channel.start();
  const patchFile = join(root, `stream-${Date.now()}-${Math.random().toString(16).slice(2)}.yml`);
  await writeFile(patchFile, streamPatchYaml(pluginPath()), 'utf8');
  const client = new AcpClient(
    {
      command: 'npx',
      args: [
        '-y',
        '@deepseek-ai/dsh@0.2.2-rc.1',
        '--profile',
        'acp',
        '--patch',
        overlay,
        '--patch',
        personaPath,
        ...(options.patches ?? []).flatMap((patch) => ["--patch", patch]),
        '--patch',
        patchFile,
      ],
      cwd: repoRoot,
      env: {
        ...process.env,
        DSH_HOME: home,
        DSH_PERMISSION_MODE: 'workspace-write',
        DSH_TELEMETRY_MODE: 'DISABLED',
        CHIVES_STREAM_SOCKET: socketPath,
        ...options.env,
      },
      stderrLines: 200,
    },
    {
      requestTimeoutMs: 180_000,
      initializeTimeoutMs: 180_000,
      permissionTimeoutMs: 120_000,
      streaming: true,
      closeGraceMs: 5000,
    },
  );
  const events: AcpEvent[] = [];
  const drafts: DraftEvent[] = [];
  const endedDrafts: string[] = [];
  const tracker = new DraftTracker((event) => drafts.push(event));
  channel.onFrame((frame) => {
    client.markDraftActivity();
    tracker.handleFrame(frame);
    if (frame.t === 'end') {
      const snapshot = tracker.snapshot(frame.session);
      if (snapshot !== undefined) endedDrafts.push(snapshot.text);
    }
  });
  client.onEvent((event) => {
    events.push(event);
    if (event.type === 'message') tracker.handleCommitted(event.sessionId, event.text);
  });
  const initialized = await client.initialize();
  return {
    client,
    channel,
    initialized,
    events,
    drafts,
    endedDrafts,
    dispose: async () => {
      await client.close();
      await channel.close();
    },
  };
}

function mcpServers(): McpServer[] {
  return [{ name: 'cn_extra', command: cnExtraPython, args: ['-m', 'cn_extra_mcp'], env: [] }];
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

suite('dsh ACP integration', () => {
  it('initializes, mounts MCP, streams deltas, and calls a tool', async () => {
    root = await mkdtemp(join(tmpdir(), 'chives-acp-integration-'));
    workspace1 = await mkdtemp(join(root, 'ws-'));
    rig1 = await createRig();
    expect(rig1.initialized.agentCapabilities?.sessionCapabilities?.resume).toBeDefined();
    const created = await rig1.client.newSession({ cwd: workspace1, mcpServers: mcpServers() });
    expect(created.sessionId.length).toBeGreaterThan(0);
    sessionA = created.sessionId;

    const before = rig1.events.length;
    const start = rig1.drafts.length;
    const result = await rig1.client.prompt(sessionA, [{
      type: 'text',
      text: '用 cn_get_quote_snapshot 查 600519.SH 的现价，只回答现价和行情时间。',
    }]);
    expect(result.stopReason).toBe('end_turn');
    const turnEvents = rig1.events.slice(before);
    expect(turnEvents.some((event) => event.type === 'tool_start')).toBe(true);
    expect(turnEvents.some((event) => event.type === 'tool_end' && event.status === 'completed')).toBe(true);
    expect(texts(turnEvents).length).toBeGreaterThan(0);

    await sleep(500);
    expect(rig1.client.streamingObserved).toBe(true);
    const commits = rig1.drafts.slice(start).filter((event) => event.type === 'draft_commit');
    expect(commits.length).toBeGreaterThan(0);
    for (const commit of commits) {
      expect(rig1.endedDrafts).toContain(commit.text);
    }
  }, 300_000);

  it('keeps context across turns in the same process', async () => {
    if (rig1 === undefined) throw new Error('rig1 was not created');
    const before = rig1.events.length;
    const result = await rig1.client.prompt(sessionA, [{ type: 'text', text: '我上一句问的是哪只股票？只回答代码。' }]);
    expect(result.stopReason).toBe('end_turn');
    expect(texts(rig1.events.slice(before))).toContain('600519');
    await rig1.client.closeSession(sessionA);
    await rig1.dispose();
    rig1 = undefined;
  }, 300_000);

  it('lists and resumes the persisted session with the MCP list in a new process', async () => {
    rig2 = await createRig();
    const listed = await rig2.client.listSessions({ cwd: workspace1 });
    expect(listed.sessions.map((entry) => entry.sessionId)).toContain(sessionA);
    const resumed = await rig2.client.resumeSession({ sessionId: sessionA, cwd: workspace1, mcpServers: mcpServers() });
    expect(resumed.configOptions?.length).toBeGreaterThan(0);
    const before = rig2.events.length;
    const result = await rig2.client.prompt(sessionA, [{
      type: 'text',
      text: '再用 cn_get_quote_snapshot 查 600519.SH 的现价，只回答现价。',
    }]);
    expect(result.stopReason).toBe('end_turn');
    const turnEvents = rig2.events.slice(before);
    expect(turnEvents.some((event) => event.type === 'tool_end' && event.status === 'completed')).toBe(true);
  }, 300_000);

  it('cancels a running turn and leaves the session usable', async () => {
    if (rig2 === undefined) throw new Error('rig2 was not created');
    const pending = rig2.client.prompt(sessionA, [{
      type: 'text',
      text: '用 bash 执行 sleep 30，然后回答完成。',
    }]);
    await sleep(3000);
    rig2.client.cancel(sessionA);
    const result = await pending;
    expect(result.stopReason).toBe('cancelled');
    const followUp = await rig2.client.prompt(sessionA, [{ type: 'text', text: '回答：好的。' }]);
    expect(followUp.stopReason).toBe('end_turn');
  }, 300_000);

  it('runs two sessions in one process concurrently', async () => {
    if (rig2 === undefined) throw new Error('rig2 was not created');
    const first = await rig2.client.newSession({ cwd: workspace1, mcpServers: [] });
    const second = await rig2.client.newSession({ cwd: workspace1, mcpServers: [] });
    const before = rig2.events.length;
    const [a, b] = await Promise.all([
      rig2.client.prompt(first.sessionId, [{ type: 'text', text: '只回答数字：17 乘以 3 等于几？' }]),
      rig2.client.prompt(second.sessionId, [{ type: 'text', text: '只回答数字：19 乘以 4 等于几？' }]),
    ]);
    expect(a.stopReason).toBe('end_turn');
    expect(b.stopReason).toBe('end_turn');
    const turnEvents = rig2.events.slice(before);
    const textFor = (sessionId: string): string => texts(turnEvents.filter((event) => event.sessionId === sessionId));
    expect(textFor(first.sessionId)).toContain('51');
    expect(textFor(second.sessionId)).toContain('76');
  }, 300_000);

  it('routes the trading guard permission through the client and rejects it', async () => {
    workspace2 = await mkdtemp(join(root, 'ws-guard-'));
    const stateDir = await mkdtemp(join(root, 'paper-state-'));
    rig3 = await createRig({ patches: [tradingGuardPath] });
    const requests: PermissionRequest[] = [];
    rig3.client.onPermission((request) => {
      requests.push(request);
      return 'reject';
    });
    const created = await rig3.client.newSession({
      cwd: workspace2,
      mcpServers: [{
        name: 'paper_broker',
        command: paperPython,
        args: ['-m', 'paper_broker_mcp', '--state-dir', stateDir],
        env: [],
      }],
    });
    const before = rig3.events.length;
    const result = await rig3.client.prompt(created.sessionId, [{
      type: 'text',
      text: '调用 paper_place_order 在模拟盘买入 600519.SH 100 股，市价单。把工具返回的结果原样告诉我。',
    }]);
    expect(result.stopReason).toBe('end_turn');
    expect(requests.length).toBeGreaterThan(0);
    expect(requests[0]?.rawInput).toBeDefined();
    const turnEvents = rig3.events.slice(before);
    expect(turnEvents.some((event) => event.type === 'tool_end' && event.status === 'failed')).toBe(true);
  }, 300_000);

  afterAll(async () => {
    for (const rig of [rig1, rig2, rig3]) await rig?.dispose();
    if (root !== '') await rm(root, { recursive: true, force: true });
  }, 60_000);
});
