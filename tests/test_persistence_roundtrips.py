"""
Persistence round-trip tests: save → load → byte-for-byte state equality.

Systemic gap this closes (review §10): persistence was tested save-side
and load-side separately against fixtures, so unit disagreements between
writer and reader (review C1: ticks saved, display-price assumed on load)
were invisible.  Round-trips make writer/reader contract drift impossible
to miss.

The engine-level book-stats round trip lives in
test_engine_review_criticals.py::TestC1BookStatsRoundTrip; these tests are
the module-level guards for the GTC order and combo files, covering every
order type and mid-lifecycle states.  They are expected to PASS today and
must stay green through the C1/C6 fixes and any future schema change.
"""

from __future__ import annotations

from edumatcher.engine.persistence import (
    load_gtc_combos,
    load_gtc_orders,
    save_gtc_combos,
    save_gtc_orders,
)
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

SYMBOL = "AAPL"


def _gtc(order_type: OrderType, **kw) -> Order:
    return Order.create(
        symbol=SYMBOL,
        side=kw.pop("side", Side.BUY),
        order_type=order_type,
        quantity=kw.pop("quantity", 100),
        gateway_id="GW01",
        tif=TIF.GTC,
        **kw,
    )


def _all_gtc_order_variants() -> list[Order]:
    limit = _gtc(OrderType.LIMIT, price=10000)

    partially_filled = _gtc(OrderType.LIMIT, price=10010)
    partially_filled.remaining_qty = 40
    partially_filled.status = OrderStatus.PARTIAL

    iceberg = _gtc(OrderType.ICEBERG, price=10020, visible_qty=10)
    iceberg.remaining_qty = 55  # mid-lifecycle: partially consumed
    iceberg.displayed_qty = 5  # mid-peak
    iceberg.status = OrderStatus.PARTIAL

    stop = _gtc(OrderType.STOP, side=Side.SELL, stop_price=9900)
    stop_limit = _gtc(OrderType.STOP_LIMIT, side=Side.SELL, price=9890, stop_price=9900)
    trailing = _gtc(
        OrderType.TRAILING_STOP, side=Side.SELL, stop_price=9900, trail_offset=100
    )
    tagged = _gtc(OrderType.LIMIT, price=10030)
    tagged.client_tag = "my-tag-42"
    tagged.oco_group_id = "OCO-7"

    return [limit, partially_filled, iceberg, stop, stop_limit, trailing, tagged]


class TestGtcOrderRoundTrip:
    def test_every_order_type_survives_save_load_unchanged(self, tmp_path) -> None:
        orders = _all_gtc_order_variants()
        path = tmp_path / "gtc_orders.json"

        save_gtc_orders(orders, path)
        loaded = load_gtc_orders(path)

        assert len(loaded) == len(
            orders
        ), f"round trip dropped orders: saved {len(orders)}, loaded {len(loaded)}"
        by_id = {o.id: o for o in loaded}
        for original in orders:
            restored = by_id.get(original.id)
            assert restored is not None, f"order {original.id[:8]} lost in round trip"
            assert restored.to_dict() == original.to_dict(), (
                f"field drift in round trip for {original.order_type.value} "
                f"{original.id[:8]}:\n  saved   = {original.to_dict()}\n"
                f"  restored= {restored.to_dict()}"
            )

    def test_terminal_and_day_orders_are_not_persisted(self, tmp_path) -> None:
        day = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            price=10000,
        )
        filled = _gtc(OrderType.LIMIT, price=10000)
        filled.remaining_qty = 0
        filled.status = OrderStatus.FILLED
        cancelled = _gtc(OrderType.LIMIT, price=10000)
        cancelled.status = OrderStatus.CANCELLED

        path = tmp_path / "gtc_orders.json"
        save_gtc_orders([day, filled, cancelled], path)
        assert load_gtc_orders(path) == []


class TestGtcComboRoundTrip:
    def test_combo_with_state_survives_save_load_unchanged(self, tmp_path) -> None:
        combo = ComboOrder.create(
            combo_id="CMB-RT",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.GTC,
            legs=[
                ComboLeg(
                    symbol=SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=10000,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=5000,
                ),
            ],
        )
        combo.child_order_ids = ["child-1", "child-2"]
        combo.leg_statuses = {0: "PARTIAL", 1: "NEW"}
        combo.leg_fill_qty = {0: 30, 1: 0}

        path = tmp_path / "gtc_combos.json"
        save_gtc_combos([combo], path)
        loaded = load_gtc_combos(path)

        assert len(loaded) == 1
        restored = loaded[0]
        assert restored.to_dict() == combo.to_dict(), (
            f"combo round-trip drift:\n  saved   = {combo.to_dict()}\n"
            f"  restored= {restored.to_dict()}"
        )
        # int-keyed dicts must survive the JSON string-key conversion
        assert restored.leg_fill_qty == {0: 30, 1: 0}
        assert restored.leg_statuses == {0: "PARTIAL", 1: "NEW"}
