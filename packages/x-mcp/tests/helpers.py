"""Local, offline test doubles for the X client and service."""

from __future__ import annotations

import copy
import json
from typing import Any


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any | None = None,
        *,
        text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload if payload is not None else {})
        self.headers = headers or {}

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON body")
        return copy.deepcopy(self._payload)


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.trust_env = True

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected upstream call")
        return self.responses.pop(0)


def tweet(tweet_id: str = "100", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": tweet_id,
        "text": "hello world",
        "created_at": "2026-11-02T00:00:00.000Z",
        "author_id": "42",
        "public_metrics": {"like_count": 1, "retweet_count": 2},
        "lang": "en",
        "conversation_id": "100",
        "entities": {"hashtags": [{"tag": "test"}]},
        "unexpected_field": "drop me",
    }
    row.update(overrides)
    return row


def user(user_id: str = "42", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": user_id,
        "name": "Test User",
        "username": "testuser",
        "created_at": "2020-01-01T00:00:00.000Z",
        "description": "bio",
        "public_metrics": {"followers_count": 10},
        "verified": False,
        "unexpected_field": "drop me",
    }
    row.update(overrides)
    return row


class StubClient:
    def __init__(
        self,
        *,
        search: dict[str, Any] | None = None,
        post: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
        posts: dict[str, Any] | None = None,
        counts: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.search_raw = search if search is not None else {"data": [], "meta": {"result_count": 0}}
        self.post_raw = post if post is not None else {"data": tweet()}
        self.user_raw = user if user is not None else {"data": user_row()}
        self.posts_raw = posts if posts is not None else {"data": [], "meta": {"result_count": 0}}
        self.counts_raw = counts if counts is not None else {"data": [], "meta": {"total_tweet_count": 0}}
        self.error = error
        self.search_calls: list[dict[str, Any]] = []
        self.post_calls: list[str] = []
        self.user_calls: list[str] = []
        self.posts_calls: list[dict[str, Any]] = []
        self.counts_calls: list[dict[str, Any]] = []

    def search_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        self.search_calls.append(copy.deepcopy(params))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.search_raw)

    def get_post(self, tweet_id: str) -> dict[str, Any]:
        self.post_calls.append(tweet_id)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.post_raw)

    def get_user(self, username: str) -> dict[str, Any]:
        self.user_calls.append(username)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.user_raw)

    def user_posts(self, params: dict[str, Any]) -> dict[str, Any]:
        self.posts_calls.append(copy.deepcopy(params))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.posts_raw)

    def counts_recent(self, params: dict[str, Any]) -> dict[str, Any]:
        self.counts_calls.append(copy.deepcopy(params))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.counts_raw)


def user_row() -> dict[str, Any]:
    return {
        "id": "42",
        "name": "Test User",
        "username": "testuser",
        "created_at": "2020-01-01T00:00:00.000Z",
        "description": "bio",
        "public_metrics": {"followers_count": 10},
        "verified": False,
        "unexpected_field": "drop me",
    }
