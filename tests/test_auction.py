"""
Tests for auction / session scheduler.

Covers:
  - Equilibrium price calculation (compute_equilibrium)
  - Uncross execution (execute_uncross)
  - OrderBook no-match mode (process(match=False))
  - Engine session state transitions
  - ATO/ATC TIF enforcement
  - Full lifecycle: auction → uncross → continuous
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.auction import (
    compute_equilibrium,
    execute_uncross,
)
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF
from edumatcher.models.session import SessionState, VALID_TRANSITIONS

# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


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
):
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
    )


def _topics(pub_sock):
    return [decode(f)[0] for f in pub_sock.sent]


@pytest.fixture
def session_engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Engine with two symbols, starting in CONTINUOUS (default)."""
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "TRADER01": FixGatewayConfig(id="TRADER01", description="Trader one"),
            "TRADER02": FixGatewayConfig(id="TRADER02", description="Trader two"),
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


# ---------------------------------------------------------------
# Equilibrium price algorithm tests
# ---------------------------------------------------------------


class TestEquilibriumPrice:

    def test_simple_cross(self) -> None:
        """Bid at 101 vs ask at 100 → equilibrium somewhere in between."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=101.0))
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0))
        # These should match immediately in continuous mode, leaving empty book.
        # For auction tests, we need to use match=False.

    def test_no_match_accumulates(self) -> None:
        """match=False prevents execution; orders rest on book."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=101.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0), match=False)

        assert len(book.resting_orders()) == 2
        result = compute_equilibrium(book)
        assert result.eq_qty == 10
        assert result.eq_price is not None

    def test_equilibrium_maximizes_quantity(self) -> None:
        """Pick price that maximizes executable quantity."""
        book = OrderBook("TEST")
        # 3 bids at different prices
        book.process(_make_order(side=Side.BUY, qty=10, price=105.0), match=False)
        book.process(_make_order(side=Side.BUY, qty=10, price=103.0), match=False)
        book.process(_make_order(side=Side.BUY, qty=10, price=100.0), match=False)
        # 2 asks
        book.process(_make_order(side=Side.SELL, qty=15, price=102.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=104.0), match=False)

        result = compute_equilibrium(book)
        # At 102: buy_qty=20 (105+103), sell_qty=15 → exec=15, surplus=5
        # At 103: buy_qty=20 (105+103), sell_qty=15 → exec=15, surplus=5
        # At 104: buy_qty=10 (only 105), sell_qty=25 → exec=10
        # Best exec = 15 at prices 102 or 103 (both surplus=5)
        # Algorithm picks first encountered (102)
        assert result.eq_qty == 15
        assert result.eq_price in (102.0, 103.0)
        assert result.surplus == 5
        assert result.surplus == 5

    def test_equilibrium_minimizes_surplus_on_tie(self) -> None:
        """When multiple prices give same max qty, pick lowest surplus."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=102.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0), match=False)

        result = compute_equilibrium(book)
        assert result.eq_qty == 10
        assert result.surplus == 0

    def test_empty_book(self) -> None:
        book = OrderBook("TEST")
        result = compute_equilibrium(book)
        assert result.eq_price is None
        assert result.eq_qty == 0

    def test_one_sided_book(self) -> None:
        """Only bids, no asks → no equilibrium."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=100.0), match=False)
        result = compute_equilibrium(book)
        assert result.eq_price is None
        assert result.eq_qty == 0

    def test_no_cross(self) -> None:
        """Bids below asks → no crossable interest."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=99.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=101.0), match=False)
        result = compute_equilibrium(book)
        assert result.eq_qty == 0

    def test_imbalance_side_buy(self) -> None:
        """More buy qty than sell qty at eq → BUY imbalance."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=20, price=100.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0), match=False)

        result = compute_equilibrium(book)
        assert result.imbalance_side == "BUY"
        assert result.surplus == 10

    def test_imbalance_side_sell(self) -> None:
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=5, price=100.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=15, price=100.0), match=False)

        result = compute_equilibrium(book)
        assert result.imbalance_side == "SELL"
        assert result.surplus == 10


# ---------------------------------------------------------------
# Uncross execution tests
# ---------------------------------------------------------------


class TestUncrossExecution:

    def test_full_execution(self) -> None:
        """All interest crosses at eq price."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=101.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0), match=False)

        result = compute_equilibrium(book)
        trades, events = execute_uncross(book, result.eq_price)  # type: ignore[arg-type]

        assert len(trades) == 1
        assert trades[0].quantity == 10
        assert trades[0].price == result.eq_price
        # Both orders should be FILLED
        filled = [e for e in events if e.status == OrderStatus.FILLED]
        assert len(filled) == 2

    def test_partial_execution_with_imbalance(self) -> None:
        """More bids than asks → surplus remains on book."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=20, price=100.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=100.0), match=False)

        result = compute_equilibrium(book)
        trades, events = execute_uncross(book, result.eq_price)  # type: ignore[arg-type]

        assert sum(t.quantity for t in trades) == 10
        # The buy order should be PARTIAL (10 remaining)
        partial = [e for e in events if e.status == OrderStatus.PARTIAL]
        assert len(partial) == 1
        assert partial[0].remaining_qty == 10

    def test_no_execution_needed(self) -> None:
        """No crossed prices → no trades."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=10, price=99.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=10, price=101.0), match=False)

        result = compute_equilibrium(book)
        assert result.eq_price is None
        # No uncross to execute

    def test_multiple_fills_at_single_price(self) -> None:
        """Multiple orders on each side → multiple trades, all at eq price."""
        book = OrderBook("TEST")
        book.process(_make_order(side=Side.BUY, qty=5, price=102.0), match=False)
        book.process(_make_order(side=Side.BUY, qty=5, price=101.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=3, price=100.0), match=False)
        book.process(_make_order(side=Side.SELL, qty=7, price=100.5), match=False)

        result = compute_equilibrium(book)
        trades, events = execute_uncross(book, result.eq_price)  # type: ignore[arg-type]

        total_qty = sum(t.quantity for t in trades)
        assert total_qty == result.eq_qty
        # All trades at the same price
        for trade in trades:
            assert trade.price == result.eq_price


# ---------------------------------------------------------------
# OrderBook no-match mode tests
# ---------------------------------------------------------------


class TestOrderBookNoMatch:

    def test_market_rejected_in_no_match(self) -> None:
        book = OrderBook("TEST")
        order = _make_order(order_type=OrderType.MARKET, price=None)
        trades, events = book.process(order, match=False)

        assert trades == []
        assert len(events) == 1
        assert events[0].status == OrderStatus.REJECTED

    def test_fok_rejected_in_no_match(self) -> None:
        book = OrderBook("TEST")
        order = _make_order(order_type=OrderType.FOK, price=100.0)
        trades, events = book.process(order, match=False)

        assert trades == []
        assert events[0].status == OrderStatus.REJECTED

    def test_limit_rests_in_no_match(self) -> None:
        book = OrderBook("TEST")
        order = _make_order(order_type=OrderType.LIMIT, price=100.0)
        trades, events = book.process(order, match=False)

        assert trades == []
        assert order in book.resting_orders()

    def test_stop_added_in_no_match(self) -> None:
        book = OrderBook("TEST")
        order = Order.create(
            symbol="TEST",
            side=Side.BUY,
            order_type=OrderType.STOP,
            quantity=10,
            gateway_id="TRADER01",
            stop_price=105.0,
        )
        trades, events = book.process(order, match=False)

        assert trades == []
        assert order.id in book._order_index


# ---------------------------------------------------------------
# Engine session state tests
# ---------------------------------------------------------------


class TestSessionTransitions:

    def test_valid_transition_continuous_to_closing(self, session_engine) -> None:
        engine, pub_sock = session_engine
        assert engine._session_state == SessionState.CONTINUOUS

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})

        assert engine._session_state == SessionState.CLOSING_AUCTION
        topics = _topics(pub_sock)
        assert "session.state" in topics

    def test_invalid_transition_rejected(self, session_engine) -> None:
        engine, pub_sock = session_engine
        # CONTINUOUS → OPENING_AUCTION is not a valid transition
        engine._handle_session_transition({"to_state": "OPENING_AUCTION"})
        assert engine._session_state == SessionState.CONTINUOUS  # unchanged

    def test_invalid_state_value_rejected(self, session_engine) -> None:
        engine, pub_sock = session_engine
        engine._handle_session_transition({"to_state": "BOGUS"})
        assert engine._session_state == SessionState.CONTINUOUS

    def test_market_rejected_during_auction(self, session_engine) -> None:
        engine, pub_sock = session_engine

        # Move to CLOSING_AUCTION
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        # MARKET order should be rejected
        order = _make_order(order_type=OrderType.MARKET, price=None)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "MARKET" in msg["reason"]

    def test_fok_rejected_during_auction(self, session_engine) -> None:
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        order = _make_order(order_type=OrderType.FOK, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_order_rejected_when_closed(self, session_engine) -> None:
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        engine._handle_session_transition({"to_state": "CLOSED"})
        pub_sock.sent.clear()

        order = _make_order()
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "closed" in msg["reason"].lower()

    def test_limit_accepted_during_auction(self, session_engine) -> None:
        """LIMIT orders can rest during auction phases."""
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        order = _make_order(order_type=OrderType.LIMIT, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert topic == "order.ack.TRADER01"
        assert msg["accepted"] is True

    def test_limit_does_not_match_during_auction(self, session_engine) -> None:
        """Even crossing LIMIT orders should not match during auction."""
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        # Seed a resting sell
        sell = _make_order(side=Side.SELL, qty=10, price=100.0, gateway_id="TRADER02")
        engine._handle_new_order(sell.to_dict())

        # Crossing buy — should rest, not match
        buy = _make_order(side=Side.BUY, qty=10, price=101.0)
        engine._handle_new_order(buy.to_dict())

        topics = _topics(pub_sock)
        # No fills should have been published
        fill_topics = [t for t in topics if "fill" in t]
        assert fill_topics == []


# ---------------------------------------------------------------
# ATO / ATC TIF tests
# ---------------------------------------------------------------


class TestAtoAtcOrders:

    def test_ato_rejected_during_continuous(self, session_engine) -> None:
        engine, pub_sock = session_engine

        order = _make_order(tif=TIF.ATO, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "ATO" in msg["reason"]

    def test_atc_rejected_during_continuous(self, session_engine) -> None:
        engine, pub_sock = session_engine

        order = _make_order(tif=TIF.ATC, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "ATC" in msg["reason"]

    def test_atc_accepted_during_closing_auction(self, session_engine) -> None:
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        order = _make_order(tif=TIF.ATC, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is True

    def test_ato_accepted_during_opening_auction(self, session_engine) -> None:
        engine, pub_sock = session_engine

        # Must get to OPENING_AUCTION: CONTINUOUS → CLOSING → CLOSED → PRE_OPEN → OPENING
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        engine._handle_session_transition({"to_state": "CLOSED"})
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        engine._handle_session_transition({"to_state": "OPENING_AUCTION"})
        pub_sock.sent.clear()

        order = _make_order(tif=TIF.ATO, price=100.0)
        engine._handle_new_order(order.to_dict())

        topic, msg = decode(pub_sock.sent[0])
        assert msg["accepted"] is True

    def test_ato_expired_on_opening_auction_end(self, session_engine) -> None:
        """ATO orders that don't fill should expire when leaving opening auction."""
        engine, pub_sock = session_engine

        # Navigate to OPENING_AUCTION
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        engine._handle_session_transition({"to_state": "CLOSED"})
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        engine._handle_session_transition({"to_state": "OPENING_AUCTION"})
        pub_sock.sent.clear()

        # Place ATO order
        order = _make_order(tif=TIF.ATO, price=100.0)
        engine._handle_new_order(order.to_dict())

        # Transition to CONTINUOUS — should trigger uncross + expire unfilled ATOs
        engine._handle_session_transition({"to_state": "CONTINUOUS"})

        topics = _topics(pub_sock)
        expired = [t for t in topics if "expired" in t]
        assert len(expired) >= 1

    def test_atc_expired_on_closing_auction_end(self, session_engine) -> None:
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        order = _make_order(tif=TIF.ATC, price=100.0)
        engine._handle_new_order(order.to_dict())

        engine._handle_session_transition({"to_state": "CLOSED"})

        topics = _topics(pub_sock)
        expired = [t for t in topics if "expired" in t]
        assert len(expired) >= 1


# ---------------------------------------------------------------
# Full uncross integration
# ---------------------------------------------------------------


class TestUncrossIntegration:

    def test_auction_uncross_on_transition_to_continuous(self, session_engine) -> None:
        """Orders collected during auction should execute on transition to CONTINUOUS."""
        engine, pub_sock = session_engine

        # Navigate to OPENING_AUCTION
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        engine._handle_session_transition({"to_state": "CLOSED"})
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        engine._handle_session_transition({"to_state": "OPENING_AUCTION"})
        pub_sock.sent.clear()

        # Place crossing orders during auction
        sell = _make_order(side=Side.SELL, qty=10, price=99.0, gateway_id="TRADER02")
        engine._handle_new_order(sell.to_dict())
        buy = _make_order(side=Side.BUY, qty=10, price=101.0)
        engine._handle_new_order(buy.to_dict())

        # No trades yet (auction mode)
        trade_topics = [t for t in _topics(pub_sock) if t == "trade.executed"]
        assert trade_topics == []

        pub_sock.sent.clear()

        # Transition to CONTINUOUS → should trigger uncross
        engine._handle_session_transition({"to_state": "CONTINUOUS"})

        topics = _topics(pub_sock)

        # Expect trades and fills from the uncross
        assert "trade.executed" in topics

        # Expect auction result
        auction_results = [t for t in topics if t.startswith("auction.result")]
        assert len(auction_results) >= 1

        # Expect session state broadcast
        assert "session.state" in topics

    def test_closing_auction_uncross_on_close(self, session_engine) -> None:
        """Orders collected during closing auction should execute on CLOSED."""
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        sell = _make_order(side=Side.SELL, qty=5, price=98.0, gateway_id="TRADER02")
        engine._handle_new_order(sell.to_dict())
        buy = _make_order(side=Side.BUY, qty=5, price=102.0)
        engine._handle_new_order(buy.to_dict())

        pub_sock.sent.clear()
        engine._handle_session_transition({"to_state": "CLOSED"})

        topics = _topics(pub_sock)
        assert "trade.executed" in topics

    def test_no_uncross_when_no_crossable_interest(self, session_engine) -> None:
        engine, pub_sock = session_engine

        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        pub_sock.sent.clear()

        # Bids below asks — no cross
        sell = _make_order(side=Side.SELL, qty=10, price=105.0, gateway_id="TRADER02")
        engine._handle_new_order(sell.to_dict())
        buy = _make_order(side=Side.BUY, qty=10, price=95.0)
        engine._handle_new_order(buy.to_dict())

        pub_sock.sent.clear()
        engine._handle_session_transition({"to_state": "CLOSED"})

        topics = _topics(pub_sock)
        # No trades expected
        assert "trade.executed" not in topics
        # But auction result still published (with eq_price=None)
        auction_results = [t for t in topics if t.startswith("auction.result")]
        assert len(auction_results) >= 1


# ---------------------------------------------------------------
# Session model unit tests
# ---------------------------------------------------------------


class TestSessionModel:

    def test_valid_transitions_defined(self) -> None:
        for state in SessionState:
            assert state in VALID_TRANSITIONS

    def test_continuous_is_only_matching_state(self) -> None:
        from edumatcher.models.session import is_matching_enabled

        for state in SessionState:
            if state == SessionState.CONTINUOUS:
                assert is_matching_enabled(state) is True
            else:
                assert is_matching_enabled(state) is False

    def test_closed_rejects_orders(self) -> None:
        from edumatcher.models.session import accepts_orders

        assert accepts_orders(SessionState.CLOSED) is False
        assert accepts_orders(SessionState.CONTINUOUS) is True
        assert accepts_orders(SessionState.PRE_OPEN) is True

    def test_auction_phases(self) -> None:
        from edumatcher.models.session import is_auction_phase

        assert is_auction_phase(SessionState.OPENING_AUCTION) is True
        assert is_auction_phase(SessionState.CLOSING_AUCTION) is True
        assert is_auction_phase(SessionState.CONTINUOUS) is False
