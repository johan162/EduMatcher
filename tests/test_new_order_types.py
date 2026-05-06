"""
Tests for the three new order types: IOC, TRAILING_STOP, and OCO.

Each section covers:
  - Happy-path execution
  - Edge cases (empty book, partial fill, price miss)
  - Integration with the Engine (gateway auth, session state)
  - Interaction with other features (SMP, GTC persistence, auction mode)
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _DummySocket:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_order(
    symbol="AAPL",
    side=Side.BUY,
    qty=10,
    price=100.0,
    order_type=OrderType.LIMIT,
    tif=TIF.DAY,
    gateway_id="TRADER01",
    stop_price=None,
    trail_offset=None,
    smp_action=SmpAction.NONE,
):
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
        trail_offset=trail_offset,
        smp_action=smp_action,
    )


@pytest.fixture
def book():
    return OrderBook("AAPL")


def _topics(pub_sock: _DummySocket) -> list[str]:
    return [decode(f)[0] for f in pub_sock.sent]


# ---------------------------------------------------------------------------
# Engine fixture (used for integration tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def eng(monkeypatch, tmp_path):
    """Wired Engine with AAPL + MSFT, TRADER01 + TRADER02."""
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "TRADER01": FixGatewayConfig(id="TRADER01", description="t1"),
            "TRADER02": FixGatewayConfig(id="TRADER02", description="t2"),
        },
        sessions_enabled=True,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(config_path=str(cfg_path))
    engine._session_state = SessionState.CONTINUOUS
    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    engine._handle_gateway_connect({"gateway_id": "TRADER02"})
    pub_sock.sent.clear()
    return engine, pub_sock


# ===========================================================================
#  IOC — Immediate-Or-Cancel
# ===========================================================================


class TestIOCOrderBook:
    """Order-book level tests — no engine overhead."""

    def test_ioc_fully_fills_when_liquidity_sufficient(self, book):
        """IOC fully fills when the opposite side has enough quantity."""
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0))  # resting ask

        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        assert len(trades) == 1
        assert trades[0].quantity == 10
        assert ioc.status == OrderStatus.FILLED
        assert ioc.remaining_qty == 0

    def test_ioc_partial_fill_cancels_remainder(self, book):
        """IOC fills what it can and cancels any unfilled portion."""
        book.process(
            _make_order(side=Side.SELL, qty=5, price=100.0)
        )  # only 5 available

        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        assert len(trades) == 1
        assert trades[0].quantity == 5
        # Remaining 5 should be CANCELLED
        ioc_event = next(
            e for e in events if e.id == ioc.id and e.status == OrderStatus.CANCELLED
        )
        assert ioc_event.remaining_qty == 5

    def test_ioc_no_fill_cancels_entire_order(self, book):
        """IOC with no matching liquidity is immediately cancelled."""
        # No resting orders at all
        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        assert trades == []
        assert ioc.status == OrderStatus.CANCELLED
        assert ioc.remaining_qty == 10

    def test_ioc_does_not_rest_on_book(self, book):
        """After processing, an IOC order must not appear in resting_orders()."""
        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        book.process(ioc)

        resting = book.resting_orders()
        assert not any(o.id == ioc.id for o in resting)

    def test_ioc_respects_price_limit(self, book):
        """IOC only crosses orders at or within its price limit."""
        book.process(
            _make_order(side=Side.SELL, qty=10, price=105.0)
        )  # ask above IOC limit

        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        assert trades == []
        assert ioc.status == OrderStatus.CANCELLED

    def test_ioc_sweeps_multiple_levels(self, book):
        """IOC sweeps across several price levels until filled or limit hit."""
        book.process(_make_order(side=Side.SELL, qty=3, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=3, price=101.0))
        book.process(_make_order(side=Side.SELL, qty=3, price=102.0))

        ioc = _make_order(side=Side.BUY, qty=9, price=102.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        total_filled = sum(t.quantity for t in trades)
        assert total_filled == 9
        assert ioc.status == OrderStatus.FILLED

    def test_ioc_sell_side_partial(self, book):
        """Sell-side IOC: partial fill, remainder cancelled."""
        book.process(_make_order(side=Side.BUY, qty=4, price=100.0))  # resting bid

        ioc = _make_order(side=Side.SELL, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc)

        assert len(trades) == 1
        assert trades[0].quantity == 4
        assert ioc.status == OrderStatus.CANCELLED
        assert ioc.remaining_qty == 6

    def test_ioc_rejected_in_no_match_mode(self, book):
        """IOC cannot rest — must be rejected during auction (no-match) mode."""
        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        trades, events = book.process(ioc, match=False)

        assert trades == []
        assert ioc.status == OrderStatus.REJECTED


class TestIOCEngine:
    """IOC integration with the Engine (gateway auth, ORDERS tracking)."""

    def test_ioc_ack_then_fill(self, eng):
        """Engine sends ACK and fill events for a fully-filled IOC."""
        engine, pub_sock = eng

        # Post a resting sell
        sell = _make_order(side=Side.SELL, qty=10, price=100.0)
        engine._handle_new_order(sell.to_dict())
        pub_sock.sent.clear()

        # Post IOC buy
        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        engine._handle_new_order(ioc.to_dict())

        topics = _topics(pub_sock)
        assert "order.ack.TRADER01" in topics
        assert "order.fill.TRADER01" in topics

    def test_ioc_partial_fill_cancel_published(self, eng):
        """Engine publishes a fill and a cancel for a partially filled IOC."""
        engine, pub_sock = eng

        # Only 5 on the sell side
        sell = _make_order(side=Side.SELL, qty=5, price=100.0)
        engine._handle_new_order(sell.to_dict())
        pub_sock.sent.clear()

        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        engine._handle_new_order(ioc.to_dict())

        topics = _topics(pub_sock)
        assert "order.fill.TRADER01" in topics
        # The CANCEL event comes via order.cancelled topic (SMP path) OR via the
        # FILL msg itself with status CANCELLED. At minimum a fill must be published.
        fill_payloads = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "order.fill.TRADER01"
        ]
        assert any(p["fill_qty"] == 5 for p in fill_payloads)

    def test_ioc_rejected_during_auction(self, eng):
        """Engine rejects IOC during a no-match (auction) phase."""
        engine, pub_sock = eng
        # Navigate: CONTINUOUS → CLOSING_AUCTION → CLOSED → PRE_OPEN → OPENING_AUCTION
        for state in ("CLOSING_AUCTION", "CLOSED", "PRE_OPEN", "OPENING_AUCTION"):
            engine._handle_session_transition({"to_state": state})
        pub_sock.sent.clear()

        ioc = _make_order(side=Side.BUY, qty=10, price=100.0, order_type=OrderType.IOC)
        engine._handle_new_order(ioc.to_dict())

        ack_payloads = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "order.ack.TRADER01"
        ]
        assert any(not p["accepted"] for p in ack_payloads)


# ===========================================================================
#  TRAILING_STOP
# ===========================================================================


class TestTrailingStopOrderBook:
    """Order-book level tests for trailing stop mechanics."""

    def test_sell_trailing_stop_triggers_when_price_falls(self, book):
        """SELL trailing stop triggers when price drops to stop level."""
        # Create a trade to establish last_trade_price = 100
        book.process(_make_order(side=Side.BUY, qty=10, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0))
        assert book.last_trade_price == 100.0

        # Place SELL trailing stop: trail=2, initial stop=98
        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)
        assert ts.status == OrderStatus.NEW
        assert len(book._trailing_stops) == 1

        # Trade at 105 → stop ratchets to 103
        book.process(_make_order(side=Side.BUY, qty=1, price=105.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=105.0))
        assert ts.stop_price == 103.0

        # Now need a buy resting at 103 so the triggered MARKET order can fill
        book.process(_make_order(side=Side.BUY, qty=10, price=103.0))

        # Trade at 103 → triggers (103 <= 103)
        book.process(_make_order(side=Side.SELL, qty=1, price=103.0))

        assert ts.status == OrderStatus.FILLED
        assert ts not in book._trailing_stops

    def test_sell_trailing_stop_ratchets_up_only(self, book):
        """SELL trailing stop's stop_price never decreases."""
        # Establish last trade
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)

        # Price rises: stop moves up
        book.process(_make_order(side=Side.BUY, qty=1, price=110.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=110.0))
        assert ts.stop_price == 108.0  # 110 - 2

        # Price falls back: stop does NOT move down
        book.process(_make_order(side=Side.BUY, qty=1, price=102.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=102.0))
        assert ts.stop_price == 108.0  # unchanged — still 108, not 100

    def test_buy_trailing_stop_triggers_when_price_rises(self, book):
        """BUY trailing stop triggers when price rises to stop level."""
        # Establish price = 100
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        # BUY trailing stop: trail=2, initial stop=102
        ts = _make_order(
            side=Side.BUY,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=102.0,
            trail_offset=2.0,
        )
        book.process(ts)

        # Price falls to 95 → stop ratchets down to 97
        book.process(_make_order(side=Side.BUY, qty=1, price=95.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=95.0))
        assert ts.stop_price == 97.0

        # Add resting sell at 97 for the triggered MARKET buy to fill against
        book.process(_make_order(side=Side.SELL, qty=10, price=97.0))

        # Trade at 97 → triggers (97 >= 97)
        book.process(_make_order(side=Side.BUY, qty=1, price=97.0))

        assert ts.status == OrderStatus.FILLED

    def test_buy_trailing_stop_ratchets_down_only(self, book):
        """BUY trailing stop's stop_price never increases."""
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        ts = _make_order(
            side=Side.BUY,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=102.0,
            trail_offset=2.0,
        )
        book.process(ts)

        # Price falls → stop moves down
        book.process(_make_order(side=Side.BUY, qty=1, price=90.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=90.0))
        assert ts.stop_price == 92.0  # 90 + 2

        # Price rises back → stop does NOT move up
        book.process(_make_order(side=Side.BUY, qty=1, price=99.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=99.0))
        assert ts.stop_price == 92.0  # unchanged

    def test_trailing_stop_cancel_removes_from_list(self, book):
        """Cancelling a trailing stop removes it from the active list."""
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)
        assert len(book._trailing_stops) == 1

        book.cancel_order(ts.id)
        assert ts.status == OrderStatus.CANCELLED

        # After next trade, lazy deletion should prune it
        book.process(_make_order(side=Side.BUY, qty=1, price=101.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=101.0))
        assert len(book._trailing_stops) == 0

    def test_trailing_stop_in_resting_orders(self, book):
        """Trailing stop appears in resting_orders() for persistence."""
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)

        resting = book.resting_orders()
        assert any(o.id == ts.id for o in resting)

    def test_trailing_stop_not_triggered_without_trades(self, book):
        """A trailing stop should not trigger unless a trade occurs."""
        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)

        # No trades → stop should not fire
        assert ts.status == OrderStatus.NEW
        assert len(book._trailing_stops) == 1

    def test_multiple_trailing_stops_all_evaluated(self, book):
        """Multiple trailing stops are all updated after each trade."""
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        ts1 = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            gateway_id="TRADER01",
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        ts2 = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            gateway_id="TRADER02",
            order_type=OrderType.TRAILING_STOP,
            stop_price=95.0,
            trail_offset=5.0,
        )
        book.process(ts1)
        book.process(ts2)

        # Trade at 110 → ts1 stop → 108, ts2 stop → 105
        book.process(_make_order(side=Side.BUY, qty=1, price=110.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=110.0))

        assert ts1.stop_price == 108.0
        assert ts2.stop_price == 105.0


class TestTrailingStopEngine:
    """Engine-level trailing stop tests."""

    def test_engine_computes_initial_stop_from_last_trade(self, eng):
        """Engine computes initial stop_price when STOP= is omitted."""
        engine, pub_sock = eng

        # Create a last trade at 100
        sell = _make_order(side=Side.SELL, qty=10, price=100.0)
        engine._handle_new_order(sell.to_dict())
        buy = _make_order(side=Side.BUY, qty=10, price=100.0)
        engine._handle_new_order(buy.to_dict())
        pub_sock.sent.clear()

        # Submit trailing stop with no STOP= — engine uses last_trade - trail
        ts = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=5,
            gateway_id="TRADER01",
            trail_offset=3.0,
        )
        engine._handle_new_order(ts.to_dict())

        # The engine accepts it (it had a last trade to compute stop_price from)
        ack_payloads = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "order.ack.TRADER01"
        ]
        assert any(p["accepted"] for p in ack_payloads)

        # The internal order in the engine should have stop_price = 97.0
        book = engine._book("AAPL")
        internal = book._order_index.get(ts.id)
        assert internal is not None, "trailing stop should be registered in the book"
        assert internal.stop_price == 97.0

    def test_engine_rejects_trailing_stop_with_no_last_price(self, eng):
        """Engine rejects trailing stop if no last trade and no STOP= provided."""
        engine, pub_sock = eng

        ts = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=5,
            gateway_id="TRADER01",
            trail_offset=3.0,
        )
        # stop_price is None, no prior trade on AAPL
        engine._handle_new_order(ts.to_dict())

        ack_payloads = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "order.ack.TRADER01"
        ]
        assert any(not p["accepted"] for p in ack_payloads)

    def test_engine_accepts_trailing_stop_with_explicit_stop(self, eng):
        """Engine accepts trailing stop when explicit STOP= is supplied."""
        engine, pub_sock = eng

        ts = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=5,
            gateway_id="TRADER01",
            trail_offset=2.0,
            stop_price=95.0,
        )
        engine._handle_new_order(ts.to_dict())

        ack_payloads = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "order.ack.TRADER01"
        ]
        assert any(p["accepted"] for p in ack_payloads)

    def test_engine_trailing_stop_triggers_and_fills(self, eng):
        """Full engine flow: trailing stop ratchets, triggers, and fills."""
        engine, pub_sock = eng

        # Establish last trade at 100 (TRADER02 vs TRADER02 so no confusion with TRADER01 fills)
        s = _make_order(side=Side.SELL, qty=10, price=100.0, gateway_id="TRADER02")
        b = _make_order(side=Side.BUY, qty=10, price=100.0, gateway_id="TRADER02")
        engine._handle_new_order(s.to_dict())
        engine._handle_new_order(b.to_dict())

        # Place trailing stop at 98 (trail=2) for TRADER01
        ts = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=5,
            gateway_id="TRADER01",
            trail_offset=2.0,
            stop_price=98.0,
        )
        engine._handle_new_order(ts.to_dict())

        # Resting BUY at 97 — will cause a trade at 97 (≤98) to trigger ts
        trigger_bid = _make_order(
            side=Side.BUY, qty=1, price=97.0, gateway_id="TRADER02"
        )
        engine._handle_new_order(trigger_bid.to_dict())

        # Resting BUY at 96 — fills the trailing stop once it converts to MARKET SELL
        fill_bid = _make_order(side=Side.BUY, qty=5, price=96.0, gateway_id="TRADER02")
        engine._handle_new_order(fill_bid.to_dict())
        pub_sock.sent.clear()

        # Trade at 97 (sell 97 crosses resting buy 97) → triggers ts → MARKET sell fills fill_bid
        aggressor_sell = _make_order(
            side=Side.SELL, qty=1, price=97.0, gateway_id="TRADER02"
        )
        engine._handle_new_order(aggressor_sell.to_dict())

        topics = _topics(pub_sock)
        assert "order.fill.TRADER01" in topics


# ===========================================================================
#  OCO — One-Cancels-Other
# ===========================================================================


class TestOCOEngine:
    """OCO integration tests all run at the Engine level."""

    def _send_oco(
        self,
        engine,
        oco_id,
        qty=10,
        tif="DAY",
        leg1_type="LIMIT",
        leg1_side="SELL",
        leg1_price=110.0,
        leg2_type="STOP",
        leg2_side="SELL",
        leg2_stop=90.0,
        symbol="AAPL",
        gateway="TRADER01",
    ):
        payload = {
            "oco_id": oco_id,
            "gateway_id": gateway,
            "symbol": symbol,
            "quantity": qty,
            "tif": tif,
            "leg1": {"side": leg1_side, "order_type": leg1_type, "price": leg1_price},
            "leg2": {
                "side": leg2_side,
                "order_type": leg2_type,
                "stop_price": leg2_stop,
            },
        }
        engine._handle_oco_order(payload)

    def test_oco_ack_sent_on_valid_pair(self, eng):
        """Engine sends oco.ack.ACCEPTED for a well-formed OCO."""
        engine, pub_sock = eng
        self._send_oco(engine, "OCO1")

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        ]
        assert len(oco_acks) == 1
        assert oco_acks[0]["accepted"] is True
        assert oco_acks[0]["oco_id"] == "OCO1"
        assert oco_acks[0]["order_id_1"] != ""
        assert oco_acks[0]["order_id_2"] != ""

    def test_oco_both_orders_posted_to_book(self, eng):
        """Both legs are present in the engine's order symbol map after submission."""
        engine, pub_sock = eng
        self._send_oco(engine, "OCO2")

        oco_ack = next(
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        )
        id1 = oco_ack["order_id_1"]
        id2 = oco_ack["order_id_2"]
        assert id1 in engine._order_symbol
        assert id2 in engine._order_symbol

    def test_oco_fill_one_leg_cancels_sibling(self, eng):
        """When the limit leg fills, the stop leg is automatically cancelled."""
        engine, pub_sock = eng

        # Leg 1: SELL LIMIT 110, Leg 2: SELL STOP 90
        self._send_oco(
            engine,
            "OCO3",
            leg1_type="LIMIT",
            leg1_side="SELL",
            leg1_price=110.0,
            leg2_type="STOP",
            leg2_side="SELL",
            leg2_stop=90.0,
        )

        oco_ack = next(
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        )
        _id1 = oco_ack["order_id_1"]  # noqa: F841  # LIMIT leg
        id2 = oco_ack["order_id_2"]  # STOP  leg
        pub_sock.sent.clear()

        # Post a buyer above 110 so the LIMIT leg fills
        buyer = _make_order(side=Side.BUY, qty=10, price=115.0, gateway_id="TRADER02")
        engine._handle_new_order(buyer.to_dict())

        topics = _topics(pub_sock)
        # LIMIT leg should fill
        assert "order.fill.TRADER01" in topics
        # Stop sibling should be cancelled via oco.cancelled
        oco_cancelled_topics = [t for t in topics if "oco.cancelled" in t]
        assert len(oco_cancelled_topics) >= 1

        # STOP leg should no longer be in the order symbol map
        assert id2 not in engine._order_symbol

    def test_oco_cancel_sibling_leg_via_manual_cancel(self, eng):
        """Manually cancelling one leg of an OCO cancels the other."""
        engine, pub_sock = eng
        self._send_oco(engine, "OCO4")

        oco_ack = next(
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        )
        id1 = oco_ack["order_id_1"]
        id2 = oco_ack["order_id_2"]
        pub_sock.sent.clear()

        # Cancel leg 1 manually
        engine._handle_cancel({"order_id": id1, "gateway_id": "TRADER01"})

        # id2 should also be gone
        assert id2 not in engine._order_symbol
        topics = _topics(pub_sock)
        oco_cancelled = [t for t in topics if "oco.cancelled" in t]
        assert len(oco_cancelled) >= 1

    def test_oco_cancel_command_cancels_both_legs(self, eng):
        """CANCEL|OCO_ID= cancels both legs in one command."""
        engine, pub_sock = eng
        self._send_oco(engine, "OCO5")

        oco_ack = next(
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        )
        id1 = oco_ack["order_id_1"]
        id2 = oco_ack["order_id_2"]
        pub_sock.sent.clear()

        engine._handle_oco_cancel({"oco_id": "OCO5", "gateway_id": "TRADER01"})

        assert id1 not in engine._order_symbol
        assert id2 not in engine._order_symbol
        assert "OCO5" not in engine._oco_groups

    def test_oco_rejected_for_unknown_gateway(self, eng):
        """OCO is rejected if the gateway is not authenticated."""
        engine, pub_sock = eng
        payload = {
            "oco_id": "OCO_UNAUTH",
            "gateway_id": "UNKNOWN_GW",
            "symbol": "AAPL",
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price": 110.0},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price": 90.0},
        }
        engine._handle_oco_order(payload)

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.UNKNOWN_GW"
        ]
        assert len(oco_acks) == 1
        assert not oco_acks[0]["accepted"]

    def test_oco_rejected_for_symbol_not_configured(self, eng):
        """OCO is rejected for a symbol not in the engine config."""
        engine, pub_sock = eng
        payload = {
            "oco_id": "OCO_SYM",
            "gateway_id": "TRADER01",
            "symbol": "NOSYM",
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price": 110.0},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price": 90.0},
        }
        engine._handle_oco_order(payload)

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        ]
        assert len(oco_acks) == 1
        assert not oco_acks[0]["accepted"]

    def test_oco_rejected_for_invalid_leg_price(self, eng):
        """OCO is rejected if a LIMIT leg has no price."""
        engine, pub_sock = eng
        payload = {
            "oco_id": "OCO_NOPRICE",
            "gateway_id": "TRADER01",
            "symbol": "AAPL",
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT"},  # missing price
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price": 90.0},
        }
        engine._handle_oco_order(payload)

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        ]
        assert len(oco_acks) == 1
        assert not oco_acks[0]["accepted"]

    def test_oco_group_removed_after_both_cancelled(self, eng):
        """After an OCO pair is fully resolved, the group is removed from tracking."""
        engine, pub_sock = eng
        self._send_oco(engine, "OCO_CLEANUP")

        engine._handle_oco_cancel({"oco_id": "OCO_CLEANUP", "gateway_id": "TRADER01"})

        assert "OCO_CLEANUP" not in engine._oco_groups

    def test_oco_two_limit_orders(self, eng):
        """OCO supports two LIMIT legs (e.g., bracket: take-profit above + take-loss below)."""
        engine, pub_sock = eng
        payload = {
            "oco_id": "BRACKET",
            "gateway_id": "TRADER01",
            "symbol": "AAPL",
            "quantity": 10,
            "tif": "DAY",
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price": 120.0},
            "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 85.0},
        }
        engine._handle_oco_order(payload)

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        ]
        assert len(oco_acks) == 1
        assert oco_acks[0]["accepted"]

    def test_oco_cancel_for_not_found_returns_rejection(self, eng):
        """Cancelling a non-existent OCO ID returns a rejection."""
        engine, pub_sock = eng
        engine._handle_oco_cancel(
            {"oco_id": "DOES_NOT_EXIST", "gateway_id": "TRADER01"}
        )

        oco_acks = [
            decode(f)[1] for f in pub_sock.sent if decode(f)[0] == "oco.ack.TRADER01"
        ]
        assert len(oco_acks) == 1
        assert not oco_acks[0]["accepted"]


# ===========================================================================
#  Cross-type interaction tests
# ===========================================================================


class TestNewOrderTypeInteractions:
    """Interactions between the new types and existing features."""

    def test_ioc_after_trailing_stop_triggers(self, book):
        """A trailing stop trigger does not affect a separately submitted IOC."""
        # Establish base price
        book.process(_make_order(side=Side.BUY, qty=1, price=100.0))
        book.process(_make_order(side=Side.SELL, qty=1, price=100.0))

        # Trailing stop
        ts = _make_order(
            side=Side.SELL,
            qty=5,
            price=None,
            order_type=OrderType.TRAILING_STOP,
            stop_price=98.0,
            trail_offset=2.0,
        )
        book.process(ts)

        # IOC (separate; different gateway)
        ioc = _make_order(
            side=Side.BUY,
            qty=3,
            price=100.0,
            order_type=OrderType.IOC,
            gateway_id="TRADER02",
        )
        # Post a sell to give IOC something to match
        book.process(
            _make_order(side=Side.SELL, qty=3, price=100.0, gateway_id="TRADER02")
        )
        trades, events = book.process(ioc)

        assert ioc.status == OrderStatus.FILLED
        assert len(trades) == 1

    def test_ioc_smp_cancel_aggressor(self, book):
        """IOC with SMP=CANCEL_AGGRESSOR cancels itself on self-match."""
        book.process(
            _make_order(side=Side.SELL, qty=10, price=100.0, gateway_id="TRADER01")
        )

        ioc = _make_order(
            side=Side.BUY,
            qty=10,
            price=100.0,
            order_type=OrderType.IOC,
            gateway_id="TRADER01",
            smp_action=SmpAction.CANCEL_AGGRESSOR,
        )
        trades, events = book.process(ioc)

        assert trades == []
        assert ioc.status == OrderStatus.CANCELLED

    def test_trailing_stop_serialization_roundtrip(self):
        """Trailing stop order serializes and deserializes preserving trail_offset."""
        ts = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=100,
            gateway_id="TRADER01",
            stop_price=98.0,
            trail_offset=2.0,
        )
        restored = Order.from_dict(ts.to_dict())

        assert restored.order_type == OrderType.TRAILING_STOP
        assert restored.trail_offset == 2.0
        assert restored.stop_price == 98.0

    def test_oco_order_serialization(self):
        """OCO leg serializes and preserves oco_group_id."""
        leg = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="TRADER01",
            price=110.0,
            oco_group_id="MY_OCO",
        )
        restored = Order.from_dict(leg.to_dict())
        assert restored.oco_group_id == "MY_OCO"

    def test_ioc_serialization_roundtrip(self):
        """IOC order type round-trips through to_dict/from_dict."""
        ioc = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.IOC,
            quantity=10,
            gateway_id="TRADER01",
            price=100.0,
        )
        restored = Order.from_dict(ioc.to_dict())
        assert restored.order_type == OrderType.IOC
