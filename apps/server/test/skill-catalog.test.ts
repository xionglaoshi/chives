import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { parse } from 'yaml';
import { describe, expect, it } from 'vitest';

import { buildCatalog, loadBots } from '../src/bots/index.js';

const repoRoot = resolve(fileURLToPath(new URL('../../../', import.meta.url)));
const botsDir = join(repoRoot, 'apps/server/test/fixtures/bots');
const skillsRoot = join(repoRoot, 'skills');
const catalog = buildCatalog(repoRoot);
const registry = loadBots(botsDir, catalog);

const OLD_TOOL_NAME = /cn_get_|mkt_get_|\bfmp_|\bob_|\bhub_|\byf_/;
const TEXT_FILE = /\.(?:md|markdown|txt|ya?ml|json|csv)$/i;
const KEBAB = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const T151_SKILLS = new Set([
  'stock-analysis',
  'trade-pitch',
  'thesis-tracker',
  'initiating-coverage',
  'company-profile',
  'competitive-analysis',
  'sector-overview',
  'catalyst-calendar',
  'earnings-preview',
  'impact-analysis',
  'risk-boundary',
]);

interface Frontmatter {
  name: string;
  description: string;
}

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(path));
    else if (entry.isFile() && TEXT_FILE.test(entry.name)) files.push(path);
  }
  return files;
}

/** Every skill directory in the repository, keyed by its frontmatter name (the mount name). */
function skillDirectories(): Map<string, string> {
  const found = new Map<string, string>();
  for (const entry of readdirSync(skillsRoot, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const dir = join(skillsRoot, entry.name);
    expect(existsSync(join(dir, 'SKILL.md')), `missing skills/${entry.name}/SKILL.md`).toBe(true);
    found.set(entry.name, dir);
  }
  return found;
}

function frontmatter(file: string): Frontmatter {
  const text = readFileSync(file, 'utf8');
  expect(text.startsWith('---\n'), `${file} must start with a frontmatter fence`).toBe(true);
  const end = text.indexOf('\n---', 4);
  expect(end, `${file} must close the frontmatter`).toBeGreaterThan(0);
  const parsed: unknown = parse(text.slice(4, end));
  expect(parsed, `${file} frontmatter must be a YAML mapping`).toBeTypeOf('object');
  return parsed as Frontmatter;
}

const dirs = skillDirectories();
const mounted = [...new Set(registry.list().flatMap((bot) => [...bot.skills]))].sort();

describe('T151 mounted skill catalog', () => {
  it('resolves every mounted skill to exactly one directory with a SKILL.md', () => {
    for (const skill of mounted) {
      expect(dirs.has(skill), `mounted skill "${skill}" has no skills/${skill}/SKILL.md`).toBe(true);
    }
  });

  it('has valid frontmatter with a kebab-case name matching the directory and a Chinese description', () => {
    for (const skill of mounted) {
      const dir = dirs.get(skill) as string;
      const meta = frontmatter(join(dir, 'SKILL.md'));
      expect(meta.name, `${skill} frontmatter name`).toBe(skill);
      expect(KEBAB.test(meta.name), `${skill} name must be kebab-case`).toBe(true);
      expect(typeof meta.description, `${skill} description`).toBe('string');
      expect(meta.description.trim().length).toBeGreaterThan(0);
      if (T151_SKILLS.has(skill)) {
        expect(/^[\u4e00-\u9fff]/.test(meta.description), `${skill} description must start in Chinese`).toBe(true);
      }
    }
  });

  it('does not reference retired tool names anywhere under a mounted skill', () => {
    const offenders: string[] = [];
    for (const skill of mounted) {
      const dir = dirs.get(skill) as string;
      for (const file of walk(dir)) {
        if (OLD_TOOL_NAME.test(readFileSync(file, 'utf8'))) {
          offenders.push(file.slice(repoRoot.length + 1));
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('mounts the T151 method skills on the bots named by the brief', () => {
    const expected: Record<string, readonly string[]> = {
      expert: [
        'stock-analysis',
        'trade-pitch',
        'risk-boundary',
        'catalyst-calendar',
        'impact-analysis',
        'sector-overview',
        // Quick reads by the expert also follow the method skills; full coverage stays with equity-analyst.
        'valuation-model',
        'financial-statement',
        'earnings-analysis',
        'earnings-forecast',
        'comps-analysis',
        'dividend-analysis',
        'company-profile',
        'competitive-analysis',
        'thesis-tracker',
        'earnings-preview',
      ],
      'equity-analyst': [
        'stock-analysis',
        'trade-pitch',
        'initiating-coverage',
        'company-profile',
        'competitive-analysis',
        'thesis-tracker',
        'earnings-preview',
      ],
      research: ['sector-overview', 'impact-analysis', 'catalyst-calendar', 'competitive-analysis'],
    };
    for (const [id, skills] of Object.entries(expected)) {
      const bot = registry.get(id);
      expect(bot, `bot ${id}`).toBeDefined();
      for (const skill of skills) expect(bot?.skills).toContain(skill);
    }
  });
});

describe('T151 gateway tool names', () => {
  it('only names tools that the live gateway exposes', async () => {
    const referenced = new Set<string>();
    const toolPattern = /\b(?:market|company|convertible_bonds)_[a-z][a-z0-9_]*\b|\b(?:news|convertible_bonds)\b/g;
    for (const skill of mounted) {
      for (const file of walk(dirs.get(skill) as string)) {
        for (const match of readFileSync(file, 'utf8').matchAll(toolPattern)) {
          referenced.add(match[0]);
        }
      }
    }
    expect(referenced.size).toBeGreaterThan(0);

    let names: string[] | undefined;
    try {
      const response = await fetch('http://127.0.0.1:8868/v1/tools', {
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) {
        const body = (await response.json()) as { tools?: readonly { name?: string }[] };
        names = (body.tools ?? []).map((tool) => tool.name ?? '').filter((name) => name.length > 0);
      }
    } catch {
      names = undefined;
    }
    if (names === undefined || names.length === 0) {
      console.warn('cn-market-gateway is not reachable; skipped live tool-name validation');
      return;
    }

    const known = new Set(names);
    const unknown = [...referenced].filter((name) => !known.has(name)).sort();
    expect(unknown, `skills reference tools missing from /v1/tools: ${unknown.join(', ')}`).toEqual([]);
  });
});
