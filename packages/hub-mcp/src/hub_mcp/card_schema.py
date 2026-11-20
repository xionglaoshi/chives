"""Local validation for ``hub_propose_card``.

The agent can only *propose* a playbook card: ``proposed_by`` is fixed to
``agent`` and there is no status field.  Condition types, counts and the stop
distance rule mirror the hub's own card validation so a bad card is rejected
before any HTTP request.
"""

from __future__ import annotations

import math
import re
from typing import Any

from hub_mcp.errors import ToolError
from hub_mcp.validation import (
    clean_free_text,
    normalize_code,
    only_fields,
    safe_date,
)

CARD_FIELDS = {
    "code",
    "review_date",
    "thesis",
    "tags",
    "market_conditions",
    "sector_conditions",
    "stock_conditions",
    "confirm_policy",
    "giveup",
    "risk",
}
TAG_FIELDS = {"streak", "theme", "env"}
RISK_FIELDS = {"stop_price", "per_trade_risk_pct", "position_cap_pct", "exit_rules"}
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
MAX_THESIS = 200
ENV_LABELS = {"strong", "neutral", "weak"}
PROPOSED_MESSAGE = "已提交作战卡建议，等待用户在「复盘」页确认后才生效"


def _condition_error(message: str) -> ToolError:
    return ToolError("bad_condition", message, field="conditions")


def _only(raw: dict[str, Any], allowed: set[str]) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise _condition_error("condition 不支持的字段: " + ", ".join(extra))


def _number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _condition_error(f"{name} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise _condition_error(f"{name} 必须是有限数字")
    if minimum is not None and number < minimum:
        raise _condition_error(f"{name} 不得小于 {minimum:g}")
    if maximum is not None and number > maximum:
        raise _condition_error(f"{name} 不得大于 {maximum:g}")
    return number


def _op(value: Any) -> str:
    if value not in {">=", "<="}:
        raise _condition_error("op 只接受 >= 或 <=")
    return str(value)


def _sector(value: Any) -> str:
    if not isinstance(value, str) or not SECTOR_CODE_RE.match(value.strip()):
        raise _condition_error("sector_code 必须形如 BK0433")
    return value.strip()


def validate_condition(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _condition_error("condition 必须是对象")
    cond_type = raw.get("type")
    if cond_type not in CONDITION_TYPES:
        raise ToolError(
            "bad_condition",
            "condition.type 只接受 regime/index_pct/sector_change/sector_rank/"
            "price_cross/price_in_range/pct_change/open_pct/volume_ratio",
            field="conditions",
        )
    if cond_type == "regime":
        _only(raw, {"type", "values"})
        values = raw.get("values")
        if not isinstance(values, list) or not values:
            raise _condition_error("regime.values 必须是非空数组")
        clean = []
        for value in values:
            if value not in ENV_LABELS:
                raise _condition_error("regime.values 只接受 strong/neutral/weak")
            clean.append(value)
        return {"type": "regime", "values": clean}
    if cond_type == "index_pct":
        _only(raw, {"type", "code", "op", "value"})
        code = raw.get("code")
        if code not in INDEX_CODES:
            raise _condition_error("index_pct.code 不在允许的 6 个指数内")
        return {
            "type": "index_pct",
            "code": code,
            "op": _op(raw.get("op")),
            "value": _number(raw.get("value"), "value"),
        }
    if cond_type == "sector_change":
        _only(raw, {"type", "sector_code", "op", "value"})
        return {
            "type": "sector_change",
            "sector_code": _sector(raw.get("sector_code")),
            "op": _op(raw.get("op")),
            "value": _number(raw.get("value"), "value"),
        }
    if cond_type == "sector_rank":
        _only(raw, {"type", "sector_code", "op", "value"})
        return {
            "type": "sector_rank",
            "sector_code": _sector(raw.get("sector_code")),
            "op": _op(raw.get("op")),
            "value": _number(raw.get("value"), "value", minimum=1),
        }
    if cond_type == "price_cross":
        _only(raw, {"type", "direction", "level"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise _condition_error("price_cross.direction 只接受 up/down")
        level = _number(raw.get("level"), "level")
        if level <= 0:
            raise _condition_error("price_cross.level 必须为正数")
        return {"type": "price_cross", "direction": direction, "level": level}
    if cond_type == "price_in_range":
        _only(raw, {"type", "lo", "hi"})
        lo = _number(raw.get("lo"), "lo")
        hi = _number(raw.get("hi"), "hi")
        if lo <= 0 or hi <= 0:
            raise _condition_error("price_in_range 价位必须为正数")
        if lo >= hi:
            raise _condition_error("price_in_range 要求 lo < hi")
        return {"type": "price_in_range", "lo": lo, "hi": hi}
    if cond_type == "pct_change":
        _only(raw, {"type", "direction", "threshold_pct"})
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise _condition_error("pct_change.direction 只接受 up/down")
        return {
            "type": "pct_change",
            "direction": direction,
            "threshold_pct": _number(raw.get("threshold_pct"), "threshold_pct", maximum=100),
        }
    if cond_type == "open_pct":
        _only(raw, {"type", "op", "value"})
        return {
            "type": "open_pct",
            "op": _op(raw.get("op")),
            "value": _number(raw.get("value"), "value", minimum=-100, maximum=100),
        }
    _only(raw, {"type", "op", "value"})
    value = _number(raw.get("value"), "value")
    if value <= 0:
        raise _condition_error("volume_ratio.value 必须为正数")
    return {"type": "volume_ratio", "op": _op(raw.get("op")), "value": value}


def validate_conditions(raw: Any, field: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _condition_error(f"{field} 必须是数组")
    if len(raw) > MAX_CONDITIONS:
        raise ToolError(
            "too_many_conditions", f"{field} 最多 {MAX_CONDITIONS} 条", field="conditions"
        )
    return [validate_condition(item) for item in raw]


def _card_code(value: Any) -> str:
    code = normalize_code(value)
    if code.endswith(".BJ"):
        raise ToolError("invalid_code", "作战卡仅支持沪深 A 股，不含北交所", field="code")
    return code


def _thesis(value: Any) -> str:
    return clean_free_text(value, "thesis", MAX_THESIS, allow_empty=True)


def _tags(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ToolError("invalid_tags", "tags 必须是对象", field="tags")
    only_fields(raw, TAG_FIELDS, field="tags")
    tags: dict[str, Any] = {}
    if raw.get("streak") is not None:
        streak = raw.get("streak")
        if isinstance(streak, bool) or not isinstance(streak, int) or not 0 <= streak <= 100:
            raise ToolError("invalid_tags", "tags.streak 必须是 0..100 的整数", field="tags")
        tags["streak"] = streak
    if raw.get("theme") is not None:
        tags["theme"] = clean_free_text(raw.get("theme"), "tags.theme", 40, allow_empty=True)
    if raw.get("env") is not None:
        if raw.get("env") not in ENV_LABELS:
            raise ToolError("invalid_tags", "tags.env 只接受 strong/neutral/weak", field="tags")
        tags["env"] = raw["env"]
    return tags


def _risk(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ToolError("invalid_risk", "risk 必须是对象（至少含 stop_price）", field="risk")
    only_fields(raw, RISK_FIELDS, field="risk")
    stop = raw.get("stop_price")
    if isinstance(stop, bool) or not isinstance(stop, (int, float)) or not math.isfinite(float(stop)):
        raise ToolError("invalid_risk", "risk.stop_price 必须是有限数字", field="risk")
    stop = float(stop)
    if stop <= 0:
        raise ToolError("invalid_risk", "risk.stop_price 必须为正数", field="risk")
    per_trade = raw.get("per_trade_risk_pct")
    if per_trade is not None:
        if isinstance(per_trade, bool) or not isinstance(per_trade, (int, float)) or not 0 <= float(per_trade) <= 10:
            raise ToolError("invalid_risk", "risk.per_trade_risk_pct 必须在 0..10", field="risk")
        per_trade = float(per_trade)
    position_cap = raw.get("position_cap_pct")
    if position_cap is not None:
        if (
            isinstance(position_cap, bool)
            or not isinstance(position_cap, (int, float))
            or not 0 <= float(position_cap) <= 100
        ):
            raise ToolError("invalid_risk", "risk.position_cap_pct 必须在 0..100", field="risk")
        position_cap = float(position_cap)
    exit_rules: list[str] = []
    if raw.get("exit_rules") is not None:
        if not isinstance(raw.get("exit_rules"), list):
            raise ToolError("invalid_risk", "risk.exit_rules 必须是数组", field="risk")
        if len(raw["exit_rules"]) > 3:
            raise ToolError("invalid_risk", "risk.exit_rules 最多 3 条", field="risk")
        exit_rules = [
            clean_free_text(item, "risk.exit_rules", 80) for item in raw["exit_rules"]
        ]
    return {
        "stop_price": stop,
        "per_trade_risk_pct": per_trade,
        "position_cap_pct": position_cap,
        "exit_rules": exit_rules,
    }


def entry_reference(conditions: list[dict[str, Any]]) -> float | None:
    """Same order as the hub: range lower edge, then cross level, else none."""
    for cond in conditions:
        if cond.get("type") == "price_in_range":
            return float(cond["lo"])
    for cond in conditions:
        if cond.get("type") == "price_cross":
            return float(cond["level"])
    return None


def _check_stop(stop: float, ref: float | None) -> None:
    if ref is None or ref <= 0:
        return
    distance = (ref - stop) / ref * 100.0
    if distance <= 0:
        raise ToolError("bad_stop", "止损价必须低于入场参考价", field="risk")
    if distance > 30.0:
        raise ToolError("bad_stop", "止损距离不得超过 30%", field="risk")


def validate_card(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ToolError("invalid_body", "card 必须是 JSON 对象", field="card")
    # Control fields a caller might forge are dropped, never forwarded: the body
    # below is built explicitly and proposed_by is always "agent".
    ignored = {"proposed_by", "status"}
    extra = sorted(set(payload) - CARD_FIELDS - ignored)
    if extra:
        raise ToolError("unexpected_field", "card 不支持的字段: " + ", ".join(extra), field="card")
    code = _card_code(payload.get("code"))
    thesis = _thesis(payload.get("thesis", ""))
    market = validate_conditions(payload.get("market_conditions"), "market_conditions")
    sector = validate_conditions(payload.get("sector_conditions"), "sector_conditions")
    stock = validate_conditions(payload.get("stock_conditions"), "stock_conditions")
    giveup = validate_conditions(payload.get("giveup"), "giveup")
    policy = payload.get("confirm_policy") or "all"
    if policy not in {"all", "any"}:
        raise ToolError("invalid_confirm_policy", "confirm_policy 只接受 all/any", field="confirm_policy")
    risk = _risk(payload.get("risk"))
    _check_stop(risk["stop_price"], entry_reference(stock))
    review_date = None
    if payload.get("review_date") is not None:
        review_date = safe_date(payload.get("review_date"), "review_date")
    return {
        "code": code,
        "review_date": review_date,
        "thesis": thesis,
        "tags": _tags(payload.get("tags")),
        "market_conditions": market,
        "sector_conditions": sector,
        "stock_conditions": stock,
        "confirm_policy": policy,
        "giveup": giveup,
        "risk": risk,
    }
