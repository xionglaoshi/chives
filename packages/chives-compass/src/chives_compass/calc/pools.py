"""Pure helpers for the v1.4 limit-pool, theme and yesterday-feedback views.

Nothing here performs I/O or reads the clock: callers pass already normalised
pool rows (the dicts produced by ``sources.gateway.pool_rows``) and quote
objects, so every rule is unit-testable without a network.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

POOL_KINDS = ("zt", "zb", "dt")
THEME_DEFINITION = "概念板块（厂商口径）"
BY_INDUSTRY_DEFINITION = (
    "行业口径（厂商行业字段，不是题材口径）；涨停/炸板家数按池内行业字段统计，"
    "同一只股票在池内只计一次"
)
HISTORY_DEFINITION = (
    "封板率_pct=涨停家数/(涨停家数+炸板家数)×100；晋级率_pct 按股票代码跨相邻两个"
    "交易日匹配：1to2=昨日连板1中今日连板2的家数÷昨日连板1家数×100，2to3 同理，"
    "3up=昨日连板≥3中今日连板≥昨日+1的家数÷昨日连板≥3家数×100；"
    "前一日缺失或分母为 0 时为 null，不插值"
)
LADDER_DEFINITION = (
    "按厂商连板数字段分层，连板数降序；streak=1 只给家数不列行，其余每层最多 8 行"
)


def _streak(row: Mapping[str, Any]) -> Optional[int]:
    value = row.get("streak")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if number >= 1 else None


def _number(row: Mapping[str, Any], key: str) -> Optional[float]:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _seal_sort(row: Mapping[str, Any]) -> tuple[int, str]:
    value = str(row.get("first_seal_time") or "99:99:99")
    return (0, value)


def sort_pool_rows(rows: Iterable[Mapping[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Return copies sorted by the contract order for one pool kind."""
    items = [dict(row) for row in rows]
    if kind == "zt":
        items.sort(
            key=lambda row: (
                -(_streak(row) or 0),
                _seal_sort(row),
                str(row.get("code") or ""),
            )
        )
    elif kind == "zb":
        items.sort(
            key=lambda row: (
                -int(_number(row, "broken_times") or 0),
                str(row.get("code") or ""),
            )
        )
    elif kind == "dt":
        items.sort(
            key=lambda row: (
                -(_number(row, "amount_yuan") or 0.0),
                str(row.get("code") or ""),
            )
        )
    else:
        raise ValueError(f"unknown pool kind: {kind}")
    return items


def ladder_payload(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build the streak tiers; rows of one tier keep the /pool zt order."""
    ordered = sort_pool_rows(rows, "zt")
    groups: dict[int, list[dict[str, Any]]] = {}
    for row in ordered:
        streak = _streak(row)
        if streak is None:
            continue
        groups.setdefault(streak, []).append(row)
    streaks = sorted(groups, reverse=True)
    tiers: list[dict[str, Any]] = []
    for streak in streaks:
        group = groups[streak]
        tier: dict[str, Any] = {"streak": streak, "count": len(group)}
        if streak > 1:
            tier["rows"] = group[:8]
        tiers.append(tier)
    return {
        "max_streak": streaks[0] if streaks else None,
        "tiers": tiers,
        "first_board_count": len(groups.get(1, [])),
    }


def seal_ratio_pct(zt: Optional[int], zb: Optional[int]) -> Optional[float]:
    if zt is None or zb is None or (zt + zb) <= 0:
        return None
    return round(zt / (zt + zb) * 100.0, 2)


def promotion_pct(
    previous_rows: Iterable[Mapping[str, Any]],
    today_rows: Iterable[Mapping[str, Any]],
    rule: str,
) -> Optional[float]:
    """Cross-day promotion rate (percentage); ``None`` when undefined."""
    previous = {str(row.get("code") or ""): _streak(row) for row in previous_rows}
    today = {str(row.get("code") or ""): _streak(row) for row in today_rows}
    if rule == "1to2":
        base = {code: streak for code, streak in previous.items() if streak == 1}
        hit = sum(1 for code in base if today.get(code) == 2)
    elif rule == "2to3":
        base = {code: streak for code, streak in previous.items() if streak == 2}
        hit = sum(1 for code in base if today.get(code) == 3)
    elif rule == "3up":
        base = {code: streak for code, streak in previous.items() if streak is not None and streak >= 3}
        hit = sum(
            1
            for code, streak in base.items()
            if today.get(code) is not None and today[code] >= streak + 1
        )
    else:
        raise ValueError(f"unknown promotion rule: {rule}")
    if not base:
        return None
    return round(hit / len(base) * 100.0, 2)


def by_industry(
    zt_rows: Iterable[Mapping[str, Any]],
    zb_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group both pools by the vendor ``hybk`` industry field (industry view)."""
    zt_rows = list(zt_rows)
    zb_rows = list(zb_rows)
    groups: dict[str, dict[str, Any]] = {}

    def bucket(name: Optional[str]) -> Optional[dict[str, Any]]:
        text = str(name or "").strip()
        if not text:
            return None
        return groups.setdefault(
            text,
            {"industry": text, "zt_count": 0, "zb_count": 0, "max_streak": 0, "leaders": []},
        )

    for row in zt_rows:
        item = bucket(row.get("industry"))
        if item is None:
            continue
        item["zt_count"] += 1
        streak = _streak(row)
        if streak is not None and streak > item["max_streak"]:
            item["max_streak"] = streak
    for row in zb_rows:
        item = bucket(row.get("industry"))
        if item is None:
            continue
        item["zb_count"] += 1
    leaders: dict[str, list[dict[str, Any]]] = {}
    for row in sort_pool_rows(zt_rows, "zt"):
        item = bucket(row.get("industry"))
        if item is None:
            continue
        leaders.setdefault(item["industry"], []).append(
            {
                "code": row.get("code"),
                "name": row.get("name"),
                "streak": _streak(row),
                "change_pct": _number(row, "change_pct"),
            }
        )
    for name, rows in leaders.items():
        groups[name]["leaders"] = rows[:3]
    return sorted(
        groups.values(),
        key=lambda item: (-item["zt_count"], -item["zb_count"], item["industry"]),
    )


def filter_theme_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop derivative concepts such as ``昨日涨停`` / ``昨日连板``."""
    return [row for row in rows if "昨日" not in str(row.get("name") or "")]


def _exchange_code(raw: Any) -> Optional[str]:
    text = str(raw or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    if len(text) != 6 or not text.isdigit():
        return None
    if text.startswith(("6", "9")):
        return f"{text}.SH"
    if text.startswith(("4", "8", "92")):
        return f"{text}.BJ"
    return f"{text}.SZ"


def theme_rows(
    rows: Iterable[Mapping[str, Any]],
    limit: int,
    *,
    require_bk: bool = True,
) -> list[dict[str, Any]]:
    """Rank the vendor-ordered concept list after filtering derivative concepts.

    ``require_bk=False`` keeps Sina concept keys (``gn_*``), which are not
    vendor ``BKxxxx`` codes; the fallback payload sets ``taxonomy`` instead.
    """
    result: list[dict[str, Any]] = []
    for row in filter_theme_rows(rows):
        code = str(row.get("code") or "")
        if require_bk and (len(code) != 6 or not code.startswith("BK") or not code[2:].isdigit()):
            continue
        leader = None
        leader_code = _exchange_code(row.get("leader_code"))
        if leader_code:
            leader = {
                "code": leader_code,
                "name": row.get("leader_name") or "",
                "change_pct": _number(row, "leader_change_pct"),
            }
        result.append(
            {
                "rank": len(result) + 1,
                "code": code,
                "name": row.get("name"),
                "change_pct": _number(row, "change_pct"),
                "amount_yuan": _number(row, "amount_yuan"),
                "up_count": row.get("up"),
                "down_count": row.get("down"),
                "leader": leader,
            }
        )
        if len(result) >= limit:
            break
    return result


def _pct_change(price: Any, prev_close: Any) -> Optional[float]:
    try:
        price_value = float(price)
        prev_value = float(prev_close)
    except (TypeError, ValueError):
        return None
    if prev_value <= 0 or price_value <= 0:
        return None
    return (price_value / prev_value - 1.0) * 100.0


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def yesterday_payload(
    previous_rows: Iterable[Mapping[str, Any]],
    quotes: Mapping[str, Any],
) -> dict[str, Any]:
    """Open/high/low/current change versus the *snapshot's* previous close.

    ``quotes`` maps ``NNNNNN.SH/SZ`` to an object exposing ``open``, ``high``,
    ``low``, ``price`` and ``prev_close`` (Tencent rows/quotes).  Rows without a
    usable quote are omitted rather than filled with zeros.
    """
    rows: list[dict[str, Any]] = []
    opens: list[float] = []
    highs: list[float] = []
    closes: list[float] = []
    for item in sort_pool_rows(previous_rows, "zt"):
        code = str(item.get("code") or "")
        quote = quotes.get(code)
        if quote is None:
            continue
        prev_close = getattr(quote, "prev_close", None)
        open_pct = _pct_change(getattr(quote, "open", None), prev_close)
        high_pct = _pct_change(getattr(quote, "high", None), prev_close)
        low_pct = _pct_change(getattr(quote, "low", None), prev_close)
        now_pct = _pct_change(getattr(quote, "price", None), prev_close)
        if open_pct is not None:
            opens.append(open_pct)
        if high_pct is not None:
            highs.append(high_pct)
        if now_pct is not None:
            closes.append(now_pct)
        rows.append(
            {
                "code": code,
                "name": item.get("name"),
                "prev_streak": _streak(item),
                "open_pct": None if open_pct is None else round(open_pct, 2),
                "high_pct": None if high_pct is None else round(high_pct, 2),
                "low_pct": None if low_pct is None else round(low_pct, 2),
                "now_pct": None if now_pct is None else round(now_pct, 2),
            }
        )
    win_ratio = (
        round(sum(1 for value in closes if value > 0) / len(closes) * 100.0, 2)
        if closes
        else None
    )
    return {
        "avg_open_pct": _mean(opens),
        "avg_high_pct": _mean(highs),
        "avg_close_pct": _mean(closes),
        "win_ratio_pct": win_ratio,
        "rows": rows,
    }
