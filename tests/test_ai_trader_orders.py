"""ai_trader.orders: order lifecycle by client tag, positions from fills only."""

from __future__ import annotations

import pytest

from edumatcher.ai_trader.orders import (
    LiveOrder,
    OrderManager,
    OrderState,
    Position,
    Purpose,
)
from edumatcher.models.order import TIF, OrderType


def _order(
    tag: str = "AI001-1",
    side: str = "BUY",
    qty: int = 100,
    price: int | None = 1000,
    symbol: str = "AAPL",
    at: float = 0.0,
    otype: OrderType = OrderType.LIMIT,
    tif: TIF = TIF.DAY,
    purpose: Purpose = Purpose.TRADE,
) -> LiveOrder:
    return LiveOrder(
        tag=tag,
        symbol=symbol,
        side=side,
        order_type=otype,
        tif=tif,
        qty=qty,
        remaining=qty,
        price_ticks=price,
        submitted_at=at,
        purpose=purpose,
    )


def _fill(
    om: OrderManager,
    *,
    tag: str | None,
    oid: str | None,
    qty: int,
    rem: int | None,
    side: str = "BUY",
    price: int = 1000,
    sym: str = "AAPL",
) -> LiveOrder | None:
    return om.on_fill(
        order_id=oid,
        tag=tag,
        symbol=sym,
        side=side,
        fill_qty=qty,
        fill_price_ticks=price,
        remaining=rem,
    )


class TestPosition:
    def test_open_add_reduce_flip(self) -> None:
        p = Position()
        p.apply("BUY", 100, 1000)
        p.apply("BUY", 100, 1100)
        assert (p.qty, p.avg_cost) == (200, 1050)
        p.apply("SELL", 50, 1200)
        assert p.qty == 150 and p.avg_cost == 1050
        assert p.realized == 50 * 150
        p.apply("SELL", 250, 1000)  # close 150, open 100 short at 1000
        assert p.qty == -100 and p.avg_cost == 1000
        assert p.realized == 50 * 150 + 150 * (1000 - 1050)

    def test_short_side_pnl(self) -> None:
        p = Position()
        p.apply("SELL", 10, 2000)
        p.apply("BUY", 10, 1900)
        assert p.qty == 0 and p.avg_cost == 0.0 and p.realized == 1000


class TestLifecycle:
    def test_ack_learns_engine_id(self) -> None:
        om = OrderManager()
        om.track(_order())
        o = om.on_ack("E1", "AI001-1")
        assert o is not None and o.state == OrderState.LIVE and o.order_id == "E1"
        # Later events may carry only the id.
        assert om.on_done("E1", None) is o
        assert om.orders == {}

    def test_partial_then_full_fill(self) -> None:
        om = OrderManager()
        om.track(_order())
        om.on_ack("E1", "AI001-1")
        _fill(om, tag="AI001-1", oid="E1", qty=40, rem=60)
        assert om.orders["AI001-1"].remaining == 60
        _fill(om, tag="AI001-1", oid="E1", qty=60, rem=0)
        assert om.orders == {}
        assert om.position("AAPL").qty == 100
        assert om.fills == 2 and om.filled_qty == 100

    def test_fill_before_ack_is_applied(self) -> None:
        # An aggressive order can fill in the same dispatch as its ack.
        om = OrderManager()
        om.track(_order())
        _fill(om, tag="AI001-1", oid="E1", qty=100, rem=0)
        assert om.orders == {} and om.position("AAPL").qty == 100

    def test_fill_of_unknown_order_still_moves_position(self) -> None:
        om = OrderManager()
        assert _fill(om, tag=None, oid="ZZ", qty=5, rem=0, side="SELL") is None
        assert om.position("AAPL").qty == -5

    def test_zero_fill_is_ignored(self) -> None:
        om = OrderManager()
        _fill(om, tag=None, oid="ZZ", qty=0, rem=0)
        assert om.fills == 0

    def test_reject_removes(self) -> None:
        om = OrderManager()
        om.track(_order())
        assert om.on_reject(None, "AI001-1") is not None
        assert om.orders == {}

    def test_second_ack_kills_after_first(self) -> None:
        # FOK/IOC/MARKET: accepted, then an authoritative accepted=False.
        om = OrderManager()
        om.track(_order(otype=OrderType.FOK))
        om.on_ack("E1", "AI001-1")
        om.on_reject("E1", "AI001-1")
        assert om.orders == {}

    def test_cancel_reject_drops_by_id(self) -> None:
        om = OrderManager()
        om.track(_order())
        om.on_ack("E1", "AI001-1")
        om.mark_cancel(om.orders["AI001-1"], now=1.0)
        assert om.on_cancel_reject("E1") is not None
        assert om.orders == {}

    def test_cancel_reject_for_untracked_id_is_harmless(self) -> None:
        assert OrderManager().on_cancel_reject("nope") is None

    def test_oco_ack_assigns_leg_ids_in_order(self) -> None:
        om = OrderManager()
        for i in (1, 2):
            o = _order(tag=f"AI001-9-{i}", side="SELL", purpose=Purpose.PROTECT)
            o.oco_tag = "AI001-9"
            om.track(o)
        om.on_oco_ack("AI001-9", True, ("L1", "L2"))
        assert om.orders["AI001-9-1"].order_id == "L1"
        assert om.orders["AI001-9-2"].order_id == "L2"
        # The engine tags both legs with the OCO's tag; resolution goes by id.
        _fill(om, tag="AI001-9", oid="L2", qty=100, rem=0, side="SELL")
        assert "AI001-9-2" not in om.orders and "AI001-9-1" in om.orders

    def test_oco_refused_drops_both_legs(self) -> None:
        om = OrderManager()
        for i in (1, 2):
            o = _order(tag=f"T-{i}", purpose=Purpose.PROTECT)
            o.oco_tag = "T"
            om.track(o)
        om.on_oco_ack("T", False, ("", ""))
        assert om.orders == {}

    def test_reset_positions(self) -> None:
        om = OrderManager()
        om.position("X").apply("BUY", 1, 1)
        om.reset_positions({"AAPL": (300, 1234.0)})
        assert "X" not in om.positions
        assert (om.position("AAPL").qty, om.position("AAPL").avg_cost) == (300, 1234.0)


class TestQueries:
    def test_open_qty_counts_trade_orders_only(self) -> None:
        om = OrderManager()
        om.track(_order(tag="a", qty=10))
        om.track(_order(tag="b", qty=20))
        om.track(_order(tag="c", qty=40, side="SELL"))
        om.track(_order(tag="p", qty=99, purpose=Purpose.PROTECT))
        assert om.open_qty("AAPL", "BUY") == 30
        assert om.open_qty("AAPL", "SELL") == 40
        assert [o.tag for o in om.live("AAPL")] == ["a", "b", "c"]
        assert len(om.live("AAPL", None)) == 4

    def _live(self, om: OrderManager, o: LiveOrder) -> LiveOrder:
        om.track(o)
        om.on_ack(f"E-{o.tag}", o.tag)
        return o

    def test_stale_by_age(self) -> None:
        om = OrderManager()
        self._live(om, _order(at=0.0))
        assert om.stale(59.0, max_age=60, drift_ticks=None, touch={}) == []
        assert len(om.stale(60.0, max_age=60, drift_ticks=None, touch={})) == 1

    @pytest.mark.parametrize(
        ("side", "price", "bid", "ask", "stale"),
        [
            ("BUY", 990, 1000, 1020, False),  # 10 behind the bid: exactly at the limit
            ("BUY", 989, 1000, 1020, True),
            ("SELL", 1030, 1000, 1020, False),
            ("SELL", 1031, 1000, 1020, True),
            ("BUY", 999, 1000, 1200, False),  # wide spread: one tick behind is fine
            ("BUY", 500, None, 1020, False),  # no bid to measure against
        ],
    )
    def test_stale_by_drift_from_own_touch(
        self, side: str, price: int, bid: int | None, ask: int | None, stale: bool
    ) -> None:
        om = OrderManager()
        self._live(om, _order(side=side, price=price))
        out = om.stale(1.0, max_age=600, drift_ticks=10, touch={"AAPL": (bid, ask)})
        assert bool(out) is stale

    def test_stale_skips_pending_protect_auction_and_market_orders(self) -> None:
        om = OrderManager()
        om.track(_order(tag="pending", at=0.0))  # never acked
        self._live(om, _order(tag="prot", purpose=Purpose.PROTECT))
        self._live(om, _order(tag="ato", tif=TIF.ATO))
        self._live(om, _order(tag="stop", otype=OrderType.STOP, price=None))
        assert om.stale(1e6, max_age=1, drift_ticks=1, touch={}) == []

    def test_unanswered_cancels(self) -> None:
        om = OrderManager()
        o = self._live(om, _order())
        om.mark_cancel(o, now=10.0)
        assert om.unanswered_cancels(20.0, timeout=15.0) == []
        assert om.unanswered_cancels(25.0, timeout=15.0) == [o]
