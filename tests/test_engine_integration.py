from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side
from edumatcher.models.participant import ParticipantRole


@dataclass
class _DummySocket:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def engine_with_allowlists(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    pull_sock = _DummySocket(sent=[])
    pub_sock = _DummySocket(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
        },
        fix_gateways={
            "TRADER01": FixGatewayConfig(id="TRADER01", description="First trader"),
            "TRADER02": FixGatewayConfig(id="TRADER02", description="Second trader"),
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

    engine = Engine(config_path=str(cfg_path))
    return engine, pub_sock


def _new_limit_order(symbol: str, gateway_id: str) -> dict:
    order = Order.create(
        symbol=symbol,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id=gateway_id,
        price=100.0,
    )
    return order.to_dict()


def test_gateway_connect_accepts_allowed_id(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_gateway_connect({"gateway_id": "TRADER01"})

    assert pub_sock.sent
    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "system.gateway_auth.TRADER01"
    assert payload["accepted"] is True
    assert payload["description"] == "First trader"


def test_gateway_connect_refuses_unknown_id(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_gateway_connect({"gateway_id": "TRADER99"})

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "system.gateway_auth.TRADER99"
    assert payload["accepted"] is False
    assert payload["reason"] == "Gateway not configured: TRADER99"


def test_new_order_rejected_when_gateway_not_connected(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    payload = _new_limit_order(symbol="AAPL", gateway_id="TRADER01")
    engine._handle_new_order(payload)

    topic, msg = decode(pub_sock.sent[-1])
    assert topic == "order.ack.TRADER01"
    assert msg["accepted"] is False
    assert msg["reason"] == "Gateway not connected: TRADER01"


def test_new_order_rejected_when_symbol_not_allowed(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    pub_sock.sent.clear()

    payload = _new_limit_order(symbol="MSFT", gateway_id="TRADER01")
    engine._handle_new_order(payload)

    topic, msg = decode(pub_sock.sent[-1])
    assert topic == "order.ack.TRADER01"
    assert msg["accepted"] is False
    assert msg["reason"] == "Symbol not configured: MSFT"
    assert "MSFT" not in engine.books


def test_quote_rejected_when_symbol_not_allowed_and_no_book_created(
    engine_with_allowlists,
) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    engine._session_for_gateway("TRADER01").role = ParticipantRole.MARKET_MAKER
    pub_sock.sent.clear()

    engine._handle_quote_new(
        {
            "gateway_id": "TRADER01",
            "symbol": "MSFT",
            "quote_id": "Q-1",
            "bid_price": 100.0,
            "ask_price": 101.0,
            "bid_qty": 10,
            "ask_qty": 10,
            "tif": "DAY",
        }
    )

    topic, msg = decode(pub_sock.sent[-1])
    assert topic == "quote.ack.TRADER01"
    assert msg["accepted"] is False
    assert msg["reason"] == "Symbol not configured: MSFT"
    assert "MSFT" not in engine.books


def test_new_order_accepted_for_connected_allowed_gateway(
    engine_with_allowlists,
) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    pub_sock.sent.clear()

    payload = _new_limit_order(symbol="AAPL", gateway_id="TRADER01")
    engine._handle_new_order(payload)

    # First publish for a non-crossing order is ACK accepted.
    topic, msg = decode(pub_sock.sent[0])
    assert topic == "order.ack.TRADER01"
    assert msg["accepted"] is True


def test_cancel_rejected_for_unauthorized_gateway(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_cancel({"order_id": "deadbeef", "gateway_id": "TRADER99"})

    topic, msg = decode(pub_sock.sent[-1])
    assert topic == "order.ack.TRADER99"
    assert msg["accepted"] is False
    assert msg["reason"] == "Gateway not configured: TRADER99"


def test_orders_request_unauthorized_returns_empty_list(engine_with_allowlists) -> None:
    engine, pub_sock = engine_with_allowlists

    engine._handle_orders_request({"gateway_id": "TRADER99"})

    topic, msg = decode(pub_sock.sent[-1])
    assert topic == "order.orders.TRADER99"
    assert msg["orders"] == []
