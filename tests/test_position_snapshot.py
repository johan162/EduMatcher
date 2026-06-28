"""
Tests for §22.5 — system.position_request / system.position_snapshot.

Covers:
  - _update_position: long/short/cross-zero/flat semantics
  - _handle_position_request: auth check, empty snapshot, filled snapshot
  - End-to-end: fill in _handle_new_order accumulates position correctly
  - topic dispatch: system.position_request is routed to the handler
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import (
    decode,
    make_position_request_msg,
    make_position_snapshot_msg,
)
from edumatcher.models.order import Order, OrderType, Side, TIF

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


@dataclass
class _Sock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
) -> tuple[Engine, _Sock]:
    pull_sock = _Sock(sent=[])
    pub_sock = _Sock(sent=[])

    cfg = EngineConfig(
        symbols={sym: SymbolConfig(name=sym) for sym in symbols},
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=f"{gw} trader") for gw in gateways
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


def _connect(engine: Engine, gw: str = "GW01") -> None:
    engine._handle_gateway_connect({"gateway_id": gw})


def _order(
    symbol: str = "AAPL",
    side: Side = Side.BUY,
    qty: int = 100,
    price: float = 100.0,
    gateway_id: str = "GW01",
) -> dict:
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gateway_id,
        tif=TIF.DAY,
        price=price,
    )
    return o.to_dict()


def _last_msg_topic_payload(pub_sock: _Sock) -> tuple[str, dict]:
    frames = pub_sock.sent[-1]
    return decode(frames)


# ---------------------------------------------------------------------------
# Unit tests for _update_position
# ---------------------------------------------------------------------------


class TestUpdatePosition:
    """Direct unit tests for the Engine._update_position helper."""

    def test_open_long(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 100
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(10.0)

    def test_add_to_long(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        engine._update_position("GW01", "AAPL", "BUY", 100, 11.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 200
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(10.5)

    def test_reduce_long_cost_unchanged(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        engine._update_position("GW01", "AAPL", "SELL", 40, 12.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 60
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(10.0)

    def test_close_long_flat(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        engine._update_position("GW01", "AAPL", "SELL", 100, 12.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 0
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(0.0)

    def test_cross_long_to_short(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        # Sell 150 → net -50 (short); avg_cost resets to fill price
        engine._update_position("GW01", "AAPL", "SELL", 150, 9.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == -50
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(9.0)

    def test_open_short(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "SELL", 100, 10.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == -100
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(10.0)

    def test_add_to_short(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "SELL", 100, 10.0)
        engine._update_position("GW01", "AAPL", "SELL", 100, 9.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == -200
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(9.5)

    def test_reduce_short_cost_unchanged(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "SELL", 100, 10.0)
        engine._update_position("GW01", "AAPL", "BUY", 40, 8.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == -60
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(10.0)

    def test_close_short_flat(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "SELL", 100, 10.0)
        engine._update_position("GW01", "AAPL", "BUY", 100, 8.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 0
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(0.0)

    def test_cross_short_to_long(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("GW01", "AAPL", "SELL", 100, 10.0)
        # Buy 150 → net +50 (long); avg_cost resets to fill price
        engine._update_position("GW01", "AAPL", "BUY", 150, 8.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 50
        assert engine._gateway_avg_cost["GW01"]["AAPL"] == pytest.approx(8.0)

    def test_case_insensitive_gateway_id(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        engine._update_position("gw01", "AAPL", "BUY", 100, 10.0)
        # Should be stored under uppercase key
        assert engine._gateway_positions["GW01"]["AAPL"] == 100

    def test_multiple_symbols_independent(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        engine._update_position("GW01", "MSFT", "SELL", 50, 20.0)
        assert engine._gateway_positions["GW01"]["AAPL"] == 100
        assert engine._gateway_positions["GW01"]["MSFT"] == -50


# ---------------------------------------------------------------------------
# Handler tests for _handle_position_request
# ---------------------------------------------------------------------------


class TestHandlePositionRequest:
    def test_empty_when_flat(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_position_request({"gateway_id": "GW01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.GW01"
        assert payload["positions"] == []

    def test_returns_long_position(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.5)
        engine._handle_position_request({"gateway_id": "GW01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.GW01"
        pos = {p["symbol"]: p for p in payload["positions"]}
        assert pos["AAPL"]["net_qty"] == 100
        assert pos["AAPL"]["avg_cost"] == pytest.approx(10.5)

    def test_excludes_flat_symbols(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        engine._update_position("GW01", "AAPL", "BUY", 100, 10.0)
        engine._update_position("GW01", "AAPL", "SELL", 100, 11.0)  # flat
        engine._update_position("GW01", "MSFT", "SELL", 50, 20.0)
        engine._handle_position_request({"gateway_id": "GW01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        symbols = [p["symbol"] for p in payload["positions"]]
        assert "AAPL" not in symbols
        assert "MSFT" in symbols

    def test_unauthorized_gateway_returns_empty(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        # GW01 is configured but NOT connected → unauthorized
        engine._handle_position_request({"gateway_id": "GW01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.GW01"
        assert payload["positions"] == []

    def test_unknown_gateway_returns_empty(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._handle_position_request({"gateway_id": "UNKNOWN"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.UNKNOWN"
        assert payload["positions"] == []

    def test_lowercase_gateway_id_normalised(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._update_position("GW01", "AAPL", "BUY", 50, 10.0)
        engine._handle_position_request({"gateway_id": "gw01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.GW01"
        assert payload["positions"][0]["net_qty"] == 50


# ---------------------------------------------------------------------------
# End-to-end: fill via _handle_new_order accumulates position
# ---------------------------------------------------------------------------


class TestPositionAccumulationViaFill:
    """Verify that real trades through the engine update the position ledger."""

    def test_matching_orders_update_positions(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, gateways=("GW01", "GW02")
        )
        _connect(engine, "GW01")
        _connect(engine, "GW02")

        # GW01 posts a resting BUY
        engine._handle_new_order(_order("AAPL", Side.BUY, 100, 10.0, "GW01"))
        # GW02 crosses with a SELL — triggers a fill
        engine._handle_new_order(_order("AAPL", Side.SELL, 100, 10.0, "GW02"))

        # Both gateways should now have non-zero positions
        gw01_pos = engine._gateway_positions.get("GW01", {}).get("AAPL", 0)
        gw02_pos = engine._gateway_positions.get("GW02", {}).get("AAPL", 0)
        assert gw01_pos == 100, f"GW01 expected long 100, got {gw01_pos}"
        assert gw02_pos == -100, f"GW02 expected short 100, got {gw02_pos}"

    def test_position_snapshot_reflects_fill(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, gateways=("GW01", "GW02")
        )
        _connect(engine, "GW01")
        _connect(engine, "GW02")

        engine._handle_new_order(_order("AAPL", Side.BUY, 50, 10.0, "GW01"))
        engine._handle_new_order(_order("AAPL", Side.SELL, 50, 10.0, "GW02"))

        engine._handle_position_request({"gateway_id": "GW01"})
        topic, payload = _last_msg_topic_payload(pub_sock)
        assert topic == "system.position_snapshot.GW01"
        pos = {p["symbol"]: p for p in payload["positions"]}
        assert pos["AAPL"]["net_qty"] == 50
        assert pos["AAPL"]["avg_cost"] == pytest.approx(10.0)

    def test_partial_fill_accumulates_incrementally(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(
            monkeypatch, tmp_path, gateways=("GW01", "GW02")
        )
        _connect(engine, "GW01")
        _connect(engine, "GW02")

        # Resting bid for 200
        engine._handle_new_order(_order("AAPL", Side.BUY, 200, 10.0, "GW01"))
        # Two separate sells of 100 each — fills GW01's order in two parts
        engine._handle_new_order(_order("AAPL", Side.SELL, 100, 10.0, "GW02"))
        engine._handle_new_order(_order("AAPL", Side.SELL, 100, 10.0, "GW02"))

        gw01_pos = engine._gateway_positions.get("GW01", {}).get("AAPL", 0)
        assert gw01_pos == 200


# ---------------------------------------------------------------------------
# Message helper round-trip
# ---------------------------------------------------------------------------


class TestMessageHelpers:
    def test_position_request_round_trip(self) -> None:
        frames = make_position_request_msg("GW01")
        topic, payload = decode(frames)
        assert topic == "system.position_request"
        assert payload["gateway_id"] == "GW01"

    def test_position_snapshot_round_trip(self) -> None:
        entries = [{"symbol": "AAPL", "net_qty": -50, "avg_cost": 9.75}]
        frames = make_position_snapshot_msg("GW01", entries)
        topic, payload = decode(frames)
        assert topic == "system.position_snapshot.GW01"
        assert payload["positions"] == entries

    def test_position_snapshot_empty(self) -> None:
        frames = make_position_snapshot_msg("GW01", [])
        topic, payload = decode(frames)
        assert topic == "system.position_snapshot.GW01"
        assert payload["positions"] == []
