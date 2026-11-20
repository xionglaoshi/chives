/** Workspace snapshots used to detect the files a turn produced or changed. */

import { readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import type { DeliverableKind } from './kinds.js';

export const MAX_DELIVERABLE_BYTES = 50 * 1024 * 1024;
export const MAX_DELIVERABLES_PER_TASK = 50;
export const IGNORED_DIRECTORIES = new Set(['node_modules', '__pycache__']);

export interface FileSnapshot {
  size: number;
  mtimeMs: number;
}

export type WorkspaceSnapshot = ReadonlyMap<string, FileSnapshot>;

export interface WorkspaceChange {
  /** POSIX-style path relative to the workspace root. */
  path: string;
  size: number;
  mtimeMs: number;
}

export interface DeliverableCandidate extends WorkspaceChange {
  kind: DeliverableKind;
}

function walk(root: string, directory: string, prefix: string, files: Map<string, FileSnapshot>): void {
  let entries;
  try {
    entries = readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    // Dot-prefixed segments, dependency caches, and byte-code caches are noise,
    // not deliverables.
    if (entry.name.startsWith('.')) continue;
    if (IGNORED_DIRECTORIES.has(entry.name)) continue;
    const absolute = join(directory, entry.name);
    const relative = prefix === '' ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isSymbolicLink()) {
      // Record the link as a file candidate; the read/reveal routes resolve it
      // with realpath and reject targets outside the workspace.
      let linked;
      try {
        linked = statSync(absolute);
      } catch {
        continue;
      }
      if (!linked.isFile() || linked.size > MAX_DELIVERABLE_BYTES) continue;
      files.set(relative, { size: linked.size, mtimeMs: linked.mtimeMs });
      continue;
    }
    if (entry.isDirectory()) {
      walk(root, absolute, relative, files);
      continue;
    }
    if (!entry.isFile()) continue;
    let stat;
    try {
      stat = statSync(absolute);
    } catch {
      continue;
    }
    if (stat.size > MAX_DELIVERABLE_BYTES) continue;
    files.set(relative, { size: stat.size, mtimeMs: stat.mtimeMs });
  }
}

/** Relative path → size + mtime for every eligible regular file under `root`. */
export function snapshotWorkspace(root: string): Map<string, FileSnapshot> {
  const files = new Map<string, FileSnapshot>();
  walk(root, root, '', files);
  return files;
}

/** Added or modified paths after a turn, sorted for deterministic caps. */
export function diffWorkspace(before: WorkspaceSnapshot, after: WorkspaceSnapshot): WorkspaceChange[] {
  const changes: WorkspaceChange[] = [];
  for (const [path, current] of after) {
    const previous = before.get(path);
    if (previous !== undefined && previous.size === current.size && previous.mtimeMs === current.mtimeMs) {
      continue;
    }
    changes.push({ path, size: current.size, mtimeMs: current.mtimeMs });
  }
  changes.sort((left, right) => left.path.localeCompare(right.path));
  return changes;
}
