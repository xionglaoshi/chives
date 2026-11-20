import { mkdirSync, symlinkSync, utimesSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type {
  BotProfile,
  BotSummary,
  ServerEvent,
  WorkspaceFileList,
} from '../src/api/protocol.js';
import {
  closeServer,
  listen,
  testConfig,
  waitFor,
} from './support.js';

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

interface StartOptions {
  revealExec?: (
    file: string,
    args: readonly string[],
    callback: (error: Error | null) => void,
  ) => void;
  platform?: NodeJS.Platform;
}

async function startApp(
  dataDir: string,
  options: StartOptions = {},
): Promise<{ app: ChivesApp; baseUrl: string }> {
  const config = testConfig(dataDir);
  config.defaultRoute = { provider: 'deepseek', model: 'deepseek-v4.1-flash' };
  const app = createApp({
    config,
    ...(options.revealExec === undefined ? {} : { revealExec: options.revealExec }),
    ...(options.platform === undefined ? {} : { platform: options.platform }),
  });
  const baseUrl = await listen(app.server);
  const entry = { app, baseUrl };
  apps.push(entry);
  return entry;
}

async function stop(entry: { app: ChivesApp; baseUrl: string }): Promise<void> {
  const index = apps.indexOf(entry);
  if (index >= 0) apps.splice(index, 1);
  entry.app.sse.closeAll();
  await closeServer(entry.app.server);
  await entry.app.close();
}

function seedDeliverable(app: ChivesApp, botId: string, path: string): void {
  const task = app.store.tasks.create({
    botId,
    title: 'profile fixture',
    startedAt: new Date().toISOString(),
  });
  app.store.deliverables.add({
    id: `d-${botId}-${path.replaceAll('/', '-')}`,
    taskId: task.id,
    botId,
    path,
    kind: 'markdown',
    size: 4,
    createdAt: new Date().toISOString(),
  });
}

describe('bot profile API', () => {
  it('offers the entire installed catalog and preserves each expert’s selection across requests', async () => {
    const { baseUrl } = await startApp(await tempDir('chives-skill-mode-'));
    const url = baseUrl + '/api/bots/expert';
    const { options, profile } = await (await fetch(url + '/assets')).json();
    expect(options.skills).toEqual(expect.arrayContaining(['dcf-model', 'daily-review', 'investor-lenses']));
    expect(profile.skillMode).toBe('selected');
    for (const skillMode of ['all', 'selected']) {
      const saved = await fetch(url + '/assets', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...profile, skillMode, skills: ['dcf-model'] }),
      });
      expect(saved.status).toBe(200);
      const effective: BotProfile = await (await fetch(url + '/profile')).json();
      expect(effective.skills.map(skill => skill.name)).toEqual(skillMode === 'all' ? options.skills : ['dcf-model']);
    }
  });

  it('returns manifest data, skill descriptions, workspace stats, and placeholders', async () => {
    const dataDir = await tempDir('chives-profile-');
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(join(workspace, 'notes'), { recursive: true });
    writeFileSync(join(workspace, 'a.md'), 'abcd');
    writeFileSync(join(workspace, 'notes', 'b.md'), '123456');
    const { app, baseUrl } = await startApp(dataDir);
    seedDeliverable(app, 'expert', 'a.md');

    const response = await fetch(`${baseUrl}/api/bots/expert/profile`);
    expect(response.status).toBe(200);
    const profile = (await response.json()) as BotProfile;

    expect(profile.bot).toMatchObject({
      id: 'expert',
      name: '投资专家',
      modelDisplayName: 'deepseek-v4.1-flash',
      workspacePath: workspace,
    });
    expect(profile.role).toContain('默认入口');
    expect(profile.personaSummary.startsWith('你的名字是「投资专家」')).toBe(true);
    expect(profile.personaSummary).not.toContain('# 投资专家');

    const idea = profile.skills.find((skill) => skill.name === 'idea-generation');
    expect(idea?.description.startsWith('A 股选股漏斗')).toBe(true);
    expect(profile.mcp).toContain('paper_broker');
    expect(profile.tools).toEqual({ code: 'sandboxed', write: 'workspace-only' });
    expect(profile.canDelegateTo).toEqual(
      expect.arrayContaining([{ id: 'equity-analyst', name: '个股分析师' }]),
    );
    expect(profile.canDelegateTo.find((entry) => entry.id === 'research')?.name).toBe('研究员');
    expect(profile.memoryPolicy).toEqual({ user: 'read', bot: 'read-write' });
    expect(profile.tradingGuard).toBe(true);
    expect(profile.model).toBe('deepseek-v4.1-flash');
    expect(profile.workspace).toEqual({ path: workspace, fileCount: 2, totalBytes: 10 });
    expect(profile.recentDeliverables.map((entry) => entry.path)).toEqual(['a.md']);
    expect(profile.memory).toEqual({
      count: 0,
      limit: 200,
      items: [],
      available: true,
      updatedAt: null,
    });
    expect(profile.defaults).toEqual({
      name: '投资专家',
      avatar: { emblem: 'crown', tone: 'gold' },
    });
  });

  it('reflects a renamed delegate in profile and summary', async () => {
    const dataDir = await tempDir('chives-profile-delegate-');
    const { baseUrl } = await startApp(dataDir);
    const patch = await fetch(`${baseUrl}/api/bots/research`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ displayName: '小数据' }),
    });
    expect(patch.status).toBe(200);

    const profile = (await (
      await fetch(`${baseUrl}/api/bots/expert/profile`)
    ).json()) as BotProfile;
    expect(profile.canDelegateTo.find((entry) => entry.id === 'research')?.name).toBe('小数据');
  });

  it('lists one workspace directory level newest first and guards traversal', async () => {
    const dataDir = await tempDir('chives-profile-files-');
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(join(workspace, 'notes'), { recursive: true });
    writeFileSync(join(workspace, 'old.md'), 'old');
    writeFileSync(join(workspace, 'new.md'), 'new');
    writeFileSync(join(workspace, 'notes', 'nested.md'), 'nested');
    utimesSync(join(workspace, 'old.md'), new Date('2026-01-01T00:00:00Z'), new Date('2026-01-01T00:00:00Z'));
    utimesSync(join(workspace, 'new.md'), new Date('2026-02-01T00:00:00Z'), new Date('2026-02-01T00:00:00Z'));
    const { app, baseUrl } = await startApp(dataDir);
    seedDeliverable(app, 'expert', 'new.md');

    const root = (await (await fetch(`${baseUrl}/api/bots/expert/files`)).json()) as WorkspaceFileList;
    expect(root.dir).toBe('');
    expect(root.files.map((file) => file.name)).toEqual(['new.md', 'old.md']);
    expect(root.files[0]).toMatchObject({ path: 'new.md', kind: 'markdown', size: 3 });
    expect(root.files[0]?.deliverableId).not.toBeNull();

    const nested = (await (
      await fetch(`${baseUrl}/api/bots/expert/files?dir=notes`)
    ).json()) as WorkspaceFileList;
    expect(nested.dir).toBe('notes');
    expect(nested.files.map((file) => file.path)).toEqual(['notes/nested.md']);

    expect((await fetch(`${baseUrl}/api/bots/expert/files?dir=..`)).status).toBe(403);
    expect((await fetch(`${baseUrl}/api/bots/expert/files?dir=missing`)).status).toBe(404);
  });

  it('skips files whose symlink resolves outside the workspace', async () => {
    const dataDir = await tempDir('chives-profile-symlink-');
    const workspace = workspaceOf(dataDir, 'expert');
    mkdirSync(workspace, { recursive: true });
    const outside = join(dataDir, 'outside.txt');
    writeFileSync(outside, 'secret');
    symlinkSync(outside, join(workspace, 'leak.txt'));
    const { baseUrl } = await startApp(dataDir);
    const root = (await (await fetch(`${baseUrl}/api/bots/expert/files`)).json()) as WorkspaceFileList;
    expect(root.files).toEqual([]);
  });

  it('opens the workspace in Finder through the injected exec', async () => {
    const dataDir = await tempDir('chives-profile-reveal-');
    const calls: Array<{ file: string; args: readonly string[] }> = [];
    const revealExec = (
      file: string,
      args: readonly string[],
      callback: (error: Error | null) => void,
    ): void => {
      calls.push({ file, args });
      callback(null);
    };
    const { baseUrl } = await startApp(dataDir, { revealExec, platform: 'darwin' });
    const response = await fetch(`${baseUrl}/api/bots/expert/reveal`, { method: 'POST' });
    expect(response.status).toBe(200);
    expect(calls).toEqual([{ file: 'open', args: [workspaceOf(dataDir, 'expert')] }]);
  });
});

describe('PATCH /api/bots/:id', () => {
  it('saves display name and avatar, publishes bot.updated, and survives a restart', async () => {
    const dataDir = await tempDir('chives-patch-');
    const first = await startApp(dataDir);
    const events: ServerEvent[] = [];
    first.app.bus.subscribe((event) => events.push(event));

    const response = await fetch(`${first.baseUrl}/api/bots/expert`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        displayName: '  阿金  ',
        avatar: { emblem: 'px-chart-line', tone: 'jade' },
      }),
    });
    expect(response.status).toBe(200);
    const summary = (await response.json()) as BotSummary;
    expect(summary.name).toBe('阿金');
    expect(summary.avatar).toEqual({ emblem: 'px-chart-line', tone: 'jade' });
    await waitFor(() => events.some((event) => event.type === 'bot.updated'));
    const updated = events.find((event) => event.type === 'bot.updated');
    expect(updated).toMatchObject({
      botId: 'expert',
      bot: { id: 'expert', name: '阿金', avatar: { emblem: 'px-chart-line', tone: 'jade' } },
    });

    const bots = (await (await fetch(`${first.baseUrl}/api/bots`)).json()) as BotSummary[];
    expect(bots.find((bot) => bot.id === 'expert')?.name).toBe('阿金');

    await stop(first);
    const second = await startApp(dataDir);
    const after = (await (await fetch(`${second.baseUrl}/api/bots`)).json()) as BotSummary[];
    expect(after.find((bot) => bot.id === 'expert')).toMatchObject({
      name: '阿金',
      avatar: { emblem: 'px-chart-line', tone: 'jade' },
    });
  });

  it('restores manifest defaults with nulls without touching bot.yaml', async () => {
    const dataDir = await tempDir('chives-patch-default-');
    const { baseUrl } = await startApp(dataDir);
    await fetch(`${baseUrl}/api/bots/equity-analyst`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ displayName: '天平', avatar: { emblem: 'shield', tone: 'ink' } }),
    });
    const restored = await fetch(`${baseUrl}/api/bots/equity-analyst`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ displayName: null, avatar: null }),
    });
    expect(restored.status).toBe(200);
    await expect(restored.json()).resolves.toMatchObject({
      name: '个股分析师',
      avatar: { emblem: 'scale', tone: 'silver' },
    });

    const manifest = (await (
      await fetch(`${baseUrl}/api/bots/equity-analyst/profile`)
    ).json()) as BotProfile;
    expect(manifest.bot.name).toBe('个股分析师');
    expect(manifest.defaults.avatar).toEqual({ emblem: 'scale', tone: 'silver' });
  });

  it('validates name length, newlines, avatar values, and unknown fields', async () => {
    const dataDir = await tempDir('chives-patch-invalid-');
    const { baseUrl } = await startApp(dataDir);
    const patch = (body: unknown): Promise<Response> =>
      fetch(`${baseUrl}/api/bots/expert`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });

    expect((await patch({ displayName: '   ' })).status).toBe(400);
    expect((await patch({ displayName: '一二三四五六七八九十一二三' })).status).toBe(400);
    expect((await patch({ displayName: '一\n二' })).status).toBe(400);
    expect((await patch({ avatar: { emblem: 'nope', tone: 'gold' } })).status).toBe(400);
    expect((await patch({ avatar: { emblem: 'crown', tone: 'pink' } })).status).toBe(400);
    expect((await patch({ avatar: { emblem: 'crown' } })).status).toBe(400);
    expect((await patch({ displayName: '好看', extra: true })).status).toBe(400);
    expect((await patch({})).status).toBe(400);
    expect((await patch({ displayName: 3 })).status).toBe(400);

    const twelve = await patch({ displayName: '一二三四五六七八九十一二' });
    expect(twelve.status).toBe(200);
  });
});
