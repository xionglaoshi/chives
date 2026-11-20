/** Harness-agnostic driver contract consumed by the orchestrator. */

import type { BotManifest } from '../bots/index.js';
import type { TaskRecord } from '../store/index.js';

export type HarnessEvent =
  | { type: 'message'; text: string }
  | { type: 'thought'; text: string }
  | {
      type: 'tool_start';
      toolCallId: string;
      title: string | undefined;
      kind: string | undefined;
      rawInput: unknown;
    }
  | {
      type: 'tool_end';
      toolCallId: string;
      status: 'completed' | 'failed';
      output: string;
      title: string | undefined;
      kind: string | undefined;
    }
  | { type: 'usage'; used: number; size: number }
  | { type: 'draft_reset'; attemptId?: string }
  | { type: 'draft_delta'; kind: 'text' | 'reasoning'; text: string; attemptId?: string }
  | { type: 'draft_commit'; text: string };

export type HarnessSink = (event: HarnessEvent) => void;

export interface HarnessPromptResult {
  /** ACP `stopReason`, e.g. `end_turn` or `cancelled`. */
  stopReason: string;
}

export interface TemporaryPromptOptions {
  timeoutMs?: number;
  /** ACP session config options applied after `session/new`, e.g. `reasoning_effort`. */
  config?: Readonly<Record<string, string>>;
}

/** Optional capability used by the task classifier; never touches the timeline. */
export interface TemporaryPromptDriver {
  temporaryPrompt(
    bot: BotManifest,
    text: string,
    options?: TemporaryPromptOptions,
  ): Promise<string | null>;
}

/** Optional capability used by the hidden task-summary turn. */
export interface HiddenPromptDriver {
  hiddenPrompt(
    bot: BotManifest,
    task: TaskRecord,
    text: string,
    timeoutMs: number,
  ): Promise<string | null>;
}

export interface HarnessDriver {
  /**
   * Returns the harness session for this task, resuming `task.harnessSessionId`
   * when present and creating a fresh session when resume is impossible.
   */
  ensureSession(
    bot: BotManifest,
    task: TaskRecord,
    options?: { silent?: boolean },
  ): Promise<string>;
  prompt(
    bot: BotManifest,
    sessionId: string,
    text: string,
    sink: HarnessSink,
  ): Promise<HarnessPromptResult>;
  cancel(bot: BotManifest, sessionId: string): void | Promise<void>;
  shutdown(): Promise<void>;
}
