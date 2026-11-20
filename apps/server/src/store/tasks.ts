/** Task rows: one segment of work on a bot's single timeline. */

import { randomUUID } from 'node:crypto';
import type { DatabaseSync } from 'node:sqlite';

import type { JsonRecord, NewTask, TaskRecord, TaskStatus } from './types.js';

interface TaskRow {
  id: string;
  bot_id: string;
  title: string | null;
  status: TaskStatus;
  harness_session_id: string | null;
  started_at: string;
  ended_at: string | null;
  parent_task_id: string | null;
  depth: number;
  delegated: number;
  brief: string | null;
  closed_at: string | null;
  reopened_at: string | null;
  segment_reason: string | null;
  context_meta: string | null;
  last_context_used: number | null;
  last_context_size: number | null;
  origin: string | null;
  error_code: string | null;
}

function parseContextMeta(raw: string | null): JsonRecord | null {
  if (raw === null || raw === '') return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      return value as JsonRecord;
    }
  } catch {
    // A malformed debug column must not hide the task itself.
  }
  return null;
}

function toTask(row: TaskRow): TaskRecord {
  return {
    id: row.id,
    botId: row.bot_id,
    title: row.title,
    status: row.status,
    harnessSessionId: row.harness_session_id,
    startedAt: row.started_at,
    endedAt: row.ended_at,
    parentTaskId: row.parent_task_id,
    depth: row.depth,
    delegated: row.delegated === 1,
    brief: row.brief,
    closedAt: row.closed_at,
    reopenedAt: row.reopened_at,
    segmentReason: row.segment_reason,
    contextMeta: parseContextMeta(row.context_meta),
    lastContextUsed: row.last_context_used,
    lastContextSize: row.last_context_size,
    origin: row.origin,
    errorCode: row.error_code,
  };
}

const TERMINAL: readonly TaskStatus[] = ['done', 'failed', 'cancelled', 'interrupted'];

export function isTerminalStatus(status: TaskStatus): boolean {
  return TERMINAL.includes(status);
}

export class TaskRepository {
  constructor(private readonly db: DatabaseSync) {}

  create(input: Omit<NewTask, 'id'> & { id?: string }): TaskRecord {
    const id = input.id ?? randomUUID();
    this.db
      .prepare(
        `INSERT INTO tasks
           (id, bot_id, title, status, harness_session_id, started_at, ended_at, parent_task_id,
            depth, delegated, brief, origin)
         VALUES (?, ?, ?, 'running', NULL, ?, NULL, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        input.botId,
        input.title ?? null,
        input.startedAt,
        input.parentTaskId ?? null,
        input.depth ?? 0,
        input.delegated === true ? 1 : 0,
        input.brief ?? null,
        input.origin ?? null,
      );
    const created = this.get(id);
    if (created === undefined) throw new Error(`failed to create task "${id}"`);
    return created;
  }

  get(id: string): TaskRecord | undefined {
    const row = this.db.prepare('SELECT * FROM tasks WHERE id = ?').get(id) as TaskRow | undefined;
    return row === undefined ? undefined : toTask(row);
  }

  /** Every task, including delegated children; used by the settings export. */
  listAll(): TaskRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM tasks ORDER BY bot_id, started_at, rowid')
      .all() as unknown as TaskRow[];
    return rows.map(toTask);
  }

  latestForBot(botId: string): TaskRecord | undefined {
    // A reopened segment is unclosed even though it is older than tasks that
    // were created afterwards; it must stay the next continuation target.
    const row = this.db
      .prepare(
        `SELECT * FROM tasks
          WHERE bot_id = ? AND delegated = 0
          ORDER BY (closed_at IS NULL) DESC, started_at DESC, rowid DESC LIMIT 1`,
      )
      .get(botId) as TaskRow | undefined;
    return row === undefined ? undefined : toTask(row);
  }

  findRunning(botId: string): TaskRecord | undefined {
    const row = this.db
      .prepare(
        "SELECT * FROM tasks WHERE bot_id = ? AND delegated = 0 AND status = 'running' ORDER BY started_at DESC, rowid DESC LIMIT 1",
      )
      .get(botId) as TaskRow | undefined;
    return row === undefined ? undefined : toTask(row);
  }

  listRunning(): TaskRecord[] {
    const rows = this.db
      .prepare("SELECT * FROM tasks WHERE status = 'running' ORDER BY started_at, rowid")
      .all() as unknown as TaskRow[];
    return rows.map(toTask);
  }

  /** Reuses an existing task for a continuation: running again, ended_at cleared. */
  restart(id: string): TaskRecord {
    this.db
      .prepare(
        "UPDATE tasks SET status = 'running', ended_at = NULL, reopened_at = NULL, error_code = NULL WHERE id = ?",
      )
      .run(id);
    const task = this.get(id);
    if (task === undefined) throw new Error(`unknown task "${id}"`);
    return task;
  }

  setHarnessSession(id: string, sessionId: string | null): void {
    this.db.prepare('UPDATE tasks SET harness_session_id = ? WHERE id = ?').run(sessionId, id);
  }

  setTitle(id: string, title: string | null): void {
    this.db.prepare('UPDATE tasks SET title = ? WHERE id = ?').run(title, id);
  }

  setSegmentReason(id: string, reason: string | null): TaskRecord | undefined {
    this.db.prepare('UPDATE tasks SET segment_reason = ? WHERE id = ?').run(reason, id);
    return this.get(id);
  }

  setContextMeta(id: string, meta: JsonRecord | null): void {
    this.db
      .prepare('UPDATE tasks SET context_meta = ? WHERE id = ?')
      .run(meta === null ? null : JSON.stringify(meta), id);
  }

  setLastContext(id: string, used: number, size: number): void {
    this.db
      .prepare('UPDATE tasks SET last_context_used = ?, last_context_size = ? WHERE id = ?')
      .run(used, size, id);
  }

  /** Marks the end of a task segment once; false when it was already closed. */
  markClosed(id: string, closedAt: string): boolean {
    const result = this.db
      .prepare('UPDATE tasks SET closed_at = ? WHERE id = ? AND closed_at IS NULL')
      .run(closedAt, id);
    return result.changes > 0;
  }

  /** Clears the segment end and forces the next message to continue this task. */
  reopen(id: string, reopenedAt: string): TaskRecord | undefined {
    this.db
      .prepare('UPDATE tasks SET closed_at = NULL, reopened_at = ? WHERE id = ?')
      .run(reopenedAt, id);
    return this.get(id);
  }

  /** Cancels a pending reopen: the target becomes closed again at `closedAt`. */
  cancelReopen(id: string, closedAt: string): TaskRecord | undefined {
    this.db
      .prepare(
        `UPDATE tasks SET reopened_at = NULL, closed_at = COALESCE(closed_at, ?)
          WHERE id = ? AND reopened_at IS NOT NULL`,
      )
      .run(closedAt, id);
    return this.get(id);
  }

  /** Unclosed user-facing segments for one bot (a reopened target included). */
  listUnclosedForBot(botId: string): TaskRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM tasks
          WHERE bot_id = ? AND delegated = 0 AND closed_at IS NULL
          ORDER BY started_at, rowid`,
      )
      .all(botId) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  /** Closed user-task segments, newest first (delegated children never segment). */
  listRecentClosed(botId: string, limit: number): TaskRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM tasks
          WHERE bot_id = ? AND delegated = 0 AND closed_at IS NOT NULL
          ORDER BY closed_at DESC, rowid DESC LIMIT ?`,
      )
      .all(botId, limit) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  /**
   * Terminal, unclosed user tasks whose last message (or start) is at or before
   * `cutoff`. A running task is never closed by the idle scan.
   */
  listUnclosedBefore(cutoff: string): TaskRecord[] {
    const rows = this.db
      .prepare(
        `SELECT t.* FROM tasks t
           LEFT JOIN (
             SELECT task_id, MAX(created_at) AS last_at FROM messages GROUP BY task_id
           ) m ON m.task_id = t.id
          WHERE t.closed_at IS NULL
            AND t.delegated = 0
            AND t.status != 'running'
            AND COALESCE(m.last_at, t.started_at) <= ?
          ORDER BY COALESCE(m.last_at, t.started_at), t.rowid`,
      )
      .all(cutoff) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  /** Moves a task to a terminal state once; returns the stored record. */
  finish(id: string, status: TaskStatus, endedAt: string, errorCode: string | null = null): TaskRecord {
    this.db
      .prepare('UPDATE tasks SET status = ?, ended_at = ?, error_code = ? WHERE id = ?')
      .run(status, endedAt, errorCode, id);
    const task = this.get(id);
    if (task === undefined) throw new Error(`unknown task "${id}"`);
    return task;
  }

  /** Delegated children of one parent, newest first. */
  listByParent(parentTaskId: string): TaskRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY started_at DESC, rowid DESC')
      .all(parentTaskId) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  /** Proactive tasks (routines + alerts) started in one Asia/Shanghai calendar day. */
  countProactiveSince(startIso: string): number {
    const row = this.db
      .prepare(
        "SELECT COUNT(*) AS count FROM tasks WHERE origin IS NOT NULL AND started_at >= ?",
      )
      .get(startIso) as { count: number };
    return row.count;
  }

  /** Most recent tasks with a classified failure, newest first. */
  listWithErrorCode(limit: number): TaskRecord[] {
    const rows = this.db
      .prepare(
        `SELECT * FROM tasks WHERE error_code IS NOT NULL
          ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC LIMIT ?`,
      )
      .all(limit) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  listRunningDelegated(botId: string): TaskRecord[] {
    const rows = this.db
      .prepare(
        "SELECT * FROM tasks WHERE bot_id = ? AND delegated = 1 AND status = 'running' ORDER BY started_at, rowid",
      )
      .all(botId) as unknown as TaskRow[];
    return rows.map(toTask);
  }

  interruptRunning(endedAt: string): TaskRecord[] {
    const running = this.listRunning();
    const update = this.db.prepare(
      "UPDATE tasks SET status = 'interrupted', ended_at = ?, error_code = NULL WHERE id = ? AND status = 'running'",
    );
    for (const task of running) update.run(endedAt, task.id);
    return running.map((task) => ({ ...task, status: 'interrupted', endedAt }));
  }
}
