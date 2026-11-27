"""Evidence snapshots and the capability model (Audit GUI AG1, design §6, §7.2).

A snapshot pins what a report is about: which files, how far into each, with
which hashes, and what the evidence can support. Everything is checked
against the recorded audit world (tests/audit_gui_world.py) and its files,
read here independently of the code under test.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from edumatcher.audit.service.capabilities import Capability, Reason
from edumatcher.audit.service.snapshot import (
    AuditCollection,
    SnapshotUnavailable,
    create_snapshot,
    open_snapshot,
)
from tests import audit_gui_world as aw
from tests.audit_gui_world import World, build


def _collection(world: World) -> AuditCollection:
    return AuditCollection("class-1", world.data)


def _store(tmp_path: Path) -> Path:
    return tmp_path / "audit-gui"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_state(world: World) -> dict[Path, tuple[bytes, int]]:
    return {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in world.data.rglob("*")
        if p.is_file()
    }


def _record_lines(data: bytes) -> list[bytes]:
    return [ln for ln in data.split(b"\n") if ln.startswith(b"[")]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build(tmp_path_factory.mktemp("audit-world"))


def test_the_descriptor_pins_the_base_worlds_evidence(
    base: World, tmp_path: Path
) -> None:
    raw = base.audit_log.read_bytes()
    lines = _record_lines(raw)
    first = lines[0].split(b"]", 1)[0][1:].decode()
    last = lines[-1].split(b"]", 1)[0][1:].decode()
    startup = json.loads(lines[0].split(b"] ", 3)[3])

    d = create_snapshot(_collection(base), _store(tmp_path))

    assert d.collection_id == "class-1"
    assert [(f.name, f.kind) for f in d.files] == [("audit.log", "active")]
    (active,) = d.files
    assert (active.size, active.cutoff, active.torn_bytes) == (len(raw), len(raw), 0)
    assert active.sha256 == _sha(raw)
    assert d.entries == len(lines)
    assert (d.first_ts, d.last_ts) == (first, last)
    assert [(r.run_seq, r.started_ts) for r in d.runs] == [(1, first)]
    assert d.runs[0].config_sha256 == startup["config_sha256"] is not None
    available = {c for c, s in d.capabilities.items() if s.available}
    assert available == {
        Capability.STORIES,
        Capability.CAUSALITY,
        Capability.PRICES,
        Capability.BOOK,
        Capability.RERUN,
        Capability.QUEUE,
    }
    # Not attached in AG1; an attached source (AG4, AG16) makes them available.
    assert d.capabilities[Capability.SIM_CONTEXT].reason is Reason.NOT_ATTACHED
    assert d.capabilities[Capability.FORENSICS].reason is Reason.NOT_ATTACHED


def test_every_capability_has_a_state_and_every_unavailable_one_a_reason(
    base: World, tmp_path: Path
) -> None:
    d = create_snapshot(_collection(base), _store(tmp_path))
    assert set(d.capabilities) == set(Capability)
    for state in d.capabilities.values():
        assert state.available == (state.reason is None)
        if not state.available:
            assert state.detail


def test_the_id_is_derived_from_the_content(base: World, tmp_path: Path) -> None:
    first = create_snapshot(_collection(base), _store(tmp_path))
    again = create_snapshot(_collection(base), _store(tmp_path))
    assert again.snapshot_id == first.snapshot_id
    other = create_snapshot(AuditCollection("other", base.data), _store(tmp_path))
    assert other.snapshot_id != first.snapshot_id
    assert open_snapshot(_store(tmp_path), first.snapshot_id).descriptor == first


def test_reads_through_a_snapshot_ignore_later_appends(tmp_path: Path) -> None:
    world = build(tmp_path / "w")
    store = _store(tmp_path)
    before = create_snapshot(_collection(world), store)
    pinned = list(open_snapshot(store, before.snapshot_id).entries())

    extra = world.audit_log.read_text().splitlines(keepends=True)[-3:]
    with world.audit_log.open("a", encoding="utf-8") as fh:
        fh.writelines(extra)

    again = list(open_snapshot(store, before.snapshot_id).entries())
    assert [(e.timestamp, e.topic, e.eseq) for e in again] == [
        (e.timestamp, e.topic, e.eseq) for e in pinned
    ]
    assert len(pinned) == before.entries
    after = create_snapshot(_collection(world), store)
    assert after.snapshot_id != before.snapshot_id
    assert after.entries == before.entries + 3


def test_entries_name_their_source_file_and_line(base: World, tmp_path: Path) -> None:
    store = _store(tmp_path)
    d = create_snapshot(_collection(base), store)
    entries = list(open_snapshot(store, d.snapshot_id).entries())
    raw = base.audit_log.read_text(encoding="utf-8").splitlines()
    for e in entries[:50]:
        assert e.file == "audit.log"
        assert e.line_no is not None
        assert raw[e.line_no - 1].startswith(f"[{e.timestamp}] [{e.topic}]")
    trades = [e for e in entries if e.topic == "trade.executed"]
    assert len(trades) == len(aw.EXECUTIONS)


def test_an_unknown_snapshot_is_unavailable_not_empty(tmp_path: Path) -> None:
    with pytest.raises(SnapshotUnavailable) as caught:
        open_snapshot(_store(tmp_path), "s-0123456789abcdef0123")
    assert caught.value.reason is Reason.UNKNOWN_SNAPSHOT


@pytest.mark.parametrize("bad", ["../etc", "s-../../x", "", "S-UPPER"])
def test_a_malformed_snapshot_id_never_reaches_the_filesystem(
    tmp_path: Path, bad: str
) -> None:
    with pytest.raises(SnapshotUnavailable) as caught:
        open_snapshot(_store(tmp_path), bad)
    assert caught.value.reason is Reason.UNKNOWN_SNAPSHOT


def test_without_a_recorded_config_rerun_and_queue_are_unavailable(
    tmp_path: Path,
) -> None:
    world = build(tmp_path / "w", no_config=True)
    d = create_snapshot(_collection(world), _store(tmp_path))
    rerun = d.capabilities[Capability.RERUN]
    assert (rerun.available, rerun.reason) == (False, Reason.NO_RECORDED_CONFIG)
    assert "run 1" in rerun.detail
    queue = d.capabilities[Capability.QUEUE]
    assert (queue.available, queue.reason) == (False, Reason.RERUN_UNAVAILABLE)
    assert d.capabilities[Capability.STORIES].available
    assert d.runs[0].config_sha256 is None


def test_a_trail_not_starting_at_an_engine_start_cannot_be_rerun(
    tmp_path: Path,
) -> None:
    world = build(tmp_path / "w")
    lines = world.audit_log.read_text().splitlines(keepends=True)
    world.audit_log.write_text("".join(ln for ln in lines if "[system.startup]" not in ln))  # fmt: skip
    d = create_snapshot(_collection(world), _store(tmp_path))
    assert d.capabilities[Capability.RERUN].reason is Reason.NO_ENGINE_START
    # The replay's numbering: the records still form run 0, with no startup.
    (run,) = d.runs
    assert (run.run, run.run_seq, run.started_ts, run.records) == (
        0,
        None,
        None,
        d.entries,
    )


def test_a_torn_tail_is_reported_and_left_out(tmp_path: Path) -> None:
    world = build(tmp_path / "w", torn_tail=True)
    raw = world.audit_log.read_bytes()
    complete = raw.rsplit(b"\n", 1)[0] + b"\n"
    store = _store(tmp_path)
    d = create_snapshot(_collection(world), store)
    (active,) = d.files
    assert (active.size, active.cutoff) == (len(raw), len(complete))
    assert active.torn_bytes == len(raw) - len(complete) > 0
    assert active.sha256 == _sha(complete)
    assert d.entries == len(_record_lines(complete))
    assert len(list(open_snapshot(store, d.snapshot_id).entries())) == d.entries


def test_a_run_reset_lists_both_runs(tmp_path: Path) -> None:
    world = build(tmp_path / "w", run_reset=True)
    d = create_snapshot(_collection(world), _store(tmp_path))
    assert [r.run_seq for r in d.runs] == [1, 2]
    assert d.runs[0].first_ts < d.runs[1].first_ts


def test_an_archived_day_is_read_from_its_archive(tmp_path: Path) -> None:
    world = build(tmp_path / "w", zstd_archive=True)
    archive = world.parts_dir / f"audit-{aw.DAY}.log.zst"
    store = _store(tmp_path)
    d = create_snapshot(_collection(world), store)
    kinds = {f.name: f.kind for f in d.files}
    assert kinds[f"audit/{archive.name}"] == "archive"
    archived = next(f for f in d.files if f.kind == "archive")
    assert (archived.size, archived.cutoff, archived.sha256) == (
        archive.stat().st_size,
        archive.stat().st_size,
        _sha(archive.read_bytes()),
    )
    topics = Counter(e.topic for e in open_snapshot(store, d.snapshot_id).entries())
    assert topics["trade.executed"] == len(aw.EXECUTIONS)


def test_a_retained_file_changed_after_the_snapshot_is_detected(
    tmp_path: Path,
) -> None:
    world = build(tmp_path / "w", zstd_archive=True)
    archive = world.parts_dir / f"audit-{aw.DAY}.log.zst"
    store = _store(tmp_path)
    d = create_snapshot(_collection(world), store)
    data = bytearray(archive.read_bytes())
    data[-1] ^= 0xFF  # same size, different content
    archive.write_bytes(bytes(data))
    with pytest.raises(SnapshotUnavailable) as caught:
        list(open_snapshot(store, d.snapshot_id).entries())
    assert caught.value.reason is Reason.SOURCE_CHANGED
    assert archive.name in str(caught.value)


def test_a_retained_file_removed_after_the_snapshot_is_detected(
    tmp_path: Path,
) -> None:
    world = build(tmp_path / "w", zstd_archive=True)
    store = _store(tmp_path)
    d = create_snapshot(_collection(world), store)
    (world.parts_dir / f"audit-{aw.DAY}.log.zst").unlink()
    with pytest.raises(SnapshotUnavailable) as caught:
        list(open_snapshot(store, d.snapshot_id).entries())
    assert caught.value.reason is Reason.SOURCE_MISSING


def test_a_collection_without_a_trail_has_no_stories(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    d = create_snapshot(AuditCollection("empty", empty), _store(tmp_path))
    assert d.files == () and d.entries == 0
    for cap in (Capability.STORIES, Capability.CAUSALITY, Capability.BOOK):
        assert d.capabilities[cap].reason is Reason.NO_EVENTS


def test_a_missing_collection_directory_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(SnapshotUnavailable) as caught:
        create_snapshot(AuditCollection("gone", tmp_path / "gone"), _store(tmp_path))
    assert caught.value.reason is Reason.SOURCE_MISSING


def test_snapshots_never_write_to_the_sources(tmp_path: Path) -> None:
    world = build(tmp_path / "w", zstd_archive=True)
    before = _source_state(world)
    store = _store(tmp_path)
    d = create_snapshot(_collection(world), store)
    list(open_snapshot(store, d.snapshot_id).entries())
    assert _source_state(world) == before
    assert not store.is_relative_to(world.data)
