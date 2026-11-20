"""Uniform JSON envelope for every tool result."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE = "fmp"
MARKET = "us"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def envelope(
    *,
    endpoint: str,
    status: str,
    rows: list[Any] | None = None,
    notes: list[str] | None = None,
    available: int | None = None,
    truncated: bool | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "endpoint": endpoint,
        "count": len(rows or []),
        "rows": list(rows or []),
    }
    if available is not None:
        data["available"] = available
    if truncated is not None:
        data["truncated"] = truncated
    if notes:
        data["notes"] = notes
    payload: dict[str, Any] = {
        "ok": status != "error",
        "source": SOURCE,
        "market": MARKET,
        "as_of": now_iso(),
        "status": status,
        "data": data,
    }
    if error is not None:
        payload["error"] = error
    return payload
