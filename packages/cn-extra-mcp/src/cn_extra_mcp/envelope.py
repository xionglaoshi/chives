"""Uniform JSON envelopes shared by all tools."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SOURCE = "akshare.sina.stock_zh_a_minute+qt.gtimg.cn"
_CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(_CN_TZ).isoformat(timespec="seconds")


def envelope(
    *,
    source: str,
    status: str,
    data: Any = None,
    error_code: str | None = None,
    error_message: str | None = None,
    warnings: list[str] | None = None,
    warning_message: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": status != "error",
        "source": source,
        "market": "cn",
        "as_of": now_iso(),
        "status": status,
        "data": {} if data is None else data,
    }
    if error_code is not None:
        payload["error"] = {"code": error_code, "message": error_message or ""}
    if warnings:
        payload["warnings"] = list(warnings)
    if warning_message:
        payload["warning_message"] = warning_message
    return payload
