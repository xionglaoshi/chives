"""Keep credentials out of everything the server returns or logs.

Two leaks are handled: sensitive query-string values in URLs (``?token=...``)
and HTTP header lines (``Authorization: ...``, ``Cookie: ...``) that some
server error strings like to echo.
"""

from __future__ import annotations

import re

MASK = "***"

_HEADER_RE = re.compile(
    r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key)\s*:\s*[^\r\n]+"
)
_PARAM_RE = re.compile(r"(?i)([?&;])([^=&#\s\"']+)=([^&#\s\"']*)")

_SENSITIVE_NAMES = frozenset(
    {
        "key",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "auth",
        "authorization",
        "password",
        "passwd",
        "pwd",
        "secret",
        "client_secret",
        "signature",
        "sig",
        "session",
        "session_id",
        "sessionid",
        "cookie",
        "credential",
        "credentials",
    }
)


def _sensitive(name: str) -> bool:
    normalized = name.lower().replace("-", "_")
    if normalized in _SENSITIVE_NAMES:
        return True
    return normalized.endswith("_key") or normalized.endswith("_token") or normalized.endswith(
        "_secret"
    )


def redact_url(value: str) -> str:
    """Mask the values of sensitive query parameters in a URL (or a message)."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(2)
        if not _sensitive(name):
            return match.group(0)
        return f"{match.group(1)}{name}={MASK}"

    return _PARAM_RE.sub(replace, value)


def redact_text(value: str) -> str:
    value = _HEADER_RE.sub(lambda match: f"{match.group(1)}: {MASK}", value)
    return redact_url(value)


class Redactor:
    def __init__(self, value: str | None = None) -> None:
        # An optional literal secret (never used for scraping; kept so the
        # server can scrub an accidental echo if a future caller has one).
        self._value = value or ""

    def url(self, value: str) -> str:
        return redact_url(value)

    def text(self, value: str) -> str:
        if self._value:
            value = value.replace(self._value, MASK)
        return redact_text(value)
