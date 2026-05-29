"""Shared monotonic nanosecond clock helpers.

Use now_ns() for all ordering-critical timestamps. It guarantees strictly
increasing values even if the system wall clock moves backwards.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_last_ns = 0


def now_ns() -> int:
    """Return a strictly increasing nanosecond timestamp.

    Uses wall-clock nanoseconds as the base value and enforces monotonicity
    with a lock to avoid ties/regressions across threads.
    """
    global _last_ns
    candidate = time.time_ns()
    with _lock:
        if candidate <= _last_ns:
            candidate = _last_ns + 1
        _last_ns = candidate
        return candidate


def reset_clock_for_tests() -> None:
    """Reset internal monotonic state (tests only)."""
    global _last_ns
    with _lock:
        _last_ns = 0
