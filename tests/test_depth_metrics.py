"""Tests for OrderBook.depth_snapshot() — depth metrics within a price tolerance."""

from __future__ import annotations

import pytest

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.price import register_tick_decimals


@pytest.fixture(autouse=True)
def register_ticks() -> None:
    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)


def _limit(symbol: str, side: Side, price: int, qty: int, gw: str = "GW01") -> Order:
    """Create a limit order with price already in ticks."""
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        gateway_id=gw,
        tif=TIF.DAY,
        price=price,
    )
    return o


class TestDepthSnapshotNoTrades:
    def test_returns_empty_dict_when_no_last_trade(self) -> None:
        book = OrderBook("AAPL")
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result == {}


class TestDepthSnapshotWithTrades:
    def _book_with_trade(self, symbol: str = "AAPL") -> OrderBook:
        """Build a book with a known last_trade_price by processing a match."""
        book = OrderBook(symbol)
        now = 1_000_000_000

        # Passive resting bid at 10000
        bid = _limit(symbol, Side.BUY, 10000, 100)
        book.process(bid, match=True, now=now)

        # Aggressive sell crosses the spread
        sell = _limit(symbol, Side.SELL, 9900, 100)
        trades, _ = book.process(sell, match=True, now=now + 1)
        assert trades, "Expected a trade to set last_trade_price"
        return book

    def test_returns_dict_after_trade(self) -> None:
        book = self._book_with_trade()
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result != {}

    def test_required_keys_present(self) -> None:
        book = self._book_with_trade()
        result = book.depth_snapshot(tolerance_ticks=100)
        expected_keys = {
            "symbol",
            "mid_price_ticks",
            "tolerance_ticks",
            "bid_depth",
            "ask_depth",
            "imbalance",
            "cost_to_move",
        }
        assert expected_keys == set(result.keys())

    def test_symbol_in_result(self) -> None:
        book = self._book_with_trade("MSFT")
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["symbol"] == "MSFT"

    def test_mid_price_is_last_trade(self) -> None:
        book = self._book_with_trade()
        mid = book.last_trade_price
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["mid_price_ticks"] == mid

    def test_tolerance_ticks_in_result(self) -> None:
        book = self._book_with_trade()
        result = book.depth_snapshot(tolerance_ticks=50)
        assert result["tolerance_ticks"] == 50

    def test_empty_book_after_full_fill_gives_zero_depths(self) -> None:
        book = self._book_with_trade()
        # After the fill both sides are empty
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["bid_depth"] == 0
        assert result["ask_depth"] == 0

    def test_imbalance_zero_when_no_depth(self) -> None:
        book = self._book_with_trade()
        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["imbalance"] == 0.0

    def test_resting_bids_within_tolerance_counted(self) -> None:
        book = OrderBook("AAPL")
        now = 1_000_000_000

        # First: create a trade to set last_trade_price = 10000
        b = _limit("AAPL", Side.BUY, 10000, 100)
        book.process(b, match=True, now=now)
        s = _limit("AAPL", Side.SELL, 9900, 100)
        book.process(s, match=True, now=now + 1)
        assert book.last_trade_price == 10000

        # Add resting bids within 100 ticks of 10000: [9900, 10000]
        b1 = _limit("AAPL", Side.BUY, 9950, 200)
        b2 = _limit("AAPL", Side.BUY, 10000, 150)
        book.process(b1, match=False, now=now + 2)
        book.process(b2, match=False, now=now + 3)

        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["bid_depth"] == 200 + 150

    def test_bids_outside_tolerance_not_counted(self) -> None:
        book = OrderBook("AAPL")
        now = 1_000_000_000

        b = _limit("AAPL", Side.BUY, 10000, 100)
        book.process(b, match=True, now=now)
        s = _limit("AAPL", Side.SELL, 9900, 100)
        book.process(s, match=True, now=now + 1)

        # Bid outside the [9900, 10000] window when tolerance = 100
        far_bid = _limit("AAPL", Side.BUY, 9899, 500)
        book.process(far_bid, match=False, now=now + 2)

        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["bid_depth"] == 0

    def test_imbalance_positive_when_more_bids(self) -> None:
        book = OrderBook("AAPL")
        now = 1_000_000_000

        # Trade to set last_trade_price
        b = _limit("AAPL", Side.BUY, 10000, 100)
        book.process(b, match=True, now=now)
        s = _limit("AAPL", Side.SELL, 9900, 100)
        book.process(s, match=True, now=now + 1)

        # More bids than asks near mid
        bid = _limit("AAPL", Side.BUY, 9990, 300)
        ask = _limit("AAPL", Side.SELL, 10010, 100)
        book.process(bid, match=False, now=now + 2)
        book.process(ask, match=False, now=now + 3)

        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["imbalance"] > 0

    def test_imbalance_negative_when_more_asks(self) -> None:
        book = OrderBook("AAPL")
        now = 1_000_000_000

        b = _limit("AAPL", Side.BUY, 10000, 100)
        book.process(b, match=True, now=now)
        s = _limit("AAPL", Side.SELL, 9900, 100)
        book.process(s, match=True, now=now + 1)

        # More asks than bids near mid
        bid = _limit("AAPL", Side.BUY, 9990, 100)
        ask = _limit("AAPL", Side.SELL, 10010, 300)
        book.process(bid, match=False, now=now + 2)
        book.process(ask, match=False, now=now + 3)

        result = book.depth_snapshot(tolerance_ticks=100)
        assert result["imbalance"] < 0

    def test_imbalance_range(self) -> None:
        book = OrderBook("AAPL")
        now = 1_000_000_000

        b = _limit("AAPL", Side.BUY, 10000, 100)
        book.process(b, match=True, now=now)
        s = _limit("AAPL", Side.SELL, 9900, 100)
        book.process(s, match=True, now=now + 1)

        bid = _limit("AAPL", Side.BUY, 9990, 100)
        ask = _limit("AAPL", Side.SELL, 10010, 100)
        book.process(bid, match=False, now=now + 2)
        book.process(ask, match=False, now=now + 3)

        result = book.depth_snapshot(tolerance_ticks=100)
        assert -1.0 <= result["imbalance"] <= 1.0
