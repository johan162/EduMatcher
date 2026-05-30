from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole


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
    *,
    role: ParticipantRole,
    enforce_mm_obligation: bool = False,
    mm_max_spread_ticks: int = 10,
    mm_min_qty: int = 100,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={"AAPL": SymbolConfig(name="AAPL")},
        fix_gateways={
            "GW01": FixGatewayConfig(
                id="GW01",
                description="MM",
                role=role,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                enforce_mm_obligation=enforce_mm_obligation,
                mm_max_spread_ticks=mm_max_spread_ticks,
                mm_min_qty=mm_min_qty,
            )
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
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    pub_sock.sent.clear()
    return engine, pub_sock


def _topics(pub_sock: _FakeSock) -> list[str]:
    return [decode(frames)[0] for frames in pub_sock.sent]


def test_quote_rejected_for_non_market_maker(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path, role=ParticipantRole.TRADER)
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "bid_price": 100.0,
            "bid_qty": 10,
            "ask_price": 101.0,
            "ask_qty": 10,
        }
    )

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "quote.ack.GW01"
    assert payload["accepted"] is False


def test_quote_accept_and_cancel(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": 100.0,
            "bid_qty": 10,
            "ask_price": 101.0,
            "ask_qty": 12,
        }
    )

    assert "quote.ack.GW01" in _topics(pub_sock)
    assert engine._quote_index.get("GW01", "AAPL") is not None

    pub_sock.sent.clear()
    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": "AAPL"})
    assert engine._quote_index.get("GW01", "AAPL") is None
    assert "quote.status.GW01" in _topics(pub_sock)


def test_kill_switch_cancels_quote_and_orders(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )

    order = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=20,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=9900,
    )
    engine._handle_new_order(order.to_dict())

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q2",
            "bid_price": 99.0,
            "bid_qty": 5,
            "ask_price": 102.0,
            "ask_qty": 5,
        }
    )

    pub_sock.sent.clear()
    engine._handle_kill_switch({"gateway_id": "GW01"})

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.kill_switch_ack.GW01"
    assert payload["accepted"] is True
    assert payload["cancelled_orders"] >= 1
    assert payload["cancelled_quotes"] >= 1


def test_disconnect_cancels_quotes_only(monkeypatch, tmp_path) -> None:
    engine, _ = _make_engine(monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER)

    order = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=20,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=9800,
    )
    engine._handle_new_order(order.to_dict())
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q3",
            "bid_price": 97.0,
            "bid_qty": 5,
            "ask_price": 103.0,
            "ask_qty": 5,
        }
    )

    engine._handle_gateway_disconnect({"gateway_id": "GW01"})

    assert engine._quote_index.get("GW01", "AAPL") is None
    book = engine._book("AAPL")
    resting_ids = {o.id for o in book.resting_orders() if o.gateway_id == "GW01"}
    assert order.id in resting_ids


def test_quote_obligation_enforced_when_enabled(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        enforce_mm_obligation=True,
        mm_max_spread_ticks=5,
        mm_min_qty=10,
    )

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-OBL-1",
            "bid_price": 100.0,
            "bid_qty": 10,
            "ask_price": 100.10,
            "ask_qty": 10,
        }
    )
    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "quote.ack.GW01"
    assert payload["accepted"] is False
    assert "Spread" in payload["reason"]


def test_quote_obligation_not_enforced_when_disabled(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        enforce_mm_obligation=False,
        mm_max_spread_ticks=5,
        mm_min_qty=10,
    )

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-OBL-2",
            "bid_price": 100.0,
            "bid_qty": 10,
            "ask_price": 100.10,
            "ask_qty": 10,
        }
    )
    topics = _topics(pub_sock)
    assert "quote.ack.GW01" in topics
    ack_payload = decode(
        [f for f in pub_sock.sent if decode(f)[0] == "quote.ack.GW01"][-1]
    )[1]
    assert ack_payload["accepted"] is True


@pytest.mark.parametrize(
    "role",
    [ParticipantRole.TRADER, ParticipantRole.MARKET_MAKER],
)
def test_global_circuit_breaker_halt_all_rejected_for_non_admin(
    monkeypatch, tmp_path, role: ParticipantRole
) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path, role=role)

    engine._handle_circuit_breaker_halt_all({"gateway_id": "GW01"})

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_halt_all_ack.GW01"
    assert payload["accepted"] is False
    assert "ADMIN" in payload["reason"]


def test_global_circuit_breaker_halt_all_accepts_admin(monkeypatch, tmp_path) -> None:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "GW01": FixGatewayConfig(
                id="GW01",
                description="Admin",
                role=ParticipantRole.ADMIN,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            )
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
    engine._handle_gateway_connect({"gateway_id": "GW01"})

    pub_sock.sent.clear()
    engine._handle_circuit_breaker_halt_all({"gateway_id": "GW01"})

    assert engine._halted_symbols.get("AAPL") is True
    assert engine._halted_symbols.get("MSFT") is True

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_halt_all_ack.GW01"
    assert payload["accepted"] is True
    assert payload["halted_symbols"] == 2
