"""Unit tests for task 7.2's Readiness_Gate probes and Collector attachment.

Scoped to what task 7.2 adds: each concrete :class:`ReadinessProbe`
implementation succeeds against a correctly-responding fake, raises
:class:`ReadinessProbeError` within a bounded (short, test-only) timeout
against a non-responding fake, and :class:`CollectorSet.attach_all` is
invoked and completes before ``Orchestrator.start_all()`` returns.

Does not cover: process start order, the excluded-process list, or snapshot
restore/re-init (task 7.1, already tested implicitly by these tests reusing
that code path), the Quiesce_Protocol or ``archive_artifacts()`` (task 7.3),
or the full Orchestrator unit test suite (task 7.4). The one exception is
the last test below, which is updated in place for task 7.3's
``start_all()``-rewraps-into-``OrchestratorTimeoutError`` contract rather
than left asserting the superseded task 7.2 behaviour.

See requirements.md Requirement 8, Acceptance Criteria 8.5, 8.6, 8.9.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import sqlite3
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Callable

import pytest
import zmq

from edumatcher.systest import orchestrator as orch
from edumatcher.systest.collectors import CollectorSet
from edumatcher.systest.orchestrator import (
    ManagedProcess,
    Orchestrator,
    OrchestratorTimeoutError,
    ProcessSpec,
    ReadinessProbe,
    ReadinessProbeError,
)

_SHORT_TIMEOUT_S = 0.2
_SHORT_POLL_S = 0.02


# ---------------------------------------------------------------------------
# Fakes shared across tests
# ---------------------------------------------------------------------------


class FakeManagedProcess:
    """A minimal :class:`ManagedProcess` fake: alive until told otherwise."""

    def __init__(self) -> None:
        self.pid = 1234
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


def _spec(name: str) -> ProcessSpec:
    return ProcessSpec(name=name, command=(name,))


@contextlib.contextmanager
def _free_port() -> Generator[int, None, None]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    yield port


# ---------------------------------------------------------------------------
# Stub TCP server: replies WELCOME (or something else) to any line it reads
# ---------------------------------------------------------------------------


class _StubHelloServer:
    """A TCP server that replies once with a fixed line after any input.

    Shared by the ALF/CALF/RALF/DC1/LALF WELCOME probe tests -- each of
    those protocols is HELLO-in, WELCOME-out over a newline-delimited text
    line, so one generic stub covers all five.
    """

    def __init__(self, reply_line: bytes) -> None:
        self._reply_line = reply_line
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        try:
            conn.settimeout(2.0)
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                buf += chunk
            conn.sendall(self._reply_line)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self._srv.close()


# ---------------------------------------------------------------------------
# TCP-connect-plus-WELCOME probes: pm-alf-gwy, pm-md-gwy, pm-ralf-gwy,
# pm-dc-gwy, pm-log-srv
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "probe_name, welcome_line",
    [
        ("_probe_alf_gwy", b"WELCOME|PROTO=ALF1|GW=alf-gwy01|ID=X\n"),
        ("_probe_md_gwy", b"WELCOME|PROTO=CALF1|GW=md-gwy01\n"),
        ("_probe_ralf_gwy", b"WELCOME|PROTO=RALF1|GW=ralf-gwy01|ROLE=CLEARING\n"),
        ("_probe_dc_gwy", b"WELCOME|PROTO=DC1|GW=dc-gwy01|ID=X\n"),
        ("_probe_log_srv", b"WELCOME|PROTO=LALF1|SRV=s|HBINT=5|SESSION=s1\n"),
    ],
)
def test_tcp_hello_probe_succeeds_against_a_welcome_reply(
    probe_name: str, welcome_line: bytes
) -> None:
    server = _StubHelloServer(welcome_line)
    try:
        probe: Callable[..., None] = getattr(orch, probe_name)
        handle = FakeManagedProcess()
        probe(
            _spec("proc"),
            handle,
            port=server.port,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    finally:
        server.close()


@pytest.mark.parametrize(
    "probe_name",
    [
        "_probe_alf_gwy",
        "_probe_md_gwy",
        "_probe_ralf_gwy",
        "_probe_dc_gwy",
        "_probe_log_srv",
    ],
)
def test_tcp_hello_probe_raises_within_bounded_timeout_when_nothing_listens(
    probe_name: str,
) -> None:
    probe: Callable[..., None] = getattr(orch, probe_name)
    handle = FakeManagedProcess()
    with _free_port() as port:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError) as exc_info:
            probe(
                _spec("proc"),
                handle,
                port=port,
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    assert exc_info.value.process_name == "proc"
    # Bounded: the probe must not wait meaningfully longer than its own
    # configured timeout (a generous multiplier absorbs scheduling jitter,
    # not a second full timeout's worth of slack).
    assert elapsed < _SHORT_TIMEOUT_S * 4


@pytest.mark.parametrize(
    "probe_name",
    [
        "_probe_alf_gwy",
        "_probe_md_gwy",
        "_probe_ralf_gwy",
        "_probe_dc_gwy",
        "_probe_log_srv",
    ],
)
def test_tcp_hello_probe_fails_fast_when_process_already_exited(
    probe_name: str,
) -> None:
    probe: Callable[..., None] = getattr(orch, probe_name)
    handle = FakeManagedProcess()
    handle.returncode = 1
    with _free_port() as port:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError):
            probe(
                _spec("proc"),
                handle,
                port=port,
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    # A dead process is detected on the very first attempt, well before the
    # probe's own timeout would otherwise elapse.
    assert elapsed < _SHORT_TIMEOUT_S


# ---------------------------------------------------------------------------
# pm-api-gwy: GET /api/v1/healthz
# ---------------------------------------------------------------------------


class _HealthzHandler(http.server.BaseHTTPRequestHandler):
    healthy = True

    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"ok": self.healthy}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


def test_api_gwy_probe_succeeds_against_a_healthy_endpoint() -> None:
    server = http.server.HTTPServer(("127.0.0.1", 0), _HealthzHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        orch._probe_api_gwy(
            _spec("pm-api-gwy"),
            FakeManagedProcess(),
            port=server.server_port,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    finally:
        server.shutdown()
        server.server_close()


def test_api_gwy_probe_raises_within_bounded_timeout_when_unhealthy() -> None:
    class _UnhealthyHandler(_HealthzHandler):
        healthy = False

    server = http.server.HTTPServer(("127.0.0.1", 0), _UnhealthyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError):
            orch._probe_api_gwy(
                _spec("pm-api-gwy"),
                FakeManagedProcess(),
                port=server.server_port,
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    finally:
        server.shutdown()
        server.server_close()
    assert elapsed < _SHORT_TIMEOUT_S * 4


def test_api_gwy_probe_raises_within_bounded_timeout_when_nothing_listens() -> None:
    with _free_port() as port:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError):
            orch._probe_api_gwy(
                _spec("pm-api-gwy"),
                FakeManagedProcess(),
                port=port,
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    assert elapsed < _SHORT_TIMEOUT_S * 4


# ---------------------------------------------------------------------------
# pm-engine / pm-index: bus request/reply round trip
# ---------------------------------------------------------------------------


def test_engine_probe_succeeds_against_a_responding_bus_peer() -> None:
    responder = _EngineLikeResponder()
    try:
        orch._probe_engine(
            _spec("pm-engine"),
            FakeManagedProcess(),
            pull_addr=responder.pull_addr,
            pub_addr=responder.pub_addr,
            timeout_s=_SHORT_TIMEOUT_S * 6,
            poll_interval_s=_SHORT_POLL_S,
        )
    finally:
        responder.close()


class _EngineLikeResponder:
    """Answers a ``gateway_connect`` request with the matching auth topic.

    A closer stand-in for pm-engine than the generic ``_FakeBusResponder``:
    it decodes the request payload to learn the probe's minted gateway id
    and replies on that id's own ``system.gateway_auth.<id>`` topic, exactly
    as ``_probe_engine`` expects.
    """

    def __init__(self) -> None:
        from edumatcher.models.generated.system import topic_gateway_auth
        from edumatcher.models.message import decode, make_gateway_auth_msg

        self._decode = decode
        self._topic_gateway_auth = topic_gateway_auth
        self._make_gateway_auth_msg = make_gateway_auth_msg

        self._ctx: zmq.Context = zmq.Context.instance()
        self._pull = self._ctx.socket(zmq.PULL)
        pull_port: int = self._pull.bind_to_random_port("tcp://127.0.0.1")
        self.pull_addr = f"tcp://127.0.0.1:{pull_port}"
        self._pub = self._ctx.socket(zmq.PUB)
        pub_port: int = self._pub.bind_to_random_port("tcp://127.0.0.1")
        self.pub_addr = f"tcp://127.0.0.1:{pub_port}"
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        poller = zmq.Poller()
        poller.register(self._pull, zmq.POLLIN)
        while self._running:
            socks = dict(poller.poll(timeout=100))
            if self._pull not in socks:
                continue
            frames = self._pull.recv_multipart()
            _topic, payload = self._decode(frames)
            gateway_id = str(payload.get("gateway_id", ""))
            time.sleep(0.05)  # let a fresh SUB connection settle; see above
            self._pub.send_multipart(
                self._make_gateway_auth_msg(gateway_id, accepted=True)
            )

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        self._pull.close(linger=0)
        self._pub.close(linger=0)


def test_engine_probe_raises_within_bounded_timeout_when_nothing_responds() -> None:
    # Bind nothing: the probe connects (ZMQ PUSH/SUB connect is always
    # non-blocking) but never receives a reply.
    with _free_port() as pull_port, _free_port() as pub_port:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError):
            orch._probe_engine(
                _spec("pm-engine"),
                FakeManagedProcess(),
                pull_addr=f"tcp://127.0.0.1:{pull_port}",
                pub_addr=f"tcp://127.0.0.1:{pub_port}",
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    assert elapsed < _SHORT_TIMEOUT_S * 4


def test_index_probe_succeeds_against_a_responding_bus_peer() -> None:
    from edumatcher.models.message import decode, make_index_error_msg

    responder_running = True
    ctx: zmq.Context = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    pull_port: int = pull.bind_to_random_port("tcp://127.0.0.1")
    pub = ctx.socket(zmq.PUB)
    pub_port: int = pub.bind_to_random_port("tcp://127.0.0.1")

    def _serve() -> None:
        poller = zmq.Poller()
        poller.register(pull, zmq.POLLIN)
        while responder_running:
            socks = dict(poller.poll(timeout=100))
            if pull not in socks:
                continue
            frames = pull.recv_multipart()
            _topic, payload = decode(frames)
            gateway_id = str(payload.get("gateway_id", ""))
            time.sleep(0.05)
            pub.send_multipart(make_index_error_msg(gateway_id, "unknown index"))

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    try:
        orch._probe_index(
            _spec("pm-index"),
            FakeManagedProcess(),
            pull_addr=f"tcp://127.0.0.1:{pull_port}",
            pub_addr=f"tcp://127.0.0.1:{pub_port}",
            timeout_s=_SHORT_TIMEOUT_S * 6,
            poll_interval_s=_SHORT_POLL_S,
        )
    finally:
        responder_running = False
        thread.join(timeout=1.0)
        pull.close(linger=0)
        pub.close(linger=0)


def test_index_probe_raises_within_bounded_timeout_when_nothing_responds() -> None:
    with _free_port() as pull_port, _free_port() as pub_port:
        started = time.monotonic()
        with pytest.raises(ReadinessProbeError):
            orch._probe_index(
                _spec("pm-index"),
                FakeManagedProcess(),
                pull_addr=f"tcp://127.0.0.1:{pull_port}",
                pub_addr=f"tcp://127.0.0.1:{pub_port}",
                timeout_s=_SHORT_TIMEOUT_S,
                poll_interval_s=_SHORT_POLL_S,
            )
        elapsed = time.monotonic() - started
    assert elapsed < _SHORT_TIMEOUT_S * 4


# ---------------------------------------------------------------------------
# pm-audit / pm-stats / pm-clearing: store-artifact probes
# ---------------------------------------------------------------------------


def test_audit_probe_succeeds_once_the_log_file_exists(tmp_path: Path) -> None:
    log_file = tmp_path / "audit.log"
    log_file.write_text("")  # the file already "exists" -- probe succeeds now
    orch._probe_audit(
        _spec("pm-audit"),
        FakeManagedProcess(),
        log_file=log_file,
        timeout_s=_SHORT_TIMEOUT_S,
        poll_interval_s=_SHORT_POLL_S,
    )


def test_audit_probe_raises_within_bounded_timeout_when_file_never_appears(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "never_created.log"
    started = time.monotonic()
    with pytest.raises(ReadinessProbeError) as exc_info:
        orch._probe_audit(
            _spec("pm-audit"),
            FakeManagedProcess(),
            log_file=log_file,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    elapsed = time.monotonic() - started
    assert exc_info.value.process_name == "pm-audit"
    assert elapsed < _SHORT_TIMEOUT_S * 4


def test_stats_probe_succeeds_once_the_writer_lock_is_held(tmp_path: Path) -> None:
    db_file = tmp_path / "stats.db"
    lock_path = db_file.with_name(db_file.name + ".lock")
    holder = sqlite3.connect(str(lock_path))
    holder.execute("BEGIN EXCLUSIVE")
    try:
        orch._probe_stats(
            _spec("pm-stats"),
            FakeManagedProcess(),
            db_file=db_file,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    finally:
        holder.rollback()
        holder.close()


def test_stats_probe_raises_within_bounded_timeout_when_lock_never_taken(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "stats.db"
    started = time.monotonic()
    with pytest.raises(ReadinessProbeError):
        orch._probe_stats(
            _spec("pm-stats"),
            FakeManagedProcess(),
            db_file=db_file,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    elapsed = time.monotonic() - started
    assert elapsed < _SHORT_TIMEOUT_S * 4


def test_clearing_probe_succeeds_once_the_schema_is_applied(tmp_path: Path) -> None:
    db_file = tmp_path / "clearing.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE trade_events (id TEXT)")
    conn.commit()
    conn.close()
    orch._probe_clearing(
        _spec("pm-clearing"),
        FakeManagedProcess(),
        db_file=db_file,
        timeout_s=_SHORT_TIMEOUT_S,
        poll_interval_s=_SHORT_POLL_S,
    )


def test_clearing_probe_raises_within_bounded_timeout_when_schema_never_applied(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "clearing.db"
    started = time.monotonic()
    with pytest.raises(ReadinessProbeError):
        orch._probe_clearing(
            _spec("pm-clearing"),
            FakeManagedProcess(),
            db_file=db_file,
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )
    elapsed = time.monotonic() - started
    assert elapsed < _SHORT_TIMEOUT_S * 4


# ---------------------------------------------------------------------------
# CollectorSet.attach_all() invoked as the last step of start_all()
# ---------------------------------------------------------------------------


class _RecordingCollector:
    """A fake Collector whose ``attach()`` records that it was called.

    ``is_idle``/``capture_file`` satisfy task 7.3's extended ``Collector``
    Protocol with the same "vacuously satisfied" defaults the real
    ``CollectorSet`` relies on -- this fake predates the Quiesce_Protocol
    and archiving and is not exercised by either, only by the
    attach-order tests below.
    """

    def __init__(self, calls: list[str], name: str) -> None:
        self._calls = calls
        self._name = name

    def attach(self) -> None:
        self._calls.append(self._name)

    def is_idle(self, idle_ms: int) -> bool:
        return True

    def capture_file(self) -> Path | None:
        return None


class _RecordingLauncher:
    """A fake :class:`ProcessLauncher` that returns fresh fake processes."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def launch(self, spec: ProcessSpec) -> ManagedProcess:
        self._calls.append(f"launch:{spec.name}")
        return FakeManagedProcess()


def test_collector_set_attach_all_runs_as_the_last_step_of_start_all() -> None:
    calls: list[str] = []
    collectors = CollectorSet(
        [_RecordingCollector(calls, "E1"), _RecordingCollector(calls, "E2")]
    )
    no_op_probes: dict[str, ReadinessProbe] = {
        name: (lambda spec, handle: None) for name in _all_process_names()
    }

    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=_RecordingLauncher(calls),
        store_reinitialiser=lambda: None,
        readiness_probes=no_op_probes,
        collectors=collectors,
    )
    orchestrator.prepare()
    orchestrator.start_all()

    # Every process launch call precedes both Collector attach calls, and
    # attach_all() ran (both collectors were attached) before start_all()
    # returned.
    launch_calls = [c for c in calls if c.startswith("launch:")]
    attach_calls = [c for c in calls if not c.startswith("launch:")]
    assert attach_calls == ["E1", "E2"]
    last_launch_index = max(calls.index(c) for c in launch_calls)
    first_attach_index = min(calls.index(c) for c in attach_calls)
    assert last_launch_index < first_attach_index


def test_collector_set_attach_all_is_a_safe_no_op_when_empty() -> None:
    """An empty CollectorSet (task 9 not yet run) doesn't break start_all()."""
    no_op_probes: dict[str, ReadinessProbe] = {
        name: (lambda spec, handle: None) for name in _all_process_names()
    }
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=_RecordingLauncher([]),
        store_reinitialiser=lambda: None,
        readiness_probes=no_op_probes,
    )
    orchestrator.prepare()
    orchestrator.start_all()  # must not raise
    assert len(orchestrator.collectors) == 0


def _all_process_names() -> list[str]:
    from edumatcher.systest.orchestrator import PROCESS_START_ORDER

    return [spec.name for spec in PROCESS_START_ORDER]


# ---------------------------------------------------------------------------
# Requirement 8.4/8.5 wiring: start_all() invokes the correct probe per spec
# ---------------------------------------------------------------------------


def test_start_all_invokes_each_processs_registered_probe_exactly_once() -> None:
    invoked: list[str] = []

    def _make_probe(name: str) -> ReadinessProbe:
        def _probe(spec: ProcessSpec, handle: ManagedProcess) -> None:
            invoked.append(spec.name)

        return _probe

    probes: dict[str, ReadinessProbe] = {
        name: _make_probe(name) for name in _all_process_names()
    }
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=_RecordingLauncher([]),
        store_reinitialiser=lambda: None,
        readiness_probes=probes,
    )
    orchestrator.prepare()
    orchestrator.start_all()

    assert invoked == _all_process_names()


def test_start_all_rewraps_a_readiness_probe_failure_into_a_timeout_error_and_stops_launching_further_processes() -> (
    None
):
    """Task 7.3: ``start_all()`` rewraps ``ReadinessProbeError`` into a single
    ``OrchestratorTimeoutError`` naming the specific probe (Requirement
    8.10), superseding task 7.2's "propagates directly" behaviour.
    """
    launched: list[str] = []

    class _FailingLauncher:
        def launch(self, spec: ProcessSpec) -> ManagedProcess:
            launched.append(spec.name)
            return FakeManagedProcess()

    def _failing_probe(spec: ProcessSpec, handle: ManagedProcess) -> None:
        raise ReadinessProbeError(spec.name, "stub failure")

    names = _all_process_names()
    probes: dict[str, ReadinessProbe] = {
        name: (lambda spec, handle: None) for name in names
    }
    # The third process in start order fails its probe.
    probes[names[2]] = _failing_probe

    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=_FailingLauncher(),
        store_reinitialiser=lambda: None,
        readiness_probes=probes,
    )
    orchestrator.prepare()
    with pytest.raises(OrchestratorTimeoutError) as exc_info:
        orchestrator.start_all()

    assert names[2] in exc_info.value.what
    assert "stub failure" in exc_info.value.detail
    assert isinstance(exc_info.value.__cause__, ReadinessProbeError)
    # Exactly the first three processes were launched; the fourth never was.
    assert launched == names[:3]
