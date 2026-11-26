"""Discipline checks driven only by adopted / user-set thresholds.

Nothing here blocks an action; a pause is a flag plus one signal per reason per
day.  Mood and the manually recorded loss streak stay in the local hub DB and
are never logged.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping, Optional

from .models import CN_TZ
from .settings import SettingsService
from .validation import ApiError, clean_text, only

MOOD_SLOTS = ("pre", "mid", "post")
MOOD_LEVELS = ("calm", "volatile", "unfit")
THRESHOLD_KEYS = {
    "day_drawdown": "pause_day_drawdown_pct",
    "total_loss": "pause_total_loss_pct",
    "loss_streak": "pause_loss_streak",
}
LOSS_STREAK_KV = "discipline.loss_streak"


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def loss_streak(store: Any) -> int:
    raw = store.get_kv(LOSS_STREAK_KV)
    return int(raw) if isinstance(raw, int) and raw >= 0 else 0


def apply_loss_streak(store: Any, payload: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, {"action"})
    action = payload.get("action")
    if action not in {"add", "reset"}:
        raise ApiError("invalid_action", "action 只接受 add/reset")
    value = 0 if action == "reset" else loss_streak(store) + 1
    store.set_kv(LOSS_STREAK_KV, value)
    return {"ok": True, "loss_streak": value}


def apply_mood(store: Any, payload: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, {"slot", "level", "note"})
    slot = payload.get("slot")
    if slot not in MOOD_SLOTS:
        raise ApiError("invalid_slot", "slot 只接受 pre/mid/post")
    level = payload.get("level")
    if level not in MOOD_LEVELS:
        raise ApiError("invalid_level", "level 只接受 calm/volatile/unfit")
    note: Optional[str] = None
    if payload.get("note") is not None:
        note = clean_text(payload.get("note"), "note", 60, allow_empty=True) or None
    day = now.astimezone(CN_TZ).date().isoformat()
    store.save_mood(day, slot, level, note, now)
    return {"ok": True, "mood_today": mood_today(store, now)}


def mood_today(store: Any, now: datetime) -> dict[str, Optional[str]]:
    rows = store.get_mood(_day(now))
    return {slot: (rows.get(slot) or {}).get("level") for slot in MOOD_SLOTS}


def _day(now: datetime) -> str:
    return now.date().isoformat()


def day_drawdown_pct(store: Any, overview: Mapping[str, Any], now: datetime) -> Optional[float]:
    totals = overview.get("totals") if isinstance(overview, Mapping) else None
    current = _finite((totals or {}).get("total_assets_cny"))
    if current is None or current <= 0:
        return None
    previous: Optional[float] = None
    for row in reversed(store.list_snapshots(90)):
        if row["day"] < now.date().isoformat():
            previous = _finite(row.get("total_assets_cny"))
            break
    if previous is None or previous <= 0:
        return None
    return max(0.0, (previous - current) / previous * 100.0)


def total_loss_pct(overview: Mapping[str, Any]) -> Optional[float]:
    totals = overview.get("totals") if isinstance(overview, Mapping) else None
    cost = _finite((totals or {}).get("cost_cny"))
    pnl = _finite((totals or {}).get("pnl_cny"))
    if cost is None or pnl is None:
        positions = overview.get("positions") if isinstance(overview, Mapping) else None
        cost = 0.0
        pnl = 0.0
        found = False
        for item in positions or []:
            if not isinstance(item, Mapping):
                continue
            quantity = _finite(item.get("qty"))
            price = _finite(item.get("cost_price_cny"))
            item_pnl = _finite(item.get("pnl_cny"))
            if quantity is not None and price is not None:
                cost += quantity * price
                found = True
            if item_pnl is not None:
                pnl += item_pnl
                found = True
        if not found:
            return None
    if cost <= 0:
        return None
    return max(0.0, -pnl / cost * 100.0)


def thresholds(settings: SettingsService) -> dict[str, Optional[float]]:
    return {key: settings.value(key) for key in THRESHOLD_KEYS.values()}


def paused_reasons(
    metrics: Mapping[str, Optional[float]], limits: Mapping[str, Optional[float]]
) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    specs = (
        ("day_drawdown", "day_drawdown_pct", "当日回撤"),
        ("total_loss", "total_loss_pct", "持仓累计浮亏"),
        ("loss_streak", "loss_streak", "连亏笔数"),
    )
    for rule, metric_key, label in specs:
        value = metrics.get(metric_key)
        limit = limits.get(rule)
        if value is None or limit is None:
            continue
        if float(value) < float(limit):
            continue
        if rule == "loss_streak":
            text = f"{label} {int(value)} 笔达到暂停线 {int(limit)} 笔"
        else:
            text = f"{label} {float(value):.2f}% 达到暂停线 {float(limit):g}%"
        reasons.append({"rule": rule, "value": value, "threshold": limit, "text": text})
    return reasons


def headroom(
    overview: Mapping[str, Any],
    settings: SettingsService,
    *,
    regime: Optional[str],
) -> dict[str, Any]:
    totals = overview.get("totals") if isinstance(overview, Mapping) else None
    positions = overview.get("positions") if isinstance(overview, Mapping) else None
    positions = [item for item in positions or [] if isinstance(item, Mapping)]
    position_ratio = _finite((totals or {}).get("position_ratio_pct"))
    total_cap = settings.total_cap_for(regime)
    total_room = (
        max(0.0, total_cap - position_ratio)
        if total_cap is not None and position_ratio is not None
        else None
    )

    weights = [
        (_finite(item.get("weight_pct")) or 0.0) for item in positions if item.get("weight_pct") is not None
    ]
    top_weight = max(weights) if weights else 0.0
    single_cap = settings.value("single_stock_cap_pct")
    single_room = max(0.0, single_cap - top_weight) if single_cap is not None else None

    theme_totals: dict[str, float] = {}
    for item in positions:
        weight = _finite(item.get("weight_pct"))
        if weight is None:
            continue
        name = item.get("industry") or item.get("theme") or "未分类"
        theme_totals[str(name)] = theme_totals.get(str(name), 0.0) + weight
    top_theme = None
    if theme_totals:
        name, weight = max(theme_totals.items(), key=lambda pair: (pair[1], pair[0]))
        top_theme = {"name": name, "weight_pct": round(weight, 4)}
    theme_cap = settings.value("theme_cap_pct")
    theme_room = (
        max(0.0, theme_cap - (top_theme["weight_pct"] if top_theme else 0.0))
        if theme_cap is not None
        else None
    )

    return {
        "total_cap_pct": total_cap,
        "position_ratio_pct": position_ratio,
        "total_room_pct": total_room,
        "single_cap_pct": single_cap,
        "top_weight_pct": top_weight,
        "single_room_pct": single_room,
        "theme_cap_pct": theme_cap,
        "top_theme": top_theme,
        "theme_room_pct": theme_room,
    }


def discipline_payload(
    *,
    store: Any,
    settings: SettingsService,
    overview: Mapping[str, Any],
    now: datetime,
    regime: Optional[str] = None,
) -> dict[str, Any]:
    metrics = {
        "day_drawdown_pct": day_drawdown_pct(store, overview, now),
        "total_loss_pct": total_loss_pct(overview),
        "loss_streak": loss_streak(store),
    }
    limits = thresholds(settings)
    rule_limits = {
        "day_drawdown": limits["pause_day_drawdown_pct"],
        "total_loss": limits["pause_total_loss_pct"],
        "loss_streak": limits["pause_loss_streak"],
    }
    reasons = paused_reasons(metrics, rule_limits)
    return {
        "ok": True,
        "paused": bool(reasons),
        "reasons": reasons,
        "metrics": metrics,
        "thresholds": {key: value for key, value in limits.items() if value is not None},
        "mood_today": mood_today(store, now),
        "headroom": headroom(overview, settings, regime=regime),
    }


def trading_day_key(day: date) -> str:
    return day.isoformat()
