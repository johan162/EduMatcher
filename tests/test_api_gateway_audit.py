"""The Audit GUI's read routes, ``/api/v1/audit`` (Audit GUI AG2, design §8).

Driven through the whole ASGI stack over the recorded audit world
(tests/audit_gui_world.py). Expectations come from the world's tables and
the existing replay vocabulary, not from what the routes print.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

from edumatcher.api_gateway.routers import audit as audit_router
from edumatcher.audit.replay import anomalies
from edumatcher.audit.service.findings import CODE_LANES, LANES, lane_of
from tests import audit_gui_world as aw
from tests.api_gateway_harness import call
from tests.audit_gui_world import World, build, make_audit_app, run_jobs

_V1 = "/api/v1/audit"
_ADMIN = f"Bearer {aw.ADMIN_KEY}"


def _get(app: Any, path: str, key: str = aw.ADMIN_KEY) -> tuple[int, dict[str, Any]]:
    status, _headers, body = asyncio.run(
        call(app, "GET", f"{_V1}{path}", authorization=f"Bearer {key}")
    )
    return status, body


def _post(
    app: Any, path: str, body: dict[str, Any], key: str = aw.ADMIN_KEY
) -> tuple[int, dict[str, Any]]:
    status, _headers, reply = asyncio.run(
        call(app, "POST", f"{_V1}{path}", body=body, authorization=f"Bearer {key}")
    )
    return status, reply


def _snapshot(app: Any) -> str:
    """Pin the world's collection and run its prepare job (no worker
    process in tests): its reads are ready."""
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert status == 201, body
    run_jobs(app)
    return str(body["snapshot_id"])


def _all_events(app: Any, sid: str, query: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    after = ""
    while True:
        status, body = _get(app, f"/events?snapshot_id={sid}&limit=1000{query}{after}")
        assert status == 200, body
        rows += body["events"]
        if not body["has_more"]:
            return rows
        after = f"&after={body['next_cursor']}"


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build(tmp_path_factory.mktemp("audit-world"))


@pytest.fixture(scope="module")
def app(base: World) -> Any:
    return make_audit_app(base)


@pytest.fixture(scope="module")
def sid(app: Any) -> str:
    return _snapshot(app)


# --- Who may call ------------------------------------------------------------

#: One request per route, with valid arguments, so only the key decides.
_ROUTES = {
    ("GET", "/collections"): "/collections",
    ("POST", "/snapshots"): "/snapshots",
    ("GET", "/snapshots/{snapshot_id}"): "/snapshots/{sid}",
    ("GET", "/events"): "/events?snapshot_id={sid}",
    ("GET", "/stories/{entity_kind}/{entity_id}"): "/stories/order/{oid}?snapshot_id={sid}",  # fmt: skip
    ("GET", "/findings"): "/findings?snapshot_id={sid}",
    ("GET", "/market/{symbol}/heatmap"): "/market/AAA/heatmap?snapshot_id={sid}",
    ("GET", "/market/{symbol}/lifelines"): "/market/AAA/lifelines?snapshot_id={sid}",
    ("POST", "/jobs"): "/jobs",
    ("GET", "/jobs/{job_id}"): "/jobs/j-0123456789abcdef",
    ("POST", "/jobs/{job_id}/cancel"): "/jobs/j-0123456789abcdef/cancel",
    ("GET", "/results/{job_id}"): "/results/j-0123456789abcdef",
}

#: A valid body per POST route, so only the key decides.
_BODIES = {
    "/snapshots": {"collection_id": "world"},
    "/jobs": {"kind": "verify", "snapshot_id": "s-0123456789abcdef0123"},
}


def test_the_role_matrix_covers_every_audit_route() -> None:
    routes = {
        (method, route.path.removeprefix(_V1))
        for route in audit_router.router.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
    }
    assert routes == set(_ROUTES)


@pytest.mark.parametrize(
    ("key", "code"),
    [
        (aw.TRADER_KEY, "ROLE_DENIED"),
        (aw.MARKET_MAKER_KEY, "ROLE_DENIED"),
        (aw.READ_ONLY_KEY, "READ_ONLY"),
    ],
)
@pytest.mark.parametrize("route", sorted(_ROUTES))
def test_only_admin_may_call_any_audit_route(
    app: Any, sid: str, base: World, route: tuple[str, str], key: str, code: str
) -> None:
    method, _ = route
    path = _ROUTES[route].format(sid=sid, oid=base.orders["layer_1"])
    if method == "POST":
        status, body = _post(app, path, _BODIES.get(route[1], {}), key=key)
    else:
        status, body = _get(app, path, key=key)
    assert (status, body["error"]["code"]) == (403, code)


# --- Collections and snapshots ----------------------------------------------


def test_collections_are_named_by_id_never_by_path(app: Any, base: World) -> None:
    status, body = _get(app, "/collections")
    assert status == 200
    assert body["count"] == 1
    (collection,) = body["collections"]
    assert collection == {"id": "world", "available": True, "reason": None, "files": 1}
    assert str(base.data) not in json.dumps(body)


def test_a_snapshot_is_created_and_described(app: Any, sid: str, base: World) -> None:
    status, body = _get(app, f"/snapshots/{sid}")
    assert status == 200
    assert body["snapshot_id"] == sid and body["collection_id"] == "world"
    assert [f["name"] for f in body["files"]] == ["audit.log"]
    assert body["entries"] > 0
    assert body["capabilities"]["rerun"] == {"available": True, "reason": None, "detail": ""}  # fmt: skip
    assert body["capabilities"]["forensics"]["reason"] == "NOT_ATTACHED"
    assert body["symbols"] == [
        {"symbol": sym, "tick_decimals": aw.TICK_DECIMALS[sym]}
        for sym in sorted(aw.TICK_DECIMALS)
    ]
    assert str(base.data) not in json.dumps(body)


def test_a_snapshot_request_takes_an_id_not_a_path(app: Any, base: World) -> None:
    status, body = _post(app, "/snapshots", {"collection_id": "world", "path": str(base.data)})  # fmt: skip
    assert (status, body["error"]["code"]) == (400, "VALIDATION")
    status, body = _post(app, "/snapshots", {"collection_id": "nope"})
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_COLLECTION")


@pytest.mark.parametrize("bad", ["s-0123456789abcdef0123", "..%2F..%2Fetc"])
def test_an_unknown_snapshot_is_404(app: Any, bad: str) -> None:
    status, body = _get(app, f"/snapshots/{bad}")
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_SNAPSHOT")
    status, body = _get(app, f"/events?snapshot_id={bad}")
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_SNAPSHOT")


def test_a_missing_collection_directory_is_503(tmp_path: Path) -> None:
    world = build(tmp_path / "w")
    app = make_audit_app(world)
    world.data.rename(tmp_path / "moved")
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert (status, body["error"]["code"]) == (503, "AUDIT_SOURCE_UNAVAILABLE")
    assert body["error"]["reason"] == "SOURCE_MISSING"
    status, body = _get(app, "/collections")
    assert body["collections"][0]["available"] is False
    assert body["collections"][0]["reason"] == "SOURCE_MISSING"


def test_the_snapshot_reports_its_manifest_state(tmp_path: Path, base: World) -> None:
    """Three separate states: no manifest, checked (no external anchor), failed."""
    app = make_audit_app(base)
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert {
        k: body["manifest"][k]
        for k in ("state", "entries", "head_sha256", "anchored", "problems")
    } == {
        "state": "absent",
        "entries": 0,
        "head_sha256": None,
        "anchored": False,
        "problems": [],
    }
    world = build(tmp_path / "w", zstd_archive=True)
    app = make_audit_app(world)
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    manifest = body["manifest"]
    assert (manifest["state"], manifest["entries"], manifest["anchored"]) == ("verified", 1, False)  # fmt: skip
    head = manifest["head_sha256"]
    assert isinstance(head, str) and len(head) == 64
    entry = world.parts_dir / "manifest.jsonl"
    tampered = entry.read_text().replace('"lines":', '"lines":1')
    assert tampered != entry.read_text()
    entry.write_text(tampered)
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    failed = body["manifest"]
    assert failed["state"] == "failed"
    assert failed["head_sha256"] != head
    assert failed["problems"] and failed["problems"][0]["day"] == aw.DAY


def test_a_retained_file_removed_later_is_503_not_an_empty_page(
    tmp_path: Path,
) -> None:
    world = build(tmp_path / "w", zstd_archive=True)
    app = make_audit_app(world)
    sid = _snapshot(app)
    (world.parts_dir / f"audit-{aw.DAY}.log.zst").unlink()
    status, body = _get(app, f"/events?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (503, "AUDIT_SOURCE_UNAVAILABLE")
    assert body["error"]["reason"] == "SOURCE_MISSING"


# --- Events -----------------------------------------------------------------


def test_events_cover_the_snapshot_page_by_page(app: Any, sid: str) -> None:
    status, first = _get(app, f"/events?snapshot_id={sid}")
    assert status == 200
    assert first["count"] == 100 and first["has_more"] is True
    rows = _all_events(app, sid)
    _status, described = _get(app, f"/snapshots/{sid}")
    assert len(rows) == described["entries"]
    assert len({r["key"] for r in rows}) == len(rows)
    # Canonical order: one run, so the engine's own sequence never goes back.
    eseqs = [r["eseq"] for r in rows if r["eseq"] is not None]
    assert eseqs == sorted(eseqs)


def test_event_rows_carry_units_clocks_and_sources(
    app: Any, sid: str, base: World
) -> None:
    trades = _all_events(app, sid, "&topic=trade.executed")
    assert len(trades) == len(aw.EXECUTIONS)
    raw = base.audit_log.read_text(encoding="utf-8").splitlines()
    for row in trades:
        ts_ns = row["fields"]["ts_ns"]
        assert isinstance(ts_ns, str) and ts_ns.isdigit()  # exact in JavaScript
        assert isinstance(row["receipt_ns"], str)
        price = next(p for p in row["prices"] if p["name"] == "price")
        assert price["tick_decimals"] == aw.TICK_DECIMALS[row["symbol"]]
        assert price["display"] == row["fields"]["price"]
        assert row["source"]["file"] == "audit.log"
        assert raw[row["source"]["line"] - 1].startswith(
            f"[{row['receipt_ts']}] [trade.executed]"
        )
    got = Counter(
        (r["symbol"], round(next(p["display"] for p in r["prices"] if p["name"] == "price") * 10 ** aw.TICK_DECIMALS[r["symbol"]]))  # fmt: skip
        for r in trades
    )
    assert got == Counter((e.symbol, e.price_ticks) for e in aw.EXECUTIONS)


def test_event_filters_combine(app: Any, sid: str, base: World) -> None:
    bbb = _all_events(app, sid, "&topic=trade.executed&symbol=BBB")
    assert len(bbb) == sum(e.symbol == "BBB" for e in aw.EXECUTIONS)
    oid = base.orders["layer_1"]
    mine = _all_events(app, sid, f"&order_id={oid}")
    assert {r["topic"] for r in mine} >= {"order.new", "order.cancel", "order.cancelled.TRADER02"}  # fmt: skip
    gw = _all_events(app, sid, "&gateway=TRADER03&topic=order.cancelled")
    assert len(gw) == aw.OWNER_CANCELS[aw.T3]


@pytest.mark.parametrize(
    "query",
    ["&limit=1001", "&limit=0", "&after=not-a-cursor", "&topic=" + "x" * 200],
)
def test_invalid_event_queries_are_400(app: Any, sid: str, query: str) -> None:
    status, body = _get(app, f"/events?snapshot_id={sid}{query}")
    assert (status, body["error"]["code"]) == (400, "VALIDATION")


def test_a_cursor_belongs_to_its_snapshot_and_filters(app: Any, sid: str) -> None:
    _status, page = _get(app, f"/events?snapshot_id={sid}&limit=5")
    cursor = page["next_cursor"]
    status, body = _get(app, f"/events?snapshot_id={sid}&limit=5&symbol=AAA&after={cursor}")  # fmt: skip
    assert (status, body["error"]["field"]) == (400, "after")
    status, _ = _get(app, f"/events?snapshot_id={sid}&limit=5&after={cursor}")
    assert status == 200


# --- Stories ----------------------------------------------------------------


def test_an_order_story_names_its_beats_links_and_confidence(
    app: Any, sid: str, base: World
) -> None:
    oid = base.orders["stop_2"]
    status, body = _get(app, f"/stories/order/{oid}?snapshot_id={sid}")
    assert status == 200
    anchors = {(e["kind"], e["anchor"]) for e in body["episodes"]}
    assert ("order", oid) in anchors
    topics = {b["topic"] for b in body["beats"]}
    assert {"order.new", "order.triggered.TRADER02", "order.fill.TRADER02"} <= topics
    assert all(b["text"] for b in body["beats"])
    assert body["links"], "a triggered stop is linked to what set it off"
    assert {link["confidence"] for link in body["links"]} <= {
        "RECORDED",
        "CERTAIN",
        "STRONG",
        "HEURISTIC",
        "NONE",
    }
    ids = {e["id"] for e in body["episodes"]}
    assert all(link["from"] in ids and link["to"] in ids for link in body["links"])


def test_a_story_of_unknown_entity_is_404(app: Any, sid: str) -> None:
    status, body = _get(app, f"/stories/order/{'f' * 32}?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_ENTITY")
    status, body = _get(app, f"/stories/nonsense/x?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (400, "VALIDATION")


def test_a_reused_id_is_never_joined_across_runs(tmp_path: Path) -> None:
    world = build(tmp_path / "w", run_reset=True)
    app = make_audit_app(world)
    sid = _snapshot(app)
    oid = world.orders["layer_1"]
    status, body = _get(app, f"/stories/order/{oid}?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (409, "AMBIGUOUS_RUN")
    # Runs are the replay's restart epochs: 0 until the second engine start.
    for run in (0, 1):
        status, body = _get(app, f"/stories/order/{oid}?snapshot_id={sid}&run_id={run}")  # fmt: skip
        assert status == 200
        seeds = [e for e in body["episodes"] if e["anchor"] == oid]
        assert seeds and all(e["run"] == run for e in seeds)
        assert all(e["run"] == run for e in body["episodes"])


def test_a_snapshot_without_events_has_no_stories(tmp_path: Path) -> None:
    empty = tmp_path / "data"
    empty.mkdir()
    world = aw.World(data=empty, variants=frozenset(), orders={}, marks={})
    app = make_audit_app(world)
    sid = _snapshot(app)
    status, body = _get(app, f"/stories/order/x?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (409, "CAPABILITY_UNAVAILABLE")
    assert body["error"]["reason"] == "NO_EVENTS"
    status, body = _get(app, f"/findings?snapshot_id={sid}")
    assert (status, body["error"]["reason"]) == (409, "NO_EVENTS")


# --- Findings ---------------------------------------------------------------


def test_every_replay_code_has_a_lane() -> None:
    codes = {
        value
        for name, value in vars(anomalies).items()
        if name.isupper()
        and isinstance(value, str)
        and not name.startswith("SEVERITY_")
    }
    assert codes == set(CODE_LANES)
    assert set(CODE_LANES.values()) <= set(LANES) - {"behaviour"}


def test_findings_keep_their_codes_in_their_lanes(app: Any, sid: str) -> None:
    status, body = _get(app, f"/findings?snapshot_id={sid}&limit=1000")
    assert status == 200
    for row in body["findings"]:
        assert row["lane"] == lane_of(row["code"])
    # The GTC bid is still open when the trail ends: an expected window edge.
    assert any(r["code"] == "TERMINAL_MISSING" for r in body["findings"])
    lanes = body["lanes"]
    assert lanes["behaviour"] == {"available": False, "reason": "NOT_IN_RELEASE", "count": None}  # fmt: skip
    for lane in ("evidence", "consistency", "operations"):
        assert lanes[lane]["available"] is True
    assert sum(lanes[lane]["count"] for lane in ("evidence", "consistency", "operations")) == body["count"]  # fmt: skip


@pytest.mark.parametrize(
    ("variant", "code"), [("gap", "ESEQ_GAP"), ("restart", "RECORDER_RESTART")]
)
def test_recording_defects_land_in_the_evidence_lane(
    tmp_path: Path, variant: str, code: str
) -> None:
    world = build(tmp_path / "w", **{variant: True})
    app = make_audit_app(world)
    sid = _snapshot(app)
    status, body = _get(app, f"/findings?snapshot_id={sid}&lane=evidence&limit=1000")
    assert status == 200
    assert code in {r["code"] for r in body["findings"]}
    assert {r["lane"] for r in body["findings"]} == {"evidence"}


def test_findings_page_and_filter_by_severity(app: Any, sid: str) -> None:
    status, body = _get(app, f"/findings?snapshot_id={sid}&severity=error")
    assert status == 200
    assert all(r["severity"] == "error" for r in body["findings"])
    status, body = _get(app, f"/findings?snapshot_id={sid}&lane=behaviour")
    assert (status, body["error"]["code"]) == (409, "CAPABILITY_UNAVAILABLE")
    assert body["error"]["reason"] == "NOT_IN_RELEASE"
