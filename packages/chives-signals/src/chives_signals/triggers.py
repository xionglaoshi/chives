"""Trigger queue, frozen context packs and one-shot judgements.

A trigger is a deterministic record of "the card state just moved" or "the
environment changed" or "an emergency rule fired".  The context pack is assembled
once, immediately after the transition, and frozen: later reads return the same
bytes.  It carries holdings, so it is ``private`` and must never be logged.

Nothing in this module calls a model or places an order.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime
from typing import Any, Mapping, Optional

from .models import fmt_iso, truncate
from .validation import ApiError, clean_text, only

TRIGGER_KINDS = {
    "card_execute",
    "card_abandon",
    "card_exit",
    "regime",
    "emergency",
}
CARD_TRIGGER_KINDS = {
    "execute": "card_execute",
    "abandon": "card_abandon",
    "exit": "card_exit",
}
JUDGEMENT_ACTIONS = ("observe", "await_confirm", "execute", "abandon", "exit")
JUDGEMENT_FIELDS = {"action", "reason", "next_check", "risk"}
JUDGEMENT_TEXT_LIMIT = 60
ACTION_LABELS = {
    "observe": "观察",
    "await_confirm": "等待确认",
    "execute": "按预案执行",
    "abandon": "放弃",
    "exit": "按计划退出",
}
MAX_CONTEXT_BYTES = 12 * 1024
MAX_CARD_HISTORY = 20
REGIME_LABELS = {"risk_on": "strong", "neutral": "neutral", "risk_off": "weak"}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return int(number) if math.isfinite(number) else None


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def trigger_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """Render a stored trigger exactly as the contract's trigger object."""
    ts = row.get("ts")
    return {
        "id": row.get("id"),
        "ts": fmt_iso(ts) if isinstance(ts, datetime) else ts,
        "kind": row.get("kind"),
        "card_id": row.get("card_id"),
        "code": row.get("code"),
        "name": row.get("name"),
        "from_state": row.get("from_state"),
        "to_state": row.get("to_state"),
        "reason": row.get("reason"),
        "context_ready": bool(row.get("context_ready")),
        "judged": row.get("judgement") is not None,
    }


def trigger_dedupe_key(kind: str, *, card_id: Optional[int], to_state: Optional[str]) -> str:
    return f"{kind}|{card_id if card_id is not None else '-'}|{to_state or '-'}"


# -- context blocks ------------------------------------------------------
def _review_summary(store: Any, code: Optional[str]) -> Optional[dict[str, Any]]:
    row = store.latest_review()
    if row is None:
        return None
    payload = row.get("payload") or {}
    env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    evidence = env.get("evidence")
    evidence = [str(item) for item in evidence][:8] if isinstance(evidence, list) else []
    mainline = payload.get("mainline")
    thesis: Optional[str] = None
    if code:
        for candidate in payload.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("code") == code:
                thesis = candidate.get("reason")
                break
    return {
        "date": payload.get("date") or row.get("date"),
        "env_label": env.get("label"),
        "evidence": evidence,
        "mainline": mainline if isinstance(mainline, dict) else None,
        "thesis_from_candidates": thesis,
    }


def _sector_rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    return [item for item in rows or [] if isinstance(item, dict)]


def _sector_block(
    card: Optional[Mapping[str, Any]],
    rows: list[dict[str, Any]],
    positions: list[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    wanted_code: Optional[str] = None
    if card:
        for cond in card.get("sector_conditions") or []:
            if isinstance(cond, dict) and cond.get("sector_code"):
                wanted_code = str(cond["sector_code"])
                break
    industry: Optional[str] = None
    card_code = str((card or {}).get("code") or "")
    if card_code:
        for position in positions:
            if position.get("code") == card_code:
                industry = position.get("industry") or position.get("theme")
                break
    for row in rows:
        code = str(row.get("code") or "")
        name = str(row.get("name") or "")
        if wanted_code and code == wanted_code:
            return {
                "code": code,
                "name": name,
                "rank": _int(row.get("rank")),
                "change_pct": _round(_num(row.get("change_pct"))),
            }
        if not wanted_code and industry and name == industry:
            return {
                "code": code,
                "name": name,
                "rank": _int(row.get("rank")),
                "change_pct": _round(_num(row.get("change_pct"))),
            }
    return None


def _limit_ratio(code: str) -> float:
    if code.startswith(("300", "301", "688", "689")):
        return 0.2
    return 0.1


def _limit_distance_pct(code: str, quote: Mapping[str, Any]) -> Optional[float]:
    price = _num(quote.get("price"))
    if price is None or price <= 0:
        return None
    up = _num(quote.get("limit_up"))
    down = _num(quote.get("limit_down"))
    prev_close = _num(quote.get("prev_close"))
    if prev_close is not None and prev_close > 0:
        ratio = _limit_ratio(code)
        if up is None:
            up = round(prev_close * (1 + ratio), 2)
        if down is None:
            down = round(prev_close * (1 - ratio), 2)
    distances = [abs(limit - price) / price * 100.0 for limit in (up, down) if limit]
    return _round(min(distances)) if distances else None


def _quote_block(code: str, quote: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if not quote:
        return None
    price = _num(quote.get("price"))
    if price is None:
        return None
    change = _num(quote.get("change_pct"))
    vwap = _num(quote.get("vwap"))
    vwap_dev = (price / vwap - 1.0) * 100.0 if vwap and vwap > 0 else None
    return {
        "price": _round(price),
        "change_pct": _round(change),
        "vwap_dev_pct": _round(vwap_dev),
        "limit_distance_pct": _limit_distance_pct(code, quote),
    }


def _market_block(overview: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(overview, Mapping):
        return None
    regime_raw = (overview.get("regime") or {}).get("label") if isinstance(overview.get("regime"), dict) else None
    regime = REGIME_LABELS.get(str(regime_raw))
    breadth_raw = overview.get("breadth") if isinstance(overview.get("breadth"), dict) else {}
    breadth: dict[str, Any] = {}
    up_ratio = _num(breadth_raw.get("up_ratio"))
    if up_ratio is not None:
        breadth["up_ratio"] = up_ratio
    for key in ("limit_up", "limit_down"):
        value = _int(breadth_raw.get(key))
        if value is not None:
            breadth[key] = value
    amount = _num(breadth_raw.get("amount_yuan"))
    if amount is None:
        amount = _num(overview.get("amount_yuan"))
    if regime is None and not breadth and amount is None:
        return None
    return {"regime": regime, "breadth": breadth or None, "amount_yuan": amount}


def _positions(overview: Optional[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if not isinstance(overview, Mapping):
        return []
    return [item for item in overview.get("positions") or [] if isinstance(item, Mapping)]


def _holdings_relation(
    overview: Optional[Mapping[str, Any]],
    code: Optional[str],
    settings: Any,
    regime: Optional[str],
) -> Optional[dict[str, Any]]:
    if not isinstance(overview, Mapping):
        return None
    from .discipline import headroom

    position = None
    if code:
        for item in _positions(overview):
            if item.get("code") == code:
                position = item
                break
    limits = headroom(overview, settings, regime=regime)
    return {
        "held": position is not None,
        "weight_pct": _round(_num((position or {}).get("weight_pct"))),
        "single_cap_pct": limits.get("single_cap_pct"),
        "total_room_pct": limits.get("total_room_pct"),
    }


def _snapshot(
    *,
    card: Optional[Mapping[str, Any]],
    sources: Any,
    overview_market: Optional[Mapping[str, Any]],
    positions: list[Mapping[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], list[str]]:
    missing: list[str] = []
    code = str((card or {}).get("code") or "")
    quote_raw: Optional[Mapping[str, Any]] = None
    quotes: dict[str, Any] = {}
    try:
        state = sources.cn_state(now=now)
    except Exception:  # noqa: BLE001 - a missing block is null + missing
        state = None
    if isinstance(state, Mapping) and isinstance(state.get("quotes"), Mapping):
        quotes = dict(state["quotes"])
        item = quotes.get(code) if code else None
        if isinstance(item, Mapping):
            quote_raw = item
    if code and quote_raw is None:
        try:
            fetched = sources.tencent_quotes([code], now=now)
        except Exception:  # noqa: BLE001
            fetched = None
        item = (fetched or {}).get(code)
        if isinstance(item, Mapping):
            quote_raw = item
        elif item is not None:
            quote_raw = {
                "price": getattr(item, "price", None),
                "prev_close": getattr(item, "prev_close", None),
                "change_pct": getattr(item, "change_pct", None),
                "name": getattr(item, "name", None),
            }
    quote = _quote_block(code, quote_raw) if code else None
    if code and quote is None:
        missing.append("snapshot.quote")
    sector = None
    rows: list[dict[str, Any]] = []
    try:
        sector_payload = sources.market_sectors("sw1", now=now)
    except Exception:  # noqa: BLE001
        sector_payload = None
    rows = _sector_rows(sector_payload)
    if code:
        sector = _sector_block(card, rows, positions)
        if sector is None:
            missing.append("snapshot.sector")
    market = _market_block(overview_market)
    if market is None:
        missing.append("snapshot.market")
    return (
        {"quote": quote, "sector": sector, "market": market},
        missing,
    )


def _discipline_block(payload: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return None
    mood = payload.get("mood_today")
    return {
        "paused": bool(payload.get("paused")),
        "mood_today": mood if isinstance(mood, Mapping) else {"pre": None, "mid": None, "post": None},
    }


def build_context_pack(
    *,
    trigger: Mapping[str, Any],
    card: Optional[Mapping[str, Any]],
    store: Any,
    settings: Any,
    sources: Any,
    portfolio_overview: Optional[Mapping[str, Any]],
    discipline: Optional[Mapping[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Assemble the context pack once; ``fit_context`` then caps it at 12 KB."""
    missing: list[str] = []
    from .cards import card_payload

    market_overview: Optional[Mapping[str, Any]] = None
    try:
        market_overview = sources.market_overview(now=now)
    except Exception:  # noqa: BLE001
        market_overview = None
    positions = _positions(portfolio_overview)
    snapshot, snapshot_missing = _snapshot(
        card=card,
        sources=sources,
        overview_market=market_overview,
        positions=positions,
        now=now,
    )
    missing.extend(snapshot_missing)

    review = _review_summary(store, str((card or {}).get("code") or "") or None)
    if review is None:
        missing.append("review")

    regime = (snapshot.get("market") or {}).get("regime")
    holdings = _holdings_relation(portfolio_overview, str((card or {}).get("code") or "") or None, settings, regime)
    if holdings is None:
        missing.append("holdings_relation")

    discipline_block = _discipline_block(discipline)
    if discipline_block is None:
        missing.append("discipline")

    pack: dict[str, Any] = {
        "trigger": trigger_payload(trigger),
        "card": None,
        "review": review,
        "snapshot": snapshot,
        "holdings_relation": holdings,
        "discipline": discipline_block,
        "thresholds": settings.adopted() if settings is not None else {},
        "today": {
            "trigger_count": store.count_triggers_today(
                now.date().isoformat(),
                card_id=trigger.get("card_id"),
            ),
            "fast_judgements_used": store.fast_judgements_used(now.date().isoformat()),
        },
        "missing": [],
        "trimmed": [],
    }
    if card is not None:
        pack["card"] = card_payload(card, store.list_card_history(card["id"]))
    else:
        missing.append("card")
    pack["missing"] = sorted(set(missing))
    pack["trigger"]["context_ready"] = True
    return fit_context(pack)


def _encoded_size(pack: Mapping[str, Any]) -> int:
    return len(json.dumps(pack, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _truncate_strings(node: Any, limit: int) -> bool:
    changed = False
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if isinstance(value, str) and len(value) > limit:
                node[key] = truncate(value, limit)
                changed = True
            elif isinstance(value, (dict, list)):
                changed = _truncate_strings(value, limit) or changed
    elif isinstance(node, list):
        for index, value in enumerate(list(node)):
            if isinstance(value, str) and len(value) > limit:
                node[index] = truncate(value, limit)
                changed = True
            elif isinstance(value, (dict, list)):
                changed = _truncate_strings(value, limit) or changed
    return changed


def fit_context(pack: Mapping[str, Any], *, max_bytes: int = MAX_CONTEXT_BYTES) -> dict[str, Any]:
    """Cap the pack at ``max_bytes``: review and sector detail go first."""
    result = copy.deepcopy(dict(pack))
    trimmed: list[str] = []
    result["trimmed"] = trimmed

    def note(name: str) -> None:
        if name not in trimmed:
            trimmed.append(name)

    card = result.get("card")
    if isinstance(card, dict) and isinstance(card.get("history"), list):
        if len(card["history"]) > MAX_CARD_HISTORY:
            card["history"] = card["history"][-MAX_CARD_HISTORY:]
            note("card.history")
    while _encoded_size(result) > max_bytes:
        review = result.get("review")
        if isinstance(review, dict):
            evidence = review.get("evidence")
            if isinstance(evidence, list) and len(evidence) > 3:
                review["evidence"] = evidence[:3]
                note("review.evidence")
                continue
            if isinstance(evidence, list) and evidence:
                review["evidence"] = []
                note("review.evidence")
                continue
            if review.get("mainline") is not None:
                review["mainline"] = None
                note("review.mainline")
                continue
            result["review"] = None
            note("review")
            continue
        snapshot = result.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("sector"):
            snapshot["sector"] = None
            note("snapshot.sector")
            continue
        if isinstance(card, dict) and card.get("history"):
            card["history"] = []
            note("card.history")
            continue
        if _truncate_strings(result, 500):
            note("long_text")
            continue
        if _truncate_strings(result, 120):
            note("long_text")
            continue
        break
    return result


# -- judgement -----------------------------------------------------------
def validate_judgement(payload: Any, *, now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("invalid_body", "请求体必须是 JSON 对象")
    only(payload, JUDGEMENT_FIELDS)
    for key in ("action", "reason", "next_check", "risk"):
        if key not in payload:
            raise ApiError("bad_request", f"{key} 必填")
    action = payload.get("action")
    if isinstance(action, str) and not action.strip():
        raise ApiError("invalid_value", "action 不得为空")
    if action not in JUDGEMENT_ACTIONS:
        raise ApiError(
            "invalid_action",
            "action 只接受 observe/await_confirm/execute/abandon/exit",
        )
    result: dict[str, Any] = {"action": action, "ts": fmt_iso(now)}
    for key in ("reason", "next_check", "risk"):
        result[key] = clean_text(
            payload.get(key), key, JUDGEMENT_TEXT_LIMIT, allow_empty=False
        )
    return result


def judged_signal_text(
    row: Mapping[str, Any], judgement: Mapping[str, Any]
) -> dict[str, str]:
    """Append the Chives judgement while keeping kind/decide/severity untouched."""
    action = str(judgement.get("action") or "observe")
    label = ACTION_LABELS.get(action, action)
    parts = [f"Chives 判断：{label}"]
    if judgement.get("reason"):
        parts.append(str(judgement["reason"]))
    if judgement.get("next_check"):
        parts.append(f"下一检查 {judgement['next_check']}")
    if judgement.get("risk"):
        parts.append(f"风险 {judgement['risk']}")
    existing_conclusion = str(row.get("conclusion") or "")
    existing_brief = str(row.get("brief") or "")
    conclusion = "｜".join(part for part in (parts[0], existing_conclusion) if part)
    brief = "；".join(parts)
    if existing_brief:
        brief = f"{brief}｜{existing_brief}" if brief else existing_brief
    return {
        "conclusion": truncate(conclusion, 60),
        "brief": truncate(brief, 140),
    }


def judgement_payload(
    *,
    trigger_id: int,
    judgement: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "trigger_id": int(trigger_id),
        "ts": fmt_iso(now),
        "action": judgement["action"],
        "reason": judgement.get("reason") or "",
        "next_check": judgement.get("next_check") or "",
        "risk": judgement.get("risk") or "",
    }
