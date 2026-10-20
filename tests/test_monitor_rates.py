"""Counters turned into totals and rates (WP-B3.1, design §9.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from edumatcher.models.generated.health import HealthBeacon
from edumatcher.monitor.activity import Activity
from edumatcher.monitor.rates import (
    BucketWindow,
    CounterTracker,
    Rate,
    Step,
    increment,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _wall(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=STOCKHOLM).timestamp()


class TestIncrement:
    def test_the_design_sequence(self) -> None:
        """10, 20, 5 (restart), 15 gives increments 10, 5, 10."""
        values = [10.0, 20.0, 5.0, 15.0]
        steps = [increment(a, b, restarted=False) for a, b in zip(values, values[1:])]
        assert steps == [10.0, 5.0, 10.0]

    def test_a_restart_counts_the_whole_new_value(self) -> None:
        assert increment(100.0, 150.0, restarted=True) == 150.0

    def test_no_previous_value_is_no_increment(self) -> None:
        assert increment(None, 42.0, restarted=False) == 0.0


class TestCounterTracker:
    def test_steps_and_restarts_by_boot_id(self) -> None:
        tracker = CounterTracker()
        key = ("pm-engine@box", "engine.orders_in", "GW1")
        assert tracker.step(key, "a", 10.0) == (10.0, Step.FIRST)
        assert tracker.step(key, "a", 25.0) == (15.0, Step.LIVE)
        # same value range, new process: everything since its start
        assert tracker.step(key, "b", 30.0) == (30.0, Step.LIVE)
        assert len(tracker) == 1
        tracker.forget_source("pm-engine@box")
        assert len(tracker) == 0

    def test_a_primed_series_resumes_once(self) -> None:
        """After a pm-monitor restart: what happened while it was down."""
        tracker = CounterTracker()
        key = ("pm-engine@box", "engine.orders_in", "GW1")
        tracker.prime({key: ("a", 100.0)})
        assert tracker.step(key, "a", 130.0) == (30.0, Step.RESUMED)
        assert tracker.step(key, "a", 131.0) == (1.0, Step.LIVE)

    def test_a_primed_series_of_a_restarted_process(self) -> None:
        tracker = CounterTracker()
        key = ("pm-engine@box", "engine.orders_in", "GW1")
        tracker.prime({key: ("a", 100.0)})
        assert tracker.step(key, "b", 7.0) == (7.0, Step.RESUMED)


class TestBucketWindow:
    def test_sums_within_the_span(self) -> None:
        w = BucketWindow(60.0, 1.0)
        w.add(100.0, 1.0)
        w.add(100.5, 2.0)  # same bucket
        w.add(130.0, 4.0)
        assert w.total(130.0) == 7.0
        assert w.total(160.9) == 7.0  # its bucket still overlaps the span
        assert w.total(161.0) == 4.0  # now the first bucket has aged out
        assert w.total(191.0) == 0.0

    def test_stays_bounded(self) -> None:
        w = BucketWindow(60.0, 1.0)
        for i in range(10_000):
            w.add(i * 0.5, 1.0)
        assert len(w._buckets) <= 61


class TestRate:
    def test_stats(self) -> None:
        r = Rate()
        for i in range(60):  # 2 per second for a minute
            r.add(1000.0 + i, 2.0)
        stats = r.stats(1059.5, hours_open=2.0)
        assert stats["today"] == 120
        assert stats["per_sec_now"] == pytest.approx(2.0)
        assert stats["avg_per_min"] == pytest.approx(2.0)  # 120 over 60 min
        assert stats["avg_per_hour"] == pytest.approx(60.0)
        assert stats["avg_per_day"] is None

    def test_unwindowed_counts_today_only(self) -> None:
        r = Rate()
        r.add(1000.0, 500.0, windowed=False)
        stats = r.stats(1000.0, hours_open=1.0)
        assert stats["today"] == 500
        assert stats["per_sec_now"] == 0.0

    def test_the_first_minute_after_the_open_does_not_explode(self) -> None:
        r = Rate()
        r.add(0.0, 10.0)
        assert r.stats(0.0, hours_open=0.0)["avg_per_hour"] == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# through Activity: first values, restarts and the trading day
# ---------------------------------------------------------------------------


def _engine(
    seq: int,
    orders: float,
    *,
    boot: str = "a" * 16,
    started: float,
    trades: float = 0.0,
) -> HealthBeacon:
    beacon = HealthBeacon.from_dict(
        {
            "process": "pm-engine",
            "pid": 1,
            "host": "box",
            "boot_id": boot,
            "seq": seq,
            "started_at_ns": int(started * 1e9),
            "interval_sec": 2.0,
            "rss_bytes": 1,
            "cpu_pct": 0.0,
            "threads": 1,
            "loop_age_ms": 0.0,
            "loop_lag_ms": 0.0,
            "metrics": [
                {
                    "name": "engine.orders_in",
                    "kind": "COUNTER",
                    "label": "GW1",
                    "value": orders,
                },
                {
                    "name": "engine.trades",
                    "kind": "COUNTER",
                    "label": "AAA",
                    "value": trades,
                },
            ],
        }
    )
    beacon.validate()
    return beacon


def _feed(a: Activity, beacons: list[tuple[HealthBeacon, float, float]]) -> None:
    for beacon, now, wall in beacons:
        a.observe("pm-engine@box", beacon, now, wall)


class TestActivityCounting:
    def test_restart_survives_in_today(self) -> None:
        a = Activity(STOCKHOLM)
        noon = _wall(2026, 10, 19, 12)
        start = _wall(2026, 10, 19, 8)
        _feed(
            a,
            [
                (_engine(0, 10, started=start), 0.0, noon),
                (_engine(1, 20, started=start), 2.0, noon + 2),
                (_engine(0, 5, boot="b" * 16, started=noon + 3), 4.0, noon + 4),
                (_engine(1, 15, boot="b" * 16, started=noon + 3), 6.0, noon + 6),
            ],
        )
        # first value 10 is today's (the engine started today), then 10, 5, 10
        assert a.orders.today == 35
        # only the increments seen live are in the rolling minute
        assert a.orders.minute.total(6.0) == 25

    def test_a_first_value_from_before_today_is_a_baseline(self) -> None:
        a = Activity(STOCKHOLM)
        noon = _wall(2026, 10, 19, 12)
        yesterday = _wall(2026, 10, 18, 9)
        _feed(
            a,
            [
                (_engine(0, 1000, started=yesterday, trades=7), 0.0, noon),
                (_engine(1, 1003, started=yesterday, trades=8), 2.0, noon + 2),
            ],
        )
        assert a.orders.today == 3
        # the engine's "daily" trade counter is a baseline too: it is zeroed
        # at PRE_OPEN, not midnight (or never, without sessions), so its first
        # value may hold earlier days (review R3)
        assert a.trades.today == 1

    def test_today_resets_at_local_midnight(self) -> None:
        a = Activity(STOCKHOLM)
        start = _wall(2026, 10, 19, 8)
        before = _wall(2026, 10, 19, 23, 59, 58)
        after = _wall(2026, 10, 20, 0, 0, 2)
        _feed(
            a,
            [
                (_engine(0, 0, started=start), 0.0, before - 10),
                (_engine(1, 50, started=start), 10.0, before),
            ],
        )
        assert (a.date, a.orders.today) == ("2026-10-19", 50)
        _feed(a, [(_engine(2, 60, started=start), 14.0, after)])
        assert (a.date, a.orders.today) == ("2026-10-20", 10)

    def test_avg_per_hour_counts_from_the_session_open(self) -> None:
        a = Activity(STOCKHOLM)
        a.roll_day(_wall(2026, 10, 19, 8))
        a.set_session_state("CLOSED", _wall(2026, 10, 19, 8))
        a.set_session_state("PRE_OPEN", _wall(2026, 10, 19, 9))
        assert a.hours_open(_wall(2026, 10, 19, 11)) == pytest.approx(2.0)
        # a later CLOSED -> open does not move today's open
        a.set_session_state("CLOSED", _wall(2026, 10, 19, 12))
        a.set_session_state("PRE_OPEN", _wall(2026, 10, 19, 13))
        assert a.hours_open(_wall(2026, 10, 19, 14)) == pytest.approx(5.0)

    def test_without_an_open_today_counts_from_midnight(self) -> None:
        a = Activity(STOCKHOLM)
        a.roll_day(_wall(2026, 10, 19, 6))
        assert a.hours_open(_wall(2026, 10, 19, 6)) == pytest.approx(6.0)


def test_dst_midnight(monkeypatch: Any) -> None:
    """The night the clocks go back (2026-10-25) is a 25-hour trading day."""
    a = Activity(STOCKHOLM)
    a.roll_day(_wall(2026, 10, 25, 23))
    assert a.hours_open(_wall(2026, 10, 25, 23)) == pytest.approx(24.0)
