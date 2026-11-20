import { afterEach, describe, expect, it } from 'vitest';

import {
  AcpProcess,
  AcpProcessExitedError,
  AcpTimeoutError,
  type AcpExitInfo,
} from '../src/index.js';
import { makeLog, fakeSpawnSpec, isRecord, waitFor, type LogContext } from './helpers.js';

const cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups.splice(0)) await cleanup();
});

function createProcess(scenario: string, log: LogContext): AcpProcess {
  const process = new AcpProcess(fakeSpawnSpec({ scenario, logPath: log.logPath }), {
    onRequest: async () => ({}),
    onNotification: () => undefined,
  });
  cleanups.push(async () => {
    await process.close();
  });
  return process;
}

describe('AcpProcess', () => {
  it('correlates requests and responses over newline JSON-RPC', async () => {
    const log = await makeLog();
    cleanups.push(log.cleanup);
    const process = createProcess('normal', log);
    const result = await process.request('initialize', { protocolVersion: 1 });
    expect(isRecord(result)).toBe(true);
    expect(result).toMatchObject({ protocolVersion: 1 });
    const messages = await log.read();
    expect(messages[0]).toMatchObject({ jsonrpc: '2.0', method: 'initialize' });
  });

  it('rejects a request with AcpTimeoutError when no response arrives', async () => {
    const log = await makeLog();
    cleanups.push(log.cleanup);
    const process = createProcess('silent', log);
    await process.request('initialize', { protocolVersion: 1 });
    await expect(process.request('session/prompt', {}, 50)).rejects.toBeInstanceOf(AcpTimeoutError);
  });

  it('fails pending requests on exit and reports code plus stderr tail', async () => {
    const log = await makeLog();
    cleanups.push(log.cleanup);
    const process = createProcess('crash', log);
    const exits: AcpExitInfo[] = [];
    process.onExit((info) => exits.push(info));
    await process.request('initialize', { protocolVersion: 1 });
    await expect(process.request('session/prompt', {}, 2000)).rejects.toBeInstanceOf(AcpProcessExitedError);
    await waitFor(() => exits.length === 1);
    expect(exits[0]?.code).toBe(1);
    expect(exits[0]?.stderrTail.join('\n')).toContain('fake-agent: crashing');
  });

  it('close is idempotent and returns the exit info', async () => {
    const log = await makeLog();
    cleanups.push(log.cleanup);
    const process = createProcess('normal', log);
    await process.request('initialize', { protocolVersion: 1 });
    const first = await process.close();
    const second = await process.close();
    expect(first.code).toBe(0);
    expect(second.code).toBe(0);
    expect(process.exited).toBe(true);
  });
});
