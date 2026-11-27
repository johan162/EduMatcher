"""The Audit GUI's read service: collections, snapshots, jobs, and reads of a
snapshot's prepared read models, as the ``/api/v1/audit`` routes need them.

The API process never reconstructs (workplan AG9, design §7.3): a snapshot is
read only through a *generation* the worker built (:mod:`build`) and
published (:mod:`generations`). Pinning a snapshot queues its ``prepare``
job; until a generation exists every read is :class:`NotPrepared`, naming
that job. A reader resolves one generation and stays on it, so a page, a
cursor or a story never moves onto a rebuild; a cursor into a generation
that has since been removed is :class:`GenerationExpired`.

The one worker process is started and watched from here
(:class:`WorkerLauncher`). A job whose worker died is failed with
``WORKER_LOST`` on the next job read, and its scratch directory removed.

Nothing here knows HTTP. Failures are typed exceptions the router maps to
statuses: :class:`SnapshotUnavailable`, :class:`UnknownCollection`,
:class:`UnknownEntity`, :class:`AmbiguousRun`,
:class:`CapabilityUnavailable`, :class:`EmptyWindow`, :class:`NotPrepared`,
:class:`GenerationExpired`, :class:`UnknownJob`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import zlib
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from edumatcher.audit.rawlines import audit_files
from edumatcher.audit.replay import episodes as replay_episodes
from edumatcher.audit.replay import index as episode_index
from edumatcher.audit.replay import reader, render_json
from edumatcher.audit.replay.anomalies import SEVERITY_INFO
from edumatcher.audit.replay.render_text import Options
from edumatcher.audit.replay.views import at_least
from edumatcher.audit.service import forensics, generations
from edumatcher.audit.service.capabilities import Capability, Reason
from edumatcher.audit.service.errors import (
    CapabilityUnavailable,
    EmptyWindow,
    UnknownEntity,
)
from edumatcher.audit.service.findings import BEHAVIOUR, lane_of
from edumatcher.audit.service.jobs import (
    PREPARE,
    SUCCEEDED,
    Job,
    JobStore,
)
from edumatcher.audit.service.market import MarketModel
from edumatcher.audit.service.rows import ns_as_strings
from edumatcher.audit.service.snapshot import (
    AuditCollection,
    SnapshotDescriptor,
    SnapshotUnavailable,
    create_snapshot,
    open_snapshot,
)

#: Story entity kinds the routes accept -> the replay's episode kinds.
ENTITY_KINDS: Mapping[str, str] = {
    "order": replay_episodes.KIND_ORDER,
    "trade": replay_episodes.KIND_TRADE,
    "quote": replay_episodes.KIND_QUOTE,
    "oco": replay_episodes.KIND_OCO,
    "combo": replay_episodes.KIND_COMBO,
    "command": replay_episodes.KIND_COMMAND,
}

#: Seconds without a heartbeat after which a running job's worker is presumed
#: dead (the worker beats every second).
STALE_AFTER = 10.0
#: Generation views kept open: the current one and one a cursor still pages.
_VIEWS = 4
_JOBS_DB = "jobs.db"
_SCRATCH = "scratch"


class UnknownCollection(LookupError):
    """No configured collection has this id."""


class UnknownJob(LookupError):
    """No job has this id."""


class AmbiguousRun(Exception):
    """The entity appears in more than one engine run; name one (``runs``
    are publisher runs, as ``/events`` reports them)."""

    def __init__(self, runs: list[int]) -> None:
        super().__init__(
            f"the id appears in runs {', '.join(map(str, runs))}: pass run_id"
        )
        self.runs = runs


class NotPrepared(Exception):
    """The snapshot has no read models yet; `job` builds them."""

    def __init__(self, job: Job) -> None:
        super().__init__(
            f"snapshot {job.snapshot_id} is being prepared (job {job.job_id}, "
            f"{job.state}); read it once the job has succeeded"
        )
        self.job = job


class GenerationExpired(Exception):
    """A cursor's generation has been replaced and removed."""

    def __init__(self, snapshot_id: str, generation: int, current: int | None) -> None:
        super().__init__(
            f"generation {generation} of {snapshot_id} was replaced (now "
            f"{current}) and removed; start the listing again"
        )
        self.generation = generation
        self.current = current


class EventFilter:
    """``/events`` filters; all optional, combined with AND."""

    def __init__(
        self,
        topic: str | None = None,
        symbol: str | None = None,
        gateway: str | None = None,
        order_id: str | None = None,
    ) -> None:
        self.topic = topic
        self.symbol = symbol
        self.gateway = gateway
        self.order_id = order_id

    def digest(self) -> str:
        """Identifies the filter in a cursor, so a cursor cannot be reused
        under different filters."""
        raw = json.dumps([self.topic, self.symbol, self.gateway, self.order_id])
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def where(self, start: int) -> tuple[str, list[Any]]:
        """The SQL condition over ``events`` (build.py's columns)."""
        clauses: list[str] = ["pos >= ?"]
        args: list[Any] = [start]
        if self.topic:
            clauses.append("substr(topic, 1, ?) = ?")
            args += [len(self.topic), self.topic]
        if self.symbol:
            clauses.append("symbol = ?")
            args.append(self.symbol)
        if self.gateway:
            clauses.append("(actor = ? OR gateway = ?)")
            args += [self.gateway, self.gateway]
        if self.order_id:
            clauses.append("pos IN (SELECT pos FROM event_orders WHERE order_id = ?)")
            args.append(self.order_id)
        return " AND ".join(clauses), args


class GenerationView:
    """Reads of one published generation of one snapshot."""

    def __init__(
        self, descriptor: SnapshotDescriptor, snapshot_dir: Path, generation: int
    ) -> None:
        self.descriptor = descriptor
        self.generation = generation
        self._snapshot_dir = snapshot_dir
        self._dir = generations.path(snapshot_dir, generation)
        self._findings: list[dict[str, Any]] | None = None
        self._market: MarketModel | None = None
        self._lock = threading.Lock()

    # -- events ---------------------------------------------------------

    def events(
        self, flt: EventFilter, start: int, limit: int
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Up to *limit* matching rows from position *start*, and the
        position to continue from (None when none follow)."""
        where, args = flt.where(start)
        with closing(_readonly(self._dir / "events.db")) as conn:
            rows = conn.execute(
                f"SELECT pos, row FROM events WHERE {where} ORDER BY pos LIMIT ?",
                [*args, limit + 1],
            ).fetchall()
        resume = rows[limit][0] if len(rows) > limit else None
        return [json.loads(zlib.decompress(r)) for _, r in rows[:limit]], resume

    # -- stories --------------------------------------------------------

    def story(
        self, entity_kind: str, entity_id: str, run_id: int | None, depth: int
    ) -> dict[str, list[dict[str, Any]]]:
        """The entity's episodes and everything within *depth* links, as the
        replay's JSON objects, never crossing into another engine run."""
        self._require(Capability.STORIES)
        with closing(episode_index.open_readonly(self._dir / "replay.db")) as conn:
            seeds = reader.episodes_by_anchor(
                conn, ENTITY_KINDS[entity_kind], entity_id
            )
            runs = sorted({_run_of(e) for e in seeds})
            if run_id is not None:
                seeds = [e for e in seeds if _run_of(e) == run_id]
            elif len(runs) > 1:
                raise AmbiguousRun(runs)
            if not seeds:
                raise UnknownEntity(f"no {entity_kind} {entity_id!r} in this snapshot")
            run = _run_of(seeds[0])
            walked = [
                e for e in reader.walk(conn, seeds, depth=depth) if _run_of(e) == run
            ]
            objects = render_json.objects(walked, reader.actors(conn), Options())
        out: dict[str, list[dict[str, Any]]] = {
            "episodes": [],
            "beats": [],
            "links": [],
            "anomalies": [],
        }
        for obj in objects:
            kind = obj.pop("type")
            if kind == render_json.TYPE_BEAT:
                obj["fields"] = ns_as_strings(obj["fields"])
            out[f"{kind}s" if kind != "anomaly" else "anomalies"].append(obj)
        runs_by_id = {e.episode_id: _run_of(e) for e in walked}
        for episode in out["episodes"]:
            episode["run"] = runs_by_id[episode["id"]]
        for anomaly in out["anomalies"]:
            anomaly["lane"] = lane_of(anomaly["code"])
        return out

    # -- findings -------------------------------------------------------

    def findings(self) -> list[dict[str, Any]]:
        """Every replay finding (worst first, then by time) and, when a
        matching pm-sim-forensics report is attached, its failed, broken and
        skipped checks after the replay's of the same severity; each row in
        its lane."""
        self._require(Capability.STORIES)
        with self._lock:
            if self._findings is None:
                with closing(
                    episode_index.open_readonly(self._dir / "replay.db")
                ) as conn:
                    episodes = reader.episodes_in_window(conn)
                rows = []
                for obj in render_json.anomalies(episodes, severity=SEVERITY_INFO):
                    obj.pop("type", None)
                    obj.pop("story", None)
                    obj["lane"] = lane_of(obj["code"])
                    obj["origin"] = "replay"
                    rows.append(obj)
                if self.descriptor.capabilities[Capability.FORENSICS].available:
                    rows += forensics.findings(self._snapshot_dir)
                rows.sort(key=lambda row: at_least(row["severity"]))
                self._findings = rows
            return self._findings

    # -- market ---------------------------------------------------------

    def heatmap(
        self, symbol: str, start: int | None, end: int | None, bins: int
    ) -> dict[str, Any]:
        """*symbol*'s depth heatmap (:meth:`MarketModel.heatmap`)."""
        self._require(Capability.BOOK)
        return dict(
            ns_as_strings(self._market_model().heatmap(symbol, start, end, bins))
        )

    def lifelines(
        self, symbol: str, start: int | None, end: int | None, gateway: str | None
    ) -> dict[str, Any]:
        """*symbol*'s order lifelines (:meth:`MarketModel.lifelines`)."""
        return dict(
            ns_as_strings(self._market_model().lifelines(symbol, start, end, gateway))
        )

    # -- internals ------------------------------------------------------

    def _market_model(self) -> MarketModel:
        with self._lock:
            if self._market is None:
                self._market = MarketModel.load(self._dir / "market.db")
            return self._market

    def _require(self, capability: Capability) -> None:
        state = self.descriptor.capabilities[capability]
        if not state.available and state.reason is not None:
            raise CapabilityUnavailable(state.reason, state.detail)


class WorkerLauncher:
    """Starts the one worker process (``python -m
    edumatcher.audit.service.worker STORE``) and tells whether it lives."""

    def __init__(self, store: Path, args: Iterable[str] = ()) -> None:
        self.store = store
        self.args = list(args)
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    def ensure(self) -> None:
        """Start the worker unless it runs."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return
            self._proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "edumatcher.audit.service.worker",
                    str(self.store),
                    *self.args,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )

    def alive(self, pid: int) -> bool:
        if self._proc is not None and pid == self._proc.pid:
            return self._proc.poll() is None  # also reaps a killed child
        return _pid_alive(pid)

    def stop(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait(timeout=10)
            self._proc = None


class AuditService:
    """The configured collections, the derivative store, the job store, and
    open views of prepared generations."""

    def __init__(
        self,
        collections: Iterable[AuditCollection],
        store: Path,
        launcher: WorkerLauncher | None = None,
    ) -> None:
        self.collections = {c.id: c for c in collections}
        self.store = store
        self.jobs = JobStore(store / _JOBS_DB)
        self.launcher = launcher
        self._lock = threading.Lock()
        self._views: OrderedDict[tuple[str, int], GenerationView] = OrderedDict()
        #: Retained files hashed since they last changed: (path, size, mtime_ns).
        self._verified: set[tuple[str, int, int]] = set()

    def collection(self, collection_id: str) -> AuditCollection:
        try:
            return self.collections[collection_id]
        except KeyError:
            raise UnknownCollection(f"no collection {collection_id!r}") from None

    @staticmethod
    def availability(collection: AuditCollection) -> tuple[bool, Reason | None, int]:
        """Whether *collection* can be read now, why not, and its file count."""
        if not collection.path.is_dir():
            return False, Reason.SOURCE_MISSING, 0
        return True, None, len(audit_files(collection.path))

    # -- snapshots ------------------------------------------------------

    def create(self, collection_id: str) -> tuple[SnapshotDescriptor, Job | None]:
        """Pin the collection; queue its ``prepare`` unless one is published."""
        descriptor = create_snapshot(self.collection(collection_id), self.store)
        return descriptor, self.prepare_job(descriptor.snapshot_id)

    def descriptor(self, snapshot_id: str) -> SnapshotDescriptor:
        return open_snapshot(self.store, snapshot_id).descriptor

    def generation(self, snapshot_id: str) -> int | None:
        """The snapshot's published generation, or None."""
        return generations.current(open_snapshot(self.store, snapshot_id).directory)

    def prepare_job(self, snapshot_id: str) -> Job | None:
        """None when a generation is published; else the active (or a new)
        ``prepare`` job."""
        if self.generation(snapshot_id) is not None:
            return None
        job, _ = self.submit(PREPARE, snapshot_id, {})
        return job

    def view(self, snapshot_id: str, generation: int | None = None) -> GenerationView:
        """A read view: of `generation`, or of the current one."""
        snapshot = open_snapshot(self.store, snapshot_id)
        # The read models are derived from the pinned evidence: a retained
        # file removed or changed since makes the snapshot unavailable, never
        # silently different (design §7.2).
        with self._lock:
            snapshot.check_sources(self._verified)
        current = generations.current(snapshot.directory)
        if current is None:
            job = self.prepare_job(snapshot_id)
            assert job is not None
            raise NotPrepared(job)
        wanted = current if generation is None else generation
        if not generations.exists(snapshot.directory, wanted):
            raise GenerationExpired(snapshot_id, wanted, current)
        key = (snapshot_id, wanted)
        with self._lock:
            view = self._views.get(key)
            if view is None:
                view = GenerationView(snapshot.descriptor, snapshot.directory, wanted)
                self._views[key] = view
                while len(self._views) > _VIEWS:
                    self._views.popitem(last=False)
            self._views.move_to_end(key)
            return view

    # -- jobs -----------------------------------------------------------

    def submit(
        self, kind: str, snapshot_id: str, options: dict[str, Any]
    ) -> tuple[Job, bool]:
        """Queue a job (the active identical one if any). A ``prepare`` that
        is not forced and finds a published generation is answered by the
        job that published it."""
        open_snapshot(self.store, snapshot_id)  # SnapshotUnavailable if unknown
        if kind == PREPARE and not options.get("force") and self.generation(snapshot_id) is not None:  # fmt: skip
            done = self.jobs.latest(PREPARE, snapshot_id, SUCCEEDED)
            if done is not None:
                return done, False
        job, created = self.jobs.submit(kind, snapshot_id, options)
        if self.launcher is not None:
            self.launcher.ensure()
        return job, created

    def job(self, job_id: str) -> Job:
        self.reconcile()
        job = self.jobs.get(job_id)
        if job is None:
            raise UnknownJob(f"no job {job_id!r}")
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs.cancel(job_id)
        if job is None:
            raise UnknownJob(f"no job {job_id!r}")
        return job

    def reconcile(self) -> list[Job]:
        """Fail jobs whose worker died; remove their scratch; restart the
        worker if jobs are waiting."""
        alive = self.launcher.alive if self.launcher is not None else _pid_alive
        lost = self.jobs.reconcile(alive, STALE_AFTER)
        for job in lost:
            shutil.rmtree(self.store / _SCRATCH / job.job_id, ignore_errors=True)
        if lost and self.launcher is not None:
            self.launcher.ensure()
        return lost


def require_behaviour_lane() -> None:
    """The behavioural lane is R2's; asking for it says so, never "none"."""
    raise CapabilityUnavailable(
        Reason.NOT_IN_RELEASE,
        f"the {BEHAVIOUR} lane needs the R2 detectors, not in this release",
    )


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_of(episode: replay_episodes.Episode) -> int:
    """The engine run an episode happened in: its first fact's publisher run
    (the restart epoch ``/events`` reports as ``run``). ``Episode.run_seq``
    is read off payloads and is unset for most orders."""
    return episode.events[0].fact.publisher_run if episode.events else 0


__all__ = [
    "AmbiguousRun",
    "AuditService",
    "CapabilityUnavailable",
    "ENTITY_KINDS",
    "EmptyWindow",
    "EventFilter",
    "GenerationExpired",
    "GenerationView",
    "NotPrepared",
    "SnapshotUnavailable",
    "UnknownCollection",
    "UnknownEntity",
    "UnknownJob",
    "WorkerLauncher",
    "require_behaviour_lane",
]
