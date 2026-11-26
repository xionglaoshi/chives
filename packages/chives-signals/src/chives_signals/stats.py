"""Deterministic candidate outcome statistics (sample < 30 is not extrapolated)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional

from .models import CN_TZ


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_outcome(
    card: Mapping[str, Any],
    quote: Optional[Mapping[str, Any]],
    *,
    history: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    quote = quote or {}
    prev_close = _num(quote.get("prev_close"))
    open_price = _num(quote.get("open"))
    high = _num(quote.get("high"))
    low = _num(quote.get("low"))
    close = _num(quote.get("price"))

    def pct(value: Optional[float]) -> Optional[float]:
        if value is None or prev_close is None or prev_close <= 0:
            return None
        return round((value - prev_close) / prev_close * 100.0, 4)

    stop = _num((card.get("risk") or {}).get("stop_price"))
    stop_hit: Optional[bool] = None
    if stop is not None and low is not None:
        stop_hit = low <= stop
    elif stop is not None and close is not None:
        stop_hit = close <= stop
    reached: list[str] = []
    for item in history:
        state = item.get("to")
        if state and state not in reached:
            reached.append(state)
    return {
        "date": now.astimezone(CN_TZ).date().isoformat(),
        "triggered_execute": "execute" in reached,
        "reached_states": reached,
        "open_pct": pct(open_price),
        "high_pct": pct(high),
        "close_pct": pct(close),
        "stop_hit": stop_hit,
    }


def _metrics(rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    n = len(rows)
    triggered = sum(1 for _, outcome in rows if outcome.get("triggered_execute") is True)
    close_values = [
        _num(outcome.get("close_pct"))
        for _, outcome in rows
        if _num(outcome.get("close_pct")) is not None
    ]
    open_values = [
        _num(outcome.get("open_pct"))
        for _, outcome in rows
        if _num(outcome.get("open_pct")) is not None
    ]
    high_values = [
        _num(outcome.get("high_pct"))
        for _, outcome in rows
        if _num(outcome.get("high_pct")) is not None
    ]

    def avg(values: list[float]) -> Optional[float]:
        return round(sum(values) / len(values), 4) if values else None

    wins = sum(1 for value in close_values if value > 0)
    return {
        "n": n,
        "trigger_rate_pct": round(triggered / n * 100.0, 4) if n else None,
        "avg_open_pct": avg(open_values),
        "avg_high_pct": avg(high_values),
        "avg_close_pct": avg(close_values),
        "win_ratio_pct": round(wins / len(close_values) * 100.0, 4) if close_values else None,
    }


def stats_payload(store: Any, *, days: int, now: datetime) -> dict[str, Any]:
    cutoff = (now.astimezone(CN_TZ).date() - timedelta(days=max(0, days - 1))).isoformat()
    rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for card in store.list_cards():
        outcome = card.get("outcome")
        if not isinstance(outcome, dict):
            continue
        day = outcome.get("date")
        if not isinstance(day, str) or day < cutoff:
            continue
        rows.append((card, outcome))
    overall = _metrics(rows)

    by_env: dict[str, dict[str, Any]] = {}
    by_streak: dict[str, dict[str, Any]] = {}
    for card, outcome in rows:
        tags = card.get("tags") or {}
        env = tags.get("env") if tags.get("env") in {"strong", "neutral", "weak"} else "unknown"
        streak = tags.get("streak")
        streak_key = str(streak) if isinstance(streak, int) else "unknown"
        by_env.setdefault(env, []).append((card, outcome))
        by_streak.setdefault(streak_key, []).append((card, outcome))

    n = overall["n"]
    note = (
        "样本不足（n<30），仅供参考，不做外推"
        if n < 30
        else "样本 n≥30；历史胜率不代表未来表现"
    )
    return {
        "ok": True,
        "n": n,
        "days": days,
        "sample_insufficient": n < 30,
        "trigger_rate_pct": overall["trigger_rate_pct"],
        "avg_open_pct": overall["avg_open_pct"],
        "avg_high_pct": overall["avg_high_pct"],
        "avg_close_pct": overall["avg_close_pct"],
        "win_ratio_pct": overall["win_ratio_pct"],
        "by_env": {key: _metrics(value) for key, value in sorted(by_env.items())},
        "by_streak": {key: _metrics(value) for key, value in sorted(by_streak.items())},
        "note": note,
    }


def outcome_day(now: datetime) -> date:
    return now.astimezone(CN_TZ).date()
