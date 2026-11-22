/** Loads every bot manifest, validates it against the repository catalog, and exposes persona text. */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';

import { BotLoadError, type BotLoadIssue } from './errors.js';
import { parseBotManifest } from './manifest.js';
import type { BotCatalog, BotManifest } from './types.js';

/** The bot users land on first. */
export const DEFAULT_ENTRY_BOT_ID = 'operator';

export class BotRegistry {
  private ordered: readonly BotManifest[];
  private byId: ReadonlyMap<string, BotManifest>;
  private personas: ReadonlyMap<string, string>;
  private sharedRules: string;
  private hired: ReadonlySet<string> | undefined;

  setHired(ids: readonly string[]): void {
    this.hired = new Set(ids);
  }

  isHired(id: string): boolean {
    return this.byId.has(id) && (id === DEFAULT_ENTRY_BOT_ID || this.hired === undefined || this.hired.has(id));
  }

  constructor(
    manifests: readonly BotManifest[],
    personas: ReadonlyMap<string, string>,
    sharedRules: string,
  ) {
    // Display order: the default entry (`operator`) first, then other conversational bots, background colleagues last.
    const rank = (manifest: BotManifest): number =>
      manifest.id === DEFAULT_ENTRY_BOT_ID ? 0 : manifest.background ? 2 : 1;
    this.ordered = [...manifests].sort((left, right) => rank(left) - rank(right));
    this.byId = new Map(manifests.map((manifest) => [manifest.id, manifest]));
    this.personas = personas;
    this.sharedRules = sharedRules;
  }

  replaceWith(next: BotRegistry): void {
    this.ordered = next.ordered;
    this.byId = next.byId;
    this.personas = next.personas;
    this.sharedRules = next.sharedRules;
  }

  list(): readonly BotManifest[] {
    return this.ordered;
  }

  get(id: string): BotManifest | undefined {
    return this.byId.get(id);
  }

  /** Shared rules first, then this bot's persona. The order is fixed. */
  personaText(id: string): string {
    const persona = this.personas.get(id);
    if (persona === undefined) throw new Error(`unknown bot id: ${id}`);
    return `${this.sharedRules.trimEnd()}\n\n${persona.trimEnd()}\n`;
  }

  /** First body paragraph of this bot's persona, excluding headings. */
  personaSummary(id: string): string {
    const persona = this.personas.get(id);
    if (persona === undefined) throw new Error(`unknown bot id: ${id}`);
    return firstParagraph(persona);
  }
}

/** The first paragraph after the persona title; headings and blank lines are skipped. */
export function firstParagraph(text: string): string {
  const lines: string[] = [];
  let started = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!started) {
      if (line === '' || line.startsWith('#')) continue;
      started = true;
      lines.push(line);
      continue;
    }
    if (line === '') break;
    lines.push(line);
  }
  return lines.join('\n');
}

function isFile(path: string): boolean {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

function readPersona(
  botFile: string,
  manifest: BotManifest,
  repoRoot: string,
  issues: BotLoadIssue[],
): string | undefined {
  const configured = isAbsolute(manifest.persona)
    ? manifest.persona
    : resolve(repoRoot, manifest.persona);
  const local = resolve(dirname(botFile), manifest.persona);
  const path = isFile(configured) ? configured : isFile(local) ? local : configured;
  if (!isFile(path)) {
    issues.push({
      file: botFile,
      message: `persona file not found: ${path} (configured as "${manifest.persona}")`,
    });
    return undefined;
  }
  return readFileSync(path, 'utf8');
}

export function loadBots(botsDir: string, catalog: BotCatalog): BotRegistry {
  const root = resolve(botsDir);
  const repoRoot = dirname(root);
  const issues: BotLoadIssue[] = [];

  const sharedPath = join(root, '_shared', 'rules.md');
  let sharedRules = '';
  if (!isFile(sharedPath)) {
    issues.push({ file: sharedPath, message: 'shared rules file not found' });
  } else {
    sharedRules = readFileSync(sharedPath, 'utf8');
  }

  let directoryNames: string[];
  try {
    directoryNames = readdirSync(root, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith('_'))
      .map((entry) => entry.name)
      .sort((left, right) => left.localeCompare(right));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new BotLoadError([{ file: root, message: `cannot read bots directory: ${message}` }]);
  }

  const skillSet = new Set(catalog.skills);
  const mcpSet = new Set(catalog.mcp);
  const manifests: BotManifest[] = [];
  const personas = new Map<string, string>();
  const seenIds = new Map<string, string>();
  const filesById = new Map<string, string>();
  const parsedIds = new Set<string>();

  for (const directory of directoryNames) {
    const botFile = join(root, directory, 'bot.yaml');
    if (!isFile(botFile)) {
      issues.push({ file: botFile, message: 'bot.yaml not found' });
      continue;
    }

    let manifest: BotManifest;
    try {
      manifest = parseBotManifest(readFileSync(botFile, 'utf8'), botFile);
    } catch (error) {
      if (error instanceof BotLoadError) issues.push(...error.issues);
      else issues.push({ file: botFile, message: error instanceof Error ? error.message : String(error) });
      continue;
    }

    parsedIds.add(manifest.id);
    const duplicateOf = seenIds.get(manifest.id);
    if (duplicateOf !== undefined) {
      issues.push({
        file: botFile,
        message: `duplicate id "${manifest.id}" (already defined in ${duplicateOf})`,
      });
      continue;
    }
    seenIds.set(manifest.id, botFile);
    filesById.set(manifest.id, botFile);

    for (const skill of manifest.skills) {
      if (!skillSet.has(skill)) {
        issues.push({ file: botFile, message: `unknown skill "${skill}" (missing from skills/)` });
      }
    }
    for (const server of manifest.mcp) {
      if (!mcpSet.has(server)) {
        issues.push({ file: botFile, message: `unknown MCP "${server}" (not in the in-use overlay list)` });
      }
    }
    if (manifest.mcp.includes('paper_broker') && manifest.trading_guard !== true) {
      issues.push({
        file: botFile,
        message: 'trading_guard must be true when paper_broker is in mcp',
      });
    }

    const persona = readPersona(botFile, manifest, repoRoot, issues);
    if (persona !== undefined) personas.set(manifest.id, persona);
    manifests.push(manifest);
  }

  const coordinator = manifests.find(bot => bot.id === DEFAULT_ENTRY_BOT_ID);
  if (coordinator) {
    coordinator.skills = [...catalog.skills];
    coordinator.mcp = [...catalog.mcp];
    if (!coordinator.trading_guard) throw new BotLoadError([{file: filesById.get(coordinator.id)!,message: '总调度员需要交易审批保护'}]);
    coordinator.can_delegate_to = manifests.filter(bot => bot !== coordinator).map(bot => bot.id);
  }

  for (const manifest of manifests) {
    for (const target of manifest.can_delegate_to) {
      if (target === manifest.id) {
        issues.push({
          file: filesById.get(manifest.id) ?? join(root, manifest.id, 'bot.yaml'),
          message: `can_delegate_to must not reference itself ("${target}")`,
        });
      } else if (!parsedIds.has(target)) {
        issues.push({
          file: filesById.get(manifest.id) ?? join(root, manifest.id, 'bot.yaml'),
          message: `can_delegate_to references unknown bot "${target}"`,
        });
      }
    }
  }

  if (issues.length > 0) throw new BotLoadError(issues);
  return new BotRegistry(manifests, personas, sharedRules);
}
