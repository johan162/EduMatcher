"""Operator dashboard WP-A2: ``HealthReporter``.

Real ZeroMQ over ``tcp://127.0.0.1:<free port>`` -- ``inproc://`` does not
cross the socket-in-thread boundary the reporter relies on. Intervals are
scaled down (0.1-0.2 s) so the behaviours are observable quickly; the logic
does not depend on the interval's size.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import zmq

from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.health import reporter as reporter_module
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.health import HealthBeacon, parse_health_beacon
from edumatcher.monitor.config import MonitorConfig
from tests.conftest import free_port

pytestmark = pytest.mark.real_health_reporter


class Collector:
    """A PULL socket standing in for pm-monitor."""

    def __init__(self) -> None:
        self.port = free_port()
        self.sock: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PULL)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(f"tcp://127.0.0.1:{self.port}")

    def next(self, timeout: float = 3.0) -> HealthBeacon:
        if not self.sock.poll(int(timeout * 1000)):
            raise AssertionError(f"no beacon within {timeout}s")
        return parse_health_beacon(self.sock.recv_multipart())

    def until(self, predicate: Any, timeout: float = 5.0) -> HealthBeacon:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            beacon = self.next(timeout=deadline - time.monotonic())
            if predicate(beacon):
                return beacon
        raise AssertionError("no matching beacon")

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def collector() -> Iterator[Collector]:
    c = Collector()
    yield c
    c.close()


def _reporter(port: int, interval: float = 0.1, **kw: Any) -> HealthReporter:
    return HealthReporter(
        "pm-test",
        kw.pop("instance", None),
        host="127.0.0.1",
        port=port,
        interval_sec=interval,
        **kw,
    )


@pytest.fixture
def running(collector: Collector) -> Iterator[HealthReporter]:
    rep = _reporter(collector.port)
    rep.start()
    yield rep
    rep.stop()


class TestSamples:
    def test_counter_and_gauge_kinds(self) -> None:
        c = counter("engine.orders_in", 3, "GW01")
        g = gauge("md.clients", 2)
        assert (c.kind, c.label, c.value) == ("COUNTER", "GW01", 3.0)
        assert (g.kind, g.label, g.value) == ("GAUGE", "", 2.0)
        c.validate()
        g.validate()

    def test_an_over_long_label_does_not_validate(self) -> None:
        with pytest.raises(MessageValidationError):
            counter("x.y", 1, "L" * 33).validate()


class TestBeaconsArrive:
    def test_every_interval_with_increasing_seq(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        beacons = [collector.next() for _ in range(4)]
        assert [b.seq for b in beacons] == [0, 1, 2, 3]
        assert {b.boot_id for b in beacons} == {running.boot_id}
        assert all(b.process == "pm-test" and b.final is False for b in beacons)

    def test_the_vitals_are_real(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        import os

        beacon = collector.next()
        assert beacon.pid == os.getpid()
        assert beacon.rss_bytes > 0
        assert beacon.threads >= 2  # this thread and the sampler
        assert beacon.fds is not None and beacon.fds > 0  # POSIX
        assert beacon.interval_sec == pytest.approx(0.1)
        assert beacon.started_at_ns > 0
        assert len(running.boot_id) == 16

    def test_the_instance_is_carried(self, collector: Collector) -> None:
        rep = _reporter(collector.port, instance="desk")
        rep.start()
        try:
            assert collector.next().instance == "desk"
        finally:
            rep.stop()

    def test_the_first_beacon_carries_the_reporters_own_metrics(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        """A2.7: present from the first beacon, zero or not."""
        names = {m.name for m in collector.next().metrics}
        assert {"health.beacons_dropped", "health.gc_gen2"} <= names

    def test_published_samples_are_sent(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        running.publish((counter("engine.orders_in", 7, "GW01"),))
        beacon = collector.until(
            lambda b: any(m.name == "engine.orders_in" for m in b.metrics)
        )
        sample = next(m for m in beacon.metrics if m.name == "engine.orders_in")
        assert (sample.label, sample.value) == ("GW01", 7.0)


class TestTheMainLoopHalfNeverTouchesTheSocket:
    def test_tick_and_publish_make_no_socket_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A2.3: every socket call happens on the sampler thread."""
        calls: list[tuple[str, int]] = []

        class FakeSocket:
            def __getattr__(self, name: str) -> Any:
                def record(*args: Any, **kwargs: Any) -> None:
                    calls.append((name, threading.get_ident()))

                return record

        class FakeContext:
            def socket(self, kind: int) -> FakeSocket:
                calls.append(("socket", threading.get_ident()))
                return FakeSocket()

        monkeypatch.setattr(zmq.Context, "instance", lambda: FakeContext())
        rep = _reporter(1, interval=0.05)
        rep.start()
        main = threading.get_ident()
        for _ in range(2000):
            rep.tick()
            if rep.due():
                rep.publish((counter("a.b", 1),))
        time.sleep(0.2)
        rep.stop()
        assert calls, "the sampler never used its socket"
        assert all(ident != main for _name, ident in calls)

    def test_tick_is_cheap(self) -> None:
        rep = _reporter(1)
        start = time.perf_counter()
        for _ in range(100_000):
            rep.tick()
        per_call = (time.perf_counter() - start) / 100_000
        assert per_call < 1e-5, f"tick() took {per_call * 1e9:.0f} ns"


class TestNoPeer:
    def test_nothing_blocks_and_stop_is_prompt(self) -> None:
        """A2.4(b): no pm-monitor bound at all."""
        rep = _reporter(free_port(), interval=0.05)
        rep.start()
        worst = 0.0
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            t0 = time.perf_counter()
            rep.tick()
            if rep.due():
                rep.publish((gauge("x.y", 1),))
            worst = max(worst, time.perf_counter() - t0)
        t0 = time.monotonic()
        rep.stop()
        assert time.monotonic() - t0 < 1.0
        assert worst < 0.01

    def test_drops_are_counted_once_the_queue_is_full(
        self, collector: Collector
    ) -> None:
        """Beacons that do not fit the high-water mark are counted, and the
        count reaches pm-monitor once it is back."""
        port = free_port()
        rep = _reporter(port, interval=0.02)
        rep.start()
        time.sleep(0.6)  # ~30 beacons against SNDHWM 10, nobody listening
        sink: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.PULL)
        sink.setsockopt(zmq.LINGER, 0)
        sink.bind(f"tcp://127.0.0.1:{port}")
        try:
            deadline = time.monotonic() + 3.0
            dropped = 0.0
            while time.monotonic() < deadline and dropped == 0:
                if sink.poll(500):
                    beacon = parse_health_beacon(sink.recv_multipart())
                    dropped = next(
                        m.value
                        for m in beacon.metrics
                        if m.name == "health.beacons_dropped"
                    )
            assert dropped > 0
        finally:
            rep.stop()
            sink.close()


class TestHungSemantics:
    def test_loop_age_grows_while_ticks_stop_and_beacons_continue(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        """A2.5: the hung case, then recovery."""
        running.tick()
        time.sleep(1.5)  # the "main loop" is stuck; the sampler is not
        hung = collector.until(lambda b: b.loop_age_ms > 1400)
        assert hung.loop_age_ms > 1400

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:  # the loop runs again
            running.tick()
            time.sleep(0.005)
        recovered = collector.until(lambda b: b.loop_age_ms < 100)
        assert recovered.seq > hung.seq

    def test_loop_lag_reports_the_worst_gap_then_resets(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        running.tick()
        time.sleep(0.4)
        running.tick()  # one 400 ms iteration
        lagged = collector.until(lambda b: b.loop_lag_ms >= 390)
        assert lagged.loop_lag_ms < 1000

        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            running.tick()
            time.sleep(0.005)
        assert collector.until(lambda b: b.loop_lag_ms < 100).seq > lagged.seq


class TestStarting:
    def test_starting_until_the_first_tick(self, collector: Collector) -> None:
        """Set-up before the loop exists is reported as starting, not as a
        hung loop -- loop_age_ms still grows, so a stuck start stays visible."""
        rep = _reporter(collector.port)
        rep.start()
        try:
            first = collector.next()
            assert first.starting is True
            rep.tick()
            assert collector.until(lambda b: not b.starting).seq > first.seq
        finally:
            rep.stop()

    def test_a_restart_starts_again(self, collector: Collector) -> None:
        rep = _reporter(collector.port)
        rep.start()
        rep.tick()
        rep.stop()
        rep.start()
        try:
            assert collector.until(lambda b: b.starting and b.seq > 0).starting
        finally:
            rep.stop()


class TestStop:
    def test_the_last_beacon_is_final(self, collector: Collector) -> None:
        """A2.6"""
        rep = _reporter(collector.port)
        rep.start()
        collector.next()
        rep.stop()
        assert collector.until(lambda b: b.final, timeout=2.0).final is True

    def test_stop_is_idempotent_and_safe_before_start(
        self, collector: Collector
    ) -> None:
        rep = _reporter(collector.port)
        rep.stop()
        rep.start()
        rep.stop()
        rep.stop()


class TestBadSamplesCostOnlyThemselves:
    def test_an_invalid_sample_is_dropped_and_counted(
        self, collector: Collector, running: HealthReporter
    ) -> None:
        """I4: a labelling bug must not silence the process."""
        running.publish((counter("ok.metric", 1), counter("bad.metric", 1, "L" * 40)))
        beacon = collector.until(
            lambda b: any(m.name == "ok.metric" for m in b.metrics)
        )
        names = {m.name for m in beacon.metrics}
        assert "bad.metric" not in names
        rejected = next(
            m for m in beacon.metrics if m.name == "health.samples_rejected"
        )
        assert rejected.value >= 1

    def test_a_long_hostname_is_truncated(
        self, collector: Collector, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("socket.gethostname", lambda: "h" * 300)
        rep = _reporter(collector.port)
        rep.start()
        try:
            assert collector.next().host == "h" * 128
        finally:
            rep.stop()


class TestFromCompiledConfig:
    def test_disabled_monitoring_means_no_reporter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reporter_module,
            "load_default_monitor_config",
            lambda: MonitorConfig(enabled=False),
        )
        assert HealthReporter.from_compiled_config("pm-engine") is None

    def test_the_section_supplies_endpoint_and_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            reporter_module,
            "load_default_monitor_config",
            lambda: MonitorConfig(
                host="10.1.2.3", pull_port=6000, beacon_interval_sec=3
            ),
        )
        rep = HealthReporter.from_compiled_config("pm-api-gwy", "desk")
        assert rep is not None
        assert rep.endpoint == "tcp://10.1.2.3:6000"
        assert rep.interval_sec == 3.0
        assert (rep.process, rep.instance) == ("pm-api-gwy", "desk")


@pytest.mark.parametrize("bad", [0, -1.0])
def test_a_non_positive_interval_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="interval_sec"):
        HealthReporter("p", host="127.0.0.1", port=1, interval_sec=bad)
