/** One markdown file per memory under `<dataDir>/bots/<id>/memory/`. */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { join } from 'node:path';

import { parse, stringify } from 'yaml';

import { isValidSlug } from './policy.js';
import type { MemoryKind, MemoryRecord, MemorySource } from './types.js';

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n)?([\s\S]*)$/;

function isKind(value: unknown): value is MemoryKind {
  return value === 'preference' || value === 'view' || value === 'fact' || value === 'note';
}

function isSource(value: unknown): value is MemorySource {
  return value === 'capture' || value === 'tool' || value === 'user';
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

export function serializeMemory(record: MemoryRecord): string {
  const header = stringify({
    title: record.title,
    description: record.description,
    kind: record.kind,
    written_at: record.writtenAt,
    expires_at: record.expiresAt,
    source: record.source,
    source_task_id: record.sourceTaskId,
  }).trimEnd();
  return `---\n${header}\n---\n\n${record.body.trim()}\n`;
}

/** Returns undefined for malformed files so one bad file cannot hide the rest. */
export function parseMemoryFile(slug: string, raw: string, updatedAt: string): MemoryRecord | undefined {
  const match = FRONTMATTER.exec(raw);
  if (match === null) return undefined;
  let header: unknown;
  try {
    header = parse(match[1] ?? '');
  } catch {
    return undefined;
  }
  if (typeof header !== 'object' || header === null) return undefined;
  const fields = header as Record<string, unknown>;
  const title = typeof fields['title'] === 'string' ? fields['title'].trim() : '';
  const writtenAt = typeof fields['written_at'] === 'string' ? fields['written_at'] : '';
  if (title === '' || !Number.isFinite(Date.parse(writtenAt)) || !isKind(fields['kind'])) {
    return undefined;
  }
  return {
    slug,
    title,
    description: typeof fields['description'] === 'string' ? fields['description'] : '',
    kind: fields['kind'],
    writtenAt,
    expiresAt: nullableString(fields['expires_at']),
    source: isSource(fields['source']) ? fields['source'] : 'tool',
    sourceTaskId: nullableString(fields['source_task_id']),
    body: (match[2] ?? '').trim(),
    updatedAt,
  };
}

export class MemoryFileStore {
  readonly botId: string;
  readonly dir: string;
  private readonly records = new Map<string, MemoryRecord>();

  constructor(dataDir: string, botId: string) {
    this.botId = botId;
    this.dir = join(dataDir, 'bots', botId, 'memory');
    this.scan();
  }

  scan(): void {
    this.records.clear();
    if (!existsSync(this.dir)) return;
    let entries: string[];
    try {
      entries = readdirSync(this.dir);
    } catch {
      return;
    }
    for (const name of entries) {
      if (!name.endsWith('.md')) continue;
      const slug = name.slice(0, -3);
      if (!isValidSlug(slug)) continue;
      try {
        const path = join(this.dir, name);
        const raw = readFileSync(path, 'utf8');
        const updatedAt = statSync(path).mtime.toISOString();
        const record = parseMemoryFile(slug, raw, updatedAt);
        if (record !== undefined) this.records.set(slug, record);
      } catch {
        // A single unreadable file is skipped; the next scan retries it.
      }
    }
  }

  list(): MemoryRecord[] {
    return [...this.records.values()]
      .sort((left, right) => right.writtenAt.localeCompare(left.writtenAt) || left.slug.localeCompare(right.slug))
      .map((record) => ({ ...record }));
  }

  get(slug: string): MemoryRecord | undefined {
    const record = this.records.get(slug);
    return record === undefined ? undefined : { ...record };
  }

  stats(): { count: number; updatedAt: string | null } {
    let updatedAt: string | null = null;
    for (const record of this.records.values()) {
      if (updatedAt === null || record.updatedAt > updatedAt) updatedAt = record.updatedAt;
    }
    return { count: this.records.size, updatedAt };
  }

  /** Writes atomically and returns the previous file text, if any. */
  put(record: MemoryRecord, now: Date): { before: string | null } {
    if (!isValidSlug(record.slug)) throw new Error(`invalid memory slug "${record.slug}"`);
    mkdirSync(this.dir, { recursive: true });
    const path = join(this.dir, `${record.slug}.md`);
    const before = existsSync(path) ? readFileSync(path, 'utf8') : null;
    const next: MemoryRecord = { ...record, updatedAt: now.toISOString() };
    const tmp = join(this.dir, `.${record.slug}.md.tmp`);
    writeFileSync(tmp, serializeMemory(next), 'utf8');
    renameSync(tmp, path);
    this.records.set(next.slug, next);
    return { before };
  }

  /** Returns the deleted text so the audit line can carry its hash. */
  delete(slug: string): string | null {
    if (!isValidSlug(slug)) return null;
    const path = join(this.dir, `${slug}.md`);
    if (!existsSync(path)) return null;
    const before = readFileSync(path, 'utf8');
    rmSync(path);
    this.records.delete(slug);
    return before;
  }
}
