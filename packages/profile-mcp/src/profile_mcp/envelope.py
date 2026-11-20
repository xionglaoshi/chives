"""Uniform JSON envelope shared by the three profile tools."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE = "profile"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def envelope(
    *,
    status: str = "ready",
    data: Any = None,
    warnings: list[Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Build the envelope; warnings are flat codes, details go to warning_details."""
    codes: list[str] = []
    details: list[dict[str, Any]] = []
    for warning in warnings or []:
        if isinstance(warning, dict):
            code = str(warning.get("code", "warning"))
            codes.append(code)
            details.append({"code": code, "message": str(warning.get("message", ""))})
        else:
            codes.append(str(warning))
    payload: dict[str, Any] = {
        "ok": status != "error",
        "source": SOURCE,
        "as_of": now_iso(),
        "status": status,
        "data": {} if data is None else data,
        "warnings": codes,
    }
    if details:
        payload["warning_details"] = details
    if error_code is not None:
        payload["error"] = {"code": error_code, "message": error_message or ""}
    return payload
