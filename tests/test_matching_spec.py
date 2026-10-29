"""
Specification scenarios for matching, run on both sides of the book.

Hand-written, readable scenarios that act as executable documentation of the
participant guide (order book, order types, the trading day and auctions).
Each one drives the real ``Engine`` (through ``tests/engine_harness.py``)
and asserts what a participant sees: the full trade tape (counterparties,
price, quantity, aggressor), the resting book, dormant stops, the auction
result and the order events.

Every scenario is written once, from the side named in it, and runs twice:
``as-written`` and ``mirrored``, where BUY and SELL swap and every price is
reflected around 100.00 (10000 ticks). The ``Venue`` translates in both
directions, so the expected values are always in the as-written orientation.
A rule broken on one side only (mutant M07, a SELL-stop off-by-one) fails
one of the two runs.

The one rule that is not mirror-symmetric is the auction's last tie-break,
the lowest price: that test states its expectation in actual prices.

Background: docs-design/EduMatcher-Matching-Test-Quality-Workplan.md (T5).
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, SmpAction, TIF
from edumatcher.models.price import from_ticks, to_ticks

from tests.engine_harness import SYMBOL, connect, make_engine

GATEWAYS = ("GW01", "GW02", "GW03")
MID = 10000  # ticks (100.00): the mirror axis

_DEAD = (
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
)
_OTHER = {"BUY": "SELL", "SELL": "BUY"}

Fill = tuple[str, str, int, int, str]  # (buy id, sell id, price, qty, aggressor)
Resting = tuple[str, int | None, int, int | None]  # (id, price, remaining, shown)


class Venue:
    """One engine, seen in the as-written orientation of a scenario."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any, mirrored: bool
    ) -> None:
        self.mirrored = mirrored
        self.engine, self.pub = make_engine(
            monkeypatch, tmp_path, gateways=GATEWAYS, sessions_enabled=True
        )
        connect(self.engine, *GATEWAYS)
        self.phase("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
        self._start = len(self.pub.sent)

    # --- orientation ---------------------------------------------------

    def side(self, side: str) -> str:
        return _OTHER[side] if self.mirrored else side

    def px(self, ticks: int) -> int:
        """As-written price → actual price (the mapping is its own inverse)."""
        return 2 * MID - ticks if self.mirrored else ticks

    def _px(self, ticks: int | None) -> int | None:
        return None if ticks is None else self.px(ticks)

    # --- actions -------------------------------------------------------

    def submit(
        self,
        side: str,
        type_: str,
        qty: int,
        gw: str = "GW01",
        *,
        price: int | None = None,
        stop: int | None = None,
        trail: int | None = None,
        visible: int | None = None,
        smp: str = "NONE",
        tif: str = "DAY",
    ) -> str:
        order = Order.create(
            symbol=SYMBOL,
            side=Side(self.side(side)),
            order_type=OrderType(type_),
            quantity=qty,
            gateway_id=gw,
            tif=TIF(tif),
            price_ticks=self._px(price),
            stop_price_ticks=self._px(stop),
            trail_offset_ticks=trail,
            visible_qty=visible,
            smp_action=SmpAction(smp),
        )
        self.engine._handle_new_order(order.to_dict())
        return order.id

    def cancel(self, order_id: str, gw: str) -> None:
        self.engine._handle_cancel({"order_id": order_id, "gateway_id": gw})

    def amend(
        self,
        order_id: str,
        gw: str,
        *,
        price: int | None = None,
        qty: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"order_id": order_id, "gateway_id": gw}
        if price is not None:
            payload["price"] = from_ticks(self.px(price), SYMBOL)
        if qty is not None:
            payload["qty"] = qty
        self.engine._handle_amend(payload)

    def phase(self, *states: str) -> None:
        for state in states:
            self.engine._handle_session_transition({"to_state": state})

    def print_at(self, price: int) -> tuple[str, str]:
        """One 1-lot print at *price* between two bystander orders of GW03.
        Returns (buy id, sell id)."""
        sell = self.submit("SELL", "LIMIT", 1, "GW03", price=price)
        buy = self.submit("BUY", "LIMIT", 1, "GW03", price=price)
        return buy, sell

    # --- what was published since the venue opened ---------------------

    def published(self, topic: str) -> list[dict[str, Any]]:
        """Payloads of every message on exactly *topic*."""
        out = []
        for frames in self.pub.sent[self._start :]:
            t, payload = decode(frames)
            if t == topic:
                out.append(payload)
        return out

    def trades(self) -> list[Fill]:
        """The trade tape, as written: (buy id, sell id, price, qty, aggressor)."""
        tape: list[Fill] = []
        for p in self.published("trade.executed"):
            buy, sell = p["buy_order_id"], p["sell_order_id"]
            aggressor = p["aggressor_side"]
            if self.mirrored:
                buy, sell = sell, buy
                aggressor = _OTHER.get(aggressor, aggressor)
            tape.append(
                (buy, sell, self.px(p["price_ticks"]), p["quantity"], aggressor)
            )
        return tape

    def book(self) -> dict[str, list[Resting]]:
        """Resting orders per as-written side, in priority order:
        (id, price, remaining, shown)."""
        book = self.engine._book(SYMBOL)
        out = {}
        for side, heap in (("BUY", book._bids), ("SELL", book._asks)):
            live = sorted(
                (e for e in heap if e.valid and e.order.status not in _DEAD),
                key=lambda e: e.key,
            )
            out[self.side(side)] = [
                (
                    e.order.id,
                    self._px(e.order.price_ticks),
                    e.order.remaining_qty,
                    (
                        e.order.displayed_qty
                        if e.order.order_type == OrderType.ICEBERG
                        else e.order.remaining_qty
                    ),
                )
                for e in live
            ]
        return out

    def stops(self) -> dict[str, int]:
        """Dormant stops: id → (ratcheted) trigger price, as written."""
        book = self.engine._book(SYMBOL)
        orders = [e.order for e in book._buy_stops + book._sell_stops if e.valid]
        orders += book._trailing_stops
        return {
            o.id: self.px(o.stop_price_ticks)
            for o in orders
            if o.status not in _DEAD and o.stop_price_ticks is not None
        }

    def auction(self) -> tuple[int | None, int, int, str]:
        """The last auction result: (price as written, qty, surplus, side)."""
        r = self.published(f"auction.result.{SYMBOL}")[-1]
        price = (
            None if r["eq_price"] is None else self.px(to_ticks(r["eq_price"], SYMBOL))
        )
        side = r.get("imbalance_side", "")  # omitted when balanced
        return price, r["eq_qty"], r["imbalance_qty"], self.side(side) if side else ""

    def event(self, kind: str, gw: str, order_id: str) -> dict[str, Any] | None:
        """The one ``order.<kind>.<gw>`` message about *order_id*, if any."""
        found = [
            p for p in self.published(f"order.{kind}.{gw}") if p["order_id"] == order_id
        ]
        assert len(found) <= 1, found
        return found[0] if found else None


@pytest.fixture(params=[False, True], ids=["as-written", "mirrored"])
def v(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> Venue:
    return Venue(monkeypatch, tmp_path, request.param)


# ---------------------------------------------------------------------------
# Price-time priority and the trade price — participant guide, The Order Book
# ---------------------------------------------------------------------------


def test_time_priority_at_one_price_then_the_next_level(v: Venue) -> None:
    """Three asks at one price fill in arrival order, then the sweep moves to
    the next level; each fill prints at its resting order's price."""
    a = v.submit("SELL", "LIMIT", 10, "GW01", price=10010)
    b = v.submit("SELL", "LIMIT", 20, "GW02", price=10010)
    c = v.submit("SELL", "LIMIT", 30, "GW03", price=10010)
    d = v.submit("SELL", "LIMIT", 10, "GW01", price=10020)

    buy = v.submit("BUY", "LIMIT", 65, "GW02", price=10020)

    assert v.trades() == [
        (buy, a, 10010, 10, "BUY"),
        (buy, b, 10010, 20, "BUY"),
        (buy, c, 10010, 30, "BUY"),
        (buy, d, 10020, 5, "BUY"),
    ]
    assert v.book() == {"BUY": [], "SELL": [(d, 10020, 5, 5)]}
    # The VWAP the owner is told: Σ price × qty over its fills.
    last = [p for p in v.published("order.fill.GW02") if p["order_id"] == buy][-1]
    assert (last["cum_qty"], last["cum_notional_ticks"]) == (
        65,
        60 * v.px(10010) + 5 * v.px(10020),
    )


def test_a_limit_trades_at_its_own_limit_and_not_one_tick_through(v: Venue) -> None:
    at = v.submit("SELL", "LIMIT", 10, "GW01", price=10010)
    beyond = v.submit("SELL", "LIMIT", 10, "GW01", price=10011)

    buy = v.submit("BUY", "LIMIT", 20, "GW02", price=10010)

    assert v.trades() == [(buy, at, 10010, 10, "BUY")]
    assert v.book() == {
        "BUY": [(buy, 10010, 10, 10)],
        "SELL": [(beyond, 10011, 10, 10)],
    }


def test_the_aggressor_gets_the_resting_price(v: Venue) -> None:
    """Price improvement: a SELL limited at 99.80 hits a bid at 99.90 and
    prints at 99.90."""
    bid = v.submit("BUY", "LIMIT", 10, "GW01", price=9990)
    sell = v.submit("SELL", "LIMIT", 10, "GW02", price=9980)
    assert v.trades() == [(bid, sell, 9990, 10, "SELL")]


# ---------------------------------------------------------------------------
# Stops — participant guide, Order Types → Stop Trigger Logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "print_price, triggers",
    [(10009, False), (10010, True), (10011, True)],
    ids=["one-tick-before", "exactly-at", "one-tick-through"],
)
def test_a_buy_stop_triggers_at_or_through_its_stop_price(
    v: Venue, print_price: int, triggers: bool
) -> None:
    """A BUY stop triggers when the last price is at or above its stop (a
    SELL stop, in the mirrored run, at or below)."""
    ask = v.submit("SELL", "LIMIT", 100, "GW01", price=10050)
    stop = v.submit("BUY", "STOP", 10, "GW02", stop=10010)

    pb, ps = v.print_at(print_price)

    tape = [(pb, ps, print_price, 1, "BUY")]
    if triggers:
        assert v.trades() == tape + [(stop, ask, 10050, 10, "BUY")]
        assert v.stops() == {}
    else:
        assert v.trades() == tape
        assert v.stops() == {stop: 10010}


@pytest.mark.parametrize(
    "type_, extra",
    [
        ("STOP", {}),
        ("STOP_LIMIT", {"price": 10050}),
        ("TRAILING_STOP", {"trail": 5}),
    ],
)
def test_a_stop_already_breached_on_entry_triggers_at_once(
    v: Venue, type_: str, extra: dict[str, Any]
) -> None:
    """Rule G3: no waiting for the next trade."""
    ask = v.submit("SELL", "LIMIT", 100, "GW01", price=10050)
    pb, ps = v.print_at(10010)

    stop = v.submit("BUY", type_, 10, "GW02", stop=10005, **extra)

    assert v.trades() == [(pb, ps, 10010, 1, "BUY"), (stop, ask, 10050, 10, "BUY")]
    assert v.stops() == {}


def test_a_cascade_of_three_stops(v: Venue) -> None:
    """Each triggered stop's print triggers the next one."""
    a20 = v.submit("SELL", "LIMIT", 10, "GW01", price=10020)
    a30 = v.submit("SELL", "LIMIT", 10, "GW01", price=10030)
    a40 = v.submit("SELL", "LIMIT", 10, "GW01", price=10040)
    s3 = v.submit("BUY", "STOP", 10, "GW02", stop=10030)
    s1 = v.submit("BUY", "STOP", 10, "GW02", stop=10010)
    s2 = v.submit("BUY", "STOP", 10, "GW02", stop=10020)

    pb, ps = v.print_at(10010)

    assert v.trades() == [
        (pb, ps, 10010, 1, "BUY"),
        (s1, a20, 10020, 10, "BUY"),
        (s2, a30, 10030, 10, "BUY"),
        (s3, a40, 10040, 10, "BUY"),
    ]
    assert v.stops() == {}


@pytest.mark.parametrize("limit", [10015, 10020], ids=["rests", "fills"])
def test_a_triggered_stop_limit_rests_or_fills_by_its_limit(
    v: Venue, limit: int
) -> None:
    near = v.submit("SELL", "LIMIT", 5, "GW01", price=10012)
    far = v.submit("SELL", "LIMIT", 10, "GW01", price=10020)
    stop = v.submit("BUY", "STOP_LIMIT", 10, "GW02", stop=10010, price=limit)

    pb, ps = v.print_at(10010)

    tape = [(pb, ps, 10010, 1, "BUY"), (stop, near, 10012, 5, "BUY")]
    if limit == 10015:
        assert v.trades() == tape
        assert v.book() == {
            "BUY": [(stop, 10015, 5, 5)],
            "SELL": [(far, 10020, 10, 10)],
        }
    else:
        assert v.trades() == tape + [(stop, far, 10020, 5, "BUY")]
        assert v.book() == {"BUY": [], "SELL": [(far, 10020, 5, 5)]}


def test_a_trailing_stop_ratchets_then_triggers(v: Venue) -> None:
    """A BUY trailing stop follows a falling price down (never up) at its
    offset, then triggers when the price comes back to it."""
    ask = v.submit("SELL", "LIMIT", 100, "GW01", price=10050)
    stop = v.submit("BUY", "TRAILING_STOP", 10, "GW02", stop=10010, trail=5)

    v.print_at(9990)
    assert v.stops() == {stop: 9995}  # ratcheted down to 99.90 + 0.05
    v.print_at(9994)
    assert v.stops() == {stop: 9995}  # a rise does not move it back up

    pb, ps = v.print_at(9995)

    assert v.trades()[-2:] == [(pb, ps, 9995, 1, "BUY"), (stop, ask, 10050, 10, "BUY")]
    assert v.stops() == {}


# ---------------------------------------------------------------------------
# FOK, IOC, MARKET — participant guide, Order Types
# ---------------------------------------------------------------------------


def test_fok_fills_exactly_across_two_levels(v: Venue) -> None:
    a = v.submit("SELL", "LIMIT", 4, "GW01", price=10010)
    b = v.submit("SELL", "LIMIT", 6, "GW01", price=10020)

    fok = v.submit("BUY", "FOK", 10, "GW02", price=10020)

    assert v.trades() == [(fok, a, 10010, 4, "BUY"), (fok, b, 10020, 6, "BUY")]
    assert v.book() == {"BUY": [], "SELL": []}


def test_fok_short_by_one_lot_trades_nothing(v: Venue) -> None:
    a = v.submit("SELL", "LIMIT", 4, "GW01", price=10010)
    b = v.submit("SELL", "LIMIT", 6, "GW01", price=10020)

    fok = v.submit("BUY", "FOK", 11, "GW02", price=10020)

    assert v.trades() == []
    assert v.book() == {"BUY": [], "SELL": [(a, 10010, 4, 4), (b, 10020, 6, 6)]}
    assert fok not in {p["order_id"] for p in v.published("order.fill.GW02")}


def test_fok_fills_through_hidden_iceberg_quantity(v: Venue) -> None:
    """Only 2 lots are shown, but all 10 count; the FOK takes them one peak
    at a time."""
    ice = v.submit("SELL", "ICEBERG", 10, "GW01", price=10010, visible=2)

    fok = v.submit("BUY", "FOK", 10, "GW02", price=10010)

    assert v.trades() == [(fok, ice, 10010, 2, "BUY")] * 5
    assert v.book() == {"BUY": [], "SELL": []}


def test_fok_does_not_count_liquidity_it_may_not_trade_with(v: Venue) -> None:
    """Self-match prevention: the FOK owner's own 6 lots are excluded, the
    other 6 are not enough, so nothing trades."""
    other = v.submit("SELL", "LIMIT", 6, "GW02", price=10010)
    v.submit("SELL", "LIMIT", 6, "GW01", price=10010)

    fok = v.submit("BUY", "FOK", 10, "GW01", price=10010, smp="CANCEL_RESTING")

    assert v.trades() == []
    assert other in [e[0] for e in v.book()["SELL"]]
    assert fok not in {p["order_id"] for p in v.published("order.fill.GW01")}


def test_fok_counts_nothing_behind_its_own_order(v: Venue) -> None:
    """Bug C: under CANCEL_AGGRESSOR the sweep would stop at the owner's own
    ask, so the 10 lots behind it cannot be reached and the FOK may not take
    the 3 in front either."""
    a = v.submit("SELL", "LIMIT", 3, "GW02", price=10010)
    own = v.submit("SELL", "LIMIT", 5, "GW01", price=10020)
    c = v.submit("SELL", "LIMIT", 10, "GW02", price=10030)

    fok = v.submit("BUY", "FOK", 10, "GW01", price=10030, smp="CANCEL_AGGRESSOR")

    assert v.trades() == []
    assert v.book()["SELL"] == [
        (a, 10010, 3, 3),
        (own, 10020, 5, 5),
        (c, 10030, 10, 10),
    ]
    cancelled = v.event("cancelled", "GW01", fok)
    assert cancelled is not None
    assert cancelled["cancel_reason"] == "SELF_MATCH_PREVENTED"


@pytest.mark.parametrize("type_, price", [("MARKET", None), ("IOC", 10010)])
def test_market_and_ioc_cancel_their_remainder_with_a_reason(
    v: Venue, type_: str, price: int | None
) -> None:
    near = v.submit("SELL", "LIMIT", 5, "GW01", price=10010)
    far = v.submit("SELL", "LIMIT", 5, "GW01", price=10020)

    taker = v.submit("BUY", type_, 12, "GW02", price=price)

    if type_ == "MARKET":
        assert v.trades() == [
            (taker, near, 10010, 5, "BUY"),
            (taker, far, 10020, 5, "BUY"),
        ]
        left, filled = 2, 10
    else:
        assert v.trades() == [(taker, near, 10010, 5, "BUY")]
        left, filled = 7, 5
    cancelled = v.event("cancelled", "GW02", taker)
    assert cancelled is not None
    assert (
        cancelled["cancel_reason"],
        cancelled["remaining_qty"],
        cancelled["cum_qty"],
    ) == ("INSUFFICIENT_LIQUIDITY", left, filled)
    assert v.book()["BUY"] == []  # neither ever rests


@pytest.mark.parametrize("type_, price", [("MARKET", None), ("IOC", 10010)])
def test_market_and_ioc_into_an_empty_book(
    v: Venue, type_: str, price: int | None
) -> None:
    taker = v.submit("BUY", type_, 8, "GW02", price=price)

    assert v.trades() == []
    cancelled = v.event("cancelled", "GW02", taker)
    assert cancelled is not None
    assert (cancelled["cancel_reason"], cancelled["remaining_qty"]) == (
        "INSUFFICIENT_LIQUIDITY",
        8,
    )


# ---------------------------------------------------------------------------
# Icebergs — participant guide, Order Types → ICEBERG
# ---------------------------------------------------------------------------


def test_a_replenished_peak_goes_to_the_back_of_the_queue(v: Venue) -> None:
    ice = v.submit("SELL", "ICEBERG", 30, "GW01", price=10010, visible=10)
    lim = v.submit("SELL", "LIMIT", 10, "GW02", price=10010)

    buy = v.submit("BUY", "LIMIT", 25, "GW03", price=10010)

    assert v.trades() == [
        (buy, ice, 10010, 10, "BUY"),  # the shown peak
        (buy, lim, 10010, 10, "BUY"),  # then the order behind it
        (buy, ice, 10010, 5, "BUY"),  # then the refilled peak
    ]
    assert v.book() == {"BUY": [], "SELL": [(ice, 10010, 15, 5)]}


def test_an_incoming_iceberg_trades_in_full_and_rests_behind_a_full_peak(
    v: Venue,
) -> None:
    """Rule G4: one print for the whole match, not one per peak; the
    remainder shows a whole peak, not what is left of the first."""
    ask = v.submit("SELL", "LIMIT", 7, "GW01", price=10010)

    ice = v.submit("BUY", "ICEBERG", 30, "GW02", price=10010, visible=10)

    assert v.trades() == [(ice, ask, 10010, 7, "BUY")]
    assert v.book() == {"BUY": [(ice, 10010, 23, 10)], "SELL": []}


# ---------------------------------------------------------------------------
# Auctions — participant guide, The Trading Day and Auctions; operator guide,
# Equilibrium price. The closing auction is used: CLOSED uncrosses it.
# ---------------------------------------------------------------------------


def test_auction_maximum_quantity_beats_a_smaller_surplus(v: Venue) -> None:
    """At 100.00 50 lots trade (surplus 50); at 100.10 only 45 (surplus 5).
    Quantity is the first criterion."""
    v.phase("CLOSING_AUCTION")
    b1 = v.submit("BUY", "LIMIT", 45, "GW01", price=10010)
    b2 = v.submit("BUY", "LIMIT", 55, "GW02", price=10000)
    s1 = v.submit("SELL", "LIMIT", 50, "GW03", price=10000)

    v.phase("CLOSED")

    assert v.auction() == (10000, 50, 50, "BUY")
    assert v.trades() == [(b1, s1, 10000, 45, "AUCTION"), (b2, s1, 10000, 5, "AUCTION")]


def test_auction_equal_quantity_goes_to_the_smaller_surplus(v: Venue) -> None:
    """50 lots trade at 100.00, 100.10 and 100.20; the surplus is 30, 30 and
    20, so 100.20 wins although it is the highest price."""
    v.phase("CLOSING_AUCTION")
    b1 = v.submit("BUY", "LIMIT", 50, "GW01", price=10020)
    v.submit("BUY", "LIMIT", 30, "GW01", price=10010)
    s1 = v.submit("SELL", "LIMIT", 50, "GW02", price=10000)
    v.submit("SELL", "LIMIT", 20, "GW02", price=10020)

    v.phase("CLOSED")

    assert v.auction() == (10020, 50, 20, "SELL")
    assert v.trades() == [(b1, s1, 10020, 50, "AUCTION")]


def test_auction_full_tie_goes_to_the_lowest_price(v: Venue) -> None:
    """10 lots trade with no surplus at both prices, so the lower one wins —
    in actual prices, which is why this rule does not mirror."""
    v.phase("CLOSING_AUCTION")
    v.submit("BUY", "LIMIT", 10, "GW01", price=10010)
    v.submit("SELL", "LIMIT", 10, "GW02", price=10000)

    v.phase("CLOSED")

    price, qty, surplus, _ = v.auction()
    assert price is not None
    assert (v.px(price), qty, surplus) == (min(v.px(10000), v.px(10010)), 10, 0)


def test_auction_documented_example(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The worked example in "The uncross — how the opening price is
    computed" (149.50 … 150.00 there; 99.50 … 100.00 here). As written only:
    it ends in a full tie at 99.80 / 100.00, which does not mirror."""
    v = Venue(monkeypatch, tmp_path, mirrored=False)
    v.phase("CLOSING_AUCTION")
    pre = v.submit("BUY", "LIMIT", 200, "GW01", price=9950)
    big = v.submit("BUY", "LIMIT", 500, "GW01", price=10000)
    gw2 = v.submit("SELL", "LIMIT", 300, "GW02", price=9980)
    gw3 = v.submit("SELL", "LIMIT", 400, "GW03", price=9950)

    v.phase("CLOSED")

    assert v.auction() == (9980, 500, 200, "SELL")
    assert v.trades() == [
        (big, gw3, 9980, 400, "AUCTION"),
        (big, gw2, 9980, 100, "AUCTION"),
    ]
    assert v.event("expired", "GW01", pre) is not None  # a DAY order, at the close


def test_auction_one_sided_book_prints_nothing(v: Venue) -> None:
    v.phase("CLOSING_AUCTION")
    v.submit("BUY", "LIMIT", 10, "GW01", price=10010)
    v.submit("BUY", "LIMIT", 10, "GW02", price=10000)

    v.phase("CLOSED")

    assert v.auction() == (None, 0, 0, "")
    assert v.trades() == []


def test_auction_all_quantity_at_one_price_fills_in_time_priority(v: Venue) -> None:
    v.phase("CLOSING_AUCTION")
    b1 = v.submit("BUY", "LIMIT", 10, "GW01", price=10000)
    b2 = v.submit("BUY", "LIMIT", 20, "GW02", price=10000)
    s1 = v.submit("SELL", "LIMIT", 25, "GW03", price=10000)

    v.phase("CLOSED")

    assert v.auction() == (10000, 25, 5, "BUY")
    assert v.trades() == [
        (b1, s1, 10000, 10, "AUCTION"),
        (b2, s1, 10000, 15, "AUCTION"),
    ]
    expired = v.event("expired", "GW02", b2)
    assert expired is not None and expired["remaining_qty"] == 5


def test_auction_hidden_iceberg_quantity_counts_and_queues_behind(v: Venue) -> None:
    """Icebergs in the uncross: hidden quantity sets the price (65 lots at
    100.00, not 10 at 100.10) and fills behind the visible order at its
    price, one peak at a time."""
    v.phase("CLOSING_AUCTION")
    ice = v.submit("SELL", "ICEBERG", 100, "GW01", price=10000, visible=10)
    lim = v.submit("SELL", "LIMIT", 20, "GW02", price=10000)
    b1 = v.submit("BUY", "LIMIT", 60, "GW03", price=10010)
    b2 = v.submit("BUY", "LIMIT", 5, "GW03", price=10000)

    v.phase("CLOSED")

    assert v.auction() == (10000, 65, 55, "SELL")
    assert v.trades() == [
        (b1, ice, 10000, 10, "AUCTION"),  # the shown peak
        (b1, lim, 10000, 20, "AUCTION"),  # the visible order behind it
        (b1, ice, 10000, 10, "AUCTION"),  # then hidden peaks
        (b1, ice, 10000, 10, "AUCTION"),
        (b1, ice, 10000, 10, "AUCTION"),
        (b2, ice, 10000, 5, "AUCTION"),
    ]


def test_auction_print_triggers_stops(v: Venue) -> None:
    """A stop that the uncross price reaches is released after the uncross
    and trades against what is left."""
    v.phase("CLOSING_AUCTION")
    b1 = v.submit("BUY", "LIMIT", 10, "GW01", price=10010)
    s1 = v.submit("SELL", "LIMIT", 10, "GW02", price=10010)
    rest = v.submit("SELL", "LIMIT", 20, "GW02", price=10030)
    stop = v.submit("BUY", "STOP", 5, "GW03", stop=10010)
    assert v.stops() == {stop: 10010}  # not triggered while collecting

    v.phase("CLOSED")

    assert v.trades() == [(b1, s1, 10010, 10, "AUCTION"), (stop, rest, 10030, 5, "BUY")]


def test_stops_released_by_the_uncross_queue_breadth_first(v: Venue) -> None:
    """Rule G2 holds after an uncross: the print at 100.10 releases A and B;
    A's fill at 100.20 releases C, which queues behind B. So B gets 100.30
    and C finds nothing left."""
    v.phase("CLOSING_AUCTION")
    b1 = v.submit("BUY", "LIMIT", 10, "GW01", price=10010)
    s1 = v.submit("SELL", "LIMIT", 10, "GW02", price=10010)
    a20 = v.submit("SELL", "LIMIT", 5, "GW02", price=10020)
    a30 = v.submit("SELL", "LIMIT", 5, "GW02", price=10030)
    a = v.submit("BUY", "STOP", 5, "GW03", stop=10010)
    b = v.submit("BUY", "STOP", 5, "GW03", stop=10010)
    c = v.submit("BUY", "STOP", 5, "GW03", stop=10020)

    v.phase("CLOSED")

    assert v.trades() == [
        (b1, s1, 10010, 10, "AUCTION"),
        (a, a20, 10020, 5, "BUY"),
        (b, a30, 10030, 5, "BUY"),
    ]
    cancelled = v.event("cancelled", "GW03", c)
    assert cancelled is not None
    assert cancelled["cancel_reason"] == "INSUFFICIENT_LIQUIDITY"


# ---------------------------------------------------------------------------
# Session × TIF — participant guide, The Trading Day; operator guide,
# Session Scheduling (TIF expiry)
# ---------------------------------------------------------------------------


def test_ato_expires_when_the_opening_auction_ends(v: Venue) -> None:
    v.phase("CLOSING_AUCTION", "CLOSED", "PRE_OPEN", "OPENING_AUCTION")
    ato = v.submit("BUY", "LIMIT", 10, "GW01", price=9990, tif="ATO")
    day = v.submit("BUY", "LIMIT", 10, "GW02", price=9990)

    v.phase("CONTINUOUS")

    expired = v.event("expired", "GW01", ato)
    assert expired is not None
    assert (expired["remaining_qty"], expired["cum_qty"]) == (10, 0)
    assert [e[0] for e in v.book()["BUY"]] == [day]


def test_atc_partly_filled_in_the_close_expires_its_remainder(v: Venue) -> None:
    v.phase("CLOSING_AUCTION")
    atc = v.submit("BUY", "LIMIT", 10, "GW01", price=10010, tif="ATC")
    sell = v.submit("SELL", "LIMIT", 4, "GW02", price=10010, tif="ATC")

    v.phase("CLOSED")

    assert v.trades() == [(atc, sell, 10010, 4, "AUCTION")]
    expired = v.event("expired", "GW01", atc)
    assert expired is not None
    assert (expired["remaining_qty"], expired["cum_qty"]) == (6, 4)
    assert v.book() == {"BUY": [], "SELL": []}


def test_day_expires_at_the_close_and_gtc_carries_over(v: Venue) -> None:
    day = v.submit("BUY", "LIMIT", 10, "GW01", price=9990)
    gtc = v.submit("BUY", "LIMIT", 10, "GW02", price=9980, tif="GTC")

    v.phase("CLOSING_AUCTION", "CLOSED")

    expired = v.event("expired", "GW01", day)
    assert expired is not None and expired["remaining_qty"] == 10
    assert v.event("expired", "GW02", gtc) is None
    assert v.book() == {"BUY": [(gtc, 9980, 10, 10)], "SELL": []}


# ---------------------------------------------------------------------------
# Cancel and amend — participant guide, Order Amendment / Cancellation
# ---------------------------------------------------------------------------


def test_only_the_owner_may_cancel(v: Venue) -> None:
    bid = v.submit("BUY", "LIMIT", 10, "GW01", price=9990)

    v.cancel(bid, "GW02")

    (ack,) = [p for p in v.published("order.ack.GW02") if p["order_id"] == bid]
    assert (ack["accepted"], ack["reject_code"]) == (False, "NOT_OWNER")
    assert [e[0] for e in v.book()["BUY"]] == [bid]

    v.cancel(bid, "GW01")

    cancelled = v.event("cancelled", "GW01", bid)
    assert cancelled is not None and cancelled.get("cancel_reason") is None
    assert v.book()["BUY"] == []


def test_a_marketable_amend_trades_at_once(v: Venue) -> None:
    ask = v.submit("SELL", "LIMIT", 10, "GW01", price=10010)
    bid = v.submit("BUY", "LIMIT", 10, "GW02", price=9990)

    v.amend(bid, "GW02", price=10010)

    assert v.trades() == [(bid, ask, 10010, 10, "BUY")]
    assert v.book() == {"BUY": [], "SELL": []}


def test_an_amend_that_decreases_quantity_keeps_priority(v: Venue) -> None:
    a = v.submit("BUY", "LIMIT", 10, "GW01", price=9990)
    b = v.submit("BUY", "LIMIT", 10, "GW02", price=9990)

    v.amend(a, "GW01", qty=5)
    sell = v.submit("SELL", "LIMIT", 12, "GW03", price=9990)

    assert v.trades() == [(a, sell, 9990, 5, "SELL"), (b, sell, 9990, 7, "SELL")]


def test_an_amend_that_increases_quantity_loses_priority(v: Venue) -> None:
    a = v.submit("BUY", "LIMIT", 10, "GW01", price=9990)
    b = v.submit("BUY", "LIMIT", 10, "GW02", price=9990)

    v.amend(a, "GW01", qty=15)
    sell = v.submit("SELL", "LIMIT", 12, "GW03", price=9990)

    assert v.trades() == [(b, sell, 9990, 10, "SELL"), (a, sell, 9990, 2, "SELL")]


def test_an_iceberg_quantity_decrease_does_not_refill_its_peak(v: Venue) -> None:
    """Bug B: the amend keeps priority, so the used peak must not grow back."""
    ice = v.submit("SELL", "ICEBERG", 100, "GW01", price=10010, visible=10)
    lim = v.submit("SELL", "LIMIT", 10, "GW02", price=10010)
    first = v.submit("BUY", "LIMIT", 6, "GW03", price=10010)

    v.amend(ice, "GW01", qty=90)

    assert v.book()["SELL"] == [(ice, 10010, 84, 4), (lim, 10010, 10, 10)]
    buy = v.submit("BUY", "LIMIT", 10, "GW03", price=10010)
    assert v.trades() == [
        (first, ice, 10010, 6, "BUY"),
        (buy, ice, 10010, 4, "BUY"),
        (buy, lim, 10010, 6, "BUY"),
    ]


# ---------------------------------------------------------------------------
# Self-match prevention — operator guide, Self-match prevention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "smp, cancelled, traded, left",
    [
        ("CANCEL_RESTING", ["own"], True, []),
        ("CANCEL_AGGRESSOR", ["buy"], False, ["own", "other"]),
        ("CANCEL_BOTH", ["own", "buy"], False, ["other"]),
    ],
)
def test_self_match_prevention_modes(
    v: Venue, smp: str, cancelled: list[str], traded: bool, left: list[str]
) -> None:
    """The owner's own ask is first in line; another firm's is behind it."""
    ids = {
        "own": v.submit("SELL", "LIMIT", 5, "GW01", price=10010),
        "other": v.submit("SELL", "LIMIT", 5, "GW02", price=10020),
    }

    ids["buy"] = v.submit("BUY", "LIMIT", 5, "GW01", price=10020, smp=smp)

    assert v.trades() == (
        [(ids["buy"], ids["other"], 10020, 5, "BUY")] if traded else []
    )
    reasons = {
        name: event["cancel_reason"]
        for name in ("own", "buy")
        if (event := v.event("cancelled", "GW01", ids[name])) is not None
    }
    assert reasons == {name: "SELF_MATCH_PREVENTED" for name in cancelled}
    assert [e[0] for e in v.book()["SELL"]] == [ids[name] for name in left]
