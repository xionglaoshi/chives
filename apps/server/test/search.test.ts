import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import { FakeDriver } from '../src/harness/fake.js';
import { SearchService, tokenizeQuery } from '../src/search/index.js';
import { Store, resolveRootTask } from '../src/store/index.js';
import { backfillSearchIndex } from '../src/store/search.js';
import { closeServer, listen, makeRegistry, testConfig } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

interface Fixture {
  store: Store;
  service: SearchService;
  ids: { root: string; child: string; other: string; newer: string };
}

async function fixture(): Promise<Fixture> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-search-'));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const store = Store.open(directory);
  cleanups.push(() => Promise.resolve(store.close()));
  const registry = makeRegistry();
  const service = new SearchService({ store, registry });

  const root = store.tasks.create({
    botId: 'expert',
    title: '贵州茅台三季报点评',
    startedAt: '2026-11-16T07:30:00.000Z',
  });
  store.messages.append({
    id: 'm-user',
    botId: 'expert',
    taskId: root.id,
    role: 'user',
    kind: 'text',
    content: '看下贵州茅台三季报',
    createdAt: '2026-11-16T07:30:00.000Z',
  });
  store.messages.append({
    id: 'm-bot',
    botId: 'expert',
    taskId: root.id,
    role: 'bot',
    kind: 'text',
    content: '结论：可以持有；茅台估值为近三年中位。',
    createdAt: '2026-11-16T07:42:00.000Z',
  });
  store.summaries.upsert({
    taskId: root.id,
    title: '贵州茅台三季报点评',
    conclusion: '可以持有，加仓没有明显的赔率优势。',
    keyNumbers: [
      { label: '市盈率', value: '21.84 倍', source: '东方财富', asOf: '2026-11-13' },
    ],
    deliverables: ['茅台_点评.md'],
    openQuestions: ['四季度批价走势没有可靠数据'],
    symbols: [{ code: '600519.SH', name: '贵州茅台' }],
    createdAt: '2026-11-16T07:45:00.000Z',
    source: 'model',
  });
  store.deliverables.upsert({
    id: 'd-1',
    taskId: root.id,
    botId: 'expert',
    path: '茅台_点评.md',
    kind: 'markdown',
    size: 100,
    createdAt: '2026-11-16T07:44:00.000Z',
  });

  const child = store.tasks.create({
    botId: 'research',
    title: '白酒行业政策梳理',
    startedAt: '2026-11-14T02:00:00.000Z',
    parentTaskId: root.id,
    depth: 1,
    delegated: true,
    brief: '梳理白酒政策',
  });
  store.messages.append({
    id: 'm-child',
    botId: 'research',
    taskId: child.id,
    role: 'bot',
    kind: 'text',
    content: '委派结论：政策里茅台受影响最小。',
    createdAt: '2026-11-14T02:10:00.000Z',
  });

  const other = store.tasks.create({
    botId: 'equity-analyst',
    title: '别的 bot 的茅台记录',
    startedAt: '2026-11-16T08:00:00.000Z',
  });
  store.messages.append({
    id: 'm-other',
    botId: 'equity-analyst',
    taskId: other.id,
    role: 'user',
    kind: 'text',
    content: '别的 bot 也提到茅台',
    createdAt: '2026-11-16T08:00:00.000Z',
  });

  const newer = store.tasks.create({
    botId: 'expert',
    title: '宁德时代持仓体检',
    startedAt: '2026-11-17T01:00:00.000Z',
  });
  store.messages.append({
    id: 'm-newer',
    botId: 'expert',
    taskId: newer.id,
    role: 'user',
    kind: 'text',
    content: '持仓里茅台占两成，宁德时代占三成。',
    createdAt: '2026-11-17T01:00:00.000Z',
  });

  return { store, service, ids: { root: root.id, child: child.id, other: other.id, newer: newer.id } };
}

describe('timeline search service', () => {
  it('opens specific messages across visible conversations with short and indexed keywords', async () => {
    const { service } = await fixture();
    const hits = service.conversationMessages('茅台',0).hits;
    expect(hits).toContainEqual(expect.objectContaining({botId:'equity-analyst',messageId:'m-other'}));
    expect(hits).toContainEqual(expect.objectContaining({botId:'expert',messageId:'m-user'}));
    expect(hits).not.toContainEqual(expect.objectContaining({messageId:'m-child'}));
    expect(service.conversationMessages('贵州茅台',0).hits).toContainEqual(
      expect.objectContaining({messageId:'m-user',snippet:expect.stringContaining('贵州茅台')}));
    expect(service.conversationMessages('%',0).hits).toHaveLength(0);
    expect(() => service.conversationMessages('茅台',-1)).toThrow();
  });

  it('indexes with trigram for 3+ characters and LIKE for short terms', async () => {
    const { service } = await fixture();
    const trigram = service.search('expert', '贵州茅台');
    const like = service.search('expert', '茅台');
    expect(trigram.groups.some((group) => group.title === '贵州茅台三季报点评')).toBe(true);
    expect(trigram.totalHits).toBeGreaterThan(0);
    expect(like.totalHits).toBeGreaterThan(0);
    expect(like.groups.some((group) => group.title === '贵州茅台三季报点评')).toBe(true);
  });

  it('intersects multiple whitespace-separated terms', async () => {
    const { service } = await fixture();
    expect(service.search('expert', '宁德时代 三季报').groups).toHaveLength(0);
    const both = service.search('expert', '茅台 宁德时代');
    expect(both.groups.map((group) => group.taskId)).toHaveLength(1);
    expect(both.groups[0]?.taskId).not.toBeUndefined();
    const ok = service.search('expert', '贵州茅台 三季报');
    expect(ok.groups).toHaveLength(1);
    expect(ok.groups[0]?.taskId).toBeTruthy();
  });

  it('never lets FTS syntax characters reach SQL as operators', async () => {
    const { service } = await fixture();
    for (const query of ['"', '*', '(', ')', 'NEAR', '"茅台"', 'a*b (c)']) {
      expect(() => service.search('expert', query)).not.toThrow();
    }
  });

  it('scopes results to the root bot timeline, including delegated children', async () => {
    const { service, ids } = await fixture();
    const expert = service.search('expert', '茅台');
    expect(expert.groups.map((group) => group.taskId)).toContain(ids.root);
    expect(expert.groups.map((group) => group.taskId)).not.toContain(ids.other);
    expect(expert.groups.map((group) => group.taskId)).not.toContain(ids.child);
    const rootGroup = expert.groups.find((group) => group.taskId === ids.root);
    expect(rootGroup?.snippets.some((snippet) => snippet.text.includes('委派结论'))).toBe(true);
    expect(rootGroup?.taskIds).toContain(ids.child);

    const research = service.search('research', '茅台');
    expect(research.groups.map((group) => group.taskId)).not.toContain(ids.root);
    expect(research.groups.map((group) => group.taskId)).not.toContain(ids.child);
  });

  it('groups by task, orders by latest activity, and returns snippet ranges', async () => {
    const { service, ids } = await fixture();
    const result = service.search('expert', '茅台');
    expect(result.groups[0]?.taskId).toBe(ids.newer);
    expect(result.groups[1]?.taskId).toBe(ids.root);
    const root = result.groups.find((group) => group.taskId === ids.root);
    expect(root?.summary?.conclusion).toContain('可以持有');
    expect(root?.deliverables.map((entry) => entry.path)).toContain('茅台_点评.md');
    expect(root?.steps).toBe(0);
    for (const group of result.groups) {
      for (const snippet of group.snippets) {
        expect(snippet.ranges.length).toBeGreaterThan(0);
        for (const range of snippet.ranges) {
          expect(snippet.text.slice(range.start, range.end).toLowerCase()).toBe('茅台');
        }
      }
    }
  });

  it('tokenizes whitespace and deduplicates terms', () => {
    expect(tokenizeQuery('  茅台   贵州茅台 茅台 ')).toEqual(['茅台', '贵州茅台']);
  });

  it('backfills messages that predate the search index', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'chives-search-backfill-'));
    cleanups.push(() => rm(directory, { recursive: true, force: true }));
    const store = Store.open(directory);
    cleanups.push(() => Promise.resolve(store.close()));
    const task = store.tasks.create({
      botId: 'expert',
      title: '旧任务',
      startedAt: '2026-11-01T01:00:00.000Z',
    });
    store.db
      .prepare(
        `INSERT INTO messages (id, bot_id, task_id, role, kind, content, meta, created_at, seq)
         VALUES (?, ?, ?, 'user', 'text', ?, NULL, ?, ?)`,
      )
      .run('legacy-m', 'expert', task.id, '很久以前的贵州茅台记录', '2026-11-01T01:00:00.000Z', 1);
    expect(store.search.count()).toBe(0);
    backfillSearchIndex(store.db);
    expect(store.search.count()).toBe(1);
    expect(resolveRootTask(store.db, task.id)?.botId).toBe('expert');
    const service = new SearchService({ store, registry: makeRegistry() });
    expect(service.search('expert', '贵州茅台').totalHits).toBe(1);
  });
});

interface Harness {
  app: ChivesApp;
  baseUrl: string;
}

async function startApp(): Promise<Harness> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-search-api-'));
  cleanups.push(() => rm(directory, { recursive: true, force: true }));
  const app = createApp({ config: testConfig(directory), driver: new FakeDriver() });
  const baseUrl = await listen(app.server);
  cleanups.push(async () => {
    await closeServer(app.server);
    await app.close();
  });
  return { app, baseUrl };
}

function makeTask(app: ChivesApp, botId = 'expert', title = '贵州茅台三季报点评'): string {
  const task = app.store.tasks.create({
    botId,
    title,
    startedAt: '2026-11-16T07:30:00.000Z',
  });
  app.store.messages.append({
    id: `m-${task.id}`,
    botId,
    taskId: task.id,
    role: 'user',
    kind: 'text',
    content: '看下贵州茅台三季报',
    createdAt: '2026-11-16T07:30:00.000Z',
  });
  return task.id;
}

async function internalSearch(
  baseUrl: string,
  token: string | null,
  body: Record<string, unknown>,
): Promise<Response> {
  return fetch(`${baseUrl}/api/internal/timeline/search`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(token === null ? {} : { authorization: `Bearer ${token}` }),
    },
    body: JSON.stringify(body),
  });
}

describe('timeline search HTTP and internal API', () => {
  it('requires a valid session token on the internal route', async () => {
    const { baseUrl } = await startApp();
    const denied = await internalSearch(baseUrl, null, { query: '茅台' });
    expect(denied.status).toBe(401);
    const bad = await internalSearch(baseUrl, 'not-a-token', { query: '茅台' });
    expect(bad.status).toBe(401);
  });

  it('serves the UI search endpoint with q/limit validation', async () => {
    const { app, baseUrl } = await startApp();
    makeTask(app);
    const ok = await fetch(`${baseUrl}/api/bots/expert/search?q=${encodeURIComponent('茅台')}`);
    expect(ok.status).toBe(200);
    const payload = (await ok.json()) as { totalGroups: number; groups: unknown[] };
    expect(payload.totalGroups).toBe(1);
    expect(payload.groups).toHaveLength(1);
    expect((await fetch(`${baseUrl}/api/bots/expert/search`)).status).toBe(400);
    expect(
      (await fetch(`${baseUrl}/api/bots/expert/search?q=茅台&limit=0`)).status,
    ).toBe(400);
  });

  it('returns the compact group JSON, task detail mode, and enforces both length caps', async () => {
    const { app, baseUrl } = await startApp();
    const taskId = makeTask(app);
    for (let index = 0; index < 300; index += 1) {
      app.store.messages.append({
        id: `long-${index}`,
        botId: 'expert',
        taskId,
        role: 'bot',
        kind: 'text',
        content: `第${index}条：茅台与贵州茅台的记录 ${'很长的内容'.repeat(40)}`,
        createdAt: `2026-11-16T08:${String(index % 60).padStart(2, '0')}:00.000Z`,
      });
    }
    app.store.summaries.upsert({
      taskId,
      title: '贵州茅台三季报点评',
      conclusion: '可以持有。',
      keyNumbers: [{ label: '市盈率', value: '21.84 倍', source: '东方财富', asOf: '2026-11-13' }],
      deliverables: [],
      openQuestions: ['四季度批价'],
      symbols: [],
      createdAt: '2026-11-16T09:00:00.000Z',
      source: 'model',
    });
    const auth = app.sessions.issue({ botId: 'expert', taskId, depth: 0 });

    const groupsResponse = await internalSearch(baseUrl, auth, { query: '茅台', limit: 10 });
    expect(groupsResponse.status).toBe(200);
    const groupsText = await groupsResponse.text();
    expect(groupsText.length).toBeLessThanOrEqual(8_000);
    const groups = JSON.parse(groupsText) as {
      groups: Array<{ task_id: string; title: string; key_numbers: unknown[]; snippets: string[] }>;
      truncated: boolean;
    };
    expect(groups.groups[0]?.task_id).toBe(taskId);
    expect(groups.groups[0]?.title).toBe('贵州茅台三季报点评');
    expect(groups.groups[0]?.key_numbers).toHaveLength(1);

    const detailResponse = await internalSearch(baseUrl, auth, {
      query: '茅台',
      task_id: taskId,
    });
    expect(detailResponse.status).toBe(200);
    const detailText = await detailResponse.text();
    expect(detailText.length).toBeLessThanOrEqual(12_000);
    const detail = JSON.parse(detailText) as {
      task: { task_id: string };
      messages: Array<{ role: string; text: string }>;
      truncated: boolean;
    };
    expect(detail.task.task_id).toBe(taskId);
    expect(detail.messages.length).toBeGreaterThan(0);
    expect(detail.truncated).toBe(true);
  });

  it('refuses a task_id from another bot timeline', async () => {
    const { app, baseUrl } = await startApp();
    const taskId = makeTask(app);
    const otherTask = makeTask(app, 'equity-analyst', '别的任务');
    const auth = app.sessions.issue({ botId: 'expert', taskId, depth: 0 });
    const response = await internalSearch(baseUrl, auth, {
      query: '茅台',
      task_id: otherTask,
    });
    expect(response.status).toBe(403);
  });

  it('reopens a closed task and closes the currently unclosed one', async () => {
    const { app, baseUrl } = await startApp();
    const old = app.store.tasks.create({
      botId: 'expert',
      title: '旧任务',
      startedAt: '2026-11-10T01:00:00.000Z',
    });
    app.store.tasks.finish(old.id, 'done', '2026-11-10T02:00:00.000Z');
    app.store.tasks.markClosed(old.id, '2026-11-10T02:10:00.000Z');
    const current = app.store.tasks.create({
      botId: 'expert',
      title: '当前任务',
      startedAt: '2026-11-16T01:00:00.000Z',
    });
    app.store.tasks.finish(current.id, 'done', '2026-11-16T02:00:00.000Z');

    const response = await fetch(`${baseUrl}/api/tasks/${old.id}/reopen`, { method: 'POST' });
    expect(response.status).toBe(200);
    const reopened = (await response.json()) as { id: string; closedAt: string | null };
    expect(reopened.id).toBe(old.id);
    expect(reopened.closedAt).toBeNull();
    expect(app.store.tasks.get(old.id)?.closedAt).toBeNull();
    expect(app.store.tasks.get(old.id)?.reopenedAt).not.toBeNull();
    expect(app.store.tasks.get(current.id)?.closedAt).not.toBeNull();
    expect(app.store.tasks.latestForBot('expert')?.id).toBe(old.id);

    const decision = await app.orchestrator.segmentation.decide(
      'expert',
      '接着说茅台',
      new Date('2026-11-20T00:00:00.000Z'),
    );
    expect(decision.kind).toBe('continue');
    expect(decision.previous?.id).toBe(old.id);
    expect(app.store.tasks.restart(old.id).reopenedAt).toBeNull();

    const missing = await fetch(`${baseUrl}/api/tasks/nope/reopen`, { method: 'POST' });
    expect(missing.status).toBe(404);

    const again = app.store.tasks.create({
      botId: 'expert',
      title: '再开一次',
      startedAt: '2026-11-12T01:00:00.000Z',
    });
    app.store.tasks.finish(again.id, 'done', '2026-11-12T02:00:00.000Z');
    app.store.tasks.markClosed(again.id, '2026-11-12T02:10:00.000Z');
    await fetch(`${baseUrl}/api/tasks/${again.id}/reopen`, { method: 'POST' });
    const cancelled = await fetch(`${baseUrl}/api/tasks/${again.id}/reopen/cancel`, {
      method: 'POST',
    });
    expect(cancelled.status).toBe(200);
    const cancelledTask = (await cancelled.json()) as {
      closedAt: string | null;
      reopenedAt?: string | null;
    };
    expect(cancelledTask.closedAt).not.toBeNull();
    expect(app.store.tasks.get(again.id)?.reopenedAt).toBeNull();
  });
});
