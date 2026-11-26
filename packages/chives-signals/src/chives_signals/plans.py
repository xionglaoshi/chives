"""Plan creation, validation, transitions and condition evaluation helpers."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from .calendar import TradingCalendar
from .models import CN_TZ, Plan, fmt_iso, parse_iso, truncate
from .portfolio_view import ensure_portfolio_path

PLAN_KINDS = {"entry", "giveup", "watch", "exit"}
PLAN_STATUSES = {"proposed", "active", "triggered", "expired", "cancelled"}
CREATE_FIELDS = {
    "code",
    "name",
    "kind",
    "condition",
    "stop",
    "rationale",
    "source",
    "proposed_by",
    "expires_at",
}
ACTION_FIELDS = {"action", "expires_at"}
DEFAULT_EXPIRY_TRADING_DAYS = 5


class PlanError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _text(value: Any, field: str, max_chars: int, *, allow_empty: bool = False) -> str:
    ensure_portfolio_path()
    from portfolio_mcp.errors import PortfolioError
    from portfolio_mcp.sanitize import clean_free_text

    try:
        return clean_free_text(value, field=field, max_chars=max_chars, allow_empty=allow_empty)
    except PortfolioError as exc:
        raise PlanError(exc.code, str(exc)) from exc


def _number(value: Any, field: str, *, positive: bool = True, maximum: Optional[float] = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError("invalid_value", f"{field} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise PlanError("invalid_value", f"{field} 必须是有限数字")
    if positive and number <= 0:
        raise PlanError("invalid_value", f"{field} 必须为正数")
    if maximum is not None and number > maximum:
        raise PlanError("invalid_value", f"{field} 不得大于 {maximum}")
    return number


def _only(payload: Mapping[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        raise PlanError("unexpected_field", "不支持的字段: " + ", ".join(extra))


def normalize_code(raw: Any) -> str:
    ensure_portfolio_path()
    from portfolio_mcp.errors import PortfolioError
    from portfolio_mcp.symbols import normalize_symbol

    if not isinstance(raw, str) or not raw.strip():
        raise PlanError("invalid_code", "code 必须是非空字符串")
    try:
        return normalize_symbol(raw).canonical
    except PortfolioError as exc:
        raise PlanError("invalid_code", str(exc)) from exc


def validate_condition(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanError("invalid_condition", "condition 必须是对象")
    cond_type = raw.get("type")
    if cond_type == "price_cross":
        _only(raw, {"type", "direction", "level"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise PlanError("invalid_condition", "price_cross.direction 只接受 up/down")
        return {
            "type": "price_cross",
            "direction": direction,
            "level": _number(raw.get("level"), "condition.level"),
        }
    if cond_type == "price_in_range":
        _only(raw, {"type", "lo", "hi"})
        lo = _number(raw.get("lo"), "condition.lo")
        hi = _number(raw.get("hi"), "condition.hi")
        if lo >= hi:
            raise PlanError("invalid_condition", "price_in_range 要求 lo < hi")
        return {"type": "price_in_range", "lo": lo, "hi": hi}
    if cond_type == "pct_change":
        _only(raw, {"type", "direction", "threshold_pct"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise PlanError("invalid_condition", "pct_change.direction 只接受 up/down")
        return {
            "type": "pct_change",
            "direction": direction,
            "threshold_pct": _number(
                raw.get("threshold_pct"), "condition.threshold_pct", maximum=100.0
            ),
        }
    raise PlanError("invalid_condition", "condition.type 只接受 price_cross/price_in_range/pct_change")


def _validate_source(raw: Any, *, default_label: str = "user") -> dict[str, Any]:
    if raw is None:
        return {"analysis_id": None, "label": default_label}
    if not isinstance(raw, dict):
        raise PlanError("invalid_source", "source 必须是对象")
    _only(raw, {"analysis_id", "label"})
    analysis_id = raw.get("analysis_id")
    if analysis_id is not None:
        if isinstance(analysis_id, bool) or not isinstance(analysis_id, int) or analysis_id < 0:
            raise PlanError("invalid_source", "source.analysis_id 必须是非负整数或 null")
    label = _text(raw.get("label", default_label), "source.label", 40, allow_empty=True) or default_label
    return {"analysis_id": analysis_id, "label": label}


def validate_expires_at(
    raw: Any,
    *,
    now: datetime,
    calendar: TradingCalendar,
    max_days: int,
) -> datetime:
    if raw is None:
        day = calendar.add_trading_days(now.date(), DEFAULT_EXPIRY_TRADING_DAYS)
        expires = calendar.close_at(day)
        if expires <= now:
            expires = calendar.close_at(calendar.next_trading_day(day))
        return expires
    if not isinstance(raw, str) or not raw.strip():
        raise PlanError("invalid_expiry", "expires_at 必须是 ISO8601 字符串")
    text = raw.strip()
    try:
        if len(text) == 10:
            from datetime import date

            expires = calendar.close_at(date.fromisoformat(text))
        else:
            expires = parse_iso(text)
    except ValueError as exc:
        raise PlanError("invalid_expiry", "expires_at 必须是带时区的 ISO8601 时间") from exc
    now_cn = now.astimezone(CN_TZ)
    if expires <= now_cn:
        raise PlanError("invalid_expiry", "expires_at 必须晚于当前时间")
    if expires - now_cn > timedelta(days=max_days):
        raise PlanError("invalid_expiry", f"有效期不得超过 {max_days} 天")
    return expires


def create_plan(
    payload: Any,
    *,
    now: datetime,
    calendar: TradingCalendar,
    max_active_plans: int,
    max_plan_days: int,
    active_count: int,
    name_resolver: Optional[Any] = None,
) -> Plan:
    if not isinstance(payload, dict):
        raise PlanError("invalid_body", "请求体必须是 JSON 对象")
    _only(payload, CREATE_FIELDS)
    code = normalize_code(payload.get("code"))
    kind = payload.get("kind")
    if kind not in PLAN_KINDS:
        raise PlanError("invalid_kind", "kind 只接受 entry/giveup/watch/exit")
    condition = validate_condition(payload.get("condition"))
    stop_raw = payload.get("stop")
    stop = None if stop_raw is None else _number(stop_raw, "stop")
    rationale = _text(payload.get("rationale", ""), "rationale", 200, allow_empty=True)
    proposed_by = payload.get("proposed_by")
    if proposed_by not in {"agent", "user"}:
        raise PlanError("invalid_proposed_by", "proposed_by 只接受 agent/user")
    source = _validate_source(payload.get("source"), default_label=proposed_by)
    expires_at = validate_expires_at(
        payload.get("expires_at"), now=now, calendar=calendar, max_days=max_plan_days
    )
    if proposed_by == "user" and active_count >= max_active_plans:
        raise PlanError(
            "plan_limit",
            f"活跃计划最多 {max_active_plans} 个",
            status=200,
        )

    name = ""
    if payload.get("name") is not None:
        name = _text(payload.get("name"), "name", 20)
    if not name and name_resolver is not None:
        try:
            name = str(name_resolver(code) or "")
        except Exception:  # noqa: BLE001 - name resolution must never block plan creation
            name = ""
    name = truncate(name or code, 20)

    status = "active" if proposed_by == "user" else "proposed"
    return Plan(
        id=None,
        code=code,
        name=name,
        kind=str(kind),
        status=status,
        condition=condition,
        stop=stop,
        rationale=rationale,
        source=source,
        proposed_by=proposed_by,
        created_at=now,
        expires_at=expires_at,
        updated_at=now,
    )


def apply_action(
    plan: Plan,
    payload: Any,
    *,
    now: datetime,
    calendar: TradingCalendar,
    max_plan_days: int,
) -> dict[str, Any]:
    """Return a dict of fields to persist; raises PlanError on invalid transitions."""
    if not isinstance(payload, dict):
        raise PlanError("invalid_body", "请求体必须是 JSON 对象")
    _only(payload, ACTION_FIELDS)
    action = payload.get("action")
    if action not in {"confirm", "cancel", "extend"}:
        raise PlanError("invalid_action", "action 只接受 confirm/cancel/extend")
    if action != "extend" and "expires_at" in payload:
        raise PlanError("unexpected_field", "只有 extend 接受 expires_at")
    if action == "confirm":
        if plan.status != "proposed":
            raise PlanError("invalid_status", "只有 proposed 计划可以 confirm", status=200)
        return {"status": "active"}
    if action == "cancel":
        if plan.status == "cancelled":
            return {"status": "cancelled"}
        if plan.status not in {"proposed", "active", "triggered"}:
            raise PlanError("invalid_status", "该状态的计划不能 cancel", status=200)
        return {"status": "cancelled"}
    if "expires_at" not in payload or payload.get("expires_at") is None:
        raise PlanError("invalid_expiry", "extend 必须提供 expires_at")
    expires_at = validate_expires_at(
        payload.get("expires_at"), now=now, calendar=calendar, max_days=max_plan_days
    )
    if plan.status == "proposed":
        return {"status": "proposed", "expires_at": expires_at}
    if plan.status == "cancelled":
        raise PlanError("invalid_status", "已取消的计划不能 extend", status=200)
    return {"status": "active", "expires_at": expires_at, "clear_triggered": True}


def condition_met(
    condition: Mapping[str, Any],
    *,
    price: Optional[float],
    change_pct: Optional[float],
) -> bool:
    cond_type = condition.get("type")
    if cond_type == "price_cross":
        if price is None:
            return False
        level = float(condition["level"])
        return price >= level if condition.get("direction") == "up" else price <= level
    if cond_type == "price_in_range":
        if price is None:
            return False
        return float(condition["lo"]) <= price <= float(condition["hi"])
    if cond_type == "pct_change":
        if change_pct is None:
            return False
        threshold = float(condition["threshold_pct"])
        return change_pct >= threshold if condition.get("direction") == "up" else change_pct <= -threshold
    return False


def trigger_kind(plan_kind: str) -> str:
    if plan_kind == "giveup":
        return "plan_giveup"
    if plan_kind in {"watch", "exit"}:
        return "plan_other"
    return "plan_entry"


def condition_text(condition: Mapping[str, Any]) -> str:
    if condition.get("type") == "price_cross":
        return f"价格{'上穿' if condition.get('direction') == 'up' else '下穿'} {condition.get('level')}"
    if condition.get("type") == "price_in_range":
        return f"价格落在 {condition.get('lo')}–{condition.get('hi')}"
    return f"涨跌幅{'≥' if condition.get('direction') == 'up' else '≤-'}{condition.get('threshold_pct')}%"


def plan_expiry_note(plan: Plan) -> str:
    return f"计划有效期至 {fmt_iso(plan.expires_at)}"
