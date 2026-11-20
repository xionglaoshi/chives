import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { AcpClient, type AcpEvent } from '@chives/acp-client';

import { buildCatalog, loadBots, type BotManifest } from '../../src/bots/index.js';
import { buildMcpServers, dshSpawnSpec } from '../../src/harness/index.js';

/** `CHIVES_DEFAULT_ROUTE=provider/model` selects the route for bots whose manifest says `model: default`. */
function defaultRouteOption(): { routes?: Record<string, { provider: string; model: string }> } {
  const raw = process.env.CHIVES_DEFAULT_ROUTE;
  if (raw === undefined || !raw.includes('/')) return {};
  const [provider, ...rest] = raw.split('/');
  return { routes: { default: { provider: provider ?? '', model: rest.join('/') } } };
}

const enabled = process.env.CHIVES_ACP_INTEGRATION === '1';
const suite = enabled ? describe : describe.skip;
const repoRoot = resolve(fileURLToPath(new URL('../../../../', import.meta.url)));

suite('bot personas over dsh ACP', () => {
  let dataDir = '';
  const catalog = buildCatalog(repoRoot);
  const registry = loadBots(join(repoRoot, 'apps/server/test/fixtures/bots'), catalog);

  beforeAll(() => {
    dataDir = mkdtempSync(join(tmpdir(), 'chives-bots-acp-'));
  });

  afterAll(() => {
    if (dataDir !== '') rmSync(dataDir, { recursive: true, force: true });
  });

  for (const bot of registry.list()) {
    it(`${bot.id} introduces itself as ${bot.name}`, async () => {
      const dshHome = process.env.DSH_FINANCE_HOME;
      const modelOverlay = process.env.DSH_FINANCE_OVERLAY;
      if (dshHome === undefined || modelOverlay === undefined) {
        throw new Error('CHIVES_ACP_INTEGRATION requires DSH_FINANCE_HOME and DSH_FINANCE_OVERLAY');
      }

      const manifest: BotManifest = bot;
      const spec = dshSpawnSpec(manifest, {
        dataDir,
        dshHome,
        modelOverlay,
        personaText: registry.personaText(manifest.id),
        repoRoot,
        ...defaultRouteOption(),
      });
      const client = new AcpClient(
        {
          command: spec.command,
          args: spec.args,
          cwd: spec.cwd,
          env: spec.env,
          stderrLines: 200,
        },
        {
          requestTimeoutMs: 180_000,
          initializeTimeoutMs: 180_000,
          permissionTimeoutMs: 120_000,
          closeGraceMs: 5000,
        },
      );

      const messages: string[] = [];
      client.onEvent((event: AcpEvent) => {
        if (event.type === 'message') messages.push(event.text);
      });

      try {
        await client.initialize();
        const { sessionId } = await client.newSession({
          cwd: spec.cwd,
          mcpServers: buildMcpServers(manifest, spec.env, repoRoot),
        });
        await client.prompt(sessionId, [
          { type: 'text', text: '你是谁？用一句话回答，并说出你的名字。' },
        ]);
        expect(messages.join('')).toContain(manifest.name);
        await client.closeSession(sessionId);
      } finally {
        await client.close();
      }
    }, 300_000);
  }
});
