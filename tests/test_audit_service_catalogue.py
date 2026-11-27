"""The full source catalogue of a snapshot (Audit GUI AG8, design AU-1,
§7.2, §9.7, §11.2 scenarios 4 and 5).

Each evidence state is recorded by the AG0 world's variants -- legacy lines,
rotated day parts, zstd archives, retired days, a missing archive, a torn
tail, a run reset, a mutated retained file -- and must come out as its own
state with its own reason. Reads never change a source.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from tests import audit_gui_world as aw
from tests.audit_gui_world import World, build, make_audit_app, run_jobs
from tests.test_api_gateway_audit import _all_events, _get, _post

ARCHIVE = f"audit/audit-{aw.DAY}.log.zst"


def _pin(world: World) -> tuple[Any, dict[str, Any]]:
    app = make_audit_app(world)
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert status == 201, body
    run_jobs(app)
    return app, body


def _days(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {d["day"]: d for d in body["days"]}


# --- Manifest: four distinct states (scenario 5) -------------------------------


def test_no_manifest_is_absent_not_failed(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path))
    m = body["manifest"]
    assert (m["state"], m["chain_ok"], m["content_ok"]) == ("absent", None, None)
    assert (m["anchored"], m["anchor"]) == (False, None)
    assert body["days"] == []


def test_a_healthy_manifest_is_checked_but_unanchored(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path, zstd_archive=True))
    m = body["manifest"]
    assert (m["state"], m["chain_ok"], m["content_ok"]) == ("verified", True, True)
    assert (m["anchored"], m["anchor"], m["problems"]) == (False, None, [])
    assert m["checked_at"]
    day = _days(body)[aw.DAY]
    assert (day["state"], day["files"], day["content_ok"]) == (
        "retained",
        [ARCHIVE],
        True,
    )


def test_a_changed_archive_fails_its_content_not_the_chain(tmp_path: Path) -> None:
    from compression import zstd

    world = build(tmp_path, zstd_archive=True)
    path = world.data / ARCHIVE
    with zstd.open(path, "rb") as fh:
        data = fh.read()
    with zstd.open(path, "wb") as fh:
        fh.write(data.replace(b"TRADER02", b"TRADER09", 1))
    _, body = _pin(world)
    m = body["manifest"]
    assert (m["state"], m["chain_ok"], m["content_ok"]) == ("failed", True, False)
    assert [(p["kind"], p["day"]) for p in m["problems"]] == [("content", aw.DAY)]
    assert _days(body)[aw.DAY]["content_ok"] is False


def test_an_edited_entry_breaks_the_chain(tmp_path: Path) -> None:
    world = build(tmp_path, zstd_archive=True)
    manifest = world.parts_dir / "manifest.jsonl"
    manifest.write_text(manifest.read_text().replace('"prev":"0', '"prev":"1', 1))
    _, body = _pin(world)
    m = body["manifest"]
    assert (m["state"], m["chain_ok"]) == ("failed", False)
    assert "chain" in {p["kind"] for p in m["problems"]}


def test_a_retired_day_is_its_own_state_not_a_failure(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path, retired=True))
    m = body["manifest"]
    assert (m["state"], m["chain_ok"], m["content_ok"]) == ("verified", True, True)
    day = _days(body)[aw.DAY]
    assert (day["state"], day["files"], day["content_ok"]) == ("retired", [], None)


def test_an_archive_gone_without_retirement_is_missing(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path, missing=True))
    m = body["manifest"]
    assert (m["state"], m["chain_ok"], m["content_ok"]) == ("failed", True, False)
    assert [(p["kind"], p["day"]) for p in m["problems"]] == [("content", aw.DAY)]
    assert _days(body)[aw.DAY]["state"] == "missing"


def test_the_four_manifest_states_are_distinct(tmp_path: Path) -> None:
    """Scenario 5: checked-unanchored, failed, retired and no manifest."""
    seen = set()
    for i, variants in enumerate(
        ({}, {"zstd_archive": True}, {"retired": True}, {"missing": True})
    ):
        _, body = _pin(build(tmp_path / str(i), **variants))
        m = body["manifest"]
        days = tuple(sorted(d["state"] for d in body["days"]))
        seen.add((m["state"], m["chain_ok"], m["content_ok"], days))
    assert len(seen) == 4


# --- Files and days -------------------------------------------------------------


def test_rotated_day_parts_are_unsealed_and_read_in_order(tmp_path: Path) -> None:
    base_app, base = _pin(build(tmp_path / "base"))
    world = build(tmp_path / "rot", rotated=True)
    app, body = _pin(world)
    parts = [f for f in body["files"] if f["kind"] == "part"]
    assert len(parts) >= 2
    assert {f["day"] for f in parts} == {aw.DAY}
    assert [f["kind"] for f in body["files"]][-1] == "active"
    assert next(f for f in body["files"] if f["kind"] == "active")["day"] is None
    day = _days(body)[aw.DAY]
    assert (day["state"], day["files"]) == ("unsealed", [f["name"] for f in parts])
    # The same session, whole, through the parts.
    assert body["entries"] == base["entries"]
    keys = [e["topic"] for e in _all_events(app, body["snapshot_id"])]
    assert keys == [e["topic"] for e in _all_events(base_app, base["snapshot_id"])]


def test_a_retained_part_changed_after_the_snapshot_is_refused(tmp_path: Path) -> None:
    world = build(tmp_path, rotated=True)
    app, body = _pin(world)
    part = world.data / next(f["name"] for f in body["files"] if f["kind"] == "part")
    part.write_text(part.read_text().replace("TRADER02", "TRADER09", 1))
    status, err = _get(app, f"/events?snapshot_id={body['snapshot_id']}")
    assert (status, err["error"]["code"], err["error"]["reason"]) == (
        503,
        "AUDIT_SOURCE_UNAVAILABLE",
        "SOURCE_CHANGED",
    )


def test_a_torn_tail_is_reported_on_its_file(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path, torn_tail=True))
    active = next(f for f in body["files"] if f["kind"] == "active")
    assert active["torn_bytes"] > 0


# --- Runs -----------------------------------------------------------------------


def test_each_run_has_its_extent_and_ordering_mode(tmp_path: Path) -> None:
    world = build(tmp_path, run_reset=True)
    app, body = _pin(world)
    runs = body["runs"]
    assert [(r["run"], r["run_seq"], r["ordering"]) for r in runs] == [
        (0, 1, "eseq"),
        (1, 2, "eseq"),
    ]
    assert sum(r["records"] for r in runs) == body["entries"]
    assert runs[0]["first_ts"] == body["first_ts"]
    assert runs[0]["last_ts"] < runs[1]["first_ts"]
    assert runs[1]["last_ts"] == body["last_ts"]
    assert all(r["with_envelope"] == r["records"] for r in runs)
    # The catalogue's run numbers are the ones /events reports.
    events = _all_events(app, body["snapshot_id"])
    per_run = {r["run"]: 0 for r in runs}
    for e in events:
        per_run[e["run"]] += 1
    assert per_run == {r["run"]: r["records"] for r in runs}


def test_legacy_lines_are_ordered_without_sequences(tmp_path: Path) -> None:
    _, body = _pin(build(tmp_path, legacy=True))
    (run,) = body["runs"]
    assert (run["ordering"], run["with_envelope"]) == ("legacy", 0)
    assert body["capabilities"]["causality"]["reason"] == "NO_ENVELOPES"


def test_a_run_reset_never_joins_stories(tmp_path: Path) -> None:
    """Scenario 4: TRADER02 reuses layer_1's id in run 1."""
    world = build(tmp_path, run_reset=True)
    app, body = _pin(world)
    sid = body["snapshot_id"]
    oid = world.orders["layer_1"]
    status, err = _get(app, f"/stories/order/{oid}?snapshot_id={sid}")
    assert (status, err["error"]["code"], err["error"]["runs"]) == (
        409,
        "AMBIGUOUS_RUN",
        [0, 1],
    )
    for run in (0, 1):
        status, story = _get(
            app, f"/stories/order/{oid}?snapshot_id={sid}&run_id={run}"
        )
        assert status == 200
        assert {e["run"] for e in story["episodes"]} == {run}


# --- Reads never change a source ------------------------------------------------


def _inventory(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.parametrize("variant", ["zstd_archive", "rotated"])
def test_reads_never_modify_the_sources(tmp_path: Path, variant: str) -> None:
    world = build(tmp_path, **{variant: True})
    before = _inventory(world.data)
    app, body = _pin(world)
    sid = body["snapshot_id"]
    _all_events(app, sid)
    for path in (
        f"/findings?snapshot_id={sid}",
        f"/market/AAA/heatmap?snapshot_id={sid}",
        f"/market/AAA/lifelines?snapshot_id={sid}",
        f"/stories/order/{world.orders['layer_1']}?snapshot_id={sid}",
    ):
        status, _ = _get(app, path)
        assert status == 200, path
    assert _inventory(world.data) == before
