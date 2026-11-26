import { retiredBotIds } from '../bots/ceo-migration.js';
/** SQLite connection, pragmas, and ordered schema migrations. */

import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

import { backfillSearchIndex } from './search.js';

export const DATABASE_FILE = 'chives.sqlite';

export type Migration = (db: DatabaseSync) => void;

const INITIAL_SCHEMA = `
CREATE TABLE IF NOT EXISTS bots (
  id TEXT PRIMARY KEY,
  display_name TEXT NULL,
  avatar_emblem TEXT NULL,
  avatar_tone TEXT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  bot_id TEXT NOT NULL,
  title TEXT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'cancelled', 'interrupted')),
  harness_session_id TEXT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NULL,
  parent_task_id TEXT NULL
);
CREATE INDEX IF NOT EXISTS tasks_bot_started ON tasks (bot_id, started_at);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks (status);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  bot_id TEXT NOT NULL,
  task_id TEXT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'bot', 'system')),
  kind TEXT NOT NULL CHECK (kind IN ('text', 'proactive', 'delegation', 'approval', 'deliverable', 'notice')),
  content TEXT NOT NULL,
  meta TEXT NULL,
  created_at TEXT NOT NULL,
  seq INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS messages_bot_seq ON messages (bot_id, seq);
CREATE INDEX IF NOT EXISTS messages_task ON messages (task_id);

CREATE TABLE IF NOT EXISTS tool_events (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  message_id TEXT NULL REFERENCES messages (id) ON DELETE SET NULL,
  tool_call_id TEXT NOT NULL,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,
  raw_input TEXT NULL,
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
  output TEXT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NULL
);
CREATE INDEX IF NOT EXISTS tool_events_task ON tool_events (task_id, started_at);
CREATE INDEX IF NOT EXISTS tool_events_call ON tool_events (task_id, tool_call_id);

CREATE TABLE IF NOT EXISTS usage (
  task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  used INTEGER NOT NULL,
  size INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_task ON usage (task_id, at);

CREATE TABLE IF NOT EXISTS deliverables (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  bot_id TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS deliverables_task ON deliverables (task_id);

CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  tool_call_id TEXT NOT NULL,
  request TEXT NOT NULL,
  decision TEXT NULL,
  decided_at TEXT NULL,
  decided_by TEXT NULL
);
CREATE INDEX IF NOT EXISTS approvals_task ON approvals (task_id);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
`;

/** Append-only list: a later task can add migrations without editing earlier entries. */
export const MIGRATIONS: readonly Migration[] = [
  (db) => {
    db.exec(INITIAL_SCHEMA);
  },
  (db) => {
    // Existing M1 databases already have the `tasks` table, so the columns
    // are added here rather than in INITIAL_SCHEMA only.
    db.exec('ALTER TABLE tasks ADD COLUMN depth INTEGER NOT NULL DEFAULT 0');
    db.exec('ALTER TABLE tasks ADD COLUMN delegated INTEGER NOT NULL DEFAULT 0');
    db.exec('ALTER TABLE tasks ADD COLUMN brief TEXT NULL');
    db.exec('CREATE INDEX IF NOT EXISTS tasks_parent ON tasks (parent_task_id)');
  },
  (db) => {
    db.exec('ALTER TABLE deliverables ADD COLUMN size INTEGER NOT NULL DEFAULT 0');
    db.exec(
      `CREATE UNIQUE INDEX IF NOT EXISTS deliverables_task_bot_path
         ON deliverables (task_id, bot_id, path)`,
    );
    db.exec(
      'CREATE INDEX IF NOT EXISTS deliverables_bot_created ON deliverables (bot_id, created_at)',
    );
  },
  (db) => {
    // T132: a task is one harness session; `closed_at` marks the end of the
    // segment independently of the per-turn `status`/`ended_at`.
    db.exec('ALTER TABLE tasks ADD COLUMN closed_at TEXT NULL');
    db.exec('ALTER TABLE tasks ADD COLUMN segment_reason TEXT NULL');
    db.exec('ALTER TABLE tasks ADD COLUMN context_meta TEXT NULL');
    db.exec('ALTER TABLE tasks ADD COLUMN last_context_used INTEGER NULL');
    db.exec('ALTER TABLE tasks ADD COLUMN last_context_size INTEGER NULL');
    db.exec(`
      CREATE TABLE IF NOT EXISTS task_summaries (
        task_id TEXT PRIMARY KEY REFERENCES tasks (id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        conclusion TEXT NOT NULL,
        key_numbers TEXT NOT NULL,
        deliverables TEXT NOT NULL,
        open_questions TEXT NOT NULL,
        symbols TEXT NOT NULL,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('model', 'fallback'))
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS task_summaries_created ON task_summaries (created_at)');
    // One row per turn (its last usage sample), not one per raw usage event.
    db.exec(`
      CREATE TABLE IF NOT EXISTS context_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        at TEXT NOT NULL,
        used INTEGER NOT NULL,
        size INTEGER NOT NULL
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS context_usage_task ON context_usage (task_id, at)');
    // Name -> code accumulated from bot replies and summaries; no network lookup.
    db.exec(`
      CREATE TABLE IF NOT EXISTS symbol_names (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        updated_at TEXT NOT NULL
      )
    `);
  },
  (db) => {
    // T132-r1: symbols seen while a segment is still open. `first_seen_at` is
    // kept from the first observation; a later name fills a NULL name only.
    db.exec(`
      CREATE TABLE IF NOT EXISTS task_symbols (
        task_id TEXT NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        code TEXT NOT NULL,
        name TEXT NULL,
        first_seen_at TEXT NOT NULL,
        PRIMARY KEY (task_id, code)
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS task_symbols_task ON task_symbols (task_id, first_seen_at)');
  },
  (db) => {
    // T133: one row per searchable document. Delegated child content is stored
    // under its root task so one bot's timeline never leaks into another's.
    db.exec('ALTER TABLE tasks ADD COLUMN reopened_at TEXT NULL');
    db.exec(`
      CREATE TABLE IF NOT EXISTS search_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timeline_bot_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        doc_type TEXT NOT NULL CHECK (doc_type IN ('message', 'summary', 'deliverable')),
        ref_id TEXT NOT NULL,
        title TEXT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        sort_key TEXT NOT NULL,
        UNIQUE (doc_type, ref_id)
      )
    `);
    db.exec(
      'CREATE INDEX IF NOT EXISTS search_documents_timeline ON search_documents (timeline_bot_id, task_id)',
    );
    db.exec(
      `CREATE VIRTUAL TABLE IF NOT EXISTS search_fts
         USING fts5(body, content='search_documents', content_rowid='id', tokenize='trigram')`,
    );
    // Triggers keep the external-content FTS table in sync with search_documents;
    // the repositories write search_documents in the same transaction as the
    // message/summary/deliverable they index.
    db.exec(`
      CREATE TRIGGER IF NOT EXISTS search_documents_ai AFTER INSERT ON search_documents BEGIN
        INSERT INTO search_fts(rowid, body) VALUES (new.id, new.body);
      END
    `);
    db.exec(`
      CREATE TRIGGER IF NOT EXISTS search_documents_ad AFTER DELETE ON search_documents BEGIN
        INSERT INTO search_fts(search_fts, rowid, body) VALUES ('delete', old.id, old.body);
      END
    `);
    db.exec(`
      CREATE TRIGGER IF NOT EXISTS search_documents_au AFTER UPDATE ON search_documents BEGIN
        INSERT INTO search_fts(search_fts, rowid, body) VALUES ('delete', old.id, old.body);
        INSERT INTO search_fts(rowid, body) VALUES (new.id, new.body);
      END
    `);
    backfillSearchIndex(db);
  },
  (db) => {
    // T135: proactive tasks are marked so the daily budget counts routines and
    // alert-triggered analysis together. Existing user/delegated tasks stay NULL.
    db.exec('ALTER TABLE tasks ADD COLUMN origin TEXT NULL');
    db.exec('CREATE INDEX IF NOT EXISTS tasks_origin_started ON tasks (origin, started_at)');
    db.exec(`
      CREATE TABLE IF NOT EXISTS routines (
        id TEXT PRIMARY KEY,
        bot_id TEXT NOT NULL,
        source TEXT NOT NULL CHECK (source IN ('manifest', 'user')),
        title TEXT NOT NULL,
        schedule TEXT NOT NULL,
        prompt TEXT NOT NULL,
        trading_days_only INTEGER NOT NULL DEFAULT 0,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        last_run_at TEXT NULL,
        next_run_at TEXT NULL
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS routines_due ON routines (enabled, next_run_at)');
    db.exec(`
      CREATE TABLE IF NOT EXISTS alert_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        alert_id INTEGER NOT NULL,
        alert_ts TEXT NULL,
        code TEXT NULL,
        name TEXT NULL,
        rule_id TEXT NULL,
        status TEXT NOT NULL CHECK (status IN ('started', 'skipped')),
        reason TEXT NULL,
        task_id TEXT NULL,
        created_at TEXT NOT NULL
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS alert_events_source ON alert_events (source, alert_id)');
    db.exec('CREATE INDEX IF NOT EXISTS alert_events_key ON alert_events (source, code, rule_id, status)');
  },
  (db) => {
    // T137: a stable failure class per failed turn, so the UI and /api/status
    // can explain what happened without parsing free-form messages.
    db.exec('ALTER TABLE tasks ADD COLUMN error_code TEXT NULL');
    db.exec('CREATE INDEX IF NOT EXISTS tasks_error ON tasks (error_code, ended_at)');
  },
  (db) => {
    // T139: a watch is a bot-owned plan rule mirrored to chives-radar. Plan ids are
    // always `chives-<id>`; plans with any other prefix are never touched.
    db.exec(`
      CREATE TABLE IF NOT EXISTS watches (
        id TEXT PRIMARY KEY,
        bot_id TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        plan TEXT NOT NULL,
        repeat INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL CHECK (status IN ('active', 'triggered', 'expired', 'cancelled')),
        engine_state TEXT NULL,
        last_price REAL NULL,
        sync_error TEXT NULL,
        created_task_id TEXT NULL,
        updated_task_id TEXT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        triggered_at TEXT NULL,
        trigger_task_id TEXT NULL,
        cancelled_by TEXT NULL CHECK (cancelled_by IN ('user', 'bot', 'system'))
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS watches_bot_status ON watches (bot_id, status)');
    db.exec('CREATE INDEX IF NOT EXISTS watches_status_expires ON watches (status, expires_at)');
    db.exec(`
      CREATE TABLE IF NOT EXISTS watch_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        watch_id TEXT NOT NULL,
        bot_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('created', 'updated', 'cancelled', 'triggered', 'expired', 'sync_error')),
        actor TEXT NOT NULL CHECK (actor IN ('user', 'bot', 'system')),
        task_id TEXT NULL,
        before TEXT NULL,
        after TEXT NULL,
        detail TEXT NULL,
        created_at TEXT NOT NULL
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS watch_events_watch ON watch_events (watch_id, id)');
    db.exec('CREATE INDEX IF NOT EXISTS watch_events_bot ON watch_events (bot_id, id)');
    db.exec(`
      CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        bot_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        level TEXT NOT NULL CHECK (level IN ('info', 'important', 'urgent')),
        created_at TEXT NOT NULL,
        read_at TEXT NULL
      )
    `);
    db.exec('CREATE INDEX IF NOT EXISTS notifications_unread ON notifications (read_at, created_at)');
    db.exec('CREATE INDEX IF NOT EXISTS notifications_bot ON notifications (bot_id, created_at)');
  },
  (db) => {
    // Adds the 'trigger_queued' event kind (a trigger waiting for a busy bot); SQLite
    // cannot alter a CHECK constraint, so the table is rebuilt with its rows.
    db.exec(`
      CREATE TABLE watch_events_next (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        watch_id TEXT NOT NULL,
        bot_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('created', 'updated', 'cancelled', 'triggered', 'trigger_queued', 'expired', 'sync_error')),
        actor TEXT NOT NULL CHECK (actor IN ('user', 'bot', 'system')),
        task_id TEXT NULL,
        before TEXT NULL,
        after TEXT NULL,
        detail TEXT NULL,
        created_at TEXT NOT NULL
      )
    `);
    db.exec(`
      INSERT INTO watch_events_next (id, watch_id, bot_id, kind, actor, task_id, before, after, detail, created_at)
      SELECT id, watch_id, bot_id, kind, actor, task_id, before, after, detail, created_at FROM watch_events
    `);
    db.exec('DROP TABLE watch_events');
    db.exec('ALTER TABLE watch_events_next RENAME TO watch_events');
    db.exec('CREATE INDEX IF NOT EXISTS watch_events_watch ON watch_events (watch_id, id)');
    db.exec('CREATE INDEX IF NOT EXISTS watch_events_bot ON watch_events (bot_id, id)');
  },
  (db) => {
    const previous = 'operator';
    const current = 'ceo';
    const botColumns = [
      ['tasks', 'bot_id'], ['messages', 'bot_id'], ['deliverables', 'bot_id'],
      ['search_documents', 'timeline_bot_id'], ['routines', 'bot_id'],
      ['watches', 'bot_id'], ['notifications', 'bot_id'], ['watch_events', 'bot_id'],
    ];
    for (const [table, column] of botColumns) {
      db.prepare(`UPDATE ${table} SET ${column} = ? WHERE ${column} = ?`).run(current, previous);
    }
    db.prepare('UPDATE bots SET id = ?, display_name = ? WHERE id = ?').run(current, '总经理', previous);
    db.prepare("UPDATE routines SET id = replace(id, 'manifest:operator:', 'manifest:ceo:') WHERE id LIKE 'manifest:operator:%'").run();
    db.prepare(`UPDATE messages SET meta = replace(replace(meta, '"operator"', '"ceo"'), '"manifest:operator:', '"manifest:ceo:')
      WHERE instr(meta, '"operator"') > 0 OR instr(meta, '"manifest:operator:') > 0`).run();
    for (const {key, value} of db.prepare('SELECT key, value FROM settings').all()) {
      const next = String(key).replace(/(^|[.:/])operator(?=$|[.:/])/g, '$1ceo');
      const renameIds = next !== key || next === 'bots.hired.v1' || next === 'sidebar.botOrder';
      const updated = renameIds ? String(value).replaceAll('"operator"', '"ceo"') : value;
      if (next !== key || updated !== value) {
        db.prepare('UPDATE settings SET key = ?, value = ? WHERE key = ?').run(next, updated!, key!);
      }
    }
  },
  db => db.exec(`
    CREATE TABLE desk_handoffs (
      id TEXT PRIMARY KEY, source_task TEXT NOT NULL, source_bot TEXT NOT NULL,
      source_message TEXT NOT NULL, target TEXT NOT NULL, intent TEXT NOT NULL,
      original TEXT NOT NULL, brief TEXT NOT NULL, status TEXT NOT NULL,
      target_task TEXT NOT NULL UNIQUE, outcome TEXT, created_at TEXT NOT NULL, context TEXT NOT NULL DEFAULT '', task_link TEXT,
      UNIQUE(source_message,target,intent)
    );
    CREATE INDEX desk_handoffs_status ON desk_handoffs(status,created_at);
    CREATE TABLE desk_news (scope TEXT NOT NULL, observed_at INTEGER NOT NULL, items TEXT NOT NULL,
      PRIMARY KEY(scope,observed_at));
    CREATE TABLE desk_flow_closes (day TEXT NOT NULL,scope TEXT NOT NULL,kind TEXT NOT NULL,observed_at TEXT NOT NULL,rows TEXT NOT NULL,
      PRIMARY KEY(day,scope,kind));
    CREATE TABLE desk_position_state (code TEXT PRIMARY KEY, quantity REAL NOT NULL);
    CREATE TABLE desk_position_changes (id INTEGER PRIMARY KEY, code TEXT NOT NULL, direction TEXT NOT NULL, observed_at TEXT NOT NULL);
    CREATE TABLE technical_watches (code TEXT PRIMARY KEY, title TEXT NOT NULL, held INTEGER NOT NULL DEFAULT 0,
      manual INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, removed INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, checked_at TEXT, state TEXT NOT NULL DEFAULT '待首份行情', bar_time TEXT);
    CREATE TABLE technical_ticks(code TEXT PRIMARY KEY, stamp TEXT NOT NULL, ratio REAL, change_pct REAL);
    CREATE TABLE technical_events (code TEXT NOT NULL, bar_time TEXT NOT NULL, direction TEXT NOT NULL, task_id TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
      summary TEXT NOT NULL, created_at TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(code,bar_time,direction));
  `),
  db => {
    const owners = [
      ['bots', 'id'], ['tasks', 'bot_id'], ['messages', 'bot_id'], ['deliverables', 'bot_id'],
      ['search_documents', 'timeline_bot_id'], ['routines', 'bot_id'], ['watches', 'bot_id'],
      ['notifications', 'bot_id'], ['watch_events', 'bot_id'],
      ['desk_handoffs', 'source_bot'], ['desk_handoffs', 'target'],
    ];
    for (const [from, to] of Object.entries(retiredBotIds)) {
      for (const [table, column] of owners) {
        db.prepare(`UPDATE ${table} SET ${column}=? WHERE ${column}=?`).run(to, from);
      }
      const oldRoutine = 'manifest:' + from + ':';
      const newRoutine = 'manifest:' + to + ':';
      db.prepare('UPDATE routines SET id=replace(id,?,?) WHERE id LIKE ?').run(oldRoutine,newRoutine,oldRoutine+'%');
      const oldLink = '#/bot/' + from;
      const newLink = '#/bot/' + to;
      db.prepare(`UPDATE messages SET meta=replace(replace(replace(meta,?,?),?,?),?,?) WHERE meta IS NOT NULL`).run(JSON.stringify(from),JSON.stringify(to),oldRoutine,newRoutine,oldLink,newLink);
      const oldPath = '/bots/' + from + '/';
      const newPath = '/bots/' + to + '/';
      db.prepare('UPDATE deliverables SET path=replace(path,?,?) WHERE instr(path,?)>0').run(oldPath,newPath,oldPath);
      db.prepare('UPDATE messages SET meta=replace(meta,?,?) WHERE instr(meta,?)>0').run(oldPath,newPath,oldPath);
      for (const {key,value} of db.prepare('SELECT key,value FROM settings').all()) {
        const renamedKey = String(key).replace(new RegExp('(^|[.:/])'+from+'(?=$|[.:/])','g'),'$1'+to);
        let renamedValue = String(value).replaceAll(oldRoutine,newRoutine);
        if (renamedKey!==key || key==='bots.hired.v1' || key==='sidebar.botOrder') {
          renamedValue=renamedValue.replaceAll(JSON.stringify(from),JSON.stringify(to));
        }
        if (renamedKey!==key || renamedValue!==value) {
          db.prepare('UPDATE settings SET key=?,value=? WHERE key=?').run(renamedKey,renamedValue,String(key));
        }
      }
    }
  },
];

function ensureVersionTable(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_version (
      version INTEGER PRIMARY KEY,
      applied_at TEXT NOT NULL
    )
  `);
}

export function currentVersion(db: DatabaseSync): number {
  ensureVersionTable(db);
  const row = db.prepare('SELECT MAX(version) AS version FROM schema_version').get() as
    | { version: number | null }
    | undefined;
  return row?.version ?? 0;
}

export function migrate(db: DatabaseSync, now: () => Date = () => new Date()): number {
  const from = currentVersion(db);
  for (let index = from; index < MIGRATIONS.length; index += 1) {
    const migration = MIGRATIONS[index];
    if (migration === undefined) continue;
    db.exec('BEGIN IMMEDIATE');
    try {
      migration(db);
      db.prepare('INSERT INTO schema_version (version, applied_at) VALUES (?, ?)').run(
        index + 1,
        now().toISOString(),
      );
      db.exec('COMMIT');
    } catch (error) {
      db.exec('ROLLBACK');
      throw error;
    }
  }
  return MIGRATIONS.length;
}

export interface OpenDatabaseOptions {
  /** Enables WAL and foreign keys; both are on by default. */
  wal?: boolean;
  now?: () => Date;
}

export function openDatabase(dataDir: string, options: OpenDatabaseOptions = {}): DatabaseSync {
  mkdirSync(dataDir, { recursive: true });
  const db = new DatabaseSync(join(dataDir, DATABASE_FILE));
  db.exec('PRAGMA busy_timeout = 5000');
  if (options.wal !== false) db.exec('PRAGMA journal_mode = WAL');
  db.exec('PRAGMA foreign_keys = ON');
  migrate(db, options.now);
  return db;
}

/** Runs `fn` inside `BEGIN IMMEDIATE`; rolls back if it throws. */
export function transaction<T>(db: DatabaseSync, fn: () => T): T {
  const nested=db.isTransaction;
  db.exec(nested?'SAVEPOINT chives_nested':'BEGIN IMMEDIATE');
  try {
    const result = fn();
    db.exec(nested?'RELEASE chives_nested':'COMMIT');
    return result;
  } catch (error) {
    db.exec(nested?'ROLLBACK TO chives_nested; RELEASE chives_nested':'ROLLBACK');
    throw error;
  }
}
