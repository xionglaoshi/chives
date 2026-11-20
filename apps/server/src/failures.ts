/** Classifies harness/model/network failures into stable codes and user-facing notices. */

import { AcpProcessExitedError, AcpTimeoutError } from '@chives/acp-client';

import type { FailureCode, StatusFailureDto } from './api/protocol.js';
import type { MessageRecord, TaskRecord } from './store/index.js';

export type FailurePhase = 'session' | 'prompt';

export interface ClassifiedFailure {
  code: FailureCode;
  /** Sanitized, truncated technical detail for the `unknown` summary. */
  detail: string;
}

const MODEL_QUOTA = /(?:^|[^a-z])(quota|rate limit|rate_limit|insufficient|too many requests)(?:[^a-z]|$)/;
const MODEL_QUOTA_CODE = /(?:^|[^0-9])429(?:[^0-9]|$)/;
const MODEL_AUTH = /(no api key|invalid api key|unauthorized|authentication|(?:^|[^0-9])401(?:[^0-9]|$))/;
const NETWORK = /(enotfound|econnrefused|fetch failed|etimedout|network error|network is unreachable)/;
const TIMEOUT = /(timed out|timeout)/;
const SPAWN = /(spawn|enoent|eacces|no such file|executable|not found)/;
const CRASH = /(harness process exited|process exited|epipe|broken pipe)/;
const INITIALIZE = /(initialize|initialise|handshake)/;

export const ENGINE_START_COMMAND = 'scripts/chives.sh start --engines';
export const ENGINE_UNAVAILABLE_NOTICE =
  `盯盘引擎没有启动，相关数据暂时取不到。在终端运行 ${ENGINE_START_COMMAND} 后重试。`;

const NOTICES: Record<Exclude<FailureCode, 'unknown'>, string> = {
  harness_unavailable: '运行环境没有启动成功。检查 dsh 是否可用后重试。',
  harness_crashed: '这一轮中断了，已保留之前的内容。',
  model_quota: '模型额度用尽或被限流，稍后再试。',
  model_auth: '模型密钥没有配置或已失效。',
  network: '网络不通，恢复后重试。',
  engine_unavailable: ENGINE_UNAVAILABLE_NOTICE,
  timeout: '这一轮超时，已停止。',
};

function collectText(value: unknown, depth: number, seen: Set<unknown>, out: string[]): void {
  if (depth > 4 || value === null || value === undefined) return;
  if (typeof value === 'string') {
    out.push(value);
    return;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    out.push(String(value));
    return;
  }
  if (typeof value !== 'object' || seen.has(value)) return;
  seen.add(value);
  if (value instanceof Error) {
    out.push(value.name, value.message);
    collectText((value as { cause?: unknown }).cause, depth + 1, seen, out);
  }
  if (value instanceof AcpProcessExitedError) {
    out.push(...value.stderrTail);
  }
  if (value instanceof AcpTimeoutError) {
    out.push(value.method);
  }
  const record = value as Record<string, unknown>;
  for (const key of ['code', 'message', 'data', 'cause', 'error', 'detail', 'body']) {
    if (key in record) collectText(record[key], depth + 1, seen, out);
  }
}

function haystack(error: unknown): string {
  const parts: string[] = [];
  collectText(error, 0, new Set(), parts);
  return parts.join('\n').toLowerCase();
}

function rawDetail(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  return text.trim() === '' ? '未知错误' : text.trim();
}

/** Replaces local usernames and token-like strings before a detail reaches the UI. */
export function sanitizeFailureDetail(text: string, limit = 200): string {
  const cleaned = text
    .replace(/\/Users\/[^/\s]+/g, '/Users/<user>')
    .replace(/\/home\/[^/\s]+/g, '/home/<user>')
    .replace(/[A-Za-z]:\\Users\\[^\\\s]+/g, 'C:\\Users\\<user>')
    .replace(/\bsk-[A-Za-z0-9_-]{6,}\b/g, '[redacted]');
  return [...cleaned].slice(0, limit).join('');
}

/**
 * A spawn/initialize failure can only happen before the first prompt; during a
 * prompt the same exit means the process crashed mid-turn.
 */
export function classifyFailure(error: unknown, phase: FailurePhase): ClassifiedFailure {
  const text = haystack(error);
  const detail = sanitizeFailureDetail(rawDetail(error));
  if (MODEL_QUOTA.test(text) || MODEL_QUOTA_CODE.test(text) || /额度|余额/.test(text)) {
    return { code: 'model_quota', detail };
  }
  if (MODEL_AUTH.test(text)) return { code: 'model_auth', detail };
  if (phase === 'session') {
    if (
      error instanceof AcpProcessExitedError ||
      error instanceof AcpTimeoutError ||
      INITIALIZE.test(text) ||
      SPAWN.test(text) ||
      TIMEOUT.test(text)
    ) {
      return { code: 'harness_unavailable', detail };
    }
  }
  if (error instanceof AcpProcessExitedError || CRASH.test(text)) {
    return { code: phase === 'session' ? 'harness_unavailable' : 'harness_crashed', detail };
  }
  if (NETWORK.test(text)) return { code: 'network', detail };
  if (error instanceof AcpTimeoutError || TIMEOUT.test(text)) return { code: 'timeout', detail };
  return { code: 'unknown', detail };
}

/** The one-sentence Chinese notice shown in the timeline. */
export function failureNotice(failure: ClassifiedFailure): string {
  if (failure.code === 'unknown') return `出了点问题：${failure.detail}`;
  return NOTICES[failure.code];
}

export function failureMeta(failure: ClassifiedFailure): Record<string, unknown> {
  return {
    code: failure.code,
    ...(failure.code === 'engine_unavailable' ? { command: ENGINE_START_COMMAND } : {}),
  };
}

/** Builds the `GET /api/status` failure entry from a task plus its notice message. */
export function statusFailure(
  task: TaskRecord,
  noticeFor: (taskId: string) => MessageRecord | undefined,
): StatusFailureDto | null {
  if (task.errorCode === null) return null;
  const notice = noticeFor(task.id);
  return {
    code: task.errorCode as FailureCode,
    taskId: task.id,
    botId: task.botId,
    message: notice?.content ?? '任务失败',
    at: task.endedAt ?? task.startedAt,
  };
}
