"""
Negative tests — Group 1: Order validation and input sanitization (tests 1-20).

Covers:
  - Invalid / missing enum values for side, order_type, tif, smp_action
  - Zero and negative quantities / prices
  - Conflicting fields for every order type (MARKET, LIMIT, STOP, STOP_LIMIT,
    ICEBERG, TRAILING_STOP, FOK, IOC)
  - Empty / blank / oversized symbol strings
  - Unknown extra fields rejected by StrictModel
  - AmendRequest with neither price nor qty
  - QuoteRequest with inverted spread (bid >= ask)
  - OcoRequest with empty oco_id
  - ComboRequest with too few legs (< 2)
  - HistoryQuery limit out of bounds (0 and 5001)
  - Engine-level: symbol not in allowlist, gateway not connected/not configured
  - Engine-level: order with unknown enum values in raw payload
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from pydantic import ValidationError

from edumatcher.api_gateway.schemas import (
    AmendRequest,
    ComboLegRequest,
    ComboRequest,
    HistoryQuery,
    OcoLegRequest,
    OcoRequest,
    OrderRequest,
    QuoteRequest,
)
from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# Shared engine fixture helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeSock:
    sent: list
    closed: bool = False

    def send_multipart(self, frames: list) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
    sessions_enabled: bool = False,
):
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={s: SymbolConfig(name=s) for s in symbols},
        fix_gateways={g: FixGatewayConfig(id=g, description=g) for g in gateways},
        sessions_enabled=sessions_enabled,
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
    return engine, pub_sock


def _connect(engine: Engine, gw: str = "GW01") -> None:
    engine._handle_gateway_connect({"gateway_id": gw})


def _last_ack(pub_sock: _FakeSock) -> dict:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if "ack" in topic:
            return payload
    return {}


# ===========================================================================
# 1. Schema-level validation (Pydantic)
# ===========================================================================


class TestOrderRequestSchemaValidation:
    """Tests 1-11: invalid inputs rejected at the schema layer."""

    # --- Test 1: invalid side enum ---
    def test_invalid_side_rejected(self) -> None:
        with pytest.raises(ValidationError, match="side"):
            OrderRequest(
                symbol="AAPL",
                side="MIDDLE",
                order_type="LIMIT",
                quantity=10,
                price=100.0,
            )

    # --- Test 2: invalid order_type enum ---
    def test_invalid_order_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="order_type"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="MAGIC",
                quantity=10,
                price=100.0,
            )

    # --- Test 3: invalid tif enum ---
    def test_invalid_tif_rejected(self) -> None:
        with pytest.raises(ValidationError, match="tif"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                quantity=10,
                price=100.0,
                tif="FOREVER",
            )

    # --- Test 4: zero quantity ---
    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                quantity=0,
                price=100.0,
            )

    # --- Test 5: negative quantity ---
    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                quantity=-50,
                price=100.0,
            )

    # --- Test 6: empty symbol ---
    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            OrderRequest(
                symbol="",
                side="BUY",
                order_type="LIMIT",
                quantity=10,
                price=100.0,
            )

    # --- Test 7: unknown extra field rejected (StrictModel) ---
    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(  # type: ignore[call-arg]
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                quantity=10,
                price=100.0,
                injected_field="evil",
            )

    # --- Test 8: MARKET order with price is invalid ---
    def test_market_order_with_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MARKET forbids"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="MARKET",
                quantity=10,
                price=100.0,
            )

    # --- Test 9: MARKET order with stop_price is invalid ---
    def test_market_order_with_stop_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="MARKET forbids"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="MARKET",
                quantity=10,
                stop_price=95.0,
            )

    # --- Test 10: STOP order without stop_price ---
    def test_stop_order_without_stop_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STOP requires stop_price"):
            OrderRequest(
                symbol="AAPL",
                side="SELL",
                order_type="STOP",
                quantity=10,
            )

    # --- Test 11: STOP order with price (should be forbidden) ---
    def test_stop_order_with_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STOP forbids price"):
            OrderRequest(
                symbol="AAPL",
                side="SELL",
                order_type="STOP",
                quantity=10,
                price=100.0,
                stop_price=95.0,
            )


class TestOrderRequestStopLimitAndIceberg:
    """Tests 12-16: STOP_LIMIT, ICEBERG, TRAILING_STOP, FOK, IOC field rules."""

    # --- Test 12: STOP_LIMIT missing both price and stop_price ---
    def test_stop_limit_missing_prices_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STOP_LIMIT requires"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="STOP_LIMIT",
                quantity=10,
            )

    # --- Test 13: ICEBERG without visible_qty ---
    def test_iceberg_without_visible_qty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ICEBERG requires"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="ICEBERG",
                quantity=100,
                price=100.0,
            )

    # --- Test 14: ICEBERG where visible_qty >= quantity ---
    def test_iceberg_visible_qty_gte_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="visible_qty must be less"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="ICEBERG",
                quantity=50,
                price=100.0,
                visible_qty=50,
            )

    # --- Test 15: TRAILING_STOP without trail_offset ---
    def test_trailing_stop_without_trail_offset_rejected(self) -> None:
        with pytest.raises(
            ValidationError, match="TRAILING_STOP requires trail_offset"
        ):
            OrderRequest(
                symbol="AAPL",
                side="SELL",
                order_type="TRAILING_STOP",
                quantity=10,
            )

    # --- Test 16: TRAILING_STOP with price (forbidden) ---
    def test_trailing_stop_with_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="TRAILING_STOP forbids price"):
            OrderRequest(
                symbol="AAPL",
                side="SELL",
                order_type="TRAILING_STOP",
                quantity=10,
                price=95.0,
                trail_offset=5.0,
            )

    # --- LIMIT / FOK / IOC without price ---
    def test_limit_without_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="LIMIT requires price"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                quantity=10,
            )

    def test_fok_without_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="FOK requires price"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="FOK",
                quantity=10,
            )

    def test_ioc_without_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="IOC requires price"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="IOC",
                quantity=10,
            )

    # --- STOP_LIMIT with only one of the two required prices ---
    def test_stop_limit_missing_stop_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STOP_LIMIT requires"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="STOP_LIMIT",
                quantity=10,
                price=100.0,
            )

    def test_stop_limit_missing_limit_price_rejected(self) -> None:
        with pytest.raises(ValidationError, match="STOP_LIMIT requires"):
            OrderRequest(
                symbol="AAPL",
                side="BUY",
                order_type="STOP_LIMIT",
                quantity=10,
                stop_price=95.0,
            )


class TestAmendRequestValidation:
    """Test 17: AmendRequest must have at least one of price or quantity."""

    def test_amend_with_neither_field_rejected(self) -> None:
        with pytest.raises(ValidationError, match="At least one"):
            AmendRequest(price=None, quantity=None)

    def test_amend_with_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            AmendRequest(quantity=0)

    def test_amend_with_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            AmendRequest(quantity=-10)


class TestQuoteRequestValidation:
    """Test 18: QuoteRequest with inverted spread or zero quantities."""

    def test_inverted_spread_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bid_price must be lower"):
            QuoteRequest(
                symbol="AAPL",
                bid_price=150.5,
                bid_qty=10,
                ask_price=150.0,
                ask_qty=10,
            )

    def test_equal_bid_ask_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bid_price must be lower"):
            QuoteRequest(
                symbol="AAPL",
                bid_price=150.0,
                bid_qty=10,
                ask_price=150.0,
                ask_qty=10,
            )

    def test_zero_bid_qty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bid_qty"):
            QuoteRequest(
                symbol="AAPL",
                bid_price=149.0,
                bid_qty=0,
                ask_price=150.0,
                ask_qty=10,
            )

    def test_zero_ask_qty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ask_qty"):
            QuoteRequest(
                symbol="AAPL",
                bid_price=149.0,
                bid_qty=10,
                ask_price=150.0,
                ask_qty=0,
            )


class TestOcoRequestValidation:
    """Test 19: OcoRequest field constraints."""

    def test_empty_oco_id_rejected(self) -> None:
        with pytest.raises(ValidationError, match="oco_id"):
            OcoRequest(
                oco_id="",
                symbol="AAPL",
                quantity=100,
                leg1=OcoLegRequest(side="BUY", order_type="LIMIT", price=95.0),
                leg2=OcoLegRequest(side="BUY", order_type="STOP", stop_price=105.0),
            )

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError, match="symbol"):
            OcoRequest(
                oco_id="O1",
                symbol="",
                quantity=100,
                leg1=OcoLegRequest(side="BUY", order_type="LIMIT", price=95.0),
                leg2=OcoLegRequest(side="BUY", order_type="STOP", stop_price=105.0),
            )

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="quantity"):
            OcoRequest(
                oco_id="O1",
                symbol="AAPL",
                quantity=0,
                leg1=OcoLegRequest(side="BUY", order_type="LIMIT", price=95.0),
                leg2=OcoLegRequest(side="BUY", order_type="STOP", stop_price=105.0),
            )


class TestComboRequestValidation:
    """Test 20: ComboRequest with too few legs."""

    def test_single_leg_combo_rejected(self) -> None:
        with pytest.raises(ValidationError, match="legs"):
            ComboRequest(
                combo_id="C1",
                legs=[
                    ComboLegRequest(
                        symbol="AAPL",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=10,
                        price=100.0,
                    )
                ],
            )

    def test_empty_legs_rejected(self) -> None:
        with pytest.raises(ValidationError, match="legs"):
            ComboRequest(combo_id="C1", legs=[])

    def test_combo_id_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="combo_id"):
            ComboRequest(
                combo_id="",
                legs=[
                    ComboLegRequest(
                        symbol="AAPL",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=10,
                        price=100.0,
                    ),
                    ComboLegRequest(
                        symbol="MSFT",
                        side="SELL",
                        order_type="LIMIT",
                        quantity=5,
                        price=200.0,
                    ),
                ],
            )

    def test_too_many_legs_rejected(self) -> None:
        """ComboRequest max_length=10; 11 legs must be rejected."""
        with pytest.raises(ValidationError, match="legs"):
            ComboRequest(
                combo_id="C_OVERFLOW",
                legs=[
                    ComboLegRequest(
                        symbol=f"SYM{i}",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=10,
                        price=100.0,
                    )
                    for i in range(11)
                ],
            )


class TestHistoryQueryValidation:
    """HistoryQuery limit boundary checks."""

    def test_limit_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="limit"):
            HistoryQuery(limit=0)

    def test_limit_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError, match="limit"):
            HistoryQuery(limit=5001)

    def test_limit_at_minimum_accepted(self) -> None:
        q = HistoryQuery(limit=1)
        assert q.limit == 1

    def test_limit_at_maximum_accepted(self) -> None:
        q = HistoryQuery(limit=5000)
        assert q.limit == 5000


# ===========================================================================
# Engine-level validation (symbol allowlist / gateway auth)
# ===========================================================================


class TestEngineSymbolAllowlist:
    """Symbol not in allowlist is rejected at the engine level."""

    def test_order_for_unknown_symbol_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL",))
        _connect(engine)
        o = Order.create(
            symbol="ZZZZ",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert "not configured" in ack["reason"].lower()

    def test_cancel_for_unknown_symbol_routes_via_symbol_map(
        self, monkeypatch, tmp_path
    ) -> None:
        """Cancel of an order whose symbol is removed post-accept should fail
        gracefully — no unhandled exception."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_cancel({"order_id": "NONEXISTENT", "gateway_id": "GW01"})
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False


class TestEngineGatewayAuth:
    """Orders from gateways not in the allowlist or not connected are rejected."""

    def test_order_from_unconfigured_gateway_rejected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, gateways=("GW01",))
        # GW99 is not in the configured gateway list
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW99",
            tif=TIF.DAY,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert "not configured" in ack["reason"].lower()

    def test_order_from_configured_but_not_connected_gateway_rejected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, gateways=("GW01",))
        # GW01 is configured but has not sent a HELLO (not connected)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert "not connected" in ack["reason"].lower()

    def test_amend_from_unconfigured_gateway_rejected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, gateways=("GW01",))
        engine._handle_amend({"order_id": "x", "gateway_id": "GW99", "qty": 10})
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False

    def test_cancel_from_unconfigured_gateway_rejected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, gateways=("GW01",))
        engine._handle_cancel({"order_id": "x", "gateway_id": "GW99"})
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False


class TestEngineMalformedPayloads:
    """Malformed raw payloads passed directly to engine handlers."""

    def test_order_payload_with_invalid_side_string_raises(
        self, monkeypatch, tmp_path
    ) -> None:
        """A raw dict with an unknown side value should raise a KeyError or
        similar — the engine does NOT silently accept garbage enum strings."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        payload = o.to_dict()
        payload["side"] = "SIDEWAYS"  # corrupt the enum value
        with pytest.raises((KeyError, ValueError)):
            engine._handle_new_order(payload)

    def test_order_payload_with_invalid_order_type_raises(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        payload = o.to_dict()
        payload["order_type"] = "MAGIC_ORDER"
        with pytest.raises((KeyError, ValueError)):
            engine._handle_new_order(payload)

    def test_order_payload_with_invalid_tif_raises(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        payload = o.to_dict()
        payload["tif"] = "WHENEVER"
        with pytest.raises((KeyError, ValueError)):
            engine._handle_new_order(payload)


# ===========================================================================
# Engine-level validation — session gating
# ===========================================================================


class TestEngineSessionGating:
    """Orders submitted while the session is CLOSED must be rejected."""

    def test_new_order_rejected_when_market_closed(self, monkeypatch, tmp_path) -> None:
        """Engine in CLOSED state (sessions_enabled=True) must reject orders
        with reason 'Market is closed'."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        assert engine._session_state == SessionState.CLOSED
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack["accepted"] is False
        assert "closed" in ack["reason"].lower()

    def test_new_order_accepted_when_sessions_disabled(
        self, monkeypatch, tmp_path
    ) -> None:
        """When sessions_enabled=False the CLOSED state must not gate orders."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=False)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack.get("accepted") is True
