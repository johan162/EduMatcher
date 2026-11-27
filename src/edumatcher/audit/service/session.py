"""The Audit GUI's read service: collections, snapshots and one session's
reconstruction, as the ``/api/v1/audit`` routes need them.

R0 (workplan AG2): a snapshot's session is reconstructed in this process on
first use, and kept for the most recently used snapshot only. The
reconstruction is the replay library's own (``normalise``, ``ordered``, the
state model and link resolver, the episode assembler and the detectors), and
its episodes go into the replay episode index, built once per snapshot in the
snapshot's directory, so stories and findings are read with the same reader
``pm-audit-replay story`` uses. AG9 moves the build into a worker job.

Nothing here knows HTTP. Failures are typed exceptions the router maps to
statuses: :class:`SnapshotUnavailable`, :class:`UnknownCollection`,
:class:`UnknownEntity`, :class:`AmbiguousRun`,
:class:`CapabilityUnavailable`, :class:`EmptyWindow`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from edumatcher.audit.rawlines import audit_files
from edumatcher.audit.replay import episodes as replay_episodes
from edumatcher.audit.replay import index as episode_index
from edumatcher.audit.replay import reader, render_json
from edumatcher.audit.replay.anomalies import SEVERITY_INFO
from edumatcher.audit.replay.detect import (
    DEFAULT_CLOCK_SKEW_WARN,
    Detector,
    detected,
    observed,
)
from edumatcher.audit.replay.episodes import assemble
from edumatcher.audit.replay.facts import Fact, normalise
from edumatcher.audit.replay.ordering import ordered, pack_sort_key
from edumatcher.audit.replay.pipeline import Reconstruction
from edumatcher.audit.replay.render_text import Options
from edumatcher.audit.service.capabilities import Capability, Reason
from edumatcher.audit.service.errors import (
    CapabilityUnavailable,
    EmptyWindow,
    UnknownEntity,
)
from edumatcher.audit.service.findings import BEHAVIOUR, lane_of
from edumatcher.audit.service.market import MarketModel, epoch_ns
from edumatcher.models.generated.order import TOPIC_ORDER_NEW
from edumatcher.audit.service.snapshot import (
    AuditCollection,
    Snapshot,
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

#: The detection settings the index is built with: pm-audit-replay's
#: defaults, spelled as its ``detection_key`` spells them.
_DETECTION = f"strict=0 clock_skew={DEFAULT_CLOCK_SKEW_WARN:g}"
_INDEX = "replay.db"


class UnknownCollection(LookupError):
    """No configured collection has this id."""


class AmbiguousRun(Exception):
    """The entity appears in more than one engine run; name one (``runs``
    are publisher runs, as ``/events`` reports them)."""

    def __init__(self, runs: list[int]) -> None:
        super().__init__(
            f"the id appears in runs {', '.join(map(str, runs))}: pass run_id"
        )
        self.runs = runs


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

    def matches(self, f: Fact) -> bool:
        if self.topic and not f.topic.startswith(self.topic):
            return False
        if self.symbol and f.symbol != self.symbol:
            return False
        p = f.payload
        if self.gateway and self.gateway not in (f.actor, p.get("gateway_id")):
            return False
        if self.order_id and self.order_id not in (
            p.get("order_id"),
            p.get("buy_order_id"),
            p.get("sell_order_id"),
            p.get("id") if f.kind == TOPIC_ORDER_NEW else None,
        ):
            return False
        return True


class ReplaySession:
    """One snapshot, reconstructed: its facts in canonical order and its
    episode index."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.descriptor = snapshot.descriptor
        self.facts: list[Fact] = list(ordered(normalise(snapshot.entries())))
        self._db = snapshot.directory / _INDEX
        if not self._index_is_current():
            self._build_index(snapshot)
        self._findings: list[dict[str, Any]] | None = None
        self._market: MarketModel | None = None

    # -- events ---------------------------------------------------------

    def events(
        self, flt: EventFilter, start: int, limit: int
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Up to *limit* matching facts from position *start*, and the
        position to continue from (None when none follow)."""
        rows: list[dict[str, Any]] = []
        pos = start
        while pos < len(self.facts):
            fact = self.facts[pos]
            pos += 1
            if not flt.matches(fact):
                continue
            if len(rows) == limit:
                return rows, pos - 1
            rows.append(event_row(fact))
        return rows, None

    # -- stories --------------------------------------------------------

    def story(
        self, entity_kind: str, entity_id: str, run_id: int | None, depth: int
    ) -> dict[str, list[dict[str, Any]]]:
        """The entity's episodes and everything within *depth* links, as the
        replay's JSON objects, never crossing into another engine run."""
        self._require(Capability.STORIES)
        with closing(episode_index.open_readonly(self._db)) as conn:
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
        """Every replay finding, worst first then by time, each in its lane."""
        self._require(Capability.STORIES)
        if self._findings is None:
            with closing(episode_index.open_readonly(self._db)) as conn:
                episodes = reader.episodes_in_window(conn)
            rows = []
            for obj in render_json.anomalies(episodes, severity=SEVERITY_INFO):
                obj.pop("type", None)
                obj.pop("story", None)
                obj["lane"] = lane_of(obj["code"])
                rows.append(obj)
            self._findings = rows
        return self._findings

    # -- market ---------------------------------------------------------

    def heatmap(
        self, symbol: str, start: int | None, end: int | None, bins: int
    ) -> dict[str, Any]:
        """*symbol*'s depth heatmap (:meth:`MarketModel.heatmap`)."""
        self._require(Capability.BOOK)
        return dict(ns_as_strings(self._market_model().heatmap(symbol, start, end, bins)))  # fmt: skip

    def lifelines(
        self, symbol: str, start: int | None, end: int | None, gateway: str | None
    ) -> dict[str, Any]:
        """*symbol*'s order lifelines (:meth:`MarketModel.lifelines`)."""
        return dict(
            ns_as_strings(self._market_model().lifelines(symbol, start, end, gateway))
        )

    # -- internals ------------------------------------------------------

    def _market_model(self) -> MarketModel:
        if self._market is None:
            self._market = MarketModel(self.facts)
        return self._market

    def _require(self, capability: Capability) -> None:
        state = self.descriptor.capabilities[capability]
        if not state.available and state.reason is not None:
            raise CapabilityUnavailable(state.reason, state.detail)

    def _index_is_current(self) -> bool:
        try:
            conn = episode_index.open_readonly(self._db)
        except FileNotFoundError, episode_index.StaleIndexError, sqlite3.Error:
            return False
        with closing(conn):
            return episode_index.read_meta(conn, episode_index.META_DETECTION) == _DETECTION  # fmt: skip

    def _build_index(self, snapshot: Snapshot) -> None:
        run = Reconstruction()
        detector = Detector(run.state)
        episodes = detected(
            assemble(observed(run.run(self.facts), detector), run.state, run.links),
            detector,
        )
        episode_index.build(
            self._db, episodes, run.state, snapshot.paths(), detection=_DETECTION
        )


class AuditService:
    """The configured collections, the derivative store, and the session of
    the most recently used snapshot (an LRU of one, design R0)."""

    def __init__(self, collections: Iterable[AuditCollection], store: Path) -> None:
        self.collections = {c.id: c for c in collections}
        self.store = store
        self._lock = threading.Lock()
        self._cached: ReplaySession | None = None

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

    def create(self, collection_id: str) -> SnapshotDescriptor:
        return create_snapshot(self.collection(collection_id), self.store)

    def descriptor(self, snapshot_id: str) -> SnapshotDescriptor:
        return open_snapshot(self.store, snapshot_id).descriptor

    def session(self, snapshot_id: str) -> ReplaySession:
        """The snapshot's reconstruction, built on first use. One at a time:
        a second snapshot replaces the first."""
        with self._lock:
            cached = self._cached
            if cached is not None and cached.descriptor.snapshot_id == snapshot_id:
                return cached
            self._cached = None
            session = ReplaySession(open_snapshot(self.store, snapshot_id))
            self._cached = session
            return session


def require_behaviour_lane() -> None:
    """The behavioural lane is R2's; asking for it says so, never "none"."""
    raise CapabilityUnavailable(
        Reason.NOT_IN_RELEASE,
        f"the {BEHAVIOUR} lane needs the R2 detectors, not in this release",
    )


def event_row(f: Fact) -> dict[str, Any]:
    """One fact as an ``/events`` row: canonical key, both clocks' raw values,
    every price with its scale, and where it was read."""
    return {
        "key": pack_sort_key(f).replace("\x1f", "|"),
        "run": f.publisher_run,
        "eseq": f.eseq,
        "topic_seq": f.topic_seq,
        "receipt_ts": f.receipt_raw,
        "receipt_ns": str(epoch_ns(f.receipt_ts)),
        "topic": f.topic,
        "kind": f.kind,
        "symbol": f.symbol,
        "actor": f.actor,
        "msg_id": f.msg_id,
        "causation_id": f.causation_id,
        "correlation_id": f.correlation_id,
        "late": f.late,
        "fields": ns_as_strings(f.payload),
        "prices": [
            {
                "name": p.name,
                "raw": p.raw,
                "display": p.display,
                "tick_decimals": p.tick_decimals,
            }
            for p in f.prices.values()
        ],
        "source": {"file": f.file, "line": f.line_no},
    }


def ns_as_strings(value: Any, key: str = "") -> Any:
    """*value* with every integer under a ``*_ns`` key as a decimal string:
    nanosecond epochs exceed JavaScript's exact integers (design §3.2)."""
    if isinstance(value, Mapping):
        return {k: ns_as_strings(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [ns_as_strings(v, key) for v in value]
    if key.endswith("_ns") and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


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
    "ReplaySession",
    "SnapshotUnavailable",
    "UnknownCollection",
    "UnknownEntity",
    "event_row",
    "require_behaviour_lane",
]
