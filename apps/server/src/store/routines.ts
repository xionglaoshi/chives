/** Scheduled proactive routines: manifest defaults plus user overrides in SQLite. */

import type { DatabaseSync } from 'node:sqlite';

import type { NewRoutine, RoutineRecord, RoutineSchedule, RoutineSource } from './types.js';

interface RoutineRow {
  id: string;
  bot_id: string;
  source: RoutineSource;
  title: string;
  schedule: string;
  prompt: string;
  trading_days_only: number;
  enabled: number;
  created_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
}

function parseSchedule(raw: string): RoutineSchedule {
  const value: unknown = JSON.parse(raw);
  if (typeof value !== 'object' || value === null) throw new Error('routine schedule is not an object');
  return value as RoutineSchedule;
}

function toRoutine(row: RoutineRow): RoutineRecord {
  return {
    id: row.id,
    botId: row.bot_id,
    source: row.source,
    title: row.title,
    schedule: parseSchedule(row.schedule),
    prompt: row.prompt,
    tradingDaysOnly: row.trading_days_only === 1,
    enabled: row.enabled === 1,
    createdAt: row.created_at,
    lastRunAt: row.last_run_at,
    nextRunAt: row.next_run_at,
  };
}

export class RoutineRepository {
  constructor(private readonly db: DatabaseSync) {}

  /** Inserts or refreshes a manifest routine without touching the user's on/off switch. */
  upsertManifest(input: NewRoutine): RoutineRecord {
    this.db
      .prepare(
        `INSERT INTO routines
           (id, bot_id, source, title, schedule, prompt, trading_days_only, enabled,
            created_at, last_run_at, next_run_at)
         VALUES (?, ?, 'manifest', ?, ?, ?, ?, ?, ?, NULL, ?)
         ON CONFLICT (id) DO UPDATE SET
           title = excluded.title,
           schedule = excluded.schedule,
           prompt = excluded.prompt,
           trading_days_only = excluded.trading_days_only,
           next_run_at = CASE
             WHEN routines.schedule <> excluded.schedule THEN excluded.next_run_at
             ELSE routines.next_run_at
           END,
           source = 'manifest'`,
      )
      .run(
        input.id,
        input.botId,
        input.title,
        JSON.stringify(input.schedule),
        input.prompt,
        input.tradingDaysOnly ? 1 : 0,
        input.enabled ? 1 : 0,
        input.createdAt,
        input.nextRunAt,
      );
    const created = this.get(input.id);
    if (created === undefined) throw new Error(`failed to upsert routine "${input.id}"`);
    return created;
  }

  create(input: NewRoutine): RoutineRecord {
    this.db
      .prepare(
        `INSERT INTO routines
           (id, bot_id, source, title, schedule, prompt, trading_days_only, enabled,
            created_at, last_run_at, next_run_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)`,
      )
      .run(
        input.id,
        input.botId,
        input.source,
        input.title,
        JSON.stringify(input.schedule),
        input.prompt,
        input.tradingDaysOnly ? 1 : 0,
        input.enabled ? 1 : 0,
        input.createdAt,
        input.nextRunAt,
      );
    const created = this.get(input.id);
    if (created === undefined) throw new Error(`failed to create routine "${input.id}"`);
    return created;
  }

  get(id: string): RoutineRecord | undefined {
    const row = this.db.prepare('SELECT * FROM routines WHERE id = ?').get(id) as
      | RoutineRow
      | undefined;
    return row === undefined ? undefined : toRoutine(row);
  }

  listByBot(botId: string): RoutineRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM routines WHERE bot_id = ? ORDER BY created_at, rowid')
      .all(botId) as unknown as RoutineRow[];
    return rows.map(toRoutine);
  }

  list(): RoutineRecord[] {
    const rows = this.db.prepare('SELECT * FROM routines ORDER BY bot_id, created_at, rowid').all() as unknown as RoutineRow[];
    return rows.map(toRoutine);
  }

  listDue(nowIso: string): RoutineRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM routines
          WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
          ORDER BY next_run_at, rowid`,
      )
      .all(nowIso) as unknown as RoutineRow[];
    return rows.map(toRoutine);
  }

  edit(id: string, input: Pick<RoutineRecord, 'title' | 'schedule' | 'prompt' | 'tradingDaysOnly' | 'nextRunAt'>): RoutineRecord | undefined {
    this.db.prepare(`UPDATE routines SET title = ?, schedule = ?, prompt = ?, trading_days_only = ?, next_run_at = ? WHERE id = ?`)
      .run(input.title, JSON.stringify(input.schedule), input.prompt, input.tradingDaysOnly ? 1 : 0, input.nextRunAt, id);
    return this.get(id);
  }

  setEnabled(id: string, enabled: boolean): RoutineRecord | undefined {
    this.db.prepare('UPDATE routines SET enabled = ? WHERE id = ?').run(enabled ? 1 : 0, id);
    return this.get(id);
  }

  setNextRun(id: string, nextRunAt: string | null): RoutineRecord | undefined {
    this.db.prepare('UPDATE routines SET next_run_at = ? WHERE id = ?').run(nextRunAt, id);
    return this.get(id);
  }

  markRun(id: string, lastRunAt: string, nextRunAt: string | null): RoutineRecord | undefined {
    this.db
      .prepare('UPDATE routines SET last_run_at = ?, next_run_at = ? WHERE id = ?')
      .run(lastRunAt, nextRunAt, id);
    return this.get(id);
  }

  delete(id: string): boolean {
    const result = this.db.prepare('DELETE FROM routines WHERE id = ?').run(id);
    return result.changes > 0;
  }

  countEnabledByBot(botId: string): number {
    const row = this.db
      .prepare('SELECT COUNT(*) AS count FROM routines WHERE bot_id = ? AND enabled = 1')
      .get(botId) as { count: number };
    return row.count;
  }
}
