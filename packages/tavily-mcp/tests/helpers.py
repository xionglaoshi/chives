"""Local, offline test doubles for the Tavily client and service."""

from __future__ import annotations

import copy
import json
from typing import Any


class FakeResponse:
    def __init__(self, status_code: int, payload: Any | None = None, *, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload if payload is not None else {})

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return copy.deepcopy(self._payload)


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected upstream call")
        return self.responses.pop(0)


class StubClient:
    def __init__(
        self,
        *,
        search_raw: dict[str, Any] | None = None,
        extract_raw: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.search_raw = search_raw if search_raw is not None else {"results": []}
        self.extract_raw = extract_raw if extract_raw is not None else {"results": [], "failed_results": []}
        self.error = error
        self.search_calls: list[dict[str, Any]] = []
        self.extract_calls: list[dict[str, Any]] = []

    def search(self, params: dict[str, Any]) -> dict[str, Any]:
        self.search_calls.append(copy.deepcopy(params))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.search_raw)

    def extract(self, params: dict[str, Any]) -> dict[str, Any]:
        self.extract_calls.append(copy.deepcopy(params))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.extract_raw)
