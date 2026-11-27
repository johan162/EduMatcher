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
  ``system.startup``) and every capability's state (``capabilities``);
* the evidence manifest (``audit/manifest.jsonl``) as ``pm-audit-cli
  verify`` checks it: ``absent``, ``verified`` or ``failed``, with the hash
  chain and the archives' content as separate results and each problem's
  kind. No external anchor is configured (gate D1), so a verified chain is
  "checked, unanchored": it shows edits, not a rewritten chain;
* the day inventory (workplan AG8, design §9.7): each day the files or the
  manifest know of is ``retained`` (archived and entered), ``unmanifested``
  (archived, no entry), ``unsealed`` (open day parts), ``retired``
  (retention removed it, by tombstone) or ``missing`` (entered, but its
  archive is gone);
* each engine run's extent, records and ordering mode (``eseq``, or
  ``legacy`` lines ordered without sequences), numbered as the replay
  numbers them (``run`` on ``/events``);
* the ``pm-sim-forensics`` report beside the collection, when there is one:
  copied, hashed and compared with the pinned audit files
  (:mod:`edumatcher.audit.service.forensics`).

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
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatcher.audit import manifest as evidence_manifest
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
from edumatcher.audit.service.forensics import (
    Attachment,
    ForensicsInput,
    ForensicsPin,
    attach,
)

#: A part's or archive's day: ``audit-2026-06-15.3.log``, ``audit-2026-06-15.log.zst``.
_DAY_RE = re.compile(r"^audit-(\d{4}-\d{2}-\d{2})\.")
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
    #: The trading day of a part or archive (from its name); None for the
    #: active file.
    day: str | None = None

    @property
    def torn_bytes(self) -> int:
        return self.size - self.cutoff


@dataclass(frozen=True)
class RunInfo:
    """One engine run of the snapshot, numbered as the replay numbers runs
    (``run``: 0, then +1 at each later ``system.startup``)."""

    run: int
    #: The engine's ``run_seq`` from its ``system.startup``; None without one.
    run_seq: int | None
    #: Receipt time of its ``system.startup``; None when the run's records
    #: begin without one (the trail starts mid-run).
    started_ts: str | None
    #: The hash of the configuration it announced; None when it carried none.
    config_sha256: str | None
    first_ts: str
    last_ts: str
    records: int
    with_envelope: int
    #: ``eseq`` (every record sequenced), ``legacy`` (none: ordered by
    #: envelope time, receipt and position) or ``mixed``.
    ordering: str


@dataclass(frozen=True)
class SymbolInfo:
    """A symbol a priced record names, and the scale its records state
    (None when none does)."""

    symbol: str
    tick_decimals: int | None


@dataclass(frozen=True)
class ManifestProblem:
    day: str | None
    message: str
    #: ``chain`` or ``content`` (audit.manifest.Problem.kind).
    kind: str


@dataclass(frozen=True)
class ManifestState:
    """The evidence manifest when the snapshot was pinned."""

    #: ``absent`` (no manifest), ``verified`` or ``failed``.
    state: str
    entries: int
    #: Hash of its newest line: the value to compare with a kept copy.
    head_sha256: str | None
    #: Whether the head was checked against an independently kept copy.
    anchored: bool
    problems: tuple[ManifestProblem, ...]
    #: The hash chain links (None: no manifest).
    chain_ok: bool | None = None
    #: Every current day matches its archive (None: no manifest).
    content_ok: bool | None = None
    #: The anchor checked against; always None (no anchor is configured).
    anchor: str | None = None
    #: When it was verified (UTC).
    checked_at: str | None = None


@dataclass(frozen=True)
class DayInfo:
    """One trading day as the files and the manifest know it."""

    day: str
    #: ``retained``, ``unmanifested``, ``unsealed``, ``retired`` or ``missing``.
    state: str
    #: The snapshot's files for the day (relative names), oldest first.
    files: tuple[str, ...]
    #: Its archive matches its manifest entry; None without an archive.
    content_ok: bool | None


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
    #: The attached pm-sim-forensics report, when one could be read.
    forensics: ForensicsPin | None = None
    manifest: ManifestState = ManifestState("absent", 0, None, False, ())
    #: Every priced symbol, by name.
    symbols: tuple[SymbolInfo, ...] = ()
    #: Every day the files or the manifest know of, oldest first.
    days: tuple[DayInfo, ...] = ()


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

    def check_sources(self, verified: set[tuple[str, int, int]]) -> None:
        """Raise :class:`SnapshotUnavailable` if a retained file went or
        changed since the pin. A file is re-hashed only when its size or
        modification time differs from one already verified (``verified``:
        the caller's ``(path, size, mtime_ns)`` cache, extended here), so a
        read costs a ``stat`` per file. The full re-hash is the ``verify``
        job."""
        for f, path in zip(self.descriptor.files, self.paths(), strict=True):
            if f.kind == "active":
                continue  # read from the pinned copy, which no one else writes
            try:
                st = path.stat()
            except FileNotFoundError:
                raise SnapshotUnavailable(
                    Reason.SOURCE_MISSING, f"{f.name} was removed after the snapshot"
                ) from None
            key = (str(path), st.st_size, st.st_mtime_ns)
            if key not in verified:
                _check_retained(path, f)
                verified.add(key)

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
        report = attach(root, {f.name: (f.cutoff, f.sha256) for f in files}, work)
        manifest = _manifest(root / "audit")
        material = json.dumps(
            [
                collection.id,
                str(root),
                [(f.name, f.kind, f.cutoff, f.sha256) for f in files],
                report.sha256 if report else None,
                manifest.head_sha256,
            ]
        )
        snapshot_id = "s-" + hashlib.sha256(material.encode()).hexdigest()[:20]
        final = snapshots / snapshot_id
        if (final / _DESCRIPTOR).is_file():
            return _load(final)
        descriptor = _describe(snapshot_id, collection, files, work, report, manifest)
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
    day = _DAY_RE.match(path.name)
    if name == "audit.log":
        size, cutoff, sha = _copy_complete_lines(path, copy_to)
        return SourceFile(name, "active", size, cutoff, sha, None)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
    kind = "archive" if path.suffix == ".zst" else "part"
    return SourceFile(
        name, kind, size, size, digest.hexdigest(), day.group(1) if day else None
    )


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


def _manifest(audit_dir: Path) -> ManifestState:
    """The manifest under *audit_dir*, verified as ``pm-audit-cli verify``
    does (chain, then each current day against its archive)."""
    checked = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    if not (audit_dir / evidence_manifest.MANIFEST_NAME).is_file():
        return ManifestState("absent", 0, None, False, (), checked_at=checked)
    problems = tuple(
        ManifestProblem(p.day, p.message, p.kind)
        for p in evidence_manifest.verify(audit_dir)
    )
    return ManifestState(
        state="failed" if problems else "verified",
        entries=len(evidence_manifest.read_entries(audit_dir)),
        head_sha256=evidence_manifest.head_hash(audit_dir),
        anchored=False,
        problems=problems,
        chain_ok=not any(p.kind == "chain" for p in problems),
        content_ok=not any(p.kind == "content" for p in problems),
        checked_at=checked,
    )


def _days(
    audit_dir: Path, files: tuple[SourceFile, ...], manifest: ManifestState
) -> tuple[DayInfo, ...]:
    """Every day the pinned files or the manifest's current entries name."""
    current: dict[str, str] = {}
    for entry in evidence_manifest.read_entries(audit_dir):
        day, kind = entry.get("day"), entry.get("kind")
        if isinstance(day, str) and isinstance(kind, str):
            current[day] = kind  # the latest entry of a day is current
    archives = {f.day: f.name for f in files if f.kind == "archive" and f.day}
    parts: dict[str, list[str]] = {}
    for f in files:
        if f.kind == "part" and f.day:
            parts.setdefault(f.day, []).append(f.name)
    bad = {p.day for p in manifest.problems if p.kind == "content"}
    out = []
    for day in sorted(set(current) | set(archives) | set(parts)):
        if day in archives:
            entered = current.get(day) == evidence_manifest.KIND_DAY
            state = "retained" if entered else "unmanifested"
            content: bool | None = entered and day not in bad
            names: tuple[str, ...] = (archives[day],)
        elif day in parts:
            state, content, names = "unsealed", None, tuple(parts[day])
        elif current.get(day) == evidence_manifest.KIND_RETIRED:
            state, content, names = "retired", None, ()
        else:
            state, content, names = "missing", None, ()
        out.append(DayInfo(day, state, names, content))
    return tuple(out)


def verify_snapshot(
    snapshot: Snapshot, report: Callable[[str, int | None, int | None], None]
) -> dict[str, Any]:
    """Check the snapshot against its sources now (the ``verify`` job): each
    pinned file still has its size and hash (``ok``, ``changed``,
    ``missing``), and the manifest and day inventory as they are now."""
    d = snapshot.descriptor
    total = sum(f.cutoff for f in d.files)
    done = 0
    files = []
    for f, path in zip(d.files, snapshot.paths(), strict=True):
        report("hashing", done, total)
        if not path.is_file():
            state = "missing"
        else:
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
            state = (
                "ok"
                if (size, digest.hexdigest()) == (f.cutoff, f.sha256)
                else "changed"
            )
        done += f.cutoff
        files.append({"name": f.name, "state": state})
    report("hashing", done, total)
    report("manifest", None, None)
    audit_dir = Path(d.source_root) / "audit"
    manifest = _manifest(audit_dir)
    return {
        "checked_at": manifest.checked_at,
        "files": files,
        "manifest": asdict(manifest),
        "days": [asdict(day) for day in _days(audit_dir, d.files, manifest)],
    }


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
    report: Attachment | None,
    manifest: ManifestState,
) -> SnapshotDescriptor:
    """One pass over the pinned records."""
    root = collection.path
    paths = [work / _PINNED if f.kind == "active" else root / f.name for f in files]
    count = with_envelope = books = 0
    first_ts = last_ts = first_topic = None
    runs: list[_RunTally] = []
    priced: set[str] = set()
    scales: dict[str, int] = {}
    for e in iter_entries(paths):
        count += 1
        if first_ts is None:
            first_ts, first_topic = e.timestamp, e.topic
        last_ts = e.timestamp
        with_envelope += e.msg_id is not None
        books += e.topic.startswith(_BOOK)
        # The replay's rule (facts.normalise): a run begins at the first
        # record, and again at each later system.startup with seq 1.
        if not runs or (e.topic == STARTUP and e.seq == 1):
            runs.append(_RunTally(len(runs), e.timestamp))
        runs[-1].add(e)
        if e.topic.startswith(_PRICED) and isinstance(e.payload.get("symbol"), str):
            priced.add(e.payload["symbol"])
            if isinstance(e.payload.get("tick_decimals"), int):
                scales.setdefault(e.payload["symbol"], e.payload["tick_decimals"])
    described = tuple(r.info() for r in runs)
    evidence = Evidence(
        entries=count,
        first_topic=first_topic,
        with_envelope=with_envelope,
        book_observations=books,
        priced_symbols=frozenset(priced),
        unscaled_symbols=frozenset(priced - scales.keys()),
        runs_without_config=tuple(
            (r.run_seq, r.started_ts)
            for r in described
            if r.started_ts is not None and r.config_sha256 is None
        ),
        forensics=report.state if report else None,
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
        runs=described,
        capabilities=evaluate(evidence),
        forensics=report.pin if report else None,
        manifest=manifest,
        symbols=tuple(SymbolInfo(s, scales.get(s)) for s in sorted(priced)),
        days=_days(root / "audit", files, manifest),
    )


class _RunTally:
    """One run's records while the describing pass counts them."""

    def __init__(self, run: int, first_ts: str) -> None:
        self.run = run
        self.first_ts = self.last_ts = first_ts
        self.records = self.with_envelope = self.sequenced = 0
        self.run_seq: int | None = None
        self.started_ts: str | None = None
        self.config_sha256: str | None = None

    def add(self, e: AuditEntry) -> None:
        self.last_ts = e.timestamp
        self.records += 1
        self.with_envelope += e.msg_id is not None
        self.sequenced += e.eseq is not None
        if e.topic == STARTUP and self.started_ts is None:
            config = e.payload.get("config")
            sha = e.payload.get("config_sha256")
            seq = e.payload.get("run_seq")
            self.run_seq = seq if isinstance(seq, int) else None
            self.started_ts = e.timestamp
            self.config_sha256 = str(sha) if config and sha else None

    def info(self) -> RunInfo:
        ordering = (
            "eseq"
            if self.sequenced == self.records
            else "legacy" if self.sequenced == 0 else "mixed"
        )
        return RunInfo(
            run=self.run,
            run_seq=self.run_seq,
            started_ts=self.started_ts,
            config_sha256=self.config_sha256,
            first_ts=self.first_ts,
            last_ts=self.last_ts,
            records=self.records,
            with_envelope=self.with_envelope,
            ordering=ordering,
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
        forensics=_load_forensics(raw["forensics"]),
        manifest=_load_manifest(raw["manifest"]),
        symbols=tuple(SymbolInfo(**s) for s in raw["symbols"]),
        days=tuple(
            DayInfo(d["day"], d["state"], tuple(d["files"]), d["content_ok"])
            for d in raw["days"]
        ),
    )


def _load_manifest(raw: dict[str, Any]) -> ManifestState:
    return ManifestState(
        state=raw["state"],
        entries=raw["entries"],
        head_sha256=raw["head_sha256"],
        anchored=raw["anchored"],
        problems=tuple(ManifestProblem(**p) for p in raw["problems"]),
        chain_ok=raw["chain_ok"],
        content_ok=raw["content_ok"],
        anchor=raw["anchor"],
        checked_at=raw["checked_at"],
    )


def _load_forensics(raw: dict[str, Any] | None) -> ForensicsPin | None:
    if raw is None:
        return None
    return ForensicsPin(
        sha256=raw["sha256"],
        size=raw["size"],
        tool_version=raw["tool_version"],
        cut_trade_id=raw["cut_trade_id"],
        statuses=raw["statuses"],
        inputs=tuple(ForensicsInput(**i) for i in raw["inputs"]),
        differing=tuple(raw["differing"]),
    )
