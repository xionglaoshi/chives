/** Bot-owned watch plans and their append-only change history. */

import type { DatabaseSync } from 'node:sqlite';

import type {
  JsonRecord,
  NewWatch,
  NewWatchEvent,
  WatchEventKind,
  WatchEventRecord,
  WatchRecord,
  WatchStatus,
} from './types.js';

interface WatchRow {
  id: string;
  bot_id: string;
  code: string;
  name: string;
  label: string;
  note: string;
  plan: string;
  repeat: number;
  status: WatchStatus;
  engine_state: string | null;
  last_price: number | null;
  sync_error: string | null;
  created_task_id: string | null;
  updated_task_id: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  triggered_at: string | null;
  trigger_task_id: string | null;
  cancelled_by: WatchRecord['cancelledBy'];
}

interface WatchEventRow {
  id: number;
  watch_id: string;
  bot_id: string;
  kind: WatchEventKind;
  actor: WatchEventRecord['actor'];
  task_id: string | null;
  before: string | null;
  after: string | null;
  detail: string | null;
  created_at: string;
}

function parseJson(raw: string | null): JsonRecord | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    return typeof value === 'object' && value !== null && !Array.isArray(value)
      ? (value as JsonRecord)
      : null;
  } catch {
    return null;
  }
}

function toWatch(row: WatchRow): WatchRecord {
  return {
    id: row.id,
    botId: row.bot_id,
    code: row.code,
    name: row.name,
    label: row.label,
    note: row.note,
    plan: parseJson(row.plan) ?? {},
    repeat: row.repeat === 1,
    status: row.status,
    engineState: row.engine_state,
    lastPrice: row.last_price,
    syncError: row.sync_error,
    createdTaskId: row.created_task_id,
    updatedTaskId: row.updated_task_id,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    expiresAt: row.expires_at,
    triggeredAt: row.triggered_at,
    triggerTaskId: row.trigger_task_id,
    cancelledBy: row.cancelled_by,
  };
}

function toEvent(row: WatchEventRow): WatchEventRecord {
  return {
    id: row.id,
    watchId: row.watch_id,
    botId: row.bot_id,
    kind: row.kind,
    actor: row.actor,
    taskId: row.task_id,
    before: parseJson(row.before),
    after: parseJson(row.after),
    detail: row.detail,
    createdAt: row.created_at,
  };
}

export interface WatchPatch {
  code?: string;
  name?: string;
  label?: string;
  note?: string;
  plan?: JsonRecord;
  repeat?: boolean;
  status?: WatchStatus;
  engineState?: string | null;
  lastPrice?: number | null;
  syncError?: string | null;
  updatedTaskId?: string | null;
  updatedAt?: string;
  expiresAt?: string;
  triggeredAt?: string | null;
  triggerTaskId?: string | null;
  cancelledBy?: WatchRecord['cancelledBy'];
}

const PATCH_COLUMNS: Record<keyof WatchPatch, string> = {
  code: 'code',
  name: 'name',
  label: 'label',
  note: 'note',
  plan: 'plan',
  repeat: 'repeat',
  status: 'status',
  engineState: 'engine_state',
  lastPrice: 'last_price',
  syncError: 'sync_error',
  updatedTaskId: 'updated_task_id',
  updatedAt: 'updated_at',
  expiresAt: 'expires_at',
  triggeredAt: 'triggered_at',
  triggerTaskId: 'trigger_task_id',
  cancelledBy: 'cancelled_by',
};

export class WatchRepository {
  constructor(private readonly db: DatabaseSync) {}

  create(input: NewWatch): WatchRecord {
    this.db
      .prepare(
        `INSERT INTO watches
           (id, bot_id, code, name, label, note, plan, repeat, status, engine_state,
            last_price, sync_error, created_task_id, updated_task_id, created_at,
            updated_at, expires_at, triggered_at, trigger_task_id, cancelled_by)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)`,
      )
      .run(
        input.id,
        input.botId,
        input.code,
        input.name,
        input.label,
        input.note,
        JSON.stringify(input.plan),
        input.repeat ? 1 : 0,
        input.status,
        input.engineState,
        input.lastPrice,
        input.syncError,
        input.createdTaskId,
        input.updatedTaskId,
        input.createdAt,
        input.updatedAt,
        input.expiresAt,
        input.cancelledBy,
      );
    const created = this.get(input.id);
    if (created === undefined) throw new Error(`failed to create watch "${input.id}"`);
    return created;
  }

  get(id: string): WatchRecord | undefined {
    const row = this.db.prepare('SELECT * FROM watches WHERE id = ?').get(id) as
      | WatchRow
      | undefined;
    return row === undefined ? undefined : toWatch(row);
  }

  update(id: string, patch: WatchPatch): WatchRecord | undefined {
    const sets: string[] = [];
    const values: Array<string | number | null> = [];
    for (const key of Object.keys(patch) as Array<keyof WatchPatch>) {
      const value = patch[key];
      if (value === undefined) continue;
      sets.push(`${PATCH_COLUMNS[key]} = ?`);
      if (key === 'plan') values.push(JSON.stringify(value));
      else if (key === 'repeat') values.push(value === true ? 1 : 0);
      else values.push(value as string | number | null);
    }
    if (sets.length > 0) {
      values.push(id);
      this.db.prepare(`UPDATE watches SET ${sets.join(', ')} WHERE id = ?`).run(...values);
    }
    return this.get(id);
  }

  list(options: { botId?: string; status?: WatchStatus } = {}): WatchRecord[] {
    const clauses: string[] = [];
    const values: string[] = [];
    if (options.botId !== undefined) {
      clauses.push('bot_id = ?');
      values.push(options.botId);
    }
    if (options.status !== undefined) {
      clauses.push('status = ?');
      values.push(options.status);
    }
    const where = clauses.length === 0 ? '' : `WHERE ${clauses.join(' AND ')}`;
    const rows = this.db
      .prepare(`SELECT * FROM watches ${where} ORDER BY created_at, rowid`)
      .all(...values) as unknown as WatchRow[];
    return rows.map(toWatch);
  }

  listActive(): WatchRecord[] {
    return this.list({ status: 'active' });
  }

  listExpired(nowIso: string): WatchRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM watches
          WHERE status = 'active' AND expires_at <= ?
          ORDER BY expires_at, rowid`,
      )
      .all(nowIso) as unknown as WatchRow[];
    return rows.map(toWatch);
  }

  countActiveByBot(botId: string): number {
    const row = this.db
      .prepare("SELECT COUNT(*) AS count FROM watches WHERE bot_id = ? AND status = 'active'")
      .get(botId) as { count: number };
    return row.count;
  }

  countActiveChives(): number {
    const row = this.db
      .prepare("SELECT COUNT(*) AS count FROM watches WHERE status = 'active'")
      .get() as { count: number };
    return row.count;
  }

  events(watchId: string): WatchEventRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM watch_events WHERE watch_id = ? ORDER BY id')
      .all(watchId) as unknown as WatchEventRow[];
    return rows.map(toEvent);
  }

  addEvent(input: NewWatchEvent): WatchEventRecord {
    const result = this.db
      .prepare(
        `INSERT INTO watch_events
           (watch_id, bot_id, kind, actor, task_id, before, after, detail, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        input.watchId,
        input.botId,
        input.kind,
        input.actor,
        input.taskId,
        input.before === undefined || input.before === null ? null : JSON.stringify(input.before),
        input.after === undefined || input.after === null ? null : JSON.stringify(input.after),
        input.detail ?? null,
        input.createdAt,
      );
    const rows = this.db
      .prepare('SELECT * FROM watch_events WHERE id = ?')
      .get(Number(result.lastInsertRowid)) as unknown as WatchEventRow;
    return toEvent(rows);
  }
}
