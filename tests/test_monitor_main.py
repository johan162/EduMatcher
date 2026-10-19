"""``pm-monitor``: entry point, sockets and the 1 Hz snapshot (WP-B1)."""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import zmq

import edumatcher.config as C
from edumatcher.health import HealthReporter
from edumatcher.log_srv.config import LogClientConfig, LogServerConfig
from edumatcher.models.generated.health import (
    TOPIC_HEALTH_SNAPSHOT,
    HealthSnapshot,
    make_health_beacon,
    parse_health_snapshot,
)
from edumatcher.monitor import main as monitor_main
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.state import Ingest
from edumatcher.monitor.timefmt import iso_utc
from tests.conftest import free_ports

STOCKHOLM = ZoneInfo("Europe/Stockholm")


class QuietHost:
    """A host sampler for an idle machine, so a busy CI box cannot trip a
    host threshold and change what a test sees."""

    def sample(self) -> dict[str, Any]:
        return {
            "cpu_pct": 1.0,
            "cpu_per_core": [1.0],
            "load1": 0.1,
            "load5": 0.1,
            "load15": 0.1,
            "mem_total_bytes": 1000,
            "mem_used_bytes": 100,
            "mem_available_bytes": 900,
            "swap_used_bytes": 0,
            "disk_free_bytes": 900,
            "disk_total_bytes": 1000,
            "files": [],
        }


def _config(**overrides: Any) -> MonitorConfig:
    pull, pub = free_ports(2)
    return MonitorConfig(pull_port=pull, pub_port=pub, **overrides)


def _beacon_frames(**overrides: Any) -> list[bytes]:
    fields: dict[str, Any] = {
        "process": "pm-engine",
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
    return make_health_beacon(**fields)


@pytest.fixture
def monitor() -> Iterator[Monitor]:
    mon = Monitor(_config(), STOCKHOLM, host_sampler=QuietHost())
    try:
        yield mon
    finally:
        mon.close()


class _Running:
    """A Monitor's loop on a thread, with a SUB on its PUB."""

    def __init__(self, mon: Monitor) -> None:
        self.mon = mon
        ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        self.sub: zmq.Socket[bytes] = ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.setsockopt(zmq.SUBSCRIBE, TOPIC_HEALTH_SNAPSHOT.encode())
        self.sub.connect(mon.config.pub_connect_addr)
        self.push: zmq.Socket[bytes] = ctx.socket(zmq.PUSH)
        self.push.setsockopt(zmq.LINGER, 0)
        self.push.connect(mon.config.pull_connect_addr)
        self.thread = threading.Thread(target=mon.run, daemon=True)
        self.thread.start()

    def next_snapshot(self, deadline: float) -> HealthSnapshot | None:
        remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
        if not self.sub.poll(remaining_ms):
            return None
        return parse_health_snapshot(self.sub.recv_multipart())

    def wait_for(self, process: str, within_sec: float) -> HealthSnapshot | None:
        deadline = time.monotonic() + within_sec
        while time.monotonic() < deadline:
            snap = self.next_snapshot(deadline)
            if snap is not None and any(p.process == process for p in snap.processes):
                return snap
        return None

    def close(self) -> None:
        self.mon.stop()
        self.thread.join(timeout=2)
        self.sub.close()
        self.push.close()


@pytest.fixture
def running(monitor: Monitor) -> Iterator[_Running]:
    r = _Running(monitor)
    try:
        yield r
    finally:
        r.close()


# ---------------------------------------------------------------------------
# B1.1 entry point
# ---------------------------------------------------------------------------


def _compiled(monitor_cfg: MonitorConfig, tz: str = "Europe/Stockholm") -> Any:
    return SimpleNamespace(
        monitor=monitor_cfg,
        engine=SimpleNamespace(
            locale=SimpleNamespace(session_timezone=tz), fix_gateways={}
        ),
        log_client=LogClientConfig(),
        log_server=LogServerConfig(),
    )


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Point main() at a fake compiled artifact and a private metrics.db;
    returns a setter."""
    monkeypatch.setattr(
        "edumatcher.config_artifact.report_deployment", lambda log: None
    )
    monkeypatch.setattr(monitor_main, "METRICS_DB_FILE", tmp_path / "metrics.db")

    def deploy(compiled: Any) -> None:
        monkeypatch.setattr(
            "edumatcher.config_artifact.load_compiled_config", lambda: compiled
        )

    return deploy


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-monitor", "--log-target", "stdout", *argv])
    monitor_main.main()


class TestEntryPoint:
    def test_version(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["pm-monitor", "--version"])
        with pytest.raises(SystemExit) as exc:
            monitor_main.main()
        assert exc.value.code == 0
        assert capsys.readouterr().out.startswith("pm-monitor ")

    def test_disabled_refuses_to_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        deployed: Any,
    ) -> None:
        deployed(_compiled(_config(enabled=False)))
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch)
        assert exc.value.code == 2
        assert (
            "monitoring is disabled (monitor.enabled: false" in capsys.readouterr().err
        )

    def test_session_timezone_comes_from_the_engine_locale(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        deployed: Any,
    ) -> None:
        deployed(_compiled(_config(), tz="America/New_York"))
        seen: dict[str, Any] = {}

        def fake_run(self: Monitor) -> None:
            seen["tz"] = self.session_tz

        monkeypatch.setattr(Monitor, "run", fake_run)
        monkeypatch.setattr("signal.signal", lambda *a: None)
        caplog.set_level(logging.INFO, logger="edumatcher.monitor.main")
        _run_main(monkeypatch, "-v")
        assert str(seen["tz"]) == "America/New_York"
        assert any(
            r.levelno == logging.INFO
            and "session timezone America/New_York" in r.getMessage()
            for r in caplog.records
        )

    def test_an_unknown_timezone_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, deployed: Any
    ) -> None:
        deployed(_compiled(_config(), tz="Mars/Olympus_Mons"))
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch)
        assert exc.value.code == 2

    def test_a_port_in_use_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, deployed: Any, monitor: Monitor
    ) -> None:
        deployed(_compiled(monitor.config))  # same ports, already bound
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch)
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# B1.2 sockets
# ---------------------------------------------------------------------------


class TestBind:
    def test_binds_the_authored_address(self, monitor: Monitor) -> None:
        cfg = monitor.config
        assert monitor.pull_endpoint == f"tcp://127.0.0.1:{cfg.pull_port}"
        assert monitor.pub_endpoint == f"tcp://127.0.0.1:{cfg.pub_port}"

    def test_the_bind_host_env_overrides_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(C, "EDUMATCHER_GATEWAY_BIND_HOST", "0.0.0.0")
        mon = Monitor(_config(), STOCKHOLM, host_sampler=QuietHost())
        try:
            assert mon.pull_endpoint.startswith("tcp://0.0.0.0:")
            assert mon.pub_endpoint.startswith("tcp://0.0.0.0:")
        finally:
            mon.close()

    def test_a_failed_bind_releases_the_first_socket(self, monitor: Monitor) -> None:
        cfg = _config()
        clash = MonitorConfig(pull_port=cfg.pull_port, pub_port=monitor.config.pub_port)
        with pytest.raises(zmq.ZMQError):
            Monitor(clash, STOCKHOLM, host_sampler=QuietHost())
        # the PULL port that did bind is free again
        Monitor(cfg, STOCKHOLM, host_sampler=QuietHost()).close()


# ---------------------------------------------------------------------------
# beacons in
# ---------------------------------------------------------------------------


class TestReceive:
    def test_a_valid_beacon_is_tracked(self, monitor: Monitor) -> None:
        assert monitor.receive(_beacon_frames(), 1.0) is Ingest.NEW
        assert len(monitor.table) == 1
        assert monitor.beacons_in == 1

    def test_garbage_is_counted_not_raised(self, monitor: Monitor) -> None:
        assert monitor.receive([b"health.beacon", b"{not json"], 1.0) is None
        assert monitor.receive([b"health.beacon", b'{"process": ""}'], 1.0) is None
        assert monitor.receive([b"only-one-frame"], 1.0) is None
        assert monitor.beacons_invalid == 3
        assert len(monitor.table) == 0

    def test_another_topic_is_invalid(self, monitor: Monitor) -> None:
        frames = _beacon_frames()
        assert monitor.receive([b"health.snapshot", frames[1]], 1.0) is None
        assert monitor.beacons_invalid == 1

    def test_stale_restart_and_rejects_are_counted(self, monitor: Monitor) -> None:
        monitor.receive(_beacon_frames(seq=3), 1.0)
        monitor.receive(_beacon_frames(seq=2), 1.0)
        monitor.receive(
            _beacon_frames(boot_id="b" * 16, started_at_ns=2_000_000_000_000), 2.0
        )
        monitor.table.max_sources = 1
        monitor.receive(_beacon_frames(process="pm-stats"), 3.0)
        assert (
            monitor.beacons_stale,
            monitor.restarts_seen,
            monitor.sources_rejected,
        ) == (
            1,
            1,
            1,
        )

    def test_drain_reads_a_whole_burst(self, monitor: Monitor) -> None:
        push: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PUSH)
        push.setsockopt(zmq.LINGER, 0)
        push.connect(monitor.config.pull_connect_addr)
        try:
            for seq in range(10):
                push.send_multipart(_beacon_frames(seq=seq, loop_age_ms=float(seq)))
            deadline = time.monotonic() + 2
            while monitor.beacons_in < 10 and time.monotonic() < deadline:
                monitor._pull.poll(100)
                monitor.drain()
        finally:
            push.close()
        state = monitor.table.get("pm-engine", None, "box")
        assert state is not None
        assert state.beacon.loop_age_ms == 9.0


# ---------------------------------------------------------------------------
# B1.4 snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_an_empty_snapshot_validates(self, monitor: Monitor) -> None:
        HealthSnapshot.from_dict(monitor.snapshot()).validate()
        assert monitor.publish_snapshot()
        assert monitor.snapshots_out == 1
        assert monitor.snapshot_bytes > 0

    def test_lists_judged_processes(self, monitor: Monitor) -> None:
        now = time.monotonic()
        monitor.receive(_beacon_frames(), now)
        monitor.receive(_beacon_frames(process="pm-stats", final=True), now)
        snap = HealthSnapshot.from_dict(monitor.snapshot())
        snap.validate()
        assert [(p.key, p.state) for p in snap.processes] == [
            ("pm-engine@box", "HEALTHY"),
            ("pm-stats@box", "STOPPED"),
        ]
        assert snap.exchange.status == "OPERATIONAL"

    def test_trading_date_and_ts_follow_the_clocks(self) -> None:
        # 23:30 UTC on 2026-10-19 is already the 20th in Stockholm (CEST)
        wall = datetime(2026, 10, 19, 23, 30, tzinfo=timezone.utc).timestamp()
        mon = Monitor(
            _config(), STOCKHOLM, wall_clock=lambda: wall, host_sampler=QuietHost()
        )
        try:
            payload = mon.snapshot()
        finally:
            mon.close()
        assert payload["ts"] == "2026-10-19T23:30:00.000Z"
        assert payload["exchange"]["trading_date"] == "2026-10-20"
        assert payload["exchange"]["session_timezone"] == "Europe/Stockholm"

    def test_seq_counts_published_snapshots(self, monitor: Monitor) -> None:
        monitor.publish_snapshot()
        monitor.publish_snapshot()
        assert monitor.snapshot()["seq"] == 2

    def test_a_subscriber_sees_a_beaconing_process_within_1_5_s(
        self, running: _Running
    ) -> None:
        time.sleep(0.2)  # let the SUB join before the deadline starts
        running.push.send_multipart(_beacon_frames())
        snap = running.wait_for("pm-engine", within_sec=1.5)
        assert snap is not None
        (proc,) = snap.processes
        assert proc.key == "pm-engine@box"
        assert proc.pid == 4242

    def test_snapshots_are_once_a_second(self, running: _Running) -> None:
        first = running.next_snapshot(time.monotonic() + 2)
        assert first is not None
        start = time.monotonic()
        second = running.next_snapshot(start + 2)
        assert second is not None
        assert second.seq == first.seq + 1
        assert 0.7 < time.monotonic() - start < 1.3

    def test_iso_utc(self) -> None:
        assert iso_utc(0.5) == "1970-01-01T00:00:00.500Z"


# ---------------------------------------------------------------------------
# B1.5 pm-monitor beacons to itself
# ---------------------------------------------------------------------------


@pytest.mark.real_health_reporter
def test_pm_monitor_lists_itself(monitor: Monitor) -> None:
    cfg = monitor.config
    reporter = HealthReporter(
        "pm-monitor", host=cfg.host, port=cfg.pull_port, interval_sec=0.2
    )
    reporter.start()
    monitor.attach_reporter(reporter)
    running = _Running(monitor)
    try:
        snap = running.wait_for("pm-monitor", within_sec=3)
    finally:
        running.close()
    assert snap is not None
    (me,) = [p for p in snap.processes if p.process == "pm-monitor"]
    assert me.state == "HEALTHY"
    names = {m.name for m in me.metrics}
    assert {"monitor.beacons_in", "monitor.snapshot_bytes", "monitor.sources"} <= names


@pytest.mark.real_health_reporter
def test_main_wires_the_reporter_to_its_own_pull(
    monkeypatch: pytest.MonkeyPatch, deployed: Any
) -> None:
    cfg = _config(beacon_interval_sec=0.2)
    deployed(_compiled(cfg))
    monkeypatch.setattr(
        "edumatcher.monitor.config.load_default_monitor_config", lambda: cfg
    )
    seen: list[str] = []

    def fake_run(self: Monitor) -> None:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not seen:
            self._pull.poll(100)
            self.drain()
            seen.extend(s.beacon.process for s in self.table.states())

    monkeypatch.setattr(Monitor, "run", fake_run)
    monkeypatch.setattr("signal.signal", lambda *a: None)
    _run_main(monkeypatch)
    assert seen == ["pm-monitor"]
