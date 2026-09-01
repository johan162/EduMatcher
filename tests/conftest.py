from __future__ import annotations

from collections.abc import Generator

import pytest

from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq


@pytest.fixture(autouse=True)
def _configure_trade_id_run() -> Generator[None, None, None]:
    reset_trade_ids_for_tests()
    set_run_seq(0)
    yield
    reset_trade_ids_for_tests()


def make_order(
    *,
    symbol: str = "AAPL",
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    tif: TIF = TIF.DAY,
    price: int | None = None,
    stop_price: int | None = None,
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
