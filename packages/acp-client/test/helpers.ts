import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { AcpSpawnSpec } from '../src/index.js';

export const fakeAgentPath = fileURLToPath(new URL('./fake-agent.mjs', import.meta.url));

export interface LogContext {
  directory: string;
  logPath: string;
  read: () => Promise<Record<string, unknown>[]>;
  cleanup: () => Promise<void>;
}

export async function makeLog(): Promise<LogContext> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-acp-test-'));
  const logPath = join(directory, 'requests.ndjson');
  return {
    directory,
    logPath,
    read: async () => {
      let text: string;
      try {
        text = await readFile(logPath, 'utf8');
      } catch {
        return [];
      }
      const messages: Record<string, unknown>[] = [];
      for (const line of text.split('\n')) {
        if (line.trim().length === 0) continue;
        messages.push(JSON.parse(line) as Record<string, unknown>);
      }
      return messages;
    },
    cleanup: async () => {
      await rm(directory, { recursive: true, force: true });
    },
  };
}

export interface FakeSpawnOptions {
  scenario?: string;
  logPath?: string;
  env?: Record<string, string | undefined>;
  stderrLines?: number;
}

export function fakeSpawnSpec(options: FakeSpawnOptions = {}): AcpSpawnSpec {
  return {
    command: process.execPath,
    args: [fakeAgentPath],
    env: {
      ...process.env,
      FAKE_AGENT_SCENARIO: options.scenario ?? 'normal',
      ...(options.logPath === undefined ? {} : { FAKE_AGENT_LOG: options.logPath }),
      ...options.env,
    },
    ...(options.stderrLines === undefined ? {} : { stderrLines: options.stderrLines }),
  };
}

export async function waitFor(
  predicate: () => boolean,
  timeoutMs = 3000,
  intervalMs = 10,
): Promise<void> {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) throw new Error('waitFor timed out');
    await new Promise((resolve) => {
      setTimeout(resolve, intervalMs);
    });
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
