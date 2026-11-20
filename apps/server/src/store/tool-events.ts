/** Tool call steps attached to a task (and optionally to a committed message). */

import type { DatabaseSync } from 'node:sqlite';

import type { NewToolEvent, ToolEventRecord, ToolEventStatus } from './types.js';

interface ToolEventRow {
  id: string;
  task_id: string;
  message_id: string | null;
  tool_call_id: string;
  title: string;
  kind: string;
  raw_input: string | null;
  status: ToolEventStatus;
  output: string | null;
  started_at: string;
  ended_at: string | null;
}

function parseRawInput(raw: string | null): unknown {
  if (raw === null || raw === '') return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

function toToolEvent(row: ToolEventRow): ToolEventRecord {
  return {
    id: row.id,
    taskId: row.task_id,
    messageId: row.message_id,
    toolCallId: row.tool_call_id,
    title: row.title,
    kind: row.kind,
    rawInput: parseRawInput(row.raw_input),
    status: row.status,
    output: row.output,
    startedAt: row.started_at,
    endedAt: row.ended_at,
  };
}

export class ToolEventRepository {
  constructor(private readonly db: DatabaseSync) {}

  start(input: NewToolEvent): ToolEventRecord {
    const rawInput = input.rawInput === undefined ? null : JSON.stringify(input.rawInput);
    this.db
      .prepare(
        `INSERT INTO tool_events
           (id, task_id, message_id, tool_call_id, title, kind, raw_input, status, output, started_at, ended_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'running', NULL, ?, NULL)`,
      )
      .run(
        input.id,
        input.taskId,
        input.messageId ?? null,
        input.toolCallId,
        input.title,
        input.kind,
        rawInput,
        input.startedAt,
      );
    const created = this.get(input.id);
    if (created === undefined) throw new Error(`failed to record tool event "${input.id}"`);
    return created;
  }

  get(id: string): ToolEventRecord | undefined {
    const row = this.db.prepare('SELECT * FROM tool_events WHERE id = ?').get(id) as
      | ToolEventRow
      | undefined;
    return row === undefined ? undefined : toToolEvent(row);
  }

  /** Ends the newest still-running row for this task/toolCallId pair. */
  finish(
    taskId: string,
    toolCallId: string,
    status: Exclude<ToolEventStatus, 'running'>,
    output: string,
    endedAt: string,
  ): ToolEventRecord | undefined {
    const target = this.db
      .prepare(
        `SELECT id FROM tool_events
         WHERE task_id = ? AND tool_call_id = ? AND status = 'running'
         ORDER BY started_at DESC, rowid DESC LIMIT 1`,
      )
      .get(taskId, toolCallId) as { id: string } | undefined;
    if (target === undefined) return undefined;
    this.db
      .prepare('UPDATE tool_events SET status = ?, output = ?, ended_at = ? WHERE id = ?')
      .run(status, output, endedAt, target.id);
    return this.get(target.id);
  }

  listByTask(taskId: string): ToolEventRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM tool_events WHERE task_id = ? ORDER BY started_at, rowid')
      .all(taskId) as unknown as ToolEventRow[];
    return rows.map(toToolEvent);
  }
}
