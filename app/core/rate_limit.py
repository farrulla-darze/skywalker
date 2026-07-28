"""In-memory sliding-window rate limiter.

Suitable for a single-process deployment; swap for a Redis-backed
implementation behind the same interface when scaling horizontally.
"""

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    """Tracks event timestamps per key and rejects when the window is full."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Record an attempt for *key*. Returns True if allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_attempts:
                return False
            bucket.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest event in the window expires (0 if not limited)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events.get(key)
            if not bucket or len(bucket) < self.max_attempts:
                return 0
            return max(0, int(bucket[0] + self.window_seconds - now) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
