"""Stable, machine-readable errors for rejected tool requests."""

from __future__ import annotations

from typing import Any


class PortfolioError(Exception):
    """A rejected request; `code` is stable and safe to show to the agent."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.details = details or {}
