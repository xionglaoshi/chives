"""SQLite/CSV outputs for the surge engine (spec section 6).

Three tables are written: ``events`` (one row per event), ``pool_snapshots``
(one row per pool member per day, ranked after the close) and ``rounds`` (one
row per code round, updated as it progresses).  CSV exports mirror the tables.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    event TEXT NOT NULL,
    "values" TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_code ON events(code, round_id);

CREATE TABLE IF NOT EXISTS pool_snapshots (
    date TEXT NOT NULL,
    pool TEXT NOT NULL,
    code TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    rank INTEGER,
    status TEXT,
    priority TEXT,
    priority_date TEXT,
    vr REAL,
    k INTEGER,
    score INTEGER,
    support_score INTEGER,
    ma_score INTEGER,
    time_score REAL,
    volume_score INTEGER,
    hb REAL,
    s1_status TEXT,
    s2_status TEXT,
    t_star TEXT,
    p_star REAL,
    close REAL,
    entry_date TEXT,
    basis REAL,
    hmax REAL,
    gain REAL,
    drawdown REAL,
    base_score INTEGER,
    deduction INTEGER,
    ma10_count INTEGER,
    ma10_obs_left INTEGER,
    PRIMARY KEY (date, pool, code)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_pool_date ON pool_snapshots(pool, date);

CREATE TABLE IF NOT EXISTS rounds (
    code TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    F TEXT NOT NULL,
    C_F REAL,
    L_F REAL,
    G REAL,
    window_max REAL,
    window_min REAL,
    drawdown REAL,
    branch TEXT,
    started INTEGER,
    T_star TEXT,
    P_star REAL,
    priority TEXT,
    priority_date TEXT,
    vr REAL,
    E TEXT,
    B REAL,
    first_in_date TEXT,
    first_out_date TEXT,
    first_out_reason TEXT,
    first_pool_days INTEGER,
    main_out_date TEXT,
    main_out_reason TEXT,
    main_pool_days INTEGER,
    ma10_count INTEGER,
    out INTEGER,
    PRIMARY KEY (code, round_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ROUND_COLUMNS = (
    "code",
    "round_id",
    "F",
    "C_F",
    "L_F",
    "G",
    "window_max",
    "window_min",
    "drawdown",
    "branch",
    "started",
    "T_star",
    "P_star",
    "priority",
    "priority_date",
    "vr",
    "E",
    "B",
    "first_in_date",
    "first_out_date",
    "first_out_reason",
    "first_pool_days",
    "main_out_date",
    "main_out_reason",
    "main_pool_days",
    "ma10_count",
    "out",
)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "packages").is_dir() and (parent / "docs").is_dir():
            return parent
    return Path.cwd()


def default_paths() -> tuple[Path, Path]:
    base = repo_root() / "runtime" / "surge"
    return base / "surge.sqlite", base / "state.json"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


class OutputStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_paths()[0]
        self.conn = connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "OutputStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def reset(self) -> None:
        self.conn.executescript(
            "DELETE FROM events; DELETE FROM pool_snapshots; DELETE FROM rounds; DELETE FROM meta;"
        )
        self.conn.commit()

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    # -- writes ------------------------------------------------------------
    def write_events(self, events: Iterable[Any]) -> None:
        rows = [event.as_row() for event in events]
        if rows:
            self.conn.executemany(
                "INSERT INTO events(code, round_id, date, event, \"values\") VALUES(?,?,?,?,?)", rows
            )

    def write_snapshots(self, rows: Iterable[dict]) -> None:
        payload = [
            (
                row["date"],
                row["pool"],
                row["code"],
                row["round_id"],
                row.get("rank"),
                row.get("status"),
                row.get("priority"),
                row.get("priority_date"),
                row.get("vr"),
                row.get("k"),
                row.get("score"),
                row.get("support_score"),
                row.get("ma_score"),
                row.get("time_score"),
                row.get("volume_score"),
                row.get("hb"),
                row.get("s1_status"),
                row.get("s2_status"),
                row.get("t_star"),
                row.get("p_star"),
                row.get("close"),
                row.get("entry_date"),
                row.get("basis"),
                row.get("hmax"),
                row.get("gain"),
                row.get("drawdown"),
                row.get("base_score"),
                row.get("deduction"),
                row.get("ma10_count"),
                row.get("ma10_obs_left"),
            )
            for row in rows
        ]
        if payload:
            self.conn.executemany(
                "INSERT OR REPLACE INTO pool_snapshots("
                "date,pool,code,round_id,rank,status,priority,priority_date,vr,k,score,support_score,ma_score,time_score,"
                "volume_score,hb,s1_status,s2_status,t_star,p_star,close,entry_date,basis,hmax,gain,drawdown,"
                "base_score,deduction,ma10_count,ma10_obs_left) VALUES("
                + ",".join("?" for _ in range(30))
                + ")",
                payload,
            )

    def upsert_round(self, summary: dict) -> None:
        values = tuple(summary.get(column) for column in ROUND_COLUMNS)
        updates = ", ".join(f"{column}=excluded.{column}" for column in ROUND_COLUMNS if column not in ("code", "round_id"))
        self.conn.execute(
            "INSERT INTO rounds(" + ",".join(ROUND_COLUMNS) + ") VALUES(" + ",".join("?" for _ in ROUND_COLUMNS) + ") "
            "ON CONFLICT(code, round_id) DO UPDATE SET " + updates,
            values,
        )

    def write_day(
        self,
        *,
        events: Iterable[Any],
        first_rows: list[dict],
        main_rows: list[dict],
        rounds: Iterable[dict],
    ) -> None:
        self.write_events(events)
        self.write_snapshots(first_rows)
        self.write_snapshots(main_rows)
        for summary in rounds:
            self.upsert_round(summary)
        self.conn.commit()

    # -- reads -------------------------------------------------------------
    def pool_rows(self, pool: str, day: date | str, limit: int | None = None) -> list[dict]:
        sql = "SELECT * FROM pool_snapshots WHERE pool=? AND date=? ORDER BY rank"
        rows = [dict(row) for row in self.conn.execute(sql, (pool, str(day)))]
        return rows if limit is None else rows[:limit]

    def events_for(self, code: str, round_id: int | None = None) -> list[dict]:
        if round_id is None:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE code=? ORDER BY date, id", (code,)
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE code=? AND round_id=? ORDER BY date, id", (code, round_id)
            )
        out = []
        for row in rows:
            item = dict(row)
            item["values"] = json.loads(item["values"])
            out.append(item)
        return out

    def rounds_for(self, code: str) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM rounds WHERE code=? ORDER BY round_id", (code,))]

    def round_row(self, code: str, round_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM rounds WHERE code=? AND round_id=?", (code, round_id)
        ).fetchone()
        return None if row is None else dict(row)

    def snapshots_for_round(self, code: str, round_id: int) -> list[dict]:
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT * FROM pool_snapshots WHERE code=? AND round_id=? ORDER BY date, pool", (code, round_id)
            )
        ]

    # -- export ------------------------------------------------------------
    def export_csv(self, directory: Path | None = None) -> list[Path]:
        target = Path(directory) if directory else self.path.parent
        target.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for table in ("events", "pool_snapshots", "rounds"):
            cursor = self.conn.execute(f"SELECT * FROM {table}")
            path = target / f"{table}.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor.fetchall())
            written.append(path)
        return written
