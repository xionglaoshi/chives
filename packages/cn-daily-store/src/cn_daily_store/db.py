"""SQLite schema and connection helpers.

The database is a single file under ``runtime/marketdata/`` by default.  Readers
open it in read-only mode so several processes can query it concurrently while
the daily updater writes under WAL.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS calendar (
    date TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS securities (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    board TEXT NOT NULL,
    list_date TEXT,
    delist_date TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS names (
    code TEXT NOT NULL,
    start_date TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (code, start_date)
);
CREATE TABLE IF NOT EXISTS bars (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    amount REAL,
    adj_factor REAL NOT NULL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_date ON bars(date);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def repo_root() -> Path:
    """Best-effort repository root for the default DB path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages").is_dir() and (parent / "docs").is_dir():
            return parent
    return Path.cwd()


def default_db_path() -> Path:
    override = (os.environ.get("CN_DAILY_STORE_DB") or "").strip()
    if override:
        return Path(override).expanduser()
    return repo_root() / "runtime" / "marketdata" / "daily.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(path: Path | str, *, readonly: bool = False) -> sqlite3.Connection:
    target = Path(path).expanduser()
    if readonly:
        if not target.is_file():
            raise FileNotFoundError(f"database not found: {target}")
        uri = f"file:{target}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def init_db(path: Path | str) -> Path:
    target = Path(path).expanduser()
    conn = connect(target, readonly=False)
    try:
        init_schema(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()
    return target


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
