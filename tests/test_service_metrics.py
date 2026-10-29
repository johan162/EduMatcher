"""Operator dashboard WP-A6: service metrics and reporters.

Per service, the counters move at their real increment sites, and the loop
that does the work is the one that ticks (findings F7, F8, risk K8).
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq

import edumatcher.market_sim.main as _sim_main
import edumatcher.scheduler.main as _sched
from edumatcher.health import HealthReporter
from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.server import LogServer
from edumatcher.models.generated.health import MetricSample, parse_health_beacon
from edumatcher.models.message import encode
from edumatcher.models.order import OrderType, Side
from tests.clearing_harness import start_clearing
from tests.conftest import free_port, free_ports
from tests.engine_harness import connect, make_engine, order_payload
from tests.test_index_main_runtime import proc  # noqa: F401  (fixture)

#: Module aliases typed Any: the tests patch stdlib modules these import but do
#: not re-export (time, zmq).
sched: Any = _sched
sim_main: Any = _sim_main


def _value(samples: Sequence[MetricSample], name: str, label: str = "") -> float:
    found = [s.value for s in samples if s.name == name and s.label == label]
    assert len(found) == 1, f"{name}{{{label}}}: {found}"
    return found[0]


def _wait(cond: Callable[[], bool], what: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


class RecordingReporter:
    """Stands in for HealthReporter: records ticks and published samples."""

    def __init__(self) -> None:
        self.ticks = 0
        self.thread_ids: set[int] = set()
        self.published: list[list[MetricSample]] = []
        self.stopped = False

    def tick(self) -> None:
        self.ticks += 1
        self.thread_ids.add(threading.get_ident())

    def tick_and_publish(self, samples: Callable[[], Sequence[MetricSample]]) -> None:
        self.tick()
        if len(self.published) < 3:
            self.published.append(list(samples()))

    def stop(self) -> None:
        self.stopped = True


# ---------------------------------------------------------------------------
# A6.1 pm-log-srv
# ---------------------------------------------------------------------------


@pytest.fixture
def log_server(tmp_path: Path) -> Iterator[tuple[LogServer, RecordingReporter, int]]:
    port, pub_port, pull_port = free_ports(3)
    server = LogServer(
        LogServerConfig(
            bind_address="127.0.0.1",
            port=port,
            db_path=tmp_path / "log.db",
            pub_port=pub_port,
            pull_port=pull_port,
        )
    )
    reporter = RecordingReporter()
    server.attach_reporter(reporter)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait(lambda: reporter.ticks > 0, "the log server loop")
    yield server, reporter, port
    server.stop()
    thread.join(timeout=5)


def test_log_server_counts_three_log_frames(
    log_server: tuple[LogServer, RecordingReporter, int],
) -> None:
    server, reporter, port = log_server
    conn = socket.create_connection(("127.0.0.1", port), timeout=2)
    conn.sendall(b"HELLO|CLIENT=pm-test|PID=1|HOST=h|PROTO=LALF1\n")
    for seq in (1, 2, 3):
        payload = f"hello {seq}".encode()
        conn.sendall(
            f"LOG|SEQ={seq}|TS=2026-10-19T10:00:00.000Z|LEVEL=INFO|"
            f"LOGGER=t|LEN={len(payload)}\n".encode() + payload
        )
    _wait(lambda: server._events_in >= 3, "three LOG frames")
    samples = server.metric_samples()
    assert _value(samples, "log.events_in") == 3
    assert _value(samples, "log.sessions") == 1
    assert _value(samples, "log.ps_subscriptions") == 0
    assert _value(samples, "log.writer_queue") >= 0
    conn.close()


def test_log_server_loop_ticks_and_close_stops_the_reporter(
    log_server: tuple[LogServer, RecordingReporter, int],
) -> None:
    server, reporter, _port = log_server
    _wait(lambda: reporter.ticks >= 20, "20 ticks")
    assert reporter.published and reporter.published[0]
    server.stop()
    _wait(lambda: reporter.stopped, "close() to stop the reporter")


# ---------------------------------------------------------------------------
# A6.2 pm-stats: ticks on the receive thread (F7)
# ---------------------------------------------------------------------------


class _StatsPoller:
    """Reports the engine SUB readable until told to stop."""

    def __init__(self, process: Any) -> None:
        self._proc = process

    def register(self, *_a: Any) -> None:
        pass

    def poll(self, timeout: int = 0) -> dict[Any, int]:
        time.sleep(0.005)
        return {self._proc.sub: zmq.POLLIN}


@pytest.fixture
def stats_proc(tmp_path: Path) -> Iterator[Any]:
    from edumatcher.stats.main import StatsProcess

    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        recorder = StatsProcess(tmp_path / "stats.db")
    sub: Any = recorder.sub
    sub.recv_multipart.return_value = encode("system.anything", {})
    sub.poll.return_value = 0  # nothing left queued when the loop stops
    yield recorder
    recorder._running = False
    recorder.close()


@pytest.mark.real_health_reporter
def test_a_stalled_receive_loop_ages_while_the_main_thread_idles(
    stats_proc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The receive thread blocks in a handler; the main thread sits in
    join() as in run(). The beacon must show the stall."""
    port = free_port()
    sink: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PULL)
    sink.setsockopt(zmq.LINGER, 0)
    sink.bind(f"tcp://127.0.0.1:{port}")
    reporter = HealthReporter("pm-stats", host="127.0.0.1", port=port, interval_sec=0.1)
    stats_proc.attach_reporter(reporter)
    stall = threading.Event()

    def dispatch(_topic: str, _payload: Any, _msg_id: str | None = None) -> None:
        if not stall.is_set():
            stall.set()
            time.sleep(1.5)  # a stuck write

    monkeypatch.setattr(stats_proc, "_dispatch", dispatch)
    monkeypatch.setattr(zmq, "Poller", lambda: _StatsPoller(stats_proc))
    reporter.start()
    receiver = threading.Thread(target=stats_proc._receive, daemon=True)
    receiver.start()
    try:
        receiver.join(timeout=0.2)  # the main thread, idle in join()
        worst = 0.0
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and worst < 1000:
            if sink.poll(500):
                worst = max(
                    worst, parse_health_beacon(sink.recv_multipart()).loop_age_ms
                )
        assert worst >= 1000, "the receive-thread stall did not show in loop_age_ms"
    finally:
        stats_proc._running = False
        receiver.join(timeout=3)
        reporter.stop()
        sink.close()


def test_stats_counts_recorded_and_dropped_events(
    stats_proc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def dispatch(_topic: str, _payload: Any, _msg_id: str | None = None) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        if calls["n"] >= 4:
            stats_proc._running = False

    monkeypatch.setattr(stats_proc, "_dispatch", dispatch)
    monkeypatch.setattr(zmq, "Poller", lambda: _StatsPoller(stats_proc))
    reporter = RecordingReporter()
    stats_proc.attach_reporter(reporter)
    stats_proc._receive_loop()
    samples = stats_proc.metric_samples()
    assert _value(samples, "stats.events_recorded") == 3
    assert _value(samples, "stats.records_dropped") == 1
    assert _value(samples, "stats.feed_gaps") == 0
    assert reporter.ticks >= 4


def test_stats_counts_a_feed_gap(stats_proc: Any) -> None:
    stats_proc._check_topic_sequence("trade.executed", 1)
    stats_proc._check_topic_sequence("trade.executed", 5)  # 2-4 missing
    assert _value(stats_proc.metric_samples(), "stats.feed_gaps") == 1


# ---------------------------------------------------------------------------
# A6.3 pm-audit
# ---------------------------------------------------------------------------


def test_audit_counts_records_and_bytes(tmp_path: Path) -> None:
    from edumatcher.audit.main import AuditProcess

    sub = MagicMock()
    frames = encode("trade.executed", {"x": 1})
    sub.recv_multipart.return_value = frames
    with (
        patch("edumatcher.audit.main.make_subscriber", return_value=sub),
        patch("edumatcher.audit.main.make_replier", return_value=MagicMock()),
    ):
        audit = AuditProcess(log_path=tmp_path / "audit.log", to_terminal=False)
    reporter = RecordingReporter()
    audit.attach_reporter(reporter)  # type: ignore[arg-type]

    n = {"polls": 0}

    class Poller:
        def register(self, *_a: Any) -> None:
            pass

        def poll(self, timeout: int = 0) -> dict[Any, int]:
            n["polls"] += 1
            if n["polls"] > 5:
                audit._running = False
                return {}
            return {sub: zmq.POLLIN}

    with patch("edumatcher.audit.main.zmq.Poller", return_value=Poller()):
        audit._receive()
    samples = audit.metric_samples()
    assert _value(samples, "audit.records") == 5
    assert _value(samples, "audit.bytes") > 5 * len(b'{"x": 1}')
    assert _value(samples, "audit.decode_errors") == 0
    assert reporter.ticks >= 5  # ticked on the receive loop itself


# ---------------------------------------------------------------------------
# A6.4 pm-clearing
# ---------------------------------------------------------------------------


def test_clearing_counts_settled_trades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine, "GW01", "GW02")
    for _ in range(3):
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 10, "GW01", 100.0)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 10, "GW02", 100.0)
        )
    cut = start_clearing(tmp_path / "clearing.db")
    try:
        cut.publish_engine_output(pub.sent)
        cut.wait_ingested(3)
        cut.flush()
        assert _value(cut.process.metric_samples(), "clearing.trades_settled") == 3
    finally:
        cut.stop()


# ---------------------------------------------------------------------------
# A6.5 pm-scheduler (F8)
# ---------------------------------------------------------------------------


def test_a_five_second_wait_ticks_at_least_four_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every wake-up calls is_running(), which is where main() ticks."""
    clock = {"t": 0.0}
    monkeypatch.setattr(sched.time, "sleep", lambda s: clock.update(t=clock["t"] + s))
    wakes = {"n": 0}

    def is_running() -> bool:
        wakes["n"] += 1
        return True

    sched._sleep_until_wallclock(
        lambda: 5.0 - clock["t"], is_running, max_chunk=sched.LIVENESS_CHUNK_SEC
    )
    assert wakes["n"] >= 5
    assert sched._next_wait_sec == 0.0  # reset once the wait is over


def test_the_gauge_reports_the_remaining_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    def fake_sleep(_s: float) -> None:
        seen.append(sched._metric_samples()[0].value)

    monkeypatch.setattr(sched.time, "sleep", fake_sleep)
    remaining = iter([30.0, 10.0, 0.0])
    sched._sleep_until_wallclock(lambda: next(remaining), lambda: True)
    assert seen == [30.0, 10.0]


def test_the_wallclock_bound_is_unchanged() -> None:
    """The liveness chunk sits inside the 30 s re-check bound."""
    assert sched.WALLCLOCK_RECHECK_SEC == 30.0
    assert sched.LIVENESS_CHUNK_SEC <= sched.WALLCLOCK_RECHECK_SEC


def test_an_idle_scheduler_is_not_degraded() -> None:
    """Its designed wait is the gap pm-monitor measures as loop_lag_ms, so it
    must sit well under the DEGRADED line (I76), with room for jitter."""
    from edumatcher.monitor.state import LOOP_LAG_DEGRADED_MS

    assert sched.LIVENESS_CHUNK_SEC * 1000 <= LOOP_LAG_DEGRADED_MS / 2


# ---------------------------------------------------------------------------
# A6.6 pm-index, pm-market-sim: the poll loop ticks
# ---------------------------------------------------------------------------


class _IdlePoller:
    def __init__(self, stop: Callable[[], None], after: int) -> None:
        self._stop, self._after, self._n = stop, after, 0

    def register(self, *_a: Any) -> None:
        pass

    def poll(self, *_a: Any, **_k: Any) -> dict[Any, int]:
        self._n += 1
        if self._n >= self._after:
            self._stop()
        return {}


def test_index_loop_ticks(
    proc: Any, monkeypatch: pytest.MonkeyPatch  # noqa: F811  (fixture)
) -> None:
    reporter = RecordingReporter()
    proc.attach_reporter(reporter)
    monkeypatch.setattr(zmq, "Poller", lambda: _IdlePoller(proc.stop, after=10))
    proc.run()
    assert reporter.ticks >= 10
    proc.close()
    assert reporter.stopped
    monkeypatch.setattr(proc, "close", lambda: None)  # the fixture closes too


class _SimSocket:
    closed = False

    def send_multipart(self, *_a: Any, **_k: Any) -> None:
        pass

    def poll(self, *_a: Any) -> int:
        return 0

    def close(self, *_a: Any, **_k: Any) -> None:
        self.closed = True


def test_market_sim_loop_ticks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_market_sim_main import _sim

    for name in ("make_publisher", "make_puller", "make_pusher", "_engine_subscriber"):
        monkeypatch.setattr(sim_main, name, lambda *_a, **_k: _SimSocket())
    runner = sim_main.Runner(_sim(), tmp_path / "sim_state.json")
    reporter = RecordingReporter()
    runner.attach_reporter(reporter)
    monkeypatch.setattr(
        sim_main.zmq, "Poller", lambda: _IdlePoller(runner.stop, after=10)
    )
    runner.run()
    assert reporter.ticks >= 10
    assert reporter.stopped


class _SlowSock:
    """A socket that is never readable; poll() waits its timeout and records it."""

    def __init__(self, readable_after: int | None = None) -> None:
        self.timeouts: list[int] = []
        self.readable_after = readable_after

    def poll(self, timeout: int = 0) -> int:
        self.timeouts.append(timeout)
        if self.readable_after is not None and len(self.timeouts) > self.readable_after:
            return 1
        time.sleep(timeout / 1000)
        return 0


def test_engine_round_trips_tick_while_they_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A+B review, I93: a 2 s wait for the engine's reply was one poll, so the
    beacon saw the scheduler's loop ~2 s late at start-up and every transition."""
    monkeypatch.setattr(sched, "LIVENESS_CHUNK_SEC", 0.05)
    wakes: list[float] = []
    sock = _SlowSock()
    assert not sched._poll_live(sock, 230, lambda: wakes.append(time.monotonic()))
    assert max(sock.timeouts) <= 50
    assert len(wakes) >= 4
    gaps = [b - a for a, b in zip(wakes, wakes[1:])]
    assert max(gaps) < 0.2


def test_a_reply_ends_the_wait_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "LIVENESS_CHUNK_SEC", 0.05)
    sock = _SlowSock(readable_after=1)
    assert sched._poll_live(sock, 5000, None)
    assert len(sock.timeouts) == 2
