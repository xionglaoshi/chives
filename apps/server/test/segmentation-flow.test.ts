import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { BotManifest } from '../src/bots/index.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import type {
  HarnessDriver,
  HarnessPromptResult,
  HarnessSink,
} from '../src/harness/types.js';
import { Orchestrator } from '../src/orchestrator.js';
import { FakeTaskClassifier, type TaskClassifier } from '../src/segmentation/classifier.js';
import type { TaskRecord } from '../src/store/index.js';
import { Store } from '../src/store/index.js';
import { closeServer, listen, makeRegistry, testConfig, waitFor } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

class RecordingDriver implements HarnessDriver {
  readonly prompts: string[] = [];

  constructor(private readonly reply?: (prompt: string) => string) {}

  ensureSession(_bot: BotManifest, task: TaskRecord): Promise<string> {
    return Promise.resolve(task.harnessSessionId ?? `session-${task.id}`);
  }

  prompt(
    _bot: BotManifest,
    _sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    this.prompts.push(text);
    if (text.startsWith('[Chives 任务小结]')) {
      const title = /标题：(.+?)）/.exec(text)?.[1] ?? '任务小结';
      sink({ type: 'draft_delta', kind: 'text', text: 'hidden' });
      sink({ type: 'message', text: JSON.stringify({
        title,
        conclusion: `${title} 的结论`,
        key_numbers: [],
        deliverables: [],
        open_questions: [],
        symbols: [],
      }) });
      return Promise.resolve({ stopReason: 'end_turn' });
    }
    sink({ type: 'message', text: this.reply?.(text) ?? `回答：${text}` });
    sink({ type: 'usage', used: 100, size: 1000 });
    return Promise.resolve({ stopReason: 'end_turn' });
  }

  cancel(): void {}

  shutdown(): Promise<void> {
    return Promise.resolve();
  }

  normalPrompts(): string[] {
    return this.prompts.filter((prompt) => !prompt.startsWith('[Chives 任务小结]'));
  }
}

interface Flow {
  dataDir: string;
  store: Store;
  driver: RecordingDriver;
  orchestrator: Orchestrator;
  clock: { now: Date };
}

async function flow(
  options: {
    classifier?: TaskClassifier;
    mode?: 'model' | 'rules';
    reply?: (prompt: string) => string;
  } = {},
): Promise<Flow> {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-seg-flow-'));
  const store = Store.open(dataDir);
  const driver = new RecordingDriver(options.reply);
  const clock = { now: new Date('2026-11-16T02:00:00.000Z') };
  const orchestrator = new Orchestrator({
    registry: makeRegistry(),
    store,
    bus: new EventBus(),
    now: () => clock.now,
    driver,
    classifierMode: options.mode ?? 'rules',
    ...(options.classifier === undefined ? {} : { classifier: options.classifier }),
    idleCloseMs: 30 * 60_000,
  });
  orchestrator.start();
  cleanups.push(async () => {
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { dataDir, store, driver, orchestrator, clock };
}

function recentLines(injection: string): string[] {
  const section = injection.split('## 最近的对话原文')[1]?.split('## 之前的任务目录')[0] ?? '';
  return section.split('\n').filter((line) => line.startsWith('- '));
}

describe('scripted multi-day conversation', () => {
  it('continues, starts a new segment, injects the directory, and records injection stats', async () => {
    const harness = await flow();
    const { store, driver, orchestrator, clock } = harness;

    const first = await orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');

    // Five minutes later the explicit continuation wording keeps the session.
    clock.now = new Date(clock.now.getTime() + 5 * 60_000);
    const second = await orchestrator.submitMessage('expert', '接着看看三季报');
    expect(second.taskId).toBe(first.taskId);
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');

    const firstTask = store.tasks.get(first.taskId);
    expect(firstTask?.contextMeta).toMatchObject({ injectedChars: expect.any(Number) });
    expect(firstTask?.contextMeta?.['directoryEntries']).toBe(0);

    // Two hours after the last message the idle scan closes the segment.
    clock.now = new Date(clock.now.getTime() + 2 * 60 * 60_000);
    await orchestrator.segmentation.scanIdle();
    expect(store.tasks.get(first.taskId)?.closedAt).not.toBeNull();
    await waitFor(() => store.summaries.get(first.taskId) !== undefined);

    const third = await orchestrator.submitMessage('expert', '宁德时代 300750.SZ 怎么样');
    expect(third.taskId).not.toBe(first.taskId);
    await waitFor(() => store.tasks.get(third.taskId)?.status === 'done');

    const thirdTask = store.tasks.get(third.taskId);
    expect(thirdTask?.segmentReason).toBe('previous_closed');
    expect(thirdTask?.contextMeta?.['directoryEntries']).toBe(1);
    const thirdInjection = driver.normalPrompts().at(-1) ?? '';
    expect(thirdInjection).toContain(`task:${first.taskId}`);
    expect(thirdInjection).toContain('看下贵州茅台');
    expect(thirdInjection).not.toContain('process.env');
    expect(recentLines(thirdInjection).length).toBeLessThanOrEqual(6);
    expect(store.messages.listByTask(third.taskId)[0]?.content).toBe('宁德时代 300750.SZ 怎么样');
    expect(thirdInjection.startsWith('[Chives 上下文：')).toBe(true);

    // Same day, five minutes later a different code starts a new segment even
    // though the gap alone would continue.
    clock.now = new Date(clock.now.getTime() + 5 * 60_000);
    const switched = await orchestrator.submitMessage('expert', '600519 怎么样');
    expect(switched.taskId).not.toBe(third.taskId);
    await waitFor(() => store.tasks.get(switched.taskId)?.status === 'done');
    expect(store.tasks.get(switched.taskId)?.segmentReason).toBe('symbols_disjoint');

    // The next day, "接着说茅台" is continuation wording but the gap forces new.
    clock.now = new Date(clock.now.getTime() + 24 * 60 * 60_000);
    await orchestrator.segmentation.scanIdle();
    const fourth = await orchestrator.submitMessage('expert', '接着说茅台');
    expect(fourth.taskId).not.toBe(switched.taskId);
    await waitFor(() => store.tasks.get(fourth.taskId)?.status === 'done');

    const fourthTask = store.tasks.get(fourth.taskId);
    expect(fourthTask?.segmentReason).toBe('previous_closed');
    const fourthInjection = driver.normalPrompts().at(-1) ?? '';
    expect(fourthInjection).toContain(`task:${first.taskId}`);
    expect(fourthInjection).toContain(`task:${third.taskId}`);
    expect(fourthInjection).toContain(`task:${switched.taskId}`);
    expect(fourthInjection).toContain('接着说茅台');
    expect(recentLines(fourthInjection).length).toBeLessThanOrEqual(6);
    expect(fourthTask?.contextMeta).toMatchObject({
      recentMessages: expect.any(Number),
      directoryEntries: 3,
    });
    expect((fourthTask?.contextMeta?.['injectedChars'] as number | undefined) ?? 0).toBeGreaterThan(0);
  });

  it('starts a new segment when a name hit points at a different symbol within five minutes', async () => {
    const harness = await flow({
      reply: (prompt) =>
        prompt.trimEnd().endsWith('看下 600519')
          ? '回答：看下 600519'
          : '宁德时代（300750.SZ）是创业板公司。',
    });
    const { store, orchestrator, clock } = harness;

    const first = await orchestrator.submitMessage('expert', '宁德时代怎么样');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');
    expect(store.summaries.symbolNameMap()).toMatchObject({ 宁德时代: '300750.SZ' });

    // Close the first segment so the next message starts a fresh 600519 task.
    clock.now = new Date(clock.now.getTime() + 2 * 60 * 60_000);
    await orchestrator.segmentation.scanIdle();
    expect(store.tasks.get(first.taskId)?.closedAt).not.toBeNull();

    const second = await orchestrator.submitMessage('expert', '看下 600519');
    await waitFor(() => store.tasks.get(second.taskId)?.status === 'done');
    expect(second.taskId).not.toBe(first.taskId);
    expect(store.taskSymbols.listForTask(second.taskId).map((symbol) => symbol.code)).toEqual([
      '600519.SH',
    ]);

    // Five minutes later the name table resolves 宁德时代 to a disjoint code.
    clock.now = new Date(clock.now.getTime() + 5 * 60_000);
    const third = await orchestrator.submitMessage('expert', '宁德时代怎么样');
    expect(third.taskId).not.toBe(second.taskId);
    expect(store.tasks.get(third.taskId)?.segmentReason).toBe('symbols_disjoint');
  });

  it('keeps the segment when only a longer name is in the table', async () => {
    const harness = await flow({ reply: () => '贵州茅台（600519）营收稳。' });
    const { store, orchestrator, clock } = harness;

    const first = await orchestrator.submitMessage('expert', '贵州茅台怎么样');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');
    expect(store.summaries.symbolNameMap()).toMatchObject({ 贵州茅台: '600519.SH' });

    // "茅台" is not in `symbol_names`, so rule 4 has no next symbols to compare.
    clock.now = new Date(clock.now.getTime() + 3 * 60_000);
    const second = await orchestrator.submitMessage('expert', '茅台的毛利率呢');
    expect(second.taskId).toBe(first.taskId);
    expect(store.tasks.get(first.taskId)?.segmentReason).toBe('gap_under_10m');
  });

  it('closes the previous segment asynchronously when a new one starts', async () => {
    const harness = await flow();
    const { store, driver, orchestrator, clock } = harness;
    const first = await orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => store.tasks.get(first.taskId)?.status === 'done');

    clock.now = new Date(clock.now.getTime() + 7 * 60 * 60_000);
    const second = await orchestrator.submitMessage('expert', '另外问问银行股');
    expect(second.taskId).not.toBe(first.taskId);
    expect(store.tasks.get(first.taskId)?.closedAt).not.toBeNull();
    await waitFor(() => store.summaries.get(first.taskId) !== undefined);

    expect(store.summaries.get(first.taskId)?.source).toBe('model');
    expect(driver.normalPrompts().at(-1)).toContain('[Chives 上下文：');
  });
});

describe('classifier integration', () => {
  it('uses the model answer for an uncertain decision', async () => {
    const harness = await flow({ mode: 'model', classifier: new FakeTaskClassifier(['continue']) });
    const first = await harness.orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => harness.store.tasks.get(first.taskId)?.status === 'done');

    harness.clock.now = new Date(harness.clock.now.getTime() + 3 * 60 * 60_000);
    const second = await harness.orchestrator.submitMessage('expert', '毛利率怎么样');
    expect(second.taskId).toBe(first.taskId);
    expect(harness.store.tasks.get(first.taskId)?.segmentReason).toBe('uncertain_model_continue');
  });

  it('rejects a second message while the classifier is still deciding', async () => {
    const slow: TaskClassifier = {
      classify: () =>
        new Promise((resolve) => {
          setTimeout(() => resolve('continue'), 40);
        }),
    };
    const harness = await flow({ mode: 'model', classifier: slow });
    const first = await harness.orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => harness.store.tasks.get(first.taskId)?.status === 'done');

    harness.clock.now = new Date(harness.clock.now.getTime() + 3 * 60 * 60_000);
    const pending = harness.orchestrator.submitMessage('expert', '毛利率怎么样');
    await expect(harness.orchestrator.submitMessage('expert', '再问一个')).rejects.toThrowError(
      /already has a running task/,
    );
    expect((await pending).taskId).toBe(first.taskId);
  });

  it('falls back to the gap rule when the classifier fails', async () => {
    const harness = await flow({ mode: 'model', classifier: new FakeTaskClassifier([], true) });
    const first = await harness.orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => harness.store.tasks.get(first.taskId)?.status === 'done');

    harness.clock.now = new Date(harness.clock.now.getTime() + 3 * 60 * 60_000);
    const second = await harness.orchestrator.submitMessage('expert', '毛利率怎么样');
    expect(second.taskId).not.toBe(first.taskId);
    expect(harness.store.tasks.get(second.taskId)?.segmentReason).toBe('uncertain_model_failed_new');
  });

  it('uses the fallback rule directly in rules mode', async () => {
    const harness = await flow({ mode: 'rules' });
    const first = await harness.orchestrator.submitMessage('expert', '看下贵州茅台');
    await waitFor(() => harness.store.tasks.get(first.taskId)?.status === 'done');

    harness.clock.now = new Date(harness.clock.now.getTime() + 60 * 60_000);
    const second = await harness.orchestrator.submitMessage('expert', '毛利率怎么样');
    expect(second.taskId).toBe(first.taskId);
    expect(harness.store.tasks.get(first.taskId)?.segmentReason).toBe('uncertain_fallback_continue');
  });
});

describe('context usage API', () => {
  it('returns recent rounds and per-task last context usage', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-seg-usage-'));
    const app: ChivesApp = createApp({ config: testConfig(dataDir), driver: new FakeDriver() });
    const baseUrl = await listen(app.server);
    cleanups.push(async () => {
      await closeServer(app.server);
      await app.close();
      await rm(dataDir, { recursive: true, force: true });
    });

    const accepted = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '看看茅台' }),
      })
    ).json()) as { taskId: string };

    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
    const second = (await (
      await fetch(`${baseUrl}/api/bots/expert/messages`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text: '接着看看利润' }),
      })
    ).json()) as { taskId: string };
    expect(second.taskId).toBe(accepted.taskId);
    await waitFor(() => app.store.messages.listByTask(accepted.taskId).length === 4);

    const usage = (await (
      await fetch(`${baseUrl}/api/bots/expert/context-usage?limit=10`)
    ).json()) as Array<{ taskId: string; at: string; used: number; size: number }>;
    expect(usage).toHaveLength(2);
    expect(usage[0]).toMatchObject({ taskId: accepted.taskId, used: 1234, size: 1_000_000 });

    const detail = (await (
      await fetch(`${baseUrl}/api/tasks/${accepted.taskId}`)
    ).json()) as {
      task: { lastContextUsed: number | null; lastContextSize: number | null };
      usage: Array<{ used: number }>;
      contextUsage: Array<{ used: number }>;
      summary: unknown;
    };
    expect(detail.task.lastContextUsed).toBe(1234);
    expect(detail.task.lastContextSize).toBe(1_000_000);
    expect(detail.usage).toHaveLength(2);
    expect(detail.contextUsage).toHaveLength(2);
    expect(detail.summary).toBeNull();

    const timeline = (await (
      await fetch(`${baseUrl}/api/bots/expert/timeline?limit=10`)
    ).json()) as { tasks: Array<{ id: string; closedAt?: string | null }> };
    expect(timeline.tasks[0]?.closedAt ?? null).toBeNull();
  });
});
