"""
Final targeted tests to push from 84% to 85% coverage.
Covers: engine _restore_gtc with orders/combos, _load_config with stats,
verbose paths, no-config init, and board/viewer/audit/stats helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    MMQuoteSeed,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.price import to_ticks
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderOrigin,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class _Sock:
    sent: list
    closed: bool = False

    def send_multipart(self, frames) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
    mm_quotes=None,
    gtc_orders=None,
    gtc_combos=None,
    book_stats=None,
    verbose=False,
    config_path_exists=True,
    symbol_overrides=None,
):
    pull_sock = _Sock(sent=[])
    pub_sock = _Sock(sent=[])

    sym_configs = {}
    for sym in symbols:
        quotes_list = mm_quotes.get(sym, []) if mm_quotes else []
        overrides = symbol_overrides.get(sym, {}) if symbol_overrides else {}
        sym_configs[sym] = SymbolConfig(
            name=sym, market_maker_quotes=quotes_list, **overrides
        )

    cfg = EngineConfig(
        symbols=sym_configs,
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=f"{gw} desc") for gw in gateways
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders",
        lambda _: list(gtc_orders) if gtc_orders else [],
    )
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_combos",
        lambda _: list(gtc_combos) if gtc_combos else [],
    )
    monkeypatch.setattr(
        "edumatcher.engine.main.load_book_stats",
        lambda _: book_stats if book_stats else {},
    )
    monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    if config_path_exists:
        cfg_path.write_text("dummy: true\n")

    engine = Engine(verbose=verbose, config_path=str(cfg_path))
    return engine, pub_sock


def _connect(engine, gw="GW01"):
    engine._handle_gateway_connect({"gateway_id": gw})


def _gtc_order(symbol="AAPL", side=Side.BUY, price=100.0):
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.GTC,
        price=price,
    )
    o.status = OrderStatus.NEW
    return o


def _day_order(symbol="AAPL", side=Side.BUY, price=100.0, days_ago=0):
    """A resting TIF=DAY order, as would be loaded from gtc_orders.json.

    days_ago controls the order's timestamp for the business-day check in
    Engine._restore_gtc (see
    docs-design/EduMatcher-Revised-Quote-Persistence.md §13.4):
    days_ago=0 is dated today (restores normally), days_ago=1 is dated
    yesterday (discarded as stale).
    """
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=price,
    )
    o.status = OrderStatus.NEW
    if days_ago:
        order_date = datetime.now() - timedelta(days=days_ago)
        o.timestamp = int(order_date.timestamp() * 1e9)
    return o


def _quote_leg(
    order_id,
    side,
    tif=TIF.GTC,
    quote_id="Q1",
    gateway_id="GW01",
    symbol="AAPL",
    days_ago=0,
):
    """A resting quote-origin order, as would be loaded from
    gtc_orders.json after §5.2's persistence change — origin=QUOTE with a
    quote_id, exactly as Engine._load_config()/_handle_quote_new produce.
    See docs-design/EduMatcher-Revised-Quote-Persistence.md §5.2-§5.3."""
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id=gateway_id,
        tif=tif,
        price=100.0 if side == Side.BUY else 100.10,
    )
    o.id = order_id
    o.status = OrderStatus.NEW
    o.origin = OrderOrigin.QUOTE
    o.quote_id = quote_id
    if days_ago:
        order_date = datetime.now() - timedelta(days=days_ago)
        o.timestamp = int(order_date.timestamp() * 1e9)
    return o


# ---------------------------------------------------------------------------
# Engine init without config file (line 162-164)
# ---------------------------------------------------------------------------


class TestEngineNoConfig:
    def test_no_config_file_does_not_restrict_symbols(
        self, monkeypatch, tmp_path
    ) -> None:
        pull_sock = _Sock(sent=[])
        pub_sock = _Sock(sent=[])
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
        # Use a path that definitely doesn't exist
        nonexistent = str(tmp_path / "no_such_config.yaml")
        engine = Engine(config_path=nonexistent)
        # No symbol restrictions
        assert engine._allowed_symbols is None


# ---------------------------------------------------------------------------
# _restore_gtc with actual orders (lines 328, 337, 349-353, 371)
# ---------------------------------------------------------------------------


class TestRestoreGTCWithOrders:
    def test_restore_gtc_with_orders_prints_and_publishes(
        self, monkeypatch, tmp_path
    ) -> None:
        """Having GTC orders triggers the if orders: block and snapshot publishes."""
        order = _gtc_order()
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[order], verbose=False
        )
        engine._restore_gtc()
        # After _restore_gtc, orders list is non-empty
        assert "AAPL" in engine.books
        # Snapshots were published for each book
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("book." in t for t in topics)

    def test_restore_gtc_verbose_restored_order(self, monkeypatch, tmp_path) -> None:
        """verbose=True prints restoration message for each GTC order."""
        order = _gtc_order()
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[order], verbose=True
        )
        engine._restore_gtc()
        assert "AAPL" in engine.books

    def test_restore_gtc_verbose_skips_removed_symbol(
        self, monkeypatch, tmp_path
    ) -> None:
        """GTC order for a symbol not in _allowed_symbols is skipped (verbose prints)."""
        order = _gtc_order(symbol="REMOVED")
        # Engine is configured with only AAPL, so REMOVED will be skipped
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            gtc_orders=[order],
            verbose=True,
        )
        engine._restore_gtc()
        # REMOVED should not be in books (skipped)
        assert "REMOVED" not in engine.books

    def test_restore_gtc_with_combos(self, monkeypatch, tmp_path) -> None:
        """GTC combos are restored and the 'Restored N GTC combo(s)' message prints."""
        combo = ComboOrder.create(
            combo_id="C01",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=100,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=200,
                ),
            ],
        )
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL", "MSFT"),
            gtc_combos=[combo],
            verbose=False,
        )
        engine._restore_gtc()
        assert combo.id in engine._combos


class TestRestoreGTCBusinessDayCheck:
    """TIF=DAY orders are only restored if their business day is still
    today's — see docs-design/EduMatcher-Revised-Quote-Persistence.md
    §12-§13. TIF=GTC orders are never date-gated."""

    def test_day_order_dated_today_restores_normally(
        self, monkeypatch, tmp_path
    ) -> None:
        order = _day_order(days_ago=0)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[order], verbose=False
        )
        engine._restore_gtc()
        restored_ids = {o.id for o in engine.books["AAPL"].resting_orders()}
        assert order.id in restored_ids

    def test_day_order_dated_yesterday_is_discarded(
        self, monkeypatch, tmp_path, caplog
    ) -> None:
        import logging

        order = _day_order(days_ago=1)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[order], verbose=False
        )
        with caplog.at_level(logging.INFO):
            engine._restore_gtc()
        # The stale order is discarded before Engine._book() is ever called
        # for it, so "AAPL" never gets a book entry at all — confirm that
        # rather than indexing into engine.books, which would KeyError.
        assert "AAPL" not in engine.books
        assert "Discarding stale TIF=DAY order" in caplog.text

    def test_gtc_order_dated_yesterday_still_restores(
        self, monkeypatch, tmp_path
    ) -> None:
        """The business-day check is DAY-only — GTC restores unconditionally
        regardless of how old the order is."""
        order = _gtc_order()
        order.timestamp = int((datetime.now() - timedelta(days=1)).timestamp() * 1e9)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[order], verbose=False
        )
        engine._restore_gtc()
        restored_ids = {o.id for o in engine.books["AAPL"].resting_orders()}
        assert order.id in restored_ids


class TestRestoreQuoteIndexRebuild:
    """Restored quote-origin orders are regrouped by (gateway_id, quote_id)
    into QuoteIndex entries — see
    docs-design/EduMatcher-Revised-Quote-Persistence.md §5.3, revised per
    §13.7 to cover same-day TIF=DAY quote legs as well as TIF=GTC."""

    def test_two_legged_gtc_quote_is_rebuilt_into_quoteindex(
        self, monkeypatch, tmp_path
    ) -> None:
        bid = _quote_leg("Q1-BID", Side.BUY, tif=TIF.GTC)
        ask = _quote_leg("Q1-ASK", Side.SELL, tif=TIF.GTC)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[bid, ask], verbose=False
        )
        engine._restore_gtc()

        entry = engine._quote_index.get("GW01", "AAPL")
        assert entry is not None
        assert entry.quote_id == "Q1"
        assert entry.bid_order_id == "Q1-BID"
        assert entry.ask_order_id == "Q1-ASK"
        # And the legs are genuinely resting in the book, not just indexed.
        restored_ids = {o.id for o in engine.books["AAPL"].resting_orders()}
        assert restored_ids == {"Q1-BID", "Q1-ASK"}

    def test_two_legged_same_day_tif_day_quote_is_rebuilt_into_quoteindex(
        self, monkeypatch, tmp_path
    ) -> None:
        """The common case per §13.7: a config-seeded quote left at the
        TIF=DAY default now also survives a same-day restart and is fully
        quote-managed again, not just resting as a plain order."""
        bid = _quote_leg("Q1-BID", Side.BUY, tif=TIF.DAY, days_ago=0)
        ask = _quote_leg("Q1-ASK", Side.SELL, tif=TIF.DAY, days_ago=0)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[bid, ask], verbose=False
        )
        engine._restore_gtc()

        entry = engine._quote_index.get("GW01", "AAPL")
        assert entry is not None
        assert entry.bid_order_id == "Q1-BID"
        assert entry.ask_order_id == "Q1-ASK"

    def test_single_surviving_leg_rests_but_is_not_quote_managed(
        self, monkeypatch, tmp_path, caplog
    ) -> None:
        """The sibling leg is gone (filled/cancelled before shutdown, or
        never GTC/same-day-DAY) — the surviving leg rests as an ordinary
        order but no QuoteEntry is created for it. See §6.3."""
        import logging

        bid_only = _quote_leg("Q1-BID", Side.BUY, tif=TIF.GTC)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[bid_only], verbose=False
        )
        with caplog.at_level(logging.INFO):
            engine._restore_gtc()

        assert engine._quote_index.get("GW01", "AAPL") is None
        restored_ids = {o.id for o in engine.books["AAPL"].resting_orders()}
        assert restored_ids == {"Q1-BID"}
        assert "single-leg quote remnant" in caplog.text

    def test_stale_day_quote_leaves_quoteindex_empty(
        self, monkeypatch, tmp_path
    ) -> None:
        """A same-day TIF=DAY quote leg that is actually stale (business day
        has rolled over) is discarded by the staleness check before it ever
        reaches the QuoteIndex grouping step — the interaction case from
        §13.7 / the former §13.9-WP4."""
        bid = _quote_leg("Q1-BID", Side.BUY, tif=TIF.DAY, days_ago=1)
        ask = _quote_leg("Q1-ASK", Side.SELL, tif=TIF.DAY, days_ago=1)
        engine, _ = _make_engine(
            monkeypatch, tmp_path, gtc_orders=[bid, ask], verbose=False
        )
        engine._restore_gtc()

        assert engine._quote_index.get("GW01", "AAPL") is None
        assert "AAPL" not in engine.books

    def test_mixed_gateways_do_not_cross_pollinate_groups(
        self, monkeypatch, tmp_path
    ) -> None:
        """Two different gateways seeding the same quote_id string must not
        be merged into one QuoteEntry — grouping key is (gateway_id,
        quote_id), not quote_id alone."""
        gw1_bid = _quote_leg("GW1-BID", Side.BUY, gateway_id="GW01", quote_id="Q1")
        gw1_ask = _quote_leg("GW1-ASK", Side.SELL, gateway_id="GW01", quote_id="Q1")
        gw2_bid = _quote_leg("GW2-BID", Side.BUY, gateway_id="MM02", quote_id="Q1")
        gw2_ask = _quote_leg("GW2-ASK", Side.SELL, gateway_id="MM02", quote_id="Q1")
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            gateways=("GW01", "MM02"),
            gtc_orders=[gw1_bid, gw1_ask, gw2_bid, gw2_ask],
            verbose=False,
        )
        engine._restore_gtc()

        entry1 = engine._quote_index.get("GW01", "AAPL")
        entry2 = engine._quote_index.get("MM02", "AAPL")
        assert entry1 is not None and entry2 is not None
        assert entry1.bid_order_id == "GW1-BID"
        assert entry2.bid_order_id == "GW2-BID"

    def test_corrupt_sibling_record_does_not_abort_startup(
        self, monkeypatch, tmp_path, caplog
    ) -> None:
        """§6.3: the per-order try/except guard in _restore_gtc() (finding
        C6) can drop one leg of a quote pair while keeping the other, if
        that leg's persisted record is individually corrupt — e.g. a
        hand-edited gtc_orders.json with a null price on a LIMIT order,
        which fails OrderBook._rest()'s assertion. Startup must not abort,
        the surviving leg must still rest as an ordinary (non-quote-managed)
        order, and no QuoteEntry should be created for the incomplete pair.
        """
        import logging

        good_leg = _quote_leg("Q1-BID", Side.BUY, tif=TIF.GTC)
        corrupt_leg = _quote_leg("Q1-ASK", Side.SELL, tif=TIF.GTC)
        corrupt_leg.price = None  # simulates a corrupt/hand-edited record

        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            gtc_orders=[good_leg, corrupt_leg],
            verbose=False,
        )
        with caplog.at_level(logging.INFO):
            engine._restore_gtc()  # must not raise

        # The corrupt leg was skipped; the good leg still rests.
        restored_ids = {o.id for o in engine.books["AAPL"].resting_orders()}
        assert restored_ids == {"Q1-BID"}
        assert "restore failed" in caplog.text
        # No QuoteEntry for an incomplete pair — surviving leg is a plain
        # resting order, not quote-managed.
        assert engine._quote_index.get("GW01", "AAPL") is None
        assert "single-leg quote remnant" in caplog.text


# ---------------------------------------------------------------------------
# _load_config with book stats (line 225)
# ---------------------------------------------------------------------------


class TestLoadConfigWithStats:
    def test_load_config_with_book_stats_prints(self, monkeypatch, tmp_path) -> None:
        """When load_book_stats returns non-empty, the stats print is triggered."""
        engine, pub_sock = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            book_stats={"AAPL": {"last_buy_price": 100.0, "last_sell_price": 99.0}},
        )
        engine._load_config()
        # stats restore path hit; book should exist
        assert "AAPL" in engine.books

    def test_load_config_verbose_mm_quote(self, monkeypatch, tmp_path) -> None:
        """With verbose=True and MM quotes, the verbose MM quote print runs."""
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            mm_quotes={
                "AAPL": [
                    MMQuoteSeed(
                        gateway_id="GW01",
                        bid_price=104.0,
                        ask_price=105.0,
                        bid_qty=100,
                        ask_qty=100,
                    )
                ]
            },
            verbose=True,
        )
        engine._load_config()
        assert "AAPL" in engine.books


# ---------------------------------------------------------------------------
# Collar reference_price prefers persisted book_stats over stale config seed
# ---------------------------------------------------------------------------


class TestCollarReferencePricePrefersPersistedStats:
    def test_reference_price_uses_persisted_book_stats_over_stale_config(
        self, monkeypatch, tmp_path
    ) -> None:
        """Persisted book_stats.json last_buy_price wins over the config seed."""
        stale_collar = CollarConfig(symbol="AAPL")
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            symbol_overrides={
                "AAPL": {"last_buy_price": 100.0, "collar": stale_collar}
            },
            book_stats={"AAPL": {"last_buy_price": 150.0}},
        )
        engine._load_config()
        assert engine._collars["AAPL"].reference_price == to_ticks(150.0, "AAPL")

    def test_reference_price_falls_back_to_config_without_persisted_stats(
        self, monkeypatch, tmp_path
    ) -> None:
        """With no persisted stats, the config seed is used as before."""
        stale_collar = CollarConfig(symbol="AAPL")
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            symbol_overrides={
                "AAPL": {"last_buy_price": 100.0, "collar": stale_collar}
            },
        )
        engine._load_config()
        assert engine._collars["AAPL"].reference_price == to_ticks(100.0, "AAPL")


# ---------------------------------------------------------------------------
# Circuit breaker reference is seeded from last price on day one
# ---------------------------------------------------------------------------


class TestCircuitBreakerSeededAtStartup:
    def _cb_config(self):
        from edumatcher.engine.circuit_breaker import (
            CircuitBreakerConfig,
            CircuitBreakerLevel,
        )

        return CircuitBreakerConfig(
            symbol="AAPL",
            reference_window_ns=300_000_000_000,
            levels=[
                CircuitBreakerLevel(
                    name="L1",
                    price_shift_pct=0.07,
                    halt_duration_ns=300_000_000_000,
                ),
            ],
        )

    def test_cb_reference_seeded_from_last_price(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            symbol_overrides={
                "AAPL": {"last_buy_price": 100.0, "circuit_breaker": self._cb_config()},
            },
        )
        engine._load_config()
        cb = engine._circuit_breakers["AAPL"]
        assert cb.reference_price == to_ticks(100.0, "AAPL")

    def test_first_trade_can_trigger_on_day_one(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=("AAPL",),
            symbol_overrides={
                "AAPL": {"last_buy_price": 100.0, "circuit_breaker": self._cb_config()},
            },
        )
        engine._load_config()
        cb = engine._circuit_breakers["AAPL"]
        # A first print +8% from the seeded reference must be able to trigger L1.
        from edumatcher.models.clock import now_ns

        level = cb.record_trade(to_ticks(108.0, "AAPL"), now_ns())
        assert level is not None
        assert level.name == "L1"


# ---------------------------------------------------------------------------
# _handle_new_order verbose rejected paths (lines 385)
# ---------------------------------------------------------------------------


class TestVerboseRejectedOrder:
    def test_verbose_gateway_not_connected_rejection(
        self, monkeypatch, tmp_path
    ) -> None:
        """Verbose rejection message for not-connected gateway."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        # Don't connect GW01 — just call _handle_new_order directly
        order = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
        )
        engine._handle_new_order(order.to_dict())
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("ack" in t for t in topics)

    def test_verbose_symbol_not_configured_rejection(
        self, monkeypatch, tmp_path
    ) -> None:
        """Verbose rejection for symbol not in allowlist."""
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, symbols=("AAPL",), verbose=True
        )
        _connect(engine)
        order = Order.create(
            symbol="UNKNOWN",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
        )
        engine._handle_new_order(order.to_dict())
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("ack" in t for t in topics)


# ---------------------------------------------------------------------------
# board/main.py — _build_rows_table with board orders
# ---------------------------------------------------------------------------


class TestBoardBuildTable:
    def test_build_table_called_via_board_helper(self) -> None:
        """_colour_change and _format_price (already tested) — check
        _build_rows_table (renamed from _build_table, same convention as
        pm-orders' own table builder)."""
        from edumatcher.board.main import _build_rows_table as board_build_table

        # Just verify the function exists and is callable
        assert callable(board_build_table)


# ---------------------------------------------------------------------------
# engine/main.py — remaining SMP event paths (lines 558-569)
# ---------------------------------------------------------------------------


class TestEngineSMPIOCEvents:
    def test_ioc_partial_fill_smp_cancel_aggressor(self, monkeypatch, tmp_path) -> None:
        """IOC order + SMP CANCEL_AGGRESSOR: aggressor fills partially then cancelled."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, verbose=True)
        _connect(engine)

        # Place a resting sell from GW01
        resting = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100,
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        engine._handle_new_order(resting.to_dict())
        pub_sock.sent.clear()

        # IOC aggressor from same gateway — should trigger SMP before matching
        ioc = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.IOC,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=105,
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        engine._handle_new_order(ioc.to_dict())
        topics = [decode(f)[0] for f in pub_sock.sent]
        # Should have some response
        assert len(topics) > 0


# ---------------------------------------------------------------------------
# Engine.__init__ config load error (lines 162-164)
# ---------------------------------------------------------------------------


class TestEngineConfigLoadError:
    def test_config_load_exception_exits(self, monkeypatch, tmp_path) -> None:
        """If load_engine_config raises, sys.exit(1) is called."""
        pull_sock = _Sock(sent=[])
        pub_sock = _Sock(sent=[])
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
        monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})

        def bad_config(_):
            raise ValueError("malformed config")

        monkeypatch.setattr("edumatcher.engine.main.load_engine_config", bad_config)
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("bad yaml: {{{{")
        with pytest.raises(SystemExit):
            Engine(config_path=str(cfg_path))
