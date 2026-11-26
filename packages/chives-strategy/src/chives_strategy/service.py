"""Read APIs shared by the HTTP daemon and the stdio MCP forwarding layer."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .db import AlertStore
from .strategy import Strategy

SHANGHAI = ZoneInfo("Asia/Shanghai")


class StrategyNotFound(KeyError):
    def __init__(self, strategy_id: str) -> None:
        super().__init__(strategy_id)
        self.strategy_id = strategy_id


def now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


class HubService:
    def __init__(
        self,
        strategies: dict[str, Strategy],
        alerts: AlertStore,
        *,
        now: Callable[[], datetime] | None = None,
        backtests: Any | None = None,
    ) -> None:
        self.strategies = strategies
        self.alerts = alerts
        self.now = now or (lambda: datetime.now(SHANGHAI))
        self.scheduler_state: Callable[[], dict[str, Any]] | None = None
        self.backtests = backtests

    def get(self, strategy_id: str) -> Strategy:
        strategy = self.strategies.get(strategy_id)
        if strategy is None:
            raise StrategyNotFound(strategy_id)
        return strategy

    def list_strategies(self) -> dict[str, Any]:
        rows = []
        for strategy in self.strategies.values():
            rows.append(
                {
                    "id": strategy.id,
                    "name": strategy.name,
                    "description": strategy.description,
                    "latest_date": strategy.latest_date(),
                    "important_events": ["优先级一确定", "入主升浪池", "主升浪移出"],
                    "basis": "前复权、收盘后计算、不使用未来数据；规则筛选结果，不是买卖建议。",
                }
            )
        return {"ok": True, "strategies": rows}

    def pools(self, strategy_id: str, day: str | None = None) -> dict[str, Any]:
        return self.get(strategy_id).pools(day)

    def round(self, strategy_id: str, code: str, day: str | None = None) -> dict[str, Any] | None:
        return self.get(strategy_id).round(code, day)

    def events(
        self,
        strategy_id: str,
        start: str | None = None,
        end: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        rows = self.get(strategy_id).events(start, end, kinds, limit)
        return {
            "ok": True,
            "strategy": strategy_id,
            "start": start,
            "end": end,
            "kinds": kinds or [],
            "count": len(rows),
            "events": rows,
        }

    def levels(self, strategy_id: str, code: str) -> dict[str, Any] | None:
        return self.get(strategy_id).levels(code)

    def annotate(self, strategy_id: str, code: str, round_id: int) -> dict[str, Any]:
        return self.get(strategy_id).annotate(code, round_id)

    def start_backtest(
        self,
        strategy_id: str,
        scheme: str,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        if self.backtests is None:
            raise RuntimeError("回测服务未启用")
        return self.backtests.submit(strategy_id, scheme, start, end)

    def backtest_result(self, strategy_id: str, job_id: str) -> dict[str, Any]:
        if self.backtests is None:
            raise RuntimeError("回测服务未启用")
        return self.backtests.result(strategy_id, job_id)

    def backtest_history(self, strategy_id: str, limit: int = 20) -> dict[str, Any]:
        if self.backtests is None:
            raise RuntimeError("回测服务未启用")
        return self.backtests.history(strategy_id, limit)

    def alerts_payload(self, since_id: int = 0, limit: int = 100) -> dict[str, Any]:
        rows = self.alerts.list(since_id, limit)
        alerts = []
        for row in rows:
            alerts.append(
                {
                    "id": int(row["id"]),
                    "strategy_id": row["strategy_id"],
                    "rule_id": row["rule_id"],
                    "code": row["code"],
                    "name": row["name"],
                    "round_id": row["round_id"],
                    "event": row["event"],
                    "event_date": row["event_date"],
                    "level": row["level"],
                    "title": row["title"],
                    "detail": row["detail"],
                    "created_at": row["created_at"],
                }
            )
        next_id = int(rows[-1]["id"]) if rows else int(since_id)
        return {"ok": True, "alerts": alerts, "next_id": next_id}

    def ingest_events(self, day: str, strategy_id: str | None = None) -> int:
        """Copy one market day's engine events into the alert table.

        Important events are pushed by the server later; info events are stored
        with ``level=info`` and are never pushed.
        """

        written = 0
        selected = [self.get(strategy_id)] if strategy_id else list(self.strategies.values())
        created_at = now_iso()
        for strategy in selected:
            for event in strategy.events(start=day, end=day, limit=10_000):
                code = str(event["code"])
                name = event.get("name")
                event_name = str(event["event"])
                level = strategy.event_level(event_name)
                detail = {
                    "strategy_id": strategy.id,
                    "event": event_name,
                    "date": event.get("date"),
                    "code": code,
                    "name": name,
                    "round_id": event.get("round_id"),
                    "values": event.get("values"),
                }
                title = f"{name or code} {code} {event_name}"
                alert_id = self.alerts.add(
                    strategy_id=strategy.id,
                    source_event_id=event.get("id") if isinstance(event.get("id"), int) else None,
                    code=code,
                    name=name,
                    round_id=event.get("round_id"),
                    event=event_name,
                    event_date=str(event.get("date")),
                    level=level,
                    rule_id=f"{strategy.id}:{event_name}",
                    title=title,
                    detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
                    created_at=created_at,
                )
                if alert_id is not None:
                    written += 1
        return written

    def health(self, scheduler: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = []
        for strategy in self.strategies.values():
            rows.append({"id": strategy.id, "latest_date": strategy.latest_date()})
        state = scheduler
        if state is None and self.scheduler_state is not None:
            try:
                state = self.scheduler_state()
            except Exception:  # noqa: BLE001 - health must still answer
                state = {"status": "unknown"}
        return {
            "ok": True,
            "service": "strategy-hub",
            "time": self.now().isoformat(timespec="seconds"),
            "strategies": rows,
            "alerts_latest_id": self.alerts.latest_id(),
            "scheduler": state or {"status": "disabled"},
        }

    @staticmethod
    def valid_date(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise ValueError(f"日期格式需要 YYYY-MM-DD：{value}") from exc
