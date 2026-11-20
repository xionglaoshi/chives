"""Shared offline test helpers."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from chives_hub.config import load_config
from chives_hub.models import CN_TZ
from chives_hub.sources import SourceError, UpstreamRejection

NOW = datetime(2026, 11, 4, 10, 0, 0, tzinfo=CN_TZ)


class FakeClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def set(self, value: datetime) -> None:
        self.value = value


def at(hour: int, minute: int = 0, second: int = 0, day: int = 4) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=CN_TZ)


@dataclass
class SimpleQuote:
    code: str
    name: str
    price: Optional[float]
    prev_close: Optional[float]
    change_pct: Optional[float]


def write_config(tmp_path: Path, **overrides: Any) -> Path:
    db = overrides.pop("db", "hub.db")
    analyses = overrides.pop("analyses", "analyses")
    calendar = overrides.pop("calendar", "calendar.json")
    text = (
        "api:\n"
        "  host: 127.0.0.1\n"
        "  port: 8867\n"
        "runtime:\n"
        f"  db_path: {db}\n"
        "  out_dir: .\n"
        f"analyses_dir: {analyses}\n"
        f"calendar_file: {calendar}\n"
    )
    for key, value in overrides.items():
        text += f"{key}: {value}\n"
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    (tmp_path / calendar).write_text("[]", encoding="utf-8")
    return path


def make_config(tmp_path: Path, **overrides: Any):
    return load_config(write_config(tmp_path, **overrides))


COND_GROUPS = ("market", "sector", "stock", "giveup")


class FakePlanRules:
    """In-memory stand-in for cn-watch's /plans* endpoints.

    Tests drive the hub mirror by rewriting ``plan.state`` through
    :meth:`set_state`; the fake never evaluates conditions itself.
    """

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.reject: Optional[tuple[str, str]] = None

    def _now(self, now: Optional[datetime]) -> datetime:
        return now or NOW

    def _plan_state(self, plan: dict[str, Any], moment: datetime) -> dict[str, Any]:
        return {
            "id": plan["id"],
            "code": plan["code"],
            "label": plan["label"],
            "state": "observe",
            "since": moment.isoformat(),
            "last_price": None,
            "held": bool(plan.get("held")),
            "conds": {
                key: [None] * len(plan.get(key) or []) for key in COND_GROUPS
            },
            "history": [],
            "expires_at": plan.get("expires_at"),
            "active": True,
        }

    def upsert_plan(self, plan: dict[str, Any], *, now: Optional[datetime] = None):
        self.calls.append(("upsert", json.loads(json.dumps(plan))))
        if self.fail:
            raise SourceError("upstream_network", "fake cn-watch down")
        if self.reject:
            code, message = self.reject
            raise UpstreamRejection(code, message)
        moment = self._now(now)
        existing = self.states.get(plan["id"])
        if existing is None:
            state = self._plan_state(plan, moment)
        else:
            state = dict(existing)
            state["held"] = bool(plan.get("held"))
            state["expires_at"] = plan.get("expires_at")
            state["label"] = plan.get("label")
        self.states[plan["id"]] = state
        return {"ok": True, "plan": json.loads(json.dumps(state))}

    def remove_plan(self, plan_id: str, *, now: Optional[datetime] = None):
        self.calls.append(("remove", {"id": plan_id}))
        if self.fail:
            raise SourceError("upstream_network", "fake cn-watch down")
        if plan_id not in self.states:
            raise UpstreamRejection("not_found", f"计划不存在: {plan_id}")
        del self.states[plan_id]
        return {"ok": True, "status": "removed", "id": plan_id}

    def plans(self, *, now: Optional[datetime] = None):
        self.calls.append(("plans", {}))
        if self.fail:
            raise SourceError("upstream_network", "fake cn-watch down")
        moment = self._now(now)
        return {
            "ok": True,
            "as_of": moment.isoformat(),
            "market_context": {"ok": True, "age_s": 1.0, "regime": "strong"},
            "plans": [json.loads(json.dumps(item)) for item in self.states.values()],
        }

    def set_state(
        self,
        plan_id: str,
        state: str,
        *,
        now: Optional[datetime] = None,
        price: Optional[float] = None,
        conds: Optional[dict[str, list[Optional[bool]]]] = None,
        reason: str = "测试驱动",
    ) -> dict[str, Any]:
        moment = self._now(now)
        plan = self.states.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        plan["history"].append(
            {
                "ts": moment.isoformat(),
                "from": plan["state"],
                "to": state,
                "reason": reason,
            }
        )
        plan["state"] = state
        plan["since"] = moment.isoformat()
        if price is not None:
            plan["last_price"] = price
        if conds is not None:
            plan["conds"] = conds
        return json.loads(json.dumps(plan))

    def upserts(self) -> list[dict[str, Any]]:
        return [payload for action, payload in self.calls if action == "upsert"]

    def removes(self) -> list[dict[str, Any]]:
        return [payload for action, payload in self.calls if action == "remove"]


class FakeSources:
    def __init__(self) -> None:
        self.cn: list[dict[str, Any]] = []
        self.market: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {"quotes": {}}
        self.quotes: dict[str, SimpleQuote] = {}
        self.analysis_map: dict[int, Any] = {}
        self.fail_cn = False
        self.fail_market = False
        self.fail_state = False
        self.fail_tencent = False
        self.fail_overview = False
        self.calls: list[str] = []
        self.plan_rules = FakePlanRules()
        self.overview_payload: dict[str, Any] = {
            "ok": True,
            "as_of": "2026-11-04T10:00:00+08:00",
            "trading_state": "open",
            "indexes": [
                {"code": "000001.SH", "name": "上证指数", "price": 3300.0, "change_pct": 0.5, "amount_yuan": 1e11},
                {"code": "399001.SZ", "name": "深证成指", "price": 11000.0, "change_pct": 0.7, "amount_yuan": 1e11},
                {"code": "399006.SZ", "name": "创业板指", "price": 2200.0, "change_pct": 1.0, "amount_yuan": 5e10},
                {"code": "000300.SH", "name": "沪深300", "price": 3900.0, "change_pct": 0.4, "amount_yuan": 8e10},
                {"code": "000852.SH", "name": "中证1000", "price": 6100.0, "change_pct": 0.2, "amount_yuan": 3e10},
                {"code": "000688.SH", "name": "科创50", "price": 900.0, "change_pct": -0.1, "amount_yuan": 2e10},
            ],
            "breadth": {
                "up": 3000,
                "down": 2000,
                "flat": 100,
                "up_ratio": 0.59,
                "limit_up": 60,
                "limit_down": 5,
                "broken": 20,
                "seal_ratio": 75.0,
                "max_streak": 4,
                "amount_yuan": 9e11,
            },
            "regime": {"label": "risk_on", "reasons": ["宽度走强", "成交额放大"]},
        }
        self.sectors_payload: dict[str, Any] = {
            "ok": True,
            "level": "sw1",
            "rows": [
                {"code": "BK0433", "name": "农林牧渔", "change_pct": 3.2, "rank": 1},
                {"code": "BK0475", "name": "银行", "change_pct": -0.8, "rank": 28},
            ],
        }
        self.pool_payloads: dict[str, dict[str, Any]] = {
            kind: {"ok": True, "kind": kind, "count": count, "rows": []}
            for kind, count in (("zt", 60), ("zb", 20), ("dt", 5))
        }
        self.ladder_payload: dict[str, Any] = {
            "ok": True,
            "max_streak": 4,
            "first_board_count": 30,
            "tiers": [
                {"streak": 4, "count": 1, "rows": [{"code": "600001.SH", "name": "甲"}]},
                {"streak": 1, "count": 30},
            ],
        }
        self.history_payload: dict[str, Any] = {
            "ok": True,
            "days": [
                {"date": "2026-11-03", "zt": 48, "dt": 8, "zb": 12, "seal_ratio_pct": 80.0, "max_streak": 3, "available": True}
            ],
        }
        self.yesterday_payload: dict[str, Any] = {
            "ok": True,
            "avg_open_pct": 1.5,
            "avg_close_pct": 2.0,
            "win_ratio_pct": 60.0,
        }
        self.themes_payload: dict[str, Any] = {
            "ok": True,
            "rows": [{"rank": 1, "code": "BK1000", "name": "机器人", "change_pct": 4.0}],
        }
        self.flows_payload: dict[str, Any] = {
            "ok": True,
            "rows": [{"rank": 1, "code": "BK0433", "name": "农林牧渔", "main_net_yuan": 1e9}],
        }
        self.by_industry_payload: dict[str, Any] = {
            "ok": True,
            "rows": [{"industry": "农林牧渔", "zt_count": 5}],
        }

    def analyses(self) -> dict[int, Any]:
        return dict(self.analysis_map)

    def market_overview(self, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_overview")
        if self.fail_overview:
            raise RuntimeError("down")
        return dict(self.overview_payload)

    def market_sectors(self, level: str = "sw1", now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_sectors")
        return dict(self.sectors_payload)

    def market_pool(self, kind: str, *, day: Optional[str] = None, limit: int = 200, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append(f"market_pool:{kind}")
        return dict(self.pool_payloads[kind])

    def market_pool_ladder(self, *, day: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_pool_ladder")
        return dict(self.ladder_payload)

    def market_pool_history(self, days: int = 10, *, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_pool_history")
        return dict(self.history_payload)

    def market_pool_by_industry(self, *, day: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_pool_by_industry")
        return dict(self.by_industry_payload)

    def market_pool_yesterday(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_pool_yesterday")
        return dict(self.yesterday_payload)

    def market_themes(self, *, limit: int = 10, sort: str = "change", now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_themes")
        return dict(self.themes_payload)

    def market_flows(self, kind: str = "sector_in", *, limit: int = 5, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("market_flows")
        return dict(self.flows_payload)

    def cn_alerts(self, after_id: int, limit: int = 200, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        self.calls.append("cn_alerts")
        if self.fail_cn:
            raise RuntimeError("down")
        rows = [row for row in self.cn if int(row["id"]) > after_id]
        rows.sort(key=lambda row: int(row["id"]))
        return rows[:limit]

    def market_alerts(self, since_id: int, limit: int = 100, now: Optional[datetime] = None) -> list[dict[str, Any]]:
        self.calls.append("market_alerts")
        if self.fail_market:
            raise RuntimeError("down")
        rows = [row for row in self.market if int(row["id"]) > since_id]
        rows.sort(key=lambda row: int(row["id"]))
        return rows[:limit]

    def cn_state(self, now: Optional[datetime] = None) -> dict[str, Any]:
        self.calls.append("cn_state")
        if self.fail_state:
            raise RuntimeError("down")
        return self.state

    def tencent_quotes(self, codes, now: Optional[datetime] = None) -> dict[str, SimpleQuote]:
        self.calls.append("tencent_quotes")
        if self.fail_tencent:
            raise RuntimeError("down")
        return {code: self.quotes[code] for code in codes if code in self.quotes}

    def plans(self, *, now: Optional[datetime] = None):
        self.calls.append("plans")
        return self.plan_rules.plans(now=now)

    def upsert_plan(self, plan, *, now: Optional[datetime] = None):
        self.calls.append("upsert_plan")
        return self.plan_rules.upsert_plan(plan, now=now)

    def remove_plan(self, plan_id, *, now: Optional[datetime] = None):
        self.calls.append("remove_plan")
        return self.plan_rules.remove_plan(plan_id, now=now)

    def health(self, now: datetime) -> dict[str, Any]:
        return {
            "cn_watch": {"ok": not self.fail_cn, "age_s": 1.0},
            "market_watch": {"ok": not self.fail_market, "age_s": 1.0},
            "analyses": {"ok": True, "age_s": 1.0},
        }


class FakePortfolio:
    def __init__(self) -> None:
        self.overview_payload: dict[str, Any] = {
            "ok": True,
            "private": True,
            "as_of": "2026-11-04T10:00:00+08:00",
            "quote_time": "2026-11-04 10:00:00",
            "empty": True,
            "totals": {
                "market_value_cny": 0.0,
                "cost_cny": 0.0,
                "pnl_cny": 0.0,
                "pnl_pct": 0.0,
                "day_pnl_cny": 0.0,
                "day_pnl_pct": None,
                "cash_cny": 0.0,
                "total_assets_cny": 0.0,
                "position_ratio_pct": None,
            },
            "positions": [],
            "risk": None,
            "history_days": 0,
        }
        self.snapshot: Optional[dict[str, Any]] = None

    def overview(self) -> dict[str, Any]:
        return dict(self.overview_payload)

    def history(self, days: int) -> dict[str, Any]:
        return {"ok": True, "private": True, "points": [], "note": "test"}

    def snapshot_values(self) -> Optional[dict[str, Any]]:
        return self.snapshot


def cn_alert(
    alert_id: int,
    *,
    code: str = "601099.SH",
    name: str = "太平洋",
    rule_id: str = "surge_3x",
    rule_type: str = "volume_surge",
    direction: Optional[str] = None,
    price: float = 3.51,
    prev_close: float = 3.54,
    change_pct: float = -0.85,
    ts: str = "2026-11-04T09:30:05+08:00",
) -> dict[str, Any]:
    return {
        "id": alert_id,
        "ts": ts,
        "code": code,
        "name": name,
        "rule_id": rule_id,
        "rule_type": rule_type,
        "direction": direction,
        "price": price,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "vwap": price,
        "limit_up": None,
        "limit_down": None,
        "detail": {},
        "dedupe_key": f"{code}|{rule_id}|{alert_id}",
    }


def market_alert(
    alert_id: int,
    *,
    rule: str = "R3",
    object_type: str = "sector",
    code: str = "BK0433",
    name: str = "农林牧渔",
    severity: str = "L2",
    title: str = "板块排名跃升",
    detail: str = "农林牧渔 排名从 20 升至 3",
    payload: Optional[dict[str, Any]] = None,
    ts: str = "2026-11-04T09:40:00+08:00",
) -> dict[str, Any]:
    return {
        "id": alert_id,
        "ts": ts,
        "rule_id": rule,
        "object": {"type": object_type, "code": code, "name": name},
        "severity": severity,
        "title": title,
        "detail": detail,
        "payload": payload or {},
        "status": "new",
    }


def free_port() -> int:
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def analysis_file(directory: Path, alert_id: int, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"analysis-{alert_id}.md"
    path.write_text(body, encoding="utf-8")
    return path


def write_analyses_index(directory: Path, rows: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    (directory / "analyses.jsonl").write_text(text + "\n", encoding="utf-8")


DEFAULT_TOTALS: dict[str, Any] = {
    "market_value_cny": 200000.0,
    "cost_cny": 190000.0,
    "pnl_cny": 10000.0,
    "pnl_pct": 5.0,
    "day_pnl_cny": 1000.0,
    "day_pnl_pct": 0.5,
    "cash_cny": 800000.0,
    "total_assets_cny": 1000000.0,
    "position_ratio_pct": 20.0,
}


def build_engine(
    tmp_path: Path,
    *,
    now: datetime = NOW,
    positions: Optional[list[dict[str, Any]]] = None,
    totals: Optional[dict[str, Any]] = None,
    sources: Optional[FakeSources] = None,
    portfolio: Optional[FakePortfolio] = None,
):
    from chives_hub.engine import HubEngine

    config = make_config(tmp_path)
    clock = FakeClock(now)
    sources = sources or FakeSources()
    if not sources.state.get("quotes"):
        sources.state["quotes"] = {
            "600519.SH": {
                "price": 100.0,
                "prev_close": 98.0,
                "open": 99.0,
                "high": 101.0,
                "low": 97.0,
                "change_pct": 2.04,
                "name": "贵州茅台",
            }
        }
    portfolio = portfolio or FakePortfolio()
    positions = positions if positions is not None else [
        {"code": "600519.SH", "name": "贵州茅台", "weight_pct": 20.0, "pnl_pct": 5.0, "industry": "食品饮料"}
    ]
    portfolio.overview_payload.update(
        {
            "empty": not positions,
            "positions": positions,
            "totals": dict(totals or DEFAULT_TOTALS),
        }
    )
    engine = HubEngine(config, clock=clock, sources=sources, portfolio=portfolio)
    return engine, clock, sources, portfolio


def active_card(engine, *, plan_state: str = "execute", plan_price: Optional[float] = 100.0,
                plan_conds: Optional[dict[str, list[Optional[bool]]]] = None, **overrides):
    """Create an active card and drive the fake cn-watch to ``plan_state``."""
    body = {
        "code": "600519.SH",
        "thesis": "测试作战卡",
        "stock_conditions": [{"type": "price_cross", "direction": "up", "level": 99}],
        "risk": {"stop_price": 90},
        "proposed_by": "user",
    }
    body.update(overrides)
    card = engine.create_card(body)["card"]
    if plan_state is not None and card["status"] == "active":
        set_plan_state(
            engine, card["id"], plan_state, price=plan_price, conds=plan_conds
        )
    return card


def set_plan_state(
    engine,
    card_id: int,
    state: str,
    *,
    price: Optional[float] = 100.0,
    conds: Optional[dict[str, list[Optional[bool]]]] = None,
    now: Optional[datetime] = None,
    reason: str = "测试驱动",
) -> dict[str, Any]:
    return engine.sources.plan_rules.set_state(
        f"card-{card_id}",
        state,
        now=now or engine.now(),
        price=price,
        conds=conds,
        reason=reason,
    )


def adopt_setting(engine, key: str, value: float) -> None:
    engine.setting_action(key, {"action": "set", "value": value})


def triggers(engine):
    return engine.store.list_triggers()


def signals_of(engine, kind: str):
    return [row for row in engine.store.list_signals(status="all") if row["kind"] == kind]
