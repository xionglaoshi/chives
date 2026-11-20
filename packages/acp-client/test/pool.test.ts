import { afterEach, describe, expect, it } from 'vitest';

import {
  AcpProcessExitedError,
  AcpTimeoutError,
  HarnessPool,
  type CrashedEvent,
  type DraftEvent,
  type HarnessPoolOptions,
} from '../src/index.js';
import { fakeSpawnSpec, makeLog, waitFor, type LogContext } from './helpers.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

async function makePool(
  scenario: string,
  options: Partial<HarnessPoolOptions> = {},
): Promise<{ pool: HarnessPool; log: LogContext }> {
  const log = await makeLog();
  const pool = new HarnessPool({
    spawnSpec: fakeSpawnSpec({ scenario, logPath: log.logPath }),
    clientOptions: { requestTimeoutMs: 3000, closeGraceMs: 1000 },
    idleMs: 60_000,
    ...options,
  });
  cleanups.push(async () => {
    await pool.stopAll();
    await log.cleanup();
  });
  return { pool, log };
}

describe('HarnessPool', () => {
  it('restarts transparently after an unexpected exit and emits crashed', async () => {
    const { pool } = await makePool('crash');
    const crashed: CrashedEvent[] = [];
    pool.onCrashed((event) => crashed.push(event));
    const client = await pool.acquire('bot');
    const pid = client.process.pid;
    const session = await client.newSession({ cwd: '/tmp' });
    await expect(pool.prompt('bot', session.sessionId, [{ type: 'text', text: 'go' }]))
      .rejects.toBeInstanceOf(AcpProcessExitedError);
    await waitFor(() => crashed.length === 1);
    expect(crashed[0]).toMatchObject({ key: 'bot', reason: 'exit', code: 1 });
    expect(crashed[0]?.stderrTail.join('\n')).toContain('fake-agent: crashing');

    const restarted = await pool.acquire('bot');
    expect(restarted).not.toBe(client);
    expect(restarted.process.pid).not.toBe(pid);
    expect(pool.size).toBe(1);
  });

  it('releases an idle process and starts a fresh one on the next acquire', async () => {
    const { pool } = await makePool('normal', { idleMs: 60 });
    const client = await pool.acquire('bot');
    const pid = client.process.pid;
    await waitFor(() => pool.size === 0);
    const again = await pool.acquire('bot');
    expect(again.process.pid).not.toBe(pid);
  });

  it('evicts the least-recently-used idle process when a new key needs a slot at the cap', async () => {
    const { pool } = await makePool('normal', { maxProcesses: 2, evictIdleAfterMs: 5 });
    const a = await pool.acquire('a');
    await new Promise((resolve) => {
      setTimeout(resolve, 10);
    });
    await pool.acquire('b');
    const c = await pool.acquire('c');
    expect(c.process.pid).toBeTypeOf('number');
    expect(pool.size).toBe(2);
    await waitFor(() => a.process.exitInfo !== undefined);
    const again = await pool.acquire('b');
    expect(again).toBeDefined();
  });

  it('does not evict a process used within the grace period (it may be about to receive a prompt)', async () => {
    const { pool } = await makePool('normal', { maxProcesses: 1, evictIdleAfterMs: 60_000 });
    await pool.acquire('a');
    let started = false;
    void pool.acquire('b').then(() => {
      started = true;
    });
    await new Promise((resolve) => {
      setTimeout(resolve, 80);
    });
    expect(started).toBe(false);
    await pool.release('a');
    await waitFor(() => started);
  });

  it('queues acquires above maxProcesses while every process is busy', async () => {
    const { pool } = await makePool('silent', { maxProcesses: 1, promptTimeoutMs: 60_000, evictIdleAfterMs: 0 });
    const client = await pool.acquire('a');
    const session = await client.newSession({ cwd: '/tmp' });
    const inFlight = pool.prompt('a', session.sessionId, [{ type: 'text', text: 'hold' }]).catch(() => undefined);
    await new Promise((resolve) => {
      setTimeout(resolve, 20);
    });
    let started = false;
    const second = pool.acquire('b').then((next) => {
      started = true;
      return next;
    });
    await new Promise((resolve) => {
      setTimeout(resolve, 80);
    });
    expect(started).toBe(false);
    expect(pool.size).toBe(1);
    await pool.release('a');
    await inFlight;
    const next = await second;
    expect(started).toBe(true);
    expect(next.process.pid).toBeTypeOf('number');
  });

  it('cancels, waits, then restarts when a prompt never completes', async () => {
    const { pool } = await makePool('silent', { promptTimeoutMs: 80, cancelGraceMs: 40 });
    const crashed: CrashedEvent[] = [];
    pool.onCrashed((event) => crashed.push(event));
    const client = await pool.acquire('bot');
    const pid = client.process.pid;
    const session = await client.newSession({ cwd: '/tmp' });
    await expect(pool.prompt('bot', session.sessionId, [{ type: 'text', text: 'never' }]))
      .rejects.toBeInstanceOf(AcpTimeoutError);
    await waitFor(() => crashed.length === 1);
    expect(crashed[0]).toMatchObject({ key: 'bot', reason: 'prompt-timeout' });
    const restarted = await pool.acquire('bot');
    expect(restarted.process.pid).not.toBe(pid);
  });

  it('mounts the stream channel and forwards draft events', async () => {
    const drafts: DraftEvent[] = [];
    const { pool } = await makePool('stream', { streaming: true, onDraft: (event) => drafts.push(event) });
    const client = await pool.acquire('bot');
    const session = await client.newSession({ cwd: '/tmp' });
    await pool.prompt('bot', session.sessionId, [{ type: 'text', text: 'stream' }]);
    await waitFor(() => drafts.some((event) => event.type === 'draft_commit'));
    const commit = drafts.find((event) => event.type === 'draft_commit');
    expect(commit).toMatchObject({ text: 'NEW TEXT' });
    expect(client.streamingObserved).toBe(true);
  });

  it('closeSession / release removes a key and frees its slot', async () => {
    const { pool } = await makePool('normal', { maxProcesses: 1 });
    const client = await pool.acquire('bot');
    const session = await client.newSession({ cwd: '/tmp' });
    await client.closeSession(session.sessionId);
    await pool.release('bot');
    expect(pool.size).toBe(0);
    const next = await pool.acquire('other');
    expect(next.process.pid).toBeTypeOf('number');
  });
});
