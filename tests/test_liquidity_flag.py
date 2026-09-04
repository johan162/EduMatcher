"""``order.fill`` says who was the maker and who was the taker (G9).

Before this, the private fill notification carried no attribution at all --
only the drop-copy feed (E7) knew whether a participant added or removed
liquidity. A client reading its own fills on the ALF or REST order-entry path
could not tell, and invariant I4 ("exactly one maker and one taker") was
unevaluable from the client-facing event.

``liquidity_flag`` is derived exactly the way the drop-copy path already
derives it (M13): the aggressor side of a trade is TAKER, the resting side is
MAKER. These tests match that against real engine matches rather than a
hand-built payload, and cross-check the private fill against drop copy's own
``liquidity_flag`` for the same trade -- the two must never disagree, because
disagreeing is exactly the defect this gap would have hidden (G9's whole
point: don't let the framework prove one E7 against itself).
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    FakeDropCopy,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def _fills(pub_sock: Any, gateway_id: str) -> list[dict[str, Any]]:
    return msgs(pub_sock, f"order.fill.{gateway_id}")


class TestLimitCross:
    """The simplest case: one resting LIMIT, one aggressing LIMIT."""

    def test_maker_and_taker_are_attributed_correctly(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")

        # GW01 rests first -> maker. GW02 crosses it -> taker.
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 50, "GW01", price=100.00)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 50, "GW02", price=100.00)
        )

        maker_fills = _fills(pub, "GW01")
        taker_fills = _fills(pub, "GW02")
        assert len(maker_fills) == 1
        assert len(taker_fills) == 1
        assert maker_fills[0]["liquidity_flag"] == "MAKER"
        assert taker_fills[0]["liquidity_flag"] == "TAKER"

    def test_flag_flips_with_the_resting_side(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """Same scenario, opposite sides resting -- the flag follows who
        arrived first, not BUY/SELL."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")

        # GW01 rests a BUY this time.
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 50, "GW01", price=100.00)
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=100.00)
        )

        assert _fills(pub, "GW01")[0]["liquidity_flag"] == "MAKER"
        assert _fills(pub, "GW02")[0]["liquidity_flag"] == "TAKER"

    def test_matches_drop_copys_own_attribution(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """The private fill and drop copy must never disagree -- that
        disagreement is exactly the defect G9 left possible."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        drop = FakeDropCopy()
        engine._drop_copy = drop
        connect(engine, "GW01", "GW02")

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 50, "GW01", price=100.00)
        )
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 50, "GW02", price=100.00)
        )

        dc_flags = {
            gw: payload["liquidity_flag"] for gw, _etype, payload in drop.events
        }
        assert dc_flags["GW01"] == _fills(pub, "GW01")[0]["liquidity_flag"]
        assert dc_flags["GW02"] == _fills(pub, "GW02")[0]["liquidity_flag"]


class TestMarketSweep:
    """MARKET orders are always the aggressor -- always TAKER."""

    def test_market_taker_and_limit_maker(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02")

        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW01", price=100.00)
        )
        engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 100, "GW02"))

        assert _fills(pub, "GW01")[0]["liquidity_flag"] == "MAKER"
        assert _fills(pub, "GW02")[0]["liquidity_flag"] == "TAKER"

    def test_multi_level_sweep_reports_one_consistent_flag_per_order(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """A MARKET order sweeping two price levels produces two trades but
        must still report a single, self-consistent liquidity_flag per
        counterparty -- proving the coalesced-fill case _order_liquidity_flags
        reasons about (an order cannot be its own aggressor for one trade and
        its own resting side for another)."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01", "GW02", "GW03")

        # Two resting makers at different price levels.
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 50, "GW01", price=100.00)
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=100.05)
        )
        # One MARKET sweeps both levels.
        engine._handle_new_order(order_payload(Side.BUY, OrderType.MARKET, 100, "GW03"))

        assert _fills(pub, "GW01")[0]["liquidity_flag"] == "MAKER"
        assert _fills(pub, "GW02")[0]["liquidity_flag"] == "MAKER"
        # GW03's fill coalesces both levels into one order.fill (H5/H6) --
        # exactly one such message, and it says TAKER.
        gw03_fills = _fills(pub, "GW03")
        assert len(gw03_fills) == 1
        assert gw03_fills[0]["liquidity_flag"] == "TAKER"
        assert gw03_fills[0]["trade_ids"] and len(gw03_fills[0]["trade_ids"]) == 2


class TestNoTradeNoFlag:
    def test_liquidity_flag_is_absent_when_nothing_traded(
        self, monkeypatch: Any, tmp_path: Any
    ) -> None:
        """A seeded/resting order with no fill yet must not claim a flag it
        has no trade to justify -- covered defensively since every current
        call site only reaches make_fill_msg from a real fill, but the field
        is nullable/omit_when_none precisely for this case."""
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")

        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 50, "GW01", price=100.00)
        )

        # Nothing crossed it, so no order.fill was published at all.
        assert _fills(pub, "GW01") == []
