"""Acceptance tests for the reference matcher (workplan T2).

Each test is a worked example or a stated rule from the documentation, cited
in its docstring, replayed through ``tests/reference_matcher.py``. They make
the oracle trustworthy before it is used to judge the engine (T3): if one of
these fails, the reference — not the engine — has drifted from the docs.

Prices are ticks at 2 decimals (150.00 == 15000). Gateways are named after
their role in the example.
"""

from __future__ import annotations

import itertools

import pytest

from tests.reference_matcher import ReferenceMatcher, ROrder, RTrade

_ids = itertools.count(1)


def order(side: str, type_: str, qty: int, gw: str = "GW", **kw: object) -> ROrder:
    return ROrder(id=f"o{next(_ids)}", side=side, type=type_, qty=qty, gw=gw, **kw)  # type: ignore[arg-type]


def limit(side: str, qty: int, price: int, gw: str = "GW", **kw: object) -> ROrder:
    return order(side, "LIMIT", qty, gw, price=price, **kw)


def print_at(m: ReferenceMatcher, price: int) -> None:
    """Make one 1-lot trade print at *price* between two bystanders (any
    stops it fires trade after it, moving the last price on)."""
    m.submit(limit("SELL", 1, price, "PRINT_S"))
    start = len(m.trades)
    m.submit(limit("BUY", 1, price, "PRINT_B"))
    assert (m.trades[start].price, m.trades[start].qty) == (price, 1)


def fills(trades: list[RTrade]) -> list[tuple[str, str, int, int]]:
    return [(t.buy_id, t.sell_id, t.price, t.qty) for t in trades]


# ---------------------------------------------------------------------------
# The order book — participant guide part 1, "The Order Book"
# ---------------------------------------------------------------------------


def test_price_time_priority_three_bids_at_one_price() -> None:
    """Worked example — three bids at the same price."""
    m = ReferenceMatcher()
    a, b, c = (
        limit("BUY", q, 14990, gw)
        for q, gw in ((100, "GW01"), (200, "GW02"), (150, "GW03"))
    )
    for o in (a, b, c):
        m.submit(o)
    sell = limit("SELL", 250, 14990, "GW04")

    trades = m.submit(sell)

    assert fills(trades) == [(a.id, sell.id, 14990, 100), (b.id, sell.id, 14990, 150)]
    assert (a.remaining, b.remaining, c.remaining) == (0, 50, 150)
    assert [e[0] for e in m.book()["bids"]] == [b.id, c.id]


def test_trade_prints_at_the_resting_orders_price() -> None:
    """Step-by-step: "Trade price is the resting order's price" — an aggressor
    with a better limit gets the improvement."""
    m = ReferenceMatcher()
    bid = limit("BUY", 100, 15000, "GW01")
    m.submit(bid)
    trades = m.submit(limit("SELL", 100, 14900, "GW02"))
    assert [(t.price, t.qty, t.aggressor) for t in trades] == [(15000, 100, "SELL")]


# ---------------------------------------------------------------------------
# Order types — participant guide part 2, "Order Types"
# ---------------------------------------------------------------------------


def test_market_order_remainder_is_cancelled_with_a_reason() -> None:
    """MARKET: the unfilled remainder is discarded as a cancellation carrying
    INSUFFICIENT_LIQUIDITY; into an empty book it cancels in full."""
    m = ReferenceMatcher()
    m.submit(limit("SELL", 5, 10100, "R"))
    mkt = order("BUY", "MARKET", 8, "T")
    trades = m.submit(mkt)
    assert [(t.price, t.qty) for t in trades] == [(10100, 5)]
    assert (mkt.status, mkt.remaining, mkt.cancel_reason) == (
        "CANCELLED",
        3,
        "INSUFFICIENT_LIQUIDITY",
    )

    empty = order("SELL", "MARKET", 10, "T")
    assert ReferenceMatcher().submit(empty) == []
    assert (empty.status, empty.cancel_reason) == (
        "CANCELLED",
        "INSUFFICIENT_LIQUIDITY",
    )


def test_limit_order_rests_its_remainder() -> None:
    m = ReferenceMatcher()
    m.submit(limit("SELL", 4, 10000, "R"))
    buy = limit("BUY", 10, 10000, "T")
    m.submit(buy)
    assert (buy.status, buy.remaining) == ("PARTIAL", 6)
    assert m.book()["bids"] == [(buy.id, 10000, 6, 6)]


@pytest.mark.parametrize(
    "asks, filled, left_on_book",
    [
        # Example 1 — full fill
        ([(10000, 10), (10100, 10)], [(10000, 10)], [(10100, 10)]),
        # Example 2 — partial fill, remainder cancelled
        ([(10000, 5), (10100, 10)], [(10000, 5)], [(10100, 10)]),
        # Example 3 — no fill, entire order cancelled
        ([(10100, 10)], [], [(10100, 10)]),
    ],
)
def test_ioc_examples_1_to_3(asks, filled, left_on_book) -> None:
    m = ReferenceMatcher()
    for price, qty in asks:
        m.submit(limit("SELL", qty, price, "R"))
    ioc = order("BUY", "IOC", 10, "T", price=10000)

    trades = m.submit(ioc)

    assert [(t.price, t.qty) for t in trades] == filled
    assert [(e[1], e[2]) for e in m.book()["asks"]] == left_on_book
    assert m.book()["bids"] == []  # an IOC never rests
    assert ioc.status == ("FILLED" if ioc.remaining == 0 else "CANCELLED")


def test_ioc_example_4_multi_level_sweep() -> None:
    m = ReferenceMatcher()
    for price in (9900, 10000, 10100, 10200):
        m.submit(limit("SELL", 3, price, "R"))
    trades = m.submit(order("BUY", "IOC", 9, "T", price=10100))
    assert [(t.price, t.qty) for t in trades] == [(9900, 3), (10000, 3), (10100, 3)]
    assert [(e[1], e[2]) for e in m.book()["asks"]] == [(10200, 3)]


def test_fok_rejects_on_shortfall_and_fills_in_full_otherwise() -> None:
    """FOK: available < qty → rejected entirely; sufficient → executes in full."""
    m = ReferenceMatcher()
    m.submit(limit("SELL", 5, 10000, "R"))
    short = order("BUY", "FOK", 6, "T", price=10000)
    assert m.submit(short) == []
    assert short.status == "REJECTED"

    exact = order("BUY", "FOK", 5, "T", price=10000)
    assert [(t.price, t.qty) for t in m.submit(exact)] == [(10000, 5)]
    assert exact.status == "FILLED"


def test_fok_counts_hidden_iceberg_quantity() -> None:
    """FOK pre-check includes hidden iceberg reserve, not just the peak."""
    m = ReferenceMatcher()
    m.submit(order("SELL", "ICEBERG", 100, "R", price=10000, visible=10))
    fok = order("BUY", "FOK", 100, "T", price=10000)
    assert sum(t.qty for t in m.submit(fok)) == 100


@pytest.mark.parametrize("smp", ["CANCEL_AGGRESSOR", "CANCEL_BOTH"])
def test_fok_never_partially_fills_under_smp(smp: str) -> None:
    """Operator guide, FOK — "a self-match candidate can never cause a partial
    fill": the sweep would stop at the own order, so only what is ahead of it
    counts (workplan bug C)."""
    m = ReferenceMatcher()
    m.submit(limit("SELL", 3, 9900, "OTHER"))
    own = limit("SELL", 5, 10000, "ME")
    m.submit(own)
    m.submit(limit("SELL", 10, 10100, "OTHER"))
    fok = order("BUY", "FOK", 10, "ME", price=10100, smp=smp)

    assert m.submit(fok) == []
    assert (fok.status, fok.cancel_reason) == ("CANCELLED", "SELF_MATCH_PREVENTED")
    assert own.status == ("CANCELLED" if smp == "CANCEL_BOTH" else "NEW")


def test_fok_with_cancel_resting_shortfall_is_rejected_and_clears_own_orders() -> None:
    m = ReferenceMatcher()
    m.submit(limit("SELL", 50, 10000, "OTHER"))
    own = limit("SELL", 50, 10000, "ME")
    m.submit(own)
    fok = order("BUY", "FOK", 100, "ME", price=10000, smp="CANCEL_RESTING")
    assert m.submit(fok) == []
    assert fok.status == "REJECTED"
    assert own.status == "CANCELLED"


def test_iceberg_shows_its_peak_and_replenishes_at_the_back() -> None:
    """ICEBERG: only VISIBLE is shown; a consumed peak is replenished with a
    new arrival_seq, behind every other order at that price."""
    m = ReferenceMatcher()
    ice = order("SELL", "ICEBERG", 30, "I", price=10000, visible=10)
    m.submit(ice)
    lim = limit("SELL", 5, 10000, "L")
    m.submit(lim)
    assert m.book()["asks"] == [(ice.id, 10000, 30, 10), (lim.id, 10000, 5, 5)]

    trades = m.submit(limit("BUY", 12, 10000, "T"))

    assert [(t.sell_id, t.qty) for t in trades] == [(ice.id, 10), (lim.id, 2)]
    assert m.book()["asks"] == [(lim.id, 10000, 3, 3), (ice.id, 10000, 20, 10)]


def test_incoming_iceberg_trades_its_full_quantity() -> None:
    """ICEBERG (rule G4): one execution per resting counterparty; the
    remainder rests behind a full peak."""
    m = ReferenceMatcher()
    a1, a2 = limit("SELL", 30, 10000, "R1"), limit("SELL", 25, 10100, "R2")
    m.submit(a1)
    m.submit(a2)
    ice = order("BUY", "ICEBERG", 100, "I", price=10100, visible=10)

    trades = m.submit(ice)

    assert [(t.sell_id, t.price, t.qty) for t in trades] == [
        (a1.id, 10000, 30),
        (a2.id, 10100, 25),
    ]
    assert m.book()["bids"] == [(ice.id, 10100, 45, 10)]


# ---------------------------------------------------------------------------
# Stops — participant guide, "Stop Trigger Logic"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "side, at, triggers",
    [
        ("BUY", 10000, True),
        ("BUY", 9999, False),
        ("SELL", 10000, True),
        ("SELL", 10001, False),
    ],
)
def test_trigger_conditions_include_the_stop_price(
    side: str, at: int, triggers: bool
) -> None:
    """Trigger Conditions: BUY last >= stop, SELL last <= stop."""
    m = ReferenceMatcher()
    stop = order(side, "STOP", 1, "S", stop=10000)
    m.submit(stop)
    # Liquidity for the triggered stop, away from the print price.
    depth_side, depth_price = ("SELL", at + 500) if side == "BUY" else ("BUY", at - 500)
    m.submit(limit(depth_side, 5, depth_price, "DEPTH"))
    print_at(m, at)
    assert (stop.status == "FILLED") is triggers


def test_scenario_a_sell_stop_triggers_and_slips() -> None:
    m = ReferenceMatcher()
    print_at(m, 14950)
    stop = order("SELL", "STOP", 100, "S", stop=14800)
    m.submit(stop)
    m.submit(limit("BUY", 100, 14700, "BIDS"))
    print_at(m, 14720)  # 147.20 <= 148.00
    assert stop.type == "MARKET" and stop.status == "FILLED"
    assert m.trades[-1].price == 14700  # filled below the stop: slippage


def test_scenario_b_stop_limit_triggers_and_rests_unfilled() -> None:
    m = ReferenceMatcher()
    print_at(m, 14950)
    stop = order("SELL", "STOP_LIMIT", 100, "S", stop=14800, price=14750)
    m.submit(stop)
    m.submit(limit("BUY", 100, 14690, "BIDS"))
    print_at(m, 14780)  # triggers; best bid 146.90 is below the 147.50 limit
    assert (stop.type, stop.status, stop.remaining) == ("LIMIT", "NEW", 100)
    assert m.book()["asks"][0][:3] == (stop.id, 14750, 100)


def test_scenario_c_one_print_fires_several_stops_highest_first() -> None:
    """Scenario C, ordered by rule G2: SELL stops highest stop price first."""
    m = ReferenceMatcher()
    print_at(m, 15000)
    stops = [order("SELL", "STOP", 100, f"S{p}", stop=p) for p in (14700, 14900, 14800)]
    for s in stops:
        m.submit(s)
    m.submit(limit("BUY", 1000, 14000, "BIDS"))
    print_at(m, 14700)
    fired = [t.sell_id for t in m.trades[-3:]]
    assert fired == [stops[1].id, stops[2].id, stops[0].id]  # 149, 148, 147


def test_stop_breached_on_entry_triggers_immediately() -> None:
    """Rule G3, for all three stop types."""
    for type_, extra in (
        ("STOP", {}),
        ("STOP_LIMIT", {"price": 9900}),
        ("TRAILING_STOP", {"trail": 300}),
    ):
        m = ReferenceMatcher()
        print_at(m, 10000)
        m.submit(limit("BUY", 10, 9900, "BIDS"))
        stop = order("SELL", type_, 5, "S", stop=10100, **extra)
        trades = m.submit(stop)
        assert [(t.price, t.qty) for t in trades] == [(9900, 5)], type_


def test_stop_entered_while_not_matching_skips_the_entry_check() -> None:
    """Rule G8: stored, and evaluated after the next trade."""
    m = ReferenceMatcher()
    print_at(m, 10000)
    stop = order("SELL", "STOP", 5, "S", stop=10100)
    m.submit(stop, matching=False)
    assert stop.status == "NEW" and stop in m.stops


def test_stop_cascade() -> None:
    """Trigger Cascades: a triggered stop's executions trigger further stops."""
    m = ReferenceMatcher()
    print_at(m, 10000)
    s1, s2 = order("SELL", "STOP", 5, "S1", stop=9900), order(
        "SELL", "STOP", 5, "S2", stop=9800
    )
    m.submit(s1)
    m.submit(s2)
    m.submit(limit("BUY", 5, 9800, "B1"))
    m.submit(limit("BUY", 5, 9700, "B2"))
    print_at(m, 9900)  # fires s1, which prints at 98.00 and fires s2
    assert (s1.status, s2.status) == ("FILLED", "FILLED")
    assert [t.price for t in m.trades[-2:]] == [9800, 9700]


def test_trailing_stop_example_1_rally_then_drop() -> None:
    m = ReferenceMatcher()
    print_at(m, 10000)
    ts = order("SELL", "TRAILING_STOP", 100, "T", stop=9800, trail=200)
    m.submit(ts)
    print_at(m, 10500)
    assert ts.stop == 10300
    print_at(m, 11000)
    assert ts.stop == 10800
    m.submit(limit("BUY", 100, 9000, "BIDS"))
    print_at(m, 10200)  # 102 <= 108 → triggered → MARKET SELL
    assert ts.status == "FILLED"


def test_trailing_stop_example_2_never_moves_down() -> None:
    m = ReferenceMatcher()
    print_at(m, 10000)
    ts = order("SELL", "TRAILING_STOP", 100, "T", stop=9800, trail=200)
    m.submit(ts)
    print_at(m, 10600)
    assert ts.stop == 10400
    m.submit(limit("BUY", 100, 9000, "BIDS"))
    print_at(m, 9500)
    assert ts.stop == 10400  # not lowered to 93 before the trigger check
    assert ts.status == "FILLED"


def test_trailing_stop_example_3_buy_side() -> None:
    m = ReferenceMatcher()
    print_at(m, 5000)
    ts = order("BUY", "TRAILING_STOP", 100, "T", stop=5300, trail=300)
    m.submit(ts)
    print_at(m, 4500)
    assert ts.stop == 4800
    print_at(m, 4000)
    assert ts.stop == 4300
    m.submit(limit("SELL", 100, 6000, "ASKS"))
    print_at(m, 4400)  # 44 >= 43 → triggered → MARKET BUY
    assert ts.status == "FILLED"


def test_trailing_stop_ratchets_once_per_incoming_order() -> None:
    """Rule G1: a multi-level sweep ratchets to its last print only."""
    m = ReferenceMatcher()
    print_at(m, 9000)
    ts = order("BUY", "TRAILING_STOP", 5, "T", stop=11000, trail=500)
    m.submit(ts)
    for p in (10000, 10100, 10200):
        m.submit(limit("SELL", 1, p, "R"))
    m.submit(limit("BUY", 3, 10200, "Q"))
    assert ts.stop == 10700  # 102 + 5, not 100 + 5


# ---------------------------------------------------------------------------
# Amendment — participant guide, "Order Amendment (AMEND)"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "price, qty, keeps_priority",
    [(None, 80, True), (None, 120, False), (10100, None, False), (9900, 50, False)],
)
def test_amend_priority_rules(price, qty, keeps_priority) -> None:
    m = ReferenceMatcher()
    first, second = limit("BUY", 100, 10000, "A"), limit("BUY", 100, 10000, "B")
    m.submit(first)
    m.submit(second)
    assert m.amend(first.id, price=price, qty=qty)
    if price is None:  # same level: is `first` still ahead of `second`?
        assert (m.book()["bids"][0][0] == first.id) is keeps_priority
    else:
        assert first.seq > second.seq


def test_amend_example_sequence() -> None:
    """Examples 1-4: QTY is the new total; remaining = QTY - filled."""
    m = ReferenceMatcher()
    o = limit("BUY", 100, 15000, "T")
    m.submit(o)
    assert m.amend(o.id, price=15100)
    assert m.amend(o.id, qty=80)
    m.submit(limit("SELL", 30, 15100, "R"))
    assert m.amend(o.id, qty=60)
    assert (o.qty, o.remaining) == (60, 30)
    assert not m.amend(o.id, qty=30)  # must exceed the filled 30


def test_amend_that_crosses_fills_immediately() -> None:
    m = ReferenceMatcher()
    m.submit(limit("SELL", 10, 15000, "R"))
    o = limit("BUY", 10, 14900, "T")
    m.submit(o)
    assert m.amend(o.id, price=15050)
    assert o.status == "FILLED"
    assert m.trades[-1].price == 15000


def test_amend_while_not_matching_rests_crossed() -> None:
    m = ReferenceMatcher()
    m.submit(limit("SELL", 10, 15000, "R"))
    o = limit("BUY", 10, 14900, "T")
    m.submit(o)
    assert m.amend(o.id, price=15050, matching=False)
    assert o.status == "NEW" and m.trades == []


def test_iceberg_qty_decrease_does_not_refill_the_peak() -> None:
    """Edge cases table: a qty decrease never enlarges the current peak."""
    m = ReferenceMatcher()
    ice = order("SELL", "ICEBERG", 100, "I", price=10000, visible=10)
    m.submit(ice)
    m.submit(limit("BUY", 6, 10000, "T"))
    assert m.amend(ice.id, qty=90)
    assert (ice.remaining, ice.shown) == (84, 4)


# ---------------------------------------------------------------------------
# Self-match prevention — operator guide, "Self-Match Prevention (SMP)"
# ---------------------------------------------------------------------------


def test_smp_cancel_aggressor_keeps_earlier_fills() -> None:
    m = ReferenceMatcher()
    m.submit(limit("SELL", 3, 9900, "OTHER"))
    own = limit("SELL", 5, 10000, "ME")
    m.submit(own)
    agg = limit("BUY", 10, 10100, "ME", smp="CANCEL_AGGRESSOR")
    assert [(t.price, t.qty) for t in m.submit(agg)] == [(9900, 3)]
    assert (agg.status, agg.cancel_reason, own.status) == (
        "CANCELLED",
        "SELF_MATCH_PREVENTED",
        "NEW",
    )


def test_smp_cancel_resting_continues_the_sweep() -> None:
    m = ReferenceMatcher()
    own = limit("SELL", 5, 10000, "ME")
    m.submit(own)
    m.submit(limit("SELL", 10, 10000, "OTHER"))
    agg = limit("BUY", 10, 10000, "ME", smp="CANCEL_RESTING")
    assert [(t.price, t.qty) for t in m.submit(agg)] == [(10000, 10)]
    assert (own.status, own.cancel_reason, agg.status) == (
        "CANCELLED",
        "SELF_MATCH_PREVENTED",
        "FILLED",
    )


def test_smp_cancel_both_and_none() -> None:
    m = ReferenceMatcher()
    own = limit("SELL", 5, 10000, "ME")
    m.submit(own)
    agg = limit("BUY", 5, 10000, "ME", smp="CANCEL_BOTH")
    assert m.submit(agg) == []
    assert own.status == agg.status == "CANCELLED"

    m.submit(limit("SELL", 5, 10000, "ME"))
    assert (
        len(m.submit(limit("BUY", 5, 10000, "ME", smp="NONE"))) == 1
    )  # self-trade allowed


def test_smp_cancels_a_resting_iceberg_whole() -> None:
    """Rule G5: peak and hidden reserve go as one order."""
    m = ReferenceMatcher()
    ice = order("SELL", "ICEBERG", 100, "ME", price=10000, visible=10)
    m.submit(ice)
    m.submit(limit("BUY", 5, 10000, "ME", smp="CANCEL_RESTING"))
    assert ice.status == "CANCELLED" and m.book()["asks"] == []


# ---------------------------------------------------------------------------
# Auctions — operator guide "Equilibrium price", participant guide "A Full
# Trading Day"
# ---------------------------------------------------------------------------


def _collect(m: ReferenceMatcher, rows: list[tuple[str, int, int]]) -> list[ROrder]:
    orders = [
        limit(side, qty, price, f"G{i}") for i, (side, qty, price) in enumerate(rows)
    ]
    for o in orders:
        m.submit(o, matching=False)
    return orders


def test_operator_guide_worked_example() -> None:
    m = ReferenceMatcher()
    _collect(
        m,
        [
            ("BUY", 10, 105),
            ("BUY", 10, 103),
            ("BUY", 10, 100),
            ("SELL", 15, 102),
            ("SELL", 10, 104),
        ],
    )
    assert m.equilibrium() == (102, 15, 5, "BUY")
    trades = m.uncross()
    assert sum(t.qty for t in trades) == 15
    assert {t.price for t in trades} == {102}
    assert {t.aggressor for t in trades} == {"AUCTION"}


def test_hands_on_tie_picks_the_lower_price() -> None:
    m = ReferenceMatcher()
    _collect(m, [("BUY", 100, 15000), ("SELL", 100, 14950)])
    assert m.equilibrium()[:2] == (14950, 100)


def test_participant_guide_opening_auction() -> None:
    m = ReferenceMatcher()
    pre_open, ato_buy, gw02, gw03 = _collect(
        m,
        [
            ("BUY", 200, 14950),
            ("BUY", 500, 15000),
            ("SELL", 300, 14980),
            ("SELL", 400, 14950),
        ],
    )
    assert m.equilibrium()[:3] == (14980, 500, 200)
    m.uncross()
    assert ato_buy.status == "FILLED" and gw03.status == "FILLED"
    assert (gw02.remaining, pre_open.remaining) == (200, 200)


def test_uncross_counts_hidden_iceberg_quantity_behind_visible() -> None:
    """Icebergs in the uncross: hidden quantity takes part, behind the
    visible orders at its price; the indicative is what prints."""
    m = ReferenceMatcher()
    ice = order("SELL", "ICEBERG", 30, "I", price=100, visible=10)
    m.submit(ice, matching=False)
    lim, buy = _collect(m, [("SELL", 20, 100), ("BUY", 50, 100)])
    assert m.equilibrium()[:2] == (100, 50)
    assert [(t.sell_id, t.qty) for t in m.uncross()] == [
        (ice.id, 10),
        (lim.id, 20),
        (ice.id, 10),
        (ice.id, 10),
    ]


def test_no_smp_in_the_uncross() -> None:
    """Rule G6."""
    m = ReferenceMatcher()
    for side in ("BUY", "SELL"):
        m.submit(limit(side, 10, 100, "SAME", smp="CANCEL_BOTH"), matching=False)
    assert [t.qty for t in m.uncross()] == [10]


def test_stops_are_evaluated_after_the_uncross_print() -> None:
    """Session-Phase Interaction: stop evaluations run after uncross trades."""
    m = ReferenceMatcher()
    stop = order("BUY", "STOP", 5, "S", stop=100)
    m.submit(stop, matching=False)
    _collect(m, [("BUY", 10, 100), ("SELL", 10, 100), ("SELL", 5, 105)])
    m.uncross()
    assert stop.status == "FILLED" and m.trades[-1].price == 105


def test_immediate_types_are_rejected_while_not_matching() -> None:
    m = ReferenceMatcher()
    for type_, kw in (("MARKET", {}), ("IOC", {"price": 100}), ("FOK", {"price": 100})):
        o = order("BUY", type_, 1, "T", **kw)
        m.submit(o, matching=False)
        assert o.status == "REJECTED", type_
