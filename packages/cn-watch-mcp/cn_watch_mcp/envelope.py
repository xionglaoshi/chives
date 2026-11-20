"""Uniform response envelope shared by every tool."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE = "cn-watch"
MARKET = "cn"
CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="seconds")


def as_of_from(payload: dict[str, Any]) -> str:
    updated_at = payload.get("updated_at")
    return updated_at if isinstance(updated_at, str) and updated_at else now_iso()


def warnings_for(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    health = payload.get("health")
    if payload.get("stale") is True or health == "stale":
        warnings.append("data_stale")
    if "trading_day" in payload and payload.get("trading_day") is False:
        warnings.append("market_closed")
    if "session" in payload and payload.get("session") != "open":
        warnings.append("outside_session")
    if isinstance(health, str) and health in {"down", "degraded"}:
        warnings.append("engine_degraded")
    return warnings


def success(data: dict[str, Any], *, as_of: str | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "source": SOURCE,
        "market": MARKET,
        "as_of": as_of or now_iso(),
        "status": "ready",
        "data": data,
        "warnings": list(warnings or []),
    }


def failure(code: str, message: str, **extra: Any) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    error.update(extra)
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
