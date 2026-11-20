/** Conventional bot workspace layout, deliverable filtering, and scratch cleanup. */

import { lstatSync, mkdirSync, readdirSync, rmdirSync, statSync, unlinkSync } from 'node:fs';
import type { Stats } from 'node:fs';
import { join } from 'node:path';

import { extensionOf } from './kinds.js';

export const WORKSPACE_MAP_FILE = 'MAP.md';

export const WORKSPACE_DIRECTORIES = [
  'reports',
  'charts',
  'data',
  'scripts',
  'scratch',
  'uploads',
] as const;

export type WorkspaceDirectory = (typeof WORKSPACE_DIRECTORIES)[number];

export const SCRATCH_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

/** Extensions that are never listed as deliverables, wherever they live. */
const NEVER_DELIVERABLE_EXTENSIONS = new Set([
  'py',
  'js',
  'ts',
  'sh',
  'json',
  'jsonl',
  'csv',
  'parquet',
  'txt',
  'log',
]);

/** Document types worth showing as a report. */
const DOCUMENT_EXTENSIONS = new Set(['md', 'markdown', 'mdx', 'html', 'htm', 'pdf', 'docx', 'xlsx', 'pptx']);

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'avif']);

/** Full trees that hold code, temporary output, user uploads, or reusable data rather than deliverables. */
const NEVER_DELIVERABLE_DIRECTORIES = new Set(['scripts', 'scratch', 'data', 'uploads']);

/** Creates the conventional directories without touching existing content. */
export function ensureWorkspaceDirectories(workspace: string): void {
  mkdirSync(workspace, { recursive: true });
  for (const directory of WORKSPACE_DIRECTORIES) {
    mkdirSync(join(workspace, directory), { recursive: true });
  }
}

function normalizedSegments(relPath: string): string[] | null {
  const normalized = relPath.replaceAll('\\', '/').replace(/^\.\//, '').replace(/^\/+/, '');
  if (normalized.trim() === '') return null;
  const segments: string[] = [];
  for (const segment of normalized.split('/')) {
    if (segment === '' || segment === '.') continue;
    if (segment === '..') return null;
    segments.push(segment);
  }
  return segments.length === 0 ? null : segments;
}

/**
 * True only for files a user should see as a deliverable: documents and images
 * outside `scripts/`, `scratch/`, `data/`, plus never for code/data extensions
 * or the generated `MAP.md`.
 */
export function isDeliverablePath(relPath: string): boolean {
  const segments = normalizedSegments(relPath);
  if (segments === null) return false;
  const top = segments[0] ?? '';
  if (segments.length === 1 && top === WORKSPACE_MAP_FILE) return false;
  if (NEVER_DELIVERABLE_DIRECTORIES.has(top)) return false;
  const extension = extensionOf(segments.at(-1) ?? '');
  if (extension === '' || NEVER_DELIVERABLE_EXTENSIONS.has(extension)) return false;
  return DOCUMENT_EXTENSIONS.has(extension) || IMAGE_EXTENSIONS.has(extension);
}

export interface ScratchCleanupOptions {
  now?: Date;
  /** Files modified longer ago than this are removed. Defaults to seven days. */
  retentionMs?: number;
}

export interface ScratchCleanupResult {
  removedFiles: number;
  removedDirectories: number;
}

function safeLstat(path: string): Stats | null {
  try {
    return lstatSync(path);
  } catch {
    return null;
  }
}

function removeScratchEntries(
  directory: string,
  cutoffMs: number,
  result: ScratchCleanupResult,
  isRoot: boolean,
): void {
  let entries;
  try {
    entries = readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    // Symlinks are neither followed nor deleted: their target may live outside.
    if (entry.isSymbolicLink()) continue;
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) {
      removeScratchEntries(absolute, cutoffMs, result, false);
      continue;
    }
    if (!entry.isFile()) continue;
    let stat;
    try {
      stat = statSync(absolute);
    } catch {
      continue;
    }
    if (stat.mtimeMs >= cutoffMs) continue;
    try {
      unlinkSync(absolute);
      result.removedFiles += 1;
    } catch {
      // A file that cannot be removed must not fail the task.
    }
  }
  if (isRoot) return;
  try {
    if (readdirSync(directory).length === 0) {
      rmdirSync(directory);
      result.removedDirectories += 1;
    }
  } catch {
    // Non-empty or vanished directories stay in place.
  }
}

/**
 * Removes regular files older than `retentionMs` from `scratch/` and prunes the
 * empty directories left behind. The scratch directory itself is kept.
 */
export function cleanupScratch(
  workspace: string,
  options: ScratchCleanupOptions = {},
): ScratchCleanupResult {
  const result: ScratchCleanupResult = { removedFiles: 0, removedDirectories: 0 };
  const scratch = join(workspace, 'scratch');
  const stat = safeLstat(scratch);
  if (stat === null || !stat.isDirectory()) return result;
  const cutoffMs = (options.now ?? new Date()).getTime() - (options.retentionMs ?? SCRATCH_RETENTION_MS);
  removeScratchEntries(scratch, cutoffMs, result, true);
  return result;
}
