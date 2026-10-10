"""What an agent asks its transport to do.

Prices are integer ticks of the symbol; the transport converts to whatever
its wire wants. ``tag`` is the agent's own correlation key: it rides in the
order's ``client_tag`` and comes back on every lifecycle event, because the
engine (and ALF) assign the order id themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.models.order import TIF, OrderType


@dataclass(frozen=True)
class NewOrder:
    tag: str
    symbol: str
    side: str  # "BUY" | "SELL"
    order_type: OrderType
    tif: TIF
    qty: int
    price_ticks: int | None = None
    stop_price_ticks: int | None = None
    trail_offset_ticks: int | None = None
    visible_qty: int | None = None


@dataclass(frozen=True)
class CancelOrder:
    order_id: str  # engine order id
    tag: str
    symbol: str


@dataclass(frozen=True)
class OcoLegSpec:
    side: str
    order_type: OrderType
    price_ticks: int | None = None
    stop_price_ticks: int | None = None


@dataclass(frozen=True)
class NewOco:
    tag: str  # also the OCO id
    symbol: str
    qty: int
    tif: TIF
    leg1: OcoLegSpec
    leg2: OcoLegSpec


@dataclass(frozen=True)
class CancelOco:
    tag: str
    symbol: str


Action = NewOrder | CancelOrder | NewOco | CancelOco
