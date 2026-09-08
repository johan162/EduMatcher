"""Process lifecycle, readiness gates, snapshot restore, and quiescence.

Implements the ``Orchestrator``: snapshot restore / store re-initialisation
before any process starts, starting and stopping the EduMatcher process set
in dependency order, per-process Readiness_Gate probes, Collector
attachment, the Quiesce_Protocol, and artefact archiving on run end.

Task 7.1 implemented the snapshot/store lifecycle and process start/stop
ordering (Requirements 8.1-8.4):

* ``restore_snapshot()`` (standard mode) / ``reinit_stores()`` (dev mode),
  each run before any process starts; failure raises :class:`SnapshotRestoreError`
  and leaves the run unable to reach ``start_all()``.
* ``start_all()`` starts the EduMatcher process set in the design document
  §5.2 dependency order, never starting ``pm-scheduler``, ``pm-ticker``,
  ``pm-board``, ``pm-orders``, ``pm-ai-trader``, or ``pm-mm-bot``.
* ``stop_all()`` stops processes in reverse start order and captures each
  process's exit code (evidence sink E11).

Task 7.2 implements the per-process Readiness_Gate probes (Requirement 8.5)
and Collector attachment (Requirement 8.6):

* ``start_all()`` awaits a positive, process-specific readiness probe
  immediately after launching each process and before launching the next --
  ``GET /api/v1/healthz`` for ``pm-api-gwy``, TCP-connect-plus-``WELCOME``
  for the TCP gateways (``pm-alf-gwy``, ``pm-md-gwy``, ``pm-ralf-gwy``,
  ``pm-dc-gwy``, ``pm-log-srv``), a bus request/reply round trip for
  ``pm-engine`` and ``pm-index``, and a store-artifact probe for the three
  processes with no external query interface (``pm-audit``, ``pm-stats``,
  ``pm-clearing``). See :func:`default_readiness_probes`.
* A probe that does not succeed within its timeout raises
  :class:`ReadinessProbeError`, naming the process and the failure -- a
  probe-specific exception a later task (7.3/8.10) wraps into a single
  ``OrchestratorTimeoutError``.
* ``CollectorSet.attach_all()`` runs as the literal last step of
  ``start_all()``, after every process has passed its readiness probe and
  strictly before ``start_all()`` returns control to the Runner.
* No ``sleep()`` call appears anywhere in this module (Requirement 8.9):
  every bounded wait below is either a single blocking call with a
  socket/HTTP timeout, or a poll loop whose inter-attempt wait is a
  ``threading.Event().wait(timeout)`` block (the same non-sleep backoff
  primitive ``calf_client.py`` already uses between reconnect attempts, via
  its ``self._stopped.wait(backoff)``), never ``time.sleep()``.

Task 7.3 implements the Quiesce_Protocol (Requirement 8.7) and artefact
archiving (Requirement 8.8), and unifies every timeout-governed failure
into a single exception type (Requirement 8.10):

* ``quiesce(idle_ms=250)`` polls, without ``sleep()``, until three
  conditions hold simultaneously: every Driver has its expected
  acknowledgement (via the injected ``driver_ack_check`` callable -- see
  its docstring for why this is a callable rather than a direct Driver
  dependency), every registered Collector reports :meth:`Collector.is_idle`
  for ``idle_ms``, and the audit journal plus stats database have been
  observed unchanged for a continuous ``idle_ms`` window.
* ``archive_artifacts(scenario_id, transport_label)`` copies every
  currently-available captured artefact (the audit log, the stats and
  clearing databases, and every Collector's own capture file) under
  ``artifacts/<scenario_id>/<transport_label>/`` and returns that
  directory. Designed to be called on any run end -- normal completion or
  a Readiness_Gate/Quiesce/Collector-attachment failure -- so it never
  raises for an artefact that does not exist yet.
* ``OrchestratorTimeoutError`` is the single exception every
  timeout-governed failure raises: ``start_all()`` now catches
  :class:`ReadinessProbeError` (and any exception from
  ``CollectorSet.attach_all()``) and re-raises it as this type, naming the
  process/attachment that did not succeed; ``quiesce()`` raises it directly
  on its own overall timeout, naming which of the three conditions had not
  yet been met.

See design.md Components §8 (Orchestrator) and Requirements 8.1-8.10.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol

import zmq

from edumatcher.alf_gwy.protocol import AlfProtocolError
from edumatcher.alf_gwy.protocol import build_line as _alf_build_line
from edumatcher.alf_gwy.protocol import parse_alf_line as _alf_parse_line
from edumatcher.config import (
    AUDIT_LOG_FILE,
    CLEARING_DB_FILE,
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
    INDEX_PUB_CONNECT_ADDR,
    INDEX_PULL_CONNECT_ADDR,
    STATS_DB_FILE,
)
from edumatcher.dc_gateway.protocol import DcProtocolError
from edumatcher.dc_gateway.protocol import build_line as _dc_build_line
from edumatcher.dc_gateway.protocol import parse_line as _dc_parse_line
from edumatcher.gateway_ports import DEFAULT_API_GATEWAY_PORT, SINGLETON_GATEWAYS
from edumatcher.logclient.protocol import LalfProtocolError
from edumatcher.logclient.protocol import build_hello_frame as _lalf_build_hello
from edumatcher.logclient.protocol import parse_header_line as _lalf_parse_header
from edumatcher.md_gateway.protocol import CalfProtocolError
from edumatcher.md_gateway.protocol import build_line as _calf_build_line
from edumatcher.md_gateway.protocol import parse_line as _calf_parse_line
from edumatcher.models.generated.index import topic_index_error
from edumatcher.models.generated.system import topic_gateway_auth
from edumatcher.models.message import (
    make_gateway_connect_msg,
    make_index_history_request_msg,
)
from edumatcher.ralf_gateway.protocol import RalfProtocolError
from edumatcher.ralf_gateway.protocol import build_line as _ralf_build_line
from edumatcher.ralf_gateway.protocol import parse_line as _ralf_parse_line
from edumatcher.systest.collectors import CollectorSet

__all__ = [
    "EXCLUDED_PROCESS_NAMES",
    "ManagedProcess",
    "Orchestrator",
    "OrchestratorError",
    "OrchestratorTimeoutError",
    "ProcessLauncher",
    "ProcessSpec",
    "PROCESS_START_ORDER",
    "ReadinessProbe",
    "ReadinessProbeError",
    "SnapshotRestoreError",
    "SubprocessProcessLauncher",
    "default_readiness_probes",
]

#: Identity every readiness probe's own TCP/bus session uses. Reserved and
#: distinct from any real Actor/gateway id a Scenario would bind, since a
#: probe session connects, proves the process answers, and disconnects again
#: before the Runner is handed control.
_PROBE_IDENTITY = "SYSTESTPROBE"

#: Overall per-process readiness budget and inter-attempt poll interval for
#: every probe below that must retry (a process launched a moment ago may
#: not have finished binding its socket yet). Deliberately module-level
#: constants rather than Orchestrator constructor parameters for now -- no
#: task or requirement calls for per-run tuning, and keeping them here keeps
#: every probe function's signature uniform.
_DEFAULT_READINESS_TIMEOUT_S = 10.0
_DEFAULT_READINESS_POLL_INTERVAL_S = 0.05

#: Overall budget for one ``quiesce()`` call and its inter-attempt poll
#: interval. A module-level constant rather than a ``quiesce()`` parameter
#: for the same reason the readiness constants above are: no requirement
#: calls for per-call tuning, and design.md's ``quiesce(self, *, idle_ms:
#: int = 250)`` signature is fixed by the design document -- adding a
#: second public parameter here would diverge from it.
_DEFAULT_QUIESCE_TIMEOUT_S = 30.0
_DEFAULT_QUIESCE_POLL_INTERVAL_S = 0.02

#: TCP ports for the gateway-style processes, taken from gateway_ports.py's
#: single source of truth rather than re-declared here (the design.md
#: rationale for that module applies equally to a second, drifting copy in
#: the Orchestrator).
_SINGLETON_GATEWAY_PORTS: dict[str, int] = {
    gw.process: gw.default_port for gw in SINGLETON_GATEWAYS
}

#: Every readiness probe below connects to ``127.0.0.1`` rather than
#: resolving each process's configured bind address. The Systest_Framework
#: runs the whole process set on one fixed-state test VM (design.md
#: Architecture; Requirement 1's "fixed-state test VM"), and every other
#: process in this package that talks TCP to a locally-started process (the
#: ALF/REST drivers, task 15/16) makes the same assumption -- a process
#: bound to ``0.0.0.0`` (the default, see ``config.py``) is always reachable
#: at ``127.0.0.1``.
_PROBE_HOST = "127.0.0.1"


class OrchestratorError(Exception):
    """Base class for Orchestrator lifecycle failures.

    Distinct from a Driver's connectivity/business-rejection exceptions
    (design.md's Error Handling table) and from a Layer 1/2/3 assertion
    failure -- this is the Orchestrator's own "the run cannot proceed"
    category.
    """


class SnapshotRestoreError(OrchestratorError):
    """Raised when ``restore_snapshot()``/``reinit_stores()`` fails.

    Requirement 8.3: this always fires before ``start_all()`` has started
    any process for the run. The Orchestrator enforces this at the API
    level, not merely by convention: ``start_all()`` refuses to run unless
    ``restore_snapshot()``/``reinit_stores()`` has *succeeded* first (see
    ``Orchestrator._prepared``), so raising this exception leaves the
    Orchestrator unable to start any process until the caller retries and
    succeeds.
    """


class ReadinessProbeError(OrchestratorError):
    """Raised when one process's Readiness_Gate probe does not succeed.

    Requirement 8.5/8.10: names the process whose probe failed and the
    specific failure, so a later task (7.3/8.10) can catch this exception
    and rewrap it into a single ``OrchestratorTimeoutError`` naming which
    probe did not succeed, without having to re-derive that information
    from a generic message string.
    """

    def __init__(self, process_name: str, detail: str) -> None:
        self.process_name = process_name
        self.detail = detail
        super().__init__(f"{process_name} readiness probe failed: {detail}")


class OrchestratorTimeoutError(OrchestratorError):
    """Raised when a Readiness_Gate, the Quiesce_Protocol, or Collector
    attachment does not succeed within its configured timeout.

    Requirement 8.10: the single exception type every timeout-governed
    Orchestrator failure raises, naming ``what`` (the specific probe,
    attachment, or Quiesce_Protocol condition that did not succeed) and
    ``detail`` (the specific failure), so a run-level diagnostic dump can
    report it without re-deriving that information from a generic message
    string.

    ``start_all()`` raises this rather than letting a
    :class:`ReadinessProbeError` or a ``CollectorSet.attach_all()``
    exception propagate directly -- each is caught and rewrapped here,
    with the original exception preserved as ``__cause__`` so nothing
    about the underlying failure is lost. ``quiesce()`` raises this
    directly on its own overall timeout, naming whichever of its three
    stability conditions had not yet been met.
    """

    def __init__(self, what: str, detail: str) -> None:
        self.what = what
        self.detail = detail
        super().__init__(
            f"{what} did not complete within its configured timeout: {detail}"
        )


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    """One process in the EduMatcher process set the Orchestrator manages.

    ``name`` is both the process's ``pm-*`` console-script name and the key
    used to report its exit code (Requirement 8.8, evidence sink E11).
    ``command`` is the argv the launcher executes.
    """

    name: str
    command: tuple[str, ...]


#: The design document §5.2 / Requirement 8.4 process set, in dependency
#: start order: ``pm-log-srv -> pm-engine -> pm-audit -> pm-stats ->
#: pm-clearing -> pm-md-gwy -> pm-ralf-gwy -> pm-dc-gwy -> pm-alf-gwy ->
#: pm-api-gwy -> pm-index``. ``stop_all()`` walks this in reverse.
PROCESS_START_ORDER: tuple[ProcessSpec, ...] = (
    ProcessSpec(name="pm-log-srv", command=("pm-log-srv",)),
    ProcessSpec(name="pm-engine", command=("pm-engine",)),
    ProcessSpec(name="pm-audit", command=("pm-audit",)),
    ProcessSpec(name="pm-stats", command=("pm-stats",)),
    ProcessSpec(name="pm-clearing", command=("pm-clearing",)),
    ProcessSpec(name="pm-md-gwy", command=("pm-md-gwy",)),
    ProcessSpec(name="pm-ralf-gwy", command=("pm-ralf-gwy",)),
    ProcessSpec(name="pm-dc-gwy", command=("pm-dc-gwy",)),
    ProcessSpec(name="pm-alf-gwy", command=("pm-alf-gwy",)),
    ProcessSpec(name="pm-api-gwy", command=("pm-api-gwy",)),
    ProcessSpec(name="pm-index", command=("pm-index",)),
)

#: Requirement 8.4: the Orchestrator SHALL NOT start any of these, so the
#: test driver remains the only source of order flow. ``start_all()`` never
#: references these names -- this constant exists so a test (task 7.4) can
#: assert the exclusion explicitly, and so this intent is documented in one
#: place rather than only implied by ``PROCESS_START_ORDER``'s omissions.
EXCLUDED_PROCESS_NAMES: frozenset[str] = frozenset(
    {
        "pm-scheduler",
        "pm-ticker",
        "pm-board",
        "pm-orders",
        "pm-ai-trader",
        "pm-mm-bot",
    }
)


class ManagedProcess(Protocol):
    """The subset of ``subprocess.Popen``'s interface the Orchestrator needs.

    A structural :class:`typing.Protocol` rather than a direct dependency on
    ``subprocess.Popen`` so a test's fake process (task 7.4's "mock process
    launcher") does not need to subclass ``Popen`` -- it only needs to
    supply these five members. ``subprocess.Popen`` already satisfies this
    Protocol structurally.
    """

    pid: int
    returncode: int | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class ProcessLauncher(Protocol):
    """Launches one :class:`ProcessSpec` and returns its :class:`ManagedProcess`.

    The Orchestrator's only dependency on *how* a process is started --
    kept to this single method so tests can substitute a fake launcher that
    records call order and returns an in-memory fake process, without
    spawning any real ``pm-*`` command (task 7.4).
    """

    def launch(self, spec: ProcessSpec) -> ManagedProcess: ...


class SubprocessProcessLauncher:
    """The Orchestrator's default :class:`ProcessLauncher`.

    Launches each :class:`ProcessSpec` as a real child process via
    ``subprocess.Popen``.
    """

    def launch(self, spec: ProcessSpec) -> ManagedProcess:
        return subprocess.Popen(list(spec.command))


class ReadinessProbe(Protocol):
    """A per-process positive Readiness_Gate probe (Requirement 8.5).

    Called by ``start_all()`` immediately after launching ``spec`` and
    before launching the next process. Implementations block until the
    process answers a probe specific to it (an HTTP health endpoint, a TCP
    connect plus ``WELCOME``, a bus request/reply round trip, or a
    store-artifact check for a process with no external query interface),
    or raise :class:`ReadinessProbeError` once their own configured timeout
    elapses -- never a fixed delay, never a ``time.sleep()`` call.

    ``handle`` is passed alongside ``spec`` so a probe can check
    :meth:`ManagedProcess.poll` and fail fast (rather than waiting out its
    full timeout) if the process has already exited.

    The Orchestrator is constructed with a ``process_name -> ReadinessProbe``
    mapping (defaulting to :func:`default_readiness_probes`) so a test can
    substitute a fake probe for a fake launcher's fake process, mirroring
    the existing ``ProcessLauncher``/``process_launcher`` injection pattern.
    """

    def __call__(self, spec: ProcessSpec, handle: ManagedProcess) -> None: ...


def _bounded_wait(seconds: float) -> None:
    """Block for up to ``seconds`` without ``time.sleep()`` or busy-spinning.

    ``threading.Event().wait(timeout)`` blocks on a condition variable
    rather than sleeping or polling in a tight loop -- the same non-sleep
    backoff primitive ``calf_client.py``'s ``CalfClient.run()`` already uses
    between reconnect attempts (``self._stopped.wait(backoff)``). Used here
    as the inter-attempt wait for every probe below that must retry.
    """
    threading.Event().wait(max(0.0, seconds))


def _check_process_alive(spec: ProcessSpec, handle: ManagedProcess) -> None:
    """Fail fast if ``handle`` has already exited.

    Every probe below calls this at the top of each retry attempt so a
    process that crashed during startup is reported immediately, by name,
    rather than the caller waiting out the full readiness timeout only to
    receive a generic "did not become ready" message.
    """
    code = handle.poll()
    if code is not None:
        raise ReadinessProbeError(
            spec.name, f"process exited with code {code} before becoming ready"
        )


def _read_line(sock: socket.socket, timeout_s: float) -> str:
    """Read one newline-terminated line from ``sock``, with a timeout.

    Every TCP protocol in this codebase (ALF, CALF, RALF, DC1, LALF) is
    newline-delimited, so this one reader is shared by every TCP-hello
    probe below rather than duplicated five times.
    """
    sock.settimeout(timeout_s)
    buf = bytearray()
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("connection closed before a full line was received")
        buf.extend(chunk)
        if len(buf) > 8192:
            raise OSError(
                "readiness probe response exceeded 8192 bytes without a newline"
            )
    idx = buf.find(b"\n")
    return buf[:idx].decode("utf-8", errors="replace").strip("\r")


def _probe_tcp_hello(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int,
    build_hello: Callable[[str], bytes],
    is_welcome: Callable[[str], bool],
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """Shared TCP-connect-plus-``WELCOME`` probe (design.md Components §8).

    Connects, sends a protocol-specific ``HELLO`` built by ``build_hello``,
    reads one reply line, and succeeds once ``is_welcome`` reports it is a
    positive ``WELCOME`` reply. A connection refusal (the process has not
    finished binding its listener yet) or any other failure is retried,
    bounded by ``timeout_s``, with :func:`_bounded_wait` as the inter-attempt
    wait -- never a fixed delay and never ``time.sleep()``.
    """
    deadline = time.monotonic() + timeout_s
    attempt = 0
    last_error = "no attempt made"
    while True:
        _check_process_alive(spec, handle)
        attempt += 1
        probe_id = f"{_PROBE_IDENTITY}{attempt}"
        remaining = max(0.1, deadline - time.monotonic())
        try:
            with socket.create_connection(
                (_PROBE_HOST, port), timeout=remaining
            ) as sock:
                sock.sendall(build_hello(probe_id))
                line = _read_line(sock, max(0.1, deadline - time.monotonic()))
            if is_welcome(line):
                return
            last_error = f"unexpected reply to HELLO: {line!r}"
        except (OSError, TimeoutError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise ReadinessProbeError(spec.name, last_error)
        _bounded_wait(poll_interval_s)


def _probe_bus_round_trip(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    pull_addr: str,
    pub_addr: str,
    build_request: Callable[[str], list[bytes]],
    reply_topic: Callable[[str], str],
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """Shared engine-query probe: a bus request/reply round trip.

    Sends a request built by ``build_request`` over a PUSH socket connected
    to ``pull_addr``, having already subscribed a SUB socket (connected to
    ``pub_addr``) to the topic ``reply_topic`` names for that same request.
    Succeeds on the first reply observed on that topic. Retried, bounded by
    ``timeout_s``, so a request sent before the SUB socket's connection has
    finished establishing (and would otherwise be missed entirely, since
    PUB/SUB delivers nothing to a not-yet-connected subscriber) is simply
    re-sent on the next attempt once the connection is up.
    """
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    push = ctx.socket(zmq.PUSH)
    push.setsockopt(zmq.LINGER, 0)
    push.connect(pull_addr)
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt(zmq.LINGER, 0)
    sub.connect(pub_addr)
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)
    deadline = time.monotonic() + timeout_s
    attempt = 0
    try:
        while True:
            _check_process_alive(spec, handle)
            attempt += 1
            probe_id = f"{_PROBE_IDENTITY}{attempt}"
            topic = reply_topic(probe_id).encode("utf-8")
            sub.setsockopt(zmq.SUBSCRIBE, topic)
            try:
                push.send_multipart(build_request(probe_id))
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                socks = dict(poller.poll(remaining_ms))
                if sub in socks:
                    sub.recv_multipart()
                    return
            finally:
                sub.setsockopt(zmq.UNSUBSCRIBE, topic)
            if time.monotonic() >= deadline:
                raise ReadinessProbeError(
                    spec.name,
                    f"no reply on {topic.decode()} within {timeout_s:.1f}s",
                )
            _bounded_wait(poll_interval_s)
    finally:
        push.close(linger=0)
        sub.close(linger=0)


def _poll_readiness(
    spec: ProcessSpec,
    handle: ManagedProcess,
    predicate: Callable[[], bool],
    *,
    what: str,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """Shared store-artifact probe: poll ``predicate`` until it is true.

    Used for the three processes with no external health endpoint, TCP
    handshake, or bus query interface (``pm-audit``, ``pm-stats``,
    ``pm-clearing``) -- each supplies a ``predicate`` that inspects a real,
    process-specific structural artifact (a lock held, a schema applied, a
    file created), never a specific expected log line (Requirement 8.5
    explicitly excludes a log-line match as a readiness technique).
    """
    deadline = time.monotonic() + timeout_s
    while True:
        _check_process_alive(spec, handle)
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise ReadinessProbeError(
                spec.name, f"{what} was not observed within {timeout_s:.1f}s"
            )
        _bounded_wait(poll_interval_s)


def _probe_http_health(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    url: str,
    is_healthy: Callable[[int, dict[str, object]], bool],
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """Shared ``GET`` health-endpoint probe (design.md Components §8).

    Issues a single blocking ``GET`` with a socket-level timeout via the
    standard library's :mod:`urllib.request` -- no new HTTP dependency is
    introduced for this internal probe (``httpx`` is reserved for the REST
    driver, task 16, which needs its WebSocket/async surface; this probe
    needs neither). Retried, bounded by ``timeout_s``, so a connection
    refusal while ``pm-api-gwy`` is still binding its listener is simply
    retried on the next attempt.
    """
    deadline = time.monotonic() + timeout_s
    last_error = "no attempt made"
    while True:
        _check_process_alive(spec, handle)
        remaining = max(0.1, deadline - time.monotonic())
        try:
            with urllib.request.urlopen(url, timeout=remaining) as resp:  # noqa: S310
                status = resp.status
                body = json.loads(resp.read().decode("utf-8"))
            if is_healthy(status, body):
                return
            last_error = f"HTTP {status}, body={body!r}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            raise ReadinessProbeError(spec.name, last_error)
        _bounded_wait(poll_interval_s)


def _probe_api_gwy(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int = DEFAULT_API_GATEWAY_PORT,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """``GET /api/v1/healthz`` for ``pm-api-gwy`` (design.md Components §8).

    ``port``/``timeout_s``/``poll_interval_s`` default to production values
    and exist so a test can point this probe at a stub HTTP server on an
    ephemeral port with a short timeout, without exercising the real
    ``pm-api-gwy`` process or waiting out the production timeout.
    """
    _probe_http_health(
        spec,
        handle,
        url=f"http://{_PROBE_HOST}:{port}/api/v1/healthz",
        is_healthy=lambda status, body: status == 200 and body.get("ok") is True,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_alf_gwy(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """TCP-connect-plus-``WELCOME`` for ``pm-alf-gwy`` over ALF1."""

    def is_welcome(line: str) -> bool:
        try:
            return _alf_parse_line(line).command == "WELCOME"
        except AlfProtocolError:
            return False

    _probe_tcp_hello(
        spec,
        handle,
        port=port if port is not None else _SINGLETON_GATEWAY_PORTS["pm-alf-gwy"],
        build_hello=lambda probe_id: _alf_build_line(
            "HELLO", {"CLIENT": "SYSTESTPROBE", "PROTO": "ALF1", "ID": probe_id}
        ),
        is_welcome=is_welcome,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_md_gwy(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """TCP-connect-plus-``WELCOME`` for ``pm-md-gwy`` over CALF1."""

    def is_welcome(line: str) -> bool:
        try:
            return _calf_parse_line(line).msg_type == "WELCOME"
        except CalfProtocolError:
            return False

    _probe_tcp_hello(
        spec,
        handle,
        port=port if port is not None else _SINGLETON_GATEWAY_PORTS["pm-md-gwy"],
        build_hello=lambda probe_id: _calf_build_line(
            "HELLO", {"CLIENT": "SYSTESTPROBE", "PROTO": "CALF1"}
        ),
        is_welcome=is_welcome,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_ralf_gwy(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """TCP-connect-plus-``WELCOME`` for ``pm-ralf-gwy`` over RALF1."""

    def is_welcome(line: str) -> bool:
        try:
            return _ralf_parse_line(line).msg_type == "WELCOME"
        except RalfProtocolError:
            return False

    _probe_tcp_hello(
        spec,
        handle,
        port=port if port is not None else _SINGLETON_GATEWAY_PORTS["pm-ralf-gwy"],
        build_hello=lambda probe_id: _ralf_build_line(
            "HELLO",
            {"CLIENT": "SYSTESTPROBE", "PROTO": "RALF1", "ROLE": "CLEARING"},
        ),
        is_welcome=is_welcome,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_dc_gwy(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """TCP-connect-plus-``WELCOME`` for ``pm-dc-gwy`` over DC1."""

    def is_welcome(line: str) -> bool:
        try:
            return _dc_parse_line(line).msg_type == "WELCOME"
        except DcProtocolError:
            return False

    _probe_tcp_hello(
        spec,
        handle,
        port=port if port is not None else _SINGLETON_GATEWAY_PORTS["pm-dc-gwy"],
        build_hello=lambda probe_id: _dc_build_line(
            "HELLO", {"CLIENT": "SYSTESTPROBE", "PROTO": "DC1", "ID": probe_id}
        ),
        is_welcome=is_welcome,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_log_srv(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    port: int | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """TCP-connect-plus-``WELCOME`` for ``pm-log-srv`` over LALF1."""

    def is_welcome(line: str) -> bool:
        try:
            msg_type, _fields = _lalf_parse_header(line)
            return msg_type == "WELCOME"
        except LalfProtocolError:
            return False

    _probe_tcp_hello(
        spec,
        handle,
        port=port if port is not None else _SINGLETON_GATEWAY_PORTS["pm-log-srv"],
        build_hello=lambda probe_id: _lalf_build_hello(
            client=f"systest-probe-{probe_id}",
            pid=os.getpid(),
            host=socket.gethostname(),
        ),
        is_welcome=is_welcome,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_engine(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    pull_addr: str = ENGINE_PULL_ADDR,
    pub_addr: str = ENGINE_PUB_ADDR,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """An engine query for ``pm-engine``: a ``gateway_connect``/auth round trip."""
    _probe_bus_round_trip(
        spec,
        handle,
        pull_addr=pull_addr,
        pub_addr=pub_addr,
        build_request=lambda probe_id: make_gateway_connect_msg(probe_id),
        reply_topic=lambda probe_id: topic_gateway_auth(probe_id),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_index(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    pull_addr: str = INDEX_PULL_CONNECT_ADDR,
    pub_addr: str = INDEX_PUB_CONNECT_ADDR,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """An engine query for ``pm-index``: a history-request/error round trip.

    Requests history for a deliberately nonexistent index id, so
    ``pm-index`` always answers with ``index.error.<probe_id>`` -- a
    positive, process-specific reply that does not depend on any index
    being configured for the run.
    """
    _probe_bus_round_trip(
        spec,
        handle,
        pull_addr=pull_addr,
        pub_addr=pub_addr,
        build_request=lambda probe_id: make_index_history_request_msg(
            probe_id, f"{probe_id}-NOPE", 0.0, 0.0
        ),
        reply_topic=lambda probe_id: topic_index_error(probe_id),
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_audit(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    log_file: Path | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """A store-artifact probe for ``pm-audit``.

    ``pm-audit`` has no health endpoint, TCP listener, or bus reply verb --
    it only subscribes to the engine bus and appends to its log file. Its
    ``AuditProcess.__init__`` creates that log file (via ``_setup_logger``,
    a ``RotatingFileHandler``) before entering its receive loop, so the
    file's existence is a genuine, process-specific structural signal that
    construction completed -- not a wait for any particular log *content*
    (Requirement 8.5 excludes a log-line match, not a log file's existence).
    """
    path = log_file if log_file is not None else AUDIT_LOG_FILE
    _poll_readiness(
        spec,
        handle,
        lambda: path.exists(),
        what="the audit log file to be created",
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_stats(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    db_file: Path | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """A store-artifact probe for ``pm-stats``: its exclusive writer lock.

    ``pm-stats`` takes a process-lifetime exclusive lock on a
    ``stats.db.lock`` sidecar file (``_acquire_writer_lock`` in
    ``stats/main.py``) before opening ``stats.db`` itself. Attempting to
    take that same lock here is a genuine positive probe of readiness: it
    fails with ``sqlite3.OperationalError`` if and only if ``pm-stats``
    already holds it, which happens synchronously very early in its own
    startup, well before it can answer any hypothetical query.
    """
    db_path = db_file if db_file is not None else STATS_DB_FILE

    def _stats_lock_held() -> bool:
        lock_path = db_path.with_name(db_path.name + ".lock")
        if not lock_path.exists():
            return False
        conn = sqlite3.connect(str(lock_path))
        try:
            conn.execute("PRAGMA busy_timeout = 0")
            try:
                conn.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError:
                return True
            conn.rollback()
            return False
        finally:
            conn.close()

    _poll_readiness(
        spec,
        handle,
        _stats_lock_held,
        what="pm-stats to acquire its writer lock",
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def _probe_clearing(
    spec: ProcessSpec,
    handle: ManagedProcess,
    *,
    db_file: Path | None = None,
    timeout_s: float = _DEFAULT_READINESS_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_READINESS_POLL_INTERVAL_S,
) -> None:
    """A store-artifact probe for ``pm-clearing``: its schema being applied.

    ``pm-clearing`` has no exclusive-lock scheme of its own, so this probes
    a different structural signal: ``ClearingProcess.__init__`` calls
    ``open_writer_connection()``, which applies the full DDL schema
    (``apply_schema``, idempotent ``CREATE TABLE IF NOT EXISTS``)
    synchronously, before the receive loop starts. The ``trade_events``
    table's presence is therefore a genuine sign construction completed.
    """
    db_path = db_file if db_file is not None else CLEARING_DB_FILE

    def _clearing_schema_applied() -> bool:
        if not db_path.exists():
            return False
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return False
        try:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='trade_events'"
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    _poll_readiness(
        spec,
        handle,
        _clearing_schema_applied,
        what="pm-clearing to apply its database schema",
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def default_readiness_probes() -> dict[str, ReadinessProbe]:
    """Production :class:`ReadinessProbe` for every name in ``PROCESS_START_ORDER``.

    Used as the ``Orchestrator``'s default ``readiness_probes`` mapping. A
    test substitutes its own mapping (of fake probes, matched to a fake
    :class:`ProcessLauncher`'s fake processes) rather than exercising any of
    these real network/bus/filesystem probes.
    """
    return {
        "pm-log-srv": _probe_log_srv,
        "pm-engine": _probe_engine,
        "pm-audit": _probe_audit,
        "pm-stats": _probe_stats,
        "pm-clearing": _probe_clearing,
        "pm-md-gwy": _probe_md_gwy,
        "pm-ralf-gwy": _probe_ralf_gwy,
        "pm-dc-gwy": _probe_dc_gwy,
        "pm-alf-gwy": _probe_alf_gwy,
        "pm-api-gwy": _probe_api_gwy,
        "pm-index": _probe_index,
    }


def _audit_journal_position(path: Path) -> int:
    """A monotonically-non-decreasing proxy for "the audit journal sequence".

    ``pm-audit`` appends one line per event to its log with no embedded
    sequence number of its own (``AuditProcess``/``_setup_logger`` in
    ``audit/main.py`` write plain ``[ts] [topic] {json}`` lines via a
    ``RotatingFileHandler``), so this uses the active log file's size in
    bytes as the observable proxy for Requirement 8.7's "audit journal
    sequence": it only ever grows while a new entry is appended, and is
    unchanged exactly when no new entry has been written since the last
    poll.

    Returns ``-1`` if the file does not exist yet -- a real, comparable
    state distinct from ``0`` (an existing-but-empty file), so a quiesce
    reached before ``pm-audit`` has written its first line is not silently
    indistinguishable from an idle, already-flushed journal.
    """
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _stats_db_max_rowid(path: Path) -> int:
    """The stats database's maximum rowid, summed across every real table.

    Requirement 8.7's "stats database maximum row identifier": queries
    SQLite's implicit ``rowid`` -- present on every ordinary table
    regardless of whether it also declares its own ``INTEGER PRIMARY KEY``
    alias (``order_events``/``feed_gaps`` do; ``trade_log`` does not, since
    its primary key is the durable ``trade_id`` text) -- rather than
    hard-coding one table's own sequence column. Summed into one integer
    across every table ``stats/main.py``'s schema defines, since this value
    is only ever compared for equality between polls, never inspected for
    its absolute magnitude.

    Returns ``-1`` if the database file does not exist yet, or if opening
    or querying it fails for any reason (including a writer holding a lock
    incompatible with even a read) -- a real, comparable state distinct
    from "0 rows written yet", exactly mirroring
    :func:`_audit_journal_position`'s ``-1`` sentinel.
    """
    if not path.exists():
        return -1
    try:
        conn = sqlite3.connect(str(path))
    except sqlite3.Error:
        return -1
    try:
        try:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
        except sqlite3.Error:
            return -1
        total = 0
        for table in tables:
            try:
                row = conn.execute(f'SELECT MAX(rowid) FROM "{table}"').fetchone()
            except sqlite3.Error:
                continue
            if row is not None and row[0] is not None:
                total += int(row[0])
        return total
    finally:
        conn.close()


def _default_reinit_stores() -> None:
    """Dev-mode default store re-initialisation.

    Runs ``pm-opctl-cli clear --state --yes`` (``edumatcher.emo.cli``'s
    ``clear`` command), which wipes engine/session state -- order books,
    GTC orders, derived stats, index and clearing state -- without touching
    logs, the audit trail, or ``ref_data/`` reference configuration. This
    matches design document §5.2's "wipe and re-init stores", as distinct
    from the standard-mode fixed snapshot restore, which additionally
    resets reference data.
    """
    result = subprocess.run(
        ["pm-opctl-cli", "clear", "--state", "--yes"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SnapshotRestoreError(
            "`pm-opctl-cli clear --state --yes` exited "
            f"{result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


class Orchestrator:
    """Snapshot/store lifecycle, process start/stop ordering, and readiness.

    See design.md Components §8. Constructed with the run's ``mode``
    (``"standard"`` restores the fixed snapshot; ``"dev"`` wipes and
    re-initialises the stores) and, optionally, the collaborators a test
    substitutes: a :class:`ProcessLauncher`, a snapshot-restore callable, a
    store-reinitialisation callable, a ``process_name -> ReadinessProbe``
    mapping (default: :func:`default_readiness_probes`), a
    :class:`CollectorSet` (default: an empty one -- Collectors themselves
    are task 9), a ``driver_ack_check`` predicate for ``quiesce()``
    (default: vacuously ``True`` -- Drivers themselves are tasks 15-17),
    the audit/stats/clearing store paths ``quiesce()``/``archive_artifacts()``
    read (default: the production paths in ``config.py``), and the root
    directory ``archive_artifacts()`` writes under (default: ``artifacts/``,
    relative to the current working directory, per Requirement 8.8).
    """

    def __init__(
        self,
        *,
        mode: Literal["standard", "dev"] = "standard",
        process_launcher: ProcessLauncher | None = None,
        snapshot_restorer: Callable[[], None] | None = None,
        store_reinitialiser: Callable[[], None] | None = None,
        readiness_probes: Mapping[str, ReadinessProbe] | None = None,
        collectors: CollectorSet | None = None,
        stop_timeout_s: float = 5.0,
        driver_ack_check: Callable[[], bool] | None = None,
        audit_log_file: Path | None = None,
        stats_db_file: Path | None = None,
        clearing_db_file: Path | None = None,
        artifacts_root: Path | None = None,
        quiesce_timeout_s: float = _DEFAULT_QUIESCE_TIMEOUT_S,
        quiesce_poll_interval_s: float = _DEFAULT_QUIESCE_POLL_INTERVAL_S,
    ) -> None:
        self._mode = mode
        self._launcher = (
            process_launcher
            if process_launcher is not None
            else SubprocessProcessLauncher()
        )
        self._snapshot_restorer = snapshot_restorer
        self._store_reinitialiser = (
            store_reinitialiser
            if store_reinitialiser is not None
            else _default_reinit_stores
        )
        self._readiness_probes: Mapping[str, ReadinessProbe] = (
            readiness_probes
            if readiness_probes is not None
            else default_readiness_probes()
        )
        self._collectors = collectors if collectors is not None else CollectorSet()
        self._stop_timeout_s = stop_timeout_s
        # Requirement 8.7's first stability condition -- "every Driver has
        # its expected acknowledgement" -- is expressed as an injected
        # predicate rather than a direct dependency on the Driver Protocol
        # (``drivers/base.py``) or on any concrete Driver instance: the
        # Orchestrator is constructed and ``start_all()``/``quiesce()`` are
        # exercised (task 7.3/7.4) well before any concrete Driver exists
        # (tasks 15-17), and the Runner -- not the Orchestrator -- is the
        # component that actually holds the bound Drivers (design.md
        # Components §3). Defaulting to a predicate that always reports
        # "satisfied" keeps ``quiesce()`` correct today (vacuously -- no
        # Driver means no outstanding acknowledgement to wait for) without
        # the Orchestrator needing to change once a Runner starts passing a
        # real one.
        self._driver_ack_check: Callable[[], bool] = (
            driver_ack_check if driver_ack_check is not None else (lambda: True)
        )
        self._audit_log_file = (
            audit_log_file if audit_log_file is not None else AUDIT_LOG_FILE
        )
        self._stats_db_file = (
            stats_db_file if stats_db_file is not None else STATS_DB_FILE
        )
        self._clearing_db_file = (
            clearing_db_file if clearing_db_file is not None else CLEARING_DB_FILE
        )
        self._artifacts_root = (
            artifacts_root if artifacts_root is not None else Path("artifacts")
        )
        self._quiesce_timeout_s = quiesce_timeout_s
        self._quiesce_poll_interval_s = quiesce_poll_interval_s
        self._prepared = False
        self._started = False
        self._handles: list[tuple[ProcessSpec, ManagedProcess]] = []
        self._exit_codes: dict[str, int | None] = {}

    @property
    def exit_codes(self) -> dict[str, int | None]:
        """Each stopped process's exit code (evidence sink E11).

        Keyed by :attr:`ProcessSpec.name`. Populated by ``stop_all()``;
        empty before the first ``stop_all()`` call for a run.
        """
        return dict(self._exit_codes)

    @property
    def collectors(self) -> CollectorSet:
        """The :class:`CollectorSet` ``start_all()`` attaches as its last step.

        Task 9 populates this (via the constructor's ``collectors``
        argument, or by calling :meth:`CollectorSet.add` on this property
        before ``start_all()`` runs) with the real per-sink Collectors;
        empty by default today.
        """
        return self._collectors

    def prepare(self) -> None:
        """Run whichever of ``restore_snapshot()``/``reinit_stores()`` this
        run's ``mode`` requires.

        A convenience for callers that don't want to branch on ``mode``
        themselves (Requirement 8.1/8.2); ``restore_snapshot()`` and
        ``reinit_stores()`` remain independently callable for a caller that
        already knows its mode.
        """
        if self._mode == "standard":
            self.restore_snapshot()
        else:
            self.reinit_stores()

    def restore_snapshot(self) -> None:
        """Restore the fixed system snapshot before any process starts.

        Requirement 8.1: runs (and must complete) before ``start_all()``.
        Requirement 8.3: on failure, raises :class:`SnapshotRestoreError`
        identifying the restore failure and leaves ``start_all()`` unusable
        for this run (see the ``_prepared`` gate in ``start_all()``).

        No concrete VM/container snapshot-restore command is hard-coded
        here: design document §4.1/§15 leaves the fixed-state substrate (VM
        snapshot vs. container reset) as an open infrastructure decision
        this task does not resolve. A caller running in standard mode
        against a real fixed-state node MUST construct this Orchestrator
        with a ``snapshot_restorer`` callable that performs that substrate's
        actual restore; calling this method without one configured is
        itself a deliberate, diagnosable failure rather than a silent
        no-op.
        """
        if self._snapshot_restorer is None:
            raise SnapshotRestoreError(
                "no snapshot restorer configured for this standard-mode "
                "run: construct Orchestrator(mode='standard', "
                "snapshot_restorer=...) with a callable that restores this "
                "run's fixed-state substrate (see design.md §4.1 -- the "
                "concrete VM/container mechanism is an infrastructure "
                "decision this Orchestrator does not hard-code)"
            )
        try:
            self._snapshot_restorer()
        except SnapshotRestoreError:
            raise
        except Exception as exc:
            raise SnapshotRestoreError(f"snapshot restore failed: {exc}") from exc
        self._prepared = True

    def reinit_stores(self) -> None:
        """Wipe and re-initialise the stores before any process starts.

        Requirement 8.2/8.3 -- see ``restore_snapshot()``'s docstring for
        the shared failure-before-any-process-starts guarantee.
        """
        try:
            self._store_reinitialiser()
        except SnapshotRestoreError:
            raise
        except Exception as exc:
            raise SnapshotRestoreError(
                f"store re-initialisation failed: {exc}"
            ) from exc
        self._prepared = True

    def start_all(self) -> None:
        """Start the process set in dependency order.

        Requirement 8.1/8.2/8.3: refuses to start any process unless
        ``restore_snapshot()``/``reinit_stores()`` has already succeeded for
        this run. Requirement 8.4: starts exactly ``PROCESS_START_ORDER``,
        in order, and never any name in ``EXCLUDED_PROCESS_NAMES``.
        Requirement 8.5: awaits each process's Readiness_Gate probe
        immediately after launching it and before launching the next one.
        Requirement 8.6: attaches every Collector in ``self.collectors`` as
        the last step, strictly before this method returns and hands
        control to the Runner.

        Requirement 8.10: a probe that does not succeed within its own
        configured timeout (:class:`ReadinessProbeError`), or a Collector
        attachment failure from ``CollectorSet.attach_all()``, is caught
        here and re-raised as a single :class:`OrchestratorTimeoutError`
        naming the specific probe/attachment, with the original exception
        preserved as ``__cause__``.
        """
        if not self._prepared:
            raise OrchestratorError(
                "start_all() called before restore_snapshot()/"
                "reinit_stores() succeeded for this run; Requirement "
                "8.1/8.2 requires the fixed snapshot (standard mode) or "
                "wiped-and-reinitialised stores (dev mode) before any "
                "process starts"
            )
        if self._started:
            raise OrchestratorError("start_all() already called for this run")

        for spec in PROCESS_START_ORDER:
            handle = self._launcher.launch(spec)
            self._handles.append((spec, handle))
            probe = self._readiness_probes.get(spec.name)
            if probe is not None:
                try:
                    probe(spec, handle)
                except ReadinessProbeError as exc:
                    raise OrchestratorTimeoutError(
                        f"{spec.name} readiness probe", exc.detail
                    ) from exc

        # Requirement 8.6: Collectors attach last, strictly before the
        # Runner is handed control -- i.e. before start_all() returns and
        # before self._started flips, so no caller can observe "started"
        # without Collectors already attached.
        try:
            self._collectors.attach_all()
        except Exception as exc:
            raise OrchestratorTimeoutError("Collector attachment", str(exc)) from exc
        self._started = True

    def stop_all(self) -> dict[str, int | None]:
        """Stop the process set in reverse start order, capturing exit codes.

        Requirement 8.8 (the E11 half): every stopped process's exit code
        is captured and returned (and available afterwards via
        :attr:`exit_codes`), keyed by :attr:`ProcessSpec.name`.
        """
        exit_codes: dict[str, int | None] = {}
        for spec, handle in reversed(self._handles):
            exit_codes[spec.name] = self._stop_one(handle)
        self._handles = []
        self._started = False
        self._exit_codes = exit_codes
        return dict(exit_codes)

    def _stop_one(self, handle: ManagedProcess) -> int | None:
        """Terminate one process and capture its exit code.

        Sends ``SIGTERM`` (``terminate()``) and waits up to
        ``stop_timeout_s``; a process that has not exited by then is sent
        ``SIGKILL`` (``kill()``) and reaped without a further timeout, so
        ``stop_all()`` always completes rather than hanging on a wedged
        process.
        """
        if handle.poll() is not None:
            return handle.returncode
        handle.terminate()
        try:
            return handle.wait(timeout=self._stop_timeout_s)
        except subprocess.TimeoutExpired:
            handle.kill()
            return handle.wait()

    def quiesce(self, *, idle_ms: int = 250) -> None:
        """Block until system-wide idle per the Quiesce_Protocol (8.7).

        A ``barrier: quiesce`` Step is complete only once three conditions
        hold *simultaneously*, each observed continuously stable for
        ``idle_ms`` milliseconds:

        1. every Driver has received its expected acknowledgement (the
           injected ``driver_ack_check`` predicate reports ``True`` --
           vacuously ``True`` by default, since no concrete Driver exists
           yet; see the constructor's docstring);
        2. every registered dissemination Collector has been silent for
           ``idle_ms`` (:meth:`CollectorSet.all_idle`; vacuously ``True``
           with no Collector registered yet);
        3. the audit journal and the stats database have both been
           observed unchanged (:func:`_audit_journal_position`,
           :func:`_stats_db_max_rowid`).

        Polls without any ``time.sleep()`` call (Requirement 8.9), using
        :func:`_bounded_wait` as the inter-attempt wait, exactly like every
        Readiness_Gate probe above. ``idle_ms`` is a poll-interval bound on
        how long a value must stay unchanged to be considered stable, not
        a fixed wait -- a run that is already idle when ``quiesce()`` is
        called still waits out one ``idle_ms`` window (to *prove* nothing
        further changes), but never any single "expected acknowledgement"
        or event for longer than it actually takes to arrive.

        Raises :class:`OrchestratorTimeoutError` (naming whichever
        condition had not yet stabilised) if all three conditions do not
        hold simultaneously within this Orchestrator's overall quiesce
        timeout (Requirement 8.10).
        """
        deadline = time.monotonic() + self._quiesce_timeout_s
        stable_since: float | None = None
        last_audit_pos: int | None = None
        last_stats_rowid: int | None = None
        last_failure = "no attempt made"

        while True:
            audit_pos = _audit_journal_position(self._audit_log_file)
            stats_rowid = _stats_db_max_rowid(self._stats_db_file)
            drivers_acked = self._driver_ack_check()
            collectors_idle = self._collectors.all_idle(idle_ms)
            stores_unchanged = (
                last_audit_pos is not None
                and last_stats_rowid is not None
                and audit_pos == last_audit_pos
                and stats_rowid == last_stats_rowid
            )

            if drivers_acked and collectors_idle and stores_unchanged:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif (time.monotonic() - stable_since) * 1000.0 >= idle_ms:
                    return
            else:
                stable_since = None
                unmet = []
                if not drivers_acked:
                    unmet.append("driver acknowledgement(s) outstanding")
                if not collectors_idle:
                    unmet.append("a Collector is still disseminating")
                if not stores_unchanged:
                    unmet.append(
                        "audit journal/stats database still changing "
                        f"(audit_pos={audit_pos}, stats_rowid={stats_rowid})"
                    )
                last_failure = "; ".join(unmet)

            last_audit_pos = audit_pos
            last_stats_rowid = stats_rowid

            if time.monotonic() >= deadline:
                raise OrchestratorTimeoutError(
                    "quiesce", f"idle_ms={idle_ms}: {last_failure}"
                )
            _bounded_wait(self._quiesce_poll_interval_s)

    def archive_artifacts(self, scenario_id: str, transport_label: str) -> Path:
        """Archive every currently-available captured artefact (8.8).

        Copies the audit log, the stats database, the clearing database,
        and every registered Collector's own capture file (see
        :meth:`CollectorSet.capture_files`) into
        ``artifacts/<scenario_id>/<transport_label>/``, creating that
        directory (and its parents) if it does not already exist, and
        returns it.

        Called on any run end -- normal completion or a
        Readiness_Gate/Quiesce/Collector-attachment failure -- so a
        missing artefact (a store a process never got far enough to
        create, for a run that failed before ``start_all()`` finished) is
        silently skipped rather than raised: an incomplete archive is
        exactly what a diagnosable early-failure run's archive should look
        like, not itself a further failure.
        """
        destination = self._artifacts_root / scenario_id / transport_label
        destination.mkdir(parents=True, exist_ok=True)

        for source in (
            self._audit_log_file,
            self._stats_db_file,
            self._clearing_db_file,
            *self._collectors.capture_files(),
        ):
            self._copy_artifact(source, destination)

        return destination

    @staticmethod
    def _copy_artifact(source: Path, destination_dir: Path) -> None:
        """Copy one artefact file into ``destination_dir``, if it exists.

        Never raises for a source that does not exist -- see
        :meth:`archive_artifacts`'s docstring for why that is the correct
        behaviour here, not an omission.
        """
        if not source.exists():
            return
        try:
            shutil.copy2(source, destination_dir / source.name)
        except OSError:
            pass
