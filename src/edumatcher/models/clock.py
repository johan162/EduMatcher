"""Shared never-decreasing nanosecond clock helpers.

Use now_ns() for all ordering-critical timestamps. It is wall-clock time
(epoch nanoseconds, not a monotonic clock such as ``time.monotonic_ns``)
with a guard: values strictly increase even if the wall clock steps
backwards, in which case each call returns the previous value plus 1 ns
until the wall clock catches up.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_last_ns = 0


def now_ns() -> int:
    """Return a strictly increasing nanosecond timestamp.

    Uses wall-clock nanoseconds as the base value and, under a lock, never
    returns a value at or below the previous one (ties and regressions
    across threads become previous + 1 ns).
    """
    global _last_ns
    candidate = time.time_ns()
    with _lock:
        if candidate <= _last_ns:
            candidate = _last_ns + 1
        _last_ns = candidate
        return candidate


def reset_clock_for_tests() -> None:
    """Reset the never-decrease guard (tests only)."""
    global _last_ns
    with _lock:
        _last_ns = 0
