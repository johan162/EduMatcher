"""Pydantic request and response schemas for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from edumatcher.models.combo import ComboType
from edumatcher.models.order import OrderType, Side, SmpAction, TIF
from edumatcher.models.session import SessionState


class StrictModel(BaseModel):
    """Base model that rejects unknown JSON fields."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ErrorDetail(StrictModel):
    code: str
    message: str
    field: str | None = None


class ErrorResponse(StrictModel):
    error: ErrorDetail


class OrderRequest(StrictModel):
    symbol: str = Field(min_length=1)
    side: Side
    order_type: OrderType
    quantity: int = Field(gt=0)
    tif: TIF = TIF.DAY
    price: float | None = None
    stop_price: float | None = None
    visible_qty: int | None = Field(default=None, gt=0)
    trail_offset: float | None = None
    # None means the client omitted smp_action -- the engine applies this
    # gateway's configured smp_action default in that case, distinct from an
    # explicit "smp_action": "NONE" (deliberately allow self-trades). See
    # SmpAction's docstring in models/order.py.
    smp_action: SmpAction | None = None
    client_order_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_by_order_type(self) -> "OrderRequest":
        order_type = OrderType(self.order_type)
        if order_type == OrderType.MARKET and (
            self.price is not None or self.stop_price is not None
        ):
            raise ValueError("MARKET forbids price and stop_price")
        if order_type in {OrderType.LIMIT, OrderType.FOK, OrderType.IOC}:
            if self.price is None:
                raise ValueError(f"{order_type.value} requires price")
            if self.stop_price is not None:
                raise ValueError(f"{order_type.value} forbids stop_price")
        if order_type == OrderType.STOP:
            if self.stop_price is None:
                raise ValueError("STOP requires stop_price")
            if self.price is not None:
                raise ValueError("STOP forbids price")
        if order_type == OrderType.STOP_LIMIT and (
            self.price is None or self.stop_price is None
        ):
            raise ValueError("STOP_LIMIT requires price and stop_price")
        if order_type == OrderType.ICEBERG:
            if self.price is None or self.visible_qty is None:
                raise ValueError("ICEBERG requires price and visible_qty")
            if self.visible_qty >= self.quantity:
                raise ValueError("ICEBERG visible_qty must be less than quantity")
        if order_type == OrderType.TRAILING_STOP:
            if self.trail_offset is None:
                raise ValueError("TRAILING_STOP requires trail_offset")
            if self.price is not None:
                raise ValueError("TRAILING_STOP forbids price")
        return self


class OrderAccepted(StrictModel):
    order_id: str
    client_order_id: str | None = None
    status: str
    accepted: bool | None = None
    event: dict[str, Any] | None = None


class CancelAccepted(StrictModel):
    order_id: str
    status: str
    event: dict[str, Any] | None = None


class AmendRequest(StrictModel):
    price: float | None = None
    quantity: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def require_one_field(self) -> "AmendRequest":
        if self.price is None and self.quantity is None:
            raise ValueError("At least one of price or quantity is required")
        return self


class ReplaceResponse(StrictModel):
    cancelled_order_id: str
    replacement_order_id: str
    status: str


class OcoLegRequest(StrictModel):
    side: Side
    order_type: OrderType
    price: float | None = None
    stop_price: float | None = None
    trail_offset: float | None = None


class OcoRequest(StrictModel):
    oco_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    tif: TIF = TIF.DAY
    leg1: OcoLegRequest
    leg2: OcoLegRequest

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class ComboLegRequest(StrictModel):
    symbol: str = Field(min_length=1)
    side: Side
    order_type: OrderType = OrderType.LIMIT
    quantity: int = Field(gt=0)
    price: float | None = None
    stop_price: float | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class ComboRequest(StrictModel):
    combo_id: str = Field(min_length=1)
    combo_type: ComboType = ComboType.AON
    tif: TIF = TIF.DAY
    # None means the client omitted smp_action -- see OrderRequest.smp_action.
    smp_action: SmpAction | None = None
    legs: list[ComboLegRequest] = Field(min_length=2, max_length=10)


class QuoteRequest(StrictModel):
    symbol: str = Field(min_length=1)
    bid_price: float
    bid_qty: int = Field(gt=0)
    ask_price: float
    ask_qty: int = Field(gt=0)
    tif: TIF = TIF.DAY
    quote_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_spread(self) -> "QuoteRequest":
        if self.bid_price >= self.ask_price:
            raise ValueError("bid_price must be lower than ask_price")
        return self


class MassCancelRequest(StrictModel):
    symbol: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_optional_symbol(cls, value: str | None) -> str | None:
        return None if value is None else value.upper()


class PendingIdResponse(StrictModel):
    id: str
    status: str
    event: dict[str, Any] | None = None


class HistoryQuery(StrictModel):
    symbol: str | None = None
    event_type: str | None = None
    date: str | None = None
    from_ts: str | None = None
    to_ts: str | None = None
    limit: int = Field(default=500, ge=1, le=5000)


class SessionTransitionRequest(StrictModel):
    to_state: SessionState


class CircuitBreakerTriggerRequest(StrictModel):
    symbol: str = Field(min_length=1)
    level: str | None = None
    reason: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class CircuitBreakerResumeRequest(StrictModel):
    symbol: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class SymbolCancelRequest(StrictModel):
    symbol: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class KillSwitchGatewayRequest(StrictModel):
    target_gateway_id: str = Field(min_length=1)
    reason: str | None = None

    @field_validator("target_gateway_id")
    @classmethod
    def uppercase_target(cls, value: str) -> str:
        return value.upper()


class KillSwitchGlobalRequest(StrictModel):
    reason: str | None = None


class IndexRebalanceUpdate(StrictModel):
    symbol: str = Field(min_length=1)
    new_shares_outstanding: int = Field(gt=0)

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class IndexRebalanceRequest(StrictModel):
    updates: list[IndexRebalanceUpdate] = Field(min_length=1)
    reason: str | None = None


MarketDataChannel = Literal["book", "trades", "depth", "auction"]

#: Venue-wide status channels. These are delivered to every market-data
#: subscriber regardless of what it asked for, because a halt or a session
#: transition changes the meaning of every other channel — a client showing a
#: stale book during a halt is showing something false. They are therefore not
#: subscribable, and the subscription ack reports them under ``always`` so the
#: behaviour is discoverable rather than surprising.
ALWAYS_ON_CHANNELS: tuple[str, ...] = ("session", "circuit_breaker")


class MarketDataSubscriptionItem(StrictModel):
    """One (symbols x channels) subscription rule.

    An empty or ``["*"]`` ``symbols`` list means every symbol. An empty
    ``channels`` list subscribes to nothing and is reported back as rejected
    rather than silently ignored.
    """

    symbols: list[str] = Field(default_factory=list)
    channels: list[MarketDataChannel] = Field(default_factory=list)


class MarketDataControl(StrictModel):
    """Market-data subscribe/unsubscribe control frame.

    Two forms, both accepted:

    * **Flat** (original) — ``symbols`` and ``channels`` at the top level,
      meaning the cross product of the two.
    * **Items** — a list of independent rules, which is the only way to
      express "book for everything, depth for one symbol". The flat form
      cannot: it has a single symbol set shared by every channel.

    The flat form is exactly equivalent to a single item, so a client using it
    needs no changes.
    """

    action: Literal["subscribe", "unsubscribe"]
    symbols: list[str] = Field(default_factory=list)
    channels: list[MarketDataChannel] = Field(default_factory=list)
    items: list[MarketDataSubscriptionItem] = Field(default_factory=list)

    def as_items(self) -> list[MarketDataSubscriptionItem]:
        """Normalise both forms to a list of items."""
        items = list(self.items)
        if self.symbols or self.channels:
            items.append(
                MarketDataSubscriptionItem(symbols=self.symbols, channels=self.channels)
            )
        return items
