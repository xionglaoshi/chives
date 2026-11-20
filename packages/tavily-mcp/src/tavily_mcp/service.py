"""Envelope construction, caching, rate limiting and redaction for both tools."""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from tavily_mcp.cache import TTLCache
from tavily_mcp.client import TavilyClient, UpstreamError
from tavily_mcp.ratelimit import SlidingWindowLimiter
from tavily_mcp.redact import Redactor
from tavily_mcp.validation import (
    ValidationError,
    validate_extract,
    validate_search,
)

SOURCE = "tavily"
MAX_CONTENT_CHARS = 2000
CACHE_TTL_SECONDS = 300.0
LOCAL_RATE_LIMIT = 20
LOCAL_RATE_WINDOW_SECONDS = 60.0
MISSING_KEY_MESSAGE = (
    "TAVILY_API_KEY is not set; run python3 scripts/install-keys.py to install it, then restart the server"
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _truncate(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_CONTENT_CHARS:
        return value, False
    return value[:MAX_CONTENT_CHARS], True


def _score(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _search_result(item: dict[str, Any]) -> dict[str, Any]:
    content, truncated = _truncate(_text(item.get("content")))
    published = item.get("published_date")
    row: dict[str, Any] = {
        "title": _text(item.get("title")),
        "url": _text(item.get("url")),
        "content": content,
        "score": _score(item.get("score")),
        "published_date": published if isinstance(published, str) else None,
    }
    if truncated:
        row["truncated"] = True
    return row


def _extract_result(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw_content")
    if raw is None:
        raw = item.get("content")
    content, truncated = _truncate(_text(raw))
    row: dict[str, Any] = {"url": _text(item.get("url")), "content": content}
    if truncated:
        row["truncated"] = True
    return row


def _failed_result(item: Any) -> dict[str, str]:
    if isinstance(item, dict):
        return {"url": _text(item.get("url")), "error": _text(item.get("error"))}
    return {"url": "", "error": _text(item)}


class TavilyService:
    def __init__(
        self,
        client: TavilyClient | None,
        *,
        redactor: Redactor | None = None,
        cache: TTLCache | None = None,
        limiter: SlidingWindowLimiter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._redactor = redactor or Redactor(None)
        self._cache = cache or TTLCache(CACHE_TTL_SECONDS, clock=clock)
        self._limiter = limiter or SlidingWindowLimiter(
            LOCAL_RATE_LIMIT,
            LOCAL_RATE_WINDOW_SECONDS,
            clock=clock,
        )

    def search(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_search(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        if self._client is None:
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        cache_key = "search:" + json.dumps(params, sort_keys=True, ensure_ascii=False)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return self._envelope("ready", copy.deepcopy(cached))
        if not self._limiter.allow():
            return self._error("rate_limited", "local rate limit exceeded (20 calls per minute)")

        try:
            raw = self._client.search(params)
        except UpstreamError as exc:
            return self._error(exc.code, str(exc))

        items = raw.get("results")
        results = [_search_result(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        data = {
            "query": params["query"],
            "count": len(results),
            "results": results,
            "untrusted_text": True,
        }
        status = "ready" if results else "empty"
        if status == "ready":
            self._cache.set(cache_key, copy.deepcopy(data))
        return self._envelope(status, data)

    def extract(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_extract(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        if self._client is None:
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        cache_key = "extract:" + json.dumps(params, sort_keys=True, ensure_ascii=False)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return self._envelope("ready", copy.deepcopy(cached))
        if not self._limiter.allow():
            return self._error("rate_limited", "local rate limit exceeded (20 calls per minute)")

        try:
            raw = self._client.extract(params)
        except UpstreamError as exc:
            return self._error(exc.code, str(exc))

        items = raw.get("results")
        results = [_extract_result(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
        failed_items = raw.get("failed_results")
        failed = [_failed_result(item) for item in failed_items] if isinstance(failed_items, list) else []
        data = {
            "count": len(results),
            "results": results,
            "failed": failed,
            "untrusted_text": True,
        }
        status = "ready" if results else "empty"
        if status == "ready":
            self._cache.set(cache_key, copy.deepcopy(data))
        return self._envelope(status, data)

    def internal_error(self) -> dict[str, Any]:
        return self._error("internal_error", "unexpected tool error")

    def _error(self, code: str, message: str) -> dict[str, Any]:
        return self._envelope("error", {}, code, message)

    def _envelope(
        self,
        status: str,
        data: dict[str, Any],
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": status != "error",
            "source": SOURCE,
            "as_of": _now_iso(),
            "status": status,
            "data": data,
        }
        if error_code is not None:
            payload["error"] = {"code": error_code, "message": self._redactor.text(error_message or "")}
        return self._redactor.obj(payload)
