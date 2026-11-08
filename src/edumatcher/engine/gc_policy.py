"""Garbage-collection policy for the matching engine's run loop.

CPython frees almost everything by reference counting; the cyclic collector
finds next to nothing in the engine (about 1000 objects per 120k messages)
yet a full pass over a big resting book takes 44-91 ms, against ~130 us for
an order. So the collector is kept off the message path:

* ``gc.freeze()`` once the book has filled, which takes the long-lived
  objects out of every later scan. The market open fills books and caches
  over the first minutes of continuous trading, so the freeze is armed on
  entering CONTINUOUS and done ``FREEZE_DELAY_SEC`` later.
* The thresholds are raised far above the defaults, so a busy engine only
  collects when net allocation really grows (the safety net). The routine
  collections run on idle ticks of the run loop instead.

Dead objects, frozen or not, are still freed by reference counting; only
reference cycles among frozen objects are never reclaimed.
"""

from __future__ import annotations

import gc
import time
from collections.abc import Callable

#: How long after continuous trading starts the long-lived set is frozen.
FREEZE_DELAY_SEC = 180.0
#: A freeze waits for an idle tick, but not longer than this past its due time.
FREEZE_FORCE_AFTER_SEC = 60.0
#: Net allocations of tracked objects between automatic generation-0
#: collections (the CPython default is 2000), and the multipliers up the
#: generations: the safety net, not the routine.
SAFETY_THRESHOLDS = (50_000, 10, 10)
#: A full collection on an idle tick at most this often; younger ones are
#: collected on every idle tick.
FULL_COLLECT_EVERY_SEC = 300.0


class GcPolicy:
    """Freeze after the open, collect when idle. One per engine run."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._saved: tuple[int, int, int] | None = None
        #: When the pending freeze is due; 0.0 when none is armed.
        self.freeze_at = 0.0
        self._last_full = 0.0

    def start(self) -> None:
        self._saved = gc.get_threshold()
        gc.set_threshold(*SAFETY_THRESHOLDS)
        self._last_full = self._clock()

    def stop(self) -> None:
        if self._saved is not None:
            gc.set_threshold(*self._saved)
            self._saved = None
        gc.unfreeze()
        self.freeze_at = 0.0

    def arm_freeze(self) -> None:
        """Continuous trading has started: freeze once the book has filled."""
        self.freeze_at = self._clock() + FREEZE_DELAY_SEC

    def tick(self, idle: bool) -> None:
        """Called each loop pass while ``freeze_at`` is set, and each idle one.

        ``idle`` means the poll timed out with no message to handle.
        """
        now = self._clock()
        if self.freeze_at and now >= self.freeze_at:
            if idle or now >= self.freeze_at + FREEZE_FORCE_AFTER_SEC:
                gc.collect()
                gc.freeze()
                self.freeze_at = 0.0
                self._last_full = now
                return
        if not idle:
            return
        if now - self._last_full >= FULL_COLLECT_EVERY_SEC:
            gc.collect()
            self._last_full = now
        else:
            gc.collect(1)
