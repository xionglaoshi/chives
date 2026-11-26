"""Runtime rule layer: validated upserts, overrides and an audit trail.

The YAML configuration is never modified.  New rules and overrides live in
``rules.runtime.json`` next to the engine state; reads tolerate a missing or
corrupt file and writes are atomic.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .config import RULE_TYPES, ConfigError, parse_rule_payload
from .models import Rule

logger = logging.getLogger("chives_radar.rule_store")

RUNTIME_RULES_FILE_NAME = "rules.runtime.json"
RUNTIME_TMP_SUFFIX = ".tmp"
MAX_ACTOR_LENGTH = 64
MAX_HISTORY = 1000
RULE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_ACTOR_STRIP_RE = re.compile(r"[\x00-\x1f\x7f<>]")

# (type, field, minimum, maximum, exclusive_minimum).  ``maximum`` None means
# there is no upper bound.
BOUNDS: dict[str, tuple[str, float, Optional[float], bool]] = {
    "pct_change": ("threshold_pct", 0.1, 25.0, False),
    "vwap_deviation": ("threshold_pct", 0.1, 25.0, False),
    "limit_proximity": ("within_pct", 0.05, 10.0, False),
    "volume_surge": ("multiple", 1.2, 50.0, False),
    "price_cross": ("level", 0.0, None, True),
}


class RuleError(Exception):
    """A runtime-rule request was rejected with a stable code and optional range."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: Optional[str] = None,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        exclusive_minimum: bool = False,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.status_code = status_code or {
            "rules_full": 409,
            "rule_not_found": 404,
            "persistence_error": 500,
        }.get(code, 400)


@dataclass(frozen=True)
class RuntimeOverride:
    rule: Optional[Rule] = None
    disabled: bool = False


@dataclass
class RuntimeRulesState:
    rules: list[Rule] = field(default_factory=list)
    overrides: dict[str, RuntimeOverride] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    def clone(self) -> "RuntimeRulesState":
        return RuntimeRulesState(
            rules=list(self.rules),
            overrides=dict(self.overrides),
            history=list(self.history),
        )


def sanitize_actor(value: Any) -> str:
    """Length-limit and strip control/HTML characters from ``X-Actor``."""
    if value is None:
        return "unknown"
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = _ACTOR_STRIP_RE.sub("", str(value))
    text = " ".join(text.split())[:MAX_ACTOR_LENGTH].strip()
    return text or "unknown"


def validate_rule_id(value: Any) -> str:
    if not isinstance(value, str) or not RULE_ID_RE.fullmatch(value):
        raise RuleError(
            "invalid_id",
            "id 只能由 1~40 个字母、数字、下划线或连字符组成",
            field="id",
        )
    return value


def _numeric(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _check_bounds(raw: dict[str, Any]) -> None:
    rule_type = raw.get("type")
    spec = BOUNDS.get(rule_type) if isinstance(rule_type, str) else None
    if spec is None:
        return
    name, minimum, maximum, exclusive = spec
    value = raw.get(name)
    # Missing or wrong-typed values are left to the shared config validator.
    if not _numeric(value):
        return
    number = float(value)
    too_low = number <= minimum if exclusive else number < minimum
    too_high = maximum is not None and number > maximum
    if not too_low and not too_high:
        return
    if maximum is None:
        message = f"{name} 必须大于 {minimum:g}"
        allowed: dict[str, Any] = {"gt": minimum}
    elif exclusive:
        message = f"{name} 必须在 ({minimum:g}, {maximum:g}] 之间"
        allowed = {"gt": minimum, "max": maximum}
    else:
        message = f"{name} 必须在 [{minimum:g}, {maximum:g}] 之间"
        allowed = {"min": minimum, "max": maximum}
    raise RuleError(
        "out_of_bounds",
        message,
        field=name,
        minimum=minimum,
        maximum=maximum,
        exclusive_minimum=exclusive,
    )


def validate_rule_payload(raw: Any, *, index: int = 0) -> Rule:
    """Validate one complete rule object; never touches engine state."""
    if not isinstance(raw, dict):
        raise RuleError("invalid_rule", "规则必须是 JSON 对象")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not RULE_ID_RE.fullmatch(rule_id):
        raise RuleError(
            "invalid_id",
            "id 只能由 1~40 个字母、数字、下划线或连字符组成",
            field="id",
        )
    rule_type = raw.get("type")
    if not isinstance(rule_type, str) or rule_type not in RULE_TYPES:
        raise RuleError("invalid_rule", f"未知规则类型: {rule_type!r}", field="type")
    _check_bounds(raw)

    payload = dict(raw)
    # ``symbols: null`` is what GET /rules emits for an unscoped rule; accept
    # that round-trip while the YAML file itself stays strict.
    if payload.get("symbols") is None:
        payload.pop("symbols", None)
    if payload.get("codes") is None:
        payload.pop("codes", None)
    try:
        return parse_rule_payload(payload, index=index)
    except ConfigError as exc:
        raise RuleError("invalid_rule", str(exc)) from exc


def rule_storage_dict(rule: Rule) -> dict[str, Any]:
    """Rule fields as persisted: omit ``symbols: null`` so it re-parses strictly."""
    data = rule.as_dict()
    if data.get("symbols") is None:
        data.pop("symbols", None)
    if data.get("codes") is None:
        data.pop("codes", None)
    return data


def rule_row(rule: Rule, source: str, disabled: bool = False) -> dict[str, Any]:
    row = rule.as_dict()
    row["source"] = source
    row["disabled"] = disabled
    row["enabled"] = not disabled
    return row


def _parse_history(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("ts"), str) or not isinstance(item.get("action"), str):
            continue
        rows.append(
            {
                "ts": item["ts"],
                "action": item["action"],
                "rule_id": item.get("rule_id"),
                "before": item.get("before"),
                "after": item.get("after"),
                "actor": sanitize_actor(item.get("actor")),
            }
        )
    return rows[-MAX_HISTORY:]


class RuntimeRulesStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> RuntimeRulesState:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.info("运行时规则文件 %s 不存在，按空处理", self.path)
            return RuntimeRulesState()
        except OSError as exc:
            logger.warning("无法读取运行时规则文件 %s: %s，按空处理", self.path, exc)
            return RuntimeRulesState()
        try:
            raw: Any = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("运行时规则文件 %s 已损坏（%s），按空处理", self.path, exc)
            return RuntimeRulesState()
        if not isinstance(raw, dict):
            logger.warning("运行时规则文件 %s 结构错误，按空处理", self.path)
            return RuntimeRulesState()

        state = RuntimeRulesState()
        seen: set[str] = set()
        rules_raw = raw.get("rules", [])
        if isinstance(rules_raw, list):
            for item in rules_raw:
                try:
                    rule = validate_rule_payload(item)
                except RuleError as exc:
                    logger.warning("运行时规则文件里的规则已忽略: %s", exc)
                    continue
                if rule.id in seen:
                    logger.warning("运行时规则文件里 id 重复，已忽略: %s", rule.id)
                    continue
                seen.add(rule.id)
                state.rules.append(rule)

        overrides_raw = raw.get("overrides", {})
        if isinstance(overrides_raw, dict):
            for rule_id, item in overrides_raw.items():
                if not isinstance(rule_id, str) or not RULE_ID_RE.fullmatch(rule_id):
                    logger.warning("运行时规则文件里的覆盖 id 非法，已忽略: %r", rule_id)
                    continue
                if not isinstance(item, dict):
                    logger.warning("运行时规则文件里的覆盖 %s 结构错误，已忽略", rule_id)
                    continue
                if item.get("disabled") is True:
                    state.overrides[rule_id] = RuntimeOverride(disabled=True)
                    continue
                candidate = item.get("rule", item)
                try:
                    rule = validate_rule_payload(candidate)
                except RuleError as exc:
                    logger.warning("运行时覆盖 %s 已忽略: %s", rule_id, exc)
                    continue
                if rule.id != rule_id:
                    logger.warning("运行时覆盖 %s 的内嵌 rule.id 不匹配，已忽略", rule_id)
                    continue
                state.overrides[rule_id] = RuntimeOverride(rule=rule)

        state.history = _parse_history(raw.get("history", []))
        return state

    def save(self, state: RuntimeRulesState) -> None:
        payload = {
            "version": 1,
            "rules": [rule_storage_dict(rule) for rule in state.rules],
            "overrides": {
                rule_id: (
                    {"disabled": True}
                    if override.disabled
                    else {"rule": rule_storage_dict(override.rule)}
                )
                for rule_id, override in state.overrides.items()
                if override.disabled or override.rule is not None
            },
            "history": state.history[-MAX_HISTORY:],
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


def history_entry(
    ts: str,
    action: str,
    rule_id: Optional[str],
    before: Optional[dict[str, Any]],
    after: Optional[dict[str, Any]],
    actor: str,
) -> dict[str, Any]:
    return {
        "ts": ts,
        "action": action,
        "rule_id": rule_id,
        "before": before,
        "after": after,
        "actor": sanitize_actor(actor),
    }
