"""Uniform flat JSON envelope for every hub tool result.

The top-level keys (``ok``/``signals``/``plan``/``analysis`` …) are deliberate:
tool consumers and acceptance drivers read them directly, while ``source`` and
``as_of`` describe where and when the payload came from.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE = "hub"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ok_payload(**fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "source": SOURCE,
        "as_of": now_iso(),
    }
    payload.update(fields)
    return payload


def error_payload(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "source": SOURCE,
        "as_of": now_iso(),
        "error": {"code": code, "message": message},
    }
