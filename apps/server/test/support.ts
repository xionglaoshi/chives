import type { Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { fileURLToPath } from 'node:url';

import { buildCatalog, loadBots, type BotManifest, type BotRegistry } from '../src/bots/index.js';
import type { ChivesConfig } from '../src/config.js';

export const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));

export function testConfig(dataDir: string): ChivesConfig {
  return {
    repoRoot,
    botsDir: `${repoRoot}/apps/server/test/fixtures/bots`,
    dataDir,
    port: 0,
    harness: 'fake',
    dshHome: '',
    dshOverlay: '',
    gatewayUrl: 'http://127.0.0.1:1',
    maxProcesses: 3,
    idleMs: 60_000,
    delegationConcurrency: 3,
    approvalTimeoutMs: 600_000,
    classifier: 'rules',
    taskIdleCloseMs: 30 * 60_000,
  };
}

export function makeRegistry(): BotRegistry {
  return loadBots(`${repoRoot}/apps/server/test/fixtures/bots`, buildCatalog(repoRoot));
}

export async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve();
    });
  });
  const address = server.address() as AddressInfo;
  return `http://127.0.0.1:${address.port}`;
}

export async function closeServer(server: Server): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error === undefined ? resolve() : reject(error)));
  });
}

export async function waitFor(predicate: () => boolean, timeoutMs = 5000): Promise<void> {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) throw new Error('waitFor timed out');
    await new Promise((resolve) => {
      setTimeout(resolve, 5);
    });
  }
}

export function makeBot(overrides: Partial<BotManifest> = {}): BotManifest {
  return {
    id: 'test-bot',
    name: 'Test Bot',
    role: 'test',
    persona: 'bots/test-bot/persona.md',
    avatar: { emblem: 'crown', tone: 'gold' },
    skills: [],
    mcp: [],
    tools: { code: 'sandboxed', write: 'workspace-only' },
    model: 'default',
    can_delegate_to: [],
    routines: [],
    memory: { user: 'read', bot: 'read-write' },
    background: false,
    trading_guard: false,
    ...overrides,
  };
}
