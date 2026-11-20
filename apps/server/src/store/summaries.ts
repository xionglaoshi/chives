/** Task summaries and the accumulated symbol-name table used by segmentation. */

import type { DatabaseSync } from 'node:sqlite';

import type {
  NewTaskSummary,
  SummaryKeyNumber,
  SummarySymbol,
  TaskSummaryRecord,
} from './types.js';
import { indexSummary } from './search.js';

interface SummaryRow {
  task_id: string;
  title: string;
  conclusion: string;
  key_numbers: string;
  deliverables: string;
  open_questions: string;
  symbols: string;
  created_at: string;
  source: 'model' | 'fallback';
}

interface SymbolNameRow {
  code: string;
  name: string;
}

function parseArray<T>(raw: string, coerce: (value: unknown) => T | undefined): T[] {
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry) => {
      const item = coerce(entry);
      return item === undefined ? [] : [item];
    });
  } catch {
    return [];
  }
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

function toKeyNumber(value: unknown): SummaryKeyNumber | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return undefined;
  const entry = value as Record<string, unknown>;
  return {
    label: asString(entry['label']) ?? '',
    value: asString(entry['value']) ?? String(entry['value'] ?? ''),
    source: asString(entry['source']) ?? '',
    asOf: asString(entry['asOf']) ?? asString(entry['as_of']) ?? '',
  };
}

function toSymbol(value: unknown): SummarySymbol | undefined {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return undefined;
  const entry = value as Record<string, unknown>;
  const code = asString(entry['code']);
  if (code === undefined || code.trim() === '') return undefined;
  return { code: code.trim().toUpperCase(), name: asString(entry['name']) ?? '' };
}

function toSummary(row: SummaryRow): TaskSummaryRecord {
  return {
    taskId: row.task_id,
    title: row.title,
    conclusion: row.conclusion,
    keyNumbers: parseArray(row.key_numbers, toKeyNumber),
    deliverables: parseArray(row.deliverables, asString),
    openQuestions: parseArray(row.open_questions, asString),
    symbols: parseArray(row.symbols, toSymbol),
    createdAt: row.created_at,
    source: row.source === 'model' ? 'model' : 'fallback',
  };
}

export class TaskSummaryRepository {
  constructor(private readonly db: DatabaseSync) {}

  listAll(): TaskSummaryRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM task_summaries ORDER BY created_at, rowid')
      .all() as unknown as SummaryRow[];
    return rows.map(toSummary);
  }

  get(taskId: string): TaskSummaryRecord | undefined {
    const row = this.db
      .prepare('SELECT * FROM task_summaries WHERE task_id = ?')
      .get(taskId) as SummaryRow | undefined;
    return row === undefined ? undefined : toSummary(row);
  }

  upsert(record: NewTaskSummary | TaskSummaryRecord): TaskSummaryRecord {
    const stored: TaskSummaryRecord = {
      taskId: record.taskId,
      title: record.title,
      conclusion: record.conclusion,
      keyNumbers: record.keyNumbers ?? [],
      deliverables: record.deliverables ?? [],
      openQuestions: record.openQuestions ?? [],
      symbols: record.symbols ?? [],
      createdAt: record.createdAt,
      source: record.source,
    };
    this.db
      .prepare(
        `INSERT INTO task_summaries
           (task_id, title, conclusion, key_numbers, deliverables, open_questions, symbols,
            created_at, source)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT (task_id) DO UPDATE SET
           title = excluded.title,
           conclusion = excluded.conclusion,
           key_numbers = excluded.key_numbers,
           deliverables = excluded.deliverables,
           open_questions = excluded.open_questions,
           symbols = excluded.symbols,
           created_at = excluded.created_at,
           source = excluded.source`,
      )
      .run(
        stored.taskId,
        stored.title,
        stored.conclusion,
        JSON.stringify(stored.keyNumbers),
        JSON.stringify(stored.deliverables),
        JSON.stringify(stored.openQuestions),
        JSON.stringify(stored.symbols),
        stored.createdAt,
        stored.source,
      );
    indexSummary(this.db, stored);
    return stored;
  }

  /** Accumulates name -> code pairs from summaries; later names win. */
  upsertSymbolNames(symbols: readonly SummarySymbol[], updatedAt: string): void {
    const statement = this.db.prepare(
      `INSERT INTO symbol_names (code, name, updated_at) VALUES (?, ?, ?)
       ON CONFLICT (code) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at`,
    );
    for (const symbol of symbols) {
      if (symbol.code === '' || symbol.name === '') continue;
      statement.run(symbol.code, symbol.name, updatedAt);
    }
  }

  /** Name -> code map. A duplicate name keeps the most recently updated code. */
  symbolNameMap(): Record<string, string> {
    const rows = this.db
      .prepare('SELECT code, name FROM symbol_names ORDER BY updated_at, rowid')
      .all() as unknown as SymbolNameRow[];
    const map: Record<string, string> = {};
    for (const row of rows) map[row.name] = row.code;
    return map;
  }
}
