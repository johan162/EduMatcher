"""Threshold rules with hysteresis (WP-B3.4, design §9.6)."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from zoneinfo import ZoneInfo

import pytest

from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig, MonitorThresholds
from edumatcher.monitor.thresholds import (
    CLEAR_AFTER,
    Reading,
    ThresholdBook,
    band_reading,
    increase_reading,
)
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost

T = MonitorThresholds()


def _cpu(value: float) -> Reading:
    return band_reading(T, "host_cpu_pct", "host", value)


def _run(book: ThresholdBook, values: Sequence[float]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(f"{c.previous}->{c.level}" for c in book.evaluate([_cpu(v)], "ts"))
    return out


class TestLevels:
    def test_reading_levels(self) -> None:
        assert [_cpu(v).level() for v in (80.0, 80.1, 95.0, 95.1)] == [
            "OK",
            "WARN",
            "WARN",
            "CRIT",
        ]

    def test_disk_free_is_inverted(self) -> None:
        disk = [
            band_reading(T, "disk_free_pct", "host", v).level()
            for v in (15, 14.9, 5, 4.9)
        ]
        assert disk == ["OK", "WARN", "WARN", "CRIT"]

    def test_an_increase_rule_has_no_critical_level(self) -> None:
        assert increase_reading("stats_feed_gaps", "pm-stats@box", 0).level() == "OK"
        assert (
            increase_reading("stats_feed_gaps", "pm-stats@box", 1e9).level() == "WARN"
        )


class TestHysteresis:
    def test_an_oscillating_value_breaches_once_and_clears_once(self) -> None:
        book = ThresholdBook()
        values = [79, 81, 79, 81, 79, 81, 79, 79, 79]
        assert _run(book, values) == ["OK->WARN", "WARN->OK"]

    def test_rises_at_once(self) -> None:
        book = ThresholdBook()
        assert _run(book, [50, 96]) == ["OK->CRIT"]

    def test_eases_to_the_highest_level_of_the_lower_run(self) -> None:
        book = ThresholdBook()
        assert _run(book, [96, 85, 50, 85]) == ["OK->CRIT", "CRIT->WARN"]

    def test_a_reading_that_stops_arriving_clears(self) -> None:
        book = ThresholdBook()
        book.evaluate([_cpu(99)], "ts")
        changes = [book.evaluate([], "ts") for _ in range(CLEAR_AFTER)]
        assert [len(c) for c in changes] == [0] * (CLEAR_AFTER - 1) + [1]
        assert book.active() == []

    def test_active_breaches(self) -> None:
        book = ThresholdBook()
        book.evaluate([_cpu(90)], "2026-10-19T10:00:00.000Z")
        book.evaluate([_cpu(97)], "2026-10-19T10:00:01.000Z")
        assert book.active() == [
            {
                "rule": "host_cpu_pct",
                "subject": "host",
                "level": "CRIT",
                "value": 97.0,
                "threshold": 95.0,
                "since": "2026-10-19T10:00:00.000Z",
            }
        ]
        assert book.breached_subjects() == {"host"}

    def test_change_detail(self) -> None:
        book = ThresholdBook()
        (breach,) = book.evaluate([band_reading(T, "disk_free_pct", "host", 3.0)], "ts")
        assert (breach.severity, breach.detail) == ("CRIT", "disk_free_pct CRIT 3 < 5")


@pytest.fixture
def monitor() -> Iterator[Monitor]:
    pull, pub = free_ports(2)
    m = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        ZoneInfo("Europe/Stockholm"),
        host_sampler=QuietHost(),
    )
    try:
        yield m
    finally:
        m.close()


def test_an_oscillation_logs_one_breach_and_one_clear(
    monitor: Monitor, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = iter([79, 81, 79, 81, 79, 81, 79, 79, 79])
    monkeypatch.setattr(monitor, "readings", lambda now, host: [_cpu(next(values))])
    events: list[tuple[str, str, str]] = []

    def record(kind: str, severity: str, subject: str, detail: str) -> bool:
        events.append((kind, severity, detail))
        return True

    monkeypatch.setattr(monitor, "publish_event", record)
    caplog.set_level(logging.INFO, logger="edumatcher.monitor.collector")
    for _ in range(9):
        monitor.snapshot()
    lines = [
        (r.levelname, r.getMessage())
        for r in caplog.records
        if "threshold" in r.getMessage()
    ]
    assert lines == [
        ("WARNING", "threshold host_cpu_pct WARN 81 > 80 on host"),
        ("INFO", "threshold host_cpu_pct cleared (79) on host"),
    ]
    assert [e for e in events if e[0] == "THRESHOLD"] == [
        ("THRESHOLD", "WARN", "host_cpu_pct WARN 81 > 80"),
        ("THRESHOLD", "INFO", "host_cpu_pct cleared (79)"),
    ]
    assert monitor.threshold_changes == 2


def test_a_critical_breach_logs_at_error(
    monitor: Monitor, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(monitor, "readings", lambda now, host: [_cpu(99)])
    caplog.set_level(logging.INFO, logger="edumatcher.monitor.collector")
    snap = monitor.snapshot()
    assert [r.levelname for r in caplog.records if "threshold" in r.getMessage()] == [
        "ERROR"
    ]
    # a breach on no process degrades the exchange
    assert snap["thresholds"][0]["level"] == "CRIT"


def test_a_process_breach_makes_that_process_degraded(
    monitor: Monitor, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from tests.test_monitor_main import _beacon_frames

    monitor.receive(_beacon_frames(), time.monotonic())
    monkeypatch.setattr(
        monitor,
        "readings",
        lambda now, host: [
            band_reading(T, "rss_growth_pct_1h", "pm-engine@box", 150.0)
        ],
    )
    snap = monitor.snapshot()
    assert [(p["key"], p["state"]) for p in snap["processes"]] == [
        ("pm-engine@box", "DEGRADED")
    ]
    assert snap["exchange"]["status"] == "DEGRADED"
