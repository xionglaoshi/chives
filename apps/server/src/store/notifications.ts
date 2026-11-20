/** User-facing notifications emitted by `notify_user` and budget guardrails. */

import type { DatabaseSync } from 'node:sqlite';

import type { NewNotification, NotificationRecord } from './types.js';

interface NotificationRow {
  id: string;
  bot_id: string;
  task_id: string;
  title: string;
  body: string;
  level: NotificationRecord['level'];
  created_at: string;
  read_at: string | null;
}

function toNotification(row: NotificationRow): NotificationRecord {
  return {
    id: row.id,
    botId: row.bot_id,
    taskId: row.task_id,
    title: row.title,
    body: row.body,
    level: row.level,
    createdAt: row.created_at,
    readAt: row.read_at,
  };
}

export class NotificationRepository {
  constructor(private readonly db: DatabaseSync) {}

  add(input: NewNotification): NotificationRecord {
    this.db
      .prepare(
        `INSERT INTO notifications (id, bot_id, task_id, title, body, level, created_at, read_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, NULL)`,
      )
      .run(
        input.id,
        input.botId,
        input.taskId,
        input.title,
        input.body,
        input.level,
        input.createdAt,
      );
    const created = this.get(input.id);
    if (created === undefined) throw new Error(`failed to create notification "${input.id}"`);
    return created;
  }

  get(id: string): NotificationRecord | undefined {
    const row = this.db.prepare('SELECT * FROM notifications WHERE id = ?').get(id) as
      | NotificationRow
      | undefined;
    return row === undefined ? undefined : toNotification(row);
  }

  list(options: { botId?: string; unreadOnly?: boolean; limit: number }): NotificationRecord[] {
    const clauses: string[] = [];
    const values: Array<string | number> = [];
    if (options.botId !== undefined) {
      clauses.push('bot_id = ?');
      values.push(options.botId);
    }
    if (options.unreadOnly === true) clauses.push('read_at IS NULL');
    const where = clauses.length === 0 ? '' : `WHERE ${clauses.join(' AND ')}`;
    values.push(options.limit);
    const rows = this.db
      .prepare(`SELECT * FROM notifications ${where} ORDER BY created_at DESC, rowid DESC LIMIT ?`)
      .all(...values) as unknown as NotificationRow[];
    return rows.map(toNotification);
  }

  markRead(id: string, at: string): NotificationRecord | undefined {
    this.db
      .prepare('UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL')
      .run(at, id);
    return this.get(id);
  }

  markAllRead(at: string): number {
    const result = this.db
      .prepare('UPDATE notifications SET read_at = ? WHERE read_at IS NULL')
      .run(at);
    return Number(result.changes);
  }

  countUnreadByBot(): Record<string, number> {
    const rows = this.db
      .prepare(
        'SELECT bot_id, COUNT(*) AS count FROM notifications WHERE read_at IS NULL GROUP BY bot_id',
      )
      .all() as unknown as Array<{ bot_id: string; count: number }>;
    const counts: Record<string, number> = {};
    for (const row of rows) counts[row.bot_id] = row.count;
    return counts;
  }

  countForBotSince(botId: string, sinceIso: string): number {
    const row = this.db
      .prepare('SELECT COUNT(*) AS count FROM notifications WHERE bot_id = ? AND created_at >= ?')
      .get(botId, sinceIso) as { count: number };
    return row.count;
  }

  countForTask(taskId: string): number {
    const row = this.db
      .prepare('SELECT COUNT(*) AS count FROM notifications WHERE task_id = ?')
      .get(taskId) as { count: number };
    return row.count;
  }
}
