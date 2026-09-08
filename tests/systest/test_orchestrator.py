"""Unit tests for the Orchestrator (task 7.4).

Scoped to what task 7.4 asks for, using a mock process launcher and fake
Collectors/probes so nothing here spawns a real ``pm-*`` subprocess or
blocks on a real ``time.sleep()``:

* ``start_all()`` launches the EduMatcher process set in the exact
  dependency order ``PROCESS_START_ORDER`` declares (Requirement 8.4).
* ``start_all()`` never launches any name in ``EXCLUDED_PROCESS_NAMES``
  (Requirement 8.4).
* A failed ``restore_snapshot()`` aborts the run before any process starts
  -- ``start_all()`` refuses to run at all (Requirement 8.3).
* ``quiesce()`` blocks while any one of its three stability conditions is
  unmet and only returns once all three hold simultaneously for
  ``idle_ms`` (Requirement 8.7).
* A Readiness_Gate probe that times out raises a single
  ``OrchestratorTimeoutError`` naming the specific probe/process that
  failed (Requirement 8.10).

Does not re-cover task 7.2's per-probe wire-protocol correctness (already
exercised by ``test_orchestrator_readiness.py``) or task 7.3's
``archive_artifacts()`` (no requirement in this task's scope names it).

See requirements.md Requirement 8, Acceptance Criteria 8.3, 8.4, 8.7, 8.10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.systest import orchestrator as orch
from edumatcher.systest.collectors import CollectorSet
from edumatcher.systest.orchestrator import (
    EXCLUDED_PROCESS_NAMES,
    ManagedProcess,
    Orchestrator,
    OrchestratorError,
    OrchestratorTimeoutError,
    PROCESS_START_ORDER,
    ProcessSpec,
    ReadinessProbeError,
    SnapshotRestoreError,
)

# Short, test-only timing constants -- generous enough to absorb scheduler
# jitter in CI while keeping every test here fast (well under a second).
_SHORT_TIMEOUT_S = 0.15
_SHORT_POLL_S = 0.01


def _all_process_names() -> list[str]:
    return [spec.name for spec in PROCESS_START_ORDER]


def _no_op_probes() -> dict[str, orch.ReadinessProbe]:
    return {name: (lambda spec, handle: None) for name in _all_process_names()}


class FakeManagedProcess:
    """A minimal :class:`ManagedProcess` fake: alive until told otherwise."""

    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9


class RecordingLauncher:
    """A mock :class:`ProcessLauncher` that records launch order and returns
    a fresh :class:`FakeManagedProcess` for each spec, never spawning a
    real subprocess."""

    def __init__(self) -> None:
        self.launched: list[str] = []

    def launch(self, spec: ProcessSpec) -> ManagedProcess:
        self.launched.append(spec.name)
        return FakeManagedProcess()


class FakeCollector:
    """A fake Collector whose ``is_idle()`` is driven by an external toggle."""

    def __init__(self, idle: bool = True) -> None:
        self.idle = idle
        self.idle_calls = 0

    def attach(self) -> None:
        return None

    def is_idle(self, idle_ms: int) -> bool:
        self.idle_calls += 1
        return self.idle

    def capture_file(self) -> Path | None:
        return None


class CountingAckCheck:
    """A ``driver_ack_check`` fake: ``False`` for the first ``flip_after``
    calls, ``True`` on every call after that.

    Call-count based (never wall-clock based) so the point at which it
    flips is deterministic regardless of scheduling jitter -- only its
    *position* in the poll sequence matters, not real elapsed time.
    """

    def __init__(self, flip_after: int) -> None:
        self._flip_after = flip_after
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self._flip_after


def _orchestrator_ready_to_start(
    *,
    process_launcher: orch.ProcessLauncher,
    readiness_probes: dict[str, orch.ReadinessProbe] | None = None,
) -> Orchestrator:
    """Build an Orchestrator that has already passed ``prepare()``."""
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=process_launcher,
        store_reinitialiser=lambda: None,
        readiness_probes=(
            readiness_probes if readiness_probes is not None else _no_op_probes()
        ),
    )
    orchestrator.prepare()
    return orchestrator


# ---------------------------------------------------------------------------
# start_all(): exact dependency order (Requirement 8.4)
# ---------------------------------------------------------------------------


def test_start_all_launches_processes_in_exact_dependency_order() -> None:
    launcher = RecordingLauncher()
    orchestrator = _orchestrator_ready_to_start(process_launcher=launcher)

    orchestrator.start_all()

    assert launcher.launched == _all_process_names()
    assert launcher.launched == [
        "pm-log-srv",
        "pm-engine",
        "pm-audit",
        "pm-stats",
        "pm-clearing",
        "pm-md-gwy",
        "pm-ralf-gwy",
        "pm-dc-gwy",
        "pm-alf-gwy",
        "pm-api-gwy",
        "pm-index",
    ]


# ---------------------------------------------------------------------------
# start_all(): excluded processes are never started (Requirement 8.4)
# ---------------------------------------------------------------------------


def test_start_all_never_launches_any_excluded_process() -> None:
    launcher = RecordingLauncher()
    orchestrator = _orchestrator_ready_to_start(process_launcher=launcher)

    orchestrator.start_all()

    launched_names = set(launcher.launched)
    assert launched_names.isdisjoint(EXCLUDED_PROCESS_NAMES)
    # And the exclusion set is exactly the six named processes -- guards
    # against a future edit silently shrinking the exclusion list.
    assert EXCLUDED_PROCESS_NAMES == {
        "pm-scheduler",
        "pm-ticker",
        "pm-board",
        "pm-orders",
        "pm-ai-trader",
        "pm-mm-bot",
    }


# ---------------------------------------------------------------------------
# A failed snapshot restore aborts before any process starts (Req 8.3)
# ---------------------------------------------------------------------------


def test_failed_snapshot_restore_aborts_before_any_process_starts() -> None:
    launcher = RecordingLauncher()

    def _failing_restorer() -> None:
        raise RuntimeError("snapshot host unreachable")

    orchestrator = Orchestrator(
        mode="standard",
        process_launcher=launcher,
        snapshot_restorer=_failing_restorer,
        readiness_probes=_no_op_probes(),
    )

    with pytest.raises(SnapshotRestoreError):
        orchestrator.restore_snapshot()

    # start_all() must also refuse to run: the Orchestrator never reached
    # a "prepared" state, so calling it directly is itself a further,
    # separate guard against any process starting.
    with pytest.raises(OrchestratorError):
        orchestrator.start_all()

    assert launcher.launched == []


def test_start_all_refuses_to_run_when_prepare_was_never_called() -> None:
    """A second angle on the same guarantee: even without an explicit
    restore failure, start_all() never launches a process unless
    restore_snapshot()/reinit_stores() has already succeeded."""
    launcher = RecordingLauncher()
    orchestrator = Orchestrator(
        mode="standard",
        process_launcher=launcher,
        readiness_probes=_no_op_probes(),
    )

    with pytest.raises(OrchestratorError):
        orchestrator.start_all()

    assert launcher.launched == []


# ---------------------------------------------------------------------------
# quiesce(): only returns once all three stability conditions hold
# simultaneously (Requirement 8.7)
# ---------------------------------------------------------------------------


def test_quiesce_times_out_while_driver_acknowledgements_are_outstanding() -> None:
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=RecordingLauncher(),
        driver_ack_check=lambda: False,
        audit_log_file=Path("/nonexistent/audit.log"),
        stats_db_file=Path("/nonexistent/stats.db"),
        quiesce_timeout_s=_SHORT_TIMEOUT_S,
        quiesce_poll_interval_s=_SHORT_POLL_S,
    )

    with pytest.raises(OrchestratorTimeoutError) as exc_info:
        orchestrator.quiesce(idle_ms=20)

    assert exc_info.value.what == "quiesce"
    assert "acknowledgement" in exc_info.value.detail


def test_quiesce_times_out_while_a_collector_is_still_disseminating() -> None:
    busy_collector = FakeCollector(idle=False)
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=RecordingLauncher(),
        collectors=CollectorSet([busy_collector]),
        driver_ack_check=lambda: True,
        audit_log_file=Path("/nonexistent/audit.log"),
        stats_db_file=Path("/nonexistent/stats.db"),
        quiesce_timeout_s=_SHORT_TIMEOUT_S,
        quiesce_poll_interval_s=_SHORT_POLL_S,
    )

    with pytest.raises(OrchestratorTimeoutError) as exc_info:
        orchestrator.quiesce(idle_ms=20)

    assert "Collector" in exc_info.value.detail
    assert busy_collector.idle_calls > 0


def test_quiesce_times_out_while_the_audit_journal_is_still_growing(
    tmp_path: Path,
) -> None:
    audit_log_file = tmp_path / "audit.log"
    audit_log_file.write_text("")

    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=RecordingLauncher(),
        driver_ack_check=lambda: True,
        audit_log_file=audit_log_file,
        stats_db_file=Path("/nonexistent/stats.db"),
        quiesce_timeout_s=_SHORT_TIMEOUT_S,
        quiesce_poll_interval_s=_SHORT_POLL_S,
    )

    # A background writer keeps appending for as long as quiesce() polls,
    # so the audit journal position never stabilises within the timeout.
    import threading

    stop = threading.Event()

    def _keep_writing() -> None:
        with audit_log_file.open("a") as fh:
            while not stop.is_set():
                fh.write("x")
                fh.flush()
                stop.wait(_SHORT_POLL_S / 2)

    writer = threading.Thread(target=_keep_writing, daemon=True)
    writer.start()
    try:
        with pytest.raises(OrchestratorTimeoutError) as exc_info:
            orchestrator.quiesce(idle_ms=20)
    finally:
        stop.set()
        writer.join(timeout=1.0)

    assert "audit journal" in exc_info.value.detail or "stats" in exc_info.value.detail


def test_quiesce_blocks_until_all_three_conditions_hold_simultaneously() -> None:
    """The core positive case: drivers un-acked, a Collector still busy,
    and the audit/stats stores static (vacuously stable from the first
    poll). ``quiesce()`` must not return until *both* the driver check and
    the Collector have flipped to their satisfied state -- and must have
    polled each of them more than once to observe that flip."""
    ack_check = CountingAckCheck(flip_after=3)
    collector = FakeCollector(idle=False)

    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=RecordingLauncher(),
        collectors=CollectorSet([collector]),
        driver_ack_check=ack_check,
        audit_log_file=Path("/nonexistent/audit.log"),
        stats_db_file=Path("/nonexistent/stats.db"),
        quiesce_timeout_s=2.0,
        quiesce_poll_interval_s=_SHORT_POLL_S,
    )

    # Flip the Collector idle a few polls after the driver-ack check would
    # have already been satisfied, so neither condition alone is
    # sufficient -- quiesce() must wait for the later of the two.
    import threading

    def _flip_collector_idle_soon() -> None:
        # Let a handful of polls observe collector.idle == False first.
        while collector.idle_calls < 3:
            pass
        collector.idle = True

    flipper = threading.Thread(target=_flip_collector_idle_soon, daemon=True)
    flipper.start()
    try:
        orchestrator.quiesce(idle_ms=20)
    finally:
        flipper.join(timeout=1.0)

    # quiesce() only returned after both conditions had flipped true.
    assert ack_check.calls > 3
    assert collector.idle_calls >= 3
    assert collector.idle is True


def test_quiesce_returns_promptly_once_all_three_conditions_already_hold() -> None:
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=RecordingLauncher(),
        collectors=CollectorSet([FakeCollector(idle=True)]),
        driver_ack_check=lambda: True,
        audit_log_file=Path("/nonexistent/audit.log"),
        stats_db_file=Path("/nonexistent/stats.db"),
        quiesce_timeout_s=2.0,
        quiesce_poll_interval_s=_SHORT_POLL_S,
    )

    orchestrator.quiesce(idle_ms=20)  # must not raise


# ---------------------------------------------------------------------------
# A timed-out Readiness_Gate probe raises OrchestratorTimeoutError naming
# the specific probe (Requirement 8.10)
# ---------------------------------------------------------------------------


def test_start_all_raises_orchestrator_timeout_error_naming_the_timed_out_probe() -> (
    None
):
    launcher = RecordingLauncher()
    names = _all_process_names()
    probes = _no_op_probes()

    # The fifth process's probe genuinely times out -- it polls a predicate
    # that never becomes true, bounded by a short, test-only timeout, using
    # the same _poll_readiness helper the real store-artifact probes use,
    # rather than raising ReadinessProbeError instantly.
    timed_out_process = names[4]

    def _never_ready(spec: ProcessSpec, handle: ManagedProcess) -> None:
        orch._poll_readiness(
            spec,
            handle,
            lambda: False,
            what="a condition that never becomes true",
            timeout_s=_SHORT_TIMEOUT_S,
            poll_interval_s=_SHORT_POLL_S,
        )

    probes[timed_out_process] = _never_ready

    orchestrator = _orchestrator_ready_to_start(
        process_launcher=launcher, readiness_probes=probes
    )

    with pytest.raises(OrchestratorTimeoutError) as exc_info:
        orchestrator.start_all()

    assert timed_out_process in exc_info.value.what
    assert isinstance(exc_info.value.__cause__, ReadinessProbeError)
    assert exc_info.value.__cause__.process_name == timed_out_process
    # Every process up to and including the failing one was launched; no
    # process after it was.
    assert launcher.launched == names[:5]


def test_start_all_raises_orchestrator_timeout_error_naming_a_collector_attachment_failure() -> (
    None
):
    """Requirement 8.10 also covers a Collector-attachment failure, not
    only a Readiness_Gate probe -- both are re-wrapped into the same
    OrchestratorTimeoutError type."""

    class _FailingAttachCollector:
        def attach(self) -> None:
            raise RuntimeError("could not subscribe to the engine bus")

        def is_idle(self, idle_ms: int) -> bool:
            return True

        def capture_file(self) -> Path | None:
            return None

    launcher = RecordingLauncher()
    orchestrator = Orchestrator(
        mode="dev",
        process_launcher=launcher,
        store_reinitialiser=lambda: None,
        readiness_probes=_no_op_probes(),
        collectors=CollectorSet([_FailingAttachCollector()]),
    )
    orchestrator.prepare()

    with pytest.raises(OrchestratorTimeoutError) as exc_info:
        orchestrator.start_all()

    assert exc_info.value.what == "Collector attachment"
    # Every process still launched -- attach_all() runs only after every
    # process has passed its own readiness probe.
    assert launcher.launched == _all_process_names()
