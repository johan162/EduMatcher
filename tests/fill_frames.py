"""``order.fill`` frames for tests of the processes that consume them.

A test fixture, not production API: the engine builds its fills with
``make_order_fill_unchecked`` directly (``Engine._fill_frames``), and this
helper builds them the same way, taking the order fields from an optional
order dict. It replaces ``models.message.make_fill_msg``, which production
never called (Models review 2026-11, C4).
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.generated.order import (
    OrderFillLiquidityFlag,
    OrderFillStatus,
    make_order_fill_unchecked,
)
from edumatcher.models.message import group_ids


def fill_frames(
    gateway_id: str,
    order_id: str,
    fill_qty: int,
    fill_price: float,
    remaining_qty: int,
    status: OrderFillStatus,
    order: dict[str, Any] | None = None,
    trade_ids: list[str] | None = None,
    *,
    liquidity_flag: OrderFillLiquidityFlag | None = None,
) -> list[bytes]:
    detail = order or {}
    return make_order_fill_unchecked(
        gateway_id=gateway_id,
        order_id=order_id,
        fill_qty=fill_qty,
        fill_price=fill_price,
        remaining_qty=remaining_qty,
        status=status,
        symbol=detail.get("symbol"),
        side=detail.get("side"),
        order_type=detail.get("order_type"),
        tif=detail.get("tif"),
        qty=detail.get("quantity"),
        price=detail.get("price"),
        client_tag=detail.get("client_tag"),
        trade_ids=list(trade_ids) if trade_ids else [],
        liquidity_flag=liquidity_flag,
        is_seed=bool(detail.get("is_seed", False)),
        **group_ids(order),
    )
