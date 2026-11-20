"""Replace the bearer token (and any recognizable prefix of it) in every value that leaves the server."""

from __future__ import annotations

import re
from typing import Any

MASK = "***"
MIN_PREFIX_CHARS = 8
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{4,}")


class Redactor:
    def __init__(self, secret: str | None) -> None:
        self._secret = (secret or "").strip()
        length = len(self._secret)
        self._prefixes = [self._secret] if self._secret else []
        if length > MIN_PREFIX_CHARS:
            self._prefixes += [
                self._secret[:size] for size in range(length - 1, MIN_PREFIX_CHARS - 1, -1)
            ]

    def text(self, value: str) -> str:
        if not self._secret:
            return value
        cleaned = BEARER_RE.sub(f"Bearer {MASK}", value)
        for prefix in self._prefixes:
            if prefix in cleaned:
                cleaned = cleaned.replace(prefix, MASK)
        return cleaned

    def obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.obj(item) for item in value]
        if isinstance(value, tuple):
            return [self.obj(item) for item in value]
        if isinstance(value, dict):
            return {
                self.text(key) if isinstance(key, str) else key: self.obj(item)
                for key, item in value.items()
            }
        return value
