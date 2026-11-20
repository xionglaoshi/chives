/** Context-window usage samples recorded once per harness `usage` event. */

import type { DatabaseSync } from 'node:sqlite';

import type { UsageRecord } from './types.js';

interface UsageRow {
  task_id: string;
  at: string;
  used: number;
  size: number;
}

function toUsage(row: UsageRow): UsageRecord {
  return { taskId: row.task_id, at: row.at, used: row.used, size: row.size };
}

export class UsageRepository {
  constructor(private readonly db: DatabaseSync) {}

  add(taskId: string, used: number, size: number, at = new Date()): UsageRecord {
    this.db.prepare('INSERT INTO usage (task_id, at, used, size) VALUES (?, ?, ?, ?)').run(
      taskId,
      at.toISOString(),
      used,
      size,
    );
    return { taskId, at: at.toISOString(), used, size };
  }

  listByTask(taskId: string): UsageRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM usage WHERE task_id = ? ORDER BY at, rowid')
      .all(taskId) as unknown as UsageRow[];
    return rows.map(toUsage);
  }

  /** Records the last sample of one turn; `context_usage` has one row per turn. */
  addRound(taskId: string, used: number, size: number, at = new Date()): UsageRecord {
    const iso = at.toISOString();
    this.db
      .prepare('INSERT INTO context_usage (task_id, at, used, size) VALUES (?, ?, ?, ?)')
      .run(taskId, iso, used, size);
    return { taskId, at: iso, used, size };
  }

  /** Per-turn context usage for one task, oldest first. */
  listRoundsByTask(taskId: string): UsageRecord[] {
    const rows = this.db
      .prepare('SELECT task_id, at, used, size FROM context_usage WHERE task_id = ? ORDER BY id')
      .all(taskId) as unknown as UsageRow[];
    return rows.map(toUsage);
  }

  /** Per-turn context usage across a bot's user tasks, newest first. */
  listRoundsByBot(botId: string, limit: number): UsageRecord[] {
    const rows = this.db
      .prepare(
        `SELECT c.task_id, c.at, c.used, c.size FROM context_usage c
           JOIN tasks t ON t.id = c.task_id
          WHERE t.bot_id = ? AND t.delegated = 0
          ORDER BY c.at DESC, c.id DESC LIMIT ?`,
      )
      .all(botId, limit) as unknown as UsageRow[];
    return rows.map(toUsage);
  }

  /** Recent samples across a bot's user tasks, newest first. */
  listByBot(botId: string, limit: number): UsageRecord[] {
    const rows = this.db
      .prepare(
        `SELECT u.task_id, u.at, u.used, u.size FROM usage u
           JOIN tasks t ON t.id = u.task_id
          WHERE t.bot_id = ? AND t.delegated = 0
          ORDER BY u.at DESC, u.rowid DESC LIMIT ?`,
      )
      .all(botId, limit) as unknown as UsageRow[];
    return rows.map(toUsage);
  }

  /** Latest sample for a task, or undefined when the harness never reported usage. */
  latestForTask(taskId: string): UsageRecord | undefined {
    const row = this.db
      .prepare('SELECT * FROM usage WHERE task_id = ? ORDER BY at DESC, rowid DESC LIMIT 1')
      .get(taskId) as UsageRow | undefined;
    return row === undefined ? undefined : toUsage(row);
  }
}
