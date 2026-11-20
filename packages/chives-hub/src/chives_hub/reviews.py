"""Review storage (strict schema) and the review data package built by the hub.

The data package is assembled from market-watch and the private portfolio view.
Anything the hub cannot fetch goes into ``missing``; nothing is invented.  On a
non-trading day only the four-field short package is returned.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional

from .calendar import TradingCalendar
from .models import CN_TZ, fmt_iso
from .plans import normalize_code
from .validation import ApiError, as_bool, as_int, clean_body, clean_text, only

REVIEW_KINDS = {"evening", "premarket"}
SAVE_FIELDS = {
    "date",
    "kind",
    "env",
    "mainline",
    "themes",
    "ladder_note",
    "lhb_note",
    "events",
    "yesterday_feedback",
    "candidates",
    "pending",
    "data_cutoff",
    "sources",
    "checklist",
    "body_markdown",
}
MAX_CANDIDATES = 5
REGIME_MAP = {"risk_on": "strong", "neutral": "neutral", "risk_off": "weak"}


def _review_date(raw: Any) -> str:
    if not isinstance(raw, str) or len(raw.strip()) != 10:
        raise ApiError("invalid_date", "date 必须是 YYYY-MM-DD")
    try:
        date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ApiError("invalid_date", "date 必须是 YYYY-MM-DD") from exc
    return raw.strip()


def validate_review(payload: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, SAVE_FIELDS)
    if "date" not in payload:
        raise ApiError("invalid_date", "date 必填")
    day = _review_date(payload.get("date"))
    kind = payload.get("kind")
    if kind not in REVIEW_KINDS:
        raise ApiError("invalid_kind", "kind 只接受 evening/premarket")

    env_raw = payload.get("env")
    if env_raw is None:
        raise ApiError("invalid_env", "env 必填")
    if not isinstance(env_raw, dict):
        raise ApiError("invalid_env", "env 必须是对象")
    only(env_raw, {"label", "evidence", "differs_from_rule", "differs_note"})
    label = env_raw.get("label")
    if label not in {"strong", "neutral", "weak"}:
        raise ApiError("invalid_env", "env.label 只接受 strong/neutral/weak")
    evidence_raw = env_raw.get("evidence", [])
    if not isinstance(evidence_raw, list):
        raise ApiError("invalid_env", "env.evidence 必须是数组")
    if len(evidence_raw) > 8:
        raise ApiError("too_many_evidence", "env.evidence 最多 8 条")
    evidence = [clean_text(item, "env.evidence", 80) for item in evidence_raw]
    env = {
        "label": label,
        "evidence": evidence,
        "differs_from_rule": as_bool(env_raw.get("differs_from_rule"), "env.differs_from_rule")
        if "differs_from_rule" in env_raw
        else False,
    }
    if env_raw.get("differs_note") is not None:
        env["differs_note"] = clean_text(env_raw.get("differs_note"), "env.differs_note", 120)

    mainline = _mainline(payload.get("mainline"))
    themes_raw = payload.get("themes") or []
    if not isinstance(themes_raw, list):
        raise ApiError("invalid_themes", "themes 必须是数组")
    if len(themes_raw) > 6:
        raise ApiError("too_many_themes", "themes 最多 6 条")
    themes = []
    for item in themes_raw:
        if not isinstance(item, dict):
            raise ApiError("invalid_themes", "themes 必须是对象数组")
        only(item, {"name", "note"})
        themes.append(
            {
                "name": clean_text(item.get("name"), "themes.name", 40),
                "note": clean_text(item.get("note"), "themes.note", 120, allow_empty=True),
            }
        )

    ladder_note = _optional_text(payload.get("ladder_note"), "ladder_note", 200)
    lhb_note = _optional_text(payload.get("lhb_note"), "lhb_note", 300)
    yesterday_feedback = _optional_text(
        payload.get("yesterday_feedback"), "yesterday_feedback", 300
    )
    events = _events(payload.get("events") or [])
    candidates = _candidates(payload.get("candidates") or [])
    pending = _pending(payload.get("pending") or [])
    data_cutoff = _optional_text(payload.get("data_cutoff"), "data_cutoff", 10)
    sources = _sources(payload.get("sources") or [])
    checklist = _checklist(payload.get("checklist") or [])
    body_markdown = clean_body(payload.get("body_markdown", ""), max_chars=20000)

    return {
        "date": day,
        "kind": kind,
        "env": env,
        "mainline": mainline,
        "themes": themes,
        "ladder_note": ladder_note,
        "lhb_note": lhb_note,
        "events": events,
        "yesterday_feedback": yesterday_feedback,
        "candidates": candidates,
        "pending": pending,
        "data_cutoff": data_cutoff,
        "sources": sources,
        "checklist": checklist,
        "body_markdown": body_markdown,
    }


def _mainline(raw: Any) -> Optional[dict[str, Any]]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiError("invalid_mainline", "mainline 必须是对象或 null")
    only(raw, {"name", "note"})
    return {
        "name": clean_text(raw.get("name"), "mainline.name", 40),
        "note": clean_text(raw.get("note"), "mainline.note", 120, allow_empty=True),
    }


def _optional_text(raw: Any, field: str, limit: int) -> Optional[str]:
    if raw is None:
        return None
    return clean_text(raw, field, limit, allow_empty=True) or None


def _events(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ApiError("invalid_events", "events 必须是数组")
    if len(raw) > 12:
        raise ApiError("too_many_events", "events 最多 12 条")
    events = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("invalid_events", "events 必须是对象数组")
        only(item, {"date", "target", "type", "source", "uncertain", "note"})
        events.append(
            {
                "date": clean_text(item.get("date"), "events.date", 10),
                "target": clean_text(item.get("target"), "events.target", 40),
                "type": clean_text(item.get("type"), "events.type", 20),
                "source": clean_text(item.get("source"), "events.source", 40),
                "uncertain": as_bool(item.get("uncertain"), "events.uncertain")
                if "uncertain" in item
                else False,
                "note": clean_text(item.get("note", ""), "events.note", 80, allow_empty=True),
            }
        )
    return events


def _candidates(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ApiError("invalid_candidates", "candidates 必须是数组")
    if len(raw) > MAX_CANDIDATES:
        raise ApiError("too_many_candidates", f"candidates 最多 {MAX_CANDIDATES} 个")
    candidates = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("invalid_candidates", "candidates 必须是对象数组")
        only(item, {"code", "reason", "card_id", "tags"})
        tags_raw = item.get("tags") or {}
        if not isinstance(tags_raw, dict):
            raise ApiError("invalid_candidates", "candidates.tags 必须是对象")
        only(tags_raw, {"streak", "theme", "env"})
        tags: dict[str, Any] = {}
        if tags_raw.get("streak") is not None:
            tags["streak"] = as_int(tags_raw.get("streak"), "tags.streak", minimum=0, maximum=100)
        if tags_raw.get("theme") is not None:
            tags["theme"] = clean_text(tags_raw.get("theme"), "tags.theme", 40, allow_empty=True)
        if tags_raw.get("env") is not None:
            if tags_raw.get("env") not in {"strong", "neutral", "weak"}:
                raise ApiError("invalid_candidates", "tags.env 只接受 strong/neutral/weak")
            tags["env"] = tags_raw["env"]
        card_id = item.get("card_id")
        if card_id is not None:
            card_id = as_int(card_id, "card_id", minimum=1)
        candidates.append(
            {
                "code": normalize_code(item.get("code")),
                "reason": clean_text(item.get("reason"), "candidates.reason", 120),
                "card_id": card_id,
                "tags": tags,
            }
        )
    return candidates


def _pending(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ApiError("invalid_pending", "pending 必须是数组")
    if len(raw) > 10:
        raise ApiError("too_many_pending", "pending 最多 10 条")
    return [clean_text(item, "pending", 80) for item in raw]


def _sources(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        raise ApiError("invalid_sources", "sources 必须是数组")
    if len(raw) > 10:
        raise ApiError("too_many_sources", "sources 最多 10 条")
    return [clean_text(item, "sources", 80) for item in raw]


def _checklist(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ApiError("invalid_checklist", "checklist 必须是数组")
    if len(raw) > 12:
        raise ApiError("too_many_checklist", "checklist 最多 12 条")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise ApiError("invalid_checklist", "checklist 必须是对象数组")
        only(item, {"item", "ok", "note"})
        entry = {
            "item": clean_text(item.get("item"), "checklist.item", 60),
            "ok": as_bool(item.get("ok"), "checklist.ok"),
        }
        if item.get("note") is not None:
            entry["note"] = clean_text(item.get("note"), "checklist.note", 80, allow_empty=True)
        result.append(entry)
    return result


# -- data package --------------------------------------------------------
def _safe(missing: list[dict[str, Any]], part: str, call: Any) -> Optional[dict[str, Any]]:
    try:
        payload = call()
    except Exception as exc:  # noqa: BLE001 - a dead upstream is a "missing" entry
        missing.append({"part": part, "reason": type(exc).__name__})
        return None
    if not isinstance(payload, dict):
        missing.append({"part": part, "reason": "invalid_payload"})
        return None
    if payload.get("ok") is False:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        missing.append({"part": part, "reason": str(code or "upstream_error")})
        return None
    return payload


def _slim_indexes(overview: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = overview.get("indexes") if isinstance(overview, Mapping) else None
    result = []
    for item in (rows or [])[:6]:
        if isinstance(item, dict):
            result.append(
                {
                    "code": item.get("code"),
                    "name": item.get("name"),
                    "price": item.get("price"),
                    "change_pct": item.get("change_pct"),
                    "amount_yuan": item.get("amount_yuan"),
                }
            )
    return result


def _breadth(overview: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    raw = overview.get("breadth") if isinstance(overview, Mapping) else None
    raw = raw if isinstance(raw, dict) else {}
    return {
        key: raw.get(key)
        for key in (
            "up",
            "down",
            "flat",
            "up_ratio",
            "limit_up",
            "limit_down",
            "broken",
            "seal_ratio",
            "max_streak",
        )
    }


def build_review_data(
    *,
    sources: Any,
    store: Any,
    settings_service: Any,
    portfolio: Any,
    calendar: TradingCalendar,
    discipline_payload: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    today = now.astimezone(CN_TZ).date()
    next_day = calendar.next_trading_day(today).isoformat()
    if not calendar.is_trading_day(today):
        return {
            "ok": True,
            "trading_day": False,
            "date": today.isoformat(),
            "next_trading_day": next_day,
        }

    missing: list[dict[str, Any]] = []
    overview = _safe(missing, "market.overview", lambda: sources.market_overview(now=now))
    regime = (
        (overview.get("regime") or {}).get("label") if isinstance(overview, Mapping) else None
    )
    env_label = REGIME_MAP.get(str(regime)) if regime is not None else None
    if env_label is None:
        missing.append({"part": "env.regime", "reason": "regime_unavailable"})
    env = {
        "regime": env_label,
        "rule_label": regime,
        "evidence": (
            list((overview.get("regime") or {}).get("reasons") or [])[:8]
            if isinstance(overview, Mapping)
            else []
        ),
    }

    breadth = _breadth(overview)
    amount_yuan = None
    if isinstance(overview, Mapping):
        amount_yuan = (overview.get("breadth") or {}).get("amount_yuan")
    amount_vs_prev = None
    if isinstance(overview, Mapping):
        amount_vs_prev = overview.get("amount_vs_prev")
        if amount_vs_prev is None:
            amount_vs_prev = (overview.get("breadth") or {}).get("amount_vs_prev_pct")
        previous_amount = (overview.get("breadth") or {}).get("amount_prev_yuan")
        if amount_vs_prev is None and amount_yuan and previous_amount:
            amount_vs_prev = round((float(amount_yuan) / float(previous_amount) - 1.0) * 100.0, 4)
    pools: dict[str, Optional[dict[str, Any]]] = {}
    for kind in ("zt", "zb", "dt"):
        pools[kind] = _safe(
            missing, f"pool.{kind}", lambda kind=kind: sources.market_pool(kind, now=now)
        )
    counts = {
        "zt": (pools["zt"] or {}).get("count"),
        "zb": (pools["zb"] or {}).get("count"),
        "dt": (pools["dt"] or {}).get("count"),
    }
    seal_ratio = breadth.get("seal_ratio")
    if seal_ratio is None and counts["zt"] is not None and counts["zb"] is not None:
        denominator = int(counts["zt"]) + int(counts["zb"])
        seal_ratio = (int(counts["zt"]) / denominator * 100.0) if denominator else None
    ladder_payload = _safe(missing, "pool.ladder", lambda: sources.market_pool_ladder(now=now))
    ladder: list[dict[str, Any]] = []
    if isinstance(ladder_payload, Mapping):
        for tier in (ladder_payload.get("tiers") or [])[:10]:
            if not isinstance(tier, dict):
                continue
            rows = tier.get("rows") or []
            top = [
                {"code": row.get("code"), "name": row.get("name")}
                for row in rows[:3]
                if isinstance(row, dict)
            ]
            ladder.append({"streak": tier.get("streak"), "count": tier.get("count"), "top": top})
    max_streak = breadth.get("max_streak")
    if max_streak is None and isinstance(ladder_payload, Mapping):
        max_streak = ladder_payload.get("max_streak")
    by_industry_payload = _safe(
        missing, "pool.by_industry", lambda: sources.market_pool_by_industry(now=now)
    )
    by_industry = []
    if isinstance(by_industry_payload, Mapping):
        by_industry = [
            row for row in (by_industry_payload.get("rows") or [])[:10] if isinstance(row, dict)
        ]
    history_payload = _safe(
        missing, "pool.history", lambda: sources.market_pool_history(10, now=now)
    )
    history = []
    if isinstance(history_payload, Mapping):
        history = [
            row for row in (history_payload.get("days") or [])[-10:] if isinstance(row, dict)
        ]
    yesterday_payload = _safe(
        missing, "pool.yesterday", lambda: sources.market_pool_yesterday(now=now)
    )
    yesterday = None
    if isinstance(yesterday_payload, Mapping):
        yesterday = {
            key: yesterday_payload.get(key)
            for key in ("avg_open_pct", "avg_close_pct", "win_ratio_pct")
        }

    themes_payload = _safe(
        missing, "themes", lambda: sources.market_themes(limit=10, now=now)
    )
    themes = []
    if isinstance(themes_payload, Mapping):
        themes = [
            row for row in (themes_payload.get("rows") or [])[:10] if isinstance(row, dict)
        ]
    sectors_payload = _safe(
        missing, "sectors", lambda: sources.market_sectors("sw1", now=now)
    )
    sectors = []
    if isinstance(sectors_payload, Mapping):
        sectors = [
            row for row in (sectors_payload.get("rows") or [])[:10] if isinstance(row, dict)
        ]
    flows_payload = _safe(
        missing, "flows", lambda: sources.market_flows("sector_in", limit=5, now=now)
    )
    flows = []
    if isinstance(flows_payload, Mapping):
        flows = [
            row for row in (flows_payload.get("rows") or [])[:5] if isinstance(row, dict)
        ]

    try:
        portfolio_payload = portfolio.overview()
    except Exception as exc:  # noqa: BLE001
        missing.append({"part": "holdings", "reason": type(exc).__name__})
        portfolio_payload = {}
    positions = []
    for item in portfolio_payload.get("positions") or []:
        if not isinstance(item, dict):
            continue
        positions.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "weight_pct": item.get("weight_pct"),
                "pnl_pct": item.get("pnl_pct"),
                "industry": item.get("industry"),
            }
        )
    holdings = {
        "empty": not positions,
        "positions": positions,
        "totals": portfolio_payload.get("totals") or {},
        "limits": discipline_payload.get("headroom") or {},
        "private": True,
    }

    open_cards = [
        _slim_card(card, store)
        for card in store.list_cards()
        if card["status"] in {"proposed", "active"}
    ]
    previous_day = _previous_trading_day(calendar, today)
    yesterday_cards = [
        {**_slim_card(card, store), "outcome": card.get("outcome")}
        for card in store.list_cards()
        if card.get("review_date") == previous_day.isoformat()
    ]

    latest = store.latest_review()
    last_review = None
    if latest is not None:
        payload = latest["payload"]
        last_review = {
            "date": latest["date"],
            "env_label": ((payload.get("env") or {}).get("label")),
            "candidates": [item.get("code") for item in payload.get("candidates") or []],
        }

    settings_values = settings_service.adopted()
    settings_payload = []
    for key, value in sorted(settings_values.items()):
        item = settings_service.item(key)
        settings_payload.append(
            {
                "key": key,
                "label": item["label"],
                "unit": item["unit"],
                "value": value,
                "source": item["source"],
            }
        )
    settings_payload += settings_service.unadopted_suggestions()

    return {
        "ok": True,
        "private": True,
        "as_of": fmt_iso(now),
        "trading_day": True,
        "date": today.isoformat(),
        "next_trading_day": next_day,
        "data_cutoff": now.astimezone(CN_TZ).strftime("%H:%M"),
        "env": env,
        "market": {
            "indexes": _slim_indexes(overview),
            "breadth": breadth,
            "amount_yuan": amount_yuan,
            "amount_vs_prev": amount_vs_prev,
        },
        "pool": {
            "counts": counts,
            "seal_ratio_pct": seal_ratio,
            "max_streak": max_streak,
            "ladder": ladder,
            "by_industry": by_industry,
            "history": history,
            "yesterday": yesterday,
        },
        "themes": themes,
        "sectors": sectors,
        "flows": flows,
        "holdings": holdings,
        "cards": {"open": open_cards, "yesterday_cards": yesterday_cards},
        "settings": settings_payload,
        "discipline": dict(discipline_payload),
        "last_review": last_review,
        "missing": missing,
    }


def _slim_card(card: Mapping[str, Any], store: Any) -> dict[str, Any]:
    return {
        "id": card["id"],
        "code": card["code"],
        "name": card["name"],
        "status": card["status"],
        "state": card["state"],
        "review_date": card.get("review_date"),
        "thesis": card.get("thesis"),
        "expires_at": fmt_iso(card.get("expires_at")),
    }


def _previous_trading_day(calendar: TradingCalendar, today: date) -> date:
    current = today - timedelta(days=1)
    for _ in range(370):
        if calendar.is_trading_day(current):
            return current
        current -= timedelta(days=1)
    return today


def review_list_payload(store: Any, *, limit: int = 20, kind: Optional[str] = None) -> dict[str, Any]:
    rows = store.list_reviews(limit=limit, kind=kind)
    items = []
    for row in rows:
        payload = row["payload"]
        items.append(
            {
                "date": row["date"],
                "kind": row["kind"],
                "revision": row["revision"],
                "env_label": ((payload.get("env") or {}).get("label")),
                "candidate_count": len(payload.get("candidates") or []),
                "updated_at": fmt_iso(row["updated_at"]),
            }
        )
    return {"ok": True, "reviews": items, "count": len(items)}


def review_detail_payload(store: Any, day: str, kind: str) -> Optional[dict[str, Any]]:
    row = store.get_review(day, kind)
    if row is None:
        return None
    body = {
        **row["payload"],
        "date": row["date"],
        "kind": row["kind"],
        "revision": row["revision"],
        "updated_at": fmt_iso(row["updated_at"]),
        "untrusted_text": True,
    }
    return {"ok": True, "review": body, "private": True, "untrusted_text": True}
