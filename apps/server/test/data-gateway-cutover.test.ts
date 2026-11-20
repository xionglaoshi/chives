import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { buildCatalog, loadBots } from '../src/bots/index.js';

const repoRoot = fileURLToPath(new URL('../../../', import.meta.url));
const botsDir = join(repoRoot, 'apps/server/test/fixtures/bots');
const catalog = buildCatalog(repoRoot);
const registry = loadBots(botsDir, catalog);

const OLD_MCP = ['cn_data', 'cn_extra', 'cn_research', 'market_watch'];
const DATA_BOTS = ['expert', 'equity-analyst', 'research'];
const OLD_TOOL_NAME =
  /cn_get_|mkt_get_|cn_search_symbol|cn_intraday_summary|cn_read_announcement/;
const OLD_FIELD_NAME =
  /\b(?:amount_wan|volume_lots|premium_ratio|free_ratio|total_ratio|ROEJQ|ZZCJLL|XSJLL|XSMLL|ZCFZL|PARENTNETPROFIT|KCFJCXSYJLR|TOTALOPERATE|quote_note|terms_fetched_at)\b/;
const TEXT_FILE = /\.(?:md|markdown|txt|ya?ml|json|csv)$/i;

function walk(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(path));
    else if (entry.isFile() && TEXT_FILE.test(entry.name)) files.push(path);
  }
  return files;
}

function bot(id: string) {
  const found = registry.get(id);
  if (found === undefined) throw new Error(`unknown bot: ${id}`);
  return found;
}

describe('data gateway cutover', () => {
  it('loads the registry and recognises cn_market', () => {
    expect(catalog.mcp).toContain('cn_market');
    for (const id of ['expert', 'equity-analyst', 'research', 'report-builder']) {
      expect(bot(id).id).toBe(id);
    }
  });

  it('mounts cn_market on every data bot and no retired data MCP anywhere', () => {
    for (const bot of registry.list()) {
      for (const retired of OLD_MCP) expect(bot.mcp).not.toContain(retired);
    }
    for (const id of DATA_BOTS) expect(bot(id).mcp).toContain('cn_market');
    expect(bot('report-builder').mcp).toEqual([]);
  });

  it('has no retired tool or field names in bots or installed skills', () => {
    const files = [
      ...walk(join(repoRoot, 'bots')),
      ...walk(botsDir),
      ...catalog.skills.flatMap((name) => walk(join(repoRoot, 'skills', name))),
    ];
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, 'utf8');
      if (OLD_TOOL_NAME.test(text) || OLD_FIELD_NAME.test(text)) {
        offenders.push(file.slice(repoRoot.length + 1));
      }
    }
    expect(offenders).toEqual([]);
  });

  it('keeps the shared rules free of unit-conversion tables and states the new contract', () => {
    const rules = readFileSync(join(repoRoot, 'bots', '_shared', 'rules.md'), 'utf8');
    for (const keyword of ['万元', 'volume_lots', 'amount_wan', '1 手 = 100 股', '单位换算']) {
      expect(rules).not.toContain(keyword);
    }
    expect(rules).toContain('字段名后缀就是单位');
    expect(rules).toContain('status:"partial"');
    expect(rules).toContain('status:"unavailable"');
    expect(rules).toContain('basis');
    expect(rules).toContain('stale:true');
    expect(rules).toContain('market_northbound');
    expect(rules).not.toContain('每个结论性数字都标注来源');
  });
});
