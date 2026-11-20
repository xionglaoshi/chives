/** Timeline search index: FTS5 trigram content plus write-path indexing helpers. */

import type { DatabaseSync } from 'node:sqlite';

import type {
  DeliverableRecord,
  MessageRecord,
  TaskSummaryRecord,
} from './types.js';

export type SearchDocType = 'message' | 'summary' | 'deliverable';

export interface SearchDocumentRecord {
  id: number;
  timelineBotId: string;
  taskId: string;
  docType: SearchDocType;
  refId: string;
  title: string | null;
  body: string;
  createdAt: string;
  sortKey: string;
}

export interface NewSearchDocument {
  timelineBotId: string;
  taskId: string;
  docType: SearchDocType;
  refId: string;
  title: string | null;
  body: string;
  createdAt: string;
  sortKey: string;
}

interface SearchDocumentRow {
  id: number;
  timeline_bot_id: string;
  task_id: string;
  doc_type: SearchDocType;
  ref_id: string;
  title: string | null;
  body: string;
  created_at: string;
  sort_key: string;
}

interface RootTaskRow {
  id: string;
  bot_id: string;
  parent_task_id: string | null;
  title: string | null;
}

interface RootTask {
  id: string;
  botId: string;
  title: string | null;
}

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

function toDocument(row: SearchDocumentRow): SearchDocumentRecord {
  return {
    id: row.id,
    timelineBotId: row.timeline_bot_id,
    taskId: row.task_id,
    docType: row.doc_type,
    refId: row.ref_id,
    title: row.title,
    body: row.body,
    createdAt: row.created_at,
    sortKey: row.sort_key,
  };
}

/** Walks `parent_task_id` to the task that owns the bot's user-facing timeline. */
export function resolveRootTask(db: DatabaseSync, taskId: string): RootTask | undefined {
  let current = taskId;
  for (let depth = 0; depth < 16; depth += 1) {
    const row = db
      .prepare('SELECT id, bot_id, parent_task_id, title FROM tasks WHERE id = ?')
      .get(current) as RootTaskRow | undefined;
    if (row === undefined) return undefined;
    if (row.parent_task_id === null) {
      return { id: row.id, botId: row.bot_id, title: row.title };
    }
    current = row.parent_task_id;
  }
  return undefined;
}

export function summarySearchBody(summary: TaskSummaryRecord): string {
  const lines = [summary.title, summary.conclusion];
  for (const entry of summary.keyNumbers) {
    lines.push([entry.label, entry.value, entry.source, entry.asOf].filter((part) => part !== '').join(' '));
  }
  for (const question of summary.openQuestions) lines.push(question);
  return lines.filter((line) => line.trim() !== '').join('\n');
}

export function upsertSearchDocument(db: DatabaseSync, doc: NewSearchDocument): void {
  if (doc.body.trim() === '') return;
  db.prepare(
    `INSERT INTO search_documents
       (timeline_bot_id, task_id, doc_type, ref_id, title, body, created_at, sort_key)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (doc_type, ref_id) DO UPDATE SET
       timeline_bot_id = excluded.timeline_bot_id,
       task_id = excluded.task_id,
       title = excluded.title,
       body = excluded.body,
       created_at = excluded.created_at,
       sort_key = excluded.sort_key`,
  ).run(
    doc.timelineBotId,
    doc.taskId,
    doc.docType,
    doc.refId,
    doc.title,
    doc.body,
    doc.createdAt,
    doc.sortKey,
  );
}

export function indexMessage(db: DatabaseSync, message: MessageRecord): void {
  if (message.taskId === null) return;
  if (message.role !== 'user' && message.role !== 'bot') return;
  if (message.kind !== 'text' && message.kind !== 'proactive') return;
  if (message.content.trim() === '') return;
  const root = resolveRootTask(db, message.taskId);
  if (root === undefined) return;
  upsertSearchDocument(db, {
    timelineBotId: root.botId,
    taskId: root.id,
    docType: 'message',
    refId: message.id,
    title: null,
    body: message.content,
    createdAt: message.createdAt,
    sortKey: `${message.createdAt}|${String(message.seq).padStart(12, '0')}`,
  });
}

export function indexSummary(db: DatabaseSync, summary: TaskSummaryRecord): void {
  const root = resolveRootTask(db, summary.taskId);
  if (root === undefined) return;
  upsertSearchDocument(db, {
    timelineBotId: root.botId,
    taskId: root.id,
    docType: 'summary',
    refId: summary.taskId,
    title: summary.title,
    body: summarySearchBody(summary),
    createdAt: summary.createdAt,
    sortKey: `${summary.createdAt}|000000000000`,
  });
}

export function indexDeliverable(db: DatabaseSync, record: DeliverableRecord): void {
  const root = resolveRootTask(db, record.taskId);
  if (root === undefined) return;
  upsertSearchDocument(db, {
    timelineBotId: root.botId,
    taskId: root.id,
    docType: 'deliverable',
    refId: record.id,
    title: record.path,
    body: record.path,
    createdAt: record.createdAt,
    sortKey: `${record.createdAt}|000000000000`,
  });
}

function asStringArray(raw: string): string[] {
  try {
    const value: unknown = JSON.parse(raw);
    return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : [];
  } catch {
    return [];
  }
}

function summaryFromRow(row: SummaryRow): TaskSummaryRecord {
  let keyNumbers: TaskSummaryRecord['keyNumbers'] = [];
  try {
    const value: unknown = JSON.parse(row.key_numbers);
    if (Array.isArray(value)) {
      keyNumbers = value.flatMap((entry) => {
        if (typeof entry !== 'object' || entry === null || Array.isArray(entry)) return [];
        const record = entry as Record<string, unknown>;
        const text = (field: string): string =>
          typeof record[field] === 'string' ? (record[field] as string) : '';
        return [
          {
            label: text('label'),
            value: text('value'),
            source: text('source'),
            asOf: text('asOf') === '' ? text('as_of') : text('asOf'),
          },
        ];
      });
    }
  } catch {
    keyNumbers = [];
  }
  return {
    taskId: row.task_id,
    title: row.title,
    conclusion: row.conclusion,
    keyNumbers,
    deliverables: asStringArray(row.deliverables),
    openQuestions: asStringArray(row.open_questions),
    symbols: [],
    createdAt: row.created_at,
    source: row.source === 'model' ? 'model' : 'fallback',
  };
}

/**
 * Backfills the index for databases that already had messages/summaries/files
 * before migration 6. New rows are indexed by the repositories that write them.
 */
export function backfillSearchIndex(db: DatabaseSync): void {
  const messages = db
    .prepare(
      `SELECT id, bot_id, task_id, role, kind, content, meta, created_at, seq
         FROM messages
        WHERE task_id IS NOT NULL AND role IN ('user', 'bot') AND kind IN ('text', 'proactive')
        ORDER BY seq`,
    )
    .all() as unknown as Array<{
    id: string;
    bot_id: string;
    task_id: string;
    role: 'user' | 'bot';
    kind: 'text' | 'proactive';
    content: string;
    meta: string | null;
    created_at: string;
    seq: number;
  }>;
  for (const row of messages) {
    indexMessage(db, {
      id: row.id,
      botId: row.bot_id,
      taskId: row.task_id,
      role: row.role,
      kind: row.kind,
      content: row.content,
      meta: null,
      createdAt: row.created_at,
      seq: row.seq,
    });
  }

  const summaries = db.prepare('SELECT * FROM task_summaries').all() as unknown as SummaryRow[];
  for (const row of summaries) indexSummary(db, summaryFromRow(row));

  const deliverables = db
    .prepare('SELECT id, task_id, bot_id, path, kind, size, created_at FROM deliverables')
    .all() as unknown as Array<{
    id: string;
    task_id: string;
    bot_id: string;
    path: string;
    kind: string;
    size: number;
    created_at: string;
  }>;
  for (const row of deliverables) {
    indexDeliverable(db, {
      id: row.id,
      taskId: row.task_id,
      botId: row.bot_id,
      path: row.path,
      kind: row.kind,
      size: row.size,
      createdAt: row.created_at,
    });
  }
}

function escapeLike(term: string): string {
  return term.replace(/[\\%_]/g, (match) => `\\${match}`);
}

export class SearchRepository {
  constructor(private readonly db: DatabaseSync) {}

  /** One term: FTS5 trigram for 3+ code points, LIKE for shorter terms. */
  matchIds(timelineBotId: string, term: string): number[] {
    if ([...term].length >= 3) {
      // A quoted FTS string is a literal phrase, so `"`, `*`, `(` and NEAR
      // cannot become query syntax. Doubling `"` is FTS5's own escape.
      const expression = `"${term.replace(/"/g, '""')}"`;
      const rows = this.db
        .prepare(
          `SELECT d.id AS id
             FROM search_fts
             JOIN search_documents d ON d.id = search_fts.rowid
            WHERE search_fts MATCH ? AND d.timeline_bot_id = ?`,
        )
        .all(expression, timelineBotId) as unknown as Array<{ id: number }>;
      return rows.map((row) => row.id);
    }
    const rows = this.db
      .prepare(
        `SELECT id FROM search_documents
          WHERE timeline_bot_id = ? AND body LIKE ? ESCAPE '\\'`,
      )
      .all(timelineBotId, `%${escapeLike(term)}%`) as unknown as Array<{ id: number }>;
    return rows.map((row) => row.id);
  }

  byIds(ids: readonly number[]): SearchDocumentRecord[] {
    if (ids.length === 0) return [];
    const placeholders = ids.map(() => '?').join(', ');
    const rows = this.db
      .prepare(`SELECT * FROM search_documents WHERE id IN (${placeholders})`)
      .all(...ids) as unknown as SearchDocumentRow[];
    return rows.map(toDocument);
  }

  listByTask(taskId: string): SearchDocumentRecord[] {
    const rows = this.db
      .prepare('SELECT * FROM search_documents WHERE task_id = ? ORDER BY sort_key, id')
      .all(taskId) as unknown as SearchDocumentRow[];
    return rows.map(toDocument);
  }

  count(): number {
    const row = this.db.prepare('SELECT COUNT(*) AS count FROM search_documents').get() as {
      count: number;
    };
    return row.count;
  }
}
