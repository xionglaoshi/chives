"""Stable error types shared by the hub client, tools and the stdio boundary."""

from __future__ import annotations


class HubConfigError(ValueError):
    """CHIVES_HUB_URL is missing, malformed or not a loopback address."""


class HubError(Exception):
    """A transport-level failure; ``code`` is stable and machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolError(ValueError):
    """A rejected tool argument; never reaches the hub."""

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
