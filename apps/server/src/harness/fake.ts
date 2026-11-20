/** Scriptable in-process harness used by tests and front-end development. */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import type { BotManifest } from '../bots/index.js';
import type { TaskRecord } from '../store/index.js';
import type { HarnessDriver, HarnessEvent, HarnessPromptResult, HarnessSink } from './types.js';

export type FakeStep =
  | { type: 'draft_reset'; attemptId?: string }
  | { type: 'draft_delta'; kind?: 'text' | 'reasoning'; text: string; attemptId?: string }
  | { type: 'draft_commit'; text: string }
  | { type: 'thought'; text: string }
  | {
      type: 'tool_start';
      toolCallId: string;
      title: string;
      kind?: string;
      rawInput?: unknown;
    }
  | {
      type: 'tool_end';
      toolCallId: string;
      status?: 'completed' | 'failed';
      output?: string;
      title?: string;
      kind?: string;
    }
  | { type: 'message'; text: string }
  | { type: 'write'; path: string; content: string }
  | { type: 'usage'; used: number; size: number }
  | { type: 'delay'; ms: number }
  | { type: 'fail'; message?: string };

export interface FakeDriverOptions {
  script?: readonly FakeStep[];
  /** Pause before each scripted step. Defaults to 2 ms. */
  delayMs?: number;
  /** Lets a scripted `write` step land in the bot's workspace during tests. */
  workspaceDirFor?: (bot: BotManifest) => string;
}

export const FAKE_DEFAULT_SCRIPT: readonly FakeStep[] = [
  { type: 'draft_reset', attemptId: 'fake-attempt-1' },
  { type: 'draft_delta', kind: 'text', text: '正在处理：', attemptId: 'fake-attempt-1' },
  { type: 'draft_commit', text: '模拟回答' },
  {
    type: 'tool_start',
    toolCallId: 'fake-tool-1',
    title: 'market_quote',
    kind: 'read',
    rawInput: { codes: ['600519.SH'] },
  },
  {
    type: 'tool_end',
    toolCallId: 'fake-tool-1',
    status: 'completed',
    output: '{"symbol":"600519.SH","price":1500}',
  },
  { type: 'message', text: '模拟回答：{text}' },
  { type: 'usage', used: 1234, size: 1_000_000 },
];

function interpolate(template: string, text: string, bot: BotManifest): string {
  return template.replaceAll('{text}', text).replaceAll('{bot}', bot.name);
}

function sleep(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * Deterministic driver: emits the configured script for every prompt. It can
 * fail on demand (`{type:'fail'}`) and honours cancellation between steps.
 */
export class FakeDriver implements HarnessDriver {
  private readonly script: readonly FakeStep[];
  private readonly delayMs: number;
  private readonly workspaceDirFor: ((bot: BotManifest) => string) | undefined;
  private readonly cancelled = new Set<string>();
  private stopped = false;

  constructor(options: FakeDriverOptions = {}) {
    this.script = options.script ?? FAKE_DEFAULT_SCRIPT;
    this.delayMs = options.delayMs ?? 2;
    this.workspaceDirFor = options.workspaceDirFor;
  }

  ensureSession(bot: BotManifest, task: TaskRecord): Promise<string> {
    if (task.harnessSessionId !== null) return Promise.resolve(task.harnessSessionId);
    return Promise.resolve(`fake-${bot.id}-${task.id}`);
  }

  async prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult> {
    this.cancelled.delete(sessionId);
    for (const step of this.script) {
      if (this.stopped || this.cancelled.has(sessionId)) return { stopReason: 'cancelled' };
      await sleep(this.delayMs);
      if (this.stopped || this.cancelled.has(sessionId)) return { stopReason: 'cancelled' };
      switch (step.type) {
        case 'delay':
          await sleep(step.ms);
          break;
        case 'fail':
          throw new Error(step.message ?? 'fake harness failure');
        case 'message':
          sink({ type: 'message', text: interpolate(step.text, text, bot) });
          break;
        case 'write': {
          const root = this.workspaceDirFor?.(bot);
          if (root === undefined) throw new Error('fake driver has no workspaceDirFor');
          const target = join(root, step.path);
          mkdirSync(dirname(target), { recursive: true });
          writeFileSync(target, step.content);
          break;
        }
        case 'thought':
          sink({ type: 'thought', text: step.text });
          break;
        case 'draft_reset':
          sink(step.attemptId === undefined
            ? { type: 'draft_reset' }
            : { type: 'draft_reset', attemptId: step.attemptId });
          break;
        case 'draft_delta':
          sink({
            type: 'draft_delta',
            kind: step.kind ?? 'text',
            text: step.text,
            ...(step.attemptId === undefined ? {} : { attemptId: step.attemptId }),
          });
          break;
        case 'draft_commit':
          sink({ type: 'draft_commit', text: interpolate(step.text, text, bot) });
          break;
        case 'tool_start':
          sink({
            type: 'tool_start',
            toolCallId: step.toolCallId,
            title: step.title,
            kind: step.kind,
            rawInput: step.rawInput,
          });
          break;
        case 'tool_end': {
          const event: HarnessEvent = {
            type: 'tool_end',
            toolCallId: step.toolCallId,
            status: step.status ?? 'completed',
            output: step.output ?? '',
            title: step.title,
            kind: step.kind,
          };
          sink(event);
          break;
        }
        case 'usage':
          sink({ type: 'usage', used: step.used, size: step.size });
          break;
        default:
          break;
      }
    }
    return { stopReason: 'end_turn' };
  }

  cancel(_bot: BotManifest, sessionId: string): void {
    this.cancelled.add(sessionId);
  }

  shutdown(): Promise<void> {
    this.stopped = true;
    this.cancelled.clear();
    return Promise.resolve();
  }
}
