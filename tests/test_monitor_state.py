"""pm-monitor's per-process state (WP-B1.3, design §9.1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from edumatcher.models.generated.health import HealthBeacon, ProcessHealth
from edumatcher.monitor.state import (
    MAX_SOURCES,
    RESTART_BADGE_SEC,
    SPARK_LEN,
    Ingest,
    ProcessTable,
    process_key,
)


def beacon(**overrides: Any) -> HealthBeacon:
    fields: dict[str, Any] = {
        "process": "pm-stats",
        "pid": 4242,
        "host": "box",
        "boot_id": "a" * 16,
        "seq": 0,
        "started_at_ns": 1_000_000_000_000,
        "interval_sec": 2.0,
        "rss_bytes": 100,
        "cpu_pct": 1.0,
        "threads": 3,
        "loop_age_ms": 5.0,
        "loop_lag_ms": 10.0,
        "metrics": [],
    }
    fields.update(overrides)
    obj = HealthBeacon.from_dict(fields)
    obj.validate()
    return obj


class TestKeys:
    def test_key_without_instance(self) -> None:
        assert process_key("pm-stats", None, "box") == "pm-stats@box"

    def test_key_with_instance(self) -> None:
        assert process_key("pm-api-gwy", "desk", "box") == "pm-api-gwy/desk@box"

    def test_instances_are_separate_sources(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(process="pm-api-gwy", instance="desk"), 0.0)
        table.ingest(beacon(process="pm-api-gwy", instance="dashboards"), 0.0)
        assert len(table) == 2

    def test_bots_are_their_own_group(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(process="pm-mm-bot"), 0.0)
        table.ingest(beacon(process="pm-stats"), 0.0)
        assert [(s.beacon.process, s.group) for s in table.states()] == [
            ("pm-stats", "EXCHANGE"),
            ("pm-mm-bot", "BOT"),
        ]


class TestIngest:
    def test_first_beacon_is_new(self) -> None:
        table = ProcessTable()
        assert table.ingest(beacon(), 1.0) is Ingest.NEW
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.received_at == 1.0
        assert list(state.rss) == [100]
        assert state.restarted_at is None

    def test_a_newer_seq_updates_and_extends_the_ring(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(), 1.0)
        assert table.ingest(beacon(seq=1, rss_bytes=200, cpu_pct=2.0), 3.0) is (
            Ingest.UPDATED
        )
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.beacon.seq == 1
        assert state.received_at == 3.0
        assert list(state.rss) == [100, 200]
        assert list(state.cpu) == [1.0, 2.0]

    def test_a_repeated_or_older_seq_is_stale(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(seq=5, loop_age_ms=1.0), 1.0)
        assert table.ingest(beacon(seq=5), 2.0) is Ingest.STALE
        assert table.ingest(beacon(seq=4, loop_age_ms=9000.0), 2.0) is Ingest.STALE
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.beacon.loop_age_ms == 1.0
        assert state.received_at == 1.0
        assert len(state.rss) == 1

    def test_a_new_boot_id_resets_the_ring_and_sets_restarted_at(self) -> None:
        table = ProcessTable()
        for seq in range(5):
            table.ingest(beacon(seq=seq), float(seq))
        outcome = table.ingest(
            beacon(
                boot_id="b" * 16, seq=0, started_at_ns=2_000_000_000_000, rss_bytes=7
            ),
            10.0,
        )
        assert outcome is Ingest.RESTARTED
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.boot_id == "b" * 16
        assert state.restarted_at == 10.0
        assert list(state.rss) == [7]
        # seq restarts at 0 for the new boot, and counts from there
        assert (
            table.ingest(
                beacon(boot_id="b" * 16, seq=1, started_at_ns=2_000_000_000_000), 11.0
            )
            is Ingest.UPDATED
        )

    def test_the_restart_badge_expires(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(), 0.0)
        table.ingest(beacon(boot_id="b" * 16, started_at_ns=2_000_000_000_000), 100.0)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.restarted_recently(100.0 + RESTART_BADGE_SEC - 1)
        assert not state.restarted_recently(100.0 + RESTART_BADGE_SEC)

    def test_a_late_beacon_of_an_older_boot_is_stale(self) -> None:
        """Two processes claiming one identity show as the newer one, not as a
        process restarting on every beacon."""
        table = ProcessTable()
        table.ingest(beacon(boot_id="b" * 16, started_at_ns=2_000_000_000_000), 0.0)
        assert table.ingest(beacon(seq=9), 1.0) is Ingest.STALE
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.boot_id == "b" * 16
        assert state.restarted_at is None

    def test_a_queued_burst_is_judged_by_its_newest_beacon(self) -> None:
        """A process that beaconed while pm-monitor was down delivers up to
        SNDHWM beacons at once; every one is a sample, the last one counts."""
        table = ProcessTable()
        for seq in range(10):
            table.ingest(beacon(seq=seq, loop_age_ms=float(seq), rss_bytes=seq), 5.0)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.beacon.loop_age_ms == 9.0
        assert list(state.rss) == list(range(10))

    def test_the_ring_holds_the_last_sixty(self) -> None:
        table = ProcessTable()
        for seq in range(SPARK_LEN + 5):
            table.ingest(beacon(seq=seq, rss_bytes=seq), float(seq))
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert list(state.rss) == list(range(5, SPARK_LEN + 5))

    def test_sources_are_bounded(self) -> None:
        table = ProcessTable(max_sources=2)
        assert table.ingest(beacon(host="a"), 0.0) is Ingest.NEW
        assert table.ingest(beacon(host="b"), 0.0) is Ingest.NEW
        assert table.ingest(beacon(host="c"), 0.0) is Ingest.REJECTED
        assert len(table) == 2
        # a known source still updates at the limit
        assert table.ingest(beacon(host="a", seq=1), 1.0) is Ingest.UPDATED

    def test_default_bound(self) -> None:
        assert ProcessTable().max_sources == MAX_SOURCES


class TestHealthRecord:
    def test_is_a_valid_process_health(self) -> None:
        table = ProcessTable()
        table.ingest(
            beacon(
                process="pm-api-gwy",
                instance="desk",
                fds=12,
                metrics=[{"name": "api.http_requests", "kind": "COUNTER", "value": 3}],
            ),
            10.0,
        )
        state = table.get("pm-api-gwy", "desk", "box")
        assert state is not None
        record = state.health(12.5, 1_100.0, "HEALTHY")
        ProcessHealth.from_dict(record).validate()
        assert record["key"] == "pm-api-gwy/desk@box"
        assert record["last_beacon_age_ms"] == 2500.0
        assert record["uptime_sec"] == 100.0  # wall 1100 s - start 1000 s
        assert record["spark"] == {"rss": [100], "cpu": [1.0]}
        assert record["metrics"] == [
            {"name": "api.http_requests", "kind": "COUNTER", "label": "", "value": 3.0}
        ]
        assert record["fds"] == 12
        assert record["restarted_recently"] is False

    def test_ages_are_never_negative(self) -> None:
        table = ProcessTable()
        table.ingest(beacon(started_at_ns=5_000_000_000_000), 10.0)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        record = state.health(9.0, 1.0, "HEALTHY")  # clocks behind the beacon
        assert record["last_beacon_age_ms"] == 0.0
        assert record["uptime_sec"] == 0.0


MB = 1024 * 1024

#: The 2026-11-16 simulation's open, as minute RSS in MiB from 07:00
#: (``samples_1m.v_last`` of ``proc.rss_bytes``): {minute: value from then on}.
OPEN_RALF_GWY = {0: 47, 90: 87, 91: 129, 92: 171, 93: 212, 94: 253, 95: 292,
                 96: 331, 97: 369, 98: 410, 99: 450, 100: 490, 101: 531,
                 102: 565, 103: 586, 104: 597}  # fmt: skip
OPEN_ENGINE = {0: 71, 60: 76, 61: 78, 62: 79, 65: 80, 90: 100, 91: 115,
               92: 126, 93: 138, 94: 146, 95: 154, 96: 156, 97: 159,
               98: 162, 99: 164, 100: 167, 101: 169, 102: 171}  # fmt: skip
OPEN_API_GWY = {0: 93, 61: 94, 62: 95, 87: 96, 90: 270, 91: 368, 92: 467,
                93: 565, 94: 659, 95: 735, 96: 737, 97: 740, 98: 741, 99: 742,
                100: 748, 101: 750, 109: 751, 116: 753}  # fmt: skip


def _growth_every_second(rss_mb: Callable[[int], float], seconds: int) -> list[int]:
    """Feed a beacon every 2 s with ``rss_mb(second)`` and judge the growth
    every second, as the collector does; the seconds it reported growth."""
    table = ProcessTable()
    reported: list[int] = []
    for s in range(seconds):
        if s % 2 == 0:
            table.ingest(beacon(seq=s, rss_bytes=int(rss_mb(s) * MB)), float(s))
        state = table.get("pm-stats", None, "box")
        assert state is not None
        if state.rss_growth_pct(float(s)) is not None:
            reported.append(s)
    return reported


def _minutes(steps: dict[int, int]) -> Callable[[int], float]:
    """``steps`` ({minute: MiB from then on}) as RSS by second."""
    return lambda s: steps[max(m for m in steps if m <= s // 60)]


class TestRssGrowth:
    """The rss_growth_pct_1h threshold's input (design §9.6, review R4)."""

    def _run(self, table: ProcessTable, minutes: int, rss: Any, **kw: Any) -> None:
        for m in range(minutes + 1):
            table.ingest(beacon(seq=m, rss_bytes=rss(m), **kw), m * 60.0)

    def test_no_figure_before_an_hour_after_warm_up(self) -> None:
        table = ProcessTable()
        self._run(table, 60, lambda m: 100 * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(60 * 60.0) is None

    def test_start_up_growth_is_not_a_leak(self) -> None:
        """Growing from 100 to 300 in the first 10 minutes, then flat: the
        baseline is taken after the warm-up, so the hour added nothing."""
        table = ProcessTable()
        self._run(table, 80, lambda m: (100 + 20 * min(m, 10)) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None

    def test_a_leak_after_warm_up(self) -> None:
        table = ProcessTable()
        self._run(table, 80, lambda m: (100 if m < 10 else 100 + 2 * (m - 10)) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        # 80 min: 240; an hour earlier (20 min): 120 -> +100 %
        assert state.rss_growth_pct(80 * 60.0) == pytest.approx(100.0)

    def test_a_step_that_levelled_off_is_not_a_leak(self) -> None:
        """Idle for 70 minutes, a 5x step at minute 65, flat since: the hour
        shows +400 % but RSS has not risen in the last 15 minutes."""
        table = ProcessTable()
        self._run(table, 80, lambda m: (100 if m < 65 else 500) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None

    def test_a_fresh_ramp_is_not_a_leak(self) -> None:
        """Idle, then a 5x ramp over two minutes ten minutes ago (continuous
        trading starting): the growth is all inside the last 15 minutes."""
        table = ProcessTable()
        self._run(
            table,
            80,
            lambda m: (100 if m < 70 else min(500, 100 + 200 * (m - 70))) * MB,
        )
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None
        assert state.rss_growth_pct(72 * 60.0) is None

    def test_a_step_with_a_slow_rise_after_is_not_a_leak(self) -> None:
        """A 5x step at minute 65, then +1 MB a minute: the hour's growth is
        the step, in one quarter of it (WP-MHD02; this read as a leak)."""
        table = ProcessTable()
        self._run(table, 80, lambda m: (100 if m < 65 else 500 + m) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None

    @pytest.mark.parametrize(
        "steps",
        [OPEN_RALF_GWY, OPEN_ENGINE, OPEN_API_GWY],
        ids=["pm-ralf-gwy", "pm-engine", "pm-api-gwy"],
    )
    def test_the_market_open_is_not_a_leak(self, steps: dict[int, int]) -> None:
        """The 2026-11-16 simulation's open (minute RSS from metrics.db, 07:00
        to 09:29): memory fills over ~13 minutes from 08:30, then stays flat.
        Judged every second, it is never a leak (C2: CRIT at 08:47-08:51)."""
        assert _growth_every_second(_minutes(steps), 150 * 60) == []

    def test_a_steady_leak_is_reported_from_its_first_hour(self) -> None:
        """100 MB + 150 MB/h: history starts after the 10 min warm-up, so the
        first full hour of it ends at 70 min."""
        reported = _growth_every_second(lambda s: 100 + 150 * s / 3600, 180 * 60)
        assert reported and reported[0] <= 70 * 60 + 60

    def test_a_leak_starting_mid_run_is_reported(self) -> None:
        """300 MB flat for 30 min, then +400 MB/h: reported by 81 min."""
        reported = _growth_every_second(
            lambda s: 300 + 400 * max(0, s - 1800) / 3600, 180 * 60
        )
        assert reported and reported[0] <= 81 * 60

    def test_a_fall_in_one_quarter_is_not_a_leak(self) -> None:
        """+3 MB/min from minute 10, a GC release of 2 MB/min in minutes
        50-65, rising again after: at 80 the hour shows +80 %, but one
        quarter gave memory back, so it is not a steady leak."""

        def rss(m: int) -> int:
            if m < 10:
                return 100
            if m < 50:
                return 100 + 3 * (m - 10)
            if m < 65:
                return 220 - 2 * (m - 50)
            return 190 + 3 * (m - 65)

        table = ProcessTable()
        self._run(table, 80, lambda m: rss(m) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None

    def test_a_small_process_doubling_is_not_a_leak(self) -> None:
        table = ProcessTable()
        self._run(table, 80, lambda m: (10 if m < 20 else 10 + (m - 20) // 3) * MB)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(80 * 60.0) is None

    def test_not_while_starting(self) -> None:
        table = ProcessTable()
        self._run(table, 80, lambda m: 100, starting=True)
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert len(state.rss_history) == 0

    def test_a_restart_clears_the_history(self) -> None:
        table = ProcessTable()
        self._run(table, 80, lambda m: 100)
        table.ingest(
            beacon(boot_id="b" * 16, started_at_ns=2_000_000_000_000, rss_bytes=999),
            81 * 60.0,
        )
        state = table.get("pm-stats", None, "box")
        assert state is not None
        assert state.rss_growth_pct(81 * 60.0) is None
