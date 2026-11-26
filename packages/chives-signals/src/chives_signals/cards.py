"""Playbook cards: condition validation, sizing, locking and payloads.

Conditions are no longer evaluated here: cn-watch owns the single intraday
evaluator (see :mod:`chives_signals.plan_sync`).  The hub keeps the business
attributes -- review link, sizing, confirm/lock policy, judgement text and the
candidate outcome statistics.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from typing import Any, Iterable, Mapping, Optional

from .calendar import TradingCalendar
from .models import CN_TZ, fmt_iso
from .validation import ApiError, as_int, clean_text, number, only

CARD_STATUSES = ("proposed", "active", "expired", "cancelled", "closed")
CARD_STATES = ("observe", "await_confirm", "execute", "abandon", "exit")
CONDITION_TYPES = {
    "regime",
    "index_pct",
    "sector_change",
    "sector_rank",
    "price_cross",
    "price_in_range",
    "pct_change",
    "open_pct",
    "volume_ratio",
}
INDEX_CODES = {
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000852.SH",
    "000688.SH",
}
SECTOR_CODE_RE = re.compile(r"^BK[0-9]{4}$")
MAX_CONDITIONS = 6
MAX_LIVE_CARDS = 15
MAX_PER_CODE_DAY = 2
MAX_THESIS = 200
LOCK_TIME = time(9, 25)

CREATE_FIELDS = {
    "code",
    "name",
    "review_date",
    "thesis",
    "tags",
    "market_conditions",
    "sector_conditions",
    "stock_conditions",
    "confirm_policy",
    "giveup",
    "risk",
    "proposed_by",
    "expires_at",
}
ACTION_FIELDS = {"action", "stop", "state"}
TAG_FIELDS = {"streak", "theme", "env"}
RISK_FIELDS = {"stop_price", "per_trade_risk_pct", "position_cap_pct", "exit_rules"}


# -- condition validation ------------------------------------------------
def _op(raw: Any, allowed: set[str]) -> str:
    if raw not in allowed:
        raise ApiError("bad_condition", "op 不合法")
    return str(raw)


def validate_condition(raw: Any) -> dict[str, Any]:
    try:
        return _validate_condition(raw)
    except ApiError as exc:
        if exc.code == "bad_condition":
            raise
        raise ApiError("bad_condition", str(exc)) from exc


def _validate_condition(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ApiError("bad_condition", "condition 必须是对象")
    cond_type = raw.get("type")
    if cond_type not in CONDITION_TYPES:
        raise ApiError("bad_condition", "未知的条件类型")
    if cond_type == "regime":
        only(raw, {"type", "values"})
        values = raw.get("values")
        if not isinstance(values, list) or not values:
            raise ApiError("bad_condition", "regime.values 必须是非空数组")
        cleaned = []
        for value in values:
            if value not in {"strong", "neutral", "weak"}:
                raise ApiError("bad_condition", "regime.values 只接受 strong/neutral/weak")
            cleaned.append(value)
        return {"type": "regime", "values": cleaned}
    if cond_type == "index_pct":
        only(raw, {"type", "code", "op", "value"})
        code = raw.get("code")
        if code not in INDEX_CODES:
            raise ApiError("bad_condition", "index_pct.code 不在允许的指数内")
        return {
            "type": "index_pct",
            "code": code,
            "op": _op(raw.get("op"), {">=", "<="}),
            "value": number(raw.get("value"), "value"),
        }
    if cond_type == "sector_change":
        only(raw, {"type", "sector_code", "op", "value"})
        return {
            "type": "sector_change",
            "sector_code": _sector(raw.get("sector_code")),
            "op": _op(raw.get("op"), {">=", "<="}),
            "value": number(raw.get("value"), "value"),
        }
    if cond_type == "sector_rank":
        only(raw, {"type", "sector_code", "op", "value"})
        return {
            "type": "sector_rank",
            "sector_code": _sector(raw.get("sector_code")),
            "op": _op(raw.get("op"), {">=", "<="}),
            "value": number(raw.get("value"), "value", minimum=1, integer=False),
        }
    if cond_type == "price_cross":
        only(raw, {"type", "direction", "level"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise ApiError("bad_condition", "price_cross.direction 只接受 up/down")
        level = number(raw.get("level"), "level")
        if level <= 0:
            raise ApiError("bad_condition", "price_cross.level 必须为正数")
        return {"type": "price_cross", "direction": direction, "level": level}
    if cond_type == "price_in_range":
        only(raw, {"type", "lo", "hi"})
        lo = number(raw.get("lo"), "lo")
        hi = number(raw.get("hi"), "hi")
        if lo <= 0 or hi <= 0:
            raise ApiError("bad_condition", "price_in_range 价位必须为正数")
        if lo >= hi:
            raise ApiError("bad_condition", "price_in_range 要求 lo < hi")
        return {"type": "price_in_range", "lo": lo, "hi": hi}
    if cond_type == "pct_change":
        only(raw, {"type", "direction", "threshold_pct"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise ApiError("bad_condition", "pct_change.direction 只接受 up/down")
        return {
            "type": "pct_change",
            "direction": direction,
            "threshold_pct": number(raw.get("threshold_pct"), "threshold_pct", maximum=100),
        }
    if cond_type == "open_pct":
        only(raw, {"type", "op", "value"})
        return {
            "type": "open_pct",
            "op": _op(raw.get("op"), {">=", "<="}),
            "value": number(raw.get("value"), "value", minimum=-100, maximum=100),
        }
    # volume_ratio
    only(raw, {"type", "op", "value"})
    value = number(raw.get("value"), "value")
    if value <= 0:
        raise ApiError("bad_condition", "volume_ratio.value 必须为正数")
    return {
        "type": "volume_ratio",
        "op": _op(raw.get("op"), {">=", "<="}),
        "value": value,
    }


def _sector(raw: Any) -> str:
    if not isinstance(raw, str) or not SECTOR_CODE_RE.match(raw.strip()):
        raise ApiError("bad_condition", "sector_code 必须形如 BK0433")
    return raw.strip()


def validate_conditions(raw: Any, field: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError("bad_condition", f"{field} 必须是数组")
    if len(raw) > MAX_CONDITIONS:
        raise ApiError("too_many_conditions", f"{field} 最多 {MAX_CONDITIONS} 条")
    return [validate_condition(item) for item in raw]


# -- creation ------------------------------------------------------------
def normalize_card_code(raw: Any) -> str:
    from .plans import normalize_code

    code = normalize_code(raw)
    if code.endswith(".BJ") or code.startswith(("4", "8", "920")):
        raise ApiError("invalid_code", "作战卡仅支持沪深 A 股，不含北交所")
    return code


def _validate_tags(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError("invalid_tags", "tags 必须是对象")
    only(raw, TAG_FIELDS)
    tags: dict[str, Any] = {}
    if raw.get("streak") is not None:
        tags["streak"] = as_int(raw.get("streak"), "tags.streak", minimum=0, maximum=100)
    if raw.get("theme") is not None:
        tags["theme"] = clean_text(raw.get("theme"), "tags.theme", 40, allow_empty=True)
    if raw.get("env") is not None:
        if raw.get("env") not in {"strong", "neutral", "weak"}:
            raise ApiError("invalid_tags", "tags.env 只接受 strong/neutral/weak")
        tags["env"] = raw["env"]
    return tags


def _validate_risk(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ApiError("invalid_risk", "risk 必须是对象")
    only(raw, RISK_FIELDS)
    stop = number(raw.get("stop_price"), "risk.stop_price")
    if stop <= 0:
        raise ApiError("invalid_risk", "risk.stop_price 必须为正数")
    per_trade = None
    if raw.get("per_trade_risk_pct") is not None:
        per_trade = number(raw.get("per_trade_risk_pct"), "risk.per_trade_risk_pct", maximum=10)
    position_cap = None
    if raw.get("position_cap_pct") is not None:
        position_cap = number(raw.get("position_cap_pct"), "risk.position_cap_pct", maximum=100)
    exit_rules: list[str] = []
    if raw.get("exit_rules") is not None:
        rules = raw.get("exit_rules")
        if not isinstance(rules, list):
            raise ApiError("invalid_risk", "exit_rules 必须是数组")
        if len(rules) > 3:
            raise ApiError("invalid_risk", "exit_rules 最多 3 条")
        exit_rules = [
            clean_text(item, "exit_rules", 80) for item in rules
        ]
    return {
        "stop_price": stop,
        "per_trade_risk_pct": per_trade,
        "position_cap_pct": position_cap,
        "exit_rules": exit_rules,
    }


def validate_expiry(
    raw: Any, *, now: datetime, calendar: TradingCalendar
) -> datetime:
    if raw is None:
        day = calendar.next_trading_day(now.date())
        return calendar.close_at(day)
    if not isinstance(raw, str) or not raw.strip():
        raise ApiError("invalid_expiry", "expires_at 必须是 ISO8601 字符串")
    text = raw.strip()
    try:
        if len(text) == 10:
            expires = calendar.close_at(date.fromisoformat(text))
        else:
            from .models import parse_iso

            expires = parse_iso(text)
    except ValueError as exc:
        raise ApiError("invalid_expiry", "expires_at 必须是带时区的 ISO8601 时间") from exc
    if expires <= now:
        raise ApiError("invalid_expiry", "expires_at 必须晚于当前时间")
    max_day = calendar.add_trading_days(now.date(), 5)
    if expires > calendar.close_at(max_day):
        raise ApiError("invalid_expiry", "作战卡有效期不得超过 5 个交易日")
    return expires


def creation_lock(now: datetime, calendar: TradingCalendar) -> tuple[Optional[datetime], bool]:
    if calendar.is_trading_day(now.date()) and now.timetz().replace(tzinfo=None) >= LOCK_TIME:
        return now, True
    return None, False


def lock_moment(created_at: datetime, calendar: TradingCalendar) -> datetime:
    local = created_at.astimezone(CN_TZ)
    if calendar.is_trading_day(local.date()):
        moment = datetime.combine(local.date(), LOCK_TIME, tzinfo=CN_TZ)
        return max(moment, local)
    day = calendar.next_trading_day(local.date())
    return datetime.combine(day, LOCK_TIME, tzinfo=CN_TZ)


def is_locked(card: Mapping[str, Any], now: datetime, calendar: TradingCalendar) -> bool:
    if card.get("locked_at") is not None:
        return True
    return now >= lock_moment(card["created_at"], calendar)


def create_card(
    payload: Any,
    *,
    now: datetime,
    calendar: TradingCalendar,
    live_count: int,
    code_day_count: int,
    name_resolver: Optional[Any] = None,
    settings: Any = None,
    overview: Optional[Mapping[str, Any]] = None,
    regime: Optional[str] = None,
    latest_price: Optional[float] = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, CREATE_FIELDS)
    code = normalize_card_code(payload.get("code"))
    proposed_by = payload.get("proposed_by")
    if proposed_by not in {"agent", "user"}:
        raise ApiError("invalid_proposed_by", "proposed_by 只接受 agent/user")
    if live_count >= MAX_LIVE_CARDS:
        raise ApiError("card_limit", f"活跃+待确认作战卡最多 {MAX_LIVE_CARDS} 张")
    if code_day_count >= MAX_PER_CODE_DAY:
        raise ApiError("card_code_limit", "同一代码同一交易日最多 2 张作战卡")

    thesis = clean_text(payload.get("thesis", ""), "thesis", MAX_THESIS, allow_empty=True)
    market_conditions = validate_conditions(payload.get("market_conditions"), "market_conditions")
    sector_conditions = validate_conditions(payload.get("sector_conditions"), "sector_conditions")
    stock_conditions = validate_conditions(payload.get("stock_conditions"), "stock_conditions")
    giveup = validate_conditions(payload.get("giveup"), "giveup")
    confirm_policy = payload.get("confirm_policy") or "all"
    if confirm_policy not in {"all", "any"}:
        raise ApiError("invalid_confirm_policy", "confirm_policy 只接受 all/any")
    risk = _validate_risk(payload.get("risk"))
    tags = _validate_tags(payload.get("tags"))
    review_date: Optional[str] = None
    if payload.get("review_date") is not None:
        raw_date = payload.get("review_date")
        if not isinstance(raw_date, str):
            raise ApiError("invalid_review_date", "review_date 必须是 YYYY-MM-DD")
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ApiError("invalid_review_date", "review_date 必须是 YYYY-MM-DD") from exc
        review_date = raw_date
    else:
        review_date = now.date().isoformat()
    expires_at = validate_expiry(payload.get("expires_at"), now=now, calendar=calendar)

    name = ""
    if payload.get("name") is not None:
        name = clean_text(payload.get("name"), "name", 20)
    if not name and name_resolver is not None:
        try:
            name = str(name_resolver(code) or "")
        except Exception:  # noqa: BLE001 - a name is cosmetic
            name = ""
    name = name or code

    entry_ref, entry_source = _entry_reference(stock_conditions, latest_price)
    if entry_ref is not None and entry_ref > 0:
        distance = (entry_ref - risk["stop_price"]) / entry_ref * 100.0
        if distance <= 0:
            raise ApiError("bad_stop", "止损价必须低于入场参考价")
        if distance > 30.0:
            raise ApiError("bad_stop", "止损距离不得超过 30%")
    sizing, sizing_error = _sizing_for(
        entry_ref=entry_ref,
        entry_source=entry_source,
        stop=risk["stop_price"],
        risk=risk,
        settings=settings,
        overview=overview,
        regime=regime,
    )
    if entry_ref is not None and entry_ref > 0 and risk["stop_price"] >= entry_ref:
        raise ApiError("bad_stop", "止损价必须低于入场参考价")
    locked_at, late = creation_lock(now, calendar)
    status = "proposed" if proposed_by == "agent" else "active"
    return {
        "code": code,
        "name": name,
        "status": status,
        "state": "observe",
        "review_date": review_date,
        "thesis": thesis,
        "tags": tags,
        "market_conditions": market_conditions,
        "sector_conditions": sector_conditions,
        "stock_conditions": stock_conditions,
        "confirm_policy": confirm_policy,
        "giveup": giveup,
        "risk": risk,
        "sizing": sizing,
        "sizing_error": sizing_error,
        "proposed_by": proposed_by,
        "created_at": now,
        "expires_at": expires_at,
        "locked_at": locked_at,
        "late": late,
    }


def _entry_reference(
    conditions: Iterable[Mapping[str, Any]], latest_price: Optional[float]
) -> tuple[Optional[float], str]:
    for cond in conditions:
        if cond.get("type") == "price_in_range":
            return float(cond["lo"]), "价格区间下沿"
    for cond in conditions:
        if cond.get("type") == "price_cross":
            return float(cond["level"]), "价格穿越位"
    if latest_price is not None and latest_price > 0:
        return float(latest_price), "最新价"
    return None, "入场参考价缺失"


def _sizing_for(
    *,
    entry_ref: Optional[float],
    entry_source: str,
    stop: float,
    risk: Mapping[str, Any],
    settings: Any,
    overview: Optional[Mapping[str, Any]],
    regime: Optional[str],
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if settings is None:
        return None, "sizing_needs_settings"
    per_trade = risk.get("per_trade_risk_pct")
    if per_trade is None:
        per_trade = settings.value("per_trade_risk_pct")
    if per_trade is None:
        return None, "sizing_needs_per_trade_risk_pct"
    totals = (overview or {}).get("totals") if isinstance(overview, Mapping) else None
    total_assets = _amount((totals or {}).get("total_assets_cny"))
    if total_assets is None or total_assets <= 0:
        return None, "sizing_needs_portfolio"
    if entry_ref is None or entry_ref <= 0:
        return None, "sizing_needs_price"
    distance = (entry_ref - stop) / entry_ref * 100.0
    if distance <= 0:
        raise ApiError("bad_stop", "止损价必须低于入场参考价")
    if distance > 30.0:
        raise ApiError("bad_stop", "止损距离不得超过 30%")

    risk_budget = total_assets * float(per_trade) / 100.0
    raw_position = risk_budget / (distance / 100.0)
    capped_by = "risk_budget"
    final_position = raw_position
    notes = [f"入场参考价 {entry_ref:.2f}（{entry_source}）", f"止损距离 {distance:.2f}%"]

    single_cap = settings.value("single_stock_cap_pct")
    if single_cap is not None:
        cap_value = single_cap / 100.0 * total_assets
        if cap_value < final_position:
            final_position = cap_value
            capped_by = "single_stock_cap"
    headroom = _headroom_from(overview, settings, regime)
    total_room = headroom.get("total_room_pct")
    if total_room is not None:
        cap_value = total_room / 100.0 * total_assets
        if cap_value < final_position:
            final_position = cap_value
            capped_by = "total_cap"
    position_cap = risk.get("position_cap_pct")
    if position_cap is not None:
        cap_value = float(position_cap) / 100.0 * total_assets
        if cap_value < final_position:
            final_position = cap_value
            capped_by = "none"
            notes.append("受 position_cap_pct 限制")
    final_position = max(0.0, final_position)
    shares = math.floor(final_position / entry_ref / 100.0) * 100
    notes.append("按 100 股取整")
    return {
        "risk_budget_cny": round(risk_budget, 2),
        "stop_distance_pct": round(distance, 4),
        "raw_position_cny": round(raw_position, 2),
        "final_position_cny": round(final_position, 2),
        "final_qty_shares": int(shares),
        "capped_by": capped_by,
        "note": "；".join(notes),
    }, None


def _amount(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _headroom_from(overview, settings, regime) -> dict[str, Any]:
    from .discipline import headroom

    return headroom(overview or {}, settings, regime=regime) if settings is not None else {}


# -- actions -------------------------------------------------------------
def apply_action(
    card: Mapping[str, Any],
    payload: Any,
    *,
    now: datetime,
    calendar: TradingCalendar,
    settings: Any,
    overview: Optional[Mapping[str, Any]],
    regime: Optional[str],
    paused: bool,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, ACTION_FIELDS)
    action = payload.get("action")
    if action not in {"confirm", "cancel", "tighten_stop", "set_state"}:
        raise ApiError("invalid_action", "action 只接受 confirm/cancel/tighten_stop/set_state")
    locked = is_locked(card, now, calendar)
    if action == "confirm":
        if "stop" in payload or "state" in payload:
            raise ApiError("unexpected_field", "confirm 不接受 stop/state")
        if card["status"] != "proposed":
            raise ApiError("invalid_status", "只有 proposed 作战卡可以 confirm")
        fields: dict[str, Any] = {"status": "active"}
        return {
            "fields": fields,
            "warnings": ["paused"] if paused else [],
            "state_change": None,
        }
    if action == "cancel":
        if "stop" in payload or "state" in payload:
            raise ApiError("unexpected_field", "cancel 不接受 stop/state")
        if card["status"] not in {"proposed", "active"}:
            raise ApiError("invalid_status", "该状态的作战卡不能 cancel")
        return {"fields": {"status": "cancelled"}, "warnings": [], "state_change": None}
    if action == "tighten_stop":
        if "state" in payload:
            raise ApiError("unexpected_field", "tighten_stop 不接受 state")
        if card["status"] not in {"proposed", "active"}:
            raise ApiError("invalid_status", "该状态的作战卡不能修改止损")
        if card.get("expires_at") and now >= card["expires_at"]:
            raise ApiError("invalid_status", "已过期的作战卡不能修改止损")
        stop = number(payload.get("stop"), "stop")
        old_stop = float((card.get("risk") or {}).get("stop_price"))
        if stop <= old_stop:
            raise ApiError("loosen_not_allowed", "做多只能收紧止损，新止损价必须高于旧止损价")
        risk = dict(card.get("risk") or {})
        risk["stop_price"] = stop
        return {"fields": {"risk": risk}, "warnings": [], "state_change": None}
    # set_state
    if "stop" in payload:
        raise ApiError("unexpected_field", "set_state 不接受 stop")
    target = payload.get("state")
    if target not in CARD_STATES:
        raise ApiError("invalid_state", "state 只接受 observe/await_confirm/execute/abandon/exit")
    if card["status"] != "active":
        raise ApiError("invalid_status", "只有 active 作战卡可以 set_state")
    if locked and target not in {"abandon", "exit"}:
        raise ApiError("locked", "09:25 锁定后只允许降级为 abandon/exit")
    if target == card["state"]:
        return {"fields": {}, "warnings": [], "state_change": None}
    return {
        "fields": {"state": target},
        "warnings": [],
        "state_change": (card["state"], target, "用户手动调整状态"),
    }


# -- payload -------------------------------------------------------------
COND_GROUPS = ("market", "sector", "stock", "giveup")


def empty_conds() -> dict[str, list[Optional[bool]]]:
    return {key: [] for key in COND_GROUPS}


def normalize_conds(raw: Any) -> dict[str, list[Optional[bool]]]:
    """Keep only true/false/null per group; unknown input degrades to empty."""
    if not isinstance(raw, Mapping):
        return empty_conds()
    result = empty_conds()
    for key in COND_GROUPS:
        values = raw.get(key)
        if not isinstance(values, list):
            continue
        result[key] = [
            value if isinstance(value, bool) or value is None else None
            for value in values
        ]
    return result


def normalize_engine(raw: Any, *, default_ok: bool = True) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {"ok": default_ok, "error": None, "synced_at": None}
    error = raw.get("error")
    synced = raw.get("synced_at")
    return {
        "ok": bool(raw.get("ok", default_ok)),
        "error": str(error) if error else None,
        "synced_at": synced if isinstance(synced, str) else None,
    }


def card_payload(card: Mapping[str, Any], history: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    rows = history if history is not None else []
    return {
        "id": card["id"],
        "code": card["code"],
        "name": card["name"],
        "status": card["status"],
        "state": card["state"],
        "review_date": card.get("review_date"),
        "thesis": card.get("thesis", ""),
        "tags": card.get("tags") or {},
        "market_conditions": card.get("market_conditions") or [],
        "sector_conditions": card.get("sector_conditions") or [],
        "stock_conditions": card.get("stock_conditions") or [],
        "confirm_policy": card.get("confirm_policy") or "all",
        "giveup": card.get("giveup") or [],
        "risk": card.get("risk") or {},
        "sizing": card.get("sizing"),
        "proposed_by": card.get("proposed_by"),
        "created_at": fmt_iso(card.get("created_at")),
        "expires_at": fmt_iso(card.get("expires_at")),
        "locked_at": fmt_iso(card.get("locked_at")) if card.get("locked_at") else None,
        "late": bool(card.get("late")),
        "history": [
            {
                "ts": fmt_iso(item.get("ts")),
                "from": item.get("from"),
                "to": item.get("to"),
                "reason": item.get("reason"),
            }
            for item in rows
        ],
        "judgement": card.get("judgement"),
        "last_price": card.get("last_price"),
        "outcome": card.get("outcome"),
        "conds": normalize_conds(card.get("conds")),
        "engine": normalize_engine(card.get("engine")),
    }
