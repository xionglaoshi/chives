"""Intraday guidance cards (deterministic, no model calls).

Five slots per trading day: 09:30, 10:00, 11:30, 13:00, 14:30.  A slot fires only
inside its five-minute window, at most once per day; a missed slot is never
back-filled and a restart cannot duplicate one (the ``(day, slot)`` row is unique).

``theme_state`` compares the leading industry sector with the previous guidance
slot of the same day:

* no current sector data -> ``未知``;
* first slot of the day -> ``延续`` when the leading sector is already in the top
  ``TOP_N``, otherwise ``分歧``;
* the rank slips by at least ``RANK_SLIP`` positions, or the limit-up count falls
  by at least ``max(LIMIT_DROP_MIN, LIMIT_DROP_RATIO * previous)`` -> ``走弱``;
* the rank improves and stays in the top ``TOP_N`` -> ``延续``;
* the rank holds inside the top ``TOP_N`` and the sector change does not fall by
  more than ``CHANGE_TOLERANCE`` points -> ``延续``;
* everything else -> ``分歧``.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Any, Mapping, Optional

from .models import CN_TZ

GUIDANCE_SLOTS: tuple[tuple[str, time], ...] = (
    ("09:30", time(9, 30)),
    ("10:00", time(10, 0)),
    ("11:30", time(11, 30)),
    ("13:00", time(13, 0)),
    ("14:30", time(14, 30)),
)
SLOT_NAMES = tuple(name for name, _ in GUIDANCE_SLOTS)
GUIDANCE_GRACE = timedelta(minutes=5)
TOP_N = 5
RANK_SLIP = 1
LIMIT_DROP_MIN = 5
LIMIT_DROP_RATIO = 0.2
CHANGE_TOLERANCE = 0.2
REGIME_LABELS = {"risk_on": "偏强", "neutral": "中性", "risk_off": "偏弱"}
STATE_ACTION = {
    "exit": "按计划退出",
    "abandon": "放弃",
    "execute": "按预案执行",
    "await_confirm": "等待确认",
    "observe": "观察",
}
LIVE_STATES = ("observe", "await_confirm", "execute")


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return None if number is None else int(number)


def due_slot(now: datetime, calendar: Any) -> Optional[str]:
    if not calendar.is_trading_day(now.date()):
        return None
    local = now.astimezone(CN_TZ)
    for name, moment in GUIDANCE_SLOTS:
        start = datetime.combine(local.date(), moment, tzinfo=CN_TZ)
        if start <= local < start + GUIDANCE_GRACE:
            return name
    return None


def next_check(slot: str) -> str:
    for index, name in enumerate(SLOT_NAMES):
        if name == slot:
            return SLOT_NAMES[index + 1] if index + 1 < len(SLOT_NAMES) else "15:00"
    return "15:00"


def theme_state(previous: Optional[Mapping[str, Any]], current: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(current, Mapping):
        return "未知"
    cur_rank = _int(current.get("rank"))
    if cur_rank is None:
        return "未知"
    if not isinstance(previous, Mapping):
        return "延续" if cur_rank <= TOP_N else "分歧"
    prev_rank = _int(previous.get("rank"))
    if prev_rank is None:
        return "延续" if cur_rank <= TOP_N else "分歧"
    if cur_rank - prev_rank >= RANK_SLIP:
        return "走弱"
    cur_limit = _int(current.get("limit_up_count"))
    prev_limit = _int(previous.get("limit_up_count"))
    if cur_limit is not None and prev_limit is not None:
        drop = prev_limit - cur_limit
        if drop >= max(LIMIT_DROP_MIN, prev_limit * LIMIT_DROP_RATIO):
            return "走弱"
    if cur_rank < prev_rank and cur_rank <= TOP_N:
        return "延续"
    if cur_rank == prev_rank and cur_rank <= TOP_N:
        cur_change = _num(current.get("change_pct"))
        prev_change = _num(previous.get("change_pct"))
        if (
            cur_change is None
            or prev_change is None
            or cur_change >= prev_change - CHANGE_TOLERANCE
        ):
            return "延续"
    return "分歧"


def _rank(row: Mapping[str, Any]) -> Optional[int]:
    rank = _int(row.get("rank"))
    return rank if rank is not None and rank >= 1 else None


def theme_snapshot(
    sources: Any,
    *,
    now: datetime,
    overview: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    try:
        payload = sources.market_sectors("sw1", now=now)
    except Exception:  # noqa: BLE001 - unknown theme state is allowed
        return None
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    rows = [row for row in rows or [] if isinstance(row, Mapping)]
    if not rows:
        return None
    best: Optional[Mapping[str, Any]] = None
    best_rank: Optional[int] = None
    for index, row in enumerate(rows):
        rank = _rank(row) or (index + 1)
        if best_rank is None or rank < best_rank:
            best = row
            best_rank = rank
    if best is None or best_rank is None:
        return None
    limit_up = None
    breadth = overview.get("breadth") if isinstance(overview, Mapping) else None
    if isinstance(breadth, Mapping):
        limit_up = _int(breadth.get("limit_up"))
    if limit_up is None:
        try:
            pool = sources.market_pool("zt", now=now)
        except Exception:  # noqa: BLE001
            pool = None
        if isinstance(pool, Mapping):
            limit_up = _int(pool.get("count"))
    return {
        "sector_code": str(best.get("code") or ""),
        "sector_name": str(best.get("name") or ""),
        "rank": best_rank,
        "change_pct": _num(best.get("change_pct")),
        "limit_up_count": limit_up,
    }


def market_state(overview: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    regime = overview.get("regime") if isinstance(overview, Mapping) else None
    raw = regime.get("label") if isinstance(regime, Mapping) else None
    label = REGIME_LABELS.get(str(raw))
    if label is None:
        return {"label": "未知", "basis": "市场环境取不到"}
    reasons = [str(item) for item in (regime.get("reasons") or []) if str(item).strip()]
    basis = "；".join(reasons)[:200] if reasons else "规则标签，无附注理由"
    return {"label": label, "basis": basis}


def current_action(cards: list[Mapping[str, Any]]) -> str:
    states = {str(card.get("state") or "") for card in cards}
    for state in ("exit", "abandon", "execute", "await_confirm", "observe"):
        if state in states:
            return STATE_ACTION[state]
    return "无预案"


def quick_cards(cards: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": card.get("id"),
            "code": card.get("code"),
            "name": card.get("name"),
            "state": card.get("state"),
        }
        for card in cards
    ]


def risk_bound(settings: Any, regime: Optional[str]) -> str:
    if settings is None:
        return "未设置"
    parts: list[str] = []
    total_cap = settings.total_cap_for(regime)
    if total_cap is not None:
        parts.append(f"总仓位≤{total_cap:g}%")
    single_cap = settings.value("single_stock_cap_pct")
    if single_cap is not None:
        parts.append(f"单票≤{single_cap:g}%")
    per_trade = settings.value("per_trade_risk_pct")
    if per_trade is not None:
        parts.append(f"单笔风险≤{per_trade:g}%")
    return "；".join(parts) if parts else "未设置"


def guidance_context(
    *,
    day: str,
    slot: str,
    now: datetime,
    overview: Optional[Mapping[str, Any]],
    cards: list[Mapping[str, Any]],
    theme: Optional[Mapping[str, Any]],
    previous_theme: Optional[Mapping[str, Any]],
    settings: Any,
    regime: Optional[str],
) -> dict[str, Any]:
    market = market_state(overview)
    return {
        "type": "guidance",
        "slot": slot,
        "data_time": now.astimezone(CN_TZ).strftime("%H:%M"),
        "market_state": market,
        "theme_state": theme_state(previous_theme, theme),
        "cards": quick_cards(cards),
        "current_action": current_action(cards),
        "next_check": next_check(slot),
        "risk_bound": risk_bound(settings, regime),
    }
