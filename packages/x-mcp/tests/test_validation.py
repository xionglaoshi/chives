from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from x_mcp.validation import (
    ValidationError,
    validate_counts_recent,
    validate_get_post,
    validate_get_user,
    validate_search_recent,
    validate_user_posts,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": 1},
        {"query": "x" * 513},
        {"query": "a", "max_results": 9},
        {"query": "a", "max_results": 101},
        {"query": "a", "max_results": True},
        {"query": "a", "max_results": "10"},
        {"query": "a", "next_token": ""},
        {"query": "a", "next_token": 5},
        {"query": "a", "next_token": "bad token"},
        {"query": "a", "start_time": "not-a-time"},
        {"query": "a", "start_time": "2026-11-02T00:00:00"},
        {"query": "a", "start_time": "2026-10-01T00:00:00Z"},
        {"query": "a", "end_time": "2026-11-05T00:00:00Z"},
        {"query": "a", "start_time": "2026-11-02T00:00:00Z", "end_time": "2026-11-01T00:00:00Z"},
        {"query": "a", "start_time": 123},
        None,
        "query",
        [],
    ],
)
def test_invalid_search_arguments(args: object) -> None:
    with pytest.raises(ValidationError):
        validate_search_recent(args, now=NOW)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"tweet_id": ""},
        {"tweet_id": "abc"},
        {"tweet_id": "-1"},
        {"tweet_id": "1" * 26},
        {"tweet_id": 1},
        {"tweet_id": "1 2"},
        {"tweet_id": "１"},
        None,
    ],
)
def test_invalid_tweet_ids(args: object) -> None:
    with pytest.raises(ValidationError):
        validate_get_post(args)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"username": ""},
        {"username": "   "},
        {"username": "@"},
        {"username": "@@user"},
        {"username": "user@"},
        {"username": "a" * 16},
        {"username": "bad-name"},
        {"username": "bad name"},
        {"username": " user "},
        {"username": "@user "},
        {"username": 123},
        None,
    ],
)
def test_invalid_usernames(args: object) -> None:
    with pytest.raises(ValidationError):
        validate_get_user(args)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"user_id": ""},
        {"user_id": "abc"},
        {"user_id": -1},
        {"user_id": 42},
        {"user_id": "1" * 26},
        {"user_id": "42", "max_results": 4},
        {"user_id": "42", "max_results": 101},
        {"user_id": "42", "max_results": True},
        {"user_id": "42", "pagination_token": ""},
        {"user_id": "42", "pagination_token": "a\tb"},
        None,
    ],
)
def test_invalid_user_posts_arguments(args: object) -> None:
    with pytest.raises(ValidationError):
        validate_user_posts(args)


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"granularity": "day"},
        {"query": ""},
        {"query": "x" * 513},
        {"query": "a", "granularity": "week"},
        {"query": "a", "granularity": None},
        {"query": "a", "granularity": "DAY"},
        None,
    ],
)
def test_invalid_counts_arguments(args: object) -> None:
    with pytest.raises(ValidationError):
        validate_counts_recent(args)


def test_search_defaults_and_boundaries() -> None:
    assert validate_search_recent({"query": "a"}, now=NOW) == {
        "query": "a",
        "max_results": 10,
        "next_token": None,
        "start_time": None,
        "end_time": None,
    }
    full = validate_search_recent(
        {
            "query": "x" * 512,
            "max_results": 100,
            "next_token": "abc",
            "start_time": (NOW - timedelta(days=7)).isoformat(),
            "end_time": NOW.isoformat(),
        },
        now=NOW,
    )
    assert full["query"] == "x" * 512
    assert full["max_results"] == 100
    assert full["start_time"].endswith("Z")
    assert full["end_time"] == "2026-11-03T12:00:00Z"


def test_search_accepts_lower_boundaries() -> None:
    assert validate_search_recent({"query": "a", "max_results": 10}, now=NOW)["max_results"] == 10
    assert validate_search_recent({"query": "a", "max_results": 100}, now=NOW)["max_results"] == 100


def test_user_posts_defaults_and_boundaries() -> None:
    assert validate_user_posts({"user_id": "42"}) == {
        "user_id": "42",
        "max_results": 10,
        "pagination_token": None,
    }
    assert validate_user_posts({"user_id": "42", "max_results": 5})["max_results"] == 5
    assert validate_user_posts({"user_id": "42", "max_results": 100})["max_results"] == 100


def test_username_strips_one_leading_at() -> None:
    assert validate_get_user({"username": "@Test_User"}) == {"username": "Test_User"}


def test_counts_default_granularity() -> None:
    assert validate_counts_recent({"query": "q"}) == {"query": "q", "granularity": "day"}
    assert validate_counts_recent({"query": "q", "granularity": "minute"})["granularity"] == "minute"


def test_timestamp_with_offset_is_normalized_to_utc() -> None:
    result = validate_search_recent(
        {"query": "q", "start_time": "2026-11-03T20:00:00+08:00"},
        now=NOW,
    )
    assert result["start_time"] == "2026-11-03T12:00:00Z"


def test_timestamp_exactly_seven_days_old_is_allowed() -> None:
    result = validate_search_recent(
        {"query": "q", "start_time": (NOW - timedelta(days=7)).isoformat()},
        now=NOW,
    )
    assert result["start_time"] == "2026-10-27T12:00:00Z"
