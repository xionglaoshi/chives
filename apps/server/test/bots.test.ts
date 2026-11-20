import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  BotLoadError,
  buildCatalog,
  loadBots,
  parseBotManifest,
  type BotManifest,
} from '../src/bots/index.js';

const repoRoot = resolve(fileURLToPath(new URL('../../../', import.meta.url)));
const catalog = buildCatalog(repoRoot);
const botsDir = join(repoRoot, 'apps/server/test/fixtures/bots');

describe('buildCatalog', () => {
  it('discovers all installed skills and MCP names from in-use overlays', () => {
    expect(catalog.skills).toContain('earnings-analysis');
    expect(catalog.skills).toContain('research-conventions');
    expect(catalog.mcp).toContain('cn_data');
    expect(catalog.mcp).toContain('paper_broker');
    expect(catalog.mcp).toContain('cn_watch');
    expect(catalog.mcp).not.toContain('fmp');
    expect(catalog.mcp).not.toContain('openbb');
    expect(catalog.mcp).not.toContain('x');
    expect(catalog.mcp).not.toContain('trading_guard');
  });
});

describe('loadBots', () => {
  const registry = loadBots(botsDir, catalog);

  it('loads the five isolated test manifests', () => {
    expect(registry.list().map((bot) => bot.id)).toEqual([
      'expert',
      'equity-analyst',
      'research',
      'zhushenglang',
      'report-builder',
    ]);
    for (const bot of registry.list()) {
      expect(registry.get(bot.id)).toBe(bot);
    }
  });

  it('keeps the declared capability and permission shape', () => {
    const expert = registry.get('expert') as BotManifest;
    expect(expert.avatar).toEqual({ emblem: 'crown', tone: 'gold' });
    expect(expert.mcp).toContain('paper_broker');
    expect(expert.trading_guard).toBe(true);
    expect(expert.background).toBe(false);
    expect(expert.can_delegate_to).toEqual([
      'equity-analyst',
      'research',
      'report-builder',
    ]);
    expect(expert.routines).toEqual([
      {
        id: 'premarket-brief',
        title: '盘前简报',
        schedule: { cron: '30 8 * * 1-5', tz: 'Asia/Shanghai' },
        trading_days_only: true,
        prompt: expect.stringContaining('按 morning-note 技能出盘前简报'),
      },
    ]);
    expect(expert.panels).toEqual(['market', 'portfolio', 'watches']);
    expect(registry.get('equity-analyst')?.panels).toBeUndefined();

    expect(registry.get('data-prep')).toBeUndefined();

    const zhushenglang = registry.get('zhushenglang') as BotManifest;
    expect(zhushenglang.name).toBe('主升浪');
    expect(zhushenglang.panels).toEqual(['strategy:zhushenglang']);
    expect(zhushenglang.watches).toBe(true);
    expect(zhushenglang.strategies).toEqual(['zhushenglang']);
    expect(zhushenglang.mcp).toEqual(['cn_market', 'strategy']);
    expect(zhushenglang.skills).toEqual([
      'factor-research',
      'zhushenglang',
      'stock-analysis',
      'research-conventions',
      'watch-briefing',
    ]);
    expect(zhushenglang.can_delegate_to).toEqual(['equity-analyst']);
    expect(zhushenglang.routines.map((routine) => routine.id)).toEqual(['surge-post-close']);
    const skillPath = join(repoRoot, 'skills/zhushenglang/SKILL.md');
    expect(existsSync(skillPath)).toBe(true);
    expect(readFileSync(skillPath, 'utf8')).not.toMatch(
      /cn_get_|mkt_get_|\bfmp_|\bob_|\bhub_|\byf_/
    );

    const reportBuilder = registry.get('report-builder') as BotManifest;
    expect(reportBuilder.mcp).toEqual([]);
    expect(reportBuilder.background).toBe(true);
  });

  it('concatenates shared rules first, then the bot persona', () => {
    const shared = readFileSync(join(botsDir, '_shared', 'rules.md'), 'utf8').trimEnd();
    const persona = readFileSync(join(botsDir, 'expert', 'persona.md'), 'utf8').trimEnd();
    const text = registry.personaText('expert');

    expect(text.startsWith(shared)).toBe(true);
    expect(text.endsWith(`${persona}\n`)).toBe(true);
    expect(text.indexOf(shared)).toBeLessThan(text.indexOf(persona));
    expect(() => registry.personaText('missing')).toThrow(/unknown bot id/);
  });
});

const badCases: ReadonlyArray<readonly [string, RegExp]> = [
  ['unknown-field', /unknown field "unexpected"/],
  ['missing-field', /missing field "role"/],
  ['duplicate-id', /duplicate id "duplicate-bot"/],
  ['missing-persona', /persona file not found/],
  ['unknown-skill', /unknown skill "not-a-skill"/],
  ['unknown-mcp', /unknown MCP "not_an_mcp"/],
  ['missing-delegate', /unknown bot "ghost"/],
  ['self-delegate', /must not reference itself/],
  ['bad-emblem', /invalid emblem "unicorn"/],
  ['bad-tone', /invalid tone "purple"/],
  ['unknown-panel', /invalid panel/i],
  ['paper-without-guard', /trading_guard must be true/],
];

function copyBadFixture(name: string): { botsDir: string; cleanup: () => void } {
  const fixtureDir = join(repoRoot, 'apps/server/test/fixtures/bots-bad', name);
  const root = mkdtempSync(join(tmpdir(), `chives-bad-${name}-`));
  const botsDir = join(root, 'bots');
  mkdirSync(botsDir, { recursive: true });
  if (existsSync(join(fixtureDir, 'bot.yaml'))) {
    cpSync(fixtureDir, join(botsDir, name), { recursive: true });
  } else {
    for (const child of readdirSync(fixtureDir, { withFileTypes: true })) {
      if (child.isDirectory()) cpSync(join(fixtureDir, child.name), join(botsDir, child.name), { recursive: true });
    }
  }
  mkdirSync(join(botsDir, '_shared'), { recursive: true });
  writeFileSync(join(botsDir, '_shared', 'rules.md'), '# shared rules fixture\n', 'utf8');
  return { botsDir, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

describe('strategy panels', () => {
  it('rejects a strategy panel whose id is not in strategies', () => {
    const text = readFileSync(join(botsDir, 'zhushenglang', 'bot.yaml'), 'utf8').replace(
      'strategy:zhushenglang',
      'strategy:other'
    );
    expect(() => parseBotManifest(text, 'bots/test/bot.yaml')).toThrow(
      /strategy:other.*不在 strategies 列表中/
    );
  });

  it('accepts the shipped strategy panel', () => {
    const manifest = parseBotManifest(
      readFileSync(join(botsDir, 'zhushenglang', 'bot.yaml'), 'utf8'),
      'bots/zhushenglang/bot.yaml'
    );
    expect(manifest.panels).toContain('strategy:zhushenglang');
  });
});

describe('loadBots rejects bad manifests', () => {
  for (const [name, expected] of badCases) {
    it(`reports ${name} with a file path`, () => {
      const fixture = copyBadFixture(name);
      let thrown: unknown;
      try {
        loadBots(fixture.botsDir, catalog);
      } catch (error) {
        thrown = error;
      } finally {
        fixture.cleanup();
      }

      expect(thrown).toBeInstanceOf(BotLoadError);
      const error = thrown as BotLoadError;
      expect(error.message).toMatch(expected);
      expect(error.message).toContain('bot.yaml');
      for (const issue of error.issues) {
        expect(issue.file.length).toBeGreaterThan(0);
      }
    });
  }
});
