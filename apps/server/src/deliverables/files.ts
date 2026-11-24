/** Resolves deliverable paths inside one bot workspace and enforces limits. */

import { existsSync, readdirSync, realpathSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';

import type { WorkspaceFileDto, WorkspaceFileList } from '../api/protocol.js';
import { AppError } from '../errors.js';
import { classifyKind, isBinaryKind, type DeliverableKind } from './kinds.js';
import { WORKSPACE_MAP_FILE } from './layout.js';
import { IGNORED_DIRECTORIES } from './snapshot.js';

export const MAX_WORKSPACE_FILES = 200;

export const TEXT_CONTENT_LIMIT_BYTES = 2 * 1024 * 1024;
export const BINARY_CONTENT_LIMIT_BYTES = 20 * 1024 * 1024;

export function botWorkspace(dataDir: string, botId: string): string {
  const workspaceRoot = process.env.CHIVES_WORKSPACE_DIR?.trim();
  return workspaceRoot ? resolve(workspaceRoot, 'bots', botId) : join(dataDir, 'bots', botId, 'workspace');
}

function isInside(root: string, target: string): boolean {
  return target === root || target.startsWith(root.endsWith(sep) ? root : `${root}${sep}`);
}

/**
 * Resolves `relativePath` with `realpath` and rejects anything that escapes
 * the workspace, including `..` segments and symlinks pointing outside.
 */
export function resolveWorkspacePath(workspace: string, relativePath: string): string {
  let root: string;
  try {
    root = realpathSync(workspace);
  } catch {
    throw new AppError(404, 'deliverable_not_found', 'bot workspace does not exist');
  }
  const candidate = resolve(workspace, relativePath);
  // Reject lexical escapes before touching the filesystem, so a missing
  // `../secret` path is still a 403 rather than a 404.
  if (!isInside(resolve(workspace), candidate)) {
    throw new AppError(403, 'path_outside_workspace', 'deliverable path escapes the bot workspace');
  }
  let target: string;
  try {
    target = realpathSync(candidate);
  } catch {
    throw new AppError(404, 'deliverable_not_found', 'deliverable file does not exist');
  }
  if (!isInside(root, target)) {
    throw new AppError(403, 'path_outside_workspace', 'deliverable path escapes the bot workspace');
  }
  return target;
}

export function contentLimitBytes(kind: DeliverableKind): number {
  return isBinaryKind(kind) ? BINARY_CONTENT_LIMIT_BYTES : TEXT_CONTENT_LIMIT_BYTES;
}

export function assertReadableFile(path: string): number {
  let stat;
  try {
    stat = statSync(path);
  } catch {
    throw new AppError(404, 'deliverable_not_found', 'deliverable file does not exist');
  }
  if (!stat.isFile()) {
    throw new AppError(404, 'deliverable_not_found', 'deliverable is not a regular file');
  }
  return stat.size;
}

export interface WorkspaceStats {
  fileCount: number;
  totalBytes: number;
}

/** Recursively counts regular files inside the workspace; symlinks are ignored. */
export function workspaceStats(workspace: string): WorkspaceStats {
  const stats: WorkspaceStats = { fileCount: 0, totalBytes: 0 };
  if (!existsSync(workspace)) return stats;
  let root: string;
  try {
    root = realpathSync(workspace);
  } catch {
    return stats;
  }
  const walk = (directory: string): void => {
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = join(directory, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!entry.isFile()) continue;
      try {
        const real = realpathSync(full);
        if (!isInside(root, real)) continue;
        if (toPosix(relative(root, full)) === WORKSPACE_MAP_FILE) continue;
        const stat = statSync(real);
        if (!stat.isFile()) continue;
        stats.fileCount += 1;
        stats.totalBytes += stat.size;
      } catch {
        // A file that vanished mid-walk does not fail the profile request.
      }
    }
  };
  walk(root);
  return stats;
}

function toPosix(path: string): string {
  return sep === '/' ? path : path.split(sep).join('/');
}

export interface ListWorkspaceOptions {
  /** Walk subdirectories and return every file under `dir`. */
  recursive?: boolean;
}

interface CollectedFile {
  absolute: string;
  name: string;
}

/**
 * Lists files inside the workspace, newest first, at most `limit`. With
 * `recursive` it walks the whole subtree under `dir`. `dir` is resolved with
 * the same realpath guard as deliverable content, so `..` and outward symlinks
 * are rejected.
 */
export function listWorkspaceFiles(
  workspace: string,
  dir = '',
  limit = MAX_WORKSPACE_FILES,
  options: ListWorkspaceOptions = {},
): WorkspaceFileList {
  const requested = dir.trim() === '' ? '.' : dir;
  if (!existsSync(workspace)) {
    if (requested === '.') return { dir: '', files: [] };
    throw new AppError(404, 'workspace_not_found', 'bot workspace does not exist');
  }
  const target = resolveWorkspacePath(workspace, requested);
  let targetStat;
  try {
    targetStat = statSync(target);
  } catch {
    throw new AppError(404, 'workspace_not_found', 'directory does not exist');
  }
  if (!targetStat.isDirectory()) {
    throw new AppError(400, 'validation_error', 'dir must be a directory inside the workspace');
  }

  const root = realpathSync(workspace);
  const relativeDir = toPosix(relative(root, target));
  const collected: CollectedFile[] = [];
  const collect = (directory: string): void => {
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue;
      const full = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (options.recursive === true && !IGNORED_DIRECTORIES.has(entry.name) && !entry.name.startsWith('.')) {
          collect(full);
        }
        continue;
      }
      if (entry.isFile()) collected.push({ absolute: full, name: entry.name });
    }
  };
  collect(target);

  const files: WorkspaceFileDto[] = [];
  for (const entry of collected) {
    try {
      const real = realpathSync(entry.absolute);
      if (!isInside(root, real)) continue;
      const path = toPosix(relative(root, entry.absolute));
      if (path === WORKSPACE_MAP_FILE) continue;
      const stat = statSync(real);
      if (!stat.isFile()) continue;
      files.push({
        path,
        name: entry.name,
        size: stat.size,
        modifiedAt: stat.mtime.toISOString(),
        kind: classifyKind(entry.name),
        deliverableId: null,
      });
    } catch {
      // Skip entries that disappear or cannot be stat'ed.
    }
  }
  files.sort(
    (left, right) =>
      right.modifiedAt.localeCompare(left.modifiedAt) || left.name.localeCompare(right.name),
  );
  return { dir: relativeDir === '.' ? '' : relativeDir, files: files.slice(0, limit) };
}
