"""Settings: agent suggestions are inert until the user adopts or sets a value.

Only adopted / user-set values are ever read by discipline, sizing or emergency
rules.  ``suggest`` never touches ``value``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from .models import fmt_iso
from .validation import ApiError, clean_text, number, only


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    integer: bool = False


SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("total_cap_strong_pct", "总仓位上限（强势）", "%", 0, 100),
    SettingSpec("total_cap_neutral_pct", "总仓位上限（中性）", "%", 0, 100),
    SettingSpec("total_cap_weak_pct", "总仓位上限（弱势）", "%", 0, 100),
    SettingSpec("single_stock_cap_pct", "单票上限", "%", 0, 100),
    SettingSpec("theme_cap_pct", "同题材合计上限", "%", 0, 100),
    SettingSpec("per_trade_risk_pct", "单笔可承受亏损", "%", 0, 10),
    SettingSpec("pause_day_drawdown_pct", "当日回撤暂停线", "%", 0, 30),
    SettingSpec("pause_total_loss_pct", "持仓累计浮亏暂停线", "%", 0, 60),
    SettingSpec("pause_loss_streak", "连亏笔数暂停线", "笔", 1, 20, True),
    SettingSpec("emergency_index_drop_pct", "指数跌幅应急线", "%", 0.5, 10),
    SettingSpec("emergency_limit_down_count", "跌停家数应急线", "家", 5, 500, True),
)

SPECS: dict[str, SettingSpec] = {spec.key: spec for spec in SETTING_SPECS}
TOTAL_CAP_KEYS = {
    "strong": "total_cap_strong_pct",
    "neutral": "total_cap_neutral_pct",
    "weak": "total_cap_weak_pct",
}
SOURCES = {"unset", "adopted", "user_set"}
ACTION_FIELDS = {"action", "value"}
SUGGEST_FIELDS = {"value", "basis"}


def spec_for(key: Any) -> SettingSpec:
    if not isinstance(key, str) or key not in SPECS:
        raise ApiError("unknown_key", "未知的设置项")
    return SPECS[key]


def _checked_value(spec: SettingSpec, raw: Any) -> float:
    value = number(
        raw,
        "value",
        minimum=spec.minimum,
        maximum=spec.maximum,
        integer=spec.integer,
    )
    return float(int(value)) if spec.integer else value


def _row_payload(row: Optional[Mapping[str, Any]], spec: SettingSpec) -> dict[str, Any]:
    if row is None:
        return {
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "value": None,
            "source": "unset",
            "suggestion": None,
            "updated_at": None,
        }
    suggestion = None
    if row.get("suggestion_value") is not None:
        suggestion = {
            "value": row["suggestion_value"],
            "basis": row.get("suggestion_basis") or "",
            "backtested": False,
            "suggested_at": fmt_iso(row["suggested_at"]) if row.get("suggested_at") else None,
        }
    source = row.get("source") or "unset"
    if source not in SOURCES:
        source = "unset"
    return {
        "key": spec.key,
        "label": spec.label,
        "unit": spec.unit,
        "value": row.get("value") if source != "unset" else None,
        "source": source,
        "suggestion": suggestion,
        "updated_at": fmt_iso(row["updated_at"]) if row.get("updated_at") else None,
    }


class SettingsService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def payload(self) -> dict[str, Any]:
        rows = {row["key"]: row for row in self.store.list_settings()}
        return {
            "ok": True,
            "settings": [_row_payload(rows.get(spec.key), spec) for spec in SETTING_SPECS],
        }

    def item(self, key: Any) -> dict[str, Any]:
        spec = spec_for(key)
        return _row_payload(self.store.get_setting(spec.key), spec)

    def action(self, key: Any, payload: Any, *, now: datetime) -> dict[str, Any]:
        spec = spec_for(key)
        if not isinstance(payload, dict):
            raise ApiError("invalid_body", "请求体必须是 JSON 对象")
        only(payload, ACTION_FIELDS)
        action = payload.get("action")
        if action not in {"adopt", "set", "clear", "dismiss"}:
            raise ApiError("invalid_action", "action 只接受 adopt/set/clear/dismiss")
        if action == "set":
            if "value" not in payload:
                raise ApiError("bad_value", "set 需要 value")
            value = _checked_value(spec, payload.get("value"))
        else:
            if "value" in payload:
                raise ApiError("unexpected_field", "只有 set 接受 value")
            value = None

        row = self.store.get_setting(spec.key)
        if action == "adopt":
            suggestion = (row or {}).get("suggestion_value")
            if suggestion is None:
                raise ApiError("no_suggestion", "当前没有可采纳的建议")
            self.store.save_setting(
                spec.key,
                value=float(suggestion),
                source="adopted",
                now=now,
                clear_suggestion=True,
            )
        elif action == "set":
            self.store.save_setting(
                spec.key, value=value, source="user_set", now=now, clear_suggestion=True
            )
        elif action == "clear":
            self.store.save_setting(spec.key, value=None, source="unset", now=now)
        else:
            if row is None or row.get("suggestion_value") is None:
                raise ApiError("no_suggestion", "当前没有可忽略的建议")
            self.store.save_setting(spec.key, keep_value=True, now=now, clear_suggestion=True)
        return {"ok": True, "setting": self.item(spec.key)}

    def suggest(self, key: Any, payload: Any, *, now: datetime) -> dict[str, Any]:
        spec = spec_for(key)
        if not isinstance(payload, dict):
            raise ApiError("invalid_body", "请求体必须是 JSON 对象")
        only(payload, SUGGEST_FIELDS)
        if "value" not in payload:
            raise ApiError("bad_value", "suggest 需要 value")
        value = _checked_value(spec, payload.get("value"))
        basis = clean_text(payload.get("basis"), "basis", 200)
        self.store.save_suggestion(spec.key, value=value, basis=basis, now=now)
        return {"ok": True, "setting": self.item(spec.key)}

    # -- readers used by other modules ----------------------------------
    def value(self, key: str) -> Optional[float]:
        row = self.store.get_setting(key)
        if row is None or row.get("source") not in {"adopted", "user_set"}:
            return None
        return row.get("value")

    def adopted(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for row in self.store.list_settings():
            if row.get("source") in {"adopted", "user_set"} and row.get("value") is not None:
                result[row["key"]] = float(row["value"])
        return result

    def unadopted_suggestions(self) -> list[dict[str, Any]]:
        rows = {row["key"]: row for row in self.store.list_settings()}
        items: list[dict[str, Any]] = []
        for spec in SETTING_SPECS:
            item = _row_payload(rows.get(spec.key), spec)
            if item["suggestion"] is not None:
                items.append(
                    {
                        "key": spec.key,
                        "label": spec.label,
                        "unit": spec.unit,
                        "suggestion": item["suggestion"],
                    }
                )
        return items

    def total_cap_for(self, regime: Optional[str]) -> Optional[float]:
        label = regime if regime in TOTAL_CAP_KEYS else None
        if label is None:
            return None
        return self.value(TOTAL_CAP_KEYS[label])
