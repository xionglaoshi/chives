/** Per-task symbols maintained incrementally while a segment is still open. */

import type { DatabaseSync } from 'node:sqlite';

import { normalizeSymbolCode } from '../symbols.js';
import { transaction } from './db.js';
import type { SummarySymbol, TaskSymbol } from './types.js';

interface TaskSymbolRow {
  code: string;
  name: string | null;
  first_seen_at: string;
}

export class TaskSymbolRepository {
  constructor(private readonly db: DatabaseSync) {}

  listForTask(taskId: string): TaskSymbol[] {
    const rows = this.db
      .prepare('SELECT code, name, first_seen_at FROM task_symbols WHERE task_id = ? ORDER BY first_seen_at, rowid')
      .all(taskId) as unknown as TaskSymbolRow[];
    return rows.map((row) => ({
      code: row.code,
      name: row.name,
      firstSeenAt: row.first_seen_at,
    }));
  }

  /** Inserts new codes, keeps the first `first_seen_at`, and fills a NULL name only. */
  upsertAll(taskId: string, symbols: readonly SummarySymbol[], firstSeenAt: string): void {
    if (symbols.length === 0) return;
    const statement = this.db.prepare(
      `INSERT INTO task_symbols (task_id, code, name, first_seen_at) VALUES (?, ?, ?, ?)
       ON CONFLICT (task_id, code) DO UPDATE SET name = COALESCE(excluded.name, task_symbols.name)`,
    );
    transaction(this.db, () => {
      for (const symbol of symbols) {
        const code = normalizeSymbolCode(symbol.code);
        if (code === '') continue;
        const name = symbol.name.trim() === '' ? null : symbol.name.trim();
        statement.run(taskId, code, name, firstSeenAt);
      }
    });
  }
}
