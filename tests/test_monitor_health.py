"""pm-monitor's health model and exchange status (WP-B2, design §10)."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from typing import Any
from zoneinfo import ZoneInfo

import psutil
import pytest

from edumatcher.models.generated.health import HealthBeacon, HealthSnapshot
from edumatcher.monitor.collector import FORGET_AFTER_SEC, Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.thresholds import CLEAR_AFTER, RAISE_AFTER
from edumatcher.monitor.state import (
    STARTUP_GRACE_SEC,
    HealthRules,
    ProcessState,
    exchange_status,
    missing_health,
    process_alive,
)
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost
from tests.test_monitor_main import _beacon_frames


class BusyHost(QuietHost):
    """QuietHost with its CPU at ``cpu_pct``."""

    def __init__(self, cpu_pct: float) -> None:
        self.cpu_pct = cpu_pct

    def sample(self) -> dict[str, Any]:
        return {**super().sample(), "cpu_pct": self.cpu_pct}


RULES = HealthRules(hung_after_sec=5.0, silent_after_beacons=3, local_host="box")
#: interval_sec 2 x silent_after_beacons 3
LIMIT = 6.0


def _state(received_at: float = 100.0, **overrides: Any) -> ProcessState:
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
    beacon = HealthBeacon.from_dict(fields)
    beacon.validate()
    return ProcessState(beacon=beacon, received_at=received_at)


def _alive(_pid: int, _started: int) -> bool:
    return True


def _gone(_pid: int, _started: int) -> bool:
    return False


# ---------------------------------------------------------------------------
# B2.1 evaluate
# ---------------------------------------------------------------------------

EVALUATE_CASES: list[tuple[str, dict[str, Any], float, Any, bool, str]] = [
    # id, beacon overrides, seconds since the beacon, alive, breached, state
    ("healthy", {}, 1.0, _alive, False, "HEALTHY"),
    ("final", {"final": True}, 1.0, _alive, False, "STOPPED"),
    ("final beats silence", {"final": True}, 999.0, _gone, False, "STOPPED"),
    ("silence boundary is not silent", {}, LIMIT, _gone, False, "HEALTHY"),
    ("silent, pid gone", {}, LIMIT + 0.001, _gone, False, "DEAD"),
    ("silent, pid alive", {}, LIMIT + 0.001, _alive, False, "SILENT"),
    ("silence beats hung", {"loop_age_ms": 1e6}, LIMIT + 1, _alive, False, "SILENT"),
    ("other host, silent", {"host": "far"}, LIMIT + 0.001, _gone, False, "SILENT"),
    ("other host, 2x boundary", {"host": "far"}, 2 * LIMIT, _gone, False, "SILENT"),
    ("other host, dead", {"host": "far"}, 2 * LIMIT + 0.001, _alive, False, "DEAD"),
    ("sender interval scales", {"interval_sec": 0.5}, 1.6, _gone, False, "DEAD"),
    ("hung boundary", {"loop_age_ms": 5000.0}, 1.0, _alive, False, "HEALTHY"),
    ("hung", {"loop_age_ms": 5000.1}, 1.0, _alive, False, "HUNG"),
    (
        "starting has a grace",
        {"starting": True, "loop_age_ms": 60_000.0},
        1.0,
        _alive,
        False,
        "HEALTHY",
    ),
    (
        "stuck starting surfaces",
        {"starting": True, "loop_age_ms": STARTUP_GRACE_SEC * 1000 + 1},
        1.0,
        _alive,
        False,
        "HUNG",
    ),
    ("hung beats degraded", {"loop_age_ms": 9000.0}, 1.0, _alive, True, "HUNG"),
    # A late loop is the loop_lag_ms rule's to judge (WP-MHD01), not evaluate's.
    ("lag alone", {"loop_lag_ms": 1000.1}, 1.0, _alive, False, "HEALTHY"),
    ("threshold breach", {}, 1.0, _alive, True, "DEGRADED"),
]


# ---------------------------------------------------------------------------
# I108: a process that stood still is not judged HUNG for it
# ---------------------------------------------------------------------------


def _then(state: ProcessState, at: float, **overrides: Any) -> str:
    """Feed the next beacon of ``state`` at ``at`` and judge it there."""
    fields = state.beacon.to_dict()
    fields.update({"seq": state.beacon.seq + 1, **overrides})
    beacon = HealthBeacon.from_dict(fields)
    beacon.validate()
    state.accept(beacon, at, RULES.silent_after_beacons)
    return state.evaluate(at, RULES, alive=_alive)


def test_sigstop_then_sigcont_is_silent_then_healthy() -> None:
    """Found end to end: the first beacons after a SIGCONT carry the stopped
    time in loop_age and then in loop_lag; neither is the loop's doing."""
    state = _state(received_at=100.0, loop_age_ms=50.0)
    assert state.evaluate(120.0, RULES, alive=_alive) == "SILENT"
    # Resumed: the sampler beacons before the loop ticks.
    assert _then(state, 120.0, loop_age_ms=19_050.0) == "HEALTHY"
    # Below the 1 s loop-age warning too, or the threshold would degrade it.
    assert state.loop_age_ms < 1_000.0
    # The loop has ticked; this beacon's worst gap spans the stop.
    assert _then(state, 122.0, loop_age_ms=30.0, loop_lag_ms=20_040.0) == "HEALTHY"
    assert state.loop_lag_ms == pytest.approx(40.0)  # the loop's own share
    assert state.loop_age_ms == 30.0
    # From here on the figures are the beacon's own again.
    _then(state, 124.0, loop_age_ms=30.0, loop_lag_ms=1_500.0)
    assert state.loop_lag_ms == 1_500.0  # for the loop_lag_ms rule to judge
    assert _then(state, 126.0, loop_age_ms=6_000.0, loop_lag_ms=0.0) == "HUNG"


def test_a_loop_hung_before_the_stop_stays_hung() -> None:
    """Hung 4 s at the stop: HUNG again within one interval of the resume."""
    state = _state(received_at=100.0, loop_age_ms=4_000.0)
    _then(state, 120.0, loop_age_ms=24_000.0)
    assert _then(state, 122.0, loop_age_ms=26_000.0) == "HUNG"
    assert _then(state, 124.0, loop_age_ms=28_000.0) == "HUNG"


def test_a_gap_short_of_silent_is_not_credited() -> None:
    """Never reported SILENT, so nothing is hidden: a 4.5 s gap stays in the figures."""
    state = _state(received_at=100.0, loop_age_ms=50.0)
    assert _then(state, 105.0, loop_age_ms=5_100.0) == "HUNG"
    assert state.age_credit_sec == 0.0


def test_a_restart_carries_no_credit() -> None:
    state = _state(received_at=100.0, loop_age_ms=50.0)
    _then(state, 120.0, loop_age_ms=20_050.0)
    assert state.age_credit_sec > 0
    _then(
        state,
        121.0,
        boot_id="b" * 16,
        seq=0,
        started_at_ns=2_000_000_000_000,
        loop_age_ms=6_000.0,
    )
    assert (
        state.age_credit_sec == 0.0
        and state.evaluate(121.0, RULES, alive=_alive) == "HUNG"
    )


@pytest.mark.parametrize(
    ("overrides", "silence", "alive", "breached", "expected"),
    [case[1:] for case in EVALUATE_CASES],
    ids=[case[0] for case in EVALUATE_CASES],
)
def test_evaluate(
    overrides: dict[str, Any], silence: float, alive: Any, breached: bool, expected: str
) -> None:
    state = _state(**overrides)
    assert state.evaluate(100.0 + silence, RULES, breached=breached, alive=alive) == (
        expected
    )


# ---------------------------------------------------------------------------
# B2.2 same-host PID check
# ---------------------------------------------------------------------------


def _own_start_ns() -> int:
    return int(psutil.Process().create_time() * 1e9)


class TestProcessAlive:
    def test_this_process_is_alive(self) -> None:
        assert process_alive(os.getpid(), _own_start_ns())

    def test_a_reused_pid_is_not_the_beaconing_process(self) -> None:
        assert not process_alive(os.getpid(), _own_start_ns() - 3_600_000_000_000)

    def test_an_exited_child_is_dead(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        started = int(psutil.Process(child.pid).create_time() * 1e9)
        child.wait()
        assert not process_alive(child.pid, started)

    def test_an_unreaped_child_is_dead(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        started = int(psutil.Process(child.pid).create_time() * 1e9)
        deadline = time.monotonic() + 5
        while psutil.Process(child.pid).status() != psutil.STATUS_ZOMBIE:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        try:
            assert not process_alive(child.pid, started)
        finally:
            child.wait()

    def test_silent_with_own_pid_and_dead_with_an_exited_one(self) -> None:
        rules = HealthRules(
            hung_after_sec=5.0, silent_after_beacons=3, local_host="box"
        )
        mine = _state(pid=os.getpid(), started_at_ns=_own_start_ns())
        assert mine.evaluate(100.0 + LIMIT + 1, rules) == "SILENT"
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        started = int(psutil.Process(child.pid).create_time() * 1e9)
        child.wait()
        theirs = _state(pid=child.pid, started_at_ns=started)
        assert theirs.evaluate(100.0 + LIMIT + 1, rules) == "DEAD"


# ---------------------------------------------------------------------------
# B2.4 exchange status
# ---------------------------------------------------------------------------


def _rec(process: str, state: str, instance: str | None = None) -> dict[str, Any]:
    record = missing_health(process, instance)
    record["state"] = state
    return record


ENGINE_OK = _rec("pm-engine", "HEALTHY")

STATUS_CASES: list[tuple[str, list[dict[str, Any]], Any, str]] = [
    ("all healthy", [ENGINE_OK, _rec("pm-stats", "HEALTHY")], None, "OPERATIONAL"),
    ("no engine at all", [_rec("pm-stats", "HEALTHY")], None, "DOWN"),
    ("engine hung", [_rec("pm-engine", "HUNG")], None, "DOWN"),
    ("engine silent", [_rec("pm-engine", "SILENT")], None, "DOWN"),
    ("engine dead", [_rec("pm-engine", "DEAD")], None, "DOWN"),
    ("engine missing", [_rec("pm-engine", "MISSING")], {("pm-engine", None)}, "DOWN"),
    ("engine stopped", [_rec("pm-engine", "STOPPED")], None, "DOWN"),
    ("engine degraded", [_rec("pm-engine", "DEGRADED")], None, "DEGRADED"),
    ("stats degraded", [ENGINE_OK, _rec("pm-stats", "DEGRADED")], None, "DEGRADED"),
    ("stats dead", [ENGINE_OK, _rec("pm-stats", "DEAD")], None, "IMPAIRED"),
    ("impaired beats degraded",
     [_rec("pm-engine", "DEGRADED"), _rec("pm-stats", "HUNG")], None, "IMPAIRED"),
    ("stopped by hand", [ENGINE_OK, _rec("pm-stats", "STOPPED")], None, "OPERATIONAL"),
    ("stopped but expected", [ENGINE_OK, _rec("pm-stats", "STOPPED")],
     {("pm-engine", None), ("pm-stats", None)}, "IMPAIRED"),
    ("dead but not expected", [ENGINE_OK, _rec("pm-index", "DEAD")],
     {("pm-engine", None)}, "OPERATIONAL"),
    ("missing api instance", [ENGINE_OK, _rec("pm-api-gwy", "MISSING", "desk")],
     {("pm-engine", None), ("pm-api-gwy", "desk")}, "IMPAIRED"),
    ("bots never count",
     [ENGINE_OK, _rec("pm-mm-bot", "DEAD"), _rec("pm-ai-swarm", "DEGRADED")],
     None, "OPERATIONAL"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("processes", "expected", "status"),
    [case[1:] for case in STATUS_CASES],
    ids=[case[0] for case in STATUS_CASES],
)
def test_exchange_status(
    processes: list[dict[str, Any]], expected: Any, status: str
) -> None:
    assert exchange_status(processes, expected) == status


# ---------------------------------------------------------------------------
# collector: roster, transitions, forgetting
# ---------------------------------------------------------------------------


class _FixedRoster:
    def __init__(self, expected: set[tuple[str, str | None]] | None) -> None:
        self.profile = None if expected is None else "test"
        self.expected = None if expected is None else frozenset(expected)

    def refresh(self) -> bool:
        return False


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


def _monitor(clock: _Clock, roster: Any = None) -> Monitor:
    pull, pub = free_ports(2)
    return Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        ZoneInfo("Europe/Stockholm"),
        clock=clock,
        roster=_FixedRoster(None) if roster is None else roster,
        local_host="box",
        host_sampler=QuietHost(),
        alive=_gone,
    )


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str, str]]:
    seen: list[tuple[str, str, str, str]] = []
    original = Monitor.publish_event

    def record(
        self: Monitor, kind: str, severity: str, subject: str, detail: str
    ) -> bool:
        seen.append((kind, severity, subject, detail))
        return original(self, kind, severity, subject, detail)

    monkeypatch.setattr(Monitor, "publish_event", record)
    return seen


@pytest.fixture
def mon(clock: _Clock) -> Iterator[Monitor]:
    m = _monitor(clock)
    try:
        yield m
    finally:
        m.close()


def _states(m: Monitor) -> list[tuple[str, str]]:
    return [(p["key"], p["state"]) for p in m.snapshot()["processes"]]


class TestTransitions:
    def test_first_seen_healthy_is_not_news(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        mon.receive(_beacon_frames(), clock.t)
        assert _states(mon) == [("pm-engine@box", "HEALTHY")]
        assert events == []

    def test_a_change_is_one_event_until_the_next_change(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        mon.receive(_beacon_frames(seq=1, loop_age_ms=6000.0), clock.t)
        mon.snapshot()
        mon.receive(_beacon_frames(seq=2, loop_age_ms=7000.0), clock.t)
        mon.snapshot()
        for seq in range(3, 4 + CLEAR_AFTER):
            mon.receive(_beacon_frames(seq=seq), clock.t)
            mon.snapshot()
        # The loop_age_ms warning (§9.6) clears after CLEAR_AFTER OK seconds, so the
        # way back passes through DEGRADED.
        assert [e for e in events if e[0] == "PROCESS_STATUS"] == [
            (
                "PROCESS_STATUS",
                "CRIT",
                "pm-engine@box",
                "HEALTHY -> HUNG: loop_age_ms 6000 > 5000",
            ),
            (
                "PROCESS_STATUS",
                "WARN",
                "pm-engine@box",
                "HUNG -> DEGRADED: loop_age_ms WARN clearing (5)",
            ),
            ("PROCESS_STATUS", "INFO", "pm-engine@box", "DEGRADED -> HEALTHY"),
        ]

    def test_silence_then_death(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        clock.t += LIMIT + 1
        assert _states(mon) == [("pm-engine@box", "DEAD")]  # alive=_gone, same host
        assert events[-1] == (
            "PROCESS_STATUS",
            "CRIT",
            "pm-engine@box",
            "HEALTHY -> DEAD: no beacon for 7.0 s, process gone",
        )

    def test_silent_names_the_silence(self, clock: _Clock, events: list[Any]) -> None:
        m = _monitor(clock)
        m._alive = _alive
        try:
            m.receive(_beacon_frames(), clock.t)
            m.snapshot()
            clock.t += LIMIT + 1
            m.snapshot()
            m.receive(_beacon_frames(host="far", seq=0), clock.t)
            m.snapshot()
            clock.t += LIMIT + 1
            m.snapshot()
        finally:
            m.close()
        assert [e[2:] for e in events if e[0] == "PROCESS_STATUS"] == [
            ("pm-engine@box", "HEALTHY -> SILENT: no beacon for 7.0 s, process runs"),
            ("pm-engine@far", "HEALTHY -> SILENT: no beacon for 7.0 s"),
        ]

    def test_a_breach_is_named_in_the_transition(
        self,
        mon: Monitor,
        clock: _Clock,
        events: list[Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO, logger="edumatcher.monitor.collector")
        p99 = {
            "name": "engine.handle_us_p99",
            "kind": "GAUGE",
            "label": "",
            "value": 25000.0,
        }
        mon.receive(_beacon_frames(metrics=[p99]), clock.t)
        mon.snapshot()
        detail = "first seen DEGRADED: engine_handle_p99_us CRIT 25000 > 20000"
        assert ("PROCESS_STATUS", "WARN", "pm-engine@box", detail) in events
        assert f"process pm-engine@box: {detail}" in caplog.messages

    def test_a_late_loop_is_a_breach_with_its_own_event(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        for seq in range(1, RAISE_AFTER + 1):
            mon.receive(_beacon_frames(seq=seq, loop_lag_ms=1500.0), clock.t)
            mon.snapshot()
            clock.t += 1.0
        snap = mon.snapshot()
        assert [(b["rule"], b["subject"], b["level"]) for b in snap["thresholds"]] == [
            ("loop_lag_ms", "pm-engine@box", "WARN")
        ]
        assert [p["state"] for p in snap["processes"]] == ["DEGRADED"]
        assert events == [
            ("THRESHOLD", "WARN", "pm-engine@box", "loop_lag_ms WARN 1500 > 1000"),
            (
                "PROCESS_STATUS",
                "WARN",
                "pm-engine@box",
                "HEALTHY -> DEGRADED: loop_lag_ms WARN 1500 > 1000",
            ),
        ]

    @pytest.mark.parametrize("figure", ["loop_age_ms", "loop_lag_ms"])
    def test_one_late_beacon_is_not_degraded(
        self, mon: Monitor, clock: _Clock, events: list[Any], figure: str
    ) -> None:
        """One beacon 1.3 s late, judged twice (2 s interval), then on time:
        not a breach (C5, WP-MHD04)."""
        for second in range(40):
            if second % 2 == 0:
                late = {figure: 1336.6} if second == 2 else {}
                mon.receive(_beacon_frames(seq=second, **late), clock.t)
            snap = mon.snapshot()
            assert [p["state"] for p in snap["processes"]] == ["HEALTHY"]
            clock.t += 1.0
        assert events == []

    @pytest.mark.parametrize("figure", ["loop_age_ms", "loop_lag_ms"])
    def test_a_loop_late_for_five_seconds_is_a_breach(
        self, mon: Monitor, clock: _Clock, events: list[Any], figure: str
    ) -> None:
        for second in range(RAISE_AFTER + 1):
            if second % 2 == 0:
                mon.receive(_beacon_frames(seq=second, **{figure: 1200.0}), clock.t)
            mon.snapshot()
            clock.t += 1.0
        assert events == [
            ("THRESHOLD", "WARN", "pm-engine@box", f"{figure} WARN 1200 > 1000"),
            (
                "PROCESS_STATUS",
                "WARN",
                "pm-engine@box",
                f"HEALTHY -> DEGRADED: {figure} WARN 1200 > 1000",
            ),
        ]

    def test_one_slow_minute_of_the_engine_is_not_degraded(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        """Four slow messages hold the engine's p99 at 5 764 us for its 60 s
        horizon (C3): no breach, no transition (WP-MHD03)."""
        for second in range(120):
            p99 = 5764.4 if second < 60 else 1970.0
            if second % 2 == 0:
                metric = {
                    "name": "engine.handle_us_p99",
                    "kind": "GAUGE",
                    "label": "",
                    "value": p99,
                }
                mon.receive(_beacon_frames(seq=second, metrics=[metric]), clock.t)
            snap = mon.snapshot()
            assert [p["state"] for p in snap["processes"]] == ["HEALTHY"]
            clock.t += 1.0
        assert events == []

    def test_host_contention_is_named_beside_a_process_breach(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        """Q3: the host breach is context, appended; the process stays DEGRADED."""
        mon.host_sampler = BusyHost(cpu_pct=97.1)
        p99 = {
            "name": "engine.handle_us_p99",
            "kind": "GAUGE",
            "label": "",
            "value": 25000.0,
        }
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        mon.receive(_beacon_frames(seq=1, metrics=[p99]), clock.t)
        mon.snapshot()
        assert [e[3] for e in events if e[0] == "PROCESS_STATUS"] == [
            "HEALTHY -> DEGRADED: engine_handle_p99_us CRIT 25000 > 20000; "
            "host: host_cpu_pct CRIT 97.1 > 95"
        ]

    def test_no_host_breach_no_host_part(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        p99 = {
            "name": "engine.handle_us_p99",
            "kind": "GAUGE",
            "label": "",
            "value": 25000.0,
        }
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        mon.receive(_beacon_frames(seq=1, metrics=[p99]), clock.t)
        mon.snapshot()
        assert [e[3] for e in events if e[0] == "PROCESS_STATUS"] == [
            "HEALTHY -> DEGRADED: engine_handle_p99_us CRIT 25000 > 20000"
        ]

    def test_a_credited_silence_is_not_a_late_loop(
        self, mon: Monitor, clock: _Clock
    ) -> None:
        mon.receive(_beacon_frames(), clock.t)
        mon.snapshot()
        clock.t += 20.0  # stood still (SIGSTOP): reported DEAD/SILENT already
        mon.receive(_beacon_frames(seq=1, loop_lag_ms=20_010.0), clock.t)
        snap = mon.snapshot()
        assert snap["thresholds"] == []
        assert [p["state"] for p in snap["processes"]] == ["HEALTHY"]

    def test_first_seen_in_trouble_is_news(
        self, mon: Monitor, clock: _Clock, events: list[Any]
    ) -> None:
        mon.receive(_beacon_frames(final=True), clock.t)
        mon.snapshot()
        assert events == [
            ("PROCESS_STATUS", "INFO", "pm-engine@box", "first seen STOPPED")
        ]

    def test_the_snapshot_carries_the_exchange_status(
        self, mon: Monitor, clock: _Clock
    ) -> None:
        mon.receive(_beacon_frames(loop_age_ms=9000.0), clock.t)
        snap = HealthSnapshot.from_dict(mon.snapshot())
        snap.validate()
        assert snap.exchange.status == "DOWN"


class TestRosterInTheCollector:
    def test_missing_waits_one_silence_period_then_is_news(
        self, clock: _Clock, events: list[Any]
    ) -> None:
        roster = _FixedRoster({("pm-engine", None), ("pm-stats", None)})
        m = _monitor(clock, roster)
        try:
            m.receive(_beacon_frames(), clock.t)
            assert _states(m) == [("pm-engine@box", "HEALTHY")]
            clock.t += LIMIT + 0.1  # 3 x the configured 2 s interval
            m.receive(_beacon_frames(seq=1), clock.t)
            assert _states(m) == [("pm-engine@box", "HEALTHY"), ("pm-stats", "MISSING")]
            assert events == [
                ("PROCESS_STATUS", "CRIT", "pm-stats", "first seen MISSING")
            ]
            snap = HealthSnapshot.from_dict(m.snapshot())
            snap.validate()
            assert snap.exchange.status == "IMPAIRED"

            # it starts: a new key with a host, and the change is reported
            m.receive(_beacon_frames(process="pm-stats", seq=2), clock.t)
            m.receive(_beacon_frames(seq=2), clock.t)
            assert _states(m) == [
                ("pm-engine@box", "HEALTHY"),
                ("pm-stats@box", "HEALTHY"),
            ]
            assert events[-1] == (
                "PROCESS_STATUS",
                "INFO",
                "pm-stats@box",
                "MISSING -> HEALTHY",
            )
        finally:
            m.close()

    def test_without_a_profile_nothing_is_missing(
        self, mon: Monitor, clock: _Clock
    ) -> None:
        clock.t += 3600
        assert _states(mon) == []

    def test_a_long_silent_source_nobody_expects_is_forgotten(
        self, clock: _Clock
    ) -> None:
        m = _monitor(clock, _FixedRoster({("pm-engine", None)}))
        try:
            m.receive(_beacon_frames(), clock.t)
            m.receive(_beacon_frames(process="pm-index"), clock.t)
            clock.t += FORGET_AFTER_SEC + 1
            assert _states(m) == [("pm-engine@box", "DEAD")]  # expected: kept
            assert m.sources_forgotten == 1
        finally:
            m.close()


# ---------------------------------------------------------------------------
# Done when: SIGKILL, SIGSTOP and a blocked loop of a real child process
# ---------------------------------------------------------------------------

_CHILD = textwrap.dedent("""
    import signal, sys, time
    from edumatcher.health import HealthReporter

    reporter = HealthReporter(
        "pm-child", sys.argv[2], host="127.0.0.1", port=int(sys.argv[1]),
        interval_sec=0.2,
    )
    reporter.start()
    blocked = False

    def block(*_):
        global blocked
        blocked = True

    signal.signal(signal.SIGUSR1, block)
    while True:
        if blocked:
            time.sleep(3600)  # the main loop hangs; the sampler thread runs on
        reporter.tick()
        time.sleep(0.02)
    """)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_kill_stop_and_block_read_dead_silent_hung() -> None:
    pull, pub = free_ports(2)
    m = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub, hung_after_sec=0.5),
        ZoneInfo("Europe/Stockholm"),
        roster=_FixedRoster(None),
        host_sampler=QuietHost(),
    )
    children = {
        name: subprocess.Popen([sys.executable, "-c", _CHILD, str(pull), name])
        for name in ("killed", "stopped", "blocked")
    }

    def states() -> dict[str, str]:
        m.drain()
        return {
            p["instance"]: p["state"]
            for p in m.processes(time.monotonic())
            if p["process"] == "pm-child"
        }

    def wait_for(want: dict[str, str], within: float = 10.0) -> dict[str, str]:
        deadline = time.monotonic() + within
        seen = states()
        while seen != want and time.monotonic() < deadline:
            m._pull.poll(100)
            seen = states()
        return seen

    try:
        healthy = {name: "HEALTHY" for name in children}
        assert wait_for(healthy) == healthy

        children["killed"].send_signal(signal.SIGKILL)
        children["killed"].wait()
        children["stopped"].send_signal(signal.SIGSTOP)
        children["blocked"].send_signal(signal.SIGUSR1)

        want = {"killed": "DEAD", "stopped": "SILENT", "blocked": "HUNG"}
        assert wait_for(want) == want
    finally:
        for child in children.values():
            child.kill()
            child.wait()
        m.close()
