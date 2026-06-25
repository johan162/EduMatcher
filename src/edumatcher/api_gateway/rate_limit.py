"""Small token-bucket rate limiter for API write endpoints."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    """A single-client token bucket.

    The implementation favours readability over cleverness.  Tokens refill
    continuously according to monotonic time, then each write endpoint consumes
    one token before sending anything to the engine.
    """

    rate_per_second: int
    burst: int
    tokens: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)
        self.updated_at = time.monotonic()

    def allow(self) -> bool:
        """Return True if one token can be consumed now."""
        now = time.monotonic()
        elapsed = now - self.updated_at
        self.updated_at = now
        self.tokens = min(
            float(self.burst), self.tokens + elapsed * self.rate_per_second
        )
        if self.tokens < 1.0:
            return False
        self.tokens -= 1.0
        return True


class RateLimiter:
    """Per-API-key token buckets."""

    def __init__(self, writes_per_second: int, burst: int) -> None:
        self._writes_per_second = writes_per_second
        self._burst = burst
        self._buckets: dict[str, TokenBucket] = {}

    def allow(self, api_key: str) -> bool:
        bucket = self._buckets.get(api_key)
        if bucket is None:
            bucket = TokenBucket(self._writes_per_second, self._burst)
            self._buckets[api_key] = bucket
        return bucket.allow()
