"""Replace the API key in every value that leaves the server."""

from __future__ import annotations

from typing import Any

MASK = "***"


class Redactor:
    def __init__(self, secret: str | None) -> None:
        self._secret = secret or ""

    def text(self, value: str) -> str:
        if not self._secret:
            return value
        return value.replace(self._secret, MASK)

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
