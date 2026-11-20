/** Append-only memory audit log kept outside every bot workspace. */

import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';

import type { MemoryAction, MemoryActor, MemoryUserChange } from './types.js';

export interface MemoryAuditEntry {
  at: string;
  bot: string;
  action: MemoryAction;
  actor: MemoryActor;
  slug: string;
  title: string;
  before_sha256: string | null;
  after_sha256: string | null;
  reason: string | null;
}

export interface MemoryAuditChanges {
  changes: MemoryUserChange[];
  cursor: number;
}

export function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

function isAuditAction(value: unknown): value is MemoryAction {
  return value === 'create' || value === 'update' || value === 'delete' || value === 'reject';
}

function toEntry(raw: string): MemoryAuditEntry | undefined {
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== 'object' || value === null) return undefined;
    const record = value as Record<string, unknown>;
    if (
      typeof record['at'] !== 'string' ||
      typeof record['bot'] !== 'string' ||
      typeof record['slug'] !== 'string' ||
      !isAuditAction(record['action'])
    ) {
      return undefined;
    }
    return {
      at: record['at'],
      bot: record['bot'],
      action: record['action'],
      actor:
        record['actor'] === 'capture' || record['actor'] === 'tool' || record['actor'] === 'user'
          ? record['actor']
          : 'tool',
      slug: record['slug'],
      title: typeof record['title'] === 'string' ? record['title'] : record['slug'],
      before_sha256:
        typeof record['before_sha256'] === 'string' ? record['before_sha256'] : null,
      after_sha256: typeof record['after_sha256'] === 'string' ? record['after_sha256'] : null,
      reason: typeof record['reason'] === 'string' ? record['reason'] : null,
    };
  } catch {
    return undefined;
  }
}

/**
 * The log lives at `<dataDir>/audit/memory.jsonl`, never under
 * `<dataDir>/bots/<id>/workspace`, so a sandboxed bot cannot rewrite it.
 * Reads use a cached line array; appends are serialised in-process.
 */
export class MemoryAuditLog {
  readonly path: string;
  private lines: string[] = [];

  constructor(dataDir: string) {
    this.path = join(dataDir, 'audit', 'memory.jsonl');
    if (existsSync(this.path)) {
      const raw = readFileSync(this.path, 'utf8');
      this.lines = raw.split('\n').filter((line) => line.trim() !== '');
    }
  }

  get cursor(): number {
    return this.lines.length;
  }

  append(entry: MemoryAuditEntry): void {
    mkdirSync(dirname(this.path), { recursive: true });
    const line = JSON.stringify(entry);
    appendFileSync(this.path, `${line}\n`, 'utf8');
    this.lines.push(line);
  }

  /** User edits/deletes after `since`, so the next prompt can say "以此为准". */
  userChanges(botId: string, since: number): MemoryAuditChanges {
    const start = Math.max(0, Math.min(since, this.lines.length));
    const changes: MemoryUserChange[] = [];
    for (let index = start; index < this.lines.length; index += 1) {
      const line = this.lines[index];
      if (line === undefined) continue;
      const entry = toEntry(line);
      if (entry === undefined || entry.bot !== botId || entry.actor !== 'user') continue;
      if (entry.action === 'update') {
        changes.push({ action: 'update', slug: entry.slug, title: entry.title, body: null });
      } else if (entry.action === 'delete') {
        changes.push({ action: 'delete', slug: entry.slug, title: entry.title, body: null });
      }
    }
    return { changes, cursor: this.lines.length };
  }
}
