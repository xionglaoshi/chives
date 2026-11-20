/** Materializes each bot's allowed skills as symlinks under its data directory. */

import {
  mkdirSync,
  lstatSync,
  readdirSync,
  readlinkSync,
  statSync,
  symlinkSync,
  unlinkSync,
} from 'node:fs';
import { dirname, join, resolve } from 'node:path';

import { BotLoadError } from './errors.js';
import type { BotManifest } from './types.js';

/** One discovered skill package. */
export interface SkillSource {
  name: string;
  path: string;
}

export interface SkillSyncOptions {
  repoRoot: string;
  dataDir: string;
  /** Discovered skills; callers syncing several bots should pass one shared map. */
  sources?: ReadonlyMap<string, SkillSource>;
}

/** Absolute `<dataDir>/bots/<id>/skills` directory. */
export function botSkillsDir(dataDir: string, botId: string): string {
  return join(resolve(dataDir), 'bots', botId, 'skills');
}

/** Discover direct skill packages. Ignore ancillary files and incomplete packages. */
export function loadSkillSources(repoRoot: string): ReadonlyMap<string, SkillSource> {
  const root = resolve(repoRoot, 'skills');
  const sources = new Map<string, SkillSource>();
  for (const name of readdirSync(root).sort()) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) continue;
    const path = join(root, name);
    if (lstatSync(path, { throwIfNoEntry: false })?.isDirectory() &&
        lstatSync(join(path, 'SKILL.md'), { throwIfNoEntry: false })?.isFile()) {
      sources.set(name, { name, path });
    }
  }
  return sources;
}

/**
 * Reconciles one bot's skill directory with its manifest. Only symbolic links
 * are removed; real files and directories are left untouched. A real entry
 * occupying a requested skill name is an error because the link cannot be made.
 */
export function syncBotSkills(bot: BotManifest, options: SkillSyncOptions): string {
  const dir = botSkillsDir(options.dataDir, bot.id);
  mkdirSync(dir, { recursive: true });
  const sources = options.sources ?? loadSkillSources(options.repoRoot);
  const skillRoot = resolve(options.repoRoot, 'skills');

  const desired = new Map<string, string>();
  for (const name of bot.skills) {
    const source = sources.get(name);
    if (source === undefined) {
      throw new BotLoadError([
        { file: skillRoot, message: `bot "${bot.id}" lists skill "${name}" but no valid package was found` },
      ]);
    }
    let isDirectory: boolean;
    try {
      isDirectory = statSync(source.path).isDirectory();
    } catch {
      isDirectory = false;
    }
    if (!isDirectory) {
      throw new BotLoadError([
        { file: skillRoot, message: `skill "${name}" resolves to "${source.path}", which is not a directory` },
      ]);
    }
    desired.set(name, source.path);
  }

  const linked = new Set<string>();
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    const wanted = desired.get(entry.name);
    if (!entry.isSymbolicLink()) {
      if (wanted !== undefined) {
        throw new Error(
          `cannot link skill "${entry.name}" for bot "${bot.id}": ${path} exists and is not a symbolic link`,
        );
      }
      continue;
    }
    if (wanted === undefined) {
      unlinkSync(path);
      continue;
    }
    if (linkTarget(path) === wanted) {
      linked.add(entry.name);
      continue;
    }
    unlinkSync(path);
  }

  for (const [name, target] of desired) {
    if (linked.has(name)) continue;
    symlinkSync(target, join(dir, name), 'dir');
  }
  return dir;
}

/** Reconciles every bot at server startup, sharing one catalog. */
export function syncAllBotSkills(
  bots: readonly BotManifest[],
  options: SkillSyncOptions,
): void {
  const sources = options.sources ?? loadSkillSources(options.repoRoot);
  for (const bot of bots) {
    syncBotSkills(bot, { ...options, sources });
  }
}

function linkTarget(path: string): string {
  return resolve(dirname(path), readlinkSync(path));
}
