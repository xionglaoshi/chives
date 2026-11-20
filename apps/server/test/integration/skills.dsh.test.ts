import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { AcpClient, type AcpEvent } from '@chives/acp-client';

import { buildCatalog, loadBots } from '../../src/bots/index.js';
import { buildMcpServers, dshSpawnSpec } from '../../src/harness/index.js';

/** `CHIVES_DEFAULT_ROUTE=provider/model` selects the route for bots whose manifest says `model: default`. */
function defaultRouteOption(): { routes?: Record<string, { provider: string; model: string }> } {
  const raw = process.env.CHIVES_DEFAULT_ROUTE;
  if (raw === undefined || !raw.includes('/')) return {};
  const [provider, ...rest] = raw.split('/');
  return { routes: { default: { provider: provider ?? '', model: rest.join('/') } } };
}

/** Kebab-case skill names in the answer; the prompt forbids prose, so any hyphenated token is a claim. */

const enabled = process.env.CHIVES_ACP_INTEGRATION === '1';
const suite = enabled ? describe : describe.skip;
const repoRoot = resolve(fileURLToPath(new URL('../../../../', import.meta.url)));

suite('skill isolation over dsh ACP', () => {
  let dataDir = '';
  const catalog = buildCatalog(repoRoot);
  const registry = loadBots(join(repoRoot, 'apps/server/test/fixtures/bots'), catalog);

  beforeAll(() => {
    dataDir = mkdtempSync(join(tmpdir(), 'chives-skills-acp-'));
  });

  afterAll(() => {
    if (dataDir !== '') rmSync(dataDir, { recursive: true, force: true });
  });

  for (const bot of registry.list()) {
    it(`${bot.id} can load its own skills and cannot load others`, async () => {
      const dshHome = process.env.DSH_FINANCE_HOME;
      const modelOverlay = process.env.DSH_FINANCE_OVERLAY;
      if (dshHome === undefined || modelOverlay === undefined) {
        throw new Error('CHIVES_ACP_INTEGRATION requires DSH_FINANCE_HOME and DSH_FINANCE_OVERLAY');
      }

      const spec = dshSpawnSpec(bot, {
        dataDir,
        dshHome,
        modelOverlay,
        personaText: registry.personaText(bot.id),
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

      // Judge by tool results, not prose: a model asked to *list* skills may echo names it read in the shared
      // rules. Loading a skill through the harness's skill tool is what isolation must actually control.
      const own = bot.skills[0];
      const foreign = catalog.skills.find((name) => !bot.skills.includes(name));
      if (foreign === undefined) throw new Error('catalog has no skill outside this bot');
      const starts = new Map<string, string>();
      const ends = new Map<string, { status: string; output: string }>();
      client.onEvent((event: AcpEvent) => {
        if (event.type === 'tool_start') {
          const name = (event.rawInput as { name?: unknown } | undefined)?.name;
          if (typeof name === 'string') starts.set(event.toolCallId, name);
        }
        if (event.type === 'tool_end') ends.set(event.toolCallId, { status: event.status, output: event.output ?? '' });
      });
      const outcome = (skill: string): { status: string; output: string } | undefined => {
        for (const [id, name] of starts) if (name === skill) return ends.get(id);
        return undefined;
      };

      try {
        await client.initialize();
        const { sessionId } = await client.newSession({
          cwd: spec.cwd,
          mcpServers: buildMcpServers(bot, spec.env, repoRoot),
        });
        const targets = own === undefined ? [foreign] : [own, foreign];
        await client.prompt(sessionId, [
          {
            type: 'text',
            text: `测试：依次用 skill 工具加载这些 skill：${targets.join('、')}。每个都要真的调用一次工具，即使你认为会失败；不要做别的，最后一句话说明结果。`,
          },
        ]);
        if (own !== undefined) expect(outcome(own)?.status).toBe('completed');
        expect(outcome(foreign)?.status).toBe('failed');
        expect(outcome(foreign)?.output ?? '').toMatch(/unknown|not available|no longer available/i);
        await client.closeSession(sessionId);
      } finally {
        await client.close();
      }
    }, 300_000);
  }
});
