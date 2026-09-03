"""A price off the symbol's tick grid is refused, not silently rounded.

``to_ticks`` rounds — right for an engine-side value already known to be
well-formed, wrong for a client submission, which used to rest at a price the
client never sent and was never told about. ``to_ticks_exact`` is the checking
variant the order-entry edges use.

The grid check has to tolerate float arithmetic. ``100.00 - 3 * 0.01`` is
99.97000000000001 in binary floating point, and that is the same price a human
types as "99.97"; an exact modulo test would reject nearly every computed
price in the system. These tests pin both halves of that: the arithmetic
artefacts pass, and a genuinely off-grid price does not.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from edumatcher.models.price import (
    TickViolation,
    clear_tick_registry,
    has_tick_decimals,
    register_tick_decimals,
    to_ticks_exact,
    to_ticks_exact_or_none,
)


@pytest.fixture(autouse=True)
def _registry() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("TST0", 0)
    register_tick_decimals("TST2", 2)
    register_tick_decimals("TST4", 4)
    yield
    clear_tick_registry()


class TestOnGrid:
    @pytest.mark.parametrize(
        "price,symbol,ticks",
        [
            (150.0, "TST2", 15000),
            (0.01, "TST2", 1),
            (150.0, "TST0", 150),
            (0.0001, "TST4", 1),
            (1.2345, "TST4", 12345),
        ],
    )
    def test_exact_prices_convert(self, price: float, symbol: str, ticks: int) -> None:
        assert to_ticks_exact(price, symbol) == ticks

    @pytest.mark.parametrize(
        "price",
        [
            100.00 - 3 * 0.01,  # 99.97000000000001
            0.1 + 0.2,  # 0.30000000000000004
            1.1 * 3,  # 3.3000000000000003
        ],
    )
    def test_float_arithmetic_artefacts_are_accepted(self, price: float) -> None:
        """A bot computes its price; the result is a tick value with an ulp of
        noise on it. Rejecting these would make the check unusable."""
        assert to_ticks_exact(price, "TST2") == round(price * 100)

    def test_optional_variant_passes_none_through(self) -> None:
        assert to_ticks_exact_or_none(None, "TST2") is None
        assert to_ticks_exact_or_none(150.0, "TST2") == 15000


class TestOffGrid:
    @pytest.mark.parametrize(
        "price,symbol",
        [
            (100.005, "TST2"),
            (100.001, "TST2"),
            (150.5, "TST0"),
            (1.00005, "TST4"),
        ],
    )
    def test_sub_tick_prices_are_refused(self, price: float, symbol: str) -> None:
        with pytest.raises(TickViolation):
            to_ticks_exact(price, symbol)

    def test_the_error_names_the_symbol_and_its_tick_size(self) -> None:
        """The edges reuse this message verbatim, so it has to be enough for a
        client to fix its request without reading the reference data."""
        with pytest.raises(TickViolation) as exc_info:
            to_ticks_exact(100.005, "TST2")
        message = str(exc_info.value)
        assert "TST2" in message
        assert "0.01" in message
        assert exc_info.value.tick_decimals == 2

    def test_the_same_price_is_fine_on_a_finer_grid(self) -> None:
        """The violation is a property of the instrument, not of the number."""
        with pytest.raises(TickViolation):
            to_ticks_exact(100.005, "TST2")
        assert to_ticks_exact(100.005, "TST4") == 1000050


class TestReadinessIsASeparateQuestion:
    """``to_ticks_exact`` checks the grid; readiness is checked at the edge."""

    def test_unregistered_symbol_uses_the_default_grid(self) -> None:
        assert not has_tick_decimals("NEWSYM")
        assert to_ticks_exact(150.0, "NEWSYM") == 15000

    def test_has_tick_decimals_distinguishes_default_from_registered(self) -> None:
        assert has_tick_decimals("TST4")
        assert not has_tick_decimals("NOPE")


class TestAlfEdge:
    """ALF answers with the legacy CODE plus the machine-readable REJECT_CODE."""

    def test_off_grid_price_is_a_tick_violation(self) -> None:
        from edumatcher.alf_gwy.gateway import AlfGateway
        from edumatcher.alf_gwy.protocol import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            AlfGateway._ticks(100.005, "TST2", "PRICE")
        error = exc_info.value
        assert error.reject_code == "TICK_VIOLATION"
        # The ERR|CODE= vocabulary is unchanged; only REJECT_CODE is new.
        assert error.code == "INVALID_VALUE"
        assert "PRICE" in error.detail

    def test_on_grid_price_converts(self) -> None:
        from edumatcher.alf_gwy.gateway import AlfGateway

        assert AlfGateway._ticks(1.2345, "TST4", "PRICE") == 12345


class TestRestEdge:
    def test_off_grid_price_raises_from_build_order(self) -> None:
        from edumatcher.api_gateway.schemas import OrderRequest
        from edumatcher.api_gateway.translate import build_order
        from edumatcher.models.order import OrderType, Side

        request = OrderRequest(
            symbol="TST2",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.005,
        )
        with pytest.raises(TickViolation):
            build_order(request, "GW01")

    def test_readiness_gate_refuses_an_unloaded_symbol(self) -> None:
        """The gate REST never had. ALF has always refused this window with
        SYMBOLS_NOT_READY; converting before the snapshot arrives would apply
        the two-decimal default to an instrument that may not have two."""
        from fastapi import HTTPException

        from edumatcher.api_gateway.routers.orders import _check_symbol_ready

        _check_symbol_ready("TST4")  # registered: no raise
        with pytest.raises(HTTPException) as exc_info:
            _check_symbol_ready("NOTLOADED")
        assert exc_info.value.status_code == 503
        detail: Any = exc_info.value.detail
        assert detail["error"]["reject_code"] == "SYMBOL_NOT_READY"


class TestBalfEdge:
    def test_off_grid_price_is_rejected_as_an_invalid_field(self) -> None:
        """BALF carries prices at 1e8 fixed point, so a client can express far
        finer values than any tick grid."""
        from edumatcher.balf_gwy.protocol import RC_INVALID_FIELD, BalfValidationError
        from edumatcher.balf_gwy.translate import build_engine_new_order

        parsed = {
            "symbol": "TST2",
            "side": 1,
            "order_type": 2,
            "tif": 1,
            "smp": 0,
            "quantity": 10,
            "price": 10000500000,  # 100.005 at scale 1e8
            "stop_price": 0,
            "trail_offset": 0,
            "visible_qty": 0,
        }
        with pytest.raises(BalfValidationError) as exc_info:
            build_engine_new_order(parsed, "GW01", "ORD1")
        assert exc_info.value.reject_code == RC_INVALID_FIELD
