"""
Tests for instrument halt (Phase 1) and price collar (Phase 3) engine integration.

These tests drive the engine's message handlers directly — no real ZMQ sockets.
The engine fixture is built by monkeypatching ``make_puller`` and ``make_publisher``
exactly as the existing integration tests do.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreakerLevel,
    CircuitBreakerState,
)
from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.price import register_tick_decimals


@dataclass
class _DummySocket:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Basic engine with AAPL + two trader gateways.  Drop copy NOT wired."""
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    register_tick_decimals("AAPL", 2)

    cfg = EngineConfig(
        symbols={"AAPL": SymbolConfig(name="AAPL", tick_decimals=2)},
        fix_gateways={
            "TRADER01": FixGatewayConfig(id="TRADER01"),
            "TRADER02": FixGatewayConfig(id="TRADER02"),
        },
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    eng = Engine(config_path=str(cfg_path))
    # Connect traders
    eng._handle_gateway_connect({"gateway_id": "TRADER01"})
    eng._handle_gateway_connect({"gateway_id": "TRADER02"})
    pub_sock.sent.clear()
    return eng, pub_sock


def _order_dict(
    *,
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    order_type: OrderType = OrderType.LIMIT,
    qty: int = 100,
    price: float | None = 100.0,
    gateway_id: str = "TRADER01",
    tif: TIF = TIF.DAY,
) -> dict:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
    ).to_dict()


# ──────────────────────────────────────────────────────────────────────────────
# Halt tests
# ──────────────────────────────────────────────────────────────────────────────


class TestHaltState:
    def test_not_halted_by_default(self, engine) -> None:
        eng, _ = engine
        assert not eng._halted_symbols.get("AAPL")

    def test_market_order_rejected_when_halted(self, engine) -> None:
        eng, pub = engine
        eng._halted_symbols["AAPL"] = True

        eng._handle_new_order(_order_dict(order_type=OrderType.MARKET, price=None))
        topic, msg = decode(pub.sent[-1])
        assert topic.startswith("order.ack.")
        assert msg["accepted"] is False
        assert "halted" in msg["reason"].lower()

    def test_fok_order_rejected_when_halted(self, engine) -> None:
        eng, pub = engine
        eng._halted_symbols["AAPL"] = True

        eng._handle_new_order(_order_dict(order_type=OrderType.FOK))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is False
        assert "halted" in msg["reason"].lower()

    def test_ioc_order_rejected_when_halted(self, engine) -> None:
        eng, pub = engine
        eng._halted_symbols["AAPL"] = True

        eng._handle_new_order(_order_dict(order_type=OrderType.IOC))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is False

    def test_limit_order_accepted_but_no_match_when_halted(self, engine) -> None:
        """LIMIT orders are accepted during halt — they collect as auction interest."""
        eng, pub = engine
        eng._halted_symbols["AAPL"] = True

        # Place a resting ask first (without halt) to give something to match against
        eng._halted_symbols["AAPL"] = False
        ask = _order_dict(side=Side.SELL, price=100.0, qty=100)
        eng._handle_new_order(ask)
        pub.sent.clear()

        eng._halted_symbols["AAPL"] = True
        # A bid at 100.0 would cross the resting ask, but matching is suppressed
        bid = _order_dict(side=Side.BUY, price=100.0, qty=100)
        eng._handle_new_order(bid)

        # Should get an ack (accepted) but no fill
        topics_sent = [decode(f)[0] for f in pub.sent]
        assert any("order.ack." in t for t in topics_sent)
        assert not any("order.fill." in t for t in topics_sent)

    def test_limit_order_acked_accepted_when_halted(self, engine) -> None:
        eng, pub = engine
        eng._halted_symbols["AAPL"] = True

        eng._handle_new_order(_order_dict(order_type=OrderType.LIMIT, price=100.0))
        topic, msg = decode(pub.sent[-1])
        assert "order.ack." in topic
        assert msg["accepted"] is True

    def test_non_halted_symbol_unaffected(self, engine) -> None:
        eng, pub = engine
        # Only halt MSFT; AAPL should work normally
        eng._halted_symbols["MSFT"] = True
        # AAPL LIMIT order should be accepted
        eng._handle_new_order(
            _order_dict(symbol="AAPL", order_type=OrderType.MARKET, price=None)
        )
        # Might be rejected for liquidity but not for halt
        topic, msg = decode(pub.sent[-1])
        # should NOT mention halted
        if not msg.get("accepted", True):
            assert "halted" not in msg.get("reason", "").lower()


# ──────────────────────────────────────────────────────────────────────────────
# Collar tests (engine integration)
# ──────────────────────────────────────────────────────────────────────────────


class TestCollarEngineIntegration:
    def _add_collar(self, eng: Engine, symbol: str = "AAPL") -> None:
        """Wire a collar for the symbol at reference_price=10000 ticks, ±20% static."""
        eng._collars[symbol] = CollarConfig(
            symbol=symbol,
            reference_price=10000,
            static_band_pct=0.20,
            dynamic_band_pct=0.02,
        )

    def test_order_within_collar_accepted(self, engine) -> None:
        eng, pub = engine
        self._add_collar(eng)
        # Price=100.0 → to_ticks("AAPL") = 10000; inside [8000, 12000]
        eng._handle_new_order(_order_dict(price=100.0))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is True

    def test_order_above_static_band_rejected(self, engine) -> None:
        eng, pub = engine
        self._add_collar(eng)
        # Reference=10000, static_upper=12000. Price 130.0 → 13000 ticks
        eng._handle_new_order(_order_dict(price=130.0))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is False
        assert "STATIC_COLLAR_BREACH" in msg["reason"]

    def test_order_below_static_band_rejected(self, engine) -> None:
        eng, pub = engine
        self._add_collar(eng)
        # Reference=10000, static_lower=8000. Price 79.0 → 7900 ticks
        eng._handle_new_order(_order_dict(price=79.0))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is False
        assert "STATIC_COLLAR_BREACH" in msg["reason"]

    def test_market_order_bypasses_collar(self, engine) -> None:
        """MARKET orders have no price so collar check is skipped."""
        eng, pub = engine
        self._add_collar(eng)
        eng._handle_new_order(_order_dict(order_type=OrderType.MARKET, price=None))
        topic, msg = decode(pub.sent[-1])
        # Any rejection is about liquidity, not collar
        if not msg.get("accepted", True):
            assert "COLLAR" not in msg.get("reason", "")

    def test_no_collar_order_always_accepted(self, engine) -> None:
        eng, pub = engine
        # No collar wired for AAPL
        eng._handle_new_order(_order_dict(price=99999.0))
        topic, msg = decode(pub.sent[-1])
        # Only acceptance check — no collar rejection
        assert "COLLAR" not in msg.get("reason", "")

    def test_dynamic_collar_rejected_when_last_trade_set(self, engine) -> None:
        eng, pub = engine
        # Wire a tight dynamic collar
        eng._collars["AAPL"] = CollarConfig(
            symbol="AAPL",
            reference_price=10000,
            static_band_pct=0.50,  # wide static so static doesn't fire
            dynamic_band_pct=0.01,  # ±1% dynamic
        )
        # Manually set last_trade_price on the book
        book = eng._book("AAPL")
        book.last_trade_price = 10000

        # Price 102.5 → 10250 ticks; dyn_upper = int(10000*1.01) = 10100
        eng._handle_new_order(_order_dict(price=102.5))
        topic, msg = decode(pub.sent[-1])
        assert msg["accepted"] is False
        assert "DYNAMIC_COLLAR_BREACH" in msg["reason"]


# ──────────────────────────────────────────────────────────────────────────────
# Circuit breaker engine integration
# ──────────────────────────────────────────────────────────────────────────────


class TestCircuitBreakerEngineIntegration:
    def _wire_cb(self, eng: Engine, symbol: str = "AAPL") -> CircuitBreakerState:
        """Wire a circuit breaker with a tight band for easy triggering in tests."""
        cfg = CircuitBreakerConfig(
            symbol=symbol,
            reference_window_ns=300_000_000_000,
            levels=[
                CircuitBreakerLevel(
                    name="L1",
                    price_shift_pct=0.05,
                    halt_duration_ns=60_000_000_000,
                    resumption_mode="AUCTION",
                )
            ],
        )
        state = CircuitBreakerState(symbol=symbol, config=cfg)
        eng._circuit_breakers[symbol] = state
        return state

    def test_check_cb_noop_when_no_config(self, engine) -> None:
        eng, pub = engine
        pub.sent.clear()
        eng._check_circuit_breaker("AAPL", 10000, 1_000_000_000)
        # No halt message should be published
        assert not any(b"circuit_breaker.halt" in f[0] for f in pub.sent if f)

    def test_check_cb_does_not_fire_within_band(self, engine) -> None:
        eng, pub = engine
        self._wire_cb(eng)
        # Record 10 trades at 10000
        for i in range(10):
            eng._check_circuit_breaker("AAPL", 10000, 1_000_000_000 + i)
        assert not eng._halted_symbols.get("AAPL")

    def test_check_cb_fires_on_extreme_price(self, engine) -> None:
        eng, pub = engine
        self._wire_cb(eng)
        # Establish history at 10000
        for i in range(10):
            eng._circuit_breakers["AAPL"].trade_history.append(
                (1_000_000_000 + i, 10000)
            )
        eng._circuit_breakers["AAPL"].reference_price = 10000
        # Trigger price well above 5% band: 10600 > int(10000*1.05) = 10500
        eng._check_circuit_breaker("AAPL", 10600, 1_000_000_010)
        assert eng._halted_symbols.get("AAPL")

    def test_halt_publishes_halt_message(self, engine) -> None:
        eng, pub = engine
        self._wire_cb(eng)
        for i in range(10):
            eng._circuit_breakers["AAPL"].trade_history.append(
                (1_000_000_000 + i, 10000)
            )
        eng._circuit_breakers["AAPL"].reference_price = 10000
        pub.sent.clear()
        eng._check_circuit_breaker("AAPL", 10600, 1_000_000_010)
        topics = [decode(f)[0] for f in pub.sent if len(f) == 2]
        assert any("circuit_breaker.halt.AAPL" in t for t in topics)

    def test_flush_cb_resumes_after_duration(self, engine) -> None:
        eng, pub = engine
        self._wire_cb(eng)
        # Manually activate the breaker
        cb = eng._circuit_breakers["AAPL"]
        level = cb.config.levels[0]
        cb.activate(0, level)
        eng._halted_symbols["AAPL"] = True
        pub.sent.clear()

        # Simulate time past halt duration
        import unittest.mock as mock

        with mock.patch(
            "edumatcher.engine.main.now_ns", return_value=cb.resume_at_ns + 1
        ):
            eng._flush_circuit_breakers()

        assert not eng._halted_symbols["AAPL"]
        topics = [decode(f)[0] for f in pub.sent if len(f) == 2]
        assert any("circuit_breaker.resume.AAPL" in t for t in topics)

    def test_flush_cb_noop_before_duration(self, engine) -> None:
        eng, pub = engine
        self._wire_cb(eng)
        cb = eng._circuit_breakers["AAPL"]
        level = cb.config.levels[0]
        cb.activate(0, level)
        eng._halted_symbols["AAPL"] = True
        pub.sent.clear()

        import unittest.mock as mock

        with mock.patch(
            "edumatcher.engine.main.now_ns",
            return_value=cb.resume_at_ns - 1,
        ):
            eng._flush_circuit_breakers()

        assert eng._halted_symbols["AAPL"]
