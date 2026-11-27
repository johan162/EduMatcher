"""Evidence snapshots: what a report is about, pinned before anything reads it.

A *collection* is an operator-configured directory holding an audit trail
(``audit.log``, its closed day parts and archives under ``audit/``). The
browser names it by id, never by path (design §7.2).

``create_snapshot`` pins a collection as it is now:

* every file's size and SHA-256. A closed part or archive is retained as
  it is; the active ``audit.log`` is still being written, so its complete
  lines are copied into the snapshot and its partial last line, if any, is
  reported (``torn_bytes``) and left out;
* the records' receipt-time extent, the engine runs (each
  ``system.startup``) and every capability's state (``capabilities``).

The id is derived from that content, so pinning an unchanged trail again
gives the same snapshot. ``open_snapshot`` reads through a snapshot: the
pinned copy of the active file, and the retained files after checking they
still have the pinned size and hash. Appending to the trail never changes
what a snapshot reads; changing or removing a retained file makes it
unavailable rather than silently different.

Descriptors and pinned copies live in a derivative store (one directory per
snapshot). Sources are only ever read, through the audit trail's own parsers
(``audit_files``, ``iter_entries``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.rawlines import STARTUP, audit_files
from edumatcher.models.generated.auction import (
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
)
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT, PREFIX_DEPTH
from edumatcher.models.generated.order import TOPIC_ORDER_NEW
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.audit.service.capabilities import (
    Capability,
    CapabilityState,
    Evidence,
    Reason,
    evaluate,
)

#: A snapshot id: ``s-`` and 20 hex digits of the content hash.
_SNAPSHOT_ID = re.compile(r"^s-[0-9a-f]{20}$")
_CHUNK = 1 << 20
#: The pinned copy of the active file, inside the snapshot's directory.
_PINNED = "active.log"
_DESCRIPTOR = "descriptor.json"
#: Topics whose payload names a symbol's price, and so its tick scale.
_PRICED = (
    TOPIC_TRADE_EXECUTED,
    PREFIX_BOOK_SNAPSHOT,
    PREFIX_DEPTH,
    TOPIC_ORDER_NEW,
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
)
#: Recorded book observations.
_BOOK = (PREFIX_BOOK_SNAPSHOT, PREFIX_DEPTH)


@dataclass(frozen=True)
class AuditCollection:
    """An operator-configured evidence collection: an id and its directory."""

    id: str
    path: Path


@dataclass(frozen=True)
class SourceFile:
    """One audit file as pinned. ``name`` is relative to the collection;
    ``kind`` is ``active``, ``part`` or ``archive``. ``cutoff`` is how many
    bytes the snapshot reads, and ``sha256`` their hash: the whole file for
    a retained one, the complete lines for the active one (``torn_bytes`` is
    what followed the last newline)."""

    name: str
    kind: str
    size: int
    cutoff: int
    sha256: str

    @property
    def torn_bytes(self) -> int:
        return self.size - self.cutoff


@dataclass(frozen=True)
class RunInfo:
    """One engine run: its ``system.startup``."""

    run_seq: int | None
    started_ts: str
    #: The hash of the configuration it announced; None when it carried none.
    config_sha256: str | None


@dataclass(frozen=True)
class SnapshotDescriptor:
    snapshot_id: str
    collection_id: str
    #: The collection directory the retained files are read from.
    source_root: str
    created_at: str
    files: tuple[SourceFile, ...]
    entries: int
    #: Receipt time (pm-audit's stamp) of the first and last record.
    first_ts: str | None
    last_ts: str | None
    runs: tuple[RunInfo, ...]
    capabilities: dict[Capability, CapabilityState]


class SnapshotUnavailable(Exception):
    """The snapshot (or its collection) cannot be read; ``reason`` says why."""

    def __init__(self, reason: Reason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class Snapshot:
    """An opened snapshot: its descriptor, and its records on demand."""

    def __init__(self, descriptor: SnapshotDescriptor, directory: Path) -> None:
        self.descriptor = descriptor
        self._dir = directory

    @property
    def directory(self) -> Path:
        """The snapshot's own directory in the store, for its derivatives."""
        return self._dir

    def paths(self) -> list[Path]:
        """The files the snapshot reads, oldest first: retained files where
        they are, the active one as pinned."""
        root = Path(self.descriptor.source_root)
        return [
            self._dir / _PINNED if f.kind == "active" else root / f.name
            for f in self.descriptor.files
        ]

    def entries(self) -> Iterator[AuditEntry]:
        """The pinned records, oldest first, each naming its source file
        (relative to the collection) and line. Raises
        :class:`SnapshotUnavailable` if a retained file changed or went."""
        paths = self.paths()
        names: dict[str, str] = {}
        for f, path in zip(self.descriptor.files, paths, strict=True):
            if f.kind != "active":
                _check_retained(path, f)
            names[str(path)] = f.name
        for entry in iter_entries(paths):
            entry.file = names.get(entry.file or "", entry.file)
            yield entry


def create_snapshot(collection: AuditCollection, store: Path) -> SnapshotDescriptor:
    """Pin *collection* as it is now (see the module doc); the descriptor of
    an identical earlier snapshot when there is one."""
    root = collection.path
    if not root.is_dir():
        raise SnapshotUnavailable(
            Reason.SOURCE_MISSING, f"collection {collection.id}: {root} does not exist"
        )
    snapshots = store / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".new-", dir=snapshots))
    try:
        files = tuple(_pin(path, root, work / _PINNED) for path in audit_files(root))
        material = json.dumps(
            [collection.id, str(root), [(f.name, f.kind, f.cutoff, f.sha256) for f in files]]  # fmt: skip
        )
        snapshot_id = "s-" + hashlib.sha256(material.encode()).hexdigest()[:20]
        final = snapshots / snapshot_id
        if (final / _DESCRIPTOR).is_file():
            return _load(final)
        descriptor = _describe(snapshot_id, collection, files, work)
        (work / _DESCRIPTOR).write_text(_dump(descriptor), encoding="utf-8")
        try:
            os.replace(work, final)
        except OSError:
            if not (final / _DESCRIPTOR).is_file():
                raise
            return _load(final)  # pinned by a concurrent caller meanwhile
        return descriptor
    finally:
        shutil.rmtree(work, ignore_errors=True)


def open_snapshot(store: Path, snapshot_id: str) -> Snapshot:
    """The snapshot *snapshot_id*; :class:`SnapshotUnavailable`
    (``UNKNOWN_SNAPSHOT``) when there is none."""
    directory = store / "snapshots" / snapshot_id
    if not _SNAPSHOT_ID.fullmatch(snapshot_id) or not (directory / _DESCRIPTOR).is_file():  # fmt: skip
        raise SnapshotUnavailable(
            Reason.UNKNOWN_SNAPSHOT, f"no snapshot {snapshot_id!r}"
        )
    return Snapshot(_load(directory), directory)


def _pin(path: Path, root: Path, copy_to: Path) -> SourceFile:
    """Hash *path*; the active file's complete lines are also copied."""
    name = path.relative_to(root).as_posix()
    if name == "audit.log":
        size, cutoff, sha = _copy_complete_lines(path, copy_to)
        return SourceFile(name, "active", size, cutoff, sha)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    kind = "archive" if path.suffix == ".zst" else "part"
    return SourceFile(name, kind, size, size, digest.hexdigest())


def _copy_complete_lines(path: Path, dest: Path) -> tuple[int, int, str]:
    """Copy *path* up to and including its last newline; (size, cutoff, sha)."""
    digest = hashlib.sha256()
    size = cutoff = 0
    pending = b""
    with path.open("rb") as src, dest.open("wb") as out:
        while chunk := src.read(_CHUNK):
            size += len(chunk)
            pending += chunk
            end = pending.rfind(b"\n") + 1
            if end:
                digest.update(pending[:end])
                out.write(pending[:end])
                cutoff += end
                pending = pending[end:]
    return size, cutoff, digest.hexdigest()


def _check_retained(path: Path, pinned: SourceFile) -> None:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise SnapshotUnavailable(
            Reason.SOURCE_MISSING, f"{pinned.name} was removed after the snapshot"
        ) from None
    digest = hashlib.sha256()
    if size == pinned.size:
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                digest.update(chunk)
    if size != pinned.size or digest.hexdigest() != pinned.sha256:
        raise SnapshotUnavailable(
            Reason.SOURCE_CHANGED,
            f"{pinned.name} changed after the snapshot (pinned {pinned.size} "
            f"bytes, sha256 {pinned.sha256[:12]}...)",
        )


def _describe(
    snapshot_id: str,
    collection: AuditCollection,
    files: tuple[SourceFile, ...],
    work: Path,
) -> SnapshotDescriptor:
    """One pass over the pinned records."""
    root = collection.path
    paths = [work / _PINNED if f.kind == "active" else root / f.name for f in files]
    count = with_envelope = books = 0
    first_ts = last_ts = first_topic = None
    runs: list[RunInfo] = []
    priced: set[str] = set()
    scaled: set[str] = set()
    for e in iter_entries(paths):
        count += 1
        if first_ts is None:
            first_ts, first_topic = e.timestamp, e.topic
        last_ts = e.timestamp
        with_envelope += e.msg_id is not None
        books += e.topic.startswith(_BOOK)
        if e.topic == STARTUP:
            config = e.payload.get("config")
            sha = e.payload.get("config_sha256")
            seq = e.payload.get("run_seq")
            runs.append(
                RunInfo(
                    seq if isinstance(seq, int) else None,
                    e.timestamp,
                    str(sha) if config and sha else None,
                )
            )
        if e.topic.startswith(_PRICED) and isinstance(e.payload.get("symbol"), str):
            priced.add(e.payload["symbol"])
            if isinstance(e.payload.get("tick_decimals"), int):
                scaled.add(e.payload["symbol"])
    evidence = Evidence(
        entries=count,
        first_topic=first_topic,
        with_envelope=with_envelope,
        book_observations=books,
        priced_symbols=frozenset(priced),
        unscaled_symbols=frozenset(priced - scaled),
        runs_without_config=tuple(
            (r.run_seq, r.started_ts) for r in runs if r.config_sha256 is None
        ),
    )
    return SnapshotDescriptor(
        snapshot_id=snapshot_id,
        collection_id=collection.id,
        source_root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        files=files,
        entries=count,
        first_ts=first_ts,
        last_ts=last_ts,
        runs=tuple(runs),
        capabilities=evaluate(evidence),
    )


def _dump(d: SnapshotDescriptor) -> str:
    raw: dict[str, Any] = asdict(d)
    raw["capabilities"] = {
        cap.value: {
            "available": s.available,
            "reason": s.reason.value if s.reason else None,
            "detail": s.detail,
        }
        for cap, s in d.capabilities.items()
    }
    return json.dumps(raw, indent=2)


def _load(directory: Path) -> SnapshotDescriptor:
    raw = json.loads((directory / _DESCRIPTOR).read_text(encoding="utf-8"))
    return SnapshotDescriptor(
        snapshot_id=raw["snapshot_id"],
        collection_id=raw["collection_id"],
        source_root=raw["source_root"],
        created_at=raw["created_at"],
        files=tuple(SourceFile(**f) for f in raw["files"]),
        entries=raw["entries"],
        first_ts=raw["first_ts"],
        last_ts=raw["last_ts"],
        runs=tuple(RunInfo(**r) for r in raw["runs"]),
        capabilities={
            Capability(cap): CapabilityState(
                s["available"],
                Reason(s["reason"]) if s["reason"] else None,
                s["detail"],
            )
            for cap, s in raw["capabilities"].items()
        },
    )
