"""Counters turned into totals and rates (design §9.4).

Every process ships its counters as totals since it started; pm-monitor turns
them into increments by differencing, so the hot path of the engine never
publishes per event. Three pieces:

* :func:`increment` -- one reset-corrected step of one counter.
* :class:`CounterTracker` -- the last value of every ``(source, name, label)``
  series, so each beacon can be turned into increments.
* :class:`Rate` -- the increments of one figure the dashboard shows, kept as
  "today" plus coarse rolling windows: the last 60 s in 1 s buckets, the last
  5 min in 5 s buckets, the last 60 min in 1 min buckets. Each window holds at
  most 60 buckets whatever the beacon rate, so memory is fixed per figure.

All times are pm-monitor's receive clock (K6).

The first value of a series
---------------------------
pm-monitor can start long after the process it watches. A counter's first
value then holds everything since that process started, and none of it
happened in the last minute, so it never enters a rolling window. It counts
towards *today* only when it is known to belong to today: the process started
on the current trading date. Otherwise it is a baseline.

That holds for the engine's "daily" book counters (``engine.trades``,
``traded_qty``, ``traded_value``) too: the engine zeroes them on the move to
PRE_OPEN, not at midnight, and never when sessions are off, so their first
value can hold yesterday's trades or a week's (review R3).

After a pm-monitor restart the tracker is *primed* from ``metrics.db``
(``counter_last``, WP-B4): the first value of a primed series is a
``RESUMED`` step whose increment is exactly what happened while pm-monitor
was down (or the whole value, if the process restarted meanwhile). It counts
towards today but not into a rolling window, where it would be a spike.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field
from typing import Any

#: Smallest "hours since the session opened" used for avg_per_hour, so the
#: first seconds after the open do not divide by almost nothing.
MIN_HOURS_OPEN = 1.0 / 60.0

SeriesKey = tuple[str, str, str]  # (source key, metric name, label)


def increment(previous: float | None, current: float, restarted: bool) -> float:
    """One reset-corrected increment (§9.4).

    A new process (``restarted``) or a value that went down started again from
    zero, so the whole current value is the increment.
    """
    if previous is None:
        return 0.0
    if restarted or current < previous:
        return current
    return current - previous


class BucketWindow:
    """Increments over the last ``span`` seconds, in ``bucket``-second buckets.

    Accurate to one bucket at the old edge, which is what lets it stay at
    ``span / bucket`` entries whatever the sample rate.
    """

    def __init__(self, span: float, bucket: float) -> None:
        self.span = span
        self.bucket = bucket
        self._buckets: deque[list[float]] = deque()  # [bucket start, sum]

    def add(self, t: float, delta: float) -> None:
        start = t - t % self.bucket
        if self._buckets and self._buckets[-1][0] == start:
            self._buckets[-1][1] += delta
        else:
            self._buckets.append([start, delta])
        self._prune(t)

    def total(self, now: float) -> float:
        self._prune(now)
        return sum(b[1] for b in self._buckets)

    def _prune(self, now: float) -> None:
        horizon = now - self.span
        while self._buckets and self._buckets[0][0] + self.bucket <= horizon:
            self._buckets.popleft()


@dataclass
class Rate:
    """One ``RateStats`` figure: today's total and the rolling windows."""

    today: float = 0.0
    minute: BucketWindow = field(default_factory=lambda: BucketWindow(60.0, 1.0))
    five_min: BucketWindow = field(default_factory=lambda: BucketWindow(300.0, 5.0))
    hour: BucketWindow = field(default_factory=lambda: BucketWindow(3600.0, 60.0))

    def add(self, t: float, delta: float, *, windowed: bool = True) -> None:
        if delta <= 0:
            return
        self.today += delta
        if windowed:
            self.minute.add(t, delta)
            self.five_min.add(t, delta)
            self.hour.add(t, delta)

    def new_day(self) -> None:
        self.today = 0.0

    def last_5m(self, now: float) -> float:
        return self.five_min.total(now)

    def stats(
        self, now: float, hours_open: float, avg_per_day: float | None = None
    ) -> dict[str, Any]:
        """The ``RateStats`` wire record."""
        return {
            "today": int(round(self.today)),
            "per_sec_now": self.minute.total(now) / 60.0,
            "avg_per_min": self.hour.total(now) / 60.0,
            "avg_per_hour": self.today / max(hours_open, MIN_HOURS_OPEN),
            "avg_per_day": avg_per_day,
        }


class Step(enum.Enum):
    """How a counter value relates to what pm-monitor knew of the series."""

    FIRST = "first"  # never seen: the value is everything since process start
    RESUMED = "resumed"  # first since a pm-monitor restart, primed from disk
    LIVE = "live"  # seen in this run: a live increment


class CounterTracker:
    """The last value of every counter series, per process incarnation."""

    def __init__(self) -> None:
        self._last: dict[SeriesKey, tuple[str, float]] = {}  # -> (boot_id, value)
        self._primed: set[SeriesKey] = set()

    @property
    def state(self) -> dict[SeriesKey, tuple[str, float]]:
        """``(boot_id, value)`` per series, for ``metrics.db``'s ``counter_last``."""
        return self._last

    def prime(self, state: dict[SeriesKey, tuple[str, float]]) -> None:
        """Resume from the counter state ``metrics.db`` last recorded."""
        self._last.update(state)
        self._primed.update(state)

    def step(self, key: SeriesKey, boot_id: str, value: float) -> tuple[float, Step]:
        """The increment of a new value, and what kind of step it was.

        A new ``boot_id`` for a known series is a restart: the whole value is
        the increment (§9.4).
        """
        last = self._last.get(key)
        self._last[key] = (boot_id, value)
        if last is None:
            return value, Step.FIRST
        last_boot, last_value = last
        delta = increment(last_value, value, restarted=boot_id != last_boot)
        if key in self._primed:
            self._primed.discard(key)
            return delta, Step.RESUMED
        return delta, Step.LIVE

    def forget_source(self, source: str) -> None:
        """Drop every series of a source pm-monitor no longer tracks."""
        for key in [k for k in self._last if k[0] == source]:
            del self._last[key]
            self._primed.discard(key)

    def __len__(self) -> int:
        return len(self._last)
