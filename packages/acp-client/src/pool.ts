/** Keyed lifecycle pool for harness processes with idle release and crash recovery. */

import { AcpError, AcpTimeoutError } from './errors.js';
import { AcpClient, type AcpClientOptions } from './client.js';
import type { AcpSpawnSpec } from './process.js';
import type { PromptContentBlock, PromptResult } from './types.js';
import { DraftTracker, StreamChannel, STREAM_SOCKET_ENV, type DraftEvent } from './stream/index.js';

const DEFAULT_IDLE_MS = 10 * 60_000;
const DEFAULT_MAX_PROCESSES = 4;
const DEFAULT_EVICT_IDLE_AFTER_MS = 30_000;
const DEFAULT_PROMPT_TIMEOUT_MS = 15 * 60_000;
const DEFAULT_CANCEL_GRACE_MS = 10_000;

export interface HarnessPoolOptions {
  spawnSpec: AcpSpawnSpec;
  clientOptions?: AcpClientOptions;
  idleMs?: number;
  maxProcesses?: number;
  /**
   * At the process cap, an idle process (no prompt in flight) unused for at least this long is closed to free
   * a slot instead of waiting for its idle timer. The grace keeps a process that was just acquired for a
   * session from being evicted before its prompt starts. Defaults to 30 seconds.
   */
  evictIdleAfterMs?: number;
  promptTimeoutMs?: number;
  cancelGraceMs?: number;
  /** Mount the streaming side-channel plugin and wire draft events to `onDraft`. */
  streaming?: boolean;
  onDraft?: (event: DraftEvent) => void;
}

export interface CrashedEvent {
  key: string;
  reason: 'exit' | 'prompt-timeout';
  code: number | null;
  signal: string | null;
  stderrTail: readonly string[];
}

export interface PoolPromptOptions {
  timeoutMs?: number;
  cancelGraceMs?: number;
}

interface PoolEntry {
  key: string;
  client: AcpClient;
  channel: StreamChannel | undefined;
  tracker: DraftTracker | undefined;
  idleTimer: ReturnType<typeof setTimeout> | undefined;
  busy: number;
  /** Last time this entry was acquired or finished a prompt (ms since epoch). */
  lastUsed: number;
  closing: boolean;
  crashReported: boolean;
  slotReleased: boolean;
}

function delay(ms: number): { promise: Promise<'timeout'>; cancel: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const promise = new Promise<'timeout'>((resolve) => {
    timer = setTimeout(() => resolve('timeout'), ms);
    timer.unref();
  });
  return {
    promise,
    cancel: () => {
      if (timer !== undefined) clearTimeout(timer);
    },
  };
}

/**
 * One harness process per key, started on demand. Idle entries are closed and
 * later resumed through `session/resume`; unexpected exits close the entry so
 * the next `acquire` starts a fresh process.
 */
export class HarnessPool {
  private readonly options: HarnessPoolOptions;
  private readonly idleMs: number;
  private readonly maxProcesses: number;
  private readonly evictIdleAfterMs: number;
  private readonly promptTimeoutMs: number;
  private readonly cancelGraceMs: number;
  private readonly streaming: boolean;
  private readonly entries = new Map<string, PoolEntry>();
  private readonly starting = new Map<string, Promise<AcpClient>>();
  private readonly crashedListeners = new Set<(event: CrashedEvent) => void>();
  private readonly waiters: Array<() => void> = [];
  private activeProcesses = 0;
  private stopped = false;

  constructor(options: HarnessPoolOptions) {
    this.options = options;
    this.idleMs = options.idleMs ?? DEFAULT_IDLE_MS;
    this.maxProcesses = options.maxProcesses ?? DEFAULT_MAX_PROCESSES;
    this.evictIdleAfterMs = options.evictIdleAfterMs ?? DEFAULT_EVICT_IDLE_AFTER_MS;
    this.promptTimeoutMs = options.promptTimeoutMs ?? DEFAULT_PROMPT_TIMEOUT_MS;
    this.cancelGraceMs = options.cancelGraceMs ?? DEFAULT_CANCEL_GRACE_MS;
    this.streaming = options.streaming ?? options.clientOptions?.streaming ?? false;
    if (!Number.isInteger(this.maxProcesses) || this.maxProcesses < 1) {
      throw new AcpError('maxProcesses must be a positive integer');
    }
  }

  get size(): number {
    return this.entries.size;
  }

  onCrashed(listener: (event: CrashedEvent) => void): () => void {
    this.crashedListeners.add(listener);
    return () => {
      this.crashedListeners.delete(listener);
    };
  }

  async acquire(key: string, spawnSpec: AcpSpawnSpec = this.options.spawnSpec): Promise<AcpClient> {
    if (this.stopped) throw new AcpError('HarnessPool has been stopped');
    const existing = this.entries.get(key);
    if (existing !== undefined) {
      this.touch(existing);
      return existing.client;
    }
    const pending = this.starting.get(key);
    if (pending !== undefined) return pending;
    const launch = this.launch(key, spawnSpec).finally(() => {
      this.starting.delete(key);
    });
    this.starting.set(key, launch);
    return launch;
  }

  /** Send one prompt with a total timeout; on expiry cancel, wait, then restart. */
  async prompt(
    key: string,
    sessionId: string,
    blocks: readonly PromptContentBlock[],
    options: PoolPromptOptions = {},
  ): Promise<PromptResult> {
    await this.acquire(key);
    const entry = this.entries.get(key);
    if (entry === undefined) throw new AcpError(`no pooled harness for key: ${key}`);
    entry.busy += 1;
    this.clearIdle(entry);
    const timeoutMs = options.timeoutMs ?? this.promptTimeoutMs;
    const graceMs = options.cancelGraceMs ?? this.cancelGraceMs;
    try {
      return await this.runPrompt(entry, sessionId, blocks, timeoutMs, graceMs);
    } finally {
      entry.busy = Math.max(0, entry.busy - 1);
      this.touch(entry);
    }
  }

  cancel(key: string, sessionId: string): void {
    this.entries.get(key)?.client.cancel(sessionId);
  }

  /** Close one key immediately (used for explicit shutdown, not idle release). */
  async release(key: string): Promise<void> {
    const entry = this.entries.get(key);
    if (entry !== undefined) await this.destroy(entry);
  }

  async stopAll(): Promise<void> {
    this.stopped = true;
    while (this.waiters.length > 0) {
      const waiter = this.waiters.shift();
      waiter?.();
    }
    await Promise.all([...this.entries.values()].map((entry) => this.destroy(entry)));
  }

  private async runPrompt(
    entry: PoolEntry,
    sessionId: string,
    blocks: readonly PromptContentBlock[],
    timeoutMs: number,
    graceMs: number,
  ): Promise<PromptResult> {
    const prompt = entry.client.prompt(sessionId, blocks);
    if (timeoutMs <= 0) return prompt;
    const first = delay(timeoutMs);
    try {
      const outcome = await Promise.race([
        prompt.then(
          (value) => ({ kind: 'done' as const, value }),
          (error: unknown) => ({ kind: 'error' as const, error }),
        ),
        first.promise.then(() => ({ kind: 'timeout' as const })),
      ]);
      if (outcome.kind === 'done') return outcome.value;
      if (outcome.kind === 'error') throw outcome.error;
    } finally {
      first.cancel();
    }
    try {
      entry.client.cancel(sessionId);
    } catch {
      // The process may already be gone; the restart path below still runs.
    }
    const grace = delay(graceMs);
    try {
      const settled = await Promise.race([
        prompt.then(
          (value) => ({ kind: 'done' as const, value }),
          (error: unknown) => ({ kind: 'error' as const, error }),
        ),
        grace.promise.then(() => ({ kind: 'timeout' as const })),
      ]);
      if (settled.kind === 'done') return settled.value;
    } finally {
      grace.cancel();
    }
    const process = entry.client.process;
    await this.destroy(entry, {
      key: entry.key,
      reason: 'prompt-timeout',
      code: process.exitInfo?.code ?? null,
      signal: process.exitInfo?.signal ?? null,
      stderrTail: process.stderrTail,
    });
    throw new AcpTimeoutError('session/prompt', timeoutMs);
  }

  private async launch(key: string, spawnSpec: AcpSpawnSpec): Promise<AcpClient> {
    await this.reserveSlot();
    if (this.stopped) {
      this.releaseSlot();
      throw new AcpError('HarnessPool has been stopped');
    }
    let channel: StreamChannel | undefined;
    let tracker: DraftTracker | undefined;
    let client: AcpClient | undefined;
    let entry: PoolEntry | undefined;
    try {
      let env = spawnSpec.env;
      if (this.streaming) {
        channel = new StreamChannel();
        const socketPath = await channel.start();
        env = { ...(spawnSpec.env ?? process.env), [STREAM_SOCKET_ENV]: socketPath };
        tracker = new DraftTracker((event) => this.options.onDraft?.(event));
      }
      client = new AcpClient(
        {
          ...spawnSpec,
          ...(env === undefined ? {} : { env }),
        },
        { ...this.options.clientOptions, streaming: this.streaming },
      );
      entry = {
        key,
        client,
        channel,
        tracker,
        idleTimer: undefined,
        busy: 0,
        lastUsed: Date.now(),
        closing: false,
        crashReported: false,
        slotReleased: false,
      };
      const created = entry;
      if (channel !== undefined) {
        channel.onFrame((frame) => {
          created.client.markDraftActivity();
          created.tracker?.handleFrame(frame);
        });
      }
      client.onEvent((event) => {
        if (event.type === 'message') created.tracker?.handleCommitted(event.sessionId, event.text);
      });
      client.onExit((info) => {
        this.handleProcessExit(created, info.code, info.signal, info.stderrTail);
      });
      await client.initialize();
      if (this.stopped) throw new AcpError('HarnessPool has been stopped');
      this.entries.set(key, entry);
      this.touch(entry);
      return client;
    } catch (error: unknown) {
      if (entry !== undefined) {
        await this.destroy(entry);
      } else {
        if (client !== undefined) await client.close();
        if (channel !== undefined) await channel.close();
        this.releaseSlot();
      }
      throw error;
    }
  }

  private handleProcessExit(
    entry: PoolEntry,
    code: number | null,
    signal: string | null,
    stderrTail: readonly string[],
  ): void {
    this.clearIdle(entry);
    if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
    void entry.channel?.close();
    if (!entry.slotReleased) {
      entry.slotReleased = true;
      this.releaseSlot();
    }
    if (!entry.closing && !entry.crashReported) {
      entry.crashReported = true;
      this.emitCrashed({ key: entry.key, reason: 'exit', code, signal, stderrTail });
    }
  }

  private async destroy(entry: PoolEntry, crash?: CrashedEvent): Promise<void> {
    entry.closing = true;
    this.clearIdle(entry);
    if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
    await entry.client.close();
    await entry.channel?.close();
    if (crash !== undefined && !entry.crashReported) {
      entry.crashReported = true;
      const info = entry.client.process.exitInfo;
      this.emitCrashed({
        ...crash,
        code: info?.code ?? crash.code,
        signal: info?.signal ?? crash.signal,
        stderrTail: info?.stderrTail ?? crash.stderrTail,
      });
    }
    if (!entry.slotReleased) {
      entry.slotReleased = true;
      this.releaseSlot();
    }
  }

  private touch(entry: PoolEntry): void {
    entry.lastUsed = Date.now();
    this.clearIdle(entry);
    if (entry.busy > 0 || entry.closing || this.idleMs <= 0) return;
    entry.idleTimer = setTimeout(() => {
      entry.idleTimer = undefined;
      void this.destroy(entry);
    }, this.idleMs);
    entry.idleTimer.unref();
  }

  private clearIdle(entry: PoolEntry): void {
    if (entry.idleTimer !== undefined) {
      clearTimeout(entry.idleTimer);
      entry.idleTimer = undefined;
    }
  }

  private async reserveSlot(): Promise<void> {
    if (this.activeProcesses < this.maxProcesses) {
      this.activeProcesses += 1;
      return;
    }
    const granted = new Promise<void>((resolve) => {
      this.waiters.push(resolve);
    });
    // At the cap: free the least-recently-used idle process now instead of waiting for its idle timer.
    // Its sessions stay on disk and are resumed on the next acquire.
    const idle = [...this.entries.values()]
      .filter((entry) => entry.busy === 0 && !entry.closing && Date.now() - entry.lastUsed >= this.evictIdleAfterMs)
      .sort((left, right) => left.lastUsed - right.lastUsed)[0];
    if (idle !== undefined) void this.destroy(idle);
    await granted;
  }

  private releaseSlot(): void {
    const next = this.waiters.shift();
    if (next !== undefined) next();
    else this.activeProcesses = Math.max(0, this.activeProcesses - 1);
  }

  private emitCrashed(event: CrashedEvent): void {
    for (const listener of [...this.crashedListeners]) {
      try {
        listener(event);
      } catch {
        // A consumer listener must not break pool bookkeeping.
      }
    }
  }
}
