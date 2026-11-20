import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, describe, expect, it } from 'vitest';
import { parse } from 'yaml';
import type { McpServer, McpStdioServer } from '@chives/acp-client';

import {
  buildDshPatch,
  buildMcpServers,
  dshPatchPath,
  dshSpawnSpec,
  evaluateOverlayEnv,
  loadOverlayMcpConfigs,
  writeDshPatch,
} from '../src/harness/index.js';
import { buildCatalog, loadBots, type BotManifest } from '../src/bots/index.js';

const repoRoot = resolve(fileURLToPath(new URL('../../../', import.meta.url)));
const catalog = buildCatalog(repoRoot);
const registry = loadBots(join(repoRoot, 'apps/server/test/fixtures/bots'), catalog);
const tempDirs: string[] = [];

function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'chives-t123-'));
  tempDirs.push(dir);
  return dir;
}

afterAll(() => {
  for (const dir of tempDirs) rmSync(dir, { recursive: true, force: true });
});

interface PatchDocument {
  id?: string;
  insert?: PatchEntryLike[];
  config?: Record<string, unknown>;
}
interface PatchEntryLike {
  id?: string;
  config?: Record<string, unknown>;
}

function parsePatch(text: string): PatchDocument[] {
  return parse(text) as PatchDocument[];
}

function entry(doc: readonly PatchDocument[], id: string): PatchDocument | undefined {
  for (const item of doc) {
    if (item.id === id) return item;
    for (const nested of item.insert ?? []) {
      if (nested.id === id) return nested;
    }
  }
  return undefined;
}

function personaText(id: string): string {
  return registry.personaText(id);
}

function requireStdio(server: McpServer | undefined): McpStdioServer {
  if (server === undefined || !('command' in server)) throw new Error('expected a stdio MCP declaration');
  return server;
}

describe('buildDshPatch', () => {
  it('emits valid YAML with the shared persona and the streaming plugin for every bot', () => {
    for (const bot of registry.list()) {
      const text = buildDshPatch(bot, { personaText: personaText(bot.id), repoRoot });
      const doc = parsePatch(text);
      const systemPrompt = entry(doc, 'system-prompt');
      expect(systemPrompt?.config?.personaPrefix).toBe(personaText(bot.id));
      expect(entry(doc, 'chives-stream')).toBeDefined();
      expect(entry(doc, 'acp')).toBeUndefined();
    }
  });

  it('embeds the trading guard only when the manifest asks for it', () => {
    const expert = registry.get('expert') as BotManifest;
    const equity = registry.get('equity-analyst') as BotManifest;
    expect(entry(parsePatch(buildDshPatch(expert, { personaText: personaText(expert.id), repoRoot })), 'fin-trading-guard')).toBeDefined();
    expect(entry(parsePatch(buildDshPatch(equity, { personaText: personaText(equity.id), repoRoot })), 'fin-trading-guard')).toBeUndefined();
  });

  it('writes provider/model only for a non-default route supplied by the caller', () => {
    const base = registry.get('equity-analyst') as BotManifest;
    const routed: BotManifest = { ...base, model: 'fast' };
    const doc = parsePatch(
      buildDshPatch(routed, {
        personaText: personaText(base.id),
        repoRoot,
        routes: { fast: { provider: 'test-provider', model: 'test-model' } },
      }),
    );
    expect(entry(doc, 'acp')?.config).toEqual({ provider: 'test-provider', model: 'test-model' });
    expect(() =>
      buildDshPatch({ ...base, model: 'missing-route' }, { personaText: personaText(base.id), repoRoot }),
    ).toThrow(/requires model route "missing-route"/);
  });

  it('routes skill discovery to the per-bot directory', () => {
    const dir = tempDir();
    for (const bot of registry.list()) {
      const doc = parsePatch(
        buildDshPatch(bot, { personaText: personaText(bot.id), repoRoot, dataDir: dir }),
      );
      const rows = doc.filter((item) => item.id === 'skill-filesystem');
      expect(rows).toHaveLength(1);
      expect(rows[0]?.config).toEqual({
        includeDefaultRoots: false,
        customSkillDirs: [join(dir, 'bots', bot.id, 'skills')],
      });
    }
  });

  it('writes <dataDir>/harness/dsh/<bot>.patch.yml when dataDir is set', () => {
    const dir = tempDir();
    const expert = registry.get('expert') as BotManifest;
    const text = buildDshPatch(expert, { personaText: personaText(expert.id), repoRoot, dataDir: dir });
    const path = dshPatchPath(dir, expert.id);
    expect(existsSync(path)).toBe(true);
    expect(readFileSync(path, 'utf8')).toBe(text);
    expect(writeDshPatch(expert, { personaText: personaText(expert.id), repoRoot, dataDir: dir })).toBe(path);
  });
});

/**
 * The overlays carry absolute paths of the checkout they were written in (see overlays/*.cordis.yml), which is
 * not necessarily this checkout (e.g. a fresh clone). Expectations about overlay-derived paths use that root.
 */
const overlayRoot = (/^\s*cwd:\s*(\S+)\s*$/m.exec(
  readFileSync(join(repoRoot, 'overlays/cn-data.cordis.yml'), 'utf8'),
)?.[1] ?? repoRoot);

describe('buildMcpServers', () => {
  const expert = registry.get('expert') as BotManifest;
  const env = {
    GILDATA_TOKEN: 'test-token',
    DSH_HOME: '/tmp/dsh-home',
    HOME: '/tmp/home',
    CHIVES_HUB_URL: '',
  };

  it('returns the manifest MCP servers plus the built-in chives server', () => {
    const servers = buildMcpServers(expert, env, repoRoot);
    expect(servers.map((server) => server.name)).toEqual([...expert.mcp, 'chives']);
    expect(servers.some((server) => server.name === 'fmp')).toBe(false);
    expect(servers.some((server) => server.name === 'openbb')).toBe(false);
    expect(servers.some((server) => server.name === 'x')).toBe(false);

    const reportBuilder = registry.get('report-builder') as BotManifest;
    expect(buildMcpServers(reportBuilder, env, repoRoot).map((server) => server.name)).toEqual([
      'chives',
    ]);
  });

  it('always declares an env array, even when empty (dsh skips stdio servers without one)', () => {
    for (const server of buildMcpServers(expert, env, repoRoot)) {
      expect(Array.isArray((server as McpStdioServer).env)).toBe(true);
    }
  });

  it('replaces paper_broker --state-dir with CHIVES_PAPER_STATE_DIR when provided', () => {
    const original = requireStdio(
      buildMcpServers(expert, env, repoRoot).find((item) => item.name === 'paper_broker'),
    );
    const originalIndex = original.args?.indexOf('--state-dir') ?? -1;
    expect(originalIndex).toBeGreaterThanOrEqual(0);
    expect(original.args?.[originalIndex + 1]).toBe(join(overlayRoot, 'runtime/paper'));

    const overridden = requireStdio(
      buildMcpServers(expert, env, repoRoot, {}, { paperStateDir: '/tmp/chives-paper-test' }).find(
        (item) => item.name === 'paper_broker',
      ),
    );
    const overriddenIndex = overridden.args?.indexOf('--state-dir') ?? -1;
    expect(overridden.args?.[overriddenIndex + 1]).toBe('/tmp/chives-paper-test');
    expect(overridden.args?.includes(join(overlayRoot, 'runtime/paper'))).toBe(false);
  });

  it('always attaches chives with a Node command and the session token env', () => {
    const servers = buildMcpServers(expert, env, repoRoot, {
      api: 'http://127.0.0.1:8880',
      token: 'session-token',
    });
    const chives = requireStdio(servers.find((item) => item.name === 'chives'));
    expect(chives.command).toBe(process.execPath);
    expect(chives.args).toEqual([join(repoRoot, 'packages/chives-mcp/dist/main.js')]);
    expect(chives.env).toEqual([
      { name: 'CHIVES_API', value: 'http://127.0.0.1:8880' },
      { name: 'CHIVES_SESSION_TOKEN', value: 'session-token' },
      { name: 'CHIVES_FEATURES', value: 'market,portfolio,watches' },
    ]);
  });

  it('declares CHIVES_FEATURES from the bot panels', () => {
    const withWatches = requireStdio(
      buildMcpServers(expert, env, repoRoot, { features: ['watches'] }).find(
        (item) => item.name === 'chives',
      ),
    );
    expect(withWatches.env).toContainEqual({ name: 'CHIVES_FEATURES', value: 'watches' });

    const reportBuilder = registry.get('report-builder') as BotManifest;
    const without = requireStdio(
      buildMcpServers(reportBuilder, env, repoRoot, { features: [] }).find(
        (item) => item.name === 'chives',
      ),
    );
    expect(without.env).toContainEqual({ name: 'CHIVES_FEATURES', value: '' });
  });

  it('injects CHIVES_STRATEGIES into the strategy MCP per bot', () => {
    const bot = registry.get('zhushenglang') as BotManifest;
    const server = requireStdio(
      buildMcpServers(bot, env, repoRoot, {}, { strategies: bot.strategies ?? [] }).find(
        (item) => item.name === 'strategy',
      ),
    );
    expect(server.env).toContainEqual({ name: 'CHIVES_STRATEGIES', value: 'zhushenglang' });
    expect(server.env?.some((entry) => entry.name === 'CHIVES_STRATEGIES' && entry.value === '')).toBe(
      false
    );
  });

  it('wraps overlays with cwd in a /bin/sh cd exec wrapper', () => {
    const market = loadOverlayMcpConfigs(repoRoot).byServer.get('cn_market');
    if (market === undefined || market.cwd === undefined) throw new Error('cn_market overlay is missing');
    const server = requireStdio(
      buildMcpServers(expert, env, overlayRoot).find((item) => item.name === 'cn_market'),
    );
    expect(server.name).toBe('cn_market');
    expect(server.command).toBe('/bin/sh');
    expect(server.args?.slice(0, 3)).toEqual(['-c', 'cd "$0" && exec "$@"', market.cwd]);
    expect(server.args?.slice(3)).toEqual([market.command, ...market.args]);
  });

  it('evaluates the three supported !!js shapes and omits empty values', () => {
    const envBots: BotManifest = { ...expert, mcp: ['cn_data', 'portfolio', 'market_watch'] };
    const servers = buildMcpServers(envBots, env, repoRoot);
    const cnData = requireStdio(servers.find((item) => item.name === 'cn_data'));
    expect(cnData.env).toEqual([{ name: 'GILDATA_TOKEN', value: 'test-token' }]);

    const portfolio = requireStdio(servers.find((item) => item.name === 'portfolio'));
    expect(portfolio.env).toEqual([{ name: 'DSH_HOME', value: '/tmp/dsh-home' }]);

    const marketWatch = requireStdio(servers.find((item) => item.name === 'market_watch'));
    expect(marketWatch.env).toEqual([{ name: 'MARKET_WATCH_URL', value: 'http://127.0.0.1:8866' }]);

    const noToken = requireStdio(
      buildMcpServers(envBots, { HOME: '/tmp/home' }, repoRoot).find((item) => item.name === 'cn_data'),
    );
    expect(noToken.env).toEqual([]);

    expect(servers.some((item) => item.name === 'hub')).toBe(false);

    const fallback = requireStdio(
      buildMcpServers(envBots, { HOME: '/tmp/home' }, repoRoot).find((item) => item.name === 'portfolio'),
    );
    expect(fallback.env).toEqual([{ name: 'DSH_HOME', value: '/tmp/home/.dsh' }]);
  });

  it('rejects unknown !!js shapes instead of evaluating them', () => {
    expect(evaluateOverlayEnv("process.env.X ?? ''", { X: 'value' })).toBe('value');
    expect(evaluateOverlayEnv("(process.env.X || '')", { X: 'value' })).toBe('value');
    expect(
      evaluateOverlayEnv("(process.env.DSH_HOME || (process.env.HOME + '/.dsh'))", {
        HOME: '/tmp/home',
      }),
    ).toBe('/tmp/home/.dsh');
    expect(() => evaluateOverlayEnv('process.env.X', { X: 'value' }, 'fixture')).toThrow(
      /unsupported !!js expression at fixture/,
    );
  });
});

describe('dshSpawnSpec', () => {
  it('spawns via npx with the model overlay, generated patch and per-bot workspace', () => {
    const dataDir = tempDir();
    const expert = registry.get('expert') as BotManifest;
    const spec = dshSpawnSpec(expert, {
      dataDir,
      dshHome: '/tmp/dsh-home',
      modelOverlay: '/tmp/model-overlay.cordis.yml',
      personaText: personaText(expert.id),
      repoRoot,
      env: { PATH: '/tmp/bin' },
    });

    expect(spec.command).toBe('npx');
    expect(spec.args).toEqual([
      '-y',
      '@deepseek-ai/dsh@0.2.2-rc.1',
      '--profile',
      'acp',
      '--patch',
      '/tmp/model-overlay.cordis.yml',
      '--patch',
      dshPatchPath(dataDir, 'expert'),
    ]);
    expect(spec.env.DSH_HOME).toBe('/tmp/dsh-home');
    expect(spec.env.DSH_PERMISSION_MODE).toBe('workspace-write');
    expect(spec.env.DSH_TELEMETRY_MODE).toBe('DISABLED');
    expect(spec.cwd).toBe(join(dataDir, 'bots', 'expert', 'workspace'));
    expect(statSync(spec.cwd).isDirectory()).toBe(true);
    expect(existsSync(dshPatchPath(dataDir, 'expert'))).toBe(true);
    const skillsDir = join(dataDir, 'bots', 'expert', 'skills');
    expect(statSync(skillsDir).isDirectory()).toBe(true);
    expect(readdirSync(skillsDir).sort()).toEqual([...expert.skills].sort());
  });
});

describe('mcpEnvironment', () => {
  it('gives the portfolio and profile MCPs the same DSH_HOME as the dsh child', async () => {
    const { mcpEnvironment } = await import('../src/harness/dsh-driver.js');
    const expert = registry.get('expert') as BotManifest;
    // The server itself has no DSH_HOME, only HOME; without the override this falls back to ~/.dsh.
    const env = mcpEnvironment({ HOME: '/tmp/home' }, '/tmp/chives-home');
    const servers = buildMcpServers(expert, env, repoRoot) as McpStdioServer[];
    for (const name of ['portfolio', 'profile']) {
      const server = servers.find((entry) => entry.name === name);
      expect(server, name).toBeDefined();
      expect(server?.env.find((pair) => pair.name === 'DSH_HOME')?.value).toBe('/tmp/chives-home');
    }
  });
});
