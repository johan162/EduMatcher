"""Time sources for the AI traders.

Every component reads time through a ``Clock`` so a worker can run on the
wall clock live and on a ``ManualClock`` in tests and event-log replay,
where the same seed and the same events must produce the same orders.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float:
        """Seconds on a monotonic scale; only differences are meaningful."""
        ...

    def wall(self) -> float:
        """Seconds since the epoch (UTC), for comparing with wire timestamps."""
        ...


class WallClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def wall(self) -> float:
        return time.time()


class ManualClock:
    """A clock that only moves when told to."""

    def __init__(self, start: float = 1_000.0, wall_start: float = 1.8e9) -> None:
        self._t = start
        self._wall_offset = wall_start - start

    def monotonic(self) -> float:
        return self._t

    def wall(self) -> float:
        return self._t + self._wall_offset

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a clock cannot move backwards")
        self._t += seconds
