/** Timeline messages: the authoritative history, ordered per bot by `seq`. */

import type { DatabaseSync } from 'node:sqlite';

import { transaction } from './db.js';
import { indexMessage } from './search.js';
import type { JsonRecord, MessageKind, MessagePage, MessageRecord, MessageRole, NewMessage } from './types.js';

interface MessageRow {
  id: string;
  bot_id: string;
  task_id: string | null;
  role: MessageRole;
  kind: MessageKind;
  content: string;
  meta: string | null;
  created_at: string;
  seq: number;
}

function parseMeta(raw: string | null): JsonRecord | null {
  if (raw === null || raw === '') return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      return value as JsonRecord;
    }
  } catch {
    // A malformed meta column must not hide the message itself.
  }
  return null;
}

function toMessage(row: MessageRow): MessageRecord {
  return {
    id: row.id,
    botId: row.bot_id,
    taskId: row.task_id,
    role: row.role,
    kind: row.kind,
    content: row.content,
    meta: parseMeta(row.meta),
    createdAt: row.created_at,
    seq: row.seq,
  };
}

export class MessageRepository {
  constructor(private readonly db: DatabaseSync) {}

  get(id: string): MessageRecord | undefined {
    const row = this.db.prepare('SELECT * FROM messages WHERE id = ?').get(id) as
      | MessageRow
      | undefined;
    return row === undefined ? undefined : toMessage(row);
  }

  append(input: NewMessage): MessageRecord {
    return transaction(this.db, () => {
      const row = this.db
        .prepare('SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM messages WHERE bot_id = ?')
        .get(input.botId) as { seq: number };
      const meta = input.meta === undefined || input.meta === null ? null : JSON.stringify(input.meta);
      this.db
        .prepare(
          `INSERT INTO messages (id, bot_id, task_id, role, kind, content, meta, created_at, seq)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        )
        .run(
          input.id,
          input.botId,
          input.taskId,
          input.role,
          input.kind,
          input.content,
          meta,
          input.createdAt,
          row.seq,
        );
      const created = this.get(input.id);
      if (created === undefined) throw new Error(`failed to append message "${input.id}"`);
      indexMessage(this.db, created);
      return created;
    });
  }

  listPage(botId: string, beforeSeq: number | null, limit: number): MessagePage {
    // Delegated children run in the target bot's workspace but must not show
    // up in its user-facing timeline.
    const visible = `bot_id = ? AND (
      task_id IS NULL OR task_id NOT IN (SELECT id FROM tasks WHERE delegated = 1)
    )`;
    const rows = (
      beforeSeq === null
        ? this.db
            .prepare(`SELECT * FROM messages WHERE ${visible} ORDER BY seq DESC LIMIT ?`)
            .all(botId, limit + 1)
        : this.db
            .prepare(`SELECT * FROM messages WHERE ${visible} AND seq < ? ORDER BY seq DESC LIMIT ?`)
            .all(botId, beforeSeq, limit + 1)
    ) as unknown as MessageRow[];

    const hasMore = rows.length > limit;
    const page = rows.slice(0, limit).reverse().map(toMessage);
    const first = page[0];
    return {
      messages: page,
      hasMore,
      nextBeforeSeq: hasMore && first !== undefined ? first.seq : null,
    };
  }

  /** Every visible timeline message, across bots; used by the settings export. */
  listAll(): MessageRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM messages
          WHERE task_id IS NULL OR task_id NOT IN (SELECT id FROM tasks WHERE delegated = 1)
          ORDER BY bot_id, seq`,
      )
      .all() as unknown as MessageRow[];
    return rows.map(toMessage);
  }

  listByTask(taskId: string): MessageRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM messages WHERE task_id = ? ORDER BY seq')
      .all(taskId) as unknown as MessageRow[];
    return rows.map(toMessage);
  }

  /** Most recent user/bot text messages before `beforeSeq`, returned oldest first. */
  listRecentText(botId: string, limit: number, beforeSeq: number): MessageRecord[] {
    const rows = this.db
      .prepare(
        `SELECT m.* FROM messages m
           LEFT JOIN tasks t ON t.id = m.task_id
          WHERE m.bot_id = ?
            AND (m.task_id IS NULL OR t.delegated = 0)
            AND m.role IN ('user', 'bot')
            AND m.kind = 'text'
            AND m.seq < ?
          ORDER BY m.seq DESC LIMIT ?`,
      )
      .all(botId, beforeSeq, limit) as unknown as MessageRow[];
    return rows.reverse().map(toMessage);
  }

  lastMessageAt(taskId: string): string | null {
    const row = this.db
      .prepare('SELECT MAX(created_at) AS at FROM messages WHERE task_id = ?')
      .get(taskId) as { at: string | null } | undefined;
    return row?.at ?? null;
  }

  listByKind(kind: MessageKind): MessageRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM messages WHERE kind = ? ORDER BY bot_id, seq')
      .all(kind) as unknown as MessageRow[];
    return rows.map(toMessage);
  }

  updateMeta(id: string, meta: JsonRecord | null): MessageRecord | undefined {
    this.db
      .prepare('UPDATE messages SET meta = ? WHERE id = ?')
      .run(meta === null ? null : JSON.stringify(meta), id);
    return this.get(id);
  }

  countForBot(botId: string): number {
    const row = this.db
      .prepare('SELECT COUNT(*) AS count FROM messages WHERE bot_id = ?')
      .get(botId) as { count: number };
    return row.count;
  }
}
