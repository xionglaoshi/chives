"""SQLite storage for strategy alerts and scheduler bookkeeping.

The service keeps its own small database under ``runtime/strategy-hub``; the
rule engine's database is opened read-only and never written here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id INTEGER,
    strategy_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    round_id INTEGER,
    event TEXT NOT NULL,
    event_date TEXT NOT NULL,
    level TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(strategy_id, source_event_id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_strategy ON alerts(strategy_id, id);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


class AlertStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        with _connect(self.path) as conn:
            self._migrate(conn)
            conn.executescript(SCHEMA)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='alerts'"
        ).fetchone()
        if row is None:
            return
        sql = str(row["sql"] or "")
        columns = {str(item["name"]) for item in conn.execute("PRAGMA table_info(alerts)")}
        if "source_event_id" in columns and "UNIQUE(strategy_id, code, round_id, event_date, event)" not in sql:
            return
        conn.execute("ALTER TABLE alerts RENAME TO alerts_old")
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO alerts(strategy_id, code, name, round_id, event, event_date, level, rule_id,"
            " title, detail, created_at) SELECT strategy_id, code, name, round_id, event, event_date,"
            " level, rule_id, title, detail, created_at FROM alerts_old"
        )
        conn.execute("DROP TABLE alerts_old")
        conn.commit()

    def add(
        self,
        *,
        strategy_id: str,
        code: str,
        name: str | None,
        round_id: int | None,
        event: str,
        event_date: str,
        level: str,
        rule_id: str,
        title: str,
        detail: str,
        created_at: str,
        source_event_id: int | None = None,
    ) -> int | None:
        with _connect(self.path) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO alerts(source_event_id, strategy_id, code, name, round_id, event,"
                " event_date, level, rule_id, title, detail, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    source_event_id,
                    strategy_id,
                    code,
                    name,
                    round_id,
                    event,
                    event_date,
                    level,
                    rule_id,
                    title,
                    detail,
                    created_at,
                ),
            )
            if cursor.rowcount == 0:
                return None
            return int(cursor.lastrowid)

    def list(self, since_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with _connect(self.path) as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE id > ? ORDER BY id ASC LIMIT ?",
                (int(since_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_id(self) -> int:
        with _connect(self.path) as conn:
            row = conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM alerts").fetchone()
        return int(row["n"]) if row is not None else 0

    def get_meta(self, key: str) -> str | None:
        with _connect(self.path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
