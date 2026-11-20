"""SQLite persistence for alerts, daily amount baselines and Shenwan members.

Writes are small and infrequent (alerts, one baseline row per instrument per
day, one member snapshot per industry per day), so every operation opens a
short-lived connection.  WAL plus ``busy_timeout`` keeps concurrent HTTP
readers and the polling thread from blocking each other; writes retry a few
times on ``database is locked``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_code TEXT NOT NULL,
    object_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    analysis_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
CREATE INDEX IF NOT EXISTS idx_alerts_rule_object ON alerts(rule_id, object_code, ts);
CREATE TABLE IF NOT EXISTS daily_amount (
    key TEXT NOT NULL,
    day TEXT NOT NULL,
    amount REAL NOT NULL,
    PRIMARY KEY (key, day)
);
CREATE TABLE IF NOT EXISTS sw_members (
    sector TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    weight_pct REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sector, code)
);
CREATE INDEX IF NOT EXISTS idx_sw_members_code ON sw_members(code);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blocks (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    as_of TEXT,
    fetched_at TEXT,
    source TEXT NOT NULL,
    reason TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS day_stats (
    day TEXT PRIMARY KEY,
    amount_yuan REAL,
    limit_up INTEGER,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pool_day (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER,
    rows_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    available INTEGER NOT NULL DEFAULT 1,
    reason TEXT,
    PRIMARY KEY (day, kind)
);
CREATE INDEX IF NOT EXISTS idx_pool_day_day ON pool_day(day);
CREATE TABLE IF NOT EXISTS breadth_series (
    day TEXT NOT NULL,
    t TEXT NOT NULL,
    up INTEGER,
    down INTEGER,
    flat INTEGER,
    limit_up INTEGER,
    limit_down INTEGER,
    PRIMARY KEY (day, t)
);
CREATE INDEX IF NOT EXISTS idx_breadth_series_day ON breadth_series(day);
"""


@dataclass(frozen=True)
class StoredMember:
    code: str
    name: str
    weight_pct: Optional[float]


def _alert_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "ts": row["ts"],
        "rule_id": row["rule_id"],
        "object": {
            "type": row["object_type"],
            "code": row["object_code"],
            "name": row["object_name"],
        },
        "severity": row["severity"],
        "title": row["title"],
        "detail": row["detail"],
        "payload": json.loads(row["payload"]),
        "status": row["status"],
    }
    if row["analysis_id"] is not None:
        item["analysis_id"] = row["analysis_id"]
    return item


class AlertStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._closed = False
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            self._migrate_day_stats(conn)

    @staticmethod
    def _migrate_day_stats(conn: sqlite3.Connection) -> None:
        """v1.4 adds limit-down / broken / max-streak to the daily snapshot."""
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(day_stats)")}
        for column, kind in (
            ("limit_down", "INTEGER"),
            ("broken", "INTEGER"),
            ("max_streak", "INTEGER"),
        ):
            if column not in existing:
                conn.execute(f"ALTER TABLE day_stats ADD COLUMN {column} {kind}")
        conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _write(self, sql: str, params: Iterable[Any]) -> int:
        last_error: Optional[sqlite3.OperationalError] = None
        for attempt in range(4):
            try:
                with self._write_lock, closing(self._connect()) as conn:
                    cursor = conn.execute(sql, tuple(params))
                    conn.commit()
                    return int(cursor.lastrowid or 0)
            except sqlite3.OperationalError as exc:
                last_error = exc
                time.sleep(0.02 * (attempt + 1))
        raise last_error  # type: ignore[misc]

    # -- alerts ----------------------------------------------------------
    def insert_alert(
        self,
        *,
        ts: datetime,
        rule_id: str,
        object_type: str,
        object_code: str,
        object_name: str,
        severity: str,
        title: str,
        detail: str,
        payload: dict[str, Any],
    ) -> int:
        return self._write(
            "INSERT INTO alerts (ts, rule_id, object_type, object_code, object_name,"
            " severity, title, detail, payload, status) VALUES (?,?,?,?,?,?,?,?,?, 'new')",
            (
                ts.isoformat(),
                rule_id,
                object_type,
                object_code,
                object_name,
                severity,
                title,
                detail,
                json.dumps(payload, ensure_ascii=False, allow_nan=False),
            ),
        )

    def list_alerts(self, since_id: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE id > ? ORDER BY id ASC LIMIT ?",
                (int(since_id), int(limit)),
            ).fetchall()
        return [_alert_payload(row) for row in rows]

    def recent_alerts(self, since: datetime, limit: int = 20) -> list[dict[str, Any]]:
        """Newest-first alerts at or after ``since`` (used by the market summary)."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE ts >= ? ORDER BY id DESC LIMIT ?",
                (since.isoformat(), int(limit)),
            ).fetchall()
        return [_alert_payload(row) for row in rows]

    def count_alerts_since(self, ts: datetime) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM alerts WHERE ts >= ?", (ts.isoformat(),)
            ).fetchone()
        return int(row["n"]) if row else 0

    def last_alert_id(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MAX(id) AS n FROM alerts").fetchone()
        return int(row["n"]) if row and row["n"] is not None else 0

    # -- daily amount baselines -----------------------------------------
    def record_daily_amount(self, key: str, day: date, amount_yuan: float) -> None:
        if amount_yuan <= 0:
            return
        self._write(
            "INSERT INTO daily_amount (key, day, amount) VALUES (?,?,?)"
            " ON CONFLICT(key, day) DO UPDATE SET amount=excluded.amount",
            (key, day.isoformat(), float(amount_yuan)),
        )

    def mean_daily_amount(
        self, key: str, before_day: date, days: int = 5
    ) -> tuple[Optional[float], int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT amount FROM daily_amount WHERE key = ? AND day < ?"
                " ORDER BY day DESC LIMIT ?",
                (key, before_day.isoformat(), int(days)),
            ).fetchall()
        if not rows:
            return None, 0
        values = [float(row["amount"]) for row in rows]
        return sum(values) / len(values), len(values)

    # -- per-day market snapshots ---------------------------------------
    def save_day_stats(
        self,
        day: date,
        *,
        amount_yuan: Optional[float],
        limit_up: Optional[int],
        updated_at: datetime,
        limit_down: Optional[int] = None,
        broken: Optional[int] = None,
        max_streak: Optional[int] = None,
    ) -> None:
        """Upsert today's amount / pool counts, keeping older non-null parts."""
        if (
            amount_yuan is None
            and limit_up is None
            and limit_down is None
            and broken is None
            and max_streak is None
        ):
            return
        self._write(
            "INSERT INTO day_stats (day, amount_yuan, limit_up, limit_down, broken,"
            " max_streak, updated_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(day) DO UPDATE SET"
            " amount_yuan=COALESCE(excluded.amount_yuan, day_stats.amount_yuan),"
            " limit_up=COALESCE(excluded.limit_up, day_stats.limit_up),"
            " limit_down=COALESCE(excluded.limit_down, day_stats.limit_down),"
            " broken=COALESCE(excluded.broken, day_stats.broken),"
            " max_streak=COALESCE(excluded.max_streak, day_stats.max_streak),"
            " updated_at=excluded.updated_at",
            (
                day.isoformat(),
                None if amount_yuan is None else float(amount_yuan),
                None if limit_up is None else int(limit_up),
                None if limit_down is None else int(limit_down),
                None if broken is None else int(broken),
                None if max_streak is None else int(max_streak),
                updated_at.isoformat(),
            ),
        )

    _DAY_STATS_COLUMNS = (
        "day, amount_yuan, limit_up, limit_down, broken, max_streak, updated_at"
    )

    def load_day_stats(self, day: date) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {self._DAY_STATS_COLUMNS} FROM day_stats WHERE day = ?",
                (day.isoformat(),),
            ).fetchone()
        return None if row is None else dict(row)

    def previous_day_stats(self, before_day: date) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                f"SELECT {self._DAY_STATS_COLUMNS} FROM day_stats"
                " WHERE day < ? ORDER BY day DESC LIMIT 1",
                (before_day.isoformat(),),
            ).fetchone()
        return None if row is None else dict(row)

    # -- Shenwan members -------------------------------------------------
    def save_members(
        self, sector: str, members: Iterable[StoredMember], updated_at: datetime
    ) -> None:
        with self._write_lock, closing(self._connect()) as conn:
            conn.execute("DELETE FROM sw_members WHERE sector = ?", (sector,))
            conn.executemany(
                "INSERT OR REPLACE INTO sw_members (sector, code, name, weight_pct, updated_at)"
                " VALUES (?,?,?,?,?)",
                [
                    (sector, member.code, member.name, member.weight_pct, updated_at.isoformat())
                    for member in members
                ],
            )
            conn.commit()

    def load_members(
        self, sector: str, now: datetime, *, max_age_hours: float = 20.0
    ) -> Optional[list[StoredMember]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT code, name, weight_pct, updated_at FROM sw_members WHERE sector = ?"
                " ORDER BY weight_pct DESC",
                (sector,),
            ).fetchall()
        if not rows:
            return None
        try:
            updated = datetime.fromisoformat(rows[0]["updated_at"])
        except ValueError:
            return None
        if now - updated > timedelta(hours=max_age_hours):
            return None
        return [
            StoredMember(
                code=row["code"],
                name=row["name"],
                weight_pct=row["weight_pct"],
            )
            for row in rows
        ]

    def member_sector_map(self, now: datetime, *, max_age_hours: float = 20.0) -> dict[str, str]:
        cutoff = (now - timedelta(hours=max_age_hours)).isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT sector, code FROM sw_members WHERE updated_at >= ?", (cutoff,)
            ).fetchall()
        return {row["code"]: row["sector"] for row in rows}

    # -- persisted last-valid blocks -------------------------------------
    def save_block(
        self,
        name: str,
        *,
        value: Any,
        as_of: Optional[datetime],
        fetched_at: Optional[datetime],
        source: str,
        reason: Optional[str],
        updated_at: datetime,
    ) -> None:
        self._write(
            "INSERT INTO blocks (name, payload, as_of, fetched_at, source, reason, updated_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,"
            " as_of=excluded.as_of, fetched_at=excluded.fetched_at,"
            " source=excluded.source, reason=excluded.reason, updated_at=excluded.updated_at",
            (
                name,
                json.dumps(value, ensure_ascii=False, allow_nan=False),
                as_of.isoformat() if as_of else None,
                fetched_at.isoformat() if fetched_at else None,
                source,
                reason,
                updated_at.isoformat(),
            ),
        )

    def load_blocks(self) -> dict[str, dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT name, payload, as_of, fetched_at, source, reason, updated_at FROM blocks"
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                value = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            result[row["name"]] = {
                "value": value,
                "as_of": row["as_of"],
                "fetched_at": row["fetched_at"],
                "source": row["source"],
                "reason": row["reason"],
                "updated_at": row["updated_at"],
            }
        return result

    # -- v1.4 limit-pool details -----------------------------------------
    def save_pool_day(
        self,
        day: date,
        kind: str,
        *,
        count: Optional[int],
        rows: Iterable[dict[str, Any]],
        fetched_at: datetime,
        available: bool = True,
        reason: Optional[str] = None,
    ) -> None:
        """Persist one pool for one day (including an explicit "no data" record)."""
        self._write(
            "INSERT INTO pool_day (day, kind, count, rows_json, fetched_at, available, reason)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(day, kind) DO UPDATE SET count=excluded.count,"
            " rows_json=excluded.rows_json, fetched_at=excluded.fetched_at,"
            " available=excluded.available, reason=excluded.reason",
            (
                day.isoformat(),
                kind,
                None if count is None else int(count),
                json.dumps(list(rows), ensure_ascii=False, allow_nan=False),
                fetched_at.isoformat(),
                1 if available else 0,
                reason,
            ),
        )

    def load_pool_day(self, day: date, kind: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT day, kind, count, rows_json, fetched_at, available, reason"
                " FROM pool_day WHERE day = ? AND kind = ?",
                (day.isoformat(), kind),
            ).fetchone()
        if row is None:
            return None
        try:
            rows = json.loads(row["rows_json"])
        except json.JSONDecodeError:
            rows = []
        return {
            "day": row["day"],
            "kind": row["kind"],
            "count": row["count"],
            "rows": rows if isinstance(rows, list) else [],
            "fetched_at": row["fetched_at"],
            "available": bool(row["available"]),
            "reason": row["reason"],
        }

    def pool_day_kinds(self, day: date) -> set[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT kind FROM pool_day WHERE day = ?", (day.isoformat(),)
            ).fetchall()
        return {str(row["kind"]) for row in rows}

    def pool_day_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT day) AS days, MAX(day) AS last_day,"
                " MAX(fetched_at) AS last_fetched FROM pool_day"
            ).fetchone()
            available = conn.execute(
                "SELECT COUNT(*) AS n FROM pool_day WHERE available = 1"
            ).fetchone()
        return {
            "days": int(row["days"] or 0) if row else 0,
            "last_day": row["last_day"] if row else None,
            "last_fetched_at": row["last_fetched"] if row else None,
            "available_rows": int(available["n"] or 0) if available else 0,
        }

    # -- v1.4 intraday breadth series -------------------------------------
    def save_breadth_point(
        self,
        day: date,
        minute: str,
        *,
        up: Optional[int],
        down: Optional[int],
        flat: Optional[int],
        limit_up: Optional[int],
        limit_down: Optional[int],
    ) -> None:
        """Insert one minute; the first sample in a minute wins."""
        self._write(
            "INSERT INTO breadth_series"
            " (day, t, up, down, flat, limit_up, limit_down) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(day, t) DO UPDATE SET"
            " up=COALESCE(breadth_series.up, excluded.up),"
            " down=COALESCE(breadth_series.down, excluded.down),"
            " flat=COALESCE(breadth_series.flat, excluded.flat),"
            " limit_up=COALESCE(breadth_series.limit_up, excluded.limit_up),"
            " limit_down=COALESCE(breadth_series.limit_down, excluded.limit_down)",
            (day.isoformat(), minute, up, down, flat, limit_up, limit_down),
        )

    def load_breadth_series(self, day: date) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT t, up, down, flat, limit_up, limit_down FROM breadth_series"
                " WHERE day = ? ORDER BY t ASC",
                (day.isoformat(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def breadth_series_summary(self) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT day) AS days, COUNT(*) AS points,"
                " MAX(day) AS last_day FROM breadth_series"
            ).fetchone()
        return {
            "days": int(row["days"] or 0) if row else 0,
            "points": int(row["points"] or 0) if row else 0,
            "last_day": row["last_day"] if row else None,
        }

    def prune_breadth_series(self, before_day: date) -> int:
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "DELETE FROM breadth_series WHERE day < ?", (before_day.isoformat(),)
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def pool_day_before(self, day: date) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MAX(day) AS day FROM pool_day WHERE day < ? AND available = 1",
                (day.isoformat(),),
            ).fetchone()
        return None if row is None else row["day"]

    # -- kv --------------------------------------------------------------
    def set_kv(self, key: str, value: Any) -> None:
        self._write(
            "INSERT INTO kv (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    def get_kv(self, key: str) -> Any:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return None

    def close(self) -> None:
        self._closed = True
