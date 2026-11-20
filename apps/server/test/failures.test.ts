import { AcpProcessExitedError, AcpRpcError, AcpTimeoutError } from '@chives/acp-client';
import { describe, expect, it } from 'vitest';

import {
  ENGINE_START_COMMAND,
  ENGINE_UNAVAILABLE_NOTICE,
  classifyFailure,
  failureMeta,
  failureNotice,
  sanitizeFailureDetail,
} from '../src/failures.js';

describe('classifyFailure', () => {
  const cases: Array<{
    code: string;
    phase: 'session' | 'prompt';
    error: unknown;
    notice: RegExp;
  }> = [
    {
      code: 'harness_unavailable',
      phase: 'session',
      error: new Error('spawn dsh ENOENT'),
      notice: /运行环境没有启动成功/,
    },
    {
      code: 'harness_unavailable',
      phase: 'session',
      error: new AcpTimeoutError('initialize', 120_000),
      notice: /运行环境没有启动成功/,
    },
    {
      code: 'harness_crashed',
      phase: 'prompt',
      error: new AcpProcessExitedError(1, null, ['boot failed']),
      notice: /这一轮中断/,
    },
    {
      code: 'harness_crashed',
      phase: 'prompt',
      error: new Error('harness process exited (code=137, signal=SIGKILL)'),
      notice: /这一轮中断/,
    },
    {
      code: 'model_quota',
      phase: 'prompt',
      error: new AcpRpcError(-32603, 'Internal error', {
        message: '429 Too Many Requests: rate limit exceeded',
      }),
      notice: /模型额度用尽或被限流/,
    },
    {
      code: 'model_quota',
      phase: 'prompt',
      error: new Error('insufficient balance，账户余额不足'),
      notice: /模型额度用尽或被限流/,
    },
    {
      code: 'model_auth',
      phase: 'prompt',
      // Verbatim text seen during T123 acceptance.
      error: new Error('no API key for provider route'),
      notice: /模型密钥没有配置或已失效/,
    },
    {
      code: 'model_auth',
      phase: 'prompt',
      error: new AcpRpcError(-32603, 'Unauthorized', { status: 401 }),
      notice: /模型密钥没有配置或已失效/,
    },
    {
      code: 'network',
      phase: 'prompt',
      error: new Error('getaddrinfo ENOTFOUND api.example.com'),
      notice: /网络不通/,
    },
    {
      code: 'network',
      phase: 'prompt',
      error: new Error('connect ECONNREFUSED 127.0.0.1:8880'),
      notice: /网络不通/,
    },
    {
      code: 'network',
      phase: 'prompt',
      error: new Error('fetch failed'),
      notice: /网络不通/,
    },
    {
      code: 'network',
      phase: 'prompt',
      error: new Error('connect ETIMEDOUT 1.2.3.4:443'),
      notice: /网络不通/,
    },
    {
      code: 'timeout',
      phase: 'prompt',
      error: new AcpTimeoutError('session/prompt', 900_000),
      notice: /这一轮超时/,
    },
    {
      code: 'timeout',
      phase: 'prompt',
      error: new Error('session/prompt timed out after 900000ms'),
      notice: /这一轮超时/,
    },
    {
      code: 'unknown',
      phase: 'prompt',
      error: new Error('something odd happened'),
      notice: /出了点问题/,
    },
  ];

  for (const entry of cases) {
    it(`maps ${entry.code}: ${String(entry.error)}`, () => {
      const failure = classifyFailure(entry.error, entry.phase);
      expect(failure.code).toBe(entry.code);
      expect(failureNotice(failure)).toMatch(entry.notice);
    });
  }

  it('does not leak the local username in an unknown detail', () => {
    const failure = classifyFailure(new Error('boom at /Users/alice/secret/file.ts'), 'prompt');
    expect(failure.code).toBe('unknown');
    expect(failure.detail).not.toContain('alice');
    expect(failureNotice(failure)).toContain('/Users/<user>');
  });

  it('truncates details to 200 characters and redacts token-like strings', () => {
    const failure = classifyFailure(
      new Error(`weird sk-abcdef123456 ${'x'.repeat(300)}`),
      'prompt',
    );
    expect(failure.detail).not.toContain('sk-abcdef123456');
    expect([...failure.detail]).toHaveLength(200);
  });

  it('exposes the engine start command in the notice and meta', () => {
    const meta = failureMeta({ code: 'engine_unavailable', detail: '' });
    expect(meta).toEqual({ code: 'engine_unavailable', command: ENGINE_START_COMMAND });
    expect(ENGINE_UNAVAILABLE_NOTICE).toContain(ENGINE_START_COMMAND);
  });

  it('sanitizes paths without rewriting other text', () => {
    expect(sanitizeFailureDetail('failed at /home/bob/x and /Users/bob/y')).toBe(
      'failed at /home/<user>/x and /Users/<user>/y',
    );
  });
});
