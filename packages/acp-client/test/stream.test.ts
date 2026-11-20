import { access } from 'node:fs/promises';
import { createConnection } from 'node:net';
import { afterEach, describe, expect, it } from 'vitest';

import {
  DraftTracker,
  StreamChannel,
  pluginPath,
  streamPatchYaml,
  type DraftEvent,
  type StreamFrame,
} from '../src/index.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

describe('StreamChannel', () => {
  it('receives NDJSON frames and ignores malformed lines', async () => {
    const channel = new StreamChannel();
    const [path, concurrent] = await Promise.all([channel.start(), channel.start()]);
    cleanups.push(async () => {
      await channel.close();
    });
    expect(concurrent).toBe(path);
    expect(await channel.start()).toBe(path);
    expect(channel.socketPath).toBe(path);
    const frames: StreamFrame[] = [];
    channel.onFrame((frame) => frames.push(frame));

    const socket = createConnection({ path });
    cleanups.push(async () => {
      socket.destroy();
    });
    await new Promise<void>((resolve) => {
      socket.once('connect', () => resolve());
    });
    socket.write('not json\n');
    socket.write(`${JSON.stringify({ session: 's1', t: 'start', attemptId: 'a1' })}\n`);
    socket.write(`${JSON.stringify({ session: 's1', t: 'text-delta', attemptId: 'a1', i: 0, text: 'hi' })}\n`);
    socket.write(`${JSON.stringify({ session: '', t: 'start' })}\n`);
    await new Promise((resolve) => {
      setTimeout(resolve, 50);
    });
    expect(frames).toEqual([
      { session: 's1', t: 'start', attemptId: 'a1' },
      { session: 's1', t: 'text-delta', attemptId: 'a1', i: 0, text: 'hi' },
    ]);
  });

  it('cleans up its socket directory on close', async () => {
    const channel = new StreamChannel();
    const path = await channel.start();
    await channel.close();
    await expect(access(path)).rejects.toBeTruthy();
  });
});

describe('DraftTracker', () => {
  it('resets on a retry, ignores stale deltas, and commits the ACP text', () => {
    const events: DraftEvent[] = [];
    const tracker = new DraftTracker((event) => events.push(event));
    tracker.handleFrame({ session: 's1', t: 'start', attemptId: 'a1' });
    tracker.handleFrame({ session: 's1', t: 'text-delta', attemptId: 'a1', i: 0, text: 'OLD ' });
    tracker.handleFrame({ session: 's1', t: 'text-delta', attemptId: 'a1', i: 1, text: 'DRAFT' });
    expect(tracker.snapshot('s1')).toMatchObject({ attemptId: 'a1', text: 'OLD DRAFT' });

    tracker.handleFrame({ session: 's1', t: 'start', attemptId: 'a2' });
    tracker.handleFrame({ session: 's1', t: 'text-delta', attemptId: 'a1', i: 2, text: 'STALE' });
    tracker.handleFrame({ session: 's1', t: 'reasoning-delta', attemptId: 'a2', i: 0, text: 'think' });
    tracker.handleFrame({ session: 's1', t: 'text-delta', attemptId: 'a2', i: 1, text: 'NEW' });
    expect(tracker.snapshot('s1')).toMatchObject({ attemptId: 'a2', text: 'NEW', reasoning: 'think' });

    tracker.handleCommitted('s1', 'NEW');
    expect(tracker.snapshot('s1')).toBeUndefined();
    expect(events).toEqual([
      { type: 'draft_reset', sessionId: 's1', attemptId: 'a1' },
      { type: 'draft_delta', sessionId: 's1', kind: 'text', text: 'OLD ', attemptId: 'a1' },
      { type: 'draft_delta', sessionId: 's1', kind: 'text', text: 'DRAFT', attemptId: 'a1' },
      { type: 'draft_reset', sessionId: 's1', attemptId: 'a2' },
      { type: 'draft_delta', sessionId: 's1', kind: 'reasoning', text: 'think', attemptId: 'a2' },
      { type: 'draft_delta', sessionId: 's1', kind: 'text', text: 'NEW', attemptId: 'a2' },
      { type: 'draft_commit', sessionId: 's1', text: 'NEW' },
    ]);
  });

  it('marks end frames without committing by itself', () => {
    const events: DraftEvent[] = [];
    const tracker = new DraftTracker((event) => events.push(event));
    tracker.handleFrame({ session: 's1', t: 'start', attemptId: 'a1' });
    tracker.handleFrame({ session: 's1', t: 'end', attemptId: 'a1', outcome: { kind: 'abandoned' } });
    expect(tracker.snapshot('s1')?.ended).toBe(true);
    expect(events.some((event) => event.type === 'draft_commit')).toBe(false);
  });
});

describe('plugin helpers', () => {
  it('resolves the shipped plugin and renders an equivalent patch', async () => {
    const path = pluginPath();
    expect(path.endsWith('/plugin/chives-stream.plugin.mjs')).toBe(true);
    await expect(access(path)).resolves.toBeUndefined();
    expect(streamPatchYaml('/tmp/chives stream.plugin.mjs')).toBe([
      '- insert:',
      '    - id: chives-stream',
      '      name: "/tmp/chives stream.plugin.mjs"',
      '      config:',
      '        verbose: true',
      '',
    ].join('\n'));
  });
});
