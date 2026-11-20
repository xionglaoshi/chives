import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { afterEach, describe, expect, it } from 'vitest';

import {
  MAX_WAIT_SECONDS,
  CHIVES_TOOLS,
  ChivesClient,
  WATCH_DISABLED_MESSAGE,
  callTool,
  clampWaitSeconds,
  createChivesMcpServer,
  isToolEnabled,
  toolsForFeatures,
} from '../src/index.js';

interface Captured {
  method: string;
  url: string;
  authorization: string | undefined;
  body: Record<string, unknown>;
}

interface FakeChives {
  url: string;
  requests: Captured[];
  close: () => Promise<void>;
}

const servers: FakeChives[] = [];

async function readBody(request: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

async function fakeChives(
  handler: (request: IncomingMessage, response: ServerResponse, body: unknown) => void,
): Promise<FakeChives> {
  const requests: Captured[] = [];
  const server = createServer((request, response) => {
    void (async () => {
      const raw = await readBody(request);
      const body = raw === '' ? {} : (JSON.parse(raw) as Record<string, unknown>);
      requests.push({
        method: request.method ?? '',
        url: request.url ?? '',
        authorization: request.headers.authorization,
        body,
      });
      handler(request, response, body);
    })();
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;
  const fake: FakeChives = {
    url: `http://127.0.0.1:${port}`,
    requests,
    close: async () => {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
  servers.push(fake);
  return fake;
}

function json(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'content-type': 'application/json' });
  response.end(JSON.stringify(body));
}

afterEach(async () => {
  for (const server of servers.splice(0)) await server.close();
});

describe('MCP tool catalog', () => {
  it('registers the built-in tools and explains the automatic follow-up', () => {
    expect(CHIVES_TOOLS.map((tool) => tool.name)).toEqual([
      'delegate',
      'delegate_wait',
      'timeline_search',
      'memory_read',
      'routine_create',
      'routine_list',
      'routine_delete',
      'memory_write',
      'watch_plan_create',
      'watch_plan_update',
      'watch_plan_delete',
      'watch_plan_list',
      'notify_user',
    ]);
    const delegate = CHIVES_TOOLS.find((tool) => tool.name === 'delegate');
    expect(delegate?.description).toContain('report_back=true');
    expect(delegate?.description).toContain('自动唤醒');
    expect(delegate?.description).toContain('不要用 delegate_wait 原地等待');
    const wait = CHIVES_TOOLS.find((tool) => tool.name === 'delegate_wait');
    expect(wait?.description).toContain('一般不需要');
    expect(wait?.description).toContain('自动唤醒');
    const reportBack = delegate?.inputSchema?.['properties'] as
      | Record<string, { type?: string }>
      | undefined;
    expect(reportBack?.['report_back']?.type).toBe('boolean');
  });

  it('clamps wait_seconds to 0..40 and defaults to 40', () => {
    expect(clampWaitSeconds(undefined)).toBe(MAX_WAIT_SECONDS);
    expect(clampWaitSeconds(999)).toBe(MAX_WAIT_SECONDS);
    expect(clampWaitSeconds(-3)).toBe(0);
    expect(clampWaitSeconds(3.9)).toBe(3);
    expect(clampWaitSeconds('12')).toBe(12);
    expect(clampWaitSeconds('nope')).toBe(MAX_WAIT_SECONDS);
  });
});

describe('CHIVES_FEATURES filtering', () => {
  it('hides watch tools unless the watches feature is present', () => {
    const all = toolsForFeatures(['watches']).map((tool) => tool.name);
    const without = toolsForFeatures([]).map((tool) => tool.name);
    expect(all).toContain('watch_plan_create');
    expect(all).toContain('watch_plan_list');
    expect(without).not.toContain('watch_plan_create');
    expect(without).not.toContain('watch_plan_update');
    expect(without).not.toContain('watch_plan_delete');
    expect(without).not.toContain('watch_plan_list');
    expect(without).toContain('delegate');
    expect(isToolEnabled('watch_plan_create', [])).toBe(false);
    expect(isToolEnabled('watch_plan_create', ['watches'])).toBe(true);
  });

  it('rejects a call to a filtered tool with the Chinese capability error', async () => {
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
    const server = createChivesMcpServer({} as never, { features: [] });
    await server.connect(serverTransport);
    const client = new Client({ name: 'test', version: '1.0.0' });
    await client.connect(clientTransport);
    try {
      const listed = await client.listTools();
      expect(listed.tools.map((tool) => tool.name)).not.toContain('watch_plan_list');
      const result = await client.callTool({ name: 'watch_plan_list', arguments: {} });
      expect(result.isError).toBe(true);
      const content = result.content as Array<{ type: string; text?: string }>;
      expect(JSON.parse(content[0]?.text ?? '{}')).toEqual({
        error: 'forbidden',
        message: WATCH_DISABLED_MESSAGE,
      });
      expect(WATCH_DISABLED_MESSAGE).toBe('这个 bot 没有盯盘能力');
    } finally {
      await client.close();
      await server.close();
    }
  });
});

describe('ChivesClient', () => {
  it('posts delegate with the bearer token and a capped wait', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, { id: 'child-1', bot: 'data-prep', status: 'running', elapsed_s: 0 });
    });
    const client = new ChivesClient({ api: `${fake.url}/`, token: 'tok-1' });
    const result = await callTool(client, 'delegate', {
      bot: 'data-prep',
      brief: '取三表',
      wait_seconds: 999,
    });

    expect(result.isError).toBe(false);
    expect(result.value).toEqual({ id: 'child-1', bot: 'data-prep', status: 'running', elapsed_s: 0 });
    expect(fake.requests).toHaveLength(1);
    expect(fake.requests[0]?.method).toBe('POST');
    expect(fake.requests[0]?.url).toBe('/api/internal/delegations');
    expect(fake.requests[0]?.authorization).toBe('Bearer tok-1');
    expect(fake.requests[0]?.body).toEqual({
      bot: 'data-prep',
      brief: '取三表',
      wait_seconds: 40,
      report_back: true,
      timeout_minutes: 20,
    });
  });

  it('passes report_back=false through for an inline wait', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, { id: 'child-1', bot: 'data-prep', status: 'done', elapsed_s: 1.2 });
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok-1' });
    const result = await callTool(client, 'delegate', {
      bot: 'data-prep',
      brief: '取三表',
      report_back: false,
      wait_seconds: 999,
    });

    expect(result.isError).toBe(false);
    expect(fake.requests[0]?.body).toEqual({
      bot: 'data-prep',
      brief: '取三表',
      wait_seconds: 40,
      report_back: false,
      timeout_minutes: 20,
    });
  });

  it('posts delegate_wait ids/mode and passes the server result through', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, [
        { id: 'child-1', bot: 'data-prep', status: 'done', result: 'ok', elapsed_s: 1.2 },
      ]);
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok-2' });
    const result = await callTool(client, 'delegate_wait', {
      ids: ['child-1'],
      mode: 'any',
      wait_seconds: 5,
    });

    expect(result.value).toEqual([
      { id: 'child-1', bot: 'data-prep', status: 'done', result: 'ok', elapsed_s: 1.2 },
    ]);
    expect(fake.requests[0]?.url).toBe('/api/internal/delegations/wait');
    expect(fake.requests[0]?.body).toEqual({
      ids: ['child-1'],
      mode: 'any',
      wait_seconds: 5,
    });
  });

  it('posts timeline_search with query, clamped limit, and task_id', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, { groups: [], truncated: false });
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok-3' });
    expect(
      (await callTool(client, 'timeline_search', { query: '茅台', limit: 99, task_id: 't-1' }))
        .value,
    ).toEqual({ groups: [], truncated: false });
    expect(fake.requests[0]?.url).toBe('/api/internal/timeline/search');
    expect(fake.requests[0]?.body).toEqual({ query: '茅台', limit: 10, task_id: 't-1' });

    await callTool(client, 'timeline_search', { query: '茅台' });
    expect(fake.requests[1]?.body).toEqual({ query: '茅台' });
    expect((await callTool(client, 'timeline_search', { query: '' })).value).toMatchObject({
      error: 'invalid_arguments',
    });
    expect(
      (await callTool(client, 'timeline_search', { query: '茅台', limit: 'many' })).value,
    ).toMatchObject({ error: 'invalid_arguments' });
  });

  it('routes memory reads and writes with the evidence contract', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, { ok: true, slug: 'm-1' });
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok-3' });
    await callTool(client, 'memory_read', { topic: '偏好' });
    await callTool(client, 'memory_write', {
      title: '偏好',
      body: '偏价值',
      kind: 'preference',
      evidence: '以后多看价值股',
      expires_in_days: 30,
    });
    expect(fake.requests.map((request) => request.url)).toEqual([
      '/api/internal/memory/read',
      '/api/internal/memory/write',
    ]);
    expect(fake.requests[1]?.body).toEqual({
      title: '偏好',
      body: '偏价值',
      kind: 'preference',
      evidence: '以后多看价值股',
      expires_in_days: 30,
    });
    expect(
      (await callTool(client, 'memory_write', {
        title: '偏好',
        body: '偏价值',
        kind: 'unknown',
        evidence: '以后多看价值股',
      })).value,
    ).toMatchObject({ error: 'invalid_arguments' });
    expect(
      (await callTool(client, 'memory_write', { title: '偏好', body: '偏价值' })).value,
    ).toMatchObject({ error: 'invalid_arguments' });
    expect(fake.requests).toHaveLength(2);
  });

  it('creates, lists and deletes routines through the internal API', async () => {
    const fake = await fakeChives((request, response) => {
      if (request.url === '/api/internal/routines/list') {
        json(response, 200, { routines: [{ id: 'user:1', enabled: false }] });
        return;
      }
      if (request.url === '/api/internal/routines/delete') {
        json(response, 200, { ok: true, id: 'user:1' });
        return;
      }
      json(response, 200, { ok: true, routine: { id: 'user:1', enabled: false }, messageId: 'm-1' });
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok-r' });
    const created = await callTool(client, 'routine_create', {
      title: '盘前简报',
      schedule: { cron: '30 8 * * 1-5', tz: 'Asia/Shanghai' },
      prompt: '按 morning-note 出简报',
      trading_days_only: true,
    });
    expect(created.isError).toBe(false);
    expect(created.value).toMatchObject({ ok: true, messageId: 'm-1' });
    expect(fake.requests[0]?.url).toBe('/api/internal/routines/create');
    expect(fake.requests[0]?.body).toEqual({
      title: '盘前简报',
      schedule: { cron: '30 8 * * 1-5', tz: 'Asia/Shanghai' },
      prompt: '按 morning-note 出简报',
      trading_days_only: true,
    });

    expect((await callTool(client, 'routine_list', {})).value).toEqual({
      routines: [{ id: 'user:1', enabled: false }],
    });
    expect(fake.requests[1]?.url).toBe('/api/internal/routines/list');

    expect((await callTool(client, 'routine_delete', { id: 'user:1' })).value).toEqual({
      ok: true,
      id: 'user:1',
    });
    expect(fake.requests[2]?.body).toEqual({ id: 'user:1' });

    expect(
      (await callTool(client, 'routine_create', { title: 'x', schedule: {}, prompt: '' })).value,
    ).toMatchObject({ error: 'invalid_arguments' });
    expect(
      (await callTool(client, 'routine_create', { title: 'x', schedule: 'daily', prompt: 'y' })).value,
    ).toMatchObject({ error: 'invalid_arguments' });
    expect(fake.requests).toHaveLength(3);
  });

  it('passes an HTTP error body through unchanged', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 401, { error: { code: 'unauthorized', message: 'valid session token required' } });
    });
    const client = new ChivesClient({ api: fake.url, token: 'bad' });
    const result = await callTool(client, 'delegate', { bot: 'data-prep', brief: 'x' });
    expect(result.isError).toBe(false);
    expect(result.value).toEqual({
      error: 'unauthorized',
      message: 'valid session token required',
    });
  });

  it('returns a timeout error instead of hanging past the 45 second budget', async () => {
    const fake = await fakeChives(() => {
      // Deliberately never answer.
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok', requestTimeoutMs: 30 });
    const started = Date.now();
    const result = await callTool(client, 'delegate', { bot: 'data-prep', brief: 'slow' });
    expect(result.value).toMatchObject({ error: 'timeout' });
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it('refuses to send without CHIVES_API or CHIVES_SESSION_TOKEN', async () => {
    const noToken = new ChivesClient({ api: 'http://127.0.0.1:1', token: '' });
    expect((await callTool(noToken, 'delegate', { bot: 'b', brief: 'x' })).value).toMatchObject({
      error: 'missing_token',
    });
    const noApi = new ChivesClient({ api: '', token: 't' });
    expect((await callTool(noApi, 'delegate_wait', { ids: ['a'] })).value).toMatchObject({
      error: 'missing_api',
    });
  });
});


describe('watch plan and notify tools', () => {
  it('creates a watch with the server-side snake_case payload', async () => {
    const fake = await fakeChives((_request, response) => {
      json(response, 200, {
        ok: true,
        id: 'abc',
        status: 'active',
        sync_error: null,
        description: '柳工 000528.SZ：跌破 7.71 时唤醒投资专家，至 11-22',
      });
    });
    const client = new ChivesClient({ api: fake.url, token: 'tok' });
    const result = await callTool(client, 'watch_plan_create', {
      code: '000528.SZ',
      label: '柳工回踩',
      when: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
      give_up: [{ type: 'pct_change', direction: 'down', threshold_pct: 5 }],
      market: [{ type: 'regime', values: ['strong', 'neutral'] }],
      match: 'all',
      expires_in_days: 7,
      note: '跌破支撑',
      repeat: true,
    });
    expect(result.isError).toBe(false);
    expect(fake.requests[0]?.url).toBe('/api/internal/watch-plans/create');
    expect(fake.requests[0]?.body).toMatchObject({
      code: '000528.SZ',
      label: '柳工回踩',
      when: [{ type: 'price_cross', direction: 'down', level: 7.71 }],
      give_up: [{ type: 'pct_change', direction: 'down', threshold_pct: 5 }],
      market: [{ type: 'regime', values: ['strong', 'neutral'] }],
      match: 'all',
      expires_in_days: 7,
      note: '跌破支撑',
      repeat: true,
    });
  });

  it('updates, deletes and lists watches', async () => {
    const fake = await fakeChives((_request, response) => json(response, 200, { ok: true }));
    const client = new ChivesClient({ api: fake.url, token: 'tok' });
    await callTool(client, 'watch_plan_update', {
      id: 'abc',
      when: [{ type: 'price_cross', direction: 'up', level: 8.69 }],
      expires_in_days: 3,
    });
    await callTool(client, 'watch_plan_delete', { id: 'abc' });
    await callTool(client, 'watch_plan_list', { status: 'all' });
    expect(fake.requests.map((request) => request.url)).toEqual([
      '/api/internal/watch-plans/update',
      '/api/internal/watch-plans/delete',
      '/api/internal/watch-plans/list',
    ]);
    expect(fake.requests[0]?.body).toMatchObject({
      id: 'abc',
      when: [{ type: 'price_cross', direction: 'up', level: 8.69 }],
      expires_in_days: 3,
    });
    expect(fake.requests[2]?.body).toEqual({ status: 'all' });
  });

  it('validates watch arguments before any HTTP call', async () => {
    const fake = await fakeChives((_request, response) => json(response, 200, {}));
    const client = new ChivesClient({ api: fake.url, token: 'tok' });
    const cases: Array<[string, Record<string, unknown>]> = [
      ['watch_plan_create', { label: 'x', when: [] }],
      ['watch_plan_create', { code: 'x', label: 'x', when: [] }],
      ['watch_plan_create', { code: 'x', label: 'x', when: [{ type: 'price_cross' }], match: 'or' }],
      ['watch_plan_create', { code: 'x', label: 'x', when: [{ type: 'price_cross' }], expires_in_days: 0 }],
      ['watch_plan_update', { id: 'abc', match: 'or' }],
      ['watch_plan_update', { id: 'abc', when: 'nope' }],
      ['watch_plan_delete', {}],
      ['watch_plan_list', { status: 'cancelled' }],
      ['notify_user', { title: 'x', body: 'y', level: 'loud' }],
      ['notify_user', { title: 'x' }],
    ];
    for (const [name, args] of cases) {
      const result = await callTool(client, name, args);
      expect(result.isError).toBe(true);
    }
    expect(fake.requests).toHaveLength(0);
  });

  it('sends notify_user and describes that watches never place orders', async () => {
    const fake = await fakeChives((_request, response) =>
      json(response, 200, { ok: true, notification: { id: 'n1' } }),
    );
    const client = new ChivesClient({ api: fake.url, token: 'tok' });
    const result = await callTool(client, 'notify_user', {
      title: '柳工放量',
      body: '现价 8.62，量比 2.1，10:31',
    });
    expect(result.isError).toBe(false);
    expect(fake.requests[0]?.url).toBe('/api/internal/notifications/notify');
    expect(fake.requests[0]?.body).toEqual({
      title: '柳工放量',
      body: '现价 8.62，量比 2.1，10:31',
      level: 'important',
    });
    const create = CHIVES_TOOLS.find((tool) => tool.name === 'watch_plan_create');
    expect(create?.description).toContain('绝不下单');
    const notify = CHIVES_TOOLS.find((tool) => tool.name === 'notify_user');
    expect(notify?.description).toContain('每小时最多 6 条');
  });
});

describe('delegate timeout_minutes', () => {
  it('documents a 1–60 minute timeout with a default of 20', () => {
    const delegate = CHIVES_TOOLS.find((tool) => tool.name === 'delegate');
    const props = delegate?.inputSchema?.['properties'] as Record<string, Record<string, unknown>>;
    expect(props['timeout_minutes']).toMatchObject({ type: 'integer', minimum: 1, maximum: 60 });
    expect(String(props['timeout_minutes']?.['description'])).toContain('默认 20');
  });

  it('passes the timeout to the server, defaults to 20 and rejects out-of-range values', async () => {
    const calls: unknown[][] = [];
    const client = {
      delegate: async (...args: unknown[]) => {
        calls.push(args);
        return { id: 'c1', status: 'running' };
      },
    } as unknown as Parameters<typeof callTool>[0];
    await callTool(client, 'delegate', { bot: 'research', brief: 'x', timeout_minutes: 35 });
    await callTool(client, 'delegate', { bot: 'research', brief: 'x' });
    expect(calls.map((args) => args[4])).toEqual([35, 20]);
    const bad = await callTool(client, 'delegate', { bot: 'research', brief: 'x', timeout_minutes: 90 });
    expect(bad.isError).toBe(true);
    expect(calls).toHaveLength(2);
  });
});
