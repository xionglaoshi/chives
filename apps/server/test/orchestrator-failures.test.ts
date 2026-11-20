import { AcpProcessExitedError, AcpRpcError, AcpTimeoutError } from '@chives/acp-client';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import type { ServerEvent } from '../src/api/protocol.js';
import { EventBus } from '../src/events/index.js';
import { FakeDriver, type FakeStep } from '../src/harness/fake.js';
import type {
  HarnessDriver,
  HarnessPromptResult,
  HarnessSink,
} from '../src/harness/types.js';
import { Orchestrator } from '../src/orchestrator.js';
import { Store } from '../src/store/index.js';
import type { BotManifest } from '../src/bots/index.js';
import type { TaskRecord } from '../src/store/index.js';
import { makeRegistry, waitFor } from './support.js';

type FailureMode = 'unavailable' | 'crash-once' | 'quota' | 'timeout';

class FailureDriver implements HarnessDriver {
  private promptCalls = 0;

  constructor(private readonly mode: FailureMode) {}

  ensureSession(bot: BotManifest, task: TaskRecord): Promise<string> {
    if (this.mode === 'unavailable') {
      return Promise.reject(Object.assign(new Error('spawn dsh ENOENT'), { code: 'ENOENT' }));
    }
    return Promise.resolve(task.harnessSessionId ?? `session-${bot.id}`);
  }

  prompt(
    _bot: BotManifest,
    _sessionId: string,
    _text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    this.promptCalls += 1;
    if (this.mode === 'crash-once' && this.promptCalls === 1) {
      sink({ type: 'message', text: '中断前已经写下的内容' });
      return Promise.reject(new AcpProcessExitedError(1, null, ['segfault']));
    }
    if (this.mode === 'quota') {
      return Promise.reject(
        new AcpRpcError(-32603, 'Internal error', { message: 'rate limit exceeded (429)' }),
      );
    }
    if (this.mode === 'timeout') {
      return Promise.reject(new AcpTimeoutError('session/prompt', 900_000));
    }
    sink({ type: 'message', text: `恢复后的回答：${_text}` });
    return Promise.resolve({ stopReason: 'end_turn' });
  }

  cancel(): void {}

  shutdown(): Promise<void> {
    return Promise.resolve();
  }
}

const cleanups: Array<() => Promise<void>> = [];

async function setup(driver: HarnessDriver) {
  const dataDir = await mkdtemp(join(tmpdir(), 'chives-failure-'));
  const store = Store.open(dataDir);
  const bus = new EventBus();
  const events: ServerEvent[] = [];
  bus.subscribe((event) => events.push(event));
  const orchestrator = new Orchestrator({ registry: makeRegistry(), store, bus, driver });
  orchestrator.start();
  let closed = false;
  cleanups.push(async () => {
    if (closed) return;
    closed = true;
    await orchestrator.close();
    store.close();
    await rm(dataDir, { recursive: true, force: true });
  });
  return { store, orchestrator, events };
}

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

function notices(store: Store, taskId: string) {
  return store.messages.listByTask(taskId).filter((message) => message.kind === 'notice');
}

describe('turn failures', () => {
  it('keeps the timeline and records harness_unavailable when the process cannot start', async () => {
    const { store, orchestrator, events } = await setup(new FailureDriver('unavailable'));
    const accepted = await orchestrator.submitMessage('expert', '看看茅台');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'failed');

    const task = store.tasks.get(accepted.taskId);
    expect(task?.errorCode).toBe('harness_unavailable');
    const messages = store.messages.listByTask(accepted.taskId);
    expect(messages.map((message) => message.role)).toEqual(['user', 'system']);
    expect(messages[0]?.content).toBe('看看茅台');
    const notice = notices(store, accepted.taskId);
    expect(notice).toHaveLength(1);
    expect(notice[0]?.meta?.['code']).toBe('harness_unavailable');
    expect(notice[0]?.content).toContain('运行环境没有启动成功');
    expect(orchestrator.status('expert')).toBe('error');
    expect(events.find((event) => event.type === 'error')).toMatchObject({
      type: 'error',
      code: 'harness_unavailable',
    });
  });

  it('keeps committed content on a crash and retries the same task without a duplicate user bubble', async () => {
    const driver = new FailureDriver('crash-once');
    const { store, orchestrator, events } = await setup(driver);
    const accepted = await orchestrator.submitMessage('expert', '跑一遍财报');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'failed');

    const task = store.tasks.get(accepted.taskId);
    expect(task?.errorCode).toBe('harness_crashed');
    const messages = store.messages.listByTask(accepted.taskId);
    expect(messages.some((message) => message.content === '中断前已经写下的内容')).toBe(true);
    const notice = notices(store, accepted.taskId);
    expect(notice[0]?.meta?.['code']).toBe('harness_crashed');
    expect(notice[0]?.content).toContain('这一轮中断了，已保留之前的内容');
    expect(events.find((event) => event.type === 'error')).toMatchObject({
      type: 'error',
      code: 'harness_crashed',
    });

    const retried = await orchestrator.retryTask(accepted.taskId);
    expect(retried.taskId).toBe(accepted.taskId);
    expect(retried.messageId).toBe(messages[0]?.id);
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');
    const after = store.messages.listByTask(accepted.taskId);
    expect(after.filter((message) => message.role === 'user')).toHaveLength(1);
    expect(after.filter((message) => message.role === 'bot').length).toBeGreaterThanOrEqual(2);
    expect(store.tasks.get(accepted.taskId)?.errorCode).toBeNull();
  });

  it('records model_quota and timeout codes', async () => {
    const quota = await setup(new FailureDriver('quota'));
    const first = await quota.orchestrator.submitMessage('expert', '额度');
    await waitFor(() => quota.store.tasks.get(first.taskId)?.status === 'failed');
    expect(quota.store.tasks.get(first.taskId)?.errorCode).toBe('model_quota');
    expect(notices(quota.store, first.taskId)[0]?.content).toContain('模型额度用尽或被限流');

    const timed = await setup(new FailureDriver('timeout'));
    const second = await timed.orchestrator.submitMessage('expert', '超时');
    await waitFor(() => timed.store.tasks.get(second.taskId)?.status === 'failed');
    expect(timed.store.tasks.get(second.taskId)?.errorCode).toBe('timeout');
    expect(notices(timed.store, second.taskId)[0]?.content).toContain('这一轮超时');
  });

  it('keeps the turn successful and appends one notice when a tool reports engine_unreachable', async () => {
    const script: FakeStep[] = [
      { type: 'tool_start', toolCallId: 'tool-1', title: 'cn_watch_alerts' },
      {
        type: 'tool_end',
        toolCallId: 'tool-1',
        output: '{"ok":false,"error":{"code":"engine_unreachable"}}',
      },
      { type: 'message', text: '引擎没起来，先给你已有数据。' },
    ];
    const { store, orchestrator } = await setup(new FakeDriver({ script }));
    const accepted = await orchestrator.submitMessage('expert', '今天有什么告警');
    await waitFor(() => store.tasks.get(accepted.taskId)?.status === 'done');

    expect(store.tasks.get(accepted.taskId)?.errorCode).toBeNull();
    const notice = notices(store, accepted.taskId);
    expect(notice).toHaveLength(1);
    expect(notice[0]?.meta).toMatchObject({
      code: 'engine_unavailable',
      command: 'scripts/chives.sh start --engines',
    });
    expect(notice[0]?.content).toContain('盯盘引擎没有启动');
    expect(store.messages.listByTask(accepted.taskId).some((message) => message.role === 'bot')).toBe(
      true,
    );
  });
});

describe('isEngineUnreachable', () => {
  it('matches the structured MCP error, plain or JSON-escaped, but not a mention in text', async () => {
    const { isEngineUnreachable } = await import('../src/orchestrator.js');
    expect(isEngineUnreachable('{"ok":false,"error":{"code":"engine_unreachable","message":"x"}}')).toBe(true);
    expect(isEngineUnreachable('{"text":"{\\"error\\":{\\"code\\": \\"engine_unreachable\\"}}"}')).toBe(true);
    expect(isEngineUnreachable('<skill_content>sync_error 为 `engine_unreachable` 时说明引擎没有启动</skill_content>')).toBe(false);
  });
});
