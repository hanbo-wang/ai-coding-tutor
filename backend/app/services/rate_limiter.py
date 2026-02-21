"""In memory sliding window rate limiter for LLM requests."""

import time
from collections import deque

from app.config import settings


class RateLimiter:
    """Track per user and global LLM request rates using sliding windows."""

    def __init__(self) -> None:
        self._user_windows: dict[str, deque[float]] = {}
        self._global_window: deque[float] = deque()

    def _prune(self, window: deque[float], now: float) -> None:
        """Remove timestamps older than 60 seconds."""
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()

    def check_user(self, user_id: str) -> bool:
        """Return True if the user is within their per minute limit."""
        now = time.monotonic()
        window = self._user_windows.get(user_id)
        if window is None:
            return True
        self._prune(window, now)
        return len(window) < settings.rate_limit_user_per_minute

    def check_global(self) -> bool:
        """Return True if the global per minute limit is not exceeded."""
        now = time.monotonic()
        self._prune(self._global_window, now)
        return len(self._global_window) < settings.rate_limit_global_per_minute

    def record(self, user_id: str) -> None:
        """Record a request for both user and global counters."""
        now = time.monotonic()
        if user_id not in self._user_windows:
            self._user_windows[user_id] = deque()
        self._user_windows[user_id].append(now)
        self._global_window.append(now)


# Single instance shared across the application.
rate_limiter = RateLimiter()
