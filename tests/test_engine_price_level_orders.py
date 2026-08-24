"""Tests for order.price_level_orders_request / order.price_level_orders —
the ADMIN-only, all-gateway "who makes up this price level" query added
alongside pm-admin's LEVEL command. See docs-design/EduMatcher-engine-
price-ticks.md for the related investigation and spec/messages/order.yaml
for the wire contract.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.price import to_ticks


@dataclass
class _FakeSock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(monkeypatch, tmp_path) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL", tick_decimals=2),
            "MSFT": SymbolConfig(name="MSFT", tick_decimals=2),
        },
        fix_gateways={
            "ADMIN01": FixGatewayConfig(
                id="ADMIN01",
                description="Admin",
                role=ParticipantRole.ADMIN,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            ),
            "GW01": FixGatewayConfig(
                id="GW01",
                description="Trader 1",
                role=ParticipantRole.TRADER,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            ),
            "GW02": FixGatewayConfig(
                id="GW02",
                description="Trader 2",
                role=ParticipantRole.TRADER,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            ),
        },
        sessions_enabled=False,
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
    for gw in ("ADMIN01", "GW01", "GW02"):
        engine._handle_gateway_connect({"gateway_id": gw})
    pub_sock.sent.clear()
    return engine, pub_sock


def _rest_order(
    engine: Engine,
    *,
    gateway_id: str,
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    price: float,
    qty: int = 100,
) -> None:
    """Post a LIMIT order that rests (opposite side left empty so nothing
    crosses)."""
    order = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway_id,
        tif=TIF.DAY,
        price=to_ticks(price, symbol),
    )
    engine._handle_new_order(order.to_dict())


def _last_price_level_reply(pub_sock: _FakeSock) -> tuple[str, dict]:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if topic.startswith("order.price_level_orders."):
            return topic, payload
    raise AssertionError("no order.price_level_orders reply was published")


@pytest.mark.parametrize("role_gw", ["GW01", "GW02"])
def test_rejected_for_non_admin(monkeypatch, tmp_path, role_gw: str) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)
    _rest_order(engine, gateway_id="GW01", price=100.0)
    pub_sock.sent.clear()

    engine._handle_price_level_orders_request({"gateway_id": role_gw, "symbol": "AAPL"})

    topic, payload = _last_price_level_reply(pub_sock)
    assert topic == f"order.price_level_orders.{role_gw}"
    assert payload["rejected"] is True
    assert "ADMIN" in payload["reason"]
    assert payload["orders"] == []


def test_rejected_for_unknown_symbol(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)

    engine._handle_price_level_orders_request(
        {"gateway_id": "ADMIN01", "symbol": "ZZZZ"}
    )

    topic, payload = _last_price_level_reply(pub_sock)
    assert payload["rejected"] is True
    assert "ZZZZ" in payload["reason"]
    assert payload["orders"] == []


def test_admin_sees_orders_from_every_gateway(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)
    _rest_order(engine, gateway_id="GW01", side=Side.BUY, price=100.00, qty=200)
    _rest_order(engine, gateway_id="GW02", side=Side.BUY, price=100.00, qty=300)
    _rest_order(engine, gateway_id="GW01", side=Side.SELL, price=101.00, qty=150)
    pub_sock.sent.clear()

    engine._handle_price_level_orders_request(
        {"gateway_id": "ADMIN01", "symbol": "AAPL"}
    )

    topic, payload = _last_price_level_reply(pub_sock)
    assert topic == "order.price_level_orders.ADMIN01"
    assert payload["rejected"] is False
    assert payload["symbol"] == "AAPL"
    assert "price" not in payload  # no filter was requested

    orders = payload["orders"]
    assert len(orders) == 3
    gateways = {o["gateway_id"] for o in orders}
    assert gateways == {"GW01", "GW02"}

    # Sorted ascending by price: the two 100.00 orders before the 101.00 one.
    prices = [o["price"] for o in orders]
    assert prices == sorted(prices)
    assert prices[0] == pytest.approx(100.00)
    assert prices[-1] == pytest.approx(101.00)

    # Within the 100.00 level, GW01 (posted first) precedes GW02 by
    # arrival_seq — time priority visible in the ordering.
    level_100 = [o for o in orders if o["price"] == pytest.approx(100.00)]
    assert [o["gateway_id"] for o in level_100] == ["GW01", "GW02"]
    assert level_100[0]["arrival_seq"] < level_100[1]["arrival_seq"]


def test_price_filter_narrows_to_one_level(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)
    _rest_order(engine, gateway_id="GW01", side=Side.BUY, price=100.00, qty=200)
    _rest_order(engine, gateway_id="GW02", side=Side.BUY, price=99.50, qty=300)
    pub_sock.sent.clear()

    engine._handle_price_level_orders_request(
        {"gateway_id": "ADMIN01", "symbol": "AAPL", "price": 100.00}
    )

    topic, payload = _last_price_level_reply(pub_sock)
    assert payload["rejected"] is False
    assert payload["price"] == pytest.approx(100.00)
    orders = payload["orders"]
    assert len(orders) == 1
    assert orders[0]["gateway_id"] == "GW01"
    assert orders[0]["price"] == pytest.approx(100.00)


def test_price_filter_with_no_matching_orders_returns_empty_not_rejected(
    monkeypatch, tmp_path
) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)
    _rest_order(engine, gateway_id="GW01", side=Side.BUY, price=100.00, qty=200)
    pub_sock.sent.clear()

    engine._handle_price_level_orders_request(
        {"gateway_id": "ADMIN01", "symbol": "AAPL", "price": 55.00}
    )

    topic, payload = _last_price_level_reply(pub_sock)
    assert payload["rejected"] is False
    assert payload["orders"] == []


def test_symbol_filter_excludes_other_symbols(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path)
    _rest_order(engine, gateway_id="GW01", symbol="AAPL", price=100.00)
    _rest_order(engine, gateway_id="GW02", symbol="MSFT", price=200.00)
    pub_sock.sent.clear()

    engine._handle_price_level_orders_request(
        {"gateway_id": "ADMIN01", "symbol": "AAPL"}
    )

    topic, payload = _last_price_level_reply(pub_sock)
    orders = payload["orders"]
    assert len(orders) == 1
    assert orders[0]["gateway_id"] == "GW01"
    assert all(o["symbol"] == "AAPL" for o in orders)
