"""Uniform response envelope shared by every tool."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE = "market-watch"
MARKET = "cn"
CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def as_of_from(payload: dict[str, Any]) -> str:
    value = payload.get("as_of")
    return value if isinstance(value, str) and value else now_iso()


def has_stale(node: Any, depth: int = 0) -> bool:
    if depth > 8:
        return False
    if isinstance(node, dict):
        if node.get("stale") is True:
            return True
        return any(has_stale(v, depth + 1) for v in node.values())
    if isinstance(node, list):
        return any(has_stale(v, depth + 1) for v in node)
    return False


def warnings_for(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if has_stale(payload):
        warnings.append("data_stale")
    state = payload.get("trading_state")
    if state is not None and state != "open":
        warnings.append("market_closed")
    backfill = payload.get("backfill")
    if isinstance(backfill, dict) and backfill.get("running"):
        warnings.append("backfill_running")
    return warnings


def is_empty(payload: dict[str, Any]) -> bool:
    reason = payload.get("reason")
    if not (isinstance(reason, str) and reason):
        return False
    for key in ("rows", "tiers"):
        if key in payload and payload[key] == []:
            return True
    return False


def success(
    data: dict[str, Any],
    *,
    as_of: str | None = None,
    warnings: list[str] | None = None,
    status: str = "ready",
) -> dict[str, Any]:
    body = dict(data)
    body["untrusted_text"] = True
    return {
        "ok": True,
        "source": SOURCE,
        "market": MARKET,
        "as_of": as_of or now_iso(),
        "status": status,
        "data": body,
        "warnings": list(warnings or []),
    }


def failure(code: str, message: str, **extra: Any) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
    return passthrough_error(error)


def passthrough_error(error: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "source": SOURCE,
        "market": MARKET,
        "as_of": now_iso(),
        "status": "error",
        "data": {},
        "warnings": [],
        "error": error,
    }
