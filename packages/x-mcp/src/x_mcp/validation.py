"""Strict validation for the five read-only X tool inputs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_QUERY_CHARS = 512
SEARCH_MIN_RESULTS = 10
SEARCH_MAX_RESULTS = 100
POSTS_MIN_RESULTS = 5
POSTS_MAX_RESULTS = 100
MAX_ID_DIGITS = 25
MAX_TOKEN_CHARS = 1024
RECENT_WINDOW = timedelta(days=7)
GRANULARITIES = ("minute", "hour", "day")
TWEET_ID_RE = re.compile(r"^[0-9]{1,25}$")
USER_ID_RE = re.compile(r"^[0-9]{1,25}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class ValidationError(ValueError):
    """A tool argument failed validation; no upstream request is made."""


def _query(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_QUERY_CHARS:
        raise ValidationError(f"query must be a non-empty string of at most {MAX_QUERY_CHARS} characters")
    return value


def _max_results(value: Any, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError(f"max_results must be an integer between {minimum} and {maximum}")
    return value


def _pagination_token(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_TOKEN_CHARS:
        raise ValidationError(f"pagination token must be a string of 1 to {MAX_TOKEN_CHARS} characters")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValidationError("pagination token must not contain whitespace or control characters")
    return value


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _timestamp(value: Any, field: str, current: datetime) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValidationError(f"{field} must be an ISO8601 timestamp")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must include a timezone")
    moment = parsed.astimezone(timezone.utc)
    if moment > current + timedelta(seconds=1):
        raise ValidationError(f"{field} must not be in the future")
    if moment < current - RECENT_WINDOW:
        raise ValidationError(f"{field} must be within the last 7 days")
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_search_recent(args: Any, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    current = _now(now)
    params: dict[str, Any] = {
        "query": _query(args.get("query")),
        "max_results": _max_results(args.get("max_results", 10), SEARCH_MIN_RESULTS, SEARCH_MAX_RESULTS),
        "next_token": None,
        "start_time": None,
        "end_time": None,
    }
    token = args.get("next_token")
    if token is not None:
        params["next_token"] = _pagination_token(token)
    start = args.get("start_time")
    if start is not None:
        params["start_time"] = _timestamp(start, "start_time", current)
    end = args.get("end_time")
    if end is not None:
        params["end_time"] = _timestamp(end, "end_time", current)
    if params["start_time"] is not None and params["end_time"] is not None:
        if params["start_time"] > params["end_time"]:
            raise ValidationError("start_time must not be after end_time")
    return params


def validate_get_post(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    tweet_id = args.get("tweet_id")
    if not isinstance(tweet_id, str) or not TWEET_ID_RE.fullmatch(tweet_id):
        raise ValidationError("tweet_id must be a string of 1 to 25 digits")
    return {"tweet_id": tweet_id}


def validate_get_user(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    username = args.get("username")
    if not isinstance(username, str) or not username:
        raise ValidationError("username must be a string of 1 to 15 letters, digits or underscores")
    candidate = username[1:] if username.startswith("@") else username
    if not USERNAME_RE.fullmatch(candidate):
        raise ValidationError("username must be a string of 1 to 15 letters, digits or underscores")
    return {"username": candidate}


def validate_user_posts(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    user_id = args.get("user_id")
    if not isinstance(user_id, str) or not USER_ID_RE.fullmatch(user_id):
        raise ValidationError("user_id must be a string of 1 to 25 digits")
    params: dict[str, Any] = {
        "user_id": user_id,
        "max_results": _max_results(args.get("max_results", 10), POSTS_MIN_RESULTS, POSTS_MAX_RESULTS),
        "pagination_token": None,
    }
    token = args.get("pagination_token")
    if token is not None:
        params["pagination_token"] = _pagination_token(token)
    return params


def validate_counts_recent(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")
    granularity = args.get("granularity", "day")
    if granularity not in GRANULARITIES:
        raise ValidationError("granularity must be minute, hour or day")
    return {"query": _query(args.get("query")), "granularity": granularity}
