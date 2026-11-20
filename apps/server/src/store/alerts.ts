/** Cursors and per-alert processing records for proactive alert routing. */

import type { DatabaseSync } from 'node:sqlite';

import type { AlertEventRecord, NewAlertEvent } from './types.js';

interface AlertEventRow {
  id: number;
  source: string;
  alert_id: number;
  alert_ts: string | null;
  code: string | null;
  name: string | null;
  rule_id: string | null;
  status: string;
  reason: string | null;
  task_id: string | null;
  created_at: string;
}

function toEvent(row: AlertEventRow): AlertEventRecord {
  return {
    id: row.id,
    source: row.source,
    alertId: row.alert_id,
    alertTs: row.alert_ts,
    code: row.code,
    name: row.name,
    ruleId: row.rule_id,
    status: row.status === 'started' ? 'started' : 'skipped',
    reason: row.reason,
    taskId: row.task_id,
    createdAt: row.created_at,
  };
}

export class AlertEventRepository {
  constructor(private readonly db: DatabaseSync) {}

  add(input: NewAlertEvent): AlertEventRecord {
    const result = this.db
      .prepare(
        `INSERT INTO alert_events
           (source, alert_id, alert_ts, code, name, rule_id, status, reason, task_id, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        input.source,
        input.alertId,
        input.alertTs,
        input.code,
        input.name,
        input.ruleId,
        input.status,
        input.reason,
        input.taskId,
        input.createdAt,
      );
    const row = this.db
      .prepare('SELECT * FROM alert_events WHERE id = ?')
      .get(Number(result.lastInsertRowid)) as unknown as AlertEventRow;
    return toEvent(row);
  }

  list(limit: number): AlertEventRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM alert_events ORDER BY id DESC LIMIT ?')
      .all(limit) as unknown as AlertEventRow[];
    return rows.map(toEvent);
  }

  /** Timestamp of the most recent alert that actually started a task for this key. */
  lastStartedTs(source: string, code: string, ruleId: string): string | null {
    const row = this.db
      .prepare(
        `SELECT alert_ts FROM alert_events
          WHERE source = ? AND code = ? AND rule_id = ? AND status = 'started'
          ORDER BY id DESC LIMIT 1`,
      )
      .get(source, code, ruleId) as { alert_ts: string | null } | undefined;
    return row?.alert_ts ?? null;
  }

  /** Same as {@link lastStartedTs}, for merged strategy groups where the code varies. */
  lastStartedAtByRule(source: string, ruleId: string): string | null {
    const row = this.db
      .prepare(
        `SELECT created_at FROM alert_events
          WHERE source = ? AND rule_id = ? AND status = 'started'
          ORDER BY id DESC LIMIT 1`,
      )
      .get(source, ruleId) as { created_at: string | null } | undefined;
    return row?.created_at ?? null;
  }

  /** Most recent strategy wake, matched by the `strategy:<id>` rule prefix. */
  lastStartedAtForStrategy(source: string, strategyId: string): string | null {
    const row = this.db
      .prepare(
        `SELECT alert_ts FROM alert_events
          WHERE source = ? AND status = 'started' AND rule_id LIKE ?
          ORDER BY id DESC LIMIT 1`,
      )
      .get(source, `${strategyId}:%`) as { alert_ts: string | null } | undefined;
    return row?.alert_ts ?? null;
  }
}
