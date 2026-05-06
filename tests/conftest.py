from __future__ import annotations

from edumatcher.models.order import Order, OrderType, Side, TIF


def make_order(
    *,
    symbol: str = "AAPL",
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    tif: TIF = TIF.DAY,
    price: float | None = None,
    stop_price: float | None = None,
    visible_qty: int | None = None,
) -> Order:
    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
        visible_qty=visible_qty,
    )
