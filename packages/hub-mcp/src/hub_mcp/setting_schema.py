"""Setting keys the agent may suggest.

The agent has no adopt/set/clear/dismiss path: it can only write a suggestion
(POST /settings/{key}/suggest).  Keys, ranges and integer-ness mirror the hub's
own whitelist so an out-of-range suggestion never reaches it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hub_mcp.errors import ToolError
from hub_mcp.validation import clean_free_text, finite_number


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    minimum: float
    maximum: float
    integer: bool = False


SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("total_cap_strong_pct", "总仓位上限（强势）", 0, 100),
    SettingSpec("total_cap_neutral_pct", "总仓位上限（中性）", 0, 100),
    SettingSpec("total_cap_weak_pct", "总仓位上限（弱势）", 0, 100),
    SettingSpec("single_stock_cap_pct", "单票上限", 0, 100),
    SettingSpec("theme_cap_pct", "同题材合计上限", 0, 100),
    SettingSpec("per_trade_risk_pct", "单笔可承受亏损", 0, 10),
    SettingSpec("pause_day_drawdown_pct", "当日回撤暂停线", 0, 30),
    SettingSpec("pause_total_loss_pct", "持仓累计浮亏暂停线", 0, 60),
    SettingSpec("pause_loss_streak", "连亏笔数暂停线", 1, 20, True),
    SettingSpec("emergency_index_drop_pct", "指数跌幅应急线", 0.5, 10),
    SettingSpec("emergency_limit_down_count", "跌停家数应急线", 5, 500, True),
)

SPECS: dict[str, SettingSpec] = {spec.key: spec for spec in SETTING_SPECS}
SETTING_KEYS = frozenset(SPECS)
MAX_BASIS_CHARS = 200
SUGGESTED_MESSAGE = "已提交建议，需用户在「复盘」页采纳后才生效"


def spec_for(key: Any) -> SettingSpec:
    if not isinstance(key, str) or key not in SPECS:
        raise ToolError("unknown_key", "未知的设置项；只能用约定的 11 个 key", field="key")
    return SPECS[key]


def validate_value(spec: SettingSpec, raw: Any) -> float:
    value = finite_number(raw, "value", minimum=spec.minimum, maximum=spec.maximum)
    if spec.integer:
        if not value.is_integer():
            raise ToolError("bad_value", f"{spec.key} 必须是整数", field="value")
        return float(int(value))
    return value


def validate_basis(raw: Any) -> str:
    return clean_free_text(raw, "basis", MAX_BASIS_CHARS)
