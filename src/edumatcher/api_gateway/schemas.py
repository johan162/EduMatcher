"""Pydantic request and response schemas for the REST API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError

from edumatcher.models.combo import ComboType
from edumatcher.models.order import OrderType, Side, SmpAction, TIF
from edumatcher.models.order_fields import (
    COMBO_LEG_FIELDS,
    OCO_LEG_FIELDS,
    ORDER_FIELDS,
    check_type_fields,
)
from edumatcher.models.session import SessionState


class StrictModel(BaseModel):
    """Base model that rejects unknown JSON fields."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class ErrorDetail(StrictModel):
    code: str = Field(
        description="Stable machine-readable category, e.g. VALIDATION, AUTH, "
        "ROLE_DENIED, RATE_LIMIT, ENGINE_TIMEOUT, NOT_FOUND, INTERNAL_ERROR, or "
        "a command-specific refusal such as HALT_REJECTED."
    )
    message: str = Field(
        description="Human-readable explanation; for an engine refusal, the "
        "engine's own reason."
    )
    field: str | None = Field(
        default=None, description="The offending request field, when there is one."
    )
    reject_code: str | None = Field(
        default=None,
        description="Engine-vocabulary reject code, identical across REST and "
        "ALF (e.g. TICK_VIOLATION, MISSING_FIELD, RATE_LIMITED).",
    )
    client_tag: str | None = Field(
        default=None, description="The request's `client_tag`, echoed back."
    )
    request_tag: str | None = Field(
        default=None, description="The request's `request_tag`, echoed back."
    )


class ErrorResponse(StrictModel):
    error: ErrorDetail


def _check_type_fields(
    model: BaseModel, order_type: OrderType, carried: tuple[str, ...], where: str
) -> None:
    """Apply the shared per-type rule (``models/order_fields``) to *model*.

    The error's type is the verdict's ``reject_code``, which the validation
    handler passes through, so a REST client gets the same ``reject_code`` as
    an ALF or BALF client sending the same order.
    """
    present = [name for name in carried if getattr(model, name) is not None]
    violation = check_type_fields(order_type, present, carried=carried, where=where)
    if violation is not None:
        raise PydanticCustomError(
            violation.reject_code.lower(), "{message}", {"message": violation.message}
        )


class OrderRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": 100,
                    "price": 187.25,
                    "tif": "DAY",
                    "client_tag": "strategy-7",
                }
            ]
        }
    )

    symbol: str = Field(
        min_length=1, description="Instrument, e.g. `AAPL` (case-insensitive)."
    )
    side: Side
    order_type: OrderType = Field(
        description="Decides which of price / stop_price / visible_qty / "
        "trail_offset are required or forbidden."
    )
    quantity: int = Field(gt=0, description="Shares; a positive whole number.")
    tif: TIF = Field(
        default=TIF.DAY,
        description="Time in force: how long the order may rest. Default DAY.",
    )
    price: float | None = Field(
        default=None,
        description="Limit price on the symbol's tick grid. Required for "
        "LIMIT, FOK, IOC, STOP_LIMIT and ICEBERG; forbidden for MARKET, STOP "
        "and TRAILING_STOP.",
    )
    stop_price: float | None = Field(
        default=None,
        description="Trigger price. Required for STOP and STOP_LIMIT; for "
        "TRAILING_STOP an optional initial stop (default: last trade +/- "
        "`trail_offset`); forbidden otherwise.",
    )
    visible_qty: int | None = Field(
        default=None,
        gt=0,
        description="ICEBERG only: the quantity shown at a time; must be "
        "smaller than `quantity`.",
    )
    trail_offset: float | None = Field(
        default=None,
        description="TRAILING_STOP only: distance the stop trails the market.",
    )
    # None means the client omitted smp_action -- the engine applies this
    # gateway's configured smp_action default in that case, distinct from an
    # explicit "smp_action": "NONE" (deliberately allow self-trades). See
    # SmpAction's docstring in models/order.py.
    smp_action: SmpAction | None = Field(
        default=None,
        description="Self-match prevention. Omit to use the gateway's "
        "configured default; `NONE` explicitly allows trading with yourself.",
    )
    client_tag: str | None = Field(
        default=None,
        max_length=64,
        description="Your own label (max 64 chars), echoed on every event and "
        "in `GET /orders` for this order.",
    )

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_by_order_type(self) -> "OrderRequest":
        order_type = OrderType(self.order_type)
        _check_type_fields(self, order_type, ORDER_FIELDS, "on an order")
        if (
            order_type == OrderType.ICEBERG
            and self.visible_qty is not None
            and self.visible_qty >= self.quantity
        ):
            raise ValueError("ICEBERG visible_qty must be less than quantity")
        return self


class OrderAccepted(StrictModel):
    order_id: str = Field(description="Engine order id; use it to amend or cancel.")
    client_tag: str | None = Field(
        default=None, description="Echo of the request's tag."
    )
    status: Literal["PENDING", "ACKED"] = Field(
        description="`PENDING` (not yet acknowledged) or `ACKED`."
    )
    accepted: bool | None = Field(
        default=None,
        description="Engine verdict; null until acknowledged (see `?wait=ack`).",
    )
    reject_code: str | None = Field(
        default=None, description="Why the engine refused it, when `accepted` is false."
    )
    event: dict[str, Any] | None = Field(
        default=None, description="The engine's `order.ack` event, once received."
    )

    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class CancelAccepted(StrictModel):
    order_id: str
    request_tag: str | None = Field(
        default=None, description="Echo of the request's `request_tag` query param."
    )
    status: Literal["PENDING_CANCEL", "ACKED", "REJECTED"]
    accepted: bool | None = Field(
        default=None, description="Engine verdict; null until acknowledged."
    )
    reject_code: str | None = Field(
        default=None, description="Why the cancel was refused, when it was."
    )
    event: dict[str, Any] | None = Field(
        default=None,
        description="The engine's cancel (or reject) event, once received.",
    )

    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class AmendRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"price": 187.5, "quantity": 100, "request_tag": "amend-1"}]
        }
    )

    price: float | None = Field(default=None, description="New limit price.")
    quantity: int | None = Field(
        default=None, gt=0, description="New total quantity (not the increment)."
    )
    request_tag: str | None = Field(
        default=None,
        max_length=64,
        description="Your label, echoed on the amend's outcome event.",
    )

    @model_validator(mode="after")
    def require_one_field(self) -> "AmendRequest":
        if self.price is None and self.quantity is None:
            raise ValueError("At least one of price or quantity is required")
        return self


class ReplaceResponse(StrictModel):
    cancelled_order_id: str = Field(description="The order that was cancelled.")
    replacement_order_id: str = Field(description="Id of the new order.")
    status: Literal["PENDING", "ACKED"] = Field(
        description="`PENDING` until the engine acks the replacement (`?wait=ack`)."
    )
    accepted: bool | None = Field(
        default=None, description="The replacement's verdict; null until acked."
    )
    reject_code: str | None = Field(
        default=None, description="Why the replacement was refused, when it was."
    )
    event: dict[str, Any] | None = Field(
        default=None, description="The replacement's `order.ack`, once received."
    )
    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class OcoLegRequest(StrictModel):
    side: Side
    order_type: OrderType
    price: float | None = Field(
        default=None, description="Limit price, if the leg has one."
    )
    stop_price: float | None = Field(
        default=None, description="Trigger price, for stop legs."
    )
    trail_offset: float | None = Field(
        default=None, description="For trailing-stop legs."
    )

    @model_validator(mode="after")
    def validate_by_order_type(self) -> "OcoLegRequest":
        _check_type_fields(
            self, OrderType(self.order_type), OCO_LEG_FIELDS, "on an OCO leg"
        )
        return self


class OcoRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "oco_id": "oco-2026-0042",
                    "symbol": "AAPL",
                    "quantity": 100,
                    "tif": "GTC",
                    "client_tag": "bracket-1",
                    "leg1": {"side": "SELL", "order_type": "LIMIT", "price": 192.0},
                    "leg2": {
                        "side": "SELL",
                        "order_type": "STOP",
                        "stop_price": 183.0,
                    },
                }
            ]
        }
    )

    oco_id: str = Field(
        min_length=1, description="Your id for the pair; used to cancel it."
    )
    symbol: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    tif: TIF = TIF.DAY
    client_tag: str | None = Field(default=None, max_length=64)
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

    @model_validator(mode="after")
    def validate_by_order_type(self) -> "ComboLegRequest":
        _check_type_fields(
            self, OrderType(self.order_type), COMBO_LEG_FIELDS, "on a combo leg"
        )
        return self


class ComboRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "combo_id": "combo-spread-17",
                    "combo_type": "AON",
                    "tif": "DAY",
                    "legs": [
                        {
                            "symbol": "AAPL",
                            "side": "BUY",
                            "order_type": "LIMIT",
                            "quantity": 100,
                            "price": 187.25,
                        },
                        {
                            "symbol": "MSFT",
                            "side": "SELL",
                            "order_type": "LIMIT",
                            "quantity": 45,
                            "price": 412.8,
                        },
                    ],
                }
            ]
        }
    )

    combo_id: str = Field(
        min_length=1, description="Your id for the combo; used to cancel it."
    )
    combo_type: ComboType = ComboType.AON
    tif: TIF = TIF.DAY
    # None means the client omitted smp_action -- see OrderRequest.smp_action.
    smp_action: SmpAction | None = None
    client_tag: str | None = Field(default=None, max_length=64)
    legs: list[ComboLegRequest] = Field(
        min_length=2, max_length=10, description="2-10 legs; all must fill (AON)."
    )


class QuoteRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "symbol": "AAPL",
                    "bid_price": 187.2,
                    "bid_qty": 500,
                    "ask_price": 187.3,
                    "ask_qty": 500,
                    "quote_id": "q-AAPL-0001",
                }
            ]
        }
    )

    symbol: str = Field(min_length=1)
    bid_price: float = Field(description="Must be lower than `ask_price`.")
    bid_qty: int = Field(gt=0)
    ask_price: float
    ask_qty: int = Field(gt=0)
    tif: TIF = TIF.DAY
    quote_id: str | None = Field(
        default=None, description="Your id for the quote; defaults to the symbol."
    )

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
    model_config = ConfigDict(json_schema_extra={"examples": [{"symbol": "AAPL"}]})

    symbol: str | None = Field(
        default=None, description="Only cancel this symbol. Omit to cancel everything."
    )

    @field_validator("symbol")
    @classmethod
    def uppercase_optional_symbol(cls, value: str | None) -> str | None:
        return None if value is None else value.upper()


class OcoAccepted(StrictModel):
    oco_id: str = Field(
        description="The id you chose; `DELETE /oco/{oco_id}` takes it."
    )
    status: Literal["PENDING", "ACKED"] = Field(
        description="`PENDING`: sent, the verdict follows on the private WebSocket "
        "(`oco.ack`); `ACKED` with `?wait=ack`."
    )
    accepted: bool | None = Field(
        default=None, description="Engine verdict; null until acknowledged."
    )
    reason: str | None = Field(
        default=None, description="The engine's reason, when it refused."
    )
    event: dict[str, Any] | None = Field(
        default=None, description="The engine's `oco.ack`, once received."
    )
    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class ComboAccepted(StrictModel):
    combo_id: str = Field(
        description="The id you chose; `DELETE /combos/{combo_id}` takes it."
    )
    status: Literal["PENDING", "ACKED"] = Field(
        description="`PENDING`: sent, the verdict follows on the private WebSocket "
        "(`combo.ack`); `ACKED` with `?wait=ack`."
    )
    accepted: bool | None = Field(
        default=None, description="Engine verdict; null until acknowledged."
    )
    reason: str | None = Field(
        default=None, description="The engine's reason, when it refused."
    )
    event: dict[str, Any] | None = Field(
        default=None, description="The engine's `combo.ack`, once received."
    )
    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class QuoteAccepted(StrictModel):
    symbol: str = Field(description="`DELETE /quotes/{symbol}` takes it.")
    quote_id: str | None = Field(description="Your id for the quote, if you set one.")
    status: Literal["PENDING", "ACKED"] = Field(
        description="`PENDING`: sent, the verdict follows on the private WebSocket "
        "(`quote.ack`); `ACKED` with `?wait=ack`."
    )
    accepted: bool | None = Field(
        default=None, description="Engine verdict; null until acknowledged."
    )
    reason: str | None = Field(
        default=None, description="The engine's reason, when it refused."
    )
    event: dict[str, Any] | None = Field(
        default=None, description="The engine's `quote.ack`, once received."
    )
    ack_timeout: bool = Field(
        default=False,
        description="True when `?wait=ack` gave up waiting: the request was sent "
        "and the outcome follows on the private WebSocket.",
    )


class SessionTransitionRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={"examples": [{"to_state": "CLOSING_AUCTION"}]}
    )

    to_state: SessionState


#: Bounds that mirror the `risk` spec's `max_len` on the fields these become.
#: They are load-bearing, not cosmetic: since 5.3a/5.3b the builders validate,
#: so an unbounded value here reaches a generated constructor and raises —
#: turning a client's bad input into a 500 where FastAPI would otherwise have
#: returned a 400 naming the offending field. Bound at the edge, where the
#: error can still say what was wrong. The admin routes apply the first two to
#: their `{symbol}` and `{gateway_id}` path parameters.
SYMBOL_MAX_LEN = 16
GATEWAY_ID_MAX_LEN = 32
_MAX_CB_LEVEL = 32
_MAX_REASON = 256


class SymbolHaltRequest(StrictModel):
    """Body of `POST /admin/symbols/{symbol}/halt`; may be omitted."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"level": "L1", "reason": "Unusual volatility"}]
        }
    )

    level: str | None = Field(
        default=None,
        max_length=_MAX_CB_LEVEL,
        description="A rung of the symbol's ladder (see `/reference/symbols`). "
        "Omit for an indefinite halt until explicitly resumed.",
    )
    reason: str | None = Field(
        default=None,
        max_length=_MAX_REASON,
        description="Free-text note for the audit log.",
    )


class AdminNoteRequest(StrictModel):
    """Body of the admin actions that take only a note; may be omitted."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"reason": "Runaway algo"}]}
    )

    reason: str | None = Field(
        default=None,
        max_length=_MAX_REASON,
        description="Free-text note for the audit log.",
    )


class IndexRebalanceUpdate(StrictModel):
    symbol: str = Field(min_length=1)
    new_shares_outstanding: int = Field(gt=0)

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, value: str) -> str:
        return value.upper()


class IndexRebalanceRequest(StrictModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "updates": [
                        {"symbol": "AAPL", "new_shares_outstanding": 15500000000},
                        {"symbol": "TSLA", "new_shares_outstanding": 3250000000},
                    ],
                }
            ]
        }
    )

    updates: list[IndexRebalanceUpdate] = Field(min_length=1)


MarketDataChannel = Literal["book", "trades", "depth", "auction"]

#: Venue-wide status channels. These are delivered to every market-data
#: subscriber regardless of what it asked for, because a halt or a session
#: transition changes the meaning of every other channel — a client showing a
#: stale book during a halt is showing something false. They are therefore not
#: subscribable, and the subscription ack reports them under ``always`` so the
#: behaviour is discoverable rather than surprising. ``news`` (pm-market-sim's
#: headlines) is here too: a handful a day, and a headline can be about a
#: whole sector or the market, which no symbol subscription could express.
ALWAYS_ON_CHANNELS: tuple[str, ...] = ("session", "circuit_breaker", "news")


class MarketDataSubscriptionItem(StrictModel):
    """One (symbols x channels) subscription rule.

    An empty or ``["*"]`` ``symbols`` list means every symbol. An empty
    ``channels`` list subscribes to nothing and is reported back as rejected
    rather than silently ignored.

    ``resume_from`` is an optional per-channel hint carrying the last ``seq``
    the client processed on that channel's topic for this item's symbol(s). It
    is honoured for ``trades`` (buffered prints after that ``seq`` are
    replayed); for the self-healing snapshot channels the current snapshot is
    sent instead. Absent means "just send me the current snapshot".
    """

    symbols: list[str] = Field(default_factory=list)
    channels: list[MarketDataChannel] = Field(default_factory=list)
    resume_from: dict[MarketDataChannel, int] | None = None


class MarketDataControl(StrictModel):
    """Market-data control frame.

    Four actions:

    * ``subscribe`` / ``unsubscribe`` — change the socket's active rule set.
    * ``snapshot`` — re-emit the current cached snapshot for the given
      symbols/channels without changing the subscription.
    * ``resume`` — replay one dropped stream from ``from_seq``. Names the
      topic either explicitly (``topic`` + optional ``symbol``) or, for
      ``subscribe``, via a per-item ``resume_from`` hint.

    Two subscription forms, both accepted (and unchanged):

    * **Flat** — ``symbols`` and ``channels`` at the top level (their cross
      product).
    * **Items** — a list of independent rules, the only way to express "book
      for everything, depth for one symbol".

    The flat form equals a single item, so an existing client needs no change.
    """

    action: Literal["subscribe", "unsubscribe", "snapshot", "resume"]
    symbols: list[str] = Field(default_factory=list)
    channels: list[MarketDataChannel] = Field(default_factory=list)
    items: list[MarketDataSubscriptionItem] = Field(default_factory=list)
    #: ``resume`` only: the engine topic to replay (e.g. ``"trade.executed"``)
    #: and the last sequence the client processed. When the topic is not itself
    #: symbol-qualified (``trade.executed``), the symbol is taken from the
    #: ``symbols`` list above — there is deliberately no singular ``symbol``
    #: field, so a ``symbol``/``symbols`` typo stays an error.
    topic: str | None = None
    from_seq: int | None = None

    def as_items(self) -> list[MarketDataSubscriptionItem]:
        """Normalise both forms to a list of items."""
        items = list(self.items)
        if self.symbols or self.channels:
            items.append(
                MarketDataSubscriptionItem(symbols=self.symbols, channels=self.channels)
            )
        return items
