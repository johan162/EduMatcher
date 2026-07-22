"""
Regression tests for the CRITICAL findings (C1-C6) in
docs-design/EduMatcher-Engine-Review.md.

IMPORTANT: These tests encode the *correct* expected behaviour, so they are
EXPECTED TO FAIL until each finding is fixed.  Run them with:

    pytest tests/test_engine_review_criticals.py -v

Once a finding is fixed its test(s) must pass and must be kept as permanent
regression coverage.  If the failing tests are disruptive to CI before the
fixes land, add `@pytest.mark.xfail(strict=True, reason="C<n> open")` to the
open ones and remove the marker together with the fix.

Finding → test map
------------------
  C1  book-stats tick/display round-trip     TestC1BookStatsRoundTrip
  C2  uncross corrupts bid qty index         TestC2UncrossQtyIndex
  C3  SMP-cancelled aggressor gets rested    TestC3SmpCancelledAggressorNotRested
  C4  lost fill notifications (IOC/MARKET)   TestC4FillNotifications
  C5  OCO race orphans the sibling leg       TestC5OcoImmediateFillRace
  C6  trailing stop in no-match mode         TestC6TrailingStopNoMatchMode
  C7  passive iceberg fills bypass the peak  TestC7IcebergDisplayedSliceSemantics
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from edumatcher.engine.auction import compute_equilibrium, execute_uncross
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.engine.persistence import load_book_stats, save_book_stats
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderType,
    Side,
    SmpAction,
    TIF,
)

SYMBOL = "AAPL"  # 2 tick decimals by default → 150.00 == 15000 ticks


# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as test_engine_handlers.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeSock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=(SYMBOL,),
    gateways=("GW01", "GW02"),
    gtc_orders: list[Order] | None = None,
    book_stats: dict[str, Any] | None = None,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={sym: SymbolConfig(name=sym) for sym in symbols},
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=f"{gw} trader") for gw in gateways
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders", lambda _: list(gtc_orders or [])
    )
    monkeypatch.setattr(
        "edumatcher.engine.main.load_book_stats", lambda _: dict(book_stats or {})
    )
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(config_path=str(cfg_path))
    return engine, pub_sock


def _connect(engine: Engine, *gws: str) -> None:
    for gw in gws or ("GW01", "GW02"):
        engine._handle_gateway_connect({"gateway_id": gw})


def _payload(
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    price: float | None = None,
    tif: TIF = TIF.DAY,
    stop_price: float | None = None,
) -> dict[str, Any]:
    o = Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
    )
    return o.to_dict()


def _msgs(pub_sock: _FakeSock, topic: str) -> list[dict[str, Any]]:
    """Decode all published messages matching *topic*."""
    out: list[dict[str, Any]] = []
    for frames in pub_sock.sent:
        t, payload = decode(frames)
        if t == topic:
            out.append(payload)
    return out


def _resting_ids(book: OrderBook) -> set[str]:
    return {o.id for o in book.resting_orders()}


def _rest_limit(
    book: OrderBook, side: Side, qty: int, price_ticks: int, gw: str = "GW01"
) -> Order:
    """Rest a LIMIT order directly on a book (prices in integer ticks)."""
    o = Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gw,
        price=price_ticks,
    )
    book.process(o, match=False)
    return o


# ---------------------------------------------------------------------------
# C1 — book-stats persistence round-trip
#
# save_book_stats() writes last_buy/sell_price as integer TICKS; on restart
# Engine._load_config() re-converts them with to_ticks(float(...)), i.e. as
# DISPLAY prices, inflating them by 10^tick_decimals.  The restored reference
# feeds the collar and circuit-breaker seeds, so every restart with prior
# trades poisons risk controls.
# ---------------------------------------------------------------------------


class TestC1BookStatsRoundTrip:
    def test_last_prices_survive_save_load_cycle(self, monkeypatch, tmp_path) -> None:
        # --- session 1: trade at 150.00 (== 15000 ticks) ---
        engine1, _ = _make_engine(monkeypatch, tmp_path)
        _connect(engine1)
        engine1._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW01", price=150.0)
        )
        engine1._handle_new_order(
            _payload(Side.BUY, OrderType.LIMIT, 100, "GW02", price=150.0)
        )
        book1 = engine1.books[SYMBOL]
        assert book1.last_buy_price == 15000, "precondition: trade must have printed"

        stats_path = tmp_path / "book_stats.json"
        save_book_stats(engine1.books, stats_path)

        # --- session 2: restart and restore ---
        engine2, _ = _make_engine(
            monkeypatch, tmp_path, book_stats=load_book_stats(stats_path)
        )
        engine2._load_config()

        restored = engine2.books[SYMBOL].last_buy_price
        assert restored == 15000, (
            f"C1: last_buy_price round-trip corrupted: saved 15000 ticks, "
            f"restored {restored} ticks (inflated by 10^tick_decimals)"
        )


# ---------------------------------------------------------------------------
# C2 — auction uncross must deduct BOTH sides from the price-level qty index
#
# execute_uncross() treats the bid as "aggressor"; _apply_fill only deducts
# the passive (ask) side, leaving phantom quantity in _bid_qty.  The phantom
# qty corrupts FOK pre-checks, depth snapshots, and the NEXT auction's
# equilibrium computation.
# ---------------------------------------------------------------------------


class TestC2UncrossQtyIndex:
    def test_full_uncross_empties_both_qty_indexes(self) -> None:
        book = OrderBook(SYMBOL)
        _rest_limit(book, Side.BUY, 100, 10100, "GW01")
        _rest_limit(book, Side.SELL, 100, 9900, "GW02")

        result = compute_equilibrium(book)
        assert result.eq_price is not None and result.eq_qty == 100  # precondition
        trades, _events = execute_uncross(book, result.eq_price)
        assert sum(t.quantity for t in trades) == 100  # precondition

        assert sum(book._ask_qty.values()) == 0
        assert sum(book._bid_qty.values()) == 0, (
            f"C2: phantom bid quantity left in level index after uncross: "
            f"{dict(book._bid_qty)}"
        )

    def test_partial_uncross_leaves_exact_remainder(self) -> None:
        book = OrderBook(SYMBOL)
        _rest_limit(book, Side.BUY, 150, 10100, "GW01")
        _rest_limit(book, Side.SELL, 100, 9900, "GW02")

        result = compute_equilibrium(book)
        assert result.eq_price is not None
        execute_uncross(book, result.eq_price)

        # 100 crossed; exactly 50 must remain on the bid side of the index.
        assert sum(book._bid_qty.values()) == 50, (
            f"C2: bid level index shows {sum(book._bid_qty.values())} "
            f"but only 50 should remain resting"
        )


# ---------------------------------------------------------------------------
# C3 — an SMP-cancelled aggressor must never be rested
#
# _sweep() cancels the aggressor on CANCEL_AGGRESSOR / CANCEL_BOTH, but
# _match_limit() then rests it anyway (remaining_qty > 0), re-registering a
# CANCELLED order and permanently inflating the qty index.
# ---------------------------------------------------------------------------


class TestC3SmpCancelledAggressorNotRested:
    def _run_smp(self, smp_action: SmpAction) -> tuple[OrderBook, Order]:
        book = OrderBook(SYMBOL)
        resting = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            price=10000,
        )
        book.process(resting)

        aggressor = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",  # same gateway → SMP fires
            price=10000,
            smp_action=smp_action,
        )
        book.process(aggressor)
        return book, aggressor

    def test_cancel_aggressor_leaves_no_phantom_bid_qty(self) -> None:
        book, aggressor = self._run_smp(SmpAction.CANCEL_AGGRESSOR)
        assert sum(book._bid_qty.values()) == 0, (
            f"C3: cancelled aggressor left phantom qty in _bid_qty: "
            f"{dict(book._bid_qty)}"
        )
        assert aggressor.id not in _resting_ids(book)
        assert (
            book.get_order(aggressor.id) is None
        ), "C3: cancelled aggressor was re-registered in the order index"

    def test_cancel_both_leaves_no_phantom_bid_qty(self) -> None:
        book, aggressor = self._run_smp(SmpAction.CANCEL_BOTH)
        assert sum(book._bid_qty.values()) == 0, (
            f"C3: cancelled aggressor left phantom qty in _bid_qty: "
            f"{dict(book._bid_qty)}"
        )
        assert book.get_order(aggressor.id) is None


# ---------------------------------------------------------------------------
# C4 — every execution must produce a fill notification for the owner
#
# events hold live Order references and the publisher branches on FINAL
# status: an IOC (or MARKET) that partially fills and is then cancelled ends
# with status CANCELLED, so the owner receives order.cancelled but NO
# order.fill — despite a real execution having printed.
# ---------------------------------------------------------------------------


class TestC4FillNotifications:
    def test_ioc_partial_fill_publishes_fill_to_aggressor(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=100.0)
        )

        ioc = _payload(Side.BUY, OrderType.IOC, 100, "GW01", price=100.0)
        engine._handle_new_order(ioc)

        # The trade printed publicly …
        trades = _msgs(pub, "trade.executed")
        assert len(trades) == 1 and trades[0]["quantity"] == 50  # precondition

        # … so the aggressor's private feed must carry a fill for 50.
        fills = [m for m in _msgs(pub, "order.fill.GW01") if m["order_id"] == ioc["id"]]
        assert fills, (
            "C4: IOC partially filled (trade printed for 50) but no "
            "order.fill.GW01 message was published for the aggressor"
        )
        assert fills[-1]["fill_qty"] == 50

    def test_unfilled_market_order_gets_terminal_notification(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)

        mkt = _payload(Side.BUY, OrderType.MARKET, 100, "GW01")
        engine._handle_new_order(mkt)  # empty book — nothing to match

        cancelled = [
            m
            for m in _msgs(pub, "order.cancelled.GW01")
            + _msgs(pub, "order.expired.GW01")
            if m["order_id"] == mkt["id"]
        ]
        rejected = [
            m
            for m in _msgs(pub, "order.ack.GW01")
            if m["order_id"] == mkt["id"] and m.get("accepted") is False
        ]
        assert cancelled or rejected, (
            "C4/M1: unfilled MARKET order was ACKed accepted=True and then "
            "silently discarded — owner never received a terminal event"
        )


# ---------------------------------------------------------------------------
# C5 — OCO whose first leg fills immediately must not orphan the sibling
#
# _handle_oco_order posts legs sequentially; if leg 1 fully fills on entry,
# _check_oco_after_event unregisters the group and pops leg 2's routing
# entries BEFORE leg 2 is posted — leg 2 then rests unlinked (both legs can
# execute) and can no longer be cancelled via the API.
# ---------------------------------------------------------------------------


class TestC5OcoImmediateFillRace:
    def test_sibling_of_immediately_filled_leg_does_not_rest(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        # Liquidity so that leg 1 fills instantly and completely.
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )

        engine._handle_oco_order(
            {
                "oco_id": "OCO-RACE-1",
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 100.0},
                "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 120.0},
            }
        )

        acks = [m for m in _msgs(pub, "oco.ack.GW01") if m.get("accepted")]
        assert acks, "precondition: OCO must be accepted"
        leg1_id = acks[0]["order_id_1"]
        leg2_id = acks[0]["order_id_2"]

        book = engine.books[SYMBOL]
        leg1 = book.get_order(leg1_id)
        assert leg1 is None or leg1.remaining_qty == 0  # precondition: leg1 filled

        assert leg2_id not in _resting_ids(book), (
            "C5: leg 1 filled immediately but leg 2 was still posted and now "
            "rests without OCO protection"
        )

    def test_orphaned_sibling_remains_cancellable(self, monkeypatch, tmp_path) -> None:
        """Even if the sibling rests, the owner must be able to cancel it.

        Today _check_oco_after_event pops _order_symbol[leg2] before leg 2 is
        posted, so a later order.cancel for leg 2 is refused with
        'Order not found' while the order sits live on the book.
        """
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )
        engine._handle_oco_order(
            {
                "oco_id": "OCO-RACE-2",
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 100.0},
                "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 120.0},
            }
        )
        acks = [m for m in _msgs(pub, "oco.ack.GW01") if m.get("accepted")]
        leg2_id = acks[0]["order_id_2"]

        book = engine.books[SYMBOL]
        if leg2_id not in _resting_ids(book):
            return  # correct behaviour (sibling never rested) — nothing to cancel

        engine._handle_cancel({"order_id": leg2_id, "gateway_id": "GW01"})
        assert leg2_id not in _resting_ids(book), (
            "C5: orphaned OCO leg rests on the book but cannot be cancelled "
            "(order→symbol routing entry was popped prematurely)"
        )


# ---------------------------------------------------------------------------
# C6 — trailing stops must survive no-match mode and GTC restore
#
# OrderBook.process(match=False) routes TRAILING_STOP to _rest(), which
# asserts price is not None → AssertionError.  Consequences: a trailing stop
# submitted during a halt/auction is ACKed then silently lost, and a
# persisted GTC trailing stop crashes _restore_gtc() at engine startup.
# ---------------------------------------------------------------------------


def _trailing_stop(tif: TIF = TIF.DAY) -> Order:
    return Order.create(
        symbol=SYMBOL,
        side=Side.SELL,
        order_type=OrderType.TRAILING_STOP,
        quantity=100,
        gateway_id="GW01",
        tif=tif,
        stop_price=9900,  # ticks
        trail_offset=100,  # ticks
    )


class TestC6TrailingStopNoMatchMode:
    def test_process_match_false_accepts_trailing_stop(self) -> None:
        book = OrderBook(SYMBOL)
        order = _trailing_stop()

        # Must not raise (currently: AssertionError from _rest, price is None)
        trades, events = book.process(order, match=False)

        assert trades == []
        assert book.get_order(order.id) is order, (
            "C6: trailing stop accepted in no-match mode must be tracked "
            "as a resting stop order"
        )

    def test_restore_gtc_with_trailing_stop_does_not_crash_startup(
        self, monkeypatch, tmp_path
    ) -> None:
        gtc = _trailing_stop(tif=TIF.GTC)
        engine, _ = _make_engine(monkeypatch, tmp_path, gtc_orders=[gtc])

        # Must not raise (currently: AssertionError propagates out of
        # _restore_gtc and aborts engine startup).
        engine._restore_gtc()

        book = engine.books.get(SYMBOL)
        assert (
            book is not None and book.get_order(gtc.id) is not None
        ), "C6: GTC trailing stop must be restored as an active stop order"


# ---------------------------------------------------------------------------
# C7 — a passive iceberg must only fill its displayed slice per iteration
#
# _sweep sizes fills from best.remaining_qty; for a passive iceberg that is
# the full HIDDEN quantity.  The hidden qty jumps the queue past same-price
# orders with better time priority, and _apply_fill deducts the oversized
# fill from a level index that only ever contained displayed_qty — silently
# stealing visible quantity from OTHER orders at the level.
# (Found by tests/test_book_invariants_random_ops.py, tier `with_icebergs`.)
# ---------------------------------------------------------------------------


class TestC7IcebergDisplayedSliceSemantics:
    def _setup(self) -> tuple[OrderBook, Order, Order]:
        book = OrderBook(SYMBOL)
        iceberg = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.ICEBERG,
            quantity=100,
            gateway_id="GW1",
            price=10000,
            visible_qty=10,
        )
        book.process(iceberg)
        plain = Order.create(  # same price, arrives after the iceberg
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=200,
            gateway_id="GW3",
            price=10000,
        )
        book.process(plain)
        return book, iceberg, plain

    def test_hidden_iceberg_qty_does_not_jump_the_queue(self) -> None:
        book, iceberg, plain = self._setup()

        buy = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW2",
            price=10000,
        )
        book.process(buy)

        # Correct: 10 from the iceberg's peak, then 40 from the plain order
        # (the refreshed peak re-queues BEHIND it).  Buggy: all 50 from the
        # iceberg's hidden quantity, plain order skipped entirely.
        assert plain.remaining_qty == 160, (
            f"C7: plain same-price order was skipped (remaining="
            f"{plain.remaining_qty}, expected 160) — the iceberg's hidden "
            f"qty filled beyond its displayed slice and jumped the queue"
        )
        assert iceberg.remaining_qty == 90

    def test_shared_level_qty_index_survives_iceberg_sweep(self) -> None:
        book, iceberg, plain = self._setup()
        assert book._ask_qty == {10000: 210}  # precondition: 10 shown + 200

        buy = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW2",
            price=10000,
        )
        book.process(buy)

        expected = (iceberg.displayed_qty or 0) + plain.remaining_qty
        actual = book._ask_qty.get(10000, 0)
        assert actual == expected, (
            f"C7: shared price-level index corrupted by iceberg over-deduct — "
            f"index shows {actual}, live visible qty is {expected}"
        )
