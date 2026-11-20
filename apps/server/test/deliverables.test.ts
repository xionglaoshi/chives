import {
  closeSync,
  ftruncateSync,
  mkdirSync,
  openSync,
  realpathSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { DeliverableDto, MessageAccepted, ServerEvent, TimelinePage } from '../src/api/protocol.js';
import {
  MAX_DELIVERABLE_BYTES,
  classifyKind,
  diffWorkspace,
  revealInFinder,
  snapshotWorkspace,
} from '../src/deliverables/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

const directories: string[] = [];
const apps: Array<{ app: ChivesApp; baseUrl: string }> = [];

afterEach(async () => {
  for (const entry of apps.splice(0)) {
    entry.app.sse.closeAll();
    await closeServer(entry.app.server);
    await entry.app.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

async function tempDir(prefix: string): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  directories.push(directory);
  return directory;
}

function workspaceOf(dataDir: string, botId: string): string {
  return join(dataDir, 'bots', botId, 'workspace');
}

async function startApp(
  dataDir: string,
  options: {
    script?: readonly FakeStep[];
    revealExec?: (file: string, args: readonly string[], callback: (error: Error | null) => void) => void;
    platform?: NodeJS.Platform;
  } = {},
): Promise<{ app: ChivesApp; baseUrl: string }> {
  const driver = new FakeDriver({
    ...(options.script === undefined ? {} : { script: options.script }),
    workspaceDirFor: (bot) => workspaceOf(dataDir, bot.id),
  });
  const app = createApp({
    config: testConfig(dataDir),
    driver,
    ...(options.revealExec === undefined ? {} : { revealExec: options.revealExec }),
    ...(options.platform === undefined ? {} : { platform: options.platform }),
  });
  const baseUrl = await listen(app.server);
  const entry = { app, baseUrl };
  apps.push(entry);
  return entry;
}

function seedDeliverable(
  app: ChivesApp,
  botId: string,
  path: string,
  kind: DeliverableDto['kind'] = 'other',
): DeliverableDto {
  const task = app.store.tasks.create({
    botId,
    title: 'deliverable fixture',
    startedAt: new Date().toISOString(),
  });
  const record = {
    id: `d-${botId}-${path.replaceAll('/', '-')}`,
    taskId: task.id,
    botId,
    path,
    kind,
    size: 0,
    createdAt: new Date().toISOString(),
  };
  return app.store.deliverables.add(record);
}

describe('workspace snapshots', () => {
  it('detects added and modified files and ignores noise', async () => {
    const root = await tempDir('chives-snap-');
    const workspace = join(root, 'workspace');
    mkdirSync(join(workspace, 'node_modules', 'pkg'), { recursive: true });
    mkdirSync(join(workspace, '__pycache__'), { recursive: true });
    mkdirSync(join(workspace, '.hidden'), { recursive: true });
    writeFileSync(join(workspace, 'unchanged.md'), 'same');
    writeFileSync(join(workspace, 'modified.md'), 'one');
    writeFileSync(join(workspace, 'node_modules', 'pkg', 'x.js'), 'ignored');
    writeFileSync(join(workspace, '__pycache__', 'x.pyc'), 'ignored');
    writeFileSync(join(workspace, '.hidden', 'x.txt'), 'ignored');
    writeFileSync(join(workspace, '.dotfile'), 'ignored');
    const big = join(workspace, 'huge.bin');
    const fd = openSync(big, 'w');
    ftruncateSync(fd, MAX_DELIVERABLE_BYTES + 1);
    closeSync(fd);

    const before = snapshotWorkspace(workspace);
    writeFileSync(join(workspace, 'modified.md'), 'two');
    writeFileSync(join(workspace, 'added.png'), 'png');
    const after = snapshotWorkspace(workspace);
    const changes = diffWorkspace(before, after);

    expect(changes.map((change) => change.path)).toEqual(['added.png', 'modified.md']);
    expect(classifyKind('added.png')).toBe('image');
    expect(classifyKind('report.md')).toBe('markdown');
    expect(classifyKind('data.csv')).toBe('csv');
    expect(classifyKind('analysis.json')).toBe('json');
    expect(classifyKind('page.html')).toBe('html');
    expect(classifyKind('chart.pdf')).toBe('pdf');
    expect(classifyKind('main.py')).toBe('code');
    expect(classifyKind('unknown.xyz')).toBe('other');
  });
});

describe('deliverable API', () => {
  it('returns metadata, content with a content type, and recent per-bot files', async () => {
    const dataDir = await tempDir('chives-deliv-api-');
    const { app, baseUrl } = await startApp(dataDir);
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, 'report.md'), '# 标题\n\n正文');
    const deliverable = app.store.deliverables.add({
      id: 'deliverable-md-1',
      taskId: app.store.tasks.create({
        botId: 'expert',
        title: 't',
        startedAt: new Date().toISOString(),
      }).id,
      botId: 'expert',
      path: 'report.md',
      kind: 'markdown',
      size: 11,
      createdAt: new Date().toISOString(),
    });

    const metadata = await fetch(`${baseUrl}/api/deliverables/${deliverable.id}`);
    expect(metadata.status).toBe(200);
    await expect(metadata.json()).resolves.toMatchObject({
      id: deliverable.id,
      path: 'report.md',
      kind: 'markdown',
      size: 11,
    });

    const content = await fetch(`${baseUrl}/api/deliverables/${deliverable.id}/content`);
    expect(content.status).toBe(200);
    expect(content.headers.get('content-type')).toBe('text/markdown; charset=utf-8');
    await expect(content.text()).resolves.toBe('# 标题\n\n正文');

    const recent = (await (await fetch(`${baseUrl}/api/bots/expert/deliverables?limit=5`)).json()) as DeliverableDto[];
    expect(recent.map((entry) => entry.id)).toEqual([deliverable.id]);
  });

  it('rejects .. and symlink escapes with 403', async () => {
    const dataDir = await tempDir('chives-deliv-escape-');
    const { app, baseUrl } = await startApp(dataDir);
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, '..', 'secret.txt'), 'secret');
    symlinkSync(join(workspace, '..', 'secret.txt'), join(workspace, 'leak.txt'));

    const traversal = seedDeliverable(app, 'expert', '../secret.txt', 'code');
    const missingTraversal = seedDeliverable(app, 'expert', '../../missing.txt', 'code');
    const symlink = seedDeliverable(app, 'expert', 'leak.txt', 'code');
    expect((await fetch(`${baseUrl}/api/deliverables/${traversal.id}/content`)).status).toBe(403);
    expect((await fetch(`${baseUrl}/api/deliverables/${missingTraversal.id}/content`)).status).toBe(403);
    expect((await fetch(`${baseUrl}/api/deliverables/${symlink.id}/content`)).status).toBe(403);
    const revealed = await fetch(`${baseUrl}/api/deliverables/${traversal.id}/reveal`, { method: 'POST' });
    expect(revealed.status).toBe(403);
  });

  it('returns 413 above the text and binary limits', async () => {
    const dataDir = await tempDir('chives-deliv-size-');
    const { app, baseUrl } = await startApp(dataDir);
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(workspace, { recursive: true });
    const textPath = join(workspace, 'too-big.md');
    const textFd = openSync(textPath, 'w');
    ftruncateSync(textFd, 2 * 1024 * 1024 + 1);
    closeSync(textFd);
    const imagePath = join(workspace, 'too-big.png');
    const imageFd = openSync(imagePath, 'w');
    ftruncateSync(imageFd, 20 * 1024 * 1024 + 1);
    closeSync(imageFd);

    const text = seedDeliverable(app, 'expert', 'too-big.md');
    const image = seedDeliverable(app, 'expert', 'too-big.png');
    expect((await fetch(`${baseUrl}/api/deliverables/${text.id}/content`)).status).toBe(413);
    expect((await fetch(`${baseUrl}/api/deliverables/${image.id}/content`)).status).toBe(413);
  });

  it('reveals via execFile open -R and returns 501 off macOS', async () => {
    const dataDir = await tempDir('chives-deliv-reveal-');
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, 'report.md'), 'hi');
    const calls: Array<{ file: string; args: readonly string[] }> = [];
    const revealExec = (file: string, args: readonly string[], callback: (error: Error | null) => void): void => {
      calls.push({ file, args });
      callback(null);
    };
    const { app, baseUrl } = await startApp(dataDir, { revealExec, platform: 'darwin' });
    const deliverable = seedDeliverable(app, 'expert', 'report.md');
    const response = await fetch(`${baseUrl}/api/deliverables/${deliverable.id}/reveal`, { method: 'POST' });
    expect(response.status).toBe(200);
    expect(calls).toEqual([
      { file: 'open', args: ['-R', realpathSync(join(workspace, 'report.md'))] },
    ]);

    const otherDir = await tempDir('chives-deliv-reveal-other-');
    const other = await startApp(otherDir, { platform: 'linux' });
    const otherWorkspace = workspaceOf(otherDir, 'expert');
    mkdirSync(otherWorkspace, { recursive: true });
    writeFileSync(join(otherWorkspace, 'report.md'), 'hi');
    const otherDeliverable = seedDeliverable(other.app, 'expert', 'report.md');
    const unsupported = await fetch(
      `${other.baseUrl}/api/deliverables/${otherDeliverable.id}/reveal`,
      { method: 'POST' },
    );
    expect(unsupported.status).toBe(501);
  });

  it('unit-tests revealInFinder arguments and errors without opening Finder', async () => {
    const exec = vi.fn((_file: string, _args: readonly string[], callback: (error: Error | null) => void) => {
      callback(null);
    });
    await revealInFinder('/tmp/x.md', { exec, platform: 'darwin' });
    expect(exec).toHaveBeenCalledWith('open', ['-R', '/tmp/x.md'], expect.any(Function));
    await expect(revealInFinder('/tmp/x.md', { platform: 'linux' })).rejects.toMatchObject({
      status: 501,
    });
  });
});

describe('deliverable capture', () => {
  it('records two files written in one fake turn and serves their content', async () => {
    const dataDir = await tempDir('chives-deliv-turn-');
    const { app, baseUrl } = await startApp(dataDir, {
      script: [
        { type: 'write', path: 'notes/report.md', content: '# 报告\n\n结论' },
        { type: 'write', path: 'charts/pe.png', content: 'png-bytes' },
        { type: 'message', text: '完成' },
      ],
    });

    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '写报告' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    const page = (await (await fetch(`${baseUrl}/api/bots/expert/timeline`)).json()) as TimelinePage;
    const message = page.messages.find((entry) => entry.kind === 'deliverable');
    expect(message).toBeDefined();
    const ids = message?.meta?.['deliverableIds'] as string[];
    expect(ids).toHaveLength(2);
    const embedded = message?.meta?.['deliverables'] as DeliverableDto[];
    expect(embedded.map((entry) => entry.path)).toEqual(['charts/pe.png', 'notes/report.md']);
    expect(embedded.every((entry) => entry.taskId === accepted.taskId)).toBe(true);

    const report = embedded.find((entry) => entry.path === 'notes/report.md');
    const content = await fetch(`${baseUrl}/api/deliverables/${report?.id}/content`);
    expect(content.headers.get('content-type')).toBe('text/markdown; charset=utf-8');
    await expect(content.text()).resolves.toBe('# 报告\n\n结论');
    const image = embedded.find((entry) => entry.path === 'charts/pe.png');
    const imageContent = await fetch(`${baseUrl}/api/deliverables/${image?.id}/content`);
    expect(imageContent.headers.get('content-type')).toBe('image/png');
  });

  it('updates one row for a path modified again in the same task', async () => {
    const dataDir = await tempDir('chives-deliv-upsert-');
    const { app, baseUrl } = await startApp(dataDir, {
      script: [
        { type: 'write', path: 'report.md', content: 'v1' },
        { type: 'message', text: 'ok' },
      ],
    });
    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 'first' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
    expect(app.store.deliverables.countByTask(accepted.taskId)).toBe(1);
    const first = app.store.deliverables.listByTask(accepted.taskId)[0];
    expect(first?.size).toBe(2);

    const second = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 'second' }),
      })
    ).json()) as MessageAccepted;
    expect(second.taskId).toBe(accepted.taskId);
    await waitFor(() => app.store.tasks.get(second.taskId)?.status === 'done');
    const rows = app.store.deliverables.listByTask(accepted.taskId);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.size).toBe(2);
  });

  it('attributes a delegated child file to the root task and the producing bot', async () => {
    const dataDir = await tempDir('chives-deliv-delegated-');
    const { app } = await startApp(dataDir, {
      script: [
        { type: 'write', path: 'dataset.md', content: '# 数据\n' },
        { type: 'message', text: 'done' },
      ],
    });
    const parent = app.store.tasks.create({
      botId: 'expert',
      title: 'parent',
      startedAt: new Date().toISOString(),
    });
    const child = app.store.tasks.create({
      botId: 'research',
      title: 'child',
      startedAt: new Date().toISOString(),
      parentTaskId: parent.id,
      depth: 1,
      delegated: true,
      brief: '取数',
    });
    app.orchestrator.startDelegatedTask(child, '取数');
    await waitFor(() => app.store.tasks.get(child.id)?.status === 'done');

    const rows = app.store.deliverables.listByTask(parent.id);
    const delegated = rows.find((row) => row.path === 'dataset.md');
    expect(delegated).toMatchObject({ botId: 'research', taskId: parent.id });
    const message = app.store.messages
      .listByTask(parent.id)
      .find((entry) => entry.kind === 'deliverable');
    expect(message?.botId).toBe('expert');
    expect(message?.meta).toMatchObject({
      sourceBotId: 'research',
      sourceBotName: '研究员',
      delegated: true,
    });
  });

  it('caps one task at 50 files and reports the overflow in meta', async () => {
    const dataDir = await tempDir('chives-deliv-cap-');
    const script: FakeStep[] = [];
    for (let index = 0; index < 52; index += 1) {
      script.push({ type: 'write', path: `files/${index}.png`, content: String(index) });
    }
    const { app, baseUrl } = await startApp(dataDir, { script });
    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 'many' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    expect(app.store.deliverables.countByTask(accepted.taskId)).toBe(50);
    const message = app.store.messages
      .listByTask(accepted.taskId)
      .find((entry) => entry.kind === 'deliverable');
    expect(message?.meta?.['overflow']).toBe(2);
    expect((message?.meta?.['deliverableIds'] as string[]).length).toBe(50);
  });

  it('publishes deliverable.created over SSE before the timeline message', async () => {
    const dataDir = await tempDir('chives-deliv-sse-');
    const { app, baseUrl } = await startApp(dataDir, {
      script: [
        { type: 'write', path: 'report.md', content: 'hi' },
        { type: 'message', text: 'ok' },
      ],
    });
    const controller = new AbortController();
    const response = await fetch(`${baseUrl}/api/events`, { signal: controller.signal });
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
          // aborted
        }
      })();
    }
    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: 'sse' }),
      })
    ).json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
    await waitFor(() =>
      events.some(
        (event) => event.type === 'deliverable.created' && event.taskId === accepted.taskId,
      ),
    );
    controller.abort();

    const created = events.find((event) => event.type === 'deliverable.created');
    expect(created).toBeDefined();
    const messageIndex = events.findIndex(
      (event) =>
        event.type === 'message.created' &&
        event.message.kind === 'deliverable',
    );
    const createdIndex = events.findIndex((event) => event.type === 'deliverable.created');
    expect(createdIndex).toBeGreaterThan(-1);
    expect(messageIndex).toBeGreaterThan(createdIndex);
  });
});
