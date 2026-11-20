"""Envelope construction, batching, robots gating and local rate limiting."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from scrape_mcp.config import Settings
from scrape_mcp.extract import MAX_CONTENT_CHARS, ExtractError, extract_content
from scrape_mcp.fetch_browser import BrowserFetcher
from scrape_mcp.fetch_http import FetchError, FetchedResponse, HttpClient
from scrape_mcp.redact import Redactor
from scrape_mcp.robots import RobotsCache
from scrape_mcp.ssrf import Target, UrlError
from scrape_mcp.validation import (
    ValidationError,
    validate_page_args,
    validate_pages_args,
)

logger = logging.getLogger(__name__)

SOURCE = "scrape"
CONCURRENCY = {"fast": 4, "browser": 2}
ROBOTS_TIMEOUT = 10.0
RATE_WINDOW_SECONDS = 60.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _SlidingWindowLimiter:
    """Per-process cap on page fetches, so one agent cannot hammer the tool."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = RATE_WINDOW_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._events: list[float] = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            self._events = [event for event in self._events if event > cutoff]
            if len(self._events) >= self._limit:
                return False
            self._events.append(now)
            return True


class ScrapeService:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: Any | None = None,
        browser: Any | None = None,
        redactor: Redactor | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._redactor = redactor or Redactor()
        self._http = http_client or HttpClient(settings)
        self._browser = browser or BrowserFetcher(settings)
        self._robots = RobotsCache(
            self._fetch_robots, user_agent=settings.user_agent
        )
        self._limiter = _SlidingWindowLimiter(settings.requests_per_minute, clock=clock)

    # ------------------------------------------------------------------ tools

    def interact(self, url: str, callback: Callable[[Any], None]) -> tuple[FetchedResponse, list[str]]:
        warnings: list[str] = []
        if not self._limiter.allow():
            raise FetchError("rate_limited", "browser request budget exhausted")
        response = self._browser.get(
            url, timeout=12, guard=lambda target: self._robots_guard(target, warnings), interact=callback
        )
        return response, [*warnings, *response.warnings]

    def scrape_page(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_page_args(args)
        except ValidationError as exc:
            return self._error(exc.code, str(exc))
        warnings: list[str] = []
        try:
            data, status = self._fetch_one(params["url"], params, warnings)
        except UrlError as exc:
            return self._error(exc.code, exc.message, warnings)
        except FetchError as exc:
            return self._error(exc.code, exc.message, warnings)
        except ExtractError as exc:
            return self._error("extract_failed", str(exc), warnings)
        except Exception as exc:  # defensive boundary
            logger.exception("unexpected scrape error: %s", type(exc).__name__)
            return self._error("fetch_failed", "unexpected error while fetching the page", warnings)
        return self._envelope(status, data, warnings)

    def scrape_pages(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_pages_args(args)
        except ValidationError as exc:
            return self._error(exc.code, str(exc))
        urls: list[str] = params["urls"]
        workers = CONCURRENCY[params["mode"]]
        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(self._batch_item, url, params) for url in urls
            ]
            for future in futures:
                item, item_warnings = future.result()
                for warning in item_warnings:
                    warnings.append(f"{item.get('url', '')}: {warning}")
                results.append(item)

        succeeded = sum(1 for item in results if item.get("ok"))
        failed_items = [item for item in results if not item.get("ok")]
        data = {
            "count": len(results),
            "succeeded": succeeded,
            "failed_count": len(failed_items),
            "results": results,
            "failed": failed_items,
            "untrusted_text": True,
        }
        if succeeded == 0:
            first = next(
                (item.get("error", {}) for item in results if item.get("error")),
                {"code": "fetch_failed", "message": "all URLs failed"},
            )
            payload = self._envelope("error", data, warnings)
            payload["error"] = {
                "code": first.get("code", "fetch_failed"),
                "message": self._redactor.text(
                    f"all {len(results)} URL(s) failed; first error: {first.get('message', '')}"
                ),
            }
            return payload
        status = "ready" if any(str(item.get("content", "")).strip() for item in results) else "empty"
        return self._envelope(status, data, warnings)

    def internal_error(self) -> dict[str, Any]:
        return self._error("fetch_failed", "unexpected tool error")

    # ------------------------------------------------------------- internals

    def _batch_item(
        self, url: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        try:
            data, _ = self._fetch_one(url, params, warnings)
        except (UrlError, FetchError, ExtractError) as exc:
            code = exc.code if hasattr(exc, "code") else "extract_failed"
            return (
                {
                    "ok": False,
                    "url": self._redactor.url(url),
                    "error": {"code": code, "message": self._redactor.text(str(exc))},
                },
                warnings,
            )
        except Exception as exc:
            logger.exception("unexpected batch item error: %s", type(exc).__name__)
            return (
                {
                    "ok": False,
                    "url": self._redactor.url(url),
                    "error": {
                        "code": "fetch_failed",
                        "message": "unexpected error while fetching the page",
                    },
                },
                warnings,
            )
        return ({**data, "ok": True}, warnings)

    def _fetch_one(
        self, url: str, params: dict[str, Any], warnings: list[str]
    ) -> tuple[dict[str, Any], str]:
        if not self._limiter.allow():
            raise FetchError(
                "rate_limited",
                f"local rate limit exceeded ({self._settings.requests_per_minute} page fetches per minute)",
            )
        fetcher = self._browser if params["mode"] == "browser" else self._http
        response: FetchedResponse = fetcher.get(
            url,
            timeout=params["timeout"],
            guard=lambda target: self._robots_guard(target, warnings),
        )
        warnings.extend(response.warnings)
        extracted = extract_content(
            response.text,
            params["extraction"],
            url=response.final_url,
            content_type=response.content_type,
        )
        content = self._redactor.text(extracted.content)
        if extracted.truncated:
            warnings.append(f"content truncated at {MAX_CONTENT_CHARS} characters")
        data = {
            "url": self._redactor.url(url),
            "final_url": self._redactor.url(response.final_url),
            "http_status": response.status,
            "title": self._redactor.text(extracted.title),
            "content": content,
            "truncated": extracted.truncated,
            "content_chars": len(content),
            "fetched_at": _now_iso(),
            "untrusted_text": True,
        }
        status = "ready" if content.strip() else "empty"
        return data, status

    def _fetch_robots(self, url: str) -> tuple[int, str]:
        response = self._http.get(url, timeout=ROBOTS_TIMEOUT, guard=None)
        return response.status, response.text

    def _robots_guard(self, target: Target, warnings: list[str]) -> None:
        allowed, warning = self._robots.check(target)
        if warning:
            warnings.append(warning)
        if not allowed:
            raise FetchError(
                "robots_disallowed",
                warning or f"robots.txt disallows {target.url}",
            )

    def _envelope(
        self, status: str, data: dict[str, Any], warnings: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "ok": status != "error",
            "source": SOURCE,
            "as_of": _now_iso(),
            "status": status,
            "data": data,
            "warnings": list(warnings or []),
        }

    def _error(
        self, code: str, message: str, warnings: list[str] | None = None
    ) -> dict[str, Any]:
        payload = self._envelope("error", {}, warnings)
        payload["error"] = {"code": code, "message": self._redactor.text(message)}
        return payload
