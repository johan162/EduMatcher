"""pm-monitor's per-process state (WP-B1.3, design §9.1)."""

from __future__ import annotations

from typing import Any

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
