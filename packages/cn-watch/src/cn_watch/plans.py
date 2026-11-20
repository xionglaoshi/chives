"""Plan rules: strict schema, deterministic state machine and persistence.

A plan is a named group of market/sector/stock conditions plus a give-up group.
It is evaluated once per watch polling cycle against the quotes the engine has
already fetched, so it never issues market-data requests of its own.  The state
machine has priority ``expired > giveup > exit > execute > await_confirm >
observe``, treats unknown inputs as neither true nor a give-up hit, needs three
consecutive evaluations before stepping down from ``execute``/``await_confirm``
or leaving ``abandon``/``exit``, and suppresses repeated alerts for the same
``(plan, to_state)`` within five minutes.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping, Optional

from .config import ConfigError, SymbolError, normalize_watch_code
from .models import CN_TZ, Quote, fmt_iso, parse_iso, to_cn

logger = logging.getLogger("cn_watch.plans")

PLANS_FILE_NAME = "plans.runtime.json"
RUNTIME_TMP_SUFFIX = ".tmp"
PLAN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
SECTOR_CODE_RE = re.compile(r"^BK[0-9]{4}$")
MAX_CONDITIONS = 6
MAX_PLANS = 30
MAX_LABEL = 40
MAX_HISTORY = 30
HYSTERESIS_EVALUATIONS = 3
ALERT_DEBOUNCE_SECONDS = 300.0
PLAN_STATES = ("observe", "await_confirm", "execute", "abandon", "exit", "expired")
ALERT_STATES = {"execute", "abandon", "exit", "await_confirm"}
TERMINAL_STATES = {"abandon", "exit"}
INDEX_CODES = {
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000300.SH",
    "000852.SH",
    "000688.SH",
}
REGIMES = ("strong", "neutral", "weak")
PLAN_FIELDS = {
    "id",
    "code",
    "market",
    "sector",
    "stock",
    "policy",
    "giveup",
    "stop_price",
    "held",
    "expires_at",
    "label",
}
COND_FIELDS = {
    "regime": {"type", "values"},
    "index_pct": {"type", "code", "op", "value"},
    "sector_change": {"type", "sector_code", "op", "value"},
    "sector_rank": {"type", "sector_code", "op", "value"},
    "price_cross": {"type", "direction", "level"},
    "price_in_range": {"type", "lo", "hi"},
    "pct_change": {"type", "direction", "threshold_pct"},
    "open_pct": {"type", "op", "value"},
    "volume_ratio": {"type", "op", "value"},
}
OPEN_PCT_TIME = time(9, 25)


class PlanError(Exception):
    """A plan request was rejected with a stable code and an optional field."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.status_code = status_code or {
            "not_found": 404,
            "persistence_error": 500,
        }.get(code, 400)


@dataclass(frozen=True)
class Plan:
    id: str
    code: str
    market: tuple[dict[str, Any], ...] = ()
    sector: tuple[dict[str, Any], ...] = ()
    stock: tuple[dict[str, Any], ...] = ()
    policy: str = "all"
    giveup: tuple[dict[str, Any], ...] = ()
    stop_price: Optional[float] = None
    held: bool = False
    expires_at: Optional[datetime] = None
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "market": [dict(item) for item in self.market],
            "sector": [dict(item) for item in self.sector],
            "stock": [dict(item) for item in self.stock],
            "policy": self.policy,
            "giveup": [dict(item) for item in self.giveup],
            "stop_price": self.stop_price,
            "held": self.held,
            "expires_at": fmt_iso(self.expires_at) if self.expires_at else None,
            "label": self.label,
        }


@dataclass
class PlanRuntime:
    plan: Plan
    state: str = "observe"
    since: datetime = None  # type: ignore[assignment]
    history: list[dict[str, Any]] = field(default_factory=list)
    conds: dict[str, list[Optional[bool]]] = field(default_factory=dict)
    last_price: Optional[float] = None
    active: bool = True
    expired_at: Optional[datetime] = None
    last_alert_ts: dict[str, datetime] = field(default_factory=dict)
    streak: int = 0
    pending: Optional[str] = None
    alert_seq: int = 0
    restored: bool = False

    def clone(self) -> "PlanRuntime":
        return PlanRuntime(
            plan=self.plan,
            state=self.state,
            since=self.since,
            history=[dict(item) for item in self.history],
            conds={key: list(value) for key, value in self.conds.items()},
            last_price=self.last_price,
            active=self.active,
            expired_at=self.expired_at,
            last_alert_ts=dict(self.last_alert_ts),
            streak=self.streak,
            pending=self.pending,
            alert_seq=self.alert_seq,
            restored=self.restored,
        )


@dataclass
class PlansState:
    plans: list[PlanRuntime] = field(default_factory=list)
    auto_codes: set[str] = field(default_factory=set)
    load_error: Optional[str] = None


# -- validation ----------------------------------------------------------
def _only(raw: Mapping[str, Any], allowed: set[str], code: str, field_name: str) -> None:
    extra = sorted(set(raw) - allowed)
    if extra:
        raise PlanError(code, f"不支持的字段: {extra[0]}", field=f"{field_name}.{extra[0]}")


def _number(
    value: Any,
    field_name: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    exclusive_minimum: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError("invalid_condition", f"{field_name} 必须是数字", field=field_name)
    number = float(value)
    if not math.isfinite(number):
        raise PlanError("invalid_condition", f"{field_name} 必须是有限数字", field=field_name)
    if minimum is not None:
        too_low = number <= minimum if exclusive_minimum else number < minimum
        if too_low:
            raise PlanError("invalid_condition", f"{field_name} 超出范围", field=field_name)
    if maximum is not None and number > maximum:
        raise PlanError("invalid_condition", f"{field_name} 超出范围", field=field_name)
    return number


def _op(value: Any, allowed: set[str], field_name: str) -> str:
    if value not in allowed:
        raise PlanError("invalid_condition", f"{field_name} 不合法", field=field_name)
    return str(value)


def _sector_code(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not SECTOR_CODE_RE.fullmatch(value.strip()):
        raise PlanError(
            "invalid_condition", f"{field_name} 必须形如 BK0433", field=field_name
        )
    return value.strip()


def validate_condition(raw: Any, field_name: str = "condition") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanError("invalid_condition", "条件必须是对象", field=field_name)
    cond_type = raw.get("type")
    if not isinstance(cond_type, str) or cond_type not in COND_FIELDS:
        raise PlanError("invalid_condition", "未知的条件类型", field=f"{field_name}.type")
    _only(raw, COND_FIELDS[cond_type], "invalid_condition", field_name)

    if cond_type == "regime":
        values = raw.get("values")
        if not isinstance(values, list) or not values:
            raise PlanError(
                "invalid_condition", "regime.values 必须是非空数组", field=f"{field_name}.values"
            )
        cleaned: list[str] = []
        for value in values:
            if value not in REGIMES:
                raise PlanError(
                    "invalid_condition",
                    "regime.values 只接受 strong/neutral/weak",
                    field=f"{field_name}.values",
                )
            if value in cleaned:
                raise PlanError(
                    "invalid_condition", "regime.values 不能重复", field=f"{field_name}.values"
                )
            cleaned.append(value)
        return {"type": "regime", "values": cleaned}

    if cond_type == "index_pct":
        code = raw.get("code")
        if code not in INDEX_CODES:
            raise PlanError(
                "invalid_condition", "index_pct.code 不在允许的指数内", field=f"{field_name}.code"
            )
        return {
            "type": "index_pct",
            "code": code,
            "op": _op(raw.get("op"), {">=", "<="}, f"{field_name}.op"),
            "value": _number(raw.get("value"), f"{field_name}.value", minimum=-100, maximum=100),
        }

    if cond_type == "sector_change":
        return {
            "type": "sector_change",
            "sector_code": _sector_code(raw.get("sector_code"), f"{field_name}.sector_code"),
            "op": _op(raw.get("op"), {">=", "<="}, f"{field_name}.op"),
            "value": _number(raw.get("value"), f"{field_name}.value", minimum=-100, maximum=100),
        }

    if cond_type == "sector_rank":
        return {
            "type": "sector_rank",
            "sector_code": _sector_code(raw.get("sector_code"), f"{field_name}.sector_code"),
            "op": _op(raw.get("op"), {"<=", ">="}, f"{field_name}.op"),
            "value": _number(raw.get("value"), f"{field_name}.value", minimum=1, maximum=1000),
        }

    if cond_type == "price_cross":
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise PlanError(
                "invalid_condition",
                "price_cross.direction 只接受 up/down",
                field=f"{field_name}.direction",
            )
        level = _number(
            raw.get("level"), f"{field_name}.level", minimum=0, exclusive_minimum=True
        )
        return {"type": "price_cross", "direction": direction, "level": level}

    if cond_type == "price_in_range":
        lo = _number(raw.get("lo"), f"{field_name}.lo", minimum=0, exclusive_minimum=True)
        hi = _number(raw.get("hi"), f"{field_name}.hi", minimum=0, exclusive_minimum=True)
        if lo >= hi:
            raise PlanError(
                "invalid_condition", "price_in_range 要求 lo < hi", field=f"{field_name}.lo"
            )
        return {"type": "price_in_range", "lo": lo, "hi": hi}

    if cond_type == "pct_change":
        direction = raw.get("direction")
        if direction not in {"up", "down"}:
            raise PlanError(
                "invalid_condition",
                "pct_change.direction 只接受 up/down",
                field=f"{field_name}.direction",
            )
        threshold = _number(
            raw.get("threshold_pct"),
            f"{field_name}.threshold_pct",
            minimum=0,
            maximum=100,
            exclusive_minimum=True,
        )
        return {
            "type": "pct_change",
            "direction": direction,
            "threshold_pct": threshold,
        }

    if cond_type == "open_pct":
        return {
            "type": "open_pct",
            "op": _op(raw.get("op"), {">=", "<="}, f"{field_name}.op"),
            "value": _number(raw.get("value"), f"{field_name}.value", minimum=-100, maximum=100),
        }

    return {
        "type": "volume_ratio",
        "op": _op(raw.get("op"), {">=", "<="}, f"{field_name}.op"),
        "value": _number(
            raw.get("value"),
            f"{field_name}.value",
            minimum=0,
            maximum=1000,
            exclusive_minimum=True,
        ),
    }


def validate_conditions(raw: Any, field_name: str) -> tuple[dict[str, Any], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise PlanError("invalid_plan", f"{field_name} 必须是数组", field=field_name)
    if len(raw) > MAX_CONDITIONS:
        raise PlanError(
            "too_many_conditions",
            f"{field_name} 最多 {MAX_CONDITIONS} 条",
            field=field_name,
        )
    return tuple(
        validate_condition(item, f"{field_name}[{index}]")
        for index, item in enumerate(raw)
    )


def validate_plan_payload(raw: Any) -> Plan:
    """Validate one complete plan object without touching engine state."""
    if not isinstance(raw, dict):
        raise PlanError("invalid_plan", "计划必须是 JSON 对象")
    _only(raw, PLAN_FIELDS, "invalid_plan", "plan")

    plan_id = raw.get("id")
    if not isinstance(plan_id, str) or not PLAN_ID_RE.fullmatch(plan_id):
        raise PlanError(
            "invalid_plan",
            "id 只能由 1~40 个字母、数字、下划线或连字符组成",
            field="id",
        )

    try:
        code = normalize_watch_code(raw.get("code"))
    except SymbolError as exc:
        raise PlanError("invalid_symbol", str(exc), field="code") from exc
    except ConfigError as exc:
        raise PlanError("invalid_symbol", str(exc), field="code") from exc
    if code.split(".")[0].startswith(("4", "8")):
        raise PlanError("invalid_symbol", "计划不支持北交所代码", field="code")

    market = validate_conditions(raw.get("market"), "market")
    sector = validate_conditions(raw.get("sector"), "sector")
    stock = validate_conditions(raw.get("stock"), "stock")
    giveup = validate_conditions(raw.get("giveup"), "giveup")

    policy = raw.get("policy", "all")
    if policy not in {"all", "any"}:
        raise PlanError("invalid_plan", "policy 只接受 all/any", field="policy")

    stop_price = raw.get("stop_price")
    if stop_price is not None:
        if isinstance(stop_price, bool) or not isinstance(stop_price, (int, float)):
            raise PlanError("invalid_plan", "stop_price 必须是正数或 null", field="stop_price")
        stop_price = float(stop_price)
        if not math.isfinite(stop_price) or stop_price <= 0:
            raise PlanError("invalid_plan", "stop_price 必须是正数或 null", field="stop_price")

    held = raw.get("held", False)
    if not isinstance(held, bool):
        raise PlanError("invalid_plan", "held 必须是布尔值", field="held")

    expires_at = raw.get("expires_at")
    if expires_at is not None:
        try:
            expires_at = parse_iso(expires_at)
        except (TypeError, ValueError) as exc:
            raise PlanError(
                "invalid_plan",
                "expires_at 必须是带时区的 ISO8601 时间",
                field="expires_at",
            ) from exc

    label = raw.get("label", "")
    if not isinstance(label, str):
        raise PlanError("invalid_plan", "label 必须是字符串", field="label")
    label = label.strip()
    if len(label) > MAX_LABEL:
        raise PlanError(
            "invalid_plan", f"label 最多 {MAX_LABEL} 个字符", field="label"
        )

    return Plan(
        id=plan_id,
        code=code,
        market=market,
        sector=sector,
        stock=stock,
        policy=policy,
        giveup=giveup,
        stop_price=stop_price,
        held=held,
        expires_at=expires_at,
        label=label,
    )


# -- evaluation ----------------------------------------------------------
@dataclass(frozen=True)
class EvalContext:
    now: datetime
    quote: Optional[Quote] = None
    regime: Optional[str] = None
    indexes: Mapping[str, float] = field(default_factory=dict)
    sectors: Mapping[str, Mapping[str, Optional[float]]] = field(default_factory=dict)


def _compare(value: float, op: str, threshold: float) -> bool:
    return value >= threshold if op == ">=" else value <= threshold


def _quote_change_pct(quote: Quote) -> Optional[float]:
    if quote.prev_close <= 0:
        return None
    return (quote.price / quote.prev_close - 1.0) * 100.0


def eval_condition(cond: Mapping[str, Any], context: EvalContext) -> Optional[bool]:
    cond_type = cond.get("type")
    if cond_type == "regime":
        if context.regime is None:
            return None
        return context.regime in cond["values"]
    if cond_type == "index_pct":
        value = context.indexes.get(str(cond["code"]))
        return None if value is None else _compare(float(value), cond["op"], float(cond["value"]))
    if cond_type in {"sector_change", "sector_rank"}:
        sector = context.sectors.get(str(cond["sector_code"]))
        if sector is None:
            return None
        key = "change_pct" if cond_type == "sector_change" else "rank"
        value = sector.get(key)
        return None if value is None else _compare(float(value), cond["op"], float(cond["value"]))
    quote = context.quote
    if cond_type == "price_cross":
        if quote is None or quote.price <= 0:
            return None
        if cond["direction"] == "up":
            return quote.price >= float(cond["level"])
        return quote.price <= float(cond["level"])
    if cond_type == "price_in_range":
        if quote is None or quote.price <= 0:
            return None
        return float(cond["lo"]) <= quote.price <= float(cond["hi"])
    if cond_type == "pct_change":
        change = _quote_change_pct(quote) if quote is not None else None
        if change is None:
            return None
        threshold = float(cond["threshold_pct"])
        return change >= threshold if cond["direction"] == "up" else change <= -threshold
    if cond_type == "open_pct":
        local = to_cn(context.now).time().replace(tzinfo=None)
        if local < OPEN_PCT_TIME:
            return None
        if quote is None or quote.open <= 0 or quote.prev_close <= 0:
            return None
        value = (quote.open / quote.prev_close - 1.0) * 100.0
        return _compare(value, cond["op"], float(cond["value"]))
    if cond_type == "volume_ratio":
        ratio = quote.volume_ratio if quote is not None else None
        return None if ratio is None else _compare(float(ratio), cond["op"], float(cond["value"]))
    return None


def evaluate_plan(
    plan: Plan, context: EvalContext
) -> tuple[str, str, dict[str, list[Optional[bool]]], int]:
    """Return ``(target_state, reason, conds, giveup_unknown)``."""
    groups = {
        "market": [eval_condition(item, context) for item in plan.market],
        "sector": [eval_condition(item, context) for item in plan.sector],
        "stock": [eval_condition(item, context) for item in plan.stock],
        "giveup": [eval_condition(item, context) for item in plan.giveup],
    }
    giveup_results = groups["giveup"]
    giveup_unknown = sum(1 for item in giveup_results if item is None)

    if any(item is True for item in giveup_results):
        index = giveup_results.index(True)
        return (
            "abandon",
            f"放弃条件 {index + 1} 成立",
            groups,
            giveup_unknown,
        )

    quote = context.quote
    if (
        plan.held
        and plan.stop_price is not None
        and quote is not None
        and quote.price > 0
        and quote.price <= plan.stop_price
    ):
        return (
            "exit",
            f"持有且现价 {quote.price:.2f} ≤ 止损价 {plan.stop_price:.2f}",
            groups,
            giveup_unknown,
        )

    market_ok = all(item is True for item in groups["market"])
    sector_ok = all(item is True for item in groups["sector"])
    stock_results = groups["stock"]
    if not stock_results:
        stock_ok = True
    elif plan.policy == "all":
        stock_ok = all(item is True for item in stock_results)
    else:
        stock_ok = any(item is True for item in stock_results)

    if market_ok and sector_ok and stock_ok:
        target, reason = "execute", "市场、板块与个股条件全部成立"
    elif market_ok and sector_ok:
        target, reason = "await_confirm", "市场与板块成立，等待个股确认"
    else:
        target, reason = "observe", "条件未全部成立"
    if giveup_unknown:
        reason += f"；放弃条件 {giveup_unknown} 项取不到数据（unknown），不触发"
    return target, reason, groups, giveup_unknown


def step_state(
    current: str,
    target: str,
    streak: int,
    pending: Optional[str],
) -> tuple[str, int, Optional[str], bool]:
    """Return ``(new_state, streak, pending, changed)``."""
    if target == current:
        return current, 0, None, False
    if current in TERMINAL_STATES:
        if target in TERMINAL_STATES:
            return current, 0, None, False
        needs_hysteresis = True
    elif current in {"execute", "await_confirm"} and (
        target == "observe" or (current == "execute" and target == "await_confirm")
    ):
        needs_hysteresis = True
    else:
        needs_hysteresis = False
    if not needs_hysteresis:
        return target, 0, None, True
    if pending == target:
        streak += 1
    else:
        streak = 1
    if streak >= HYSTERESIS_EVALUATIONS:
        return target, 0, None, True
    return current, streak, target, False


# -- persistence ---------------------------------------------------------
def _initial_conds(plan: Plan) -> dict[str, list[Optional[bool]]]:
    return {
        "market": [None] * len(plan.market),
        "sector": [None] * len(plan.sector),
        "stock": [None] * len(plan.stock),
        "giveup": [None] * len(plan.giveup),
    }


def _parse_history(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("ts"), str):
            continue
        rows.append(
            {
                "ts": item["ts"],
                "from": item.get("from"),
                "to": item.get("to"),
                "reason": item.get("reason"),
            }
        )
    return rows[-MAX_HISTORY:]


def _parse_conds(raw: Any, plan: Plan) -> dict[str, list[Optional[bool]]]:
    empty = _initial_conds(plan)
    if not isinstance(raw, dict):
        return empty
    parsed: dict[str, list[Optional[bool]]] = {}
    for group in ("market", "sector", "stock", "giveup"):
        values = raw.get(group)
        if not isinstance(values, list):
            parsed[group] = empty[group]
            continue
        cleaned = [item if isinstance(item, bool) else None for item in values][
            : len(empty[group])
        ]
        parsed[group] = cleaned + [None] * (len(empty[group]) - len(cleaned))
    return parsed


class RuntimePlanStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, now: datetime) -> PlansState:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return PlansState()
        except OSError as exc:
            logger.warning("无法读取计划规则文件 %s: %s，按空处理", self.path, exc)
            return PlansState(load_error=str(exc))
        try:
            raw: Any = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("计划规则文件 %s 已损坏（%s），按空处理", self.path, exc)
            return PlansState(load_error=str(exc))
        if not isinstance(raw, dict):
            logger.warning("计划规则文件 %s 结构错误，按空处理", self.path)
            return PlansState(load_error="structure")
        if raw.get("version") not in (None, 1):
            logger.warning("计划规则文件 %s 版本未知，按空处理", self.path)
            return PlansState(load_error="version")

        state = PlansState()
        rows = raw.get("plans", [])
        if isinstance(rows, list):
            for item in rows:
                runtime = _parse_runtime(item, now)
                if runtime is None:
                    continue
                if any(existing.plan.id == runtime.plan.id for existing in state.plans):
                    logger.warning("计划规则文件里 id 重复，已忽略: %s", runtime.plan.id)
                    continue
                state.plans.append(runtime)
        auto = raw.get("auto_codes", [])
        if isinstance(auto, list):
            for code in auto:
                if isinstance(code, str):
                    try:
                        state.auto_codes.add(normalize_watch_code(code))
                    except (SymbolError, ConfigError):
                        logger.warning("计划自动监控代码非法，已忽略: %r", code)
        return state

    def save(self, state: PlansState) -> None:
        payload = {
            "version": 1,
            "auto_codes": sorted(state.auto_codes),
            "plans": [_runtime_to_dict(item) for item in state.plans],
        }
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}{RUNTIME_TMP_SUFFIX}")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(data)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise


def _parse_runtime(raw: Any, now: datetime) -> Optional[PlanRuntime]:
    if not isinstance(raw, dict):
        return None
    plan_raw = raw.get("plan", raw)
    try:
        plan = validate_plan_payload(plan_raw)
    except PlanError as exc:
        logger.warning("计划规则文件里的计划已忽略: %s", exc)
        return None
    state = raw.get("state", "observe")
    if state not in PLAN_STATES:
        state = "observe"
    try:
        since = parse_iso(raw.get("since"))
    except (TypeError, ValueError):
        since = now
    try:
        expired_at = (
            parse_iso(raw.get("expired_at")) if raw.get("expired_at") else None
        )
    except (TypeError, ValueError):
        expired_at = None
    last_alert_ts: dict[str, datetime] = {}
    if isinstance(raw.get("last_alert_ts"), dict):
        for key, value in raw["last_alert_ts"].items():
            if not isinstance(key, str):
                continue
            try:
                last_alert_ts[key] = parse_iso(value)
            except (TypeError, ValueError):
                continue
    active = raw.get("active")
    if not isinstance(active, bool):
        active = state != "expired"
    if state == "expired":
        active = False
    alert_seq = raw.get("alert_seq")
    if isinstance(alert_seq, bool) or not isinstance(alert_seq, int):
        alert_seq = 0
    streak = raw.get("streak")
    if isinstance(streak, bool) or not isinstance(streak, int) or streak < 0:
        streak = 0
    pending = raw.get("pending")
    if pending not in PLAN_STATES:
        pending = None
    last_price = raw.get("last_price")
    if isinstance(last_price, bool) or not isinstance(last_price, (int, float)):
        last_price = None
    return PlanRuntime(
        plan=plan,
        state=state,
        since=since,
        history=_parse_history(raw.get("history")),
        conds=_parse_conds(raw.get("conds"), plan),
        last_price=float(last_price) if last_price is not None else None,
        active=active,
        expired_at=expired_at,
        last_alert_ts=last_alert_ts,
        streak=streak,
        pending=pending,
        alert_seq=max(0, alert_seq),
        restored=True,
    )


def _runtime_to_dict(runtime: PlanRuntime) -> dict[str, Any]:
    return {
        "plan": runtime.plan.as_dict(),
        "state": runtime.state,
        "since": fmt_iso(runtime.since),
        "history": runtime.history[-MAX_HISTORY:],
        "conds": runtime.conds,
        "last_price": runtime.last_price,
        "active": runtime.active,
        "expired_at": fmt_iso(runtime.expired_at) if runtime.expired_at else None,
        "last_alert_ts": {
            key: fmt_iso(value) for key, value in runtime.last_alert_ts.items()
        },
        "streak": runtime.streak,
        "pending": runtime.pending,
        "alert_seq": runtime.alert_seq,
    }


def plan_state_dict(runtime: PlanRuntime) -> dict[str, Any]:
    return {
        "id": runtime.plan.id,
        "code": runtime.plan.code,
        "label": runtime.plan.label,
        "state": runtime.state,
        "since": fmt_iso(runtime.since),
        "last_price": runtime.last_price,
        "held": runtime.plan.held,
        "conds": runtime.conds,
        "history": runtime.history[-MAX_HISTORY:],
        "expires_at": (
            fmt_iso(runtime.plan.expires_at) if runtime.plan.expires_at else None
        ),
        "active": runtime.active,
    }


def make_runtime(plan: Plan, now: datetime) -> PlanRuntime:
    return PlanRuntime(
        plan=plan,
        state="observe",
        since=now.astimezone(CN_TZ),
        conds=_initial_conds(plan),
    )
