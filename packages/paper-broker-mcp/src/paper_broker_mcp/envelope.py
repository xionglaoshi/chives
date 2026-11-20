"""Uniform JSON envelopes for the paper-broker MCP server."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE = "paper-broker"
SIMULATED = True
CN_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    return datetime.now(CN_TZ)


def to_cn(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CN_TZ)
    return value.astimezone(CN_TZ)


def iso(value: datetime) -> str:
    return to_cn(value).isoformat(timespec="seconds")


def envelope(
    *,
    as_of: datetime,
    status: str = "ready",
    data: Any = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": status != "error",
        "source": SOURCE,
        "simulated": SIMULATED,
        "as_of": iso(as_of),
        "status": status,
        "data": {} if data is None else data,
    }
    if error_code is not None:
        payload["error"] = {"code": error_code, "message": error_message or ""}
    return payload
