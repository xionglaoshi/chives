from __future__ import annotations

from x_mcp.ratelimit import TokenBucket


def test_bucket_allows_capacity_then_blocks() -> None:
    now = [0.0]
    bucket = TokenBucket(2, 10.0, clock=lambda: now[0])
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False
    assert bucket.retry_after() > 0


def test_bucket_refills_over_time() -> None:
    now = [0.0]
    bucket = TokenBucket(1, 10.0, clock=lambda: now[0])
    assert bucket.allow() is True
    assert bucket.allow() is False
    now[0] = 10.0
    assert bucket.allow() is True


def test_bucket_never_exceeds_capacity() -> None:
    now = [0.0]
    bucket = TokenBucket(2, 1.0, clock=lambda: now[0])
    now[0] = 1000.0
    assert bucket.allow() is True
    assert bucket.allow() is True
    assert bucket.allow() is False


def test_retry_after_is_zero_when_a_token_is_available() -> None:
    bucket = TokenBucket(1, 10.0, clock=lambda: 0.0)
    assert bucket.retry_after() == 0
