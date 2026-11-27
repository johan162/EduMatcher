"""The Audit GUI's market read models: ``/api/v1/audit/market/{symbol}/heatmap``
and ``/lifelines`` (Audit GUI AG3, design §9.4, §8).

Driven through the ASGI stack over the recorded audit world. Expectations
come from the world's tables and marks and from the raw lines read naively
(tests/test_audit_gui_world.py's reader), never from the routes' own output.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.query import iter_entries
from edumatcher.audit.rawlines import iso_ns
from edumatcher.audit.replay.facts import normalise
from edumatcher.audit.replay.ordering import ordered
from edumatcher.audit.service import market
from edumatcher.audit.service.capabilities import Reason
from edumatcher.audit.service.market import MarketModel
from edumatcher.audit.service.session import CapabilityUnavailable
from tests import audit_gui_world as aw
from tests.audit_gui_world import World, build, make_audit_app
from tests.test_api_gateway_audit import _get, _snapshot
from tests.test_audit_gui_world import Rec, records

SEC = aw.SEC
MS = aw.MS
#: The first record (system.startup) is received 1 ms after the engine starts.
FIRST = aw.START_NS + aw.RECEIPT_LATENCY_NS


def _at(mark: int) -> int:
    """Receipt time of the records a command at engine time *mark* made."""
    return mark + aw.RECEIPT_LATENCY_NS


def _ticks(price: float, decimals: int) -> int:
    return round(price * 10**decimals)


def _books(recs: list[Rec], symbol: str) -> list[tuple[int, dict[str, dict[int, int]]]]:
    """Every ``book.<symbol>`` observation: receipt ns, side -> {ticks: qty}."""
    out = []
    for r in recs:
        if r.topic == f"book.{symbol}":
            td = r.payload["tick_decimals"]
            out.append(
                (
                    iso_ns(r.ts),
                    {
                        side: {_ticks(lv["price"], td): lv["qty"] for lv in r.payload[side]}  # fmt: skip
                        for side in ("bids", "asks")
                    },
                )
            )
    return out


def _cells(column: dict[str, Any], side: str) -> dict[int, float]:
    return {price: qty for price, qty in column[side]}


def _column_at(body: dict[str, Any], t: int) -> dict[str, Any]:
    width = int(body["bin_ns"])
    return body["columns"][(t - int(body["from_ns"])) // width]


def _whole_seconds(recs: list[Rec]) -> tuple[int, int]:
    """A window from the first record, one-second bins, past the last."""
    last = iso_ns(recs[-1].ts)
    return FIRST, FIRST + (math.ceil((last - FIRST) / SEC) + 1) * SEC


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build(tmp_path_factory.mktemp("audit-world"))


@pytest.fixture(scope="module")
def recs(base: World) -> list[Rec]:
    return records(base)


@pytest.fixture(scope="module")
def app(base: World) -> Any:
    return make_audit_app(base)


@pytest.fixture(scope="module")
def sid(app: Any) -> str:
    return _snapshot(app)


def _heatmap(app: Any, sid: str, symbol: str, query: str = "") -> dict[str, Any]:
    status, body = _get(app, f"/market/{symbol}/heatmap?snapshot_id={sid}{query}")
    assert status == 200, body
    return body


def _lifelines(app: Any, sid: str, symbol: str, query: str = "") -> dict[str, Any]:
    status, body = _get(app, f"/market/{symbol}/lifelines?snapshot_id={sid}{query}")
    assert status == 200, body
    return body


# --- Depth heatmap -------------------------------------------------------------


@pytest.mark.parametrize("symbol", sorted(aw.TICK_DECIMALS))
def test_heatmap_cells_are_the_recorded_displayed_depth(
    app: Any, sid: str, recs: list[Rec], symbol: str
) -> None:
    """One-second bins on the world's one-second command clock: every bin an
    observation starts is that observation, level by level, in ticks."""
    start, end = _whole_seconds(recs)
    bins = (end - start) // SEC
    body = _heatmap(app, sid, symbol, f"&from={start}&to={end}&bins={bins}")
    assert (body["bin_ns"], body["bins"], body["clock"]) == (str(SEC), bins, "receipt")
    assert body["tick_decimals"] == aw.TICK_DECIMALS[symbol]
    observations = _books(recs, symbol)
    assert observations
    for t, sides in observations:
        column = _column_at(body, t)
        assert column["start_ns"] == str(t - (t - start) % SEC)
        assert column["observations"] == 1
        assert _cells(column, "bids") == sides["bids"], t
        assert _cells(column, "asks") == sides["asks"], t


def test_heatmap_levels_keep_integer_ticks_and_the_recorded_scale(
    app: Any, sid: str
) -> None:
    aaa = {lv["price_ticks"]: lv["price"] for lv in _heatmap(app, sid, "AAA")["levels"]}
    bbb = {lv["price_ticks"]: lv["price"] for lv in _heatmap(app, sid, "BBB")["levels"]}
    assert aaa[9985] == "99.85"
    assert aaa[10010] == "100.10"
    assert bbb[25100] == "2.5100"
    assert bbb[24500] == "2.4500"


def test_cadence_is_measured_and_bins_are_never_finer(
    app: Any, sid: str, recs: list[Rec]
) -> None:
    times = [t for t, _ in _books(recs, "AAA")]
    median = statistics.median(b - a for a, b in zip(times, times[1:]))
    body = _heatmap(app, sid, "AAA", "&bins=2000")
    cadence = body["cadence"]
    assert cadence["observations"] == len(times)
    assert cadence["median_interval_ns"] == str(int(median))
    assert cadence["min_interval_ns"] == str(
        min(b - a for a, b in zip(times, times[1:]))
    )
    # Asked for 2,000 bins over about 90 s: never finer than the median.
    span = int(body["to_ns"]) - int(body["from_ns"])
    assert body["requested_bins"] == 2000
    assert body["bin_ns"] == str(int(median))
    assert body["bins"] == math.ceil(span / median) == len(body["columns"])


def test_the_halt_is_masked_and_keeps_its_observed_book(
    app: Any, sid: str, base: World, recs: list[Rec]
) -> None:
    halt, resume = _at(base.marks["halt"]), _at(base.marks["resume"])
    start, end = _whole_seconds(recs)
    query = f"&from={start}&to={end}&bins={(end - start) // SEC}"
    body = _heatmap(app, sid, "AAA", query)
    assert {"kind": "halt", "from_ns": str(halt), "to_ns": str(resume)} == {
        k: m[k] for m in body["masks"] if m["kind"] == "halt" for k in ("kind", "from_ns", "to_ns")  # fmt: skip
    }
    for column in body["columns"]:
        inside = int(column["start_ns"]) < resume and int(column["end_ns"]) > halt
        assert ("halt" in column["masks"]) == inside, column["start_ns"]
    # The book observed as the halt began (MM01's ask cancelled) is evidence:
    # the bin is hatched, not emptied.
    halted = _column_at(body, halt)
    assert _cells(halted, "asks") == {}
    assert _cells(halted, "bids") == {9985: 50, 9900: 10}
    assert not any(m["kind"] == "halt" for m in _heatmap(app, sid, "BBB")["masks"])


def test_the_phase_band_starts_from_the_startup_checkpoint(app: Any, sid: str) -> None:
    """AGF1: no session.state precedes the first transition; the phase the
    engine started in comes from its STARTUP checkpoint."""
    phases = _heatmap(app, sid, "AAA")["phases"]
    assert [p["phase"] for p in phases] == ["CLOSED", *aw.PHASES]
    assert phases[0]["from_ns"] == str(FIRST)
    assert all(a["to_ns"] == b["from_ns"] for a, b in zip(phases, phases[1:]))


def test_a_phase_change_ends_an_observation(
    app: Any, sid: str, base: World, recs: list[Rec]
) -> None:
    """The opening uncross publishes no book: the auction's crossed book must
    not be drawn into continuous trading."""
    start, end = _whole_seconds(recs)
    body = _heatmap(app, sid, "AAA", f"&from={start}&to={end}&bins={(end - start) // SEC}")  # fmt: skip
    column = _column_at(body, _at(base.marks["phase_CONTINUOUS"]))
    assert (column["covered_ns"], column["observations"]) == ("0", 0)
    assert column["bids"] == column["asks"] == []
    assert column["age_ns"] is None


def test_a_gap_is_masked_and_never_interpolated(
    tmp_path: Path,
) -> None:
    world = build(tmp_path, gap=True)
    app = make_audit_app(world)
    sid = _snapshot(app)
    recs = records(world)
    assert world.gap_eseq is not None
    first_lost, last_lost = world.gap_eseq
    before = next(r for r in recs if r.meta.get("eseq") == str(first_lost - 1))
    after = next(r for r in recs if r.meta.get("eseq") == str(last_lost + 1))
    start, end = _whole_seconds(recs)
    body = _heatmap(app, sid, "AAA", f"&from={start}&to={end}&bins={(end - start) // SEC}")  # fmt: skip
    gaps = [m for m in body["masks"] if m["kind"] == "gap"]
    assert [(m["from_ns"], m["to_ns"]) for m in gaps] == [
        (str(iso_ns(before.ts)), str(iso_ns(after.ts)))
    ]
    # The plant removes burst_2's cancel and its order.cancelled; the book
    # published after them survives. The loss lies between the last record
    # of the first burst cancel and that book: the second before it.
    assert before.ts.startswith(aw.DAY) and after.topic == "book.AAA"
    lost = _column_at(body, _at(world.marks["burst_cancel_1"]))
    assert lost["masks"] == ["gap"]
    assert (lost["covered_ns"], lost["bids"]) == ("0", [])
    # The book recorded after the gap is valid again from its receipt.
    resumed = _column_at(body, iso_ns(after.ts))
    assert resumed["masks"] == []
    observed = dict(_books(recs, "AAA"))[iso_ns(after.ts)]
    assert _cells(resumed, "bids") == observed["bids"]
    assert resumed["covered_ns"] == str(SEC)


def test_an_observation_never_spans_an_engine_restart(tmp_path: Path) -> None:
    world = build(tmp_path, run_reset=True)
    app = make_audit_app(world)
    sid = _snapshot(app)
    recs = records(world)
    second = next(i for i, r in enumerate(recs) if r.topic == "system.startup" and i)
    down, up = iso_ns(recs[second - 1].ts), iso_ns(recs[second].ts)
    assert up - down >= 60 * SEC
    body = _heatmap(app, sid, "AAA", f"&from={down}&to={up}&bins=60")
    assert {c["covered_ns"] for c in body["columns"]} == {"0"}


# --- Order lifelines -------------------------------------------------------------


def _by_order(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for lf in body["lifelines"]:
        assert lf["order_id"] not in out
        out[lf["order_id"]] = lf
    return out


def _first(recs: list[Rec], prefix: str, oid: str) -> Rec:
    return next(
        r
        for r in recs
        if r.topic.startswith(prefix) and r.payload.get("order_id") == oid
    )


def test_lifelines_match_each_orders_recorded_life(
    app: Any, sid: str, base: World, recs: list[Rec]
) -> None:
    lines = {
        **_by_order(_lifelines(app, sid, "AAA")),
        **_by_order(_lifelines(app, sid, "BBB")),
    }
    for name, life in aw.LIVES.items():
        oid = base.orders[name]
        lf = lines[oid]
        end, _, reason = life.end.partition(":")
        assert (lf["gateway"], lf["side"], lf["filled_qty"]) == (
            life.gateway,
            life.side,
            life.filled,
        ), name
        assert (lf["end"], lf["end_reason"]) == (end, reason or None), name
        assert lf["start_ns"] == str(iso_ns(_first(recs, "order.ack.", oid).ts)), name
        assert lf["start_censored"] is False
        if end == "open":
            assert lf["end_ns"] is None
        else:
            terminal = next(
                r
                for r in recs
                if r.payload.get("order_id") == oid
                and r.topic.startswith(("order.cancelled.", "order.expired."))
                or r.payload.get("order_id") == oid
                and r.topic.startswith("order.fill.")
                and r.payload["status"] == "FILLED"
            )
            assert lf["end_ns"] == str(iso_ns(terminal.ts)), name
        segments = lf["segments"]
        assert segments[0]["start_ns"] == lf["start_ns"]
        assert all(a["end_ns"] == b["start_ns"] for a, b in zip(segments, segments[1:]))


def test_quote_legs_are_lifelines_with_their_end_reasons(app: Any, sid: str) -> None:
    mm = [
        lf for lf in _lifelines(app, sid, "AAA")["lifelines"] if lf["gateway"] == aw.MM
    ]
    # Five quotes, two legs each.
    assert len(mm) == 10
    assert {lf["quote_id"] for lf in mm} == {"Q1"}
    assert Counter((lf["end"], lf["end_reason"]) for lf in mm) == {
        # Three replacements of the two-sided quote.
        ("cancel.system", "QUOTE_REPLACED"): aw.SYSTEM_CANCELS["QUOTE_REPLACED"],
        # The halt cancels the fourth quote's ask (150 left).
        ("cancel.system", "CIRCUIT_BREAKER_HALT"): aw.SYSTEM_CANCELS[
            "CIRCUIT_BREAKER_HALT"
        ],
        # The fourth quote's bid is filled by the stop cascade's first sell.
        ("filled", None): 1,
        # The requote's two legs; the third expiry is TRADER01's stop_bid.
        ("expired", None): aw.EXPIRED_AT_CLOSE - 1,
    }
    # The fourth quote: 99.90 / 100.10 x 200 (the quoted spread after the burst).
    prices = {(lf["side"], lf["segments"][0]["price_ticks"]) for lf in mm}
    assert {
        ("BUY", aw.QUOTE_AFTER_BURST[0]),
        ("SELL", aw.QUOTE_AFTER_BURST[1]),
    } <= prices


def test_amendments_break_a_lifeline(app: Any, sid: str, base: World) -> None:
    lf = _by_order(_lifelines(app, sid, "BBB"))[base.orders["amend_bid"]]
    shape = tuple((s["price_ticks"], s["displayed_qty"]) for s in lf["segments"])
    assert shape == aw.AMENDMENTS["amend_bid"]
    assert [s["cause"] for s in lf["segments"]] == ["admission", "amend", "amend"]
    assert lf["end"] == "cancel.owner"


def test_fills_and_iceberg_refills_change_the_displayed_quantity(
    app: Any, sid: str, base: World
) -> None:
    bbb = _by_order(_lifelines(app, sid, "BBB"))
    iceberg = bbb[base.orders["iceberg"]]["segments"]
    assert [s["cause"] for s in iceberg].count("refill") == aw.ICEBERG_REFILLS
    assert {s["displayed_qty"] for s in iceberg} == {1000}
    aaa = _by_order(_lifelines(app, sid, "AAA"))
    # stop_bid rests 100 @ 99.85; the two stop sells take 20 and 30 in one
    # command, so the bar shows 50 for the rest of the day.
    stop_bid = aaa[base.orders["stop_bid"]]["segments"]
    assert [(s["price_ticks"], s["displayed_qty"]) for s in stop_bid] == [
        (9985, 100),
        (9985, 50),
    ]
    # An untriggered stop is held at its stop price and shows nothing.
    stop_1 = aaa[base.orders["stop_1"]]["segments"]
    assert (stop_1[0]["state"], stop_1[0]["price_ticks"], stop_1[0]["displayed_qty"]) == ("stop", 9990, 0)  # fmt: skip


def test_a_window_that_cuts_an_order_censors_it(
    app: Any, sid: str, base: World
) -> None:
    layering = base.marks["layering"]
    oid = base.orders["layer_1"]
    # layer_1 rests from the first layering command; its cancel comes four
    # commands later.
    cut = _by_order(_lifelines(app, sid, "AAA", f"&from={FIRST}&to={layering + 2 * SEC}"))  # fmt: skip
    lf = cut[oid]
    assert (lf["end"], lf["end_ns"], lf["end_reason"]) == ("censored", None, None)
    assert lf["segments"][-1]["end_ns"] == str(layering + 2 * SEC)
    late = _by_order(_lifelines(app, sid, "AAA", f"&from={layering + 2 * SEC}"))
    lf = late[oid]
    assert lf["start_censored"] is True
    assert lf["segments"][0]["start_ns"] == str(layering + 2 * SEC)
    assert lf["end"] == "cancel.owner"
    # Orders over before the window are not in it.
    assert base.orders["open_buy"] not in late


def test_lifelines_filter_by_gateway(app: Any, sid: str) -> None:
    body = _lifelines(app, sid, "AAA", f"&gateway={aw.T2}")
    assert body["gateway"] == aw.T2
    expected = {n for n, life in aw.LIVES.items() if (life.gateway, life.symbol) == (aw.T2, "AAA")}  # fmt: skip
    assert len(body["lifelines"]) == len(expected)
    assert {lf["gateway"] for lf in body["lifelines"]} == {aw.T2}


def test_lifelines_over_the_cap_are_aggregated_per_level(
    app: Any, sid: str, base: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    whole = _lifelines(app, sid, "BBB")
    assert whole["aggregated"] is False
    assert whole["levels"] == []
    total = sum(len(lf["segments"]) for lf in whole["lifelines"])
    assert whole["segments"] == total
    monkeypatch.setattr(market, "LIFELINE_SEGMENT_CAP", total - 1)
    capped = _lifelines(app, sid, "BBB")
    assert (capped["aggregated"], capped["lifelines"]) == (True, [])
    assert (capped["segment_cap"], capped["segments"]) == (total - 1, total)
    assert sum(lv["segments"] for lv in capped["levels"]) == total
    # amend_bid is the only order ever bid at 2.4500: once by price, once
    # by size.
    level = next(
        lv
        for lv in capped["levels"]
        if (lv["side"], lv["price_ticks"]) == ("BUY", 24500)
    )
    assert (level["orders"], level["segments"], level["max_displayed_qty"]) == (
        1,
        2,
        100,
    )
    assert level["ends"] == {"cancel.owner": 1}


def test_runs_keep_lifelines_apart(tmp_path: Path) -> None:
    world = build(tmp_path, run_reset=True)
    app = make_audit_app(world)
    sid = _snapshot(app)
    recs = records(world)
    body = _lifelines(app, sid, "AAA")
    reused = [
        lf for lf in body["lifelines"] if lf["order_id"] == world.orders["layer_1"]
    ]
    assert sorted((lf["run"], lf["end"]) for lf in reused) == [
        (0, "cancel.owner"),
        (1, "filled"),
    ]
    # The GTC bid rests when run 0 stops: open, ending with that run.
    second = next(i for i, r in enumerate(recs) if r.topic == "system.startup" and i)
    gtc = next(
        lf for lf in body["lifelines"] if lf["order_id"] == world.orders["gtc_bid"]
    )
    assert (gtc["run"], gtc["end"]) == (0, "open")
    assert gtc["segments"][-1]["end_ns"] == str(iso_ns(recs[second - 1].ts))
    # Run 1 trades against it without admitting it again.
    assert body["without_admission"] == 1


# --- Errors ---------------------------------------------------------------------


@pytest.mark.parametrize("route", ["heatmap", "lifelines"])
def test_market_errors(app: Any, sid: str, route: str) -> None:
    status, body = _get(app, f"/market/ZZZ/{route}?snapshot_id={sid}")
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_ENTITY")
    status, body = _get(app, f"/market/AAA/{route}?snapshot_id=s-00000000000000000000")
    assert (status, body["error"]["code"]) == (404, "UNKNOWN_SNAPSHOT")
    t = aw.START_NS
    status, body = _get(app, f"/market/AAA/{route}?snapshot_id={sid}&from={t}&to={t}")
    assert (status, body["error"]["code"], body["error"]["field"]) == (400, "VALIDATION", "to")  # fmt: skip


def test_heatmap_bins_are_bounded(app: Any, sid: str) -> None:
    for bins in (0, 2001):
        status, body = _get(app, f"/market/AAA/heatmap?snapshot_id={sid}&bins={bins}")
        assert (status, body["error"]["code"]) == (400, "VALIDATION")


# --- The model, below the routes -------------------------------------------------


def _facts(world: World) -> list[Any]:
    return list(ordered(normalise(iter_entries([world.audit_log]))))


def test_a_symbol_without_book_observations_says_so(base: World) -> None:
    facts = [f for f in _facts(base) if f.topic != "book.BBB"]
    model = MarketModel(facts)
    with pytest.raises(CapabilityUnavailable) as caught:
        model.heatmap("BBB", None, None, 10)
    assert caught.value.reason is Reason.NO_BOOK_OBSERVATIONS
    # Its lifelines need no book.
    assert model.lifelines("BBB", None, None, None)["lifelines"]


def test_an_oco_leg_cancelled_by_its_sibling_ends(tmp_path: Path) -> None:
    """``oco.cancelled`` is the only record that a sibling leg ended."""
    log = tmp_path / "audit.log"
    ack = (
        '{"order_id": "%s", "accepted": true, "symbol": "AAA", "side": "SELL", '
        '"order_type": "LIMIT", "qty": 10, "price_ticks": %d, "tick_decimals": 2, '
        '"request": "NEW"}'
    )
    log.write_text(
        "\n".join(
            [
                f"[2026-06-15T07:00:01.001+00:00] [order.ack.T1] [seq=1 eseq=1] {ack % ('leg-a', 10100)}",  # fmt: skip
                f"[2026-06-15T07:00:01.001+00:00] [order.ack.T1] [seq=2 eseq=2] {ack % ('leg-b', 10200)}",  # fmt: skip
                '[2026-06-15T07:00:02.001+00:00] [order.fill.T1] [seq=1 eseq=3] {"order_id": "leg-a", "fill_qty": 10, "remaining_qty": 0, "status": "FILLED", "symbol": "AAA"}',  # fmt: skip
                '[2026-06-15T07:00:02.001+00:00] [oco.cancelled.T1] [seq=1 eseq=4] {"gateway_id": "T1", "oco_id": "o1", "cancelled_order_id": "leg-b", "reason": "SIBLING_FILLED"}',  # fmt: skip
            ]
        )
        + "\n"
    )
    facts = list(ordered(normalise(iter_entries([log]))))
    lines = {lf["order_id"]: lf for lf in MarketModel(facts).lifelines("AAA", None, None, None)["lifelines"]}  # fmt: skip
    assert (
        lines["leg-a"]["end"],
        lines["leg-b"]["end"],
        lines["leg-b"]["end_reason"],
    ) == (
        "filled",
        "cancel.system",
        "SIBLING_FILLED",
    )


def test_a_book_without_a_recorded_scale_is_not_guessed(tmp_path: Path) -> None:
    log = tmp_path / "audit.log"
    log.write_text(
        '[2026-06-15T07:00:01.001+00:00] [book.AAA] [seq=1 eseq=1] {"symbol": "AAA", "bids": [{"price": 99.85, "qty": 5, "count": 1}], "asks": []}\n'  # fmt: skip
    )
    model = MarketModel(list(ordered(normalise(iter_entries([log])))))
    with pytest.raises(CapabilityUnavailable) as caught:
        model.heatmap("AAA", None, None, 10)
    assert caught.value.reason is Reason.NO_TICK_SCALE


def test_an_uncross_ends_an_observation(tmp_path: Path) -> None:
    """A reopen uncross changes the book without a phase change; with no
    book published after it, the halted book must not be drawn on."""
    log = tmp_path / "audit.log"
    book = '{"symbol": "AAA", "tick_decimals": 2, "bids": [{"price": 100.0, "qty": 5, "count": 1}], "asks": [{"price": 100.0, "qty": 5, "count": 1}]}'  # fmt: skip
    log.write_text(
        f"[2026-06-15T07:00:01.000+00:00] [book.AAA] [seq=1 eseq=1] {book}\n"
        '[2026-06-15T07:00:02.000+00:00] [auction.result.AAA] [seq=1 eseq=2] {"symbol": "AAA", "eq_price": 100.0, "eq_qty": 5, "reason": "REOPEN", "tick_decimals": 2, "eq_price_ticks": 10000}\n'  # fmt: skip
        '[2026-06-15T07:00:04.000+00:00] [trade.executed] [seq=1 eseq=3] {"id": "t", "symbol": "AAA", "price": 100.0, "quantity": 5, "tick_decimals": 2, "price_ticks": 10000}\n'  # fmt: skip
    )
    model = MarketModel(list(ordered(normalise(iter_entries([log])))))
    body = model.heatmap("AAA", None, None, 3)
    assert [c["covered_ns"] for c in body["columns"]] == [SEC, 0, 0]


def test_concurrent_first_reads_build_the_model_once(
    base: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GUI asks for the heatmap and the lifelines at once: on a cold
    session they must share one build, not run two (AG7 review)."""
    import threading
    import time

    from edumatcher.audit.service import session as session_module
    from edumatcher.audit.service.session import AuditService
    from edumatcher.audit.service.snapshot import AuditCollection

    builds: list[int] = []

    class Slow(MarketModel):
        def __init__(self, facts: Any) -> None:
            builds.append(1)
            time.sleep(0.2)  # widen the window two threads could both enter
            super().__init__(facts)

    monkeypatch.setattr(session_module, "MarketModel", Slow)
    service = AuditService([AuditCollection("world", base.data)], tmp_path / "store")
    sid = service.create("world").snapshot_id
    replay = service.session(sid)
    threads = [
        threading.Thread(target=replay.heatmap, args=("AAA", None, None, 10)),
        threading.Thread(target=replay.lifelines, args=("AAA", None, None, None)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(builds) == 1
