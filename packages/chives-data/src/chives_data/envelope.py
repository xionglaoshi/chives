"""The only response envelope exposed outside the gateway (design §5)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from . import config

_AUTHORED_WORDS = tuple(re.compile(re.escape(word), re.IGNORECASE) for word in config.FORBIDDEN_AUTHORED)


class EnvelopeLeak(AssertionError):
    """Raised when an implementation detail would leak into a tool response."""


def now_iso(now: datetime) -> str:
    return now.astimezone(config.CN_TZ).isoformat(timespec="seconds")


def missing(field: str, reason: str, *, item: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"field": field, "reason": reason}
    if item is not None:
        entry["item"] = item
    return entry


def basis(field: str, note: str) -> dict[str, Any]:
    return {"field": field, "note": note}


def authored_leaks(text: str) -> list[str]:
    """Forbidden words found in gateway-authored text (notes, reasons, messages, descriptions)."""
    return [pattern.pattern for pattern in _AUTHORED_WORDS if pattern.search(text)]


def _assert_clean(payload: dict[str, Any]) -> None:
    # Only text the gateway writes is checked at runtime; `data` is third-party content.
    authored = {key: payload[key] for key in ("basis", "missing", "message") if key in payload}
    leaks = authored_leaks(json.dumps(authored, ensure_ascii=False, allow_nan=False))
    if leaks:
        raise EnvelopeLeak(f"implementation word leaked: {leaks[0]}")
    for key in _walk_keys(payload):
        if key.lower() == "source":
            raise EnvelopeLeak("source field leaked")


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def envelope(
    status: str,
    *,
    data: Any = None,
    as_of: str,
    stale: bool = False,
    basis_items: list[dict[str, Any]] | None = None,
    missing_items: list[dict[str, Any]] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    if status not in {"ok", "partial", "unavailable"}:
        raise ValueError(f"unknown status: {status}")
    payload: dict[str, Any] = {
        "status": status,
        "as_of": as_of,
        "data": {} if data is None else data,
        "stale": bool(stale),
    }
    if basis_items:
        payload["basis"] = [dict(item) for item in basis_items]
    if missing_items:
        payload["missing"] = [dict(item) for item in missing_items]
    if message is not None:
        if status != "unavailable":
            raise ValueError("message is only allowed for unavailable")
        payload["message"] = message
    _assert_clean(payload)
    return payload


def unavailable(as_of: str, message: str, *, missing_items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return envelope(
        "unavailable",
        as_of=as_of,
        missing_items=missing_items,
        message=message,
    )


def bad_argument(as_of: str, field: str, message: str) -> dict[str, Any]:
    return unavailable(
        as_of,
        message,
        missing_items=[missing(field, "参数不合法，请按提示修改")],
    )


def with_stale(payload: dict[str, Any]) -> dict[str, Any]:
    """Mark a cached payload as a stale fallback without touching its data time."""
    copied = json.loads(json.dumps(payload, ensure_ascii=False))
    copied["stale"] = True
    _assert_clean(copied)
    return copied
