"""Rate limiter unit tests."""

import time

from app.services.rate_limiter import RateLimiter


def test_user_within_limit(monkeypatch) -> None:
    """5 requests within the limit should all be allowed."""
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_user_per_minute", 5)
    limiter = RateLimiter()
    for _ in range(5):
        assert limiter.check_user("user-1")
        limiter.record("user-1")


def test_user_exceeds_limit(monkeypatch) -> None:
    """The 6th request should be rejected."""
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_user_per_minute", 5)
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_global_per_minute", 1000)
    limiter = RateLimiter()
    for _ in range(5):
        limiter.record("user-1")
    assert not limiter.check_user("user-1")


def test_global_limit(monkeypatch) -> None:
    """Exceeding the global limit should reject requests."""
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_user_per_minute", 1000)
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_global_per_minute", 3)
    limiter = RateLimiter()
    for i in range(3):
        limiter.record(f"user-{i}")
    assert not limiter.check_global()


def test_timestamp_expiry(monkeypatch) -> None:
    """Requests older than 60 seconds should not count."""
    monkeypatch.setattr("app.services.rate_limiter.settings.rate_limit_user_per_minute", 2)
    limiter = RateLimiter()

    # Manually insert an old timestamp.
    from collections import deque
    old_time = time.monotonic() - 61
    limiter._user_windows["user-1"] = deque([old_time])

    # The old entry should be pruned, so the user is within limit.
    assert limiter.check_user("user-1")
