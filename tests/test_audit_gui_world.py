"""Self-tests of the audit world (tests/audit_gui_world.py), Audit GUI AG0.

They read the recorded lines with a deliberately naive reader (topic,
metadata and payload only, no replay library) and compare them with the
world's expectation tables. If the world drifts from its tables, every later
Audit GUI test would be checking the wrong thing; this is where that shows.
"""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from compression import zstd

from edumatcher.audit.indexer import build_index
from edumatcher.audit.manifest import verify
from edumatcher.audit.query import iter_entries
from edumatcher.audit.rawlines import iso_ns
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.config import DATA_DIR
from tests import audit_gui_world as aw
from tests.api_gateway_harness import call
from tests.audit_gui_world import World, build

_LINE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[(?P<topic>[^\]]+)\] "
    r"(?:\[(?P<meta>[^\]]*)\] )?(?P<payload>\{.*\})$"
)


@dataclass(frozen=True)
class Rec:
    ts: str
    topic: str
    meta: dict[str, str]
    payload: dict[str, Any]


def _files(world: World) -> list[Path]:
    """Archives, then day parts, then the active file: oldest first."""
    parts = world.parts_dir
    found = sorted(parts.glob("*.zst")) + sorted(
        parts.glob("audit-*.log"), key=lambda p: int(p.name.split(".")[-2])
    )
    return found + ([world.audit_log] if world.audit_log.exists() else [])


def _text(path: Path) -> str:
    if path.suffix == ".zst":
        with zstd.ZstdFile(path, "rb") as fh:
            return fh.read().decode("utf-8")
    return path.read_text(encoding="utf-8")


def raw_lines(world: World) -> list[str]:
    return [ln for p in _files(world) for ln in _text(p).split("\n") if ln]


def records(world: World) -> list[Rec]:
    out = []
    for ln in raw_lines(world):
        m = _LINE.match(ln)
        if m is None:
            continue
        meta = dict(kv.split("=", 1) for kv in (m["meta"] or "").split())
        out.append(Rec(m["ts"], m["topic"], meta, json.loads(m["payload"])))
    return out


def executions(recs: list[Rec]) -> list[aw.Execution]:
    return [
        aw.Execution(
            p["symbol"],
            p["sell_gateway_id"],
            p["buy_gateway_id"],
            p["quantity"],
            round(p["price"] * 10 ** p["tick_decimals"]),
        )
        for r in recs
        if r.topic == "trade.executed"
        for p in [r.payload]
    ]


def runs(recs: list[Rec]) -> list[list[Rec]]:
    """The records split at each ``system.startup`` (one list per run)."""
    out: list[list[Rec]] = []
    for r in recs:
        if r.topic == "system.startup" or not out:
            out.append([])
        out[-1].append(r)
    return out


def cancel_origin(recs: list[Rec], cancelled: Rec) -> str:
    """``owner`` when the cancel was caused by the order's own gateway's
    ``order.cancel`` command, else ``system:<cancel_reason>``."""
    by_msg = {r.meta["msg"]: r for r in recs if "msg" in r.meta}
    cause = by_msg.get(cancelled.meta.get("cause", ""))
    gateway = cancelled.topic.rsplit(".", 1)[1]
    if (
        cause is not None
        and cause.topic == "order.cancel"
        and cause.payload["gateway_id"] == gateway
    ):
        return "owner"
    return f"system:{cancelled.payload.get('cancel_reason')}"


def life(recs: list[Rec], oid: str) -> tuple[aw.Life, int]:
    """What the trail says about order *oid*, as a ``Life``, and its
    ``order.new`` count."""
    new = [r.payload for r in recs if r.topic == "order.new" and r.payload["id"] == oid]
    assert new, oid
    first = new[0]
    filled = sum(
        r.payload["fill_qty"]
        for r in recs
        if r.topic.startswith("order.fill.") and r.payload["order_id"] == oid
    )
    end = "filled" if filled == first["quantity"] else "open"
    for r in recs:
        if r.payload.get("order_id") != oid:
            continue
        if r.topic.startswith("order.cancelled."):
            origin = cancel_origin(recs, r)
            end = "cancel.owner" if origin == "owner" else f"cancel.{origin}"
        elif r.topic.startswith("order.expired."):
            end = "expired"
    side = first["side"]
    return (
        aw.Life(first["gateway_id"], first["symbol"], side, first["quantity"], filled, end),  # fmt: skip
        len(new),
    )


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    """The base world, built once for the read-only tests below."""
    return build(tmp_path_factory.mktemp("audit-world"))


@pytest.fixture(scope="module")
def base_recs(base: World) -> list[Rec]:
    return records(base)


# --- The base world ---------------------------------------------------------


def test_every_contracted_execution_is_recorded_once(base_recs: list[Rec]) -> None:
    assert Counter(executions(base_recs)) == Counter(aw.EXECUTIONS)
    ids = [r.payload["id"] for r in base_recs if r.topic == "trade.executed"]
    assert len(ids) == len(set(ids))
    assert set(ids) == aw.TRADE_IDS


def test_both_tick_scales_are_recorded(base_recs: list[Rec]) -> None:
    scales = {
        r.payload["symbol"]: r.payload["tick_decimals"]
        for r in base_recs
        if r.topic == "trade.executed"
    }
    assert scales == aw.TICK_DECIMALS


def test_each_trade_has_one_fill_per_side(base_recs: list[Rec]) -> None:
    """Fills are not extra executions: two per print, one for each side."""
    fills = Counter(
        tid
        for r in base_recs
        if r.topic.startswith("order.fill.")
        for tid in r.payload["trade_ids"]
    )
    assert fills == {tid: 2 for tid in aw.TRADE_IDS}


def test_flows_seller_to_buyer(base_recs: list[Rec]) -> None:
    flows: dict[tuple[str, str, str], list[int]] = {}
    for e in executions(base_recs):
        total = flows.setdefault((e.symbol, e.seller, e.buyer), [0, 0])
        total[0] += e.qty
        total[1] += 1
    assert {k: tuple(v) for k, v in flows.items()} == aw.FLOWS


def test_cancellations_keep_their_origin(base_recs: list[Rec]) -> None:
    origins = Counter(
        (cancel_origin(base_recs, r), r.topic.rsplit(".", 1)[1])
        for r in base_recs
        if r.topic.startswith("order.cancelled.")
    )
    owner = {gw: n for (o, gw), n in origins.items() if o == "owner"}
    system: Counter[str] = Counter()
    for (o, _gw), n in origins.items():
        if o != "owner":
            system[o.removeprefix("system:")] += n
    assert owner == aw.OWNER_CANCELS
    assert dict(system) == aw.SYSTEM_CANCELS
    expired = [r for r in base_recs if r.topic.startswith("order.expired.")]
    assert len(expired) == aw.EXPIRED_AT_CLOSE


def test_named_orders_live_as_the_table_says(base: World, base_recs: list[Rec]) -> None:
    assert set(base.orders) == set(aw.LIVES)
    for name, expected in aw.LIVES.items():
        got, news = life(base_recs, base.orders[name])
        assert (got, news) == (expected, 1), name


def test_amended_order_keeps_each_price_and_size(
    base: World, base_recs: list[Rec]
) -> None:
    for name, expected in aw.AMENDMENTS.items():
        oid = base.orders[name]
        new = next(r for r in base_recs if r.topic == "order.new" and r.payload["id"] == oid)  # fmt: skip
        states = [(new.payload["price_ticks"], new.payload["quantity"])] + [
            (r.payload["price_ticks"], r.payload["remaining_qty"])
            for r in base_recs
            if r.topic.startswith("order.amended.") and r.payload["order_id"] == oid
        ]
        assert tuple(states) == expected, name


def test_phases_auctions_and_halt(base_recs: list[Rec]) -> None:
    states = [r.payload["state"] for r in base_recs if r.topic == "session.state"]
    entered = tuple(s for i, s in enumerate(states) if i == 0 or s != states[i - 1])
    assert entered == aw.PHASES
    # No session.state precedes the first transition; the phase the engine
    # started in is on its STARTUP checkpoints (sessions enabled: CLOSED).
    startup = {
        r.payload["symbol"]: r.payload["phase"]
        for r in base_recs
        if r.topic.startswith("system.book_checkpoint.")
        and r.payload["reason"] == "STARTUP"
    }
    assert startup == dict.fromkeys(aw.TICK_DECIMALS, "CLOSED")
    # The opening call's indication moves as the offers arrive: 100.00 x 60
    # once TRADER02 offers, 100.00 x 100 once TRADER03 does.
    indicative = {
        (r.payload.get("eq_price_ticks"), r.payload["eq_qty"])
        for r in base_recs
        if r.topic == "auction.indicative.AAA"
    }
    assert {(10000, 60), (10000, 100)} <= indicative
    assert {r.topic for r in base_recs if r.topic.startswith("auction.result.")} == {
        "auction.result.AAA",
        "auction.result.BBB",
    }
    halts = [
        i for i, r in enumerate(base_recs) if r.topic == "circuit_breaker.halt.AAA"
    ]
    resumes = [
        i for i, r in enumerate(base_recs) if r.topic == "circuit_breaker.resume.AAA"
    ]
    assert len(halts) == 1 and len(resumes) == 1 and halts[0] < resumes[0]


def test_book_and_depth_observations_for_both_symbols(base_recs: list[Rec]) -> None:
    topics = Counter(r.topic for r in base_recs)
    for sym in aw.TICK_DECIMALS:
        assert topics[f"book.{sym}"] >= 5 and topics[f"depth.{sym}"] >= 5


def test_quote_after_the_replacement_burst(base: World, base_recs: list[Rec]) -> None:
    """The last AAA book before the layering's first offer shows MM01's
    final quote as the best bid and ask."""
    layer_1 = base.orders["layer_1"]
    first = next(
        i
        for i, r in enumerate(base_recs)
        if r.topic == "order.new" and r.payload["id"] == layer_1
    )
    book = next(r for r in reversed(base_recs[:first]) if r.topic == "book.AAA")
    td = book.payload["tick_decimals"]
    best = (
        round(book.payload["bids"][0]["price"] * 10**td),
        round(book.payload["asks"][0]["price"] * 10**td),
    )
    assert best == aw.QUOTE_AFTER_BURST


def test_iceberg_refills_and_stop_links(base: World, base_recs: list[Rec]) -> None:
    refills = [
        r
        for r in base_recs
        if r.topic == "engine.trace.BBB"
        and r.payload["kind"] == "ICEBERG_REFILL"
        and r.payload["order_id"] == base.orders["iceberg"]
    ]
    assert len(refills) == aw.ICEBERG_REFILLS
    # Both stops trigger inside the chain of the sell that set them off: the
    # recorded link the replay draws as a causal cascade.
    push = next(
        r
        for r in base_recs
        if r.topic == "order.new" and r.payload["id"] == base.orders["stop_push"]
    )
    triggered = {
        r.payload["order_id"]: r.meta["chain"]
        for r in base_recs
        if r.topic.startswith("order.triggered.")
    }
    assert triggered == {
        base.orders["stop_1"]: push.meta["msg"],
        base.orders["stop_2"]: push.meta["msg"],
    }


def test_one_gap_free_run_with_envelopes(base: World, base_recs: list[Rec]) -> None:
    lines = raw_lines(base)
    assert lines[0].startswith("# edumatcher-audit format=1 ")
    assert not any(ln.startswith("# edumatcher-audit recorder-start") for ln in lines)
    assert len(runs(base_recs)) == 1
    eseqs = [int(r.meta["eseq"]) for r in base_recs]
    assert eseqs == list(range(1, len(eseqs) + 1))
    assert all("msg" in r.meta and "chain" in r.meta for r in base_recs)
    startup = base_recs[0]
    assert startup.topic == "system.startup" and startup.payload["config"]


def test_commands_precede_their_effects(base_recs: list[Rec]) -> None:
    """Each command is echoed before anything it caused (Engine._echo_command)."""
    seen: set[str] = set()
    for r in base_recs:
        if "cause" in r.meta:
            assert r.meta["cause"] in seen, r
        seen.add(r.meta["msg"])


def test_receipt_and_engine_clocks_are_pinned(
    base: World, base_recs: list[Rec]
) -> None:
    trades = [r for r in base_recs if r.topic == "trade.executed"]
    for r in trades:
        receipt = iso_ns(r.ts)
        assert receipt - r.payload["ts_ns"] == pytest.approx(aw.RECEIPT_LATENCY_NS, abs=aw.MS)  # fmt: skip
    assert min(base.marks.values()) >= aw.START_NS


# --- Variants ---------------------------------------------------------------


def test_gap_removes_one_contiguous_eseq_run(tmp_path: Path) -> None:
    world = build(tmp_path, gap=True)
    assert world.gap_eseq is not None
    first, last = world.gap_eseq
    assert last >= first
    eseqs = [int(r.meta["eseq"]) for r in records(world)]
    holes = [(a + 1, b - 1) for a, b in zip(eseqs, eseqs[1:]) if b != a + 1]
    assert holes == [(first, last)]


def test_restart_marks_one_recorder_restart_before_the_halt(tmp_path: Path) -> None:
    world = build(tmp_path, restart=True)
    lines = raw_lines(world)
    markers = [
        i
        for i, ln in enumerate(lines)
        if ln.startswith("# edumatcher-audit recorder-start")
    ]
    halt = next(i for i, ln in enumerate(lines) if "[risk.symbol_halt]" in ln)
    assert len(markers) == 1 and markers[0] < halt
    # Nothing was lost across the restart: the counters run on.
    eseqs = [int(r.meta["eseq"]) for r in records(world)]
    assert eseqs == list(range(1, len(eseqs) + 1))


def test_run_reset_starts_the_counters_again(tmp_path: Path) -> None:
    world = build(tmp_path, run_reset=True)
    recs = records(world)
    run_1, run_2 = runs(recs)
    assert [r.payload["run_seq"] for r in (run_1[0], run_2[0])] == [1, 2]
    assert int(run_2[0].meta["eseq"]) == 1  # the new engine counts from 1 again
    assert Counter(executions(run_1)) == Counter(aw.EXECUTIONS)
    assert executions(run_2) == list(aw.RUN_2_EXECUTIONS)
    run_2_ids = {r.payload["id"] for r in run_2 if r.topic == "trade.executed"}
    assert run_2_ids == aw.RUN_2_TRADE_IDS
    # TRADER02 sends an order id in run 2 that it already used in run 1.
    reused = world.orders["layer_1"]
    for run in (run_1, run_2):
        assert any(r.topic == "order.new" and r.payload["id"] == reused for r in run)


def test_no_config_startup_carries_no_config(tmp_path: Path) -> None:
    world = build(tmp_path, no_config=True)
    startup = records(world)[0]
    assert startup.topic == "system.startup"
    assert startup.payload.get("config") is None
    assert startup.payload.get("config_sha256") is None


def test_zstd_archive_holds_the_whole_session(tmp_path: Path) -> None:
    world = build(tmp_path, zstd_archive=True)
    assert [p.name for p in world.parts_dir.glob("*.zst")] == [
        f"audit-{aw.DAY}.log.zst"
    ]
    assert not list(world.parts_dir.glob("audit-*.log"))
    assert not any(
        ln.startswith("[") for ln in world.audit_log.read_text().splitlines()
    )
    assert verify(world.parts_dir) == []
    assert Counter(executions(records(world))) == Counter(aw.EXECUTIONS)


def test_torn_tail_ends_in_a_partial_line(tmp_path: Path) -> None:
    world = build(tmp_path, torn_tail=True)
    data = world.audit_log.read_bytes()
    assert not data.endswith(b"\n")
    tail = data.rsplit(b"\n", 1)[1].decode()
    assert tail.startswith("[") and _LINE.match(tail) is None
    assert Counter(executions(records(world))) == Counter(aw.EXECUTIONS)


def test_sim_context_news_and_value_jumps(tmp_path: Path) -> None:
    world = build(tmp_path, sim_context=True)
    assert world.news_db == world.data / "market_sim_news.db"
    with closing(sqlite3.connect(f"file:{world.news_db}?mode=ro", uri=True)) as conn:
        news = conn.execute(
            "SELECT id, ts_ns, targets, status, related_id FROM news_events "
            "ORDER BY ts_ns"
        ).fetchall()
        jumps = conn.execute("SELECT ts_ns, symbol FROM value_jumps").fetchall()
    by_id = {row[0]: row for row in news}
    statuses = [row[3] for row in news]
    assert sorted(statuses) == ["CONFIRMED", "RETRACTED", "RUMOUR", "RUMOUR"]
    for row in news:
        if row[3] != "RUMOUR":
            assert by_id[row[4]][3] == "RUMOUR"  # resolves an earlier rumour
            assert by_id[row[4]][1] < row[1]
    confirmed = next(row for row in news if row[3] == "CONFIRMED")
    assert json.loads(confirmed[2]) == ["AAA"]
    # The simulator stamped the confirmation SIM_CLOCK_OFFSET_NS after the
    # engine time the world marks for it; the value jump sits with it.
    assert confirmed[1] - world.marks["news_confirmed"] == aw.SIM_CLOCK_OFFSET_NS
    assert jumps == [(confirmed[1], "AAA")]


def test_forensics_report_has_every_status(tmp_path: Path) -> None:
    world = build(tmp_path, forensics_report=True)
    assert world.forensics_report is not None
    report = json.loads(world.forensics_report.read_text())
    assert {c["id"]: c["status"] for c in report["checks"]} == aw.FORENSICS_STATUSES
    failed = next(c for c in report["checks"] if c["status"] == "FAIL")
    assert failed["violations"] == len(failed["samples"]) >= 1
    assert (world.forensics_report.parent / "report.md").is_file()


def test_unknown_variant_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown audit world variant"):
        build(tmp_path, nonsense=True)


def test_build_is_fast_and_stays_inside_tmp_path(tmp_path: Path) -> None:
    def listing(root: Path) -> set[Path]:
        return set(root.rglob("*")) if root.exists() else set()

    before = listing(DATA_DIR)
    started = time.perf_counter()
    build(tmp_path / "w", **dict.fromkeys(aw.VARIANTS - {"zstd_archive"}, True))
    elapsed = time.perf_counter() - started
    assert listing(DATA_DIR) == before
    assert elapsed < 3.0


# --- API harness ------------------------------------------------------------


@pytest.fixture
def indexed(tmp_path: Path) -> Iterator[tuple[World, Path]]:
    world = build(tmp_path)
    db = tmp_path / "audit_index.db"
    build_index(db, world.audit_log)
    yield world, db


@pytest.mark.parametrize(
    ("key", "status", "code"),
    [
        (aw.ADMIN_KEY, 200, None),
        (aw.TRADER_KEY, 403, "ROLE_DENIED"),
        (aw.MARKET_MAKER_KEY, 403, "ROLE_DENIED"),
        (aw.READ_ONLY_KEY, 403, "READ_ONLY"),
    ],
)
def test_harness_keys_meet_the_admin_guard(
    indexed: tuple[World, Path], key: str, status: int, code: str | None
) -> None:
    """Through an existing ADMIN route over the world's own audit index."""
    world, db = indexed
    app = aw.make_audit_app(world, audit_db=db)
    oid = world.orders["layer_1"]
    got, _headers, body = asyncio.run(
        call(app, "GET", f"/api/v1/admin/orders/{oid}/audit", authorization=f"Bearer {key}")  # fmt: skip
    )
    assert got == status
    if code is None:
        assert body["order_id"] == oid and body["count"] >= 3
    else:
        assert body["error"]["code"] == code


# --- The planted defects look real to the shipped reader ---------------------


def _anomaly_codes(world: World) -> Counter[str]:
    _run, steps = reconstruct(iter_entries([world.audit_log]))
    return Counter(a.code for step in steps for a in step.anomalies)


def test_the_replay_finds_the_planted_gap_and_restart(tmp_path: Path) -> None:
    """pm-audit-replay's own detectors see the planted defects, so a later
    test that expects them in a read model is testing a realistic trail."""
    base = _anomaly_codes(build(tmp_path / "base"))
    assert base["ESEQ_GAP"] == 0 and base["RECORDER_RESTART"] == 0
    assert _anomaly_codes(build(tmp_path / "gap", gap=True))["ESEQ_GAP"] == 1
    restarted = _anomaly_codes(build(tmp_path / "restart", restart=True))
    assert restarted["RECORDER_RESTART"] == 1
