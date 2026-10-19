"""pm-monitor-cli (WP-B6)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from edumatcher.monitor import cli
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.store import MetricsStore
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost, _beacon_frames, _Running

TZ = ZoneInfo("Europe/Stockholm")


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc:
        cli.main(list(argv))
    out, err = capsys.readouterr()
    code = exc.value.code
    return (code if isinstance(code, int) else 0), out, err


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "metrics.db"


@pytest.fixture
def mon(db: Path) -> Iterator[Monitor]:
    pull, pub = free_ports(2)
    m = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        TZ,
        host_sampler=QuietHost(),
        local_host="box",
        store=MetricsStore(db, "Europe/Stockholm", raw_hours=6, minute_days=7),
    )
    try:
        yield m
    finally:
        m.close()


def _args(mon: Monitor, db: Path, *rest: str) -> list[str]:
    return [
        "--host",
        "127.0.0.1",
        "--port",
        str(mon.config.pub_port),
        "--db",
        str(db),
        *rest,
    ]


@pytest.fixture
def running(mon: Monitor) -> Iterator[_Running]:
    r = _Running(mon)
    try:
        yield r
    finally:
        r.close()


def _beacon(running: _Running, **overrides: Any) -> None:
    running.push.send_multipart(_beacon_frames(**overrides))
    assert running.wait_for(overrides.get("process", "pm-engine"), within_sec=3)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_healthy(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code, out, _ = _run(capsys, *_args(mon, db, "health", "-v"))
        assert code == 0
        assert "pm-monitor snapshot: OK" in out and "health: OK" in out
        assert "endpoint: tcp://127.0.0.1:" in out

    def test_quiet(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code, out, _ = _run(capsys, *_args(mon, db, "health", "-q"))
        assert (code, out) == (0, "")

    def test_unreachable(self, db: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (port,) = free_ports(1)
        argv = ["--port", str(port), "--timeout", "0.3", "--db", str(db)]
        code, out, _ = _run(capsys, *argv, "health")
        assert code == 1 and "health: FAIL" in out
        code, out, _ = _run(capsys, *argv, "health", "-q")
        assert (code, out) == (-1, "")

    def test_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        db: Path,
    ) -> None:
        monkeypatch.setattr(
            cli, "load_default_monitor_config", lambda: MonitorConfig(enabled=False)
        )
        code, out, _ = _run(capsys, "--db", str(db), "--format", "json", "health")
        report = json.loads(out)
        assert code == 1 and not report["healthy"]
        assert "monitoring is disabled" in report["detail"]


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatus:
    def test_operational(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _beacon(running)
        code, out, _ = _run(capsys, *_args(mon, db, "status"))
        assert code == 0
        assert out.startswith("exchange OPERATIONAL")
        assert any(
            line.startswith("pm-engine@box") and "HEALTHY" in line
            for line in out.splitlines()
        )
        assert "breaches: none" in out

    def test_json_is_the_snapshot(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _beacon(running)
        code, out, _ = _run(capsys, *_args(mon, db, "--format", "json", "status"))
        snap = json.loads(out)
        assert code == 0
        assert snap["exchange"]["status"] == "OPERATIONAL"
        assert [p["key"] for p in snap["processes"]] == ["pm-engine@box"]

    def test_a_hung_engine_is_exit_4_and_shows_the_breach(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _beacon(running, loop_age_ms=9000.0)
        code, out, _ = _run(capsys, *_args(mon, db, "status"))
        assert code == cli.EXIT_STATUS["DOWN"] == 4
        assert "exchange DOWN" in out and "HUNG" in out
        assert "loop_age_ms" in out  # the warning breach on the engine

    def test_no_engine_at_all_is_down(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code, out, _ = _run(capsys, *_args(mon, db, "status"))
        assert code == 4 and "(no processes)" in out

    def test_unreachable_is_exit_5(
        self, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (port,) = free_ports(1)
        code, _, err = _run(capsys, "--port", str(port), "--timeout", "0.3", "status")
        assert code == cli.EXIT_UNREACHABLE == 5
        assert "no snapshot from pm-monitor" in err


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def _store_events(mon: Monitor) -> None:
    mon.publish_event("SESSION", "INFO", "session", "CLOSED -> PRE_OPEN")
    mon.publish_event("DISCONNECT", "WARN", "TRADER01", "heartbeat_timeout")
    mon.publish_event("HALT", "WARN", "AAPL", "L1 CB")
    mon.publish_event("DISCONNECT", "INFO", "TRADER02", "logout")


class TestEvents:
    def test_the_newest_n_oldest_first(
        self, mon: Monitor, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _store_events(mon)
        code, out, _ = _run(capsys, *_args(mon, db, "events", "--limit", "2"))
        lines = out.splitlines()
        assert code == 0
        assert lines[0].split()[:4] == ["SEQ", "TS", "SEV", "KIND"]
        assert [line.split()[0] for line in lines[1:]] == ["3", "4"]

    @pytest.mark.parametrize(
        ("filters", "seqs"),
        [
            (["--kind", "disconnect"], [2, 4]),
            (["--subject", "TRADER0"], [2, 4]),
            (["--kind", "DISCONNECT", "--subject", "TRADER02"], [4]),
            (["--since", "2000-01-01T00:00:00.000Z"], [1, 2, 3, 4]),
            (["--since", "2999-01-01T00:00:00.000Z"], []),
        ],
    )
    def test_filters(
        self,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
        filters: list[str],
        seqs: list[int],
    ) -> None:
        _store_events(mon)
        code, out, _ = _run(
            capsys, *_args(mon, db, "--format", "json", "events", *filters)
        )
        assert code == 0
        assert [json.loads(line)["seq"] for line in out.splitlines()] == seqs

    def test_no_database(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _run(capsys, "--db", str(tmp_path / "none.db"), "events")
        assert code == 1 and "does not exist" in err

    def test_count_needs_follow(
        self, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, err = _run(capsys, "--db", str(db), "events", "--count", "1")
        assert code == 2 and "--count needs --follow" in err

    def test_an_unknown_kind_is_a_usage_error(
        self, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, _ = _run(capsys, "--db", str(db), "events", "--kind", "NOPE")
        assert code == 2

    def test_it_never_writes(
        self, mon: Monitor, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _store_events(mon)
        before = db.stat().st_mtime_ns
        _run(capsys, *_args(mon, db, "events"))
        assert db.stat().st_mtime_ns == before

    def test_follow_prints_live_events_after_the_history(
        self, mon: Monitor, db: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _store_events(mon)
        result: dict[str, Any] = {}

        def follow() -> None:
            try:
                cli.main(
                    _args(
                        mon,
                        db,
                        "--format",
                        "json",
                        "events",
                        "--follow",
                        "--count",
                        "1",
                    )
                )
            except SystemExit as exc:
                result["code"] = exc.code

        thread = threading.Thread(target=follow, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        while thread.is_alive() and time.monotonic() < deadline:
            # live events until the follower has joined (slow joiner)
            mon.publish_event("RESUME", "INFO", "AAPL", "timer")
            time.sleep(0.1)
        thread.join(timeout=2)
        out = capsys.readouterr().out
        rows = [json.loads(line) for line in out.splitlines()]
        assert result["code"] == 0
        seqs = [r["seq"] for r in rows]
        assert seqs[:4] == [1, 2, 3, 4]  # the stored history
        # Events stored before the follower read the history are part of it;
        # live ones follow without a duplicate or a gap (seq dedupe).
        assert seqs == list(range(1, len(seqs) + 1))
        assert len(seqs) >= 5 and all(r["kind"] == "RESUME" for r in rows[4:])


def test_follow_fills_a_gap_from_the_database(
    mon: Monitor, db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An event published before the follower's subscription took effect is
    not lost: the next live event's seq reveals the gap, and metrics.db has it."""
    import argparse

    _store_events(mon)  # seq 1-4 in the log
    args = argparse.Namespace(kind=None, subject=None, count=3, format="json")
    sub = cli._subscriber(f"tcp://127.0.0.1:{mon.config.pub_port}", "health.event")
    try:
        time.sleep(0.3)  # the follower is connected from here on
        # seq 5 and 6 "happened while it was not yet listening": stored only
        assert mon.store is not None
        mon.store.add_event("2026-10-19T10:00:00.000Z", "HALT", "WARN", "MSFT", "L1 CB")
        mon.store.add_event(
            "2026-10-19T10:00:01.000Z", "RESUME", "INFO", "MSFT", "timer"
        )
        mon.publish_event("SESSION", "INFO", "session", "PRE_OPEN -> CONTINUOUS")
        assert cli._follow(args, db, sub, last_seq=4, header=False) == 0
    finally:
        sub.close()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["seq"], r["kind"]) for r in rows] == [
        (5, "HALT"),
        (6, "RESUME"),
        (7, "SESSION"),
    ]


# ---------------------------------------------------------------------------
# health --extended
# ---------------------------------------------------------------------------


class TestHealthExtended:
    def test_a_sound_database(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            cli, "_deployed_session_timezone", lambda: "Europe/Stockholm"
        )
        _store_events(mon)
        code, out, _ = _run(capsys, *_args(mon, db, "health", "--extended", "-v"))
        assert code == 0, out
        assert "metrics.db:          OK" in out
        assert "events rows: 4" in out and "session timezone: Europe/Stockholm" in out
        assert "(+ WAL " in out

    def test_without_extended_the_database_is_skipped(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code, out, _ = _run(capsys, *_args(mon, db, "health"))
        assert code == 0 and "skipped (pass --extended" in out

    def test_a_timezone_mismatch_is_unhealthy(
        self,
        running: _Running,
        mon: Monitor,
        db: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pm-monitor would refuse to start on it: health must say so first."""
        monkeypatch.setattr(
            cli, "_deployed_session_timezone", lambda: "America/New_York"
        )
        code, out, _ = _run(
            capsys, *_args(mon, db, "--format", "json", "health", "--extended")
        )
        report = json.loads(out)
        assert code == 1 and not report["healthy"]
        assert "will refuse to start" in report["database"]["detail"]

    def test_a_missing_database(
        self,
        running: _Running,
        mon: Monitor,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code, _, _ = _run(
            capsys, *_args(mon, tmp_path / "none.db", "health", "--extended", "-q")
        )
        assert code == -1

    def test_not_a_metrics_database(self, tmp_path: Path) -> None:
        import sqlite3

        other = tmp_path / "other.db"
        sqlite3.connect(other).execute("CREATE TABLE t (x)").connection.commit()
        result = cli.check_database(other, "UTC")
        assert not result["healthy"] and "missing tables" in result["detail"]

    def test_it_never_writes(
        self, mon: Monitor, db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _store_events(mon)
        mon.close()  # pm-monitor gone: a writable last connection would checkpoint
        wal = Path(f"{db}-wal")
        before = (db.stat().st_mtime_ns, db.stat().st_size)
        assert cli.check_database(db, "Europe/Stockholm", collect_stats=True)["healthy"]
        assert (db.stat().st_mtime_ns, db.stat().st_size) == before
        # A read of a WAL database may create the empty -wal/-shm SQLite needs;
        # nothing is written into either.
        assert not wal.exists() or wal.stat().st_size == 0
