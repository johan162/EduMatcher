"""What an agent asks its transport to do.

Prices are integer ticks of the symbol; the transport converts to whatever
its wire wants. ``tag`` is the agent's own correlation key: it rides in the
order's ``client_tag`` and comes back on every lifecycle event, because the
engine (and ALF) assign the order id themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.models.order import TIF, OrderType

#: request_tag prefix on amends (then the order's tag), so a refused amend is
#: told from a refused cancel or order.
AMEND_RTAG_PREFIX = "AMD-"


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
    #: Explicit self-match prevention; None leaves the gateway's default.
    smp: str | None = None


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


@dataclass(frozen=True)
class AmendOrder:
    """Re-price (and/or resize) a resting order the agent tracks."""

    order_id: str  # engine order id
    tag: str
    symbol: str
    price_ticks: int | None = None
    qty: int | None = None


@dataclass(frozen=True)
class ComboLegSpec:
    symbol: str
    side: str
    qty: int
    price_ticks: int
    tick_decimals: int


@dataclass(frozen=True)
class NewCombo:
    """An all-or-none combo across symbols. Fire and forget: the agent does
    not track its legs, but their fills still move its positions."""

    tag: str  # also the combo id
    symbol: str  # the first leg's (the transport's routing key)
    legs: tuple[ComboLegSpec, ...]
    tif: TIF


Action = NewOrder | CancelOrder | NewOco | CancelOco | AmendOrder | NewCombo
