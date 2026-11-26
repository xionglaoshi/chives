"""Strategy adapters.  This release ships ``zhushenglang`` only.

Reads go to the rule engine's SQLite output (never written here) and to the
local daily store for names and the MA10 line.  All prices are forward-adjusted
and every payload is computed after the close; no future data is read.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from cn_daily_store import DailyStore

IMPORTANT_EVENTS = {"优先级一确定", "入主升浪池", "主升浪移出"}


class Strategy(Protocol):
    id: str
    name: str
    description: str

    def latest_date(self) -> str | None: ...

    def pools(self, day: str | None = None) -> dict[str, Any]: ...

    def round(self, code: str, day: str | None = None) -> dict[str, Any] | None: ...

    def events(
        self,
        start: str | None = None,
        end: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]: ...

    def levels(self, code: str) -> dict[str, Any] | None: ...

    def annotate(self, code: str, round_id: int) -> dict[str, Any]: ...

    def event_level(self, event: str) -> str: ...


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"数据库不存在：{path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


class ZhushenglangStrategy:
    id = "zhushenglang"
    name = "主升浪"
    description = "首板观察池与主升浪阶段池：收盘后按规格 v1 计算，前复权价格，不使用未来数据。"

    def __init__(self, surge_db: Path | str, daily_db: Path | str) -> None:
        self.surge_db = Path(surge_db)
        self.daily_db = Path(daily_db)

    # -- metadata ---------------------------------------------------------
    def _meta(self, key: str) -> str | None:
        with closing(_readonly(self.surge_db)) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def latest_date(self) -> str | None:
        try:
            return self._meta("last_date")
        except FileNotFoundError:
            return None

    def spec_version(self) -> str | None:
        return self._meta("spec_version")

    def _name(self, code: str, day: str | None) -> str | None:
        try:
            with closing(DailyStore(self.daily_db)) as store:
                return store.name_on(code, day)
        except (FileNotFoundError, sqlite3.Error):
            return None

    # -- reads ------------------------------------------------------------
    def pools(self, day: str | None = None) -> dict[str, Any]:
        latest = self.latest_date()
        target = day or latest
        if target is None:
            raise ValueError("策略还没有计算过任何交易日")
        with closing(_readonly(self.surge_db)) as conn:
            first = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM pool_snapshots WHERE pool='first' AND date=? ORDER BY rank",
                    (target,),
                )
            ]
            main = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM pool_snapshots WHERE pool='main' AND date=? ORDER BY rank",
                    (target,),
                )
            ]
        for row in first + main:
            row["name"] = self._name(str(row["code"]), target)
        return {
            "strategy": self.id,
            "name": self.name,
            "description": self.description,
            "date": target,
            "latest_date": latest,
            "spec_version": self.spec_version(),
            "status": "已计算" if target == latest else ("尚未计算" if latest is not None and target > latest else "历史"),
            "counts": {"first": len(first), "main": len(main)},
            "pools": {"first": first, "main": main},
        }

    def _round_row(self, code: str, day: str | None) -> dict[str, Any] | None:
        with closing(_readonly(self.surge_db)) as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM rounds WHERE code=? ORDER BY round_id", (code,)
                )
            ]
        if not rows:
            return None
        target = day or self.latest_date()
        if target is None:
            return rows[-1]
        candidates = [row for row in rows if str(row["F"]) <= target]
        if not candidates:
            return None
        selected = candidates[-1]
        for row in candidates:
            ends = [
                value
                for value in (row.get("main_out_date"), row.get("first_out_date"))
                if value is not None
            ]
            if ends and all(str(end) >= target for end in ends):
                selected = row
                break
        return selected

    def round(self, code: str, day: str | None = None) -> dict[str, Any] | None:
        target = day or self.latest_date()
        row = self._round_row(code, target)
        if row is None:
            return None
        round_id = int(row["round_id"])
        with closing(_readonly(self.surge_db)) as conn:
            events = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM events WHERE code=? AND round_id=? ORDER BY date, id",
                    (code, round_id),
                )
            ]
            snapshots = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM pool_snapshots WHERE code=? AND round_id=? ORDER BY date, pool",
                    (code, round_id),
                )
            ]
        for event in events:
            event["values"] = json.loads(str(event["values"]))
        current = [item for item in snapshots if item["date"] == target] if target else []
        return {
            "strategy": self.id,
            "name": self._name(code, target),
            "code": code,
            "date": target,
            "round": row,
            "current": current,
            "events": events,
            "snapshots": snapshots,
        }

    def events(
        self,
        start: str | None = None,
        end: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append("date >= ?")
            params.append(start)
        if end:
            clauses.append("date <= ?")
            params.append(end)
        if kinds:
            clauses.append("event IN (" + ",".join("?" for _ in kinds) + ")")
            params.extend(kinds)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(int(limit))
        with closing(_readonly(self.surge_db)) as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM events" + where + " ORDER BY date, id LIMIT ?", params
                )
            ]
        for row in rows:
            row["values"] = json.loads(str(row["values"]))
            row["level"] = self.event_level(str(row["event"]))
            row["name"] = self._name(str(row["code"]), str(row["date"]))
        return rows

    def _ma10(self, code: str, day: str) -> float | None:
        try:
            with closing(DailyStore(self.daily_db)) as store:
                bars = store.bars(code, end=day, adjust="qfq")
        except (FileNotFoundError, sqlite3.Error):
            return None
        closes = [bar.close for bar in bars[-10:]]
        if len(closes) < 10:
            return None
        return round(sum(closes) / len(closes), 4)

    def levels(self, code: str) -> dict[str, Any] | None:
        latest = self.latest_date()
        if latest is None:
            return None
        row = self._round_row(code, latest)
        if row is None:
            return None
        with closing(_readonly(self.surge_db)) as conn:
            snapshots = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM pool_snapshots WHERE code=? AND date=? ORDER BY pool",
                    (code, latest),
                )
            ]
        main = next((item for item in snapshots if item["pool"] == "main"), None)
        first = next((item for item in snapshots if item["pool"] == "first"), None)
        snapshot = main or first or {}
        hb = first["hb"] if first is not None else None
        status = {
            "S1": (first or {}).get("s1_status"),
            "S2": (first or {}).get("s2_status"),
        }
        values = [
            {
                "key": "hb",
                "label": "突破线 Hb",
                "value": _float_or_none(hb),
                "basis": "首板日至上一交易日的最高收盘价（前复权）；收盘价严格高于它才记为启动。",
                "note": "二板直接入池时没有突破线。",
            },
            {
                "key": "p_star",
                "label": "标记价 P*",
                "value": _float_or_none(row.get("P_star")),
                "basis": "首次收盘价高于突破线当日的收盘价（前复权），之后不更新。",
                "note": "只对从首板观察池启动的轮次有值。",
            },
            {
                "key": "s1",
                "label": "支撑 S1（黄金坑低点 G）",
                "value": _float_or_none(row.get("G")),
                "basis": "首板前 10 个市场交易日的收盘最低点（前复权）。",
                "status": status["S1"],
                "note": "启动后停止支撑监控。",
            },
            {
                "key": "s2",
                "label": "支撑 S2（首板日最低价 L_F）",
                "value": _float_or_none(row.get("L_F")),
                "basis": "首板日最低价（前复权）。",
                "status": status["S2"],
                "note": "启动后停止支撑监控。",
            },
            {
                "key": "ma10",
                "label": "MA10",
                "value": self._ma10(code, latest),
                "basis": f"截至 {latest} 的最近 10 根有效 K 线前复权收盘均值；不足 10 根为 null。",
                "count": _int_or_none(snapshot.get("ma10_count")),
                "observing_days": _int_or_none(snapshot.get("ma10_obs_left")),
                "note": "主升浪池按入池后跌破 MA10 的次数与 3 日观察移出。",
            },
        ]
        return {
            "strategy": self.id,
            "name": self._name(code, latest),
            "code": code,
            "as_of": latest,
            "round": {
                "round_id": int(row["round_id"]),
                "F": row.get("F"),
                "T_star": row.get("T_star"),
                "E": row.get("E"),
                "B": _float_or_none(row.get("B")),
                "priority": row.get("priority"),
            },
            "levels": values,
            "disclaimer": "规则筛选结果，不是买卖建议。",
        }

    def annotate(self, code: str, round_id: int) -> dict[str, Any]:
        from surge_engine.annotate import annotate_round
        from surge_engine.outputs import OutputStore

        output = OutputStore(self.surge_db)
        store = DailyStore(self.daily_db)
        try:
            payload = annotate_round(
                code,
                int(round_id),
                output=output,
                store=store,
                out_dir=self.surge_db.parent / "review",
            )
        finally:
            output.close()
            store.close()
        payload["image_path"] = payload.get("html_path")
        return payload

    def event_level(self, event: str) -> str:
        return "important" if event in IMPORTANT_EVENTS else "info"
