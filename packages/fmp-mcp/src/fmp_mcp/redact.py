"""Remove API key material from anything that may leave the process."""

from __future__ import annotations

import re

# `apikey=...` in URLs / exception text / upstream bodies.
_APIKEY_QUERY = re.compile(r"(?i)(apikey=)[^&\s\"'<>]+")
# `"apikey": "..."` in JSON snippets.
_APIKEY_JSON = re.compile(r'(?i)("apikey"\s*:\s*")[^"]*(")')

REDACTED = "***"


def redact(text: str, secret: str | None) -> str:
    """Redact both the raw secret value and any apikey=... fragment."""
    if not text:
        return text
    out = _APIKEY_QUERY.sub(r"\1" + REDACTED, text)
    out = _APIKEY_JSON.sub(r"\1" + REDACTED + r"\2", out)
    if secret:
        out = out.replace(secret, REDACTED)
    return out


def redact_error_message(message: str | None, secret: str | None) -> str:
    return redact(message or "", secret)
