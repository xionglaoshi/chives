import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import type { ServerEvent } from '../src/api/protocol.js';
import { EventBus } from '../src/events/index.js';
import type { BotManifest } from '../src/bots/index.js';
import type {
  HarnessDriver,
  HarnessPromptResult,
  HarnessSink,
} from '../src/harness/types.js';
import { Orchestrator } from '../src/orchestrator.js';
import { FakeDriver } from '../src/harness/fake.js';
import {
  buildContextInjection,
  MAX_INJECTION_CHARS,
  type ContextTaskLine,
} from '../src/segmentation/context.js';
import {
  decideSegment,
  type SegmentInput,
  type SegmentPrevious,
} from '../src/segmentation/decide.js';
import { SegmentationService } from '../src/segmentation/service.js';
import { buildSummaryPrompt, parseSummaryResponse } from '../src/segmentation/summary.js';
import { Store, type TaskRecord } from '../src/store/index.js';
import { extractBotSymbols, extractUserSymbols, normalizeSymbolCode } from '../src/symbols.js';
import { makeRegistry } from './support.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

const NOW = new Date('2026-11-16T12:00:00.000Z');

function previous(overrides: Partial<SegmentPrevious> = {}): SegmentPrevious {
  return {
    id: 't1',
    title: '看下贵州茅台',
    closedAt: null,
    symbols: [{ code: '600519.SH', name: '贵州茅台' }],
    ...overrides,
  };
}

function segmentInput(overrides: Partial<SegmentInput> = {}): SegmentInput {
  return {
    previous: previous(),
    lastMessageAt: new Date(NOW.getTime() - 5 * 60_000).toISOString(),
    text: '再帮我看看',
    now: NOW,
    symbolNames: {},
    ...overrides,
  };
}

describe('decideSegment', () => {
  it('starts new without a previous segment and when the previous one is closed', () => {
    expect(decideSegment(segmentInput({ previous: undefined }))).toMatchObject({
      kind: 'new',
      reason: 'no_previous',
    });
    expect(
      decideSegment(segmentInput({ previous: previous({ closedAt: '2026-11-16T11:00:00.000Z' }) })),
    ).toMatchObject({ kind: 'new', reason: 'previous_closed' });
  });

  it('honours explicit new-topic and continuation wording', () => {
    expect(decideSegment(segmentInput({ text: '另外看看比亚迪' }))).toMatchObject({
      kind: 'new',
      reason: 'explicit_new_topic',
    });
    expect(decideSegment(segmentInput({ text: '换个话题，聊聊银行' }))).toMatchObject({
      kind: 'new',
      reason: 'explicit_new_topic',
    });
    expect(decideSegment(segmentInput({ text: '接着看看三季报' }))).toMatchObject({
      kind: 'continue',
      reason: 'explicit_continue',
    });
    expect(decideSegment(segmentInput({ text: '它的毛利率呢' }))).toMatchObject({
      kind: 'continue',
      reason: 'explicit_continue',
    });
  });

  it('uses the injected clock for the 5-minute, 2-hour, 6-hour and 7-hour branches', () => {
    expect(decideSegment(segmentInput())).toMatchObject({
      kind: 'continue',
      reason: 'gap_under_10m',
    });
    expect(
      decideSegment(
        segmentInput({ lastMessageAt: new Date(NOW.getTime() - 2 * 60 * 60_000).toISOString() }),
      ),
    ).toMatchObject({ kind: 'uncertain', reason: 'rules_uncertain' });
    expect(
      decideSegment(
        segmentInput({ lastMessageAt: new Date(NOW.getTime() - 6 * 60 * 60_000).toISOString() }),
      ),
    ).toMatchObject({ kind: 'new', reason: 'gap_over_6h' });
    expect(
      decideSegment(
        segmentInput({ lastMessageAt: new Date(NOW.getTime() - 7 * 60 * 60_000).toISOString() }),
      ),
    ).toMatchObject({ kind: 'new', reason: 'gap_over_6h' });
    // Explicit continuation wording does not cross the 6-hour boundary.
    expect(
      decideSegment({
        ...segmentInput({
          lastMessageAt: new Date(NOW.getTime() - 7 * 60 * 60_000).toISOString(),
          text: '接着看茅台',
        }),
      }),
    ).toMatchObject({ kind: 'new', reason: 'gap_over_6h' });
  });

  it('compares A-share codes and accumulated names with the previous symbols', () => {
    const twoHoursAgo = new Date(NOW.getTime() - 2 * 60 * 60_000).toISOString();
    expect(
      decideSegment(
        segmentInput({ lastMessageAt: twoHoursAgo, text: '宁德时代 300750.SZ 怎么样' }),
      ),
    ).toMatchObject({ kind: 'new', reason: 'symbols_disjoint' });
    expect(
      decideSegment(segmentInput({ lastMessageAt: twoHoursAgo, text: '600519 还值得拿吗' })),
    ).toMatchObject({ kind: 'continue', reason: 'symbols_overlap' });
    expect(
      decideSegment(
        segmentInput({
          lastMessageAt: twoHoursAgo,
          text: '贵州茅台的三季报呢',
          symbolNames: { 贵州茅台: '600519.SH' },
        }),
      ),
    ).toMatchObject({ kind: 'continue', reason: 'symbols_overlap' });
    expect(
      decideSegment(
        segmentInput({
          lastMessageAt: twoHoursAgo,
          text: '宁德时代的三季报呢',
          symbolNames: { 宁德时代: '300750.SZ' },
        }),
      ),
    ).toMatchObject({ kind: 'new', reason: 'symbols_disjoint' });
  });

  it('returns uncertain between 10 minutes and 6 hours when no signal exists', () => {
    const threeHoursAgo = new Date(NOW.getTime() - 3 * 60 * 60_000).toISOString();
    expect(decideSegment(segmentInput({ lastMessageAt: threeHoursAgo }))).toMatchObject({
      kind: 'uncertain',
    });
    expect(
      decideSegment(segmentInput({ lastMessageAt: new Date(NOW.getTime() - 10 * 60_000).toISOString() })),
    ).toMatchObject({ kind: 'uncertain' });
  });
});

describe('symbol parsing', () => {
  it('normalizes codes to a suffixed exchange form and respects explicit suffixes', () => {
    expect(normalizeSymbolCode('600519')).toBe('600519.SH');
    expect(normalizeSymbolCode('000001')).toBe('000001.SZ');
    expect(normalizeSymbolCode('300750')).toBe('300750.SZ');
    expect(normalizeSymbolCode('430047')).toBe('430047.BJ');
    expect(normalizeSymbolCode('830799')).toBe('830799.BJ');
    expect(normalizeSymbolCode('920001')).toBe('920001.BJ');
    expect(normalizeSymbolCode('600519.sz')).toBe('600519.SZ');
    expect(normalizeSymbolCode('300750.SZ')).toBe('300750.SZ');
  });

  it('extracts user codes and name hits, and bot name（code）pairs', () => {
    expect(
      extractUserSymbols('看下 600519 和 000001，还有宁德时代', { 宁德时代: '300750' }),
    ).toEqual([
      { code: '600519.SH', name: '' },
      { code: '000001.SZ', name: '' },
      { code: '300750.SZ', name: '宁德时代' },
    ]);
    expect(extractBotSymbols('贵州茅台（600519）与 宁德时代(300750.sz)')).toEqual([
      { code: '600519.SH', name: '贵州茅台' },
      { code: '300750.SZ', name: '宁德时代' },
    ]);
  });
});

describe('context injection', () => {
  const tasks: ContextTaskLine[] = Array.from({ length: 20 }, (_, index) => ({
    taskId: `task-${index}`,
    date: `2026-11-${String(10 + (index % 10)).padStart(2, '0')}`,
    title: `任务${index}`,
    conclusion: `结论${index}`,
  }));

  it('renders the fixed structure and omits an empty memory section', () => {
    const injection = buildContextInjection({
      userText: '看看茅台',
      recentMessages: [
        {
          role: 'user',
          content: '第一行\n第二行',
          createdAt: '2026-11-16T01:00:00.000Z',
          taskTitle: '看茅台',
        },
      ],
      tasks: tasks.slice(0, 2),
      memory: '',
    });
    expect(injection.text.startsWith('[Chives 上下文：')).toBe(true);
    expect(injection.text).not.toContain('## 你记得的');
    expect(injection.text).toContain('## 最近的对话原文');
    expect(injection.text).toContain('- 2026-11-16 01:00 · 任务「看茅台」· 用户：第一行 第二行');
    expect(injection.text).toContain('## 之前的任务目录');
    expect(injection.text).toContain('需要某个旧任务的细节时，调用 timeline_search。');
    expect(injection.text.endsWith('[用户的新消息]\n看看茅台')).toBe(true);
    expect(injection.meta).toMatchObject({
      recentMessages: 1,
      directoryEntries: 2,
      memoryIncluded: false,
    });
  });

  it('includes memory when present', () => {
    const injection = buildContextInjection({
      userText: '继续',
      recentMessages: [],
      tasks: [],
      memory: '偏好低估值，不接受杠杆。',
    });
    expect(injection.text).toContain('## 你记得的\n偏好低估值，不接受杠杆。');
    expect(injection.meta.memoryIncluded).toBe(true);
  });

  it('keeps at most six recent messages and truncates each at 1200 characters', () => {
    const recent = Array.from({ length: 8 }, (_, index) => ({
      role: 'user' as const,
      content: `${index}:${'x'.repeat(index === 7 ? 1500 : 10)}`,
      createdAt: '2026-11-16T01:00:00.000Z',
      taskTitle: null,
    }));
    const injection = buildContextInjection({ userText: 'hi', recentMessages: recent, tasks: [] });
    expect(injection.meta.recentMessages).toBe(6);
    expect(injection.text).not.toContain('0:');
    expect(injection.text).toContain('7:');
    expect(injection.text).toContain('…');
    const line = injection.text.split('\n').find((entry) => entry.includes('7:'));
    expect(line?.length).toBeLessThan(1200 + 80);
  });

  it('drops directory tail first and shortens the original text at the 8000-character cap', () => {
    const injection = buildContextInjection({
      userText: '问'.repeat(9000),
      recentMessages: Array.from({ length: 6 }, (_, index) => ({
        role: 'bot' as const,
        content: `${index}${'y'.repeat(1200)}`,
        createdAt: '2026-11-16T01:00:00.000Z',
        taskTitle: `任务${index}`,
      })),
      tasks,
    });
    expect(injection.text.length).toBeLessThanOrEqual(MAX_INJECTION_CHARS);
    expect(injection.meta.directoryEntries).toBeLessThan(20);
    expect(injection.text).toContain('…');
    expect(injection.text.endsWith('…')).toBe(true);
  });
});

describe('summary parsing', () => {
  it('parses fenced JSON and normalizes key numbers', () => {
    const parsed = parseSummaryResponse(
      '```json\n{"title":"茅台小结","conclusion":"利润稳","key_numbers":[{"label":"营收","value":123,"source":"三季报","as_of":"2026-10-30"}],"deliverables":["reports/a.md"],"open_questions":["Q1"],"symbols":[{"code":"600519.sh","name":"贵州茅台"}]}\n```',
    );
    expect(parsed).toMatchObject({
      title: '茅台小结',
      conclusion: '利润稳',
      keyNumbers: [{ label: '营收', value: '123', source: '三季报', asOf: '2026-10-30' }],
      deliverables: ['reports/a.md'],
      openQuestions: ['Q1'],
      symbols: [{ code: '600519.SH', name: '贵州茅台' }],
    });
  });

  it('returns null for non-JSON output', () => {
    expect(parseSummaryResponse('抱歉，我无法总结。')).toBeNull();
    expect(parseSummaryResponse('{"title":')).toBeNull();
  });

  it('builds a prompt that forbids tools and invented numbers', () => {
    const prompt = buildSummaryPrompt('看茅台', 't1');
    expect(prompt).toContain('不要调用任何工具');
    expect(prompt).toContain('不要编造');
    expect(prompt).toContain('key_numbers');
  });
});

class TestDriver implements HarnessDriver {
  readonly prompts: string[] = [];

  constructor(
    private readonly summaryReply: string | null = 'not-json',
    private readonly summaryBehavior: 'reply' | 'hang' | 'fail' = 'reply',
  ) {}

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
      sink({ type: 'draft_delta', kind: 'text', text: 'hidden draft' });
      sink({ type: 'tool_start', toolCallId: 'hidden-tool', title: 'hidden', kind: 'read', rawInput: {} });
      if (this.summaryBehavior === 'hang') return new Promise<HarnessPromptResult>(() => undefined);
      if (this.summaryBehavior === 'fail') return Promise.reject(new Error('summary failed'));
      sink({ type: 'message', text: this.summaryReply ?? '' });
      return Promise.resolve({ stopReason: 'end_turn' });
    }
    sink({ type: 'message', text: `回答：${text}` });
    sink({ type: 'usage', used: 100, size: 1000 });
    return Promise.resolve({ stopReason: 'end_turn' });
  }

  cancel(): void {}

  shutdown(): Promise<void> {
    return Promise.resolve();
  }
}

interface ServiceHarness {
  store: Store;
  bus: EventBus;
  events: ServerEvent[];
  driver: TestDriver;
  service: SegmentationService;
  clock: { now: Date };
}

async function serviceHarness(driver = new TestDriver(), summaryTimeoutMs = 200): Promise<ServiceHarness> {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-seg-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: ServerEvent[] = [];
  bus.subscribe((event) => events.push(event));
  const clock = { now: NOW };
  const service = new SegmentationService({
    registry: makeRegistry(),
    store,
    bus,
    driver,
    now: () => clock.now,
    idleCloseMs: 30 * 60_000,
    summaryTimeoutMs,
  });
  cleanups.push(async () => {
    service.stop();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, bus, events, driver, service, clock };
}

function seedTask(
  store: Store,
  options: { title?: string; lastMessageAt?: string; status?: 'done' | 'running' } = {},
): TaskRecord {
  const startedAt = options.lastMessageAt ?? NOW.toISOString();
  const task = store.tasks.create({
    botId: 'expert',
    title: options.title ?? '看下贵州茅台',
    startedAt,
    depth: 0,
    delegated: false,
  });
  store.tasks.setHarnessSession(task.id, `session-${task.id}`);
  store.messages.append({
    id: `u-${task.id}`,
    botId: 'expert',
    taskId: task.id,
    role: 'user',
    kind: 'text',
    content: '看下贵州茅台',
    createdAt: startedAt,
  });
  store.messages.append({
    id: `b-${task.id}`,
    botId: 'expert',
    taskId: task.id,
    role: 'bot',
    kind: 'text',
    content: '茅台三季报结论：营收稳，利润稳。',
    createdAt: startedAt,
  });
  if (options.status !== 'running') {
    store.tasks.finish(task.id, 'done', startedAt);
  }
  const stored = store.tasks.get(task.id);
  if (stored === undefined) throw new Error('seed task missing');
  return stored;
}

describe('SegmentationService summaries', () => {
  it('stores a model summary, updates the title, and publishes task.closed', async () => {
    const harness = await serviceHarness(
      new TestDriver(
        JSON.stringify({
          title: '茅台三季报小结',
          conclusion: '营收与利润都稳。',
          key_numbers: [{ label: '营收', value: '123 亿', source: '三季报', as_of: '2026-10-30' }],
          deliverables: ['reports/maotai.md'],
          open_questions: ['四季度增速？'],
          symbols: [{ code: '600519.SH', name: '贵州茅台' }],
        }),
      ),
    );
    const task = seedTask(harness.store);
    harness.events.length = 0;
    const summary = await harness.service.closeTask(task.id);

    expect(summary).toMatchObject({
      taskId: task.id,
      title: '茅台三季报小结',
      conclusion: '营收与利润都稳。',
      source: 'model',
    });
    expect(summary?.keyNumbers[0]).toMatchObject({ asOf: '2026-10-30' });
    expect(harness.store.tasks.get(task.id)?.title).toBe('茅台三季报小结');
    expect(harness.store.tasks.get(task.id)?.closedAt).not.toBeNull();
    expect(harness.store.summaries.symbolNameMap()).toEqual({ 贵州茅台: '600519.SH' });
    expect(harness.store.taskSymbols.listForTask(task.id)).toMatchObject([
      { code: '600519.SH', name: '贵州茅台' },
    ]);
    expect(harness.events.filter((event) => event.type === 'task.closed')).toHaveLength(1);
  });

  it('falls back when the hidden turn returns non-JSON', async () => {
    const harness = await serviceHarness(new TestDriver('不是 JSON'));
    const task = seedTask(harness.store);
    const summary = await harness.service.closeTask(task.id);
    expect(summary).toMatchObject({
      title: '看下贵州茅台',
      conclusion: '茅台三季报结论：营收稳，利润稳。',
      source: 'fallback',
      keyNumbers: [],
      symbols: [],
    });
  });

  it('falls back on timeout without waiting for the hidden turn', async () => {
    const harness = await serviceHarness(new TestDriver(null, 'hang'), 20);
    const task = seedTask(harness.store);
    const summary = await harness.service.closeTask(task.id);
    expect(summary?.source).toBe('fallback');
    expect(summary?.conclusion).toContain('茅台三季报结论');
  });

  it('does not write timeline messages, tool events, drafts, or deliverables for the hidden turn', async () => {
    const harness = await serviceHarness(new TestDriver(JSON.stringify({ title: '小结', conclusion: '结论' })));
    const task = seedTask(harness.store);
    const beforeMessages = harness.store.messages.listByTask(task.id).length;
    harness.events.length = 0;
    await harness.service.closeTask(task.id);

    expect(harness.store.messages.listByTask(task.id)).toHaveLength(beforeMessages);
    expect(harness.store.toolEvents.listByTask(task.id)).toHaveLength(0);
    expect(harness.store.deliverables.listByTask(task.id)).toHaveLength(0);
    const types = harness.events.map((event) => event.type);
    expect(types).not.toContain('draft.delta');
    expect(types).not.toContain('tool.started');
    expect(types).not.toContain('message.created');
    expect(types).toContain('task.closed');
  });

  it('closes only once even if two callers race', async () => {
    const harness = await serviceHarness(new TestDriver(JSON.stringify({ title: '小结', conclusion: '结论' })));
    const task = seedTask(harness.store);
    const [first, second] = await Promise.all([
      harness.service.closeTask(task.id),
      harness.service.closeTask(task.id),
    ]);
    expect(first?.taskId).toBe(task.id);
    expect(second?.taskId).toBe(task.id);
    expect(harness.driver.prompts.filter((prompt) => prompt.startsWith('[Chives 任务小结]'))).toHaveLength(1);
  });
});

describe('idle closing', () => {
  it('closes stale terminal tasks but not recent or running ones', async () => {
    const harness = await serviceHarness(new TestDriver(JSON.stringify({ title: '小结', conclusion: '结论' })));
    const stale = seedTask(harness.store, {
      lastMessageAt: new Date(NOW.getTime() - 31 * 60_000).toISOString(),
    });
    const recent = seedTask(harness.store, { lastMessageAt: NOW.toISOString() });
    const running = seedTask(harness.store, {
      lastMessageAt: new Date(NOW.getTime() - 60 * 60_000).toISOString(),
      status: 'running',
    });

    await harness.service.scanIdle();

    expect(harness.store.tasks.get(stale.id)?.closedAt).not.toBeNull();
    expect(harness.store.tasks.get(recent.id)?.closedAt).toBeNull();
    expect(harness.store.tasks.get(running.id)?.closedAt).toBeNull();
  });

  it('closes a timed-out task after a restart on the next scan', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-seg-restart-'));
    const first = Store.open(dataDir);
    const task = seedTask(first, {
      lastMessageAt: new Date(NOW.getTime() - 2 * 60 * 60_000).toISOString(),
    });
    first.close();

    const reopened = Store.open(dataDir);
    const bus = new EventBus();
    const service = new SegmentationService({
      registry: makeRegistry(),
      store: reopened,
      bus,
      driver: new TestDriver(JSON.stringify({ title: '小结', conclusion: '结论' })),
      now: () => NOW,
    });
    cleanups.push(async () => {
      service.stop();
      reopened.close();
      await rm(dataDir, { recursive: true, force: true });
    });
    await service.scanIdle();
    expect(reopened.tasks.get(task.id)?.closedAt).not.toBeNull();
  });

  it('cancels a running delegated child when its segment closes', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-seg-child-'));
    const store = Store.open(dataDir);
    const bus = new EventBus();
    const orchestrator = new Orchestrator({
      registry: makeRegistry(),
      store,
      bus,
      driver: new FakeDriver(),
    });
    orchestrator.start();
    cleanups.push(async () => {
      await orchestrator.close();
      store.close();
      await rm(dataDir, { recursive: true, force: true });
    });

    const parent = store.tasks.create({
      botId: 'expert',
      title: '父任务',
      startedAt: NOW.toISOString(),
      depth: 0,
      delegated: false,
    });
    store.tasks.finish(parent.id, 'done', NOW.toISOString());
    const child = store.tasks.create({
      botId: 'research',
      title: '委派：取数',
      startedAt: NOW.toISOString(),
      parentTaskId: parent.id,
      depth: 1,
      delegated: true,
      brief: '取数',
    });

    await orchestrator.segmentation.closeTask(parent.id);
    expect(store.tasks.get(child.id)?.status).toBe('cancelled');
  });
});
