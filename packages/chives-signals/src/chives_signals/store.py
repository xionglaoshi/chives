"""SQLite persistence for signals, plans, daily snapshots and poll cursors.

Every operation uses a short-lived connection; WAL plus ``busy_timeout`` keeps
the polling thread and HTTP readers from blocking each other.  Writes retry a
few times on ``database is locked`` like the sibling market-watch store.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from .models import CN_TZ, Plan, Signal, fmt_iso, parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_code TEXT NOT NULL,
    object_name TEXT NOT NULL,
    title TEXT NOT NULL,
    direction TEXT NOT NULL,
    conclusion TEXT NOT NULL,
    brief TEXT NOT NULL,
    context TEXT,
    source TEXT NOT NULL,
    merged_count INTEGER NOT NULL DEFAULT 1,
    primary_payload TEXT NOT NULL,
    detail_available INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL,
    rule_id TEXT,
    analysis_id INTEGER,
    snooze_until TEXT,
    ignored INTEGER NOT NULL DEFAULT 0,
    folded INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_dedupe ON signals(dedupe_key, ts);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status, ts);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    condition TEXT NOT NULL,
    stop REAL,
    rationale TEXT NOT NULL,
    source TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    triggered_at TEXT,
    last_price REAL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_plans_code ON plans(code);

CREATE TABLE IF NOT EXISTS snapshots (
    day TEXT PRIMARY KEY,
    market_value_cny REAL NOT NULL,
    total_assets_cny REAL NOT NULL,
    pnl_cny REAL NOT NULL,
    day_pnl_cny REAL NOT NULL,
    quote_time TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_alerts (
    source TEXT NOT NULL,
    alert_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    signal_id INTEGER,
    ts TEXT NOT NULL,
    PRIMARY KEY (source, alert_id)
);
CREATE INDEX IF NOT EXISTS idx_processed_ts ON processed_alerts(ts);

CREATE TABLE IF NOT EXISTS merge_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    alert_id INTEGER,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_merge_events_ts ON merge_events(ts);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value REAL,
    source TEXT NOT NULL DEFAULT 'unset',
    suggestion_value REAL,
    suggestion_basis TEXT,
    suggested_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS mood (
    day TEXT NOT NULL,
    slot TEXT NOT NULL,
    level TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, slot)
);

CREATE TABLE IF NOT EXISTS discipline_marks (
    day TEXT NOT NULL,
    rule TEXT NOT NULL,
    ts TEXT NOT NULL,
    PRIMARY KEY (day, rule)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    kind TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (date, kind)
);

CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    state TEXT NOT NULL,
    review_date TEXT,
    thesis TEXT NOT NULL,
    tags TEXT NOT NULL,
    market_conditions TEXT NOT NULL,
    sector_conditions TEXT NOT NULL,
    stock_conditions TEXT NOT NULL,
    confirm_policy TEXT NOT NULL,
    giveup TEXT NOT NULL,
    risk TEXT NOT NULL,
    sizing TEXT,
    proposed_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    locked_at TEXT,
    late INTEGER NOT NULL DEFAULT 0,
    judgement TEXT,
    last_price REAL,
    outcome TEXT,
    history TEXT NOT NULL DEFAULT '[]',
    conds TEXT NOT NULL DEFAULT '{}',
    engine TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cards_status ON cards(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_cards_code ON cards(code, created_at);

CREATE TABLE IF NOT EXISTS card_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_card_history ON card_history(card_id, ts);

CREATE TABLE IF NOT EXISTS triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    card_id INTEGER,
    code TEXT,
    name TEXT,
    from_state TEXT,
    to_state TEXT,
    reason TEXT NOT NULL,
    signal_id INTEGER,
    context TEXT,
    context_ready INTEGER NOT NULL DEFAULT 0,
    judgement TEXT,
    judged_at TEXT,
    day TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_triggers_day ON triggers(day, kind);
CREATE INDEX IF NOT EXISTS idx_triggers_dedupe ON triggers(dedupe_key, ts);
CREATE INDEX IF NOT EXISTS idx_triggers_pending ON triggers(context_ready, id);

CREATE TABLE IF NOT EXISTS daily_counters (
    day TEXT NOT NULL,
    name TEXT NOT NULL,
    value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, name)
);

CREATE TABLE IF NOT EXISTS guidance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    slot TEXT NOT NULL,
    ts TEXT NOT NULL,
    signal_id INTEGER,
    context TEXT NOT NULL,
    theme TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (day, slot)
);

CREATE TABLE IF NOT EXISTS emergency_marks (
    day TEXT NOT NULL,
    reason TEXT NOT NULL,
    ts TEXT NOT NULL,
    PRIMARY KEY (day, reason)
);
"""


def _signal_row(row: sqlite3.Row) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": int(row["id"]),
        "ts": parse_iso(row["ts"]),
        "kind": row["kind"],
        "severity": row["severity"],
        "status": row["status"],
        "object_type": row["object_type"],
        "object_code": row["object_code"],
        "object_name": row["object_name"],
        "title": row["title"],
        "direction": row["direction"],
        "conclusion": row["conclusion"],
        "brief": row["brief"],
        "context": json.loads(row["context"]) if row["context"] else None,
        "source": json.loads(row["source"]),
        "merged_count": int(row["merged_count"]),
        "primary": json.loads(row["primary_payload"]),
        "detail_available": bool(row["detail_available"]),
        "rule_id": row["rule_id"],
        "analysis_id": row["analysis_id"],
        "snooze_until": parse_iso(row["snooze_until"]) if row["snooze_until"] else None,
        "ignored": bool(row["ignored"]),
        "folded": bool(row["folded"]),
        "dedupe_key": row["dedupe_key"],
        "created_at": parse_iso(row["created_at"]),
        "updated_at": parse_iso(row["updated_at"]),
    }
    item["decide"] = _is_decide(item)
    return item


def _plan_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "code": row["code"],
        "name": row["name"],
        "kind": row["kind"],
        "status": row["status"],
        "condition": json.loads(row["condition"]),
        "stop": row["stop"],
        "rationale": row["rationale"],
        "source": json.loads(row["source"]),
        "proposed_by": row["proposed_by"],
        "created_at": parse_iso(row["created_at"]),
        "expires_at": parse_iso(row["expires_at"]),
        "triggered_at": parse_iso(row["triggered_at"]) if row["triggered_at"] else None,
        "last_price": row["last_price"],
        "updated_at": parse_iso(row["updated_at"]),
    }


class HubStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
        if "folded" not in columns:
            conn.execute("ALTER TABLE signals ADD COLUMN folded INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        card_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cards)")}
        if card_columns and "history" not in card_columns:
            conn.execute("ALTER TABLE cards ADD COLUMN history TEXT NOT NULL DEFAULT '[]'")
            conn.commit()
        # T111: mirrored chives-radar condition flags and per-card engine status.
        if card_columns and "conds" not in card_columns:
            conn.execute("ALTER TABLE cards ADD COLUMN conds TEXT NOT NULL DEFAULT '{}'")
            conn.commit()
        if card_columns and "engine" not in card_columns:
            conn.execute("ALTER TABLE cards ADD COLUMN engine TEXT")
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

    def _transaction(self, action: Callable[[sqlite3.Connection], Any]) -> Any:
        last_error: Optional[sqlite3.OperationalError] = None
        for attempt in range(4):
            try:
                with self._write_lock, closing(self._connect()) as conn:
                    result = action(conn)
                    conn.commit()
                    return result
            except sqlite3.OperationalError as exc:
                last_error = exc
                time.sleep(0.02 * (attempt + 1))
        raise last_error  # type: ignore[misc]

    # -- signals ---------------------------------------------------------
    def _insert_signal_conn(
        self, conn: sqlite3.Connection, signal: Signal, now: datetime
    ) -> int:
        stamp = fmt_iso(now)
        cursor = conn.execute(
            "INSERT INTO signals (ts, kind, severity, status, object_type, object_code,"
            " object_name, title, direction, conclusion, brief, context, source,"
            " merged_count, primary_payload, detail_available, dedupe_key, rule_id, analysis_id,"
            " snooze_until, ignored, folded, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fmt_iso(signal.ts),
                signal.kind,
                signal.severity,
                signal.status,
                signal.object_type,
                signal.object_code,
                signal.object_name,
                signal.title,
                signal.direction,
                signal.conclusion,
                signal.brief,
                json.dumps(signal.context, ensure_ascii=False, allow_nan=False)
                if signal.context is not None
                else None,
                json.dumps(signal.source, ensure_ascii=False, allow_nan=False),
                int(signal.merged_count),
                json.dumps(signal.primary, ensure_ascii=False, allow_nan=False),
                int(bool(signal.detail_available)),
                signal.dedupe_key,
                signal.rule_id,
                signal.analysis_id,
                fmt_iso(signal.snooze_until),
                int(bool(signal.ignored)),
                int(bool(signal.folded)),
                stamp,
                stamp,
            ),
        )
        return int(cursor.lastrowid or 0)

    def insert_signal(self, signal: Signal, now: datetime) -> int:
        return int(
            self._transaction(lambda conn: self._insert_signal_conn(conn, signal, now))
        )

    def get_signal(self, signal_id: int) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM signals WHERE id = ?", (int(signal_id),)).fetchone()
        return None if row is None else _signal_row(row)

    def find_merge_candidate(self, dedupe_key: str, since: datetime) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM signals WHERE dedupe_key = ? AND ts >= ?"
                " AND status != 'ignored' ORDER BY id DESC LIMIT 1",
                (dedupe_key, fmt_iso(since)),
            ).fetchone()
        return None if row is None else _signal_row(row)

    def merge_signal(
        self,
        signal_id: int,
        *,
        alert_id: Optional[int],
        analysis_id: Optional[int],
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        def action(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
            row = conn.execute("SELECT * FROM signals WHERE id = ?", (int(signal_id),)).fetchone()
            if row is None:
                return None
            source = json.loads(row["source"])
            ids = list(source.get("alert_ids") or [])
            if alert_id is not None and str(alert_id) not in {str(item) for item in ids}:
                ids.append(int(alert_id))
            source["alert_ids"] = ids
            merged = int(row["merged_count"]) + 1
            if analysis_id is not None:
                source["analysis_id"] = analysis_id
            conn.execute(
                "UPDATE signals SET merged_count = ?, source = ?, updated_at = ? WHERE id = ?",
                (
                    merged,
                    json.dumps(source, ensure_ascii=False, allow_nan=False),
                    fmt_iso(now),
                    int(signal_id),
                ),
            )
            conn.execute(
                "INSERT INTO merge_events (signal_id, alert_id, ts) VALUES (?,?,?)",
                (int(signal_id), alert_id, fmt_iso(now)),
            )
            return None

        self._transaction(action)
        return self.get_signal(signal_id)

    def update_signal(
        self,
        signal_id: int,
        *,
        status: Optional[str] = None,
        snooze_until: Optional[datetime] = None,
        clear_snooze: bool = False,
        ignored: Optional[bool] = None,
        folded: Optional[bool] = None,
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        fields: list[str] = ["updated_at = ?"]
        params: list[Any] = [fmt_iso(now)]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if clear_snooze:
            fields.append("snooze_until = NULL")
        elif snooze_until is not None:
            fields.append("snooze_until = ?")
            params.append(fmt_iso(snooze_until))
        if ignored is not None:
            fields.append("ignored = ?")
            params.append(int(bool(ignored)))
        if folded is not None:
            fields.append("folded = ?")
            params.append(int(bool(folded)))
        params.append(int(signal_id))
        self._write(f"UPDATE signals SET {', '.join(fields)} WHERE id = ?", params)
        return self.get_signal(signal_id)

    def restore_snoozed(self, now: datetime) -> int:
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE signals SET status = 'new', snooze_until = NULL, updated_at = ?"
                " WHERE status = 'snoozed' AND snooze_until IS NOT NULL AND snooze_until <= ?",
                (fmt_iso(now), fmt_iso(now)),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def list_signals(
        self,
        *,
        status: str = "active",
        decide: Optional[bool] = None,
        object_type: Optional[str] = None,
        limit: int = 50,
        since_id: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["id > ?"]
        params: list[Any] = [int(since_id)]
        if status == "active":
            clauses.append("status IN ('new','seen')")
        elif status == "snoozed":
            clauses.append("status = 'snoozed'")
        elif status == "done":
            clauses.append("status IN ('done','ignored')")
        if decide is not None:
            decide_expr = (
                "(kind IN ('plan_proposal','plan_entry','plan_giveup',"
                "'card_proposal','card_state','discipline','emergency')"
                " OR (kind IN ('sector','opportunity') AND severity IN ('L2','L3')))"
            )
            clauses.append(decide_expr if decide else f"NOT {decide_expr}")
        if object_type is not None:
            if object_type == "market":
                clauses.append("object_type IN ('market','index')")
            else:
                clauses.append("object_type = ?")
                params.append(object_type)
        params.append(int(limit))
        sql = (
            "SELECT * FROM signals WHERE "
            + " AND ".join(clauses)
            + " ORDER BY id DESC LIMIT ?"
        )
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_signal_row(row) for row in rows]

    def all_active_signals(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM signals WHERE status IN ('new','seen','snoozed') ORDER BY id DESC"
            ).fetchall()
        return [_signal_row(row) for row in rows]

    def signal_counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT status, kind, COUNT(*) AS n FROM signals GROUP BY status, kind"
            ).fetchall()
        counts = {
            "signals": 0,
            "active": 0,
            "snoozed": 0,
            "done": 0,
            "decide": 0,
        }
        for row in rows:
            count = int(row["n"])
            counts["signals"] += count
            status = row["status"]
            if status in {"new", "seen"}:
                counts["active"] += count
            elif status == "snoozed":
                counts["snoozed"] += count
            elif status in {"done", "ignored"}:
                counts["done"] += count
        for item in self.all_active_signals():
            if _is_decide(item):
                counts["decide"] += 1
        return counts

    def merged_today(self, day_start: datetime) -> int:
        """Alerts merged into an existing card since ``day_start`` (merge events)."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM merge_events WHERE ts >= ?",
                (fmt_iso(day_start),),
            ).fetchone()
        return int(row["n"]) if row else 0

    def close_plan_proposals(self, plan_id: int, now: datetime) -> int:
        """Mark pending plan_proposal cards for a plan as done (confirm/cancel)."""

        def action(conn: sqlite3.Connection) -> int:
            rows = conn.execute(
                "SELECT id, source FROM signals WHERE kind = 'plan_proposal'"
                " AND status IN ('new','seen')"
            ).fetchall()
            closed = 0
            for row in rows:
                try:
                    source = json.loads(row["source"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if source.get("plan_id") == plan_id:
                    conn.execute(
                        "UPDATE signals SET status = 'done', updated_at = ? WHERE id = ?",
                        (fmt_iso(now), int(row["id"])),
                    )
                    closed += 1
            return closed

        return int(self._transaction(action))

    def max_signal_id(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT MAX(id) AS n FROM signals").fetchone()
        return int(row["n"]) if row and row["n"] is not None else 0

    # -- plans -----------------------------------------------------------
    def insert_plan(self, plan: Plan, now: datetime) -> int:
        return self._write(
            "INSERT INTO plans (code, name, kind, status, condition, stop, rationale, source,"
            " proposed_by, created_at, expires_at, triggered_at, last_price, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                plan.code,
                plan.name,
                plan.kind,
                plan.status,
                json.dumps(plan.condition, ensure_ascii=False, allow_nan=False),
                plan.stop,
                plan.rationale,
                json.dumps(plan.source, ensure_ascii=False, allow_nan=False),
                plan.proposed_by,
                fmt_iso(plan.created_at),
                fmt_iso(plan.expires_at),
                fmt_iso(plan.triggered_at),
                plan.last_price,
                fmt_iso(now),
            ),
        )

    def get_plan(self, plan_id: int) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM plans WHERE id = ?", (int(plan_id),)).fetchone()
        return None if row is None else _plan_row(row)

    def list_plans(self, status: str = "all") -> list[dict[str, Any]]:
        if status == "all":
            sql = "SELECT * FROM plans ORDER BY id DESC"
            params: tuple[Any, ...] = ()
        else:
            sql = "SELECT * FROM plans WHERE status = ? ORDER BY id DESC"
            params = (status,)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_plan_row(row) for row in rows]

    def count_active_plans(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM plans WHERE status = 'active'").fetchone()
        return int(row["n"]) if row else 0

    def update_plan(
        self,
        plan_id: int,
        *,
        status: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        triggered_at: Optional[datetime] = None,
        clear_triggered: bool = False,
        last_price: Optional[float] = None,
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        fields: list[str] = ["updated_at = ?"]
        params: list[Any] = [fmt_iso(now)]
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if expires_at is not None:
            fields.append("expires_at = ?")
            params.append(fmt_iso(expires_at))
        if clear_triggered:
            fields.append("triggered_at = NULL")
        elif triggered_at is not None:
            fields.append("triggered_at = ?")
            params.append(fmt_iso(triggered_at))
        if last_price is not None:
            fields.append("last_price = ?")
            params.append(float(last_price))
        params.append(int(plan_id))
        self._write(f"UPDATE plans SET {', '.join(fields)} WHERE id = ?", params)
        return self.get_plan(plan_id)

    # -- processed alert cursors ----------------------------------------
    def is_processed(self, source: str, alert_id: int) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_alerts WHERE source = ? AND alert_id = ?",
                (source, int(alert_id)),
            ).fetchone()
        return row is not None

    def mark_processed(
        self,
        source: str,
        alert_id: int,
        *,
        status: str,
        reason: Optional[str],
        signal_id: Optional[int],
        ts: datetime,
    ) -> None:
        self._write(
            "INSERT OR IGNORE INTO processed_alerts (source, alert_id, status, reason, signal_id, ts)"
            " VALUES (?,?,?,?,?,?)",
            (source, int(alert_id), status, reason, signal_id, fmt_iso(ts)),
        )

    def processed_signal_id(self, source: str, alert_id: int) -> Optional[int]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT signal_id FROM processed_alerts WHERE source = ? AND alert_id = ?",
                (source, int(alert_id)),
            ).fetchone()
        return None if row is None or row["signal_id"] is None else int(row["signal_id"])

    def update_signal_content(
        self,
        signal_id: int,
        *,
        kind: Optional[str] = None,
        status: Optional[str] = None,
        conclusion: Optional[str] = None,
        direction: Optional[str] = None,
        brief: Optional[str] = None,
        analysis_id: Optional[int] = None,
        detail_available: Optional[bool] = None,
        folded: Optional[bool] = None,
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        fields: list[str] = ["updated_at = ?"]
        params: list[Any] = [fmt_iso(now)]
        for name, value in (
            ("kind", kind),
            ("status", status),
            ("conclusion", conclusion),
            ("direction", direction),
            ("brief", brief),
            ("analysis_id", analysis_id),
        ):
            if value is not None:
                fields.append(f"{name} = ?")
                params.append(value)
        if detail_available is not None:
            fields.append("detail_available = ?")
            params.append(int(bool(detail_available)))
        if folded is not None:
            fields.append("folded = ?")
            params.append(int(bool(folded)))
        params.append(int(signal_id))
        self._write(f"UPDATE signals SET {', '.join(fields)} WHERE id = ?", params)
        return self.get_signal(signal_id)

    def processed_count_today(self, day_start: datetime) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM processed_alerts WHERE ts >= ?",
                (fmt_iso(day_start),),
            ).fetchone()
        return int(row["n"]) if row else 0

    def max_alert_id(self, source: str) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MAX(alert_id) AS n FROM processed_alerts WHERE source = ?", (source,)
            ).fetchone()
        return int(row["n"]) if row and row["n"] is not None else 0

    # -- snapshots ------------------------------------------------------
    def insert_snapshot(
        self,
        *,
        day: date,
        market_value_cny: float,
        total_assets_cny: float,
        pnl_cny: float,
        day_pnl_cny: float,
        quote_time: Optional[str],
        now: datetime,
    ) -> bool:
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO snapshots"
                " (day, market_value_cny, total_assets_cny, pnl_cny, day_pnl_cny, quote_time, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    day.isoformat(),
                    float(market_value_cny),
                    float(total_assets_cny),
                    float(pnl_cny),
                    float(day_pnl_cny),
                    quote_time,
                    fmt_iso(now),
                ),
            )
            conn.commit()
            return bool(cursor.rowcount)

    def get_snapshot(self, day: date) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE day = ?", (day.isoformat(),)).fetchone()
        return None if row is None else dict(row)

    def list_snapshots(self, limit: int = 90) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY day DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def count_snapshots(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()
        return int(row["n"]) if row else 0

    # -- kv --------------------------------------------------------------
    def set_kv(self, key: str, value: Any) -> None:
        self._write(
            "INSERT INTO kv (key, value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
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

    # -- settings -------------------------------------------------------
    @staticmethod
    def _setting_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "value": row["value"],
            "source": row["source"],
            "suggestion_value": row["suggestion_value"],
            "suggestion_basis": row["suggestion_basis"],
            "suggested_at": parse_iso(row["suggested_at"]) if row["suggested_at"] else None,
            "updated_at": parse_iso(row["updated_at"]) if row["updated_at"] else None,
        }

    def get_setting(self, key: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else self._setting_row(row)

    def list_settings(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM settings ORDER BY key").fetchall()
        return [self._setting_row(row) for row in rows]

    def save_setting(
        self,
        key: str,
        *,
        value: Optional[float] = None,
        source: str = "unset",
        now: datetime,
        clear_suggestion: bool = False,
        keep_value: bool = False,
    ) -> None:
        current = self.get_setting(key) or {}
        if keep_value:
            value = current.get("value")
            source = current.get("source") or "unset"
        suggested_value = None if clear_suggestion else current.get("suggestion_value")
        suggested_basis = None if clear_suggestion else current.get("suggestion_basis")
        suggested_at = None if clear_suggestion else current.get("suggested_at")
        self._write(
            "INSERT INTO settings (key, value, source, suggestion_value, suggestion_basis,"
            " suggested_at, updated_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
            " source = excluded.source, suggestion_value = excluded.suggestion_value,"
            " suggestion_basis = excluded.suggestion_basis, suggested_at = excluded.suggested_at,"
            " updated_at = excluded.updated_at",
            (
                key,
                value,
                source,
                suggested_value,
                suggested_basis,
                fmt_iso(suggested_at) if suggested_at else None,
                fmt_iso(now),
            ),
        )

    def save_suggestion(
        self, key: str, *, value: float, basis: str, now: datetime
    ) -> None:
        current = self.get_setting(key)
        source = (current or {}).get("source") or "unset"
        current_value = (current or {}).get("value")
        self._write(
            "INSERT INTO settings (key, value, source, suggestion_value, suggestion_basis,"
            " suggested_at, updated_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(key) DO UPDATE SET suggestion_value = excluded.suggestion_value,"
            " suggestion_basis = excluded.suggestion_basis, suggested_at = excluded.suggested_at,"
            " updated_at = excluded.updated_at",
            (key, current_value, source, float(value), basis, fmt_iso(now), fmt_iso(now)),
        )

    # -- discipline ------------------------------------------------------
    def save_mood(
        self, day: str, slot: str, level: str, note: Optional[str], now: datetime
    ) -> None:
        self._write(
            "INSERT INTO mood (day, slot, level, note, updated_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(day, slot) DO UPDATE SET level = excluded.level,"
            " note = excluded.note, updated_at = excluded.updated_at",
            (day, slot, level, note, fmt_iso(now)),
        )

    def get_mood(self, day: str) -> dict[str, Any]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM mood WHERE day = ?", (day,)).fetchall()
        return {
            row["slot"]: {
                "level": row["level"],
                "note": row["note"],
                "updated_at": parse_iso(row["updated_at"]),
            }
            for row in rows
        }

    def mark_discipline(self, day: str, rule: str, now: datetime) -> bool:
        """Return True only for the first pause signal of ``(day, rule)``."""
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO discipline_marks (day, rule, ts) VALUES (?,?,?)",
                (day, rule, fmt_iso(now)),
            )
            conn.commit()
            return bool(cursor.rowcount)

    # -- reviews ---------------------------------------------------------
    @staticmethod
    def _review_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload"])
        item = {
            "id": int(row["id"]),
            "date": row["date"],
            "kind": row["kind"],
            "revision": int(row["revision"]),
            "payload": payload,
            "created_at": parse_iso(row["created_at"]),
            "updated_at": parse_iso(row["updated_at"]),
        }
        return item

    def save_review(
        self, day: str, kind: str, payload: dict[str, Any], now: datetime
    ) -> dict[str, Any]:
        with self._write_lock, closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, revision, created_at FROM reviews WHERE date = ? AND kind = ?",
                (day, kind),
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO reviews (date, kind, revision, payload, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        day,
                        kind,
                        1,
                        json.dumps(payload, ensure_ascii=False, allow_nan=False),
                        fmt_iso(now),
                        fmt_iso(now),
                    ),
                )
                review_id = int(cursor.lastrowid or 0)
            else:
                review_id = int(row["id"])
                conn.execute(
                    "UPDATE reviews SET revision = revision + 1, payload = ?, updated_at = ?"
                    " WHERE id = ?",
                    (
                        json.dumps(payload, ensure_ascii=False, allow_nan=False),
                        fmt_iso(now),
                        review_id,
                    ),
                )
            conn.commit()
        stored = self.get_review(day, kind)
        assert stored is not None
        return stored

    def get_review(self, day: str, kind: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM reviews WHERE date = ? AND kind = ?", (day, kind)
            ).fetchone()
        return None if row is None else self._review_row(row)

    def list_reviews(self, *, limit: int = 20, kind: Optional[str] = None) -> list[dict[str, Any]]:
        if kind:
            sql = "SELECT * FROM reviews WHERE kind = ? ORDER BY date DESC, id DESC LIMIT ?"
            params: tuple[Any, ...] = (kind, int(limit))
        else:
            sql = "SELECT * FROM reviews ORDER BY date DESC, id DESC LIMIT ?"
            params = (int(limit),)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._review_row(row) for row in rows]

    def latest_review(self) -> Optional[dict[str, Any]]:
        rows = self.list_reviews(limit=1)
        return rows[0] if rows else None

    # -- cards -----------------------------------------------------------
    @staticmethod
    def _card_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "code": row["code"],
            "name": row["name"],
            "status": row["status"],
            "state": row["state"],
            "review_date": row["review_date"],
            "thesis": row["thesis"],
            "tags": json.loads(row["tags"]),
            "market_conditions": json.loads(row["market_conditions"]),
            "sector_conditions": json.loads(row["sector_conditions"]),
            "stock_conditions": json.loads(row["stock_conditions"]),
            "confirm_policy": row["confirm_policy"],
            "giveup": json.loads(row["giveup"]),
            "risk": json.loads(row["risk"]),
            "sizing": json.loads(row["sizing"]) if row["sizing"] else None,
            "proposed_by": row["proposed_by"],
            "created_at": parse_iso(row["created_at"]),
            "expires_at": parse_iso(row["expires_at"]),
            "locked_at": parse_iso(row["locked_at"]) if row["locked_at"] else None,
            "late": bool(row["late"]),
            "judgement": json.loads(row["judgement"]) if row["judgement"] else None,
            "last_price": row["last_price"],
            "outcome": json.loads(row["outcome"]) if row["outcome"] else None,
            "conds": json.loads(row["conds"]) if row["conds"] else {},
            "engine": json.loads(row["engine"]) if row["engine"] else None,
            "updated_at": parse_iso(row["updated_at"]),
        }

    def close_card_signals(self, card_id: int, now: datetime) -> int:
        """Mark pending card_proposal cards for ``card_id`` as done."""

        def action(conn: sqlite3.Connection) -> int:
            rows = conn.execute(
                "SELECT id, source FROM signals WHERE kind = 'card_proposal'"
                " AND status IN ('new','seen')"
            ).fetchall()
            closed = 0
            for row in rows:
                try:
                    source = json.loads(row["source"])
                except (TypeError, json.JSONDecodeError):
                    continue
                if source.get("card_id") == int(card_id):
                    conn.execute(
                        "UPDATE signals SET status = 'done', updated_at = ? WHERE id = ?",
                        (fmt_iso(now), int(row["id"])),
                    )
                    closed += 1
            return closed

        return int(self._transaction(action))

    def insert_card(self, card: dict[str, Any], now: datetime) -> int:
        return self._write(
            "INSERT INTO cards (code, name, status, state, review_date, thesis, tags,"
            " market_conditions, sector_conditions, stock_conditions, confirm_policy, giveup,"
            " risk, sizing, proposed_by, created_at, expires_at, locked_at, late, judgement,"
            " last_price, outcome, history, conds, engine, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                card["code"],
                card["name"],
                card["status"],
                card["state"],
                card.get("review_date"),
                card["thesis"],
                json.dumps(card["tags"], ensure_ascii=False, allow_nan=False),
                json.dumps(card["market_conditions"], ensure_ascii=False, allow_nan=False),
                json.dumps(card["sector_conditions"], ensure_ascii=False, allow_nan=False),
                json.dumps(card["stock_conditions"], ensure_ascii=False, allow_nan=False),
                card["confirm_policy"],
                json.dumps(card["giveup"], ensure_ascii=False, allow_nan=False),
                json.dumps(card["risk"], ensure_ascii=False, allow_nan=False),
                json.dumps(card["sizing"], ensure_ascii=False, allow_nan=False)
                if card.get("sizing") is not None
                else None,
                card["proposed_by"],
                fmt_iso(card["created_at"]),
                fmt_iso(card["expires_at"]),
                fmt_iso(card.get("locked_at")) if card.get("locked_at") else None,
                int(bool(card.get("late"))),
                json.dumps(card["judgement"], ensure_ascii=False, allow_nan=False)
                if card.get("judgement") is not None
                else None,
                card.get("last_price"),
                json.dumps(card["outcome"], ensure_ascii=False, allow_nan=False)
                if card.get("outcome") is not None
                else None,
                json.dumps(card.get("history") or [], ensure_ascii=False, allow_nan=False),
                json.dumps(card.get("conds") or {}, ensure_ascii=False, allow_nan=False),
                json.dumps(card["engine"], ensure_ascii=False, allow_nan=False)
                if card.get("engine") is not None
                else None,
                fmt_iso(now),
            ),
        )

    def get_card(self, card_id: int) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (int(card_id),)).fetchone()
        return None if row is None else self._card_row(row)

    def list_cards(
        self, *, status: Optional[str] = None, date: Optional[str] = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)
        if date:
            clauses.append("review_date = ?")
            params.append(date)
        sql = "SELECT * FROM cards"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._card_row(row) for row in rows]

    def count_live_cards(self) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM cards WHERE status IN ('proposed','active')"
            ).fetchone()
        return int(row["n"]) if row else 0

    def count_cards_for_code_day(self, code: str, day_start: datetime, day_end: datetime) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM cards WHERE code = ? AND created_at >= ?"
                " AND created_at < ?"
                " AND NOT (status = 'active' AND state IN ('abandon','exit'))",
                (code, fmt_iso(day_start), fmt_iso(day_end)),
            ).fetchone()
        return int(row["n"]) if row else 0

    def update_card(self, card_id: int, *, now: datetime, **fields: Any) -> Optional[dict[str, Any]]:
        if not fields:
            return self.get_card(card_id)
        columns: list[str] = []
        params: list[Any] = []
        for name in (
            "status",
            "state",
            "sizing",
            "risk",
            "locked_at",
            "late",
            "judgement",
            "last_price",
            "outcome",
            "expires_at",
            "conds",
            "engine",
        ):
            if name not in fields:
                continue
            value = fields[name]
            columns.append(f"{name} = ?")
            if name in {"locked_at", "expires_at"}:
                params.append(fmt_iso(value) if value is not None else None)
            elif name in {"late"}:
                params.append(int(bool(value)))
            elif name in {"sizing", "judgement", "outcome", "risk", "conds", "engine"}:
                params.append(
                    json.dumps(value, ensure_ascii=False, allow_nan=False)
                    if value is not None
                    else None
                )
            else:
                params.append(value)
        if not columns:
            return self.get_card(card_id)
        columns.append("updated_at = ?")
        params.append(fmt_iso(now))
        params.append(int(card_id))
        self._write(f"UPDATE cards SET {', '.join(columns)} WHERE id = ?", params)
        return self.get_card(card_id)

    def append_card_history(
        self,
        card_id: int,
        *,
        from_state: Optional[str],
        to_state: str,
        reason: str,
        now: datetime,
    ) -> None:
        stamp = fmt_iso(now)
        entry = {"ts": stamp, "from": from_state, "to": to_state, "reason": reason}

        def action(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO card_history (card_id, ts, from_state, to_state, reason)"
                " VALUES (?,?,?,?,?)",
                (int(card_id), stamp, from_state, to_state, reason),
            )
            row = conn.execute(
                "SELECT history FROM cards WHERE id = ?", (int(card_id),)
            ).fetchone()
            rows: list[Any] = []
            if row is not None and row["history"]:
                try:
                    parsed = json.loads(row["history"])
                    rows = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    rows = []
            rows.append(entry)
            conn.execute(
                "UPDATE cards SET history = ?, updated_at = ? WHERE id = ?",
                (json.dumps(rows, ensure_ascii=False, allow_nan=False), stamp, int(card_id)),
            )

        self._transaction(action)

    def list_card_history(self, card_id: int) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM card_history WHERE card_id = ? ORDER BY id",
                (int(card_id),),
            ).fetchall()
        return [
            {
                "ts": parse_iso(row["ts"]),
                "from": row["from_state"],
                "to": row["to_state"],
                "reason": row["reason"],
            }
            for row in rows
        ]

    def saw_card_state_since(
        self, card_id: int, to_state: str, since: datetime
    ) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM card_history WHERE card_id = ? AND to_state = ? AND ts >= ?"
                " LIMIT 1",
                (int(card_id), to_state, fmt_iso(since)),
            ).fetchone()
        return row is not None

    # -- triggers --------------------------------------------------------
    @staticmethod
    def _trigger_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "ts": parse_iso(row["ts"]),
            "kind": row["kind"],
            "card_id": None if row["card_id"] is None else int(row["card_id"]),
            "code": row["code"],
            "name": row["name"],
            "from_state": row["from_state"],
            "to_state": row["to_state"],
            "reason": row["reason"],
            "signal_id": None if row["signal_id"] is None else int(row["signal_id"]),
            "context": json.loads(row["context"]) if row["context"] else None,
            "context_ready": bool(row["context_ready"]),
            "judgement": json.loads(row["judgement"]) if row["judgement"] else None,
            "judged_at": parse_iso(row["judged_at"]) if row["judged_at"] else None,
            "day": row["day"],
            "dedupe_key": row["dedupe_key"],
        }

    def _insert_trigger_conn(
        self, conn: sqlite3.Connection, trigger: Mapping[str, Any], now: datetime
    ) -> int:
        moment = trigger.get("ts") or now
        moment = moment if isinstance(moment, datetime) else now
        stamp = fmt_iso(now)
        cursor = conn.execute(
            "INSERT INTO triggers (ts, kind, card_id, code, name, from_state, to_state, reason,"
            " signal_id, context, context_ready, judgement, judged_at, day, dedupe_key, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                fmt_iso(moment),
                trigger["kind"],
                trigger.get("card_id"),
                trigger.get("code"),
                trigger.get("name"),
                trigger.get("from_state"),
                trigger.get("to_state"),
                str(trigger.get("reason") or ""),
                trigger.get("signal_id"),
                None,
                0,
                None,
                None,
                moment.astimezone(CN_TZ).date().isoformat(),
                str(trigger.get("dedupe_key") or trigger["kind"]),
                stamp,
            ),
        )
        return int(cursor.lastrowid or 0)

    def record_card_transition(
        self,
        card_id: int,
        *,
        from_state: Optional[str],
        to_state: str,
        reason: str,
        now: datetime,
        signal: Optional[Signal] = None,
        trigger: Optional[Mapping[str, Any]] = None,
        last_price: Optional[float] = None,
    ) -> dict[str, Any]:
        """Card state, history, signal and trigger land in one transaction (all or none)."""

        def action(conn: sqlite3.Connection) -> dict[str, Any]:
            stamp = fmt_iso(now)
            conn.execute(
                "UPDATE cards SET state = ?, last_price = COALESCE(?, last_price),"
                " updated_at = ? WHERE id = ?",
                (
                    to_state,
                    None if last_price is None else float(last_price),
                    stamp,
                    int(card_id),
                ),
            )
            entry = {"ts": stamp, "from": from_state, "to": to_state, "reason": reason}
            conn.execute(
                "INSERT INTO card_history (card_id, ts, from_state, to_state, reason)"
                " VALUES (?,?,?,?,?)",
                (int(card_id), stamp, from_state, to_state, reason),
            )
            row = conn.execute(
                "SELECT history FROM cards WHERE id = ?", (int(card_id),)
            ).fetchone()
            rows: list[Any] = []
            if row is not None and row["history"]:
                try:
                    parsed = json.loads(row["history"])
                    rows = parsed if isinstance(parsed, list) else []
                except json.JSONDecodeError:
                    rows = []
            rows.append(entry)
            conn.execute(
                "UPDATE cards SET history = ?, updated_at = ? WHERE id = ?",
                (json.dumps(rows, ensure_ascii=False, allow_nan=False), stamp, int(card_id)),
            )
            signal_id = (
                self._insert_signal_conn(conn, signal, now) if signal is not None else None
            )
            trigger_id = None
            if trigger is not None:
                payload = dict(trigger)
                payload.setdefault("signal_id", signal_id)
                payload.setdefault("ts", now)
                trigger_id = self._insert_trigger_conn(conn, payload, now)
            return {"signal_id": signal_id, "trigger_id": trigger_id}

        return dict(self._transaction(action))

    def insert_trigger(self, trigger: Mapping[str, Any], now: datetime) -> int:
        return int(
            self._transaction(lambda conn: self._insert_trigger_conn(conn, trigger, now))
        )

    def insert_emergency_once(
        self,
        *,
        day: str,
        reason: str,
        signal: Signal,
        trigger: Mapping[str, Any],
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        """Insert the first emergency of ``(day, reason)``; later ones are no-ops."""

        def action(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO emergency_marks (day, reason, ts) VALUES (?,?,?)",
                (day, reason, fmt_iso(now)),
            )
            if not cursor.rowcount:
                return None
            signal_id = self._insert_signal_conn(conn, signal, now)
            payload = dict(trigger)
            payload["signal_id"] = signal_id
            payload.setdefault("ts", now)
            trigger_id = self._insert_trigger_conn(conn, payload, now)
            return {"signal_id": signal_id, "trigger_id": trigger_id}

        return self._transaction(action)

    def get_trigger(self, trigger_id: int) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM triggers WHERE id = ?", (int(trigger_id),)
            ).fetchone()
        return None if row is None else self._trigger_row(row)

    def list_triggers(self, *, since_id: int = 0, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM triggers WHERE id > ? ORDER BY id LIMIT ?",
                (int(since_id), int(limit)),
            ).fetchall()
        return [self._trigger_row(row) for row in rows]

    def set_trigger_context(
        self, trigger_id: int, context: Mapping[str, Any]
    ) -> bool:
        """Freeze the context pack; never overwrite one already stored."""
        with self._write_lock, closing(self._connect()) as conn:
            cursor = conn.execute(
                "UPDATE triggers SET context = ?, context_ready = 1"
                " WHERE id = ? AND context IS NULL",
                (
                    json.dumps(context, ensure_ascii=False, allow_nan=False),
                    int(trigger_id),
                ),
            )
            conn.commit()
            return bool(cursor.rowcount)

    def pending_trigger_ids(self, limit: int = 5) -> list[int]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id FROM triggers WHERE context_ready = 0 ORDER BY id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [int(row["id"]) for row in rows]

    def saw_trigger_since(self, card_id: int, to_state: str, since: datetime) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM triggers WHERE card_id = ? AND to_state = ? AND ts >= ?"
                " LIMIT 1",
                (int(card_id), to_state, fmt_iso(since)),
            ).fetchone()
        return row is not None

    def saw_regime_trigger_since(self, to_state: str, since: datetime) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM triggers WHERE kind = 'regime' AND card_id IS NULL"
                " AND to_state = ? AND ts >= ? LIMIT 1",
                (to_state, fmt_iso(since)),
            ).fetchone()
        return row is not None

    def count_triggers_today(
        self, day: str, *, card_id: Optional[int] = None
    ) -> int:
        sql = "SELECT COUNT(*) AS n FROM triggers WHERE day = ?"
        params: list[Any] = [day]
        if card_id is not None:
            sql += " AND card_id = ?"
            params.append(int(card_id))
        with closing(self._connect()) as conn:
            row = conn.execute(sql, tuple(params)).fetchone()
        return int(row["n"]) if row else 0

    def fast_judgements_used(self, day: str) -> int:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT value FROM daily_counters WHERE day = ? AND name = 'fast_judgements'",
                (day,),
            ).fetchone()
        return int(row["value"]) if row else 0

    def record_judgement(
        self,
        trigger_id: int,
        judgement: Mapping[str, Any],
        *,
        now: datetime,
        day: str,
    ) -> tuple[str, Optional[dict[str, Any]]]:
        """Write once.  Returns (status, trigger row) with status ok/not_found/already_judged."""

        def action(conn: sqlite3.Connection) -> tuple[str, Optional[dict[str, Any]]]:
            row = conn.execute(
                "SELECT * FROM triggers WHERE id = ?", (int(trigger_id),)
            ).fetchone()
            if row is None:
                return "not_found", None
            if row["judgement"] is not None:
                return "already_judged", self._trigger_row(row)
            stamp = fmt_iso(now)
            payload = json.dumps(dict(judgement), ensure_ascii=False, allow_nan=False)
            cursor = conn.execute(
                "UPDATE triggers SET judgement = ?, judged_at = ?"
                " WHERE id = ? AND judgement IS NULL",
                (payload, stamp, int(trigger_id)),
            )
            if not cursor.rowcount:
                return "already_judged", self._trigger_row(row)
            conn.execute(
                "INSERT INTO daily_counters (day, name, value) VALUES (?, 'fast_judgements', 1)"
                " ON CONFLICT(day, name) DO UPDATE SET value = value + 1",
                (day,),
            )
            if row["card_id"] is not None:
                conn.execute(
                    "UPDATE cards SET judgement = ?, updated_at = ? WHERE id = ?",
                    (payload, stamp, int(row["card_id"])),
                )
            updated = conn.execute(
                "SELECT * FROM triggers WHERE id = ?", (int(trigger_id),)
            ).fetchone()
            return "ok", None if updated is None else self._trigger_row(updated)

        return self._transaction(action)

    # -- guidance --------------------------------------------------------
    def save_guidance(
        self,
        *,
        day: str,
        slot: str,
        signal: Signal,
        context: Mapping[str, Any],
        theme: Optional[Mapping[str, Any]],
        now: datetime,
    ) -> Optional[dict[str, Any]]:
        """One guidance card per (day, slot); a restart cannot duplicate it."""

        def action(conn: sqlite3.Connection) -> Optional[dict[str, Any]]:
            stamp = fmt_iso(now)
            cursor = conn.execute(
                "INSERT OR IGNORE INTO guidance (day, slot, ts, signal_id, context, theme,"
                " created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    day,
                    slot,
                    stamp,
                    None,
                    json.dumps(context, ensure_ascii=False, allow_nan=False),
                    json.dumps(theme, ensure_ascii=False, allow_nan=False)
                    if theme is not None
                    else None,
                    stamp,
                ),
            )
            if not cursor.rowcount:
                return None
            guidance_id = int(cursor.lastrowid or 0)
            signal_id = self._insert_signal_conn(conn, signal, now)
            conn.execute(
                "UPDATE guidance SET signal_id = ? WHERE id = ?",
                (signal_id, guidance_id),
            )
            return {"id": guidance_id, "signal_id": signal_id}

        return self._transaction(action)

    @staticmethod
    def _guidance_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "day": row["day"],
            "slot": row["slot"],
            "ts": parse_iso(row["ts"]),
            "signal_id": None if row["signal_id"] is None else int(row["signal_id"]),
            "context": json.loads(row["context"]),
            "theme": json.loads(row["theme"]) if row["theme"] else None,
        }

    def get_guidance(self, day: str, slot: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM guidance WHERE day = ? AND slot = ?", (day, slot)
            ).fetchone()
        return None if row is None else self._guidance_row(row)

    def list_guidance(self, day: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM guidance WHERE day = ? ORDER BY slot, id", (day,)
            ).fetchall()
        return [self._guidance_row(row) for row in rows]

    def previous_guidance_theme(self, day: str, slot: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT theme FROM guidance WHERE day = ? AND slot < ?"
                " ORDER BY slot DESC, id DESC LIMIT 1",
                (day, slot),
            ).fetchone()
        if row is None or not row["theme"]:
            return None
        try:
            value = json.loads(row["theme"])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def close(self) -> None:
        return


def _is_decide(item: dict[str, Any]) -> bool:
    kind = item["kind"]
    if kind in {
        "plan_proposal",
        "plan_entry",
        "plan_giveup",
        "card_proposal",
        "card_state",
        "discipline",
        "emergency",
    }:
        return True
    return kind in {"sector", "opportunity"} and item["severity"] in {"L2", "L3"}
