"""Envelope construction, budget accounting, rate limiting and redaction for the five tools."""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from typing import Any, Callable

from x_mcp.budget import BudgetError, BudgetSnapshot, DailyBudget
from x_mcp.client import (
    UpstreamError,
    XClient,
    classify_errors,
    error_items,
    error_message,
    error_summary,
    has_data,
)
from x_mcp.ratelimit import TokenBucket
from x_mcp.redact import Redactor
from x_mcp.validation import (
    ValidationError,
    validate_counts_recent,
    validate_get_post,
    validate_get_user,
    validate_search_recent,
    validate_user_posts,
)

SOURCE = "x"
MAX_TEXT_CHARS = 4000
MAX_DESCRIPTION_CHARS = 2000
LOCAL_RATE_CAPACITY = 30
LOCAL_RATE_REFILL_SECONDS = 30.0
MISSING_KEY_MESSAGE = (
    "X_BEARER_TOKEN is not set; run python3 scripts/install-keys.py to install it, then restart the server"
)

TWEET_KEYS = (
    "id",
    "text",
    "created_at",
    "author_id",
    "public_metrics",
    "lang",
    "conversation_id",
    "entities",
)
USER_KEYS = (
    "id",
    "name",
    "username",
    "created_at",
    "description",
    "public_metrics",
    "verified",
)
TWEET_STRINGS = ("id", "text", "created_at", "author_id", "lang", "conversation_id")
USER_STRINGS = ("id", "name", "username", "created_at", "description")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _truncate(value: str, limit: int) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _metrics(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    cleaned = {
        str(key): item
        for key, item in value.items()
        if isinstance(item, int) and not isinstance(item, bool)
    }
    return cleaned or None


def _tweet(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    row: dict[str, Any] = {}
    for key in TWEET_KEYS:
        value = item.get(key)
        if value is None:
            continue
        if key in TWEET_STRINGS and isinstance(value, str):
            if key == "text":
                value, truncated = _truncate(value, MAX_TEXT_CHARS)
                if truncated:
                    row["truncated"] = True
            row[key] = value
        elif key == "public_metrics":
            metrics = _metrics(value)
            if metrics is not None:
                row[key] = metrics
        elif key == "entities" and isinstance(value, dict):
            row[key] = copy.deepcopy(value)
    if "id" not in row:
        return None
    return row


def _user(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    row: dict[str, Any] = {}
    for key in USER_KEYS:
        value = item.get(key)
        if value is None:
            continue
        if key in USER_STRINGS and isinstance(value, str):
            if key == "description":
                value, truncated = _truncate(value, MAX_DESCRIPTION_CHARS)
                if truncated:
                    row["truncated"] = True
            row[key] = value
        elif key == "public_metrics":
            metrics = _metrics(value)
            if metrics is not None:
                row[key] = metrics
        elif key == "verified" and isinstance(value, bool):
            row[key] = value
    if "id" not in row:
        return None
    return row


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _users(raw: dict[str, Any]) -> list[dict[str, Any]]:
    includes = raw.get("includes")
    if not isinstance(includes, dict):
        return []
    rows = [_user(item) for item in _list(includes.get("users"))]
    return [row for row in rows if row is not None]


def _next_token(raw: dict[str, Any]) -> str | None:
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        return None
    token = meta.get("next_token")
    return token if isinstance(token, str) and token else None


def _error_text(raw: dict[str, Any]) -> str:
    errors = raw.get("errors")
    if not isinstance(errors, list) or not errors:
        return ""
    first = errors[0]
    if isinstance(first, dict):
        message = first.get("message") or first.get("detail") or first.get("title")
        if isinstance(message, str):
            return message
    return ""


def _payload_failure(raw: dict[str, Any]) -> tuple[str, str] | None:
    errors = error_items(raw)
    if not errors or has_data(raw):
        return None
    return classify_errors(errors), error_message(errors)


def _warnings(raw: dict[str, Any]) -> list[str]:
    errors = error_items(raw)
    if not errors or not has_data(raw):
        return []
    summary = error_summary(errors)
    return [summary] if summary else []


class XService:
    def __init__(
        self,
        client: XClient | None,
        *,
        redactor: Redactor | None = None,
        budget: DailyBudget | None = None,
        limiter: TokenBucket | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._redactor = redactor or Redactor(None)
        self._budget = budget
        self._limiter = limiter or TokenBucket(
            LOCAL_RATE_CAPACITY,
            LOCAL_RATE_REFILL_SECONDS,
            clock=clock,
        )

    def search_recent(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_search_recent(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        blocked = self._guard()
        if blocked is not None:
            return blocked
        reservation, denied = self._reserve(params["max_results"])
        if denied is not None:
            return denied
        if self._client is None:  # pragma: no cover - guarded above
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        try:
            raw = self._client.search_recent(params)
        except UpstreamError as exc:
            self._release(reservation)
            return self._upstream_error(exc)

        failure = _payload_failure(raw)
        if failure is not None:
            self._release(reservation)
            return self._error(*failure)
        warnings = _warnings(raw)
        items = raw.get("data")
        if items is None:
            rows: list[dict[str, Any]] = []
        elif isinstance(items, list):
            rows = [row for row in (_tweet(item) for item in items) if row is not None]
        else:
            self._release(reservation)
            return self._error("malformed_response", "X returned an unexpected search payload")
        snapshot = self._settle(reservation, len(rows))
        data = {
            "query": params["query"],
            "count": len(rows),
            "results": rows,
            "users": _users(raw),
            "next_token": _next_token(raw),
            "untrusted_text": True,
            "budget": snapshot.short(),
        }
        return self._envelope("ready" if rows else "empty", data, warnings=warnings)

    def get_post(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_get_post(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        blocked = self._guard()
        if blocked is not None:
            return blocked
        reservation, denied = self._reserve(1)
        if denied is not None:
            return denied
        if self._client is None:  # pragma: no cover - guarded above
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        try:
            raw = self._client.get_post(params["tweet_id"])
        except UpstreamError as exc:
            self._release(reservation)
            return self._upstream_error(exc)

        failure = _payload_failure(raw)
        if failure is not None:
            self._release(reservation)
            return self._error(*failure)
        warnings = _warnings(raw)
        item = raw.get("data")
        row = _tweet(item) if isinstance(item, dict) else None
        if row is None:
            self._release(reservation)
            if _error_text(raw):
                return self._error("not_found", "the post is unavailable (deleted or protected)")
            return self._error("malformed_response", "X returned no post object")
        snapshot = self._settle(reservation, 1)
        data = {
            "post": row,
            "users": _users(raw),
            "untrusted_text": True,
            "budget": snapshot.short(),
        }
        return self._envelope("ready", data, warnings=warnings)

    def get_user(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_get_user(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        blocked = self._guard()
        if blocked is not None:
            return blocked
        reservation, denied = self._reserve(1)
        if denied is not None:
            return denied
        if self._client is None:  # pragma: no cover - guarded above
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        try:
            raw = self._client.get_user(params["username"])
        except UpstreamError as exc:
            self._release(reservation)
            return self._upstream_error(exc)

        failure = _payload_failure(raw)
        if failure is not None:
            self._release(reservation)
            return self._error(*failure)
        warnings = _warnings(raw)
        item = raw.get("data")
        row = _user(item) if isinstance(item, dict) else None
        if row is None:
            self._release(reservation)
            if _error_text(raw):
                return self._error("not_found", "the user is unavailable (deleted or protected)")
            return self._error("malformed_response", "X returned no user object")
        snapshot = self._settle(reservation, 1)
        data = {"user": row, "untrusted_text": True, "budget": snapshot.short()}
        return self._envelope("ready", data, warnings=warnings)

    def user_posts(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_user_posts(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        blocked = self._guard()
        if blocked is not None:
            return blocked
        reservation, denied = self._reserve(params["max_results"])
        if denied is not None:
            return denied
        if self._client is None:  # pragma: no cover - guarded above
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        try:
            raw = self._client.user_posts(params)
        except UpstreamError as exc:
            self._release(reservation)
            return self._upstream_error(exc)

        failure = _payload_failure(raw)
        if failure is not None:
            self._release(reservation)
            return self._error(*failure)
        warnings = _warnings(raw)
        items = raw.get("data")
        if items is None:
            rows: list[dict[str, Any]] = []
        elif isinstance(items, list):
            rows = [row for row in (_tweet(item) for item in items) if row is not None]
        else:
            self._release(reservation)
            return self._error("malformed_response", "X returned an unexpected posts payload")
        snapshot = self._settle(reservation, len(rows))
        data = {
            "user_id": params["user_id"],
            "count": len(rows),
            "results": rows,
            "users": _users(raw),
            "next_token": _next_token(raw),
            "untrusted_text": True,
            "budget": snapshot.short(),
        }
        return self._envelope("ready" if rows else "empty", data, warnings=warnings)

    def counts_recent(self, args: Any) -> dict[str, Any]:
        try:
            params = validate_counts_recent(args)
        except ValidationError as exc:
            return self._error("invalid_argument", str(exc))
        blocked = self._guard()
        if blocked is not None:
            return blocked
        reservation, denied = self._reserve(1)
        if denied is not None:
            return denied
        if self._client is None:  # pragma: no cover - guarded above
            return self._error("missing_key", MISSING_KEY_MESSAGE)

        try:
            raw = self._client.counts_recent(params)
        except UpstreamError as exc:
            self._release(reservation)
            return self._upstream_error(exc)

        failure = _payload_failure(raw)
        if failure is not None:
            self._release(reservation)
            return self._error(*failure)
        warnings = _warnings(raw)
        items = raw.get("data")
        if items is None:
            buckets: list[dict[str, Any]] = []
        elif isinstance(items, list):
            buckets = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                start = item.get("start")
                end = item.get("end")
                count = item.get("tweet_count")
                if isinstance(count, bool) or not isinstance(count, int):
                    continue
                buckets.append(
                    {
                        "start": start if isinstance(start, str) else None,
                        "end": end if isinstance(end, str) else None,
                        "tweet_count": count,
                    }
                )
        else:
            self._release(reservation)
            return self._error("malformed_response", "X returned an unexpected counts payload")
        meta = raw.get("meta")
        total = meta.get("total_tweet_count") if isinstance(meta, dict) else None
        if isinstance(total, bool) or not isinstance(total, int):
            total = sum(bucket["tweet_count"] for bucket in buckets)
        snapshot = self._settle(reservation, 1)
        data = {
            "query": params["query"],
            "granularity": params["granularity"],
            "count": len(buckets),
            "buckets": buckets,
            "total_tweet_count": total,
            "untrusted_text": True,
            "budget": snapshot.short(),
        }
        return self._envelope("ready" if buckets else "empty", data, warnings=warnings)

    def internal_error(self) -> dict[str, Any]:
        return self._error("internal_error", "unexpected tool error")

    def _guard(self) -> dict[str, Any] | None:
        if self._client is None:
            return self._error("missing_key", MISSING_KEY_MESSAGE)
        if not self._limiter.allow():
            return self._error(
                "rate_limited",
                "local rate limit exceeded; the tool does not retry automatically",
                {"retry_after_seconds": self._limiter.retry_after()},
            )
        return None

    def _reserve(self, count: int) -> tuple[int, dict[str, Any] | None]:
        if self._budget is None:
            return 0, None
        try:
            allowed, snapshot = self._budget.reserve(count)
        except BudgetError as exc:
            return 0, self._error("http_error", str(exc))
        if not allowed:
            message = (
                f"daily X read budget exhausted (used {snapshot.used_today} of {snapshot.limit}); "
                f"resets at {snapshot.reset_at}"
            )
            return 0, self._error(
                "budget_exhausted",
                message,
                {
                    "budget": snapshot.short(),
                    "reset_at": snapshot.reset_at,
                    "reset_at_epoch": snapshot.reset_at_epoch,
                },
            )
        return count, None

    def _release(self, reserved: int) -> None:
        if self._budget is None or reserved <= 0:
            return
        try:
            self._budget.release(reserved)
        except BudgetError:
            pass

    def _settle(self, reserved: int, actual: int) -> BudgetSnapshot:
        if self._budget is None:
            return BudgetSnapshot(0, 0, 0, 0, "")
        try:
            return self._budget.settle(reserved, actual)
        except BudgetError:
            return BudgetSnapshot(
                used_today=reserved,
                remaining=0,
                limit=0,
                reset_at_epoch=0,
                reset_at="",
            )

    def _upstream_error(self, exc: UpstreamError) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if exc.code == "rate_limited":
            if exc.reset_at_epoch is not None:
                data["reset_at_epoch"] = exc.reset_at_epoch
            if exc.retry_after_seconds is not None:
                data["retry_after_seconds"] = exc.retry_after_seconds
        return self._error(exc.code, str(exc), data)

    def _error(
        self,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._envelope("error", data or {}, code, message)

    def _envelope(
        self,
        status: str,
        data: dict[str, Any],
        error_code: str | None = None,
        error_message: str | None = None,
        *,
        warnings: list[str] | None = None,
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
        if warnings:
            payload["warnings"] = [self._redactor.text(item) for item in warnings]
        return self._redactor.obj(payload)
