"""Deterministic market summary headlines (no model, no invented numbers).

Every headline is derived from the payloads the same engine serves at
``/overview``, ``/sectors`` and ``/movers``.  Inputs are plain dictionaries so
the rules stay pure and unit-testable; a missing data block omits the whole
headline instead of filling a placeholder.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional, Sequence

MAX_HEADLINES = 5

RISK_LABELS = {
    "R1": "指数放量下跌",
    "R2": "宽度恶化/背离",
    "R3": "板块排名跃升",
    "R4": "板块涨停骤增",
    "R5": "相对强弱穿越",
    "R6": "个股与板块背离",
}


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fmt_pct(value: Any) -> str:
    """``-0.5`` -> ``-0.50%`` (two decimals, always signed)."""
    number = _number(value)
    return f"{number:+.2f}%" if number is not None else ""


def fmt_amount_yi(value: Any) -> str:
    """Yuan -> 亿元 with two decimals; callers append the unit."""
    number = _number(value)
    return f"{number / 1e8:.2f}" if number is not None else ""


def _ref(object_type: str, code: Any, name: Any) -> dict[str, Any]:
    return {"type": object_type, "code": str(code), "name": str(name or "")}


def _index_row(overview: Mapping[str, Any], code: str) -> Optional[dict[str, Any]]:
    for row in overview.get("indexes") or []:
        if row.get("code") == code and _number(row.get("change_pct")) is not None:
            return row
    return None


def _indexes_headline(overview: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    picked = [
        row
        for code in ("000001.SH", "399001.SZ", "399006.SZ")
        if (row := _index_row(overview, code)) is not None
    ]
    if not picked:
        return None
    changes = [_number(row["change_pct"]) for row in picked]
    values = [value for value in changes if value is not None]
    label = "三大指数" if len(picked) == 3 else "主要指数"
    if all(value > 0 for value in values):
        title = f"{label}收涨"
        tone = "up"
    elif all(value < 0 for value in values):
        title = f"{label}收跌"
        tone = "down"
    else:
        title = f"{label}涨跌互现"
        tone = "neutral"
    body = "，".join(f"{row['name']} {fmt_pct(row['change_pct'])}" for row in picked) + "。"
    refs = [_ref("index", row["code"], row.get("name")) for row in picked]
    return {"id": "indexes", "tone": tone, "title": title, "body": body, "refs": refs}


def _breadth_headline(
    overview: Mapping[str, Any], previous_day: Optional[Mapping[str, Any]]
) -> Optional[dict[str, Any]]:
    breadth = overview.get("breadth") or {}
    up = breadth.get("up")
    down = breadth.get("down")
    if up is None or down is None:
        return None
    ratio = _number(breadth.get("up_ratio"))
    parts: list[str] = []
    if ratio is not None:
        parts.append(f"上涨占比 {ratio:.2f}")
    limit_up = breadth.get("limit_up")
    if limit_up is not None:
        text = f"涨停 {int(limit_up)} 家"
        previous_limit = (previous_day or {}).get("limit_up")
        if previous_limit is not None:
            text += f"（上一交易日 {int(previous_limit)} 家）"
        parts.append(text)
    amount = _number(breadth.get("amount_yuan"))
    if amount is not None:
        text = f"全市场成交额 {fmt_amount_yi(amount)} 亿元"
        previous_amount = _number((previous_day or {}).get("amount_yuan"))
        if previous_amount is not None:
            text += f"，上一交易日全天 {fmt_amount_yi(previous_amount)} 亿元"
        parts.append(text)
    if ratio is None:
        tone = "neutral"
    else:
        tone = "up" if ratio >= 0.55 else "down" if ratio <= 0.45 else "neutral"
    title = f"上涨 {int(up)} 家、下跌 {int(down)} 家"
    return {
        "id": "breadth",
        "tone": tone,
        "title": title,
        "body": "；".join(parts) + "。",
        "refs": [],
    }


def _sectors_headline(sectors: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    eligible = []
    for row in sectors.get("rows") or []:
        change = _number(row.get("change_pct"))
        members = _number(row.get("member_count"))
        if change is not None and members is not None and members >= 10:
            eligible.append(row)
    if len(eligible) < 2:
        return None
    ordered = sorted(eligible, key=lambda row: (-float(row["change_pct"]), str(row["code"])))
    strongest = ordered[0]
    weakest = ordered[-1]
    if strongest["code"] == weakest["code"]:
        return None
    title = f"最强行业 {strongest['name']} {fmt_pct(strongest['change_pct'])}"
    body = f"{weakest['name']} {fmt_pct(weakest['change_pct'])} 垫底（仅统计成分股足够多的行业）。"
    refs = [
        _ref("sector", strongest["code"], strongest.get("name")),
        _ref("sector", weakest["code"], weakest.get("name")),
    ]
    return {"id": "sectors", "tone": "neutral", "title": title, "body": body, "refs": refs}


def _limit_headline(
    overview: Mapping[str, Any], movers: Optional[Mapping[str, Any]]
) -> Optional[dict[str, Any]]:
    breadth = overview.get("breadth") or {}
    limit_up = breadth.get("limit_up")
    if limit_up is None:
        return None
    limit_down = breadth.get("limit_down")
    title_parts = [f"涨停 {int(limit_up)} 家"]
    if limit_down is not None:
        title_parts.append(f"跌停 {int(limit_down)} 家")
    body_parts: list[str] = []
    broken = breadth.get("broken")
    if broken is not None:
        body_parts.append(f"炸板 {int(broken)} 家")
    streak = breadth.get("max_streak")
    if streak is not None:
        body_parts.append(f"最大连板 {int(streak)} 板")
    top: Optional[Mapping[str, Any]] = None
    for row in (movers or {}).get("rows") or []:
        if _number(row.get("change_pct")) is not None:
            top = row
            break
    if top is not None:
        body_parts.append(f"涨幅榜首位 {top['name']} {fmt_pct(top['change_pct'])}")
    body = "；".join(body_parts) + "。" if body_parts else "涨停家数已更新。"
    refs = [_ref("stock", top["code"], top.get("name"))] if top is not None else []
    return {
        "id": "limit",
        "tone": "neutral",
        "title": "，".join(title_parts),
        "body": body,
        "refs": refs,
    }


def _alert_headline(alerts: Sequence[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    label = None
    for alert in alerts:
        label = RISK_LABELS.get(str(alert.get("rule_id") or ""))
        if label:
            break
    if label is None:
        return None
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for alert in alerts:
        obj = alert.get("object") or {}
        object_type = str(obj.get("type") or "")
        code = obj.get("code")
        if object_type not in {"index", "sector", "stock"} or not code:
            continue
        key = (object_type, str(code))
        if key in seen:
            continue
        seen.add(key)
        refs.append(_ref(object_type, code, obj.get("name")))
        if len(refs) >= 3:
            break
    return {
        "id": "risk",
        "tone": "warn",
        "title": f"风险提示：{label}",
        "body": "引擎规则已进入触发窗口，请关注盘面变化。",
        "refs": refs,
    }


def build_summary(
    *,
    overview: Mapping[str, Any],
    sectors: Mapping[str, Any],
    movers: Mapping[str, Any],
    previous_day: Optional[Mapping[str, Any]] = None,
    alerts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return ``{headlines, note}``; at most five rows, missing data omitted."""
    headline_list: list[dict[str, Any]] = []
    for candidate in (
        _indexes_headline(overview),
        _breadth_headline(overview, previous_day),
        _sectors_headline(sectors),
        _limit_headline(overview, movers),
        _alert_headline(list(alerts)),
    ):
        if candidate is not None:
            headline_list.append(candidate)
    return {
        "generated_by": "engine",
        "headlines": headline_list[:MAX_HEADLINES],
        "note": "由引擎按确定性规则生成；数字可在 /overview、/sectors、/movers 中回查。",
    }
