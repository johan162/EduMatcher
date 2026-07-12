"""
Regression tests for the MEDIUM-severity findings (M1-M14) in
docs-design/EduMatcher-Engine-Review.md.

IMPORTANT: These tests encode the *correct* expected behaviour, so they are
EXPECTED TO FAIL until each finding is fixed.  Run them with:

    pytest tests/test_engine_review_mediums.py -v

Once a finding is fixed its test(s) must pass and must be kept as permanent
regression coverage.  If the failing tests are disruptive to CI before the
fixes land, add `@pytest.mark.xfail(strict=True, reason="M<n> open")` to
the open ones and remove the marker together with the fix.

Finding → test map
------------------
  M1   silent MARKET remainder cancel      TestM1MarketRemainderEvent
  M2   stops dormant when already breached TestM2ImmediatelyTriggerableStop
  M3   crossed book after restore/resume   TestM3CrossedBookRecovery
  M4   snapshot before tick registration   TestM4RestoreSnapshotTickDecimals
  M5   ComboType.AON not enforced          TestM5AonComboAtomicity
  M6   unbounded stop-cascade recursion    TestM6StopCascadeDepth
  M7   no engine boundary validation       TestM7BoundaryValidation
                                           (+ tests/test_engine_adversarial.py)
  M8   half-applied state after handler
       exception                           TestM8ExceptionAtomicity
  M9   wall clock on the matching path     TestM9MonotonicEngineClock
  M10  no tie-break beyond timestamp       TestM10EqualTimestampFifo
  M11  monetary aggregates in float        TestM11ExactMoneyAggregates
  M12  raw amend payload types             (tests/test_engine_adversarial.py::
                                            TestAmendPayloadTypes)
  M13  drop copy liquidity_flag always
       MAKER                               TestM13DropCopyLiquidityFlag
  M14  no day-boundary reset               TestM14DayBoundaryReset
"""

from __future__ import annotations

from decimal import Decimal

from edumatcher.engine.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerState,
)
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

from tests.engine_harness import (
    SYMBOL,
    FakeDropCopy,
    connect,
    make_engine,
    msgs,
    order_payload,
    resting_ids,
)


def _limit(
    side: Side, price_ticks: int, qty: int = 100, gw: str = "GW1", **kw
) -> Order:
    return Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gw,
        price=price_ticks,
        **kw,
    )


def _best(index: dict[int, int], side: Side) -> int | None:
    live = [p for p, q in index.items() if q > 0]
    if not live:
        return None
    return max(live) if side == Side.BUY else min(live)


# ---------------------------------------------------------------------------
# M1 — an unfilled MARKET order must emit its cancellation event
# ---------------------------------------------------------------------------


class TestM1MarketRemainderEvent:
    def test_fully_unfilled_market_order_emits_terminal_event(self) -> None:
        book = OrderBook(SYMBOL)  # empty book — nothing to match

        market = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            gateway_id="GW1",
        )
        trades, events = book.process(market)

        assert trades == []
        assert market.status == OrderStatus.CANCELLED  # discard is fine …
        assert any(e.id == market.id for e in events), (
            "M1: MARKET order was cancelled with an EMPTY events list — the "
            "engine has nothing to publish and the owner is never notified"
        )


# ---------------------------------------------------------------------------
# M2 — a stop whose trigger is already breached must not lie dormant
# ---------------------------------------------------------------------------


class TestM2ImmediatelyTriggerableStop:
    def test_already_breached_buy_stop_executes_or_rejects_on_entry(self) -> None:
        book = OrderBook(SYMBOL)
        # Print a trade at 100.00 to establish last_trade_price = 10000.
        book.process(_limit(Side.SELL, 10000, qty=50, gw="GW2"))
        book.process(_limit(Side.BUY, 10000, qty=50, gw="GW3"))
        assert book.last_trade_price == 10000  # precondition
        # Liquidity for the stop to execute against.
        book.process(_limit(Side.SELL, 10100, qty=100, gw="GW2"))

        # BUY stop with stop_price 99.00 — ALREADY breached (last >= stop).
        stop = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.STOP,
            quantity=100,
            gateway_id="GW1",
            stop_price=9900,
        )
        trades, events = book.process(stop)

        # Correct behaviour (either standard variant): trigger immediately
        # (→ trades) or reject as "would trigger immediately".  What it must
        # NOT do is park silently until some unrelated future trade.
        assert trades or stop.status == OrderStatus.REJECTED, (
            f"M2: stop with already-breached trigger (last=10000 >= "
            f"stop=9900) was parked dormant (status={stop.status.value}, "
            f"no trades) — it must trigger on entry or be rejected"
        )


# ---------------------------------------------------------------------------
# M3 — a crossed book must be uncrossed after GTC restore and after a
#       non-auction circuit-breaker resume
# ---------------------------------------------------------------------------


class TestM3CrossedBookRecovery:
    def _assert_not_crossed(self, book: OrderBook, where: str) -> None:
        best_bid = _best(book._bid_qty, Side.BUY)
        best_ask = _best(book._ask_qty, Side.SELL)
        assert best_bid is None or best_ask is None or best_bid < best_ask, (
            f"M3: book left CROSSED after {where} "
            f"(best_bid={best_bid} >= best_ask={best_ask}) — crossed "
            f"restored/halted interest must be uncrossed before continuous "
            f"trading resumes"
        )

    def test_crossed_gtc_restore_is_uncrossed_at_startup(
        self, monkeypatch, tmp_path
    ) -> None:
        crossed = [
            Order.create(
                symbol=SYMBOL, side=Side.BUY, order_type=OrderType.LIMIT,
                quantity=100, gateway_id="GW01", tif=TIF.GTC, price=10100,
            ),
            Order.create(
                symbol=SYMBOL, side=Side.SELL, order_type=OrderType.LIMIT,
                quantity=100, gateway_id="GW02", tif=TIF.GTC, price=10000,
            ),
        ]
        engine, pub = make_engine(monkeypatch, tmp_path, gtc_orders=crossed)
        engine._restore_gtc()
        self._assert_not_crossed(engine.books[SYMBOL], "GTC restore")

    def test_non_auction_breaker_resume_uncrosses_the_book(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        # Halted symbol with a timed breaker whose resumption mode is NOT
        # an auction.
        state = CircuitBreakerState(
            symbol=SYMBOL, config=CircuitBreakerConfig(symbol=SYMBOL)
        )
        state.halted = True
        state.halted_at_ns = 1
        state.resume_at_ns = 1  # already elapsed
        state.active_resumption_mode = "CONTINUOUS"
        engine._circuit_breakers[SYMBOL] = state
        engine._halted_symbols[SYMBOL] = True

        # Crossed interest accumulates during the halt (LIMITs rest unmatched).
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=101.0)
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )

        engine._flush_circuit_breakers()  # timed resume fires here
        assert not engine._halted_symbols.get(SYMBOL)  # precondition: resumed
        self._assert_not_crossed(
            engine.books[SYMBOL], "circuit-breaker resume (mode=CONTINUOUS)"
        )


# ---------------------------------------------------------------------------
# M4 — snapshots published during GTC restore must use the symbol's real
#      tick decimals (run() restores BEFORE _load_config registers them)
# ---------------------------------------------------------------------------


class TestM4RestoreSnapshotTickDecimals:
    def test_restore_snapshot_prices_respect_tick_decimals(
        self, monkeypatch, tmp_path
    ) -> None:
        sym = "TICKY"  # fresh symbol → nothing pre-registered in the registry
        gtc = Order.create(
            symbol=sym,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=1_000_000,  # ticks at 4 decimals == 100.0000
        )
        engine, pub = make_engine(
            monkeypatch,
            tmp_path,
            symbols=(sym,),
            symbol_configs={sym: SymbolConfig(name=sym, tick_decimals=4)},
            gtc_orders=[gtc],
        )

        # Mimic run(): _restore_gtc() runs first and publishes snapshots.
        engine._restore_gtc()

        books = msgs(pub, f"book.{sym}")
        assert books and books[0]["bids"], "precondition: snapshot published"
        price = books[0]["bids"][0]["price"]
        assert price == 100.0, (
            f"M4: restore-time snapshot shows price {price} — 1,000,000 ticks "
            f"at tick_decimals=4 is 100.0, but the snapshot was published "
            f"before tick decimals were registered (default 2 → 100x off)"
        )


# ---------------------------------------------------------------------------
# M5 — an AON combo must be all-or-none
# ---------------------------------------------------------------------------


class TestM5AonComboAtomicity:
    def test_aon_combo_does_not_execute_when_a_leg_is_unfillable(
        self, monkeypatch, tmp_path
    ) -> None:
        from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType

        engine, pub = make_engine(monkeypatch, tmp_path, symbols=(SYMBOL, "MSFT"))
        connect(engine)
        # Liquidity exists for leg 1 only; leg 2 (MSFT) cannot fill.
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )

        combo = ComboOrder.create(
            combo_id="CMB-M5",
            gateway_id="GW01",
            combo_type=ComboType.AON,  # all-or-none
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol=SYMBOL, side=Side.BUY, order_type=OrderType.LIMIT,
                    quantity=100, price=10000,
                ),
                ComboLeg(
                    symbol="MSFT", side=Side.BUY, order_type=OrderType.LIMIT,
                    quantity=10, price=5000,  # empty book — cannot fill
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        trades = msgs(pub, "trade.executed")
        assert trades == [], (
            f"M5: AON combo executed {len(trades)} trade(s) although leg 2 is "
            f"unfillable — all-or-none semantics require that no leg executes "
            f"unless every leg can"
        )


# ---------------------------------------------------------------------------
# M6 — deep stop cascades must not exhaust the interpreter stack
# ---------------------------------------------------------------------------


class TestM6StopCascadeDepth:
    def test_thousand_link_stop_cascade_completes(self) -> None:
        n = 1000
        book = OrderBook(SYMBOL)
        # Ask ladder: one lot at each tick upward.
        for i in range(n + 1):
            book.process(_limit(Side.SELL, 10000 + 10 * i, qty=1, gw="GW2"))
        # Buy stops that each trigger off the previous link's fill.
        for i in range(1, n + 1):
            book.process(
                Order.create(
                    symbol=SYMBOL, side=Side.BUY, order_type=OrderType.STOP,
                    quantity=1, gateway_id="GW1",
                    stop_price=10000 + 10 * (i - 1),
                )
            )

        # One trade at the bottom starts the cascade.  Must complete —
        # today it dies with RecursionError at ~1000 links (process()
        # recurses once per triggered stop).
        trigger = _limit(Side.BUY, 10000, qty=1, gw="GW3")
        trades, _events = book.process(trigger)

        assert len(trades) == n + 1, (
            f"M6: cascade produced {len(trades)} trades, expected {n + 1}"
        )


# ---------------------------------------------------------------------------
# M7 — the engine boundary must validate orders it ACKs
#      (companion tests: tests/test_engine_adversarial.py)
# ---------------------------------------------------------------------------


class TestM7BoundaryValidation:
    def test_limit_without_price_is_rejected_not_crashed(
        self, monkeypatch, tmp_path
    ) -> None:
        """A LIMIT order with price=None currently passes every check, is
        ACKed accepted=True, and then blows up on the _rest() assertion —
        which run() swallows, so the order silently vanishes."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        payload["price"] = None

        # Must not raise …
        engine._handle_new_order(payload)

        # … and must be explicitly rejected.
        rejects = [
            m
            for m in msgs(pub, "order.ack.GW01")
            if m["order_id"] == payload["id"] and m.get("accepted") is False
        ]
        assert rejects, (
            "M7: LIMIT without a price must be rejected with a reasoned NACK "
            "before the positive ACK is sent"
        )


# ---------------------------------------------------------------------------
# M8 — a handler failure must not leave half-applied engine state
# ---------------------------------------------------------------------------


class TestM8ExceptionAtomicity:
    def test_failed_order_leaves_no_partial_registration(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        # Force the book to fail mid-processing, as run()'s blanket handler
        # would experience it.
        def _boom(self, order, *, match=True, now=None):
            raise RuntimeError("injected failure")

        monkeypatch.setattr(OrderBook, "process", _boom)

        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        try:
            engine._handle_new_order(payload)
        except RuntimeError:
            pass  # run() swallows this; state inspection is what matters

        assert payload["id"] not in engine._order_symbol, (
            "M8: order that FAILED processing is still registered in "
            "_order_symbol — the engine ACKed and half-applied an order that "
            "never reached the book (registration must happen after, or be "
            "rolled back on failure)"
        )


# ---------------------------------------------------------------------------
# M9 — the matching path must use a monotonic clock
# ---------------------------------------------------------------------------


class TestM9MonotonicEngineClock:
    def test_engine_timestamps_never_regress_when_wall_clock_does(
        self, monkeypatch, tmp_path
    ) -> None:
        """clock.now_ns() guarantees strict monotonicity; the hot path
        deliberately bypasses it with raw time.time_ns (main.py PERF note).
        If the wall clock steps backwards (NTP), matching timestamps regress.
        """
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine)

        # Wall clock that jumps back one second between the two orders.
        base = 1_800_000_000_000_000_000
        ticks = iter([base, base - 1_000_000_000])
        monkeypatch.setattr(
            "edumatcher.engine.main._time_ns", lambda: next(ticks)
        )

        seen: list[int] = []
        orig = OrderBook.process

        def spy(self, order, *, match=True, now=None):
            if now is not None:
                seen.append(now)
            return orig(self, order, match=match, now=now)

        monkeypatch.setattr(OrderBook, "process", spy)

        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=99.0)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=98.0)
        )

        assert len(seen) == 2, "precondition: both orders reached the book"
        assert seen[1] >= seen[0], (
            f"M9: matching timestamp regressed with the wall clock "
            f"({seen[0]} → {seen[1]}) — the engine must use a monotonic "
            f"source (clock.now_ns) for anything that orders events"
        )


# ---------------------------------------------------------------------------
# M10 — equal-timestamp orders at one price must still fill FIFO
# ---------------------------------------------------------------------------


class TestM10EqualTimestampFifo:
    def test_same_timestamp_orders_fill_in_arrival_order(self) -> None:
        """With key=(price, timestamp) and equal timestamps, heapq order is
        arbitrary (deterministically NOT insertion order for >2 entries).
        A same-nanosecond burst — or any coarser clock — breaks FIFO.
        Requires an arrival sequence number as the tie-break (review H1/M10).
        """
        book = OrderBook(SYMBOL)
        ts = 1_800_000_000_000_000_000
        sells: list[Order] = []
        for _ in range(5):
            o = _limit(Side.SELL, 10000, qty=1, gw="GW2")
            o.timestamp = ts  # same-instant burst
            book.process(o)
            sells.append(o)

        buy = _limit(Side.BUY, 10000, qty=5, gw="GW1")
        trades, _events = book.process(buy)
        assert len(trades) == 5  # precondition

        got = [t.sell_order_id for t in trades]
        expected = [o.id for o in sells]
        assert got == expected, (
            f"M10: equal-timestamp orders did not fill FIFO — arrival order "
            f"{[i[:8] for i in expected]}, fill order {[i[:8] for i in got]}"
        )


# ---------------------------------------------------------------------------
# M11 — monetary aggregates must be exact, not float-accumulated
# ---------------------------------------------------------------------------


class TestM11ExactMoneyAggregates:
    def test_daily_value_is_exact_over_repeated_fills(self) -> None:
        book = OrderBook(SYMBOL)
        # Three 1-lot trades at 100.10 (10010 ticks).  Exact total: 300.30.
        for _ in range(3):
            book.process(_limit(Side.SELL, 10010, qty=1, gw="GW2"))
            book.process(_limit(Side.BUY, 10010, qty=1, gw="GW1"))

        assert book.daily_qty == 3  # precondition
        got = Decimal(repr(book.daily_value))
        assert got == Decimal("300.3"), (
            f"M11: daily_value drifted to {book.daily_value!r} — accumulating "
            f"display floats loses exactness; keep the aggregate in integer "
            f"ticks (30030) and convert once at the boundary"
        )


# ---------------------------------------------------------------------------
# M13 — drop copy must distinguish maker and taker fills
# ---------------------------------------------------------------------------


class TestM13DropCopyLiquidityFlag:
    def test_aggressor_fill_is_not_flagged_as_maker(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        drop = FakeDropCopy()
        engine._drop_copy = drop
        connect(engine)

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )
        aggressor = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(aggressor)

        agg_fills = [
            p
            for gw, ev, p in drop.events
            if gw == "GW01" and ev == "order.fill" and p["order_id"] == aggressor["id"]
        ]
        assert agg_fills, "precondition: aggressor fill reached drop copy"
        flags = {p.get("liquidity_flag") for p in agg_fills}
        assert not any(str(f).startswith("MAKER") for f in flags), (
            f"M13: the AGGRESSOR's drop-copy fill is flagged {flags} — taker "
            f"fills must not be labelled MAKER (flag is hardcoded)"
        )


# ---------------------------------------------------------------------------
# M14 — the CLOSED transition is the day boundary: expire DAY orders,
#       reset daily statistics
# ---------------------------------------------------------------------------


class TestM14DayBoundaryReset:
    def _trade_and_close(self, monkeypatch, tmp_path):
        engine, pub = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        connect(engine)
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        engine._handle_session_transition({"to_state": "CONTINUOUS"})

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 50, "GW01", price=100.0)
        )
        # 50 remain resting for GW02 as a DAY order.
        engine._handle_session_transition({"to_state": "CLOSED"})
        return engine, pub

    def test_day_orders_expire_when_the_session_closes(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = self._trade_and_close(monkeypatch, tmp_path)

        book = engine.books[SYMBOL]
        still_resting = resting_ids(book)
        expired = msgs(pub, "order.expired.GW02")
        assert not still_resting or expired, (
            f"M14: session transitioned to CLOSED but {len(still_resting)} DAY "
            f"order(s) still rest with no expiry notice — DAY orders must be "
            f"expired at the close, not only at process shutdown"
        )

    def test_daily_stats_reset_for_the_new_trading_day(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = self._trade_and_close(monkeypatch, tmp_path)
        assert engine.books[SYMBOL].daily_qty == 50  # precondition: day 1 volume

        engine._handle_session_transition({"to_state": "PRE_OPEN"})  # day 2

        book = engine.books[SYMBOL]
        assert book.daily_qty == 0 and book.daily_trades == 0, (
            f"M14: new trading day opened with day-1 volume still on the "
            f"books (daily_qty={book.daily_qty}, trades={book.daily_trades}) "
            f"— 'daily' statistics must reset at the day boundary"
        )
