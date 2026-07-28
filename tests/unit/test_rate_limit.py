"""Unit tests: sliding-window rate limiter."""

from app.core.rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_max_attempts():
    limiter = SlidingWindowRateLimiter(max_attempts=3, window_seconds=60)
    assert limiter.check("k")
    assert limiter.check("k")
    assert limiter.check("k")
    assert not limiter.check("k")


def test_keys_are_independent():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.check("a")
    assert limiter.check("b")
    assert not limiter.check("a")


def test_reset_clears_window():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    assert limiter.check("k")
    assert not limiter.check("k")
    limiter.reset("k")
    assert limiter.check("k")


def test_retry_after_positive_when_limited():
    limiter = SlidingWindowRateLimiter(max_attempts=1, window_seconds=60)
    limiter.check("k")
    assert limiter.retry_after("k") > 0
    assert limiter.retry_after("unknown") == 0
