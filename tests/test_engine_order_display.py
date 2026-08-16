"""Tests for engine.main.order_to_display_dict() with focus on uncovered lines.

This file targets the specific uncovered lines in order_to_display_dict:
- Lines 250-253: price None branches
- Line 256: stop_price None branch
- Line 259-260: trail_offset None branches
"""

import pytest
from edumatcher.engine.main import order_to_display_dict
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF


@pytest.fixture
def base_order():
    """Create a minimal order with all required fields."""
    return Order(
        id="ORD001",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        tif=TIF.DAY,
        quantity=100,
        remaining_qty=100,
        gateway_id="GW001",
        timestamp=1_000_000_000,
        status=OrderStatus.NEW,
    )


class TestOrderToDisplayDictPriceCoverage:
    """Tests targeting the uncovered None branches in order_to_display_dict."""

    def test_with_all_prices_set(self, base_order):
        """Test when all price fields have values (baseline)."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
            price=12550,  # display: 125.50
            stop_price=12450,  # display: 124.50
            trail_offset=50,  # display: 0.50
        )
        result = order_to_display_dict(order)

        assert "price" in result
        assert result["price"] is not None
        assert "stop_price" in result
        assert result["stop_price"] is not None
        assert "trail_offset" in result
        assert result["trail_offset"] is not None
        assert "timestamp" in result
        assert result["timestamp"] == 1.0  # ns to seconds

    def test_with_price_none(self, base_order):
        """Test when price is None (covers line 250-252)."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
            price=None,
            stop_price=12450,
            trail_offset=50,
        )
        result = order_to_display_dict(order)

        assert result["price"] is None
        assert result["stop_price"] is not None
        assert result["trail_offset"] is not None

    def test_with_stop_price_none(self, base_order):
        """Test when stop_price is None (covers line 256)."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
            price=12550,
            stop_price=None,
            trail_offset=50,
        )
        result = order_to_display_dict(order)

        assert result["price"] is not None
        assert result["stop_price"] is None
        assert result["trail_offset"] is not None

    def test_with_trail_offset_none(self, base_order):
        """Test when trail_offset is None (covers line 259-260)."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
            price=12550,
            stop_price=12450,
            trail_offset=None,
        )
        result = order_to_display_dict(order)

        assert result["price"] is not None
        assert result["stop_price"] is not None
        assert result["trail_offset"] is None

    def test_with_all_prices_none(self, base_order):
        """Test when all price fields are None."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
            price=None,
            stop_price=None,
            trail_offset=None,
        )
        result = order_to_display_dict(order)

        assert result["price"] is None
        assert result["stop_price"] is None
        assert result["trail_offset"] is None

    def test_timestamp_conversion(self, base_order):
        """Test timestamp conversion from nanoseconds to seconds."""
        order = Order(
            id=base_order.id,
            symbol=base_order.symbol,
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=base_order.quantity,
            remaining_qty=base_order.remaining_qty,
            gateway_id=base_order.gateway_id,
            timestamp=1_234_567_890,  # 1.23456789 seconds in ns
            status=OrderStatus.NEW,
        )
        result = order_to_display_dict(order)

        assert result["timestamp"] == pytest.approx(1.23456789, rel=1e-6)

    def test_maintains_other_order_fields(self, base_order):
        """Test that other order fields are preserved in dict."""
        order = Order(
            id="TEST-123",
            symbol="MSFT",
            side=base_order.side,
            order_type=base_order.order_type,
            tif=base_order.tif,
            quantity=500,
            remaining_qty=250,
            gateway_id="GW-ALF",
            timestamp=base_order.timestamp,
            status=OrderStatus.NEW,
        )
        result = order_to_display_dict(order)

        assert result["id"] == "TEST-123"
        assert result["symbol"] == "MSFT"
        assert result["quantity"] == 500
        assert result["remaining_qty"] == 250
        assert result["gateway_id"] == "GW-ALF"
