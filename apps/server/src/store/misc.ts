import {PersonalSettings} from './personal-settings.js';
/** Deliverables, approvals, and key/value settings. Table-first for later tasks. */

import type { DatabaseSync } from 'node:sqlite';

import type { ApprovalRecord, DeliverableRecord, JsonRecord } from './types.js';
import { indexDeliverable } from './search.js';

interface DeliverableRow {
  id: string;
  task_id: string;
  bot_id: string;
  path: string;
  kind: string;
  size: number;
  created_at: string;
}

interface ApprovalRow {
  id: string;
  task_id: string;
  tool_call_id: string;
  request: string;
  decision: string | null;
  decided_at: string | null;
  decided_by: string | null;
}

function parseRecord(raw: string): JsonRecord {
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      return value as JsonRecord;
    }
  } catch {
    // Fall through to an empty record; malformed JSON is not fatal here.
  }
  return {};
}

function toDeliverable(row: DeliverableRow): DeliverableRecord {
  return {
    id: row.id,
    taskId: row.task_id,
    botId: row.bot_id,
    path: row.path,
    kind: row.kind,
    size: row.size,
    createdAt: row.created_at,
  };
}

function toApproval(row: ApprovalRow): ApprovalRecord {
  return {
    id: row.id,
    taskId: row.task_id,
    toolCallId: row.tool_call_id,
    request: parseRecord(row.request),
    decision: row.decision,
    decidedAt: row.decided_at,
    decidedBy: row.decided_by,
  };
}

export class DeliverableRepository {
  constructor(private readonly db: DatabaseSync) {}

  add(record: DeliverableRecord): DeliverableRecord {
    this.db
      .prepare(
        `INSERT INTO deliverables (id, task_id, bot_id, path, kind, size, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.id,
        record.taskId,
        record.botId,
        record.path,
        record.kind,
        record.size,
        record.createdAt,
      );
    indexDeliverable(this.db, record);
    return record;
  }

  /**
   * One row per (task, bot, relative path): a later turn that rewrites the
   * same file refreshes kind/size/time instead of appending a duplicate.
   */
  upsert(record: DeliverableRecord): DeliverableRecord {
    const existing = this.getByTaskPath(record.taskId, record.botId, record.path);
    if (existing === undefined) return this.add(record);
    this.db
      .prepare(
        `UPDATE deliverables SET kind = ?, size = ?, created_at = ? WHERE id = ?`,
      )
      .run(record.kind, record.size, record.createdAt, existing.id);
    const updated = this.get(existing.id);
    if (updated === undefined) throw new Error(`failed to update deliverable "${existing.id}"`);
    indexDeliverable(this.db, updated);
    return updated;
  }

  get(id: string): DeliverableRecord | undefined {
    const row = this.db.prepare('SELECT * FROM deliverables WHERE id = ?').get(id) as
      | DeliverableRow
      | undefined;
    return row === undefined ? undefined : toDeliverable(row);
  }

  getByTaskPath(taskId: string, botId: string, path: string): DeliverableRecord | undefined {
    const row = this.db
      .prepare('SELECT * FROM deliverables WHERE task_id = ? AND bot_id = ? AND path = ?')
      .get(taskId, botId, path) as DeliverableRow | undefined;
    return row === undefined ? undefined : toDeliverable(row);
  }

  listByTask(taskId: string): DeliverableRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM deliverables WHERE task_id = ? ORDER BY created_at, rowid')
      .all(taskId) as unknown as DeliverableRow[];
    return rows.map(toDeliverable);
  }

  listByBot(botId: string, limit: number): DeliverableRecord[] {
    const rows = this.db
      .prepare(
        'SELECT * FROM deliverables WHERE bot_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?',
      )
      .all(botId, limit) as unknown as DeliverableRow[];
    return rows.map(toDeliverable);
  }

  listAll(): DeliverableRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM deliverables ORDER BY bot_id, created_at, rowid')
      .all() as unknown as DeliverableRow[];
    return rows.map(toDeliverable);
  }

  countByTask(taskId: string): number {
    const row = this.db
      .prepare('SELECT COUNT(*) AS count FROM deliverables WHERE task_id = ?')
      .get(taskId) as { count: number };
    return row.count;
  }
}

export class ApprovalRepository {
  constructor(private readonly db: DatabaseSync) {}

  add(record: ApprovalRecord): ApprovalRecord {
    this.db
      .prepare(
        `INSERT INTO approvals (id, task_id, tool_call_id, request, decision, decided_at, decided_by)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        record.id,
        record.taskId,
        record.toolCallId,
        JSON.stringify(record.request),
        record.decision,
        record.decidedAt,
        record.decidedBy,
      );
    return record;
  }

  listByTask(taskId: string): ApprovalRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM approvals WHERE task_id = ? ORDER BY rowid')
      .all(taskId) as unknown as ApprovalRow[];
    return rows.map(toApproval);
  }

  get(id: string): ApprovalRecord | undefined {
    const row = this.db.prepare('SELECT * FROM approvals WHERE id = ?').get(id) as
      | ApprovalRow
      | undefined;
    return row === undefined ? undefined : toApproval(row);
  }

  listPending(): ApprovalRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM approvals WHERE decision IS NULL ORDER BY rowid')
      .all() as unknown as ApprovalRow[];
    return rows.map(toApproval);
  }

  list(): ApprovalRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM approvals ORDER BY rowid')
      .all() as unknown as ApprovalRow[];
    return rows.map(toApproval);
  }

  decide(
    id: string,
    decision: string,
    decidedAt: string,
    decidedBy: string,
  ): ApprovalRecord | undefined {
    this.db
      .prepare(
        'UPDATE approvals SET decision = ?, decided_at = ?, decided_by = ? WHERE id = ? AND decision IS NULL',
      )
      .run(decision, decidedAt, decidedBy, id);
    return this.get(id);
  }
}

export class SettingsRepository {
  private personal?:PersonalSettings;
  constructor(private readonly db: DatabaseSync,dataDir?:string) {if(dataDir)this.personal=new PersonalSettings(dataDir,db);}

  get<T = unknown>(key: string): T | undefined {
    const path=this.personal?.path(key);if(path)return this.personal!.get(path);
    const row = this.db.prepare('SELECT value FROM settings WHERE key = ?').get(key) as
      | { value: string }
      | undefined;
    if (row === undefined) return undefined;
    try {
      return JSON.parse(row.value) as T;
    } catch {
      return undefined;
    }
  }

  set(key: string, value: unknown): void {
    const path=this.personal?.path(key);if(path)return this.personal!.set(path,value);
    this.db
      .prepare(
        `INSERT INTO settings (key, value) VALUES (?, ?)
         ON CONFLICT (key) DO UPDATE SET value = excluded.value`,
      )
      .run(key, JSON.stringify(value));
  }

  delete(key: string): void {
    const path=this.personal?.path(key);if(path)return this.personal!.delete(path);
    this.db.prepare('DELETE FROM settings WHERE key = ?').run(key);
  }

  list(): Record<string, unknown> {
    const rows = this.db.prepare('SELECT key, value FROM settings ORDER BY key').all() as unknown as Array<{
      key: string;
      value: string;
    }>;
    const result: Record<string, unknown> = this.personal?.list()??{};
    for (const row of rows) {
      try {
        result[row.key] = JSON.parse(row.value) as unknown;
      } catch {
        result[row.key] = row.value;
      }
    }
    return result;
  }
}
