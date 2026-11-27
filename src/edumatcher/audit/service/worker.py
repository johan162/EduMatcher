"""The Audit GUI's worker process (workplan AG9, design §7.3).

``python -m edumatcher.audit.service.worker STORE``: one process per
deployment, started by the API (:class:`session.WorkerLauncher`), running one
job at a time from the job store in ``STORE/jobs.db``:

``prepare``
    build the snapshot's read models into scratch and publish them as its
    next generation (``options.force`` rebuilds a published snapshot);
``verify``
    check the pinned files and the manifest against the sources now;
``forensics_import``
    check the ``pm-sim-forensics`` report now beside the collection against
    the snapshot (a report is attached by pinning it, AG4).

Limits: a time limit per job, an address-space limit for the process, and
a free-disk floor before a build. A job stops at its next progress report
when cancelled or out of time; its scratch directory is removed on every
ending, and nothing is published unless the build completed. The worker
beats every second while it runs a job, and exits when its parent goes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from edumatcher.audit.service import forensics, generations
from edumatcher.audit.service.build import build_generation
from edumatcher.audit.service.jobs import (
    CANCELLED,
    CANCELLED_BY_USER,
    DISK_LOW,
    FAILED,
    FORENSICS_IMPORT,
    JOB_ERROR,
    PREPARE,
    SUCCEEDED,
    TIMEOUT,
    UNAVAILABLE,
    VERIFY,
    Job,
    JobStore,
)
from edumatcher.audit.service.snapshot import (
    SnapshotUnavailable,
    open_snapshot,
    verify_snapshot,
)

#: Default limits (the design's reference: 4 GiB, an hour, 512 MiB free).
JOB_TIMEOUT_S = 3600.0
MEMORY_MB = 4096
MIN_FREE_MB = 512
HEARTBEAT_S = 1.0
POLL_S = 0.5
#: A testing aid: seconds a job waits (still cancellable) before its work,
#: so a test can cancel it or kill the worker mid-job.
STALL_ENV = "EDUMATCHER_AUDIT_WORKER_STALL"
_SCRATCH = "scratch"


class _Stop(Exception):
    def __init__(self, state: str, reason: str) -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason


class _Context:
    """Progress reporting, and the job's one chance to stop."""

    def __init__(self, jobs: JobStore, job: Job, deadline: float) -> None:
        self.jobs = jobs
        self.job = job
        self.deadline = deadline

    def report(self, stage: str, done: int | None, total: int | None) -> None:
        if self.jobs.cancel_requested(self.job.job_id):
            raise _Stop(CANCELLED, CANCELLED_BY_USER)
        if time.monotonic() > self.deadline:
            raise _Stop(FAILED, TIMEOUT)
        self.jobs.progress(self.job.job_id, stage, done, total)


def run_job(
    store: Path,
    jobs: JobStore,
    job: Job,
    *,
    timeout_s: float = JOB_TIMEOUT_S,
    min_free_mb: int = MIN_FREE_MB,
) -> None:
    """Run one claimed job to an ending; never raises for the job's sake."""
    scratch = store / _SCRATCH / job.job_id
    ctx = _Context(jobs, job, time.monotonic() + timeout_s)
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        stall = float(os.environ.get(STALL_ENV) or 0)
        until = time.monotonic() + stall
        while time.monotonic() < until:
            ctx.report("waiting", None, None)
            time.sleep(0.05)
        if shutil.disk_usage(store).free < min_free_mb * 1024 * 1024:
            jobs.finish(job.job_id, UNAVAILABLE, reason=DISK_LOW, detail=f"less than {min_free_mb} MiB free in the store")  # fmt: skip
            return
        if job.kind == PREPARE:
            result = _prepare(store, job, ctx, scratch)
        elif job.kind == VERIFY:
            result = verify_snapshot(open_snapshot(store, job.snapshot_id), ctx.report)
        elif job.kind == FORENSICS_IMPORT:
            outcome = _forensics_import(store, job)
            if outcome is None:
                jobs.finish(
                    job.job_id,
                    UNAVAILABLE,
                    reason="NOT_ATTACHED",
                    detail="no pm-sim-forensics report beside the collection",
                )
                return
            result = outcome
        else:  # the store refuses unknown kinds; a newer store's kind
            jobs.finish(job.job_id, FAILED, reason=JOB_ERROR, detail=f"unknown kind {job.kind!r}")  # fmt: skip
            return
        jobs.finish(job.job_id, SUCCEEDED, result=result)
    except _Stop as stop:
        jobs.finish(job.job_id, stop.state, reason=stop.reason)
    except SnapshotUnavailable as exc:
        jobs.finish(job.job_id, UNAVAILABLE, reason=exc.reason.value, detail=str(exc))
    except Exception as exc:  # a failed build is a job outcome, not a crash
        jobs.finish(job.job_id, FAILED, reason=JOB_ERROR, detail=f"{type(exc).__name__}: {exc}")  # fmt: skip
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _prepare(store: Path, job: Job, ctx: _Context, scratch: Path) -> dict[str, Any]:
    snapshot = open_snapshot(store, job.snapshot_id)
    published = generations.current(snapshot.directory)
    if published is not None and not job.options.get("force"):
        return {"generation": published, "reused": True}
    built = scratch / "generation"
    meta = build_generation(snapshot, built, ctx.report)
    ctx.report("publishing", None, None)
    generation = generations.publish(snapshot.directory, built)
    return {"generation": generation, "reused": False, **meta}


def _forensics_import(store: Path, job: Job) -> dict[str, Any] | None:
    snapshot = open_snapshot(store, job.snapshot_id)
    d = snapshot.descriptor
    pinned = {f.name: (f.cutoff, f.sha256) for f in d.files}
    found = forensics.attach(Path(d.source_root), pinned, None)
    if found is None:
        return None
    pin = found.pin
    return {
        "sha256": found.sha256,
        "available": found.state.available,
        "reason": found.state.reason.value if found.state.reason else None,
        "detail": found.state.detail,
        "inputs_match": pin.inputs_match if pin else False,
        "differing": list(pin.differing) if pin else [],
        "statuses": pin.statuses if pin else None,
        "pinned_sha256": d.forensics.sha256 if d.forensics else None,
    }


def run_pending(store: Path, **limits: Any) -> int:
    """Run every queued job here, in this process (tests, and tools that
    have no worker); the number run."""
    jobs = JobStore(store / "jobs.db")
    count = 0
    while (job := jobs.claim(os.getpid())) is not None:
        run_job(store, jobs, job, **limits)
        count += 1
    return count


def _beat(jobs: JobStore, job_id: str, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_S):
        jobs.heartbeat(job_id)


def _limit_memory(megabytes: int) -> None:
    try:
        import resource
    except ImportError:  # not POSIX
        return
    limit = megabytes * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def serve(
    store: Path,
    *,
    timeout_s: float,
    min_free_mb: int,
    poll_s: float = POLL_S,
    parent_alive: Callable[[], bool],
) -> None:
    """Claim and run jobs one at a time until the parent goes."""
    jobs = JobStore(store / "jobs.db")
    while parent_alive():
        job = jobs.claim(os.getpid())
        if job is None:
            time.sleep(poll_s)
            continue
        stop = threading.Event()
        beat = threading.Thread(
            target=_beat, args=(jobs, job.job_id, stop), daemon=True
        )
        beat.start()
        try:
            run_job(store, jobs, job, timeout_s=timeout_s, min_free_mb=min_free_mb)
        finally:
            stop.set()
            beat.join()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="edumatcher.audit.service.worker",
        description="The Audit GUI's job worker (started by pm-api-gwy).",
    )
    parser.add_argument("store", type=Path, help="The audit GUI derivative store")
    parser.add_argument("--job-timeout", type=float, default=JOB_TIMEOUT_S, help="Seconds per job")  # fmt: skip
    parser.add_argument(
        "--memory-mb", type=int, default=MEMORY_MB, help="Address-space limit"
    )
    parser.add_argument("--min-free-mb", type=int, default=MIN_FREE_MB, help="Free disk a job needs")  # fmt: skip
    args = parser.parse_args(argv)
    _limit_memory(args.memory_mb)
    parent = os.getppid()
    serve(
        args.store,
        timeout_s=args.job_timeout,
        min_free_mb=args.min_free_mb,
        parent_alive=lambda: os.getppid() == parent,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
