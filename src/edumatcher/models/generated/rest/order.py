# GENERATED FROM spec/messages/order.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``order`` message family.

Family version 1. Derived from ``spec/messages/order.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OcoLegSide = Literal["BUY", "SELL"]
OcoLegOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
ComboLegSide = Literal["BUY", "SELL"]
ComboLegOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
ComboLegSmpAction = Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]
OrderDisplaySide = Literal["BUY", "SELL"]
OrderDisplayOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
OrderDisplayTif = Literal["DAY", "GTC", "ATO", "ATC"]
OrderDisplayStatus = Literal[
    "NEW",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]
OrderDisplaySmpAction = Literal[
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
]
OrderDisplayOrigin = Literal["ORDER", "QUOTE", "IMPLIED"]
PriceLevelOrderSide = Literal["BUY", "SELL"]
PriceLevelOrderOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
PriceLevelOrderTif = Literal["DAY", "GTC", "ATO", "ATC"]
PriceLevelOrderStatus = Literal[
    "NEW",
    "PARTIAL",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
]
PriceLevelOrderSmpAction = Literal[
    "NONE",
    "CANCEL_AGGRESSOR",
    "CANCEL_RESTING",
    "CANCEL_BOTH",
]
PriceLevelOrderOrigin = Literal["ORDER", "QUOTE", "IMPLIED"]
ExecutionReportSide = Literal["BUY", "SELL"]
ExecutionReportStatus = Literal["PARTIAL", "FILLED"]
StopTriggeredOrderType = Literal["STOP", "STOP_LIMIT", "TRAILING_STOP"]
StopTriggeredBecomes = Literal["MARKET", "LIMIT"]
OrderAckRejectCode = Literal[
    "MALFORMED_MESSAGE",
    "MISSING_FIELD",
    "INVALID_VALUE",
    "UNSUPPORTED_FIELD",
    "AUTH_REQUIRED",
    "AUTH_FAILED",
    "ROLE_DENIED",
    "NOT_OWNER",
    "RATE_LIMITED",
    "GATEWAY_NOT_CONFIGURED",
    "UNKNOWN_SYMBOL",
    "SYMBOL_NOT_READY",
    "TICK_VIOLATION",
    "LOT_VIOLATION",
    "PRICE_OUT_OF_RANGE",
    "QTY_OUT_OF_RANGE",
    "COLLAR_BREACH",
    "MAX_ORDER_QTY",
    "MAX_ORDER_VALUE",
    "POSITION_LIMIT",
    "KILL_SWITCH_ACTIVE",
    "MARKET_CLOSED",
    "SESSION_NOT_PERMITTED",
    "INSTRUMENT_HALTED",
    "CIRCUIT_BREAKER_ACTIVE",
    "ORDER_NOT_FOUND",
    "ORDER_ALREADY_TERMINAL",
    "AMEND_NOT_PERMITTED",
    "DUPLICATE_ORDER",
    "INSUFFICIENT_LIQUIDITY",
    "SELF_MATCH_PREVENTED",
    "INTERNAL_ERROR",
    "UNKNOWN",
]
OrderAckSmpAction = Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]
OrderFillStatus = Literal["PARTIAL", "FILLED"]
OrderFillLiquidityFlag = Literal["MAKER", "TAKER"]
OrderCancelledCancelReason = Literal[
    "SELF_MATCH_PREVENTED",
    "INSUFFICIENT_LIQUIDITY",
    "KILL_SWITCH",
    "CIRCUIT_BREAKER_HALT",
    "GATEWAY_DISCONNECT",
    "ADMIN_CANCEL_SYMBOL",
    "QUOTE_REPLACED",
    "QUOTE_LEG_FILLED",
]
OrderTriggeredOrderType = Literal["STOP", "STOP_LIMIT", "TRAILING_STOP"]
OrderTriggeredBecomes = Literal["MARKET", "LIMIT"]
EngineTraceKind = Literal["RESTED", "ICEBERG_REFILL", "TRAILING_RATCHET"]
OrderNewSide = Literal["BUY", "SELL"]
OrderNewOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
OrderNewTif = Literal["DAY", "GTC", "ATO", "ATC"]
OrderNewStatus = Literal["NEW", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"]
OrderNewSmpAction = Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]
OrderNewOrigin = Literal["ORDER", "QUOTE", "IMPLIED"]
OrderComboComboType = Literal["AON"]
OrderComboTif = Literal["DAY", "GTC", "ATO", "ATC"]
OrderOcoTif = Literal["DAY", "GTC", "ATO", "ATC"]


class OcoLeg(BaseModel):
    """One side of an OCO pair. It has no symbol or quantity of its own: both legs
    trade the same instrument in the same size, and the OCO carries those. That is
    what makes it a different record from a combo leg, which does own a symbol and
    a quantity.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    side: OcoLegSide
    order_type: OcoLegOrderType
    price_ticks: int | None = Field(default=None)
    """Limit price in engine ticks. Absent for a leg with none. The scale is
    `order.oco.tick_decimals`: both legs trade one instrument, so one scale covers
    the pair. Unit: ticks.
    """
    stop_price_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    trail_offset_ticks: int | None = Field(default=None)
    """Unit: ticks."""


class ComboLeg(BaseModel):
    """One leg of a combo. Unlike an OcoLeg it owns a symbol and a quantity: the legs
    of a combo trade different instruments, in sizes that need not match. That is
    why the two are separate types rather than one shared `leg` - an early draft
    of design section 15 assumed they could be merged and was wrong.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    side: ComboLegSide
    order_type: ComboLegOrderType
    quantity: int = Field(gt=0)
    """Unit: shares."""
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for this leg's tick prices; 1 tick = 10^-tick_decimals. Per leg
    rather than on the combo, because a combo's legs trade different instruments
    and two instruments need not share a scale - which is exactly the distinction
    that makes ComboLeg a separate record from OcoLeg.
    """
    price_ticks: int | None
    """Limit price in engine ticks; null for a leg with none. Unit: ticks."""
    stop_price_ticks: int | None
    """Unit: ticks."""
    smp_action: ComboLegSmpAction | None
    """Null means the client did not specify SMP, which is distinct from an explicit
    NONE. Combo-level in the ALF protocols, so every leg carries the same value.
    """


class OrderDisplay(BaseModel):
    """One resting order as the engine reports it in an `order.orders` snapshot, in
    display units. It is `Order.to_dict()` with price, stop_price and trail_offset
    converted from ticks to display money - the projection `order_to_display_dict`
    builds so an operator reads prices in the same money the book shows, not raw
    ticks. `timestamp` is carried through as `ts_ns` unconverted (AR-0.3b): unlike
    price, a raw nanosecond integer is exactly what a post-mortem needs to compare
    against `trade.executed.ts_ns` and the rest of the wire's ordering convention,
    and converting it to seconds here would only have to be undone by anything
    that wanted to compare it. `spec/messages/index.yaml`'s family made the same
    call for the same reason in AR-0.3; this type was out of scope for that pass
    (it is not part of the index family) and CP-0's own checklist item 3 is what
    caught it being left behind. Gateway_id is not included here; it is topic-only
    (part of the message topic as order.orders.{gateway_id}, not part of the
    record). The record contains the order state (id, symbol, side, etc.) exactly
    as Order.to_dict() produces, minus gateway_id; the eleven nullable ones ride
    as null when unset.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=64)
    """Engine order id; a UUID string."""
    symbol: str = Field(max_length=16)
    side: OrderDisplaySide
    order_type: OrderDisplayOrderType
    tif: OrderDisplayTif
    quantity: int = Field(gt=0)
    """Total original quantity. Unit: shares."""
    remaining_qty: int = Field(ge=0)
    """Quantity yet to be filled. Unit: shares."""
    trail_offset: float | None
    """TRAILING_STOP: trail distance, in display money. Unit: display_price."""
    oco_group_id: str | None = Field(max_length=64)
    ts_ns: int = Field(ge=0)
    """Client-supplied submission time (Order.timestamp, unconverted). NOT the book's
    time priority key - see arrival_seq. AR-0.3b: previously named "timestamp" and
    expressed as a seconds-based float; see OrderDisplay's type doc for why that
    was out of step with the rest of the wire and got fixed here rather than left
    as the one field of that kind outside log.yaml. Unit: epoch_nanos.
    """
    status: OrderDisplayStatus
    price: float | None
    """Limit price in display money. Null for MARKET, which has none. Unit:
    display_price.
    """
    stop_price: float | None
    """STOP / STOP_LIMIT / TRAILING_STOP trigger. Unit: display_price."""
    visible_qty: int | None
    """ICEBERG: fixed peak size. Unit: shares."""
    displayed_qty: int | None
    """ICEBERG: current visible slice on the book. Unit: shares."""
    smp_action: OrderDisplaySmpAction | None
    """Self-match prevention. Null means the client did not specify SMP at all,
    distinct from an explicit NONE. See SmpAction's docstring.
    """
    combo_parent_id: str | None = Field(max_length=64)
    leg_index: int | None
    """Position in the parent combo's legs, 0-based."""
    origin: OrderDisplayOrigin
    """Defaulted rather than nullable: to_dict always supplies ORDER."""
    is_seed: bool
    """True when this order was created by config-driven startup seeding
    (market_maker_quotes / market_maker_combos in the engine config) rather than a
    live gateway submission. Purely observational — nothing in the engine branches
    on it; origin still governs routing. Lets a post-mortem tell a config
    bootstrap apart from real participant activity without depending on id-naming
    conventions. Absent on records written before this field existed.
    """
    quote_id: str | None = Field(max_length=64)
    client_tag: str | None = Field(max_length=64)
    """Client correlation tag, echoed on every lifecycle event."""
    arrival_seq: int
    """Engine-assigned monotonic arrival sequence; 0 = unassigned."""


class PriceLevelOrder(BaseModel):
    """One resting order as reported by order.price_level_orders — the same
    projection as OrderDisplay (order_to_display_dict, including its ts_ns field —
    see OrderDisplay's doc for why that one is not converted to display units the
    way price/stop_price/trail_offset are), with one field added: gateway_id.
    OrderDisplay can leave gateway_id topic-only because an order.orders reply is
    always about a single, already-known gateway; a price_level_orders reply spans
    every gateway resting at a symbol/price, so each record must say whose order
    it is. The generator has no type-extension mechanism, so this duplicates
    OrderDisplay's field list rather than referencing it — keep the two in sync by
    hand if OrderDisplay's fields change.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Owning gateway — the one piece of information OrderDisplay omits because its
    own topic already says it.
    """
    id: str = Field(max_length=64)
    """Engine order id; a UUID string."""
    symbol: str = Field(max_length=16)
    side: PriceLevelOrderSide
    order_type: PriceLevelOrderOrderType
    tif: PriceLevelOrderTif
    quantity: int = Field(gt=0)
    """Total original quantity. Unit: shares."""
    remaining_qty: int = Field(ge=0)
    """Quantity yet to be filled. Unit: shares."""
    trail_offset: float | None
    """TRAILING_STOP: trail distance, in display money. Unit: display_price."""
    oco_group_id: str | None = Field(max_length=64)
    ts_ns: int = Field(ge=0)
    """Client-supplied submission time (Order.timestamp, unconverted). NOT the book's
    time priority key - see arrival_seq. AR-0.3b: previously named "timestamp" and
    expressed as a seconds-based float; see OrderDisplay's type doc for why that
    was out of step with the rest of the wire and got fixed here rather than left
    as the one field of that kind outside log.yaml. Unit: epoch_nanos.
    """
    status: PriceLevelOrderStatus
    price: float | None
    """Limit price in display money. Null for MARKET, which has none. Unit:
    display_price.
    """
    stop_price: float | None
    """STOP / STOP_LIMIT / TRAILING_STOP trigger. Unit: display_price."""
    visible_qty: int | None
    """ICEBERG: fixed peak size. Unit: shares."""
    displayed_qty: int | None
    """ICEBERG: current visible slice on the book. Unit: shares."""
    smp_action: PriceLevelOrderSmpAction | None
    """Self-match prevention. Null means the client did not specify SMP at all,
    distinct from an explicit NONE. See SmpAction's docstring.
    """
    combo_parent_id: str | None = Field(max_length=64)
    leg_index: int | None
    """Position in the parent combo's legs, 0-based."""
    origin: PriceLevelOrderOrigin
    """Defaulted rather than nullable: to_dict always supplies ORDER."""
    is_seed: bool
    """True when this order was created by config-driven startup seeding
    (market_maker_quotes / market_maker_combos in the engine config) rather than a
    live gateway submission. Purely observational — nothing in the engine branches
    on it; origin still governs routing. Lets a post-mortem tell a config
    bootstrap apart from real participant activity without depending on id-naming
    conventions. Absent on records written before this field existed.
    """
    quote_id: str | None = Field(max_length=64)
    client_tag: str | None = Field(max_length=64)
    """Client correlation tag, echoed on every lifecycle event."""
    arrival_seq: int
    """Engine-assigned monotonic arrival sequence; 0 = unassigned."""


class ExecutionReport(BaseModel):
    """Private per-order fill notification, sent to the gateway session that owns the
    order. Both sides of a match receive their own report.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    client_order_id: int
    """Echoed from the original NEW_ORDER so a client can correlate."""
    order_id: int
    """Session-scoped BALF order id assigned by the gateway. A u64 on the wire, not a
    string - this is the field the reference example got wrong.
    """
    fill_price: float = Field(gt=0)
    """Execution price in display money. On the wire it is an i64 scaled by the fixed
    BALF PRICE_SCALE of 10^8, never by the instrument's tick_decimals. Unit:
    display_price.
    """
    fill_qty: int = Field(gt=0)
    """Quantity matched in this event, not cumulatively. Unit: shares."""
    remaining_qty: int = Field(ge=0)
    """Unfilled quantity after this fill; zero means the order is done. Unit: shares."""
    timestamp_ns: int = Field(ge=0)
    """Trade time in nanoseconds since the Unix epoch. Unit: epoch_nanos."""
    symbol: str = Field(max_length=8, pattern="^[A-Z0-9._]+$")
    """Instrument, echoed for convenience; matches the original order."""
    side: ExecutionReportSide
    """Side of the filled order."""
    status: ExecutionReportStatus
    """Whether this fill completed the order. Only these two values exist on BALF -
    there is no NEW or CANCELLED execution report.
    """


class StopTriggered(BaseModel):
    """A stop, stop-limit or trailing stop of this session has fired. Sent before the
    order's own execution reports, so a client knows why its stop traded -- the
    FIX analogue is ExecType=L.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    client_order_id: int
    """Echoed from the original NEW_ORDER."""
    order_id: int
    """Session-scoped BALF order id assigned by the gateway."""
    stop_price: float = Field(gt=0)
    """The trigger price it fired at (a trailing stop's ratcheted one), in display
    money; i64 x 10^8 on the wire. Unit: display_price.
    """
    trigger_price: float = Field(ge=0)
    """The price of the trade that reached the trigger; 0 when the last price came
    from a restart. Unit: display_price.
    """
    symbol: str = Field(max_length=8, pattern="^[A-Z0-9._]+$")
    order_type: StopTriggeredOrderType
    """The order as it was armed (NEW_ORDER's order_type codes)."""
    becomes: StopTriggeredBecomes
    """STOP and TRAILING_STOP become MARKET; STOP_LIMIT becomes LIMIT."""


class OrderAck(BaseModel):
    """Acknowledge acceptance or rejection of a new order, addressed to the gateway
    that submitted it.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    accepted: bool
    reason: str = Field(max_length=256)
    """Rejection detail; empty when accepted."""
    reject_code: OrderAckRejectCode | None = Field(default=None)
    """Machine-readable rejection classification, stable across every order-entry
    transport (ALF, BALF, REST) and every layer (gateway-local validation and
    engine-side business rules). Absent when accepted; present on every rejection.
    The human-readable detail rides in reason; this field never carries data
    values. New members may be added; existing members are never removed or
    renamed. A client must treat an unrecognised code as UNKNOWN.
    """
    symbol: str | None = Field(default=None, max_length=16)
    side: str | None = Field(default=None, max_length=8)
    order_type: str | None = Field(default=None, max_length=16)
    tif: str | None = Field(default=None, max_length=8)
    qty: int | None = Field(default=None)
    """Unit: shares."""
    price: float | None = Field(default=None)
    """Absent for a MARKET order, which has no limit price. Unit: display_price."""
    stop_price: float | None = Field(default=None)
    """STOP / STOP_LIMIT / TRAILING_STOP trigger. Absent for a type that carries
    none. Unit: display_price.
    """
    visible_qty: int | None = Field(default=None)
    """ICEBERG: fixed peak size. Absent for a type that carries none. Unit: shares."""
    trail_offset: float | None = Field(default=None)
    """TRAILING_STOP: trail distance, in display money. Absent for a type that
    carries none. Unit: display_price.
    """
    smp_action: OrderAckSmpAction | None = Field(default=None)
    """Self-match prevention. Null means the client did not specify SMP at all,
    distinct from an explicit NONE. See SmpAction's docstring.
    """
    client_tag: str | None = Field(default=None, max_length=64)
    request_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this request, echoed on the resulting event or
    rejection. Distinct from the target order's client_tag, which identifies the
    order rather than the request acting on it. A client may have several requests
    outstanding against one order.
    """
    oco_group_id: str | None = Field(default=None, max_length=64)
    combo_parent_id: str | None = Field(default=None, max_length=64)
    quote_id: str | None = Field(default=None, max_length=64)
    leg_index: int | None = Field(default=None)
    is_seed: bool
    """True when this order was created by config-driven startup seeding rather than
    a live gateway submission. See OrderDisplay.is_seed (above) for the full
    rationale; this is the ack-time echo of the same fact, since order.ack — not
    order.new, which never reaches the engine's PUB feed — is the first audit-
    visible event for any order, seeded or live.
    """
    price_ticks: int | None = Field(default=None)
    """`price` in engine ticks. Canonical; the float beside it is for display. Scale:
    the symbol's tick_decimals. Unit: ticks.
    """
    stop_price_ticks: int | None = Field(default=None)
    """`stop_price` in engine ticks. Canonical; the float beside it is for display.
    Scale: the symbol's tick_decimals. Unit: ticks.
    """
    trail_offset_ticks: int | None = Field(default=None)
    """`trail_offset` in engine ticks. Canonical; the float beside it is for display.
    Scale: the symbol's tick_decimals. Unit: ticks.
    """


class OrderFill(BaseModel):
    """Private fill notification for one order, addressed to the gateway that owns
    it. The public counterpart is trade.executed.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    fill_qty: int
    """Unit: shares."""
    fill_price: float
    """Unit: display_price."""
    remaining_qty: int
    """Unit: shares."""
    status: OrderFillStatus
    """Whether this fill completed the order. The same two values BALF's
    execution_report uses, and the same vocabulary as order.new.status - there is
    one name for an order state across the system. This was the only status field
    the spec left as an unconstrained string, and it drifted: six publish sites
    derived the value from OrderStatus and sent PARTIAL while the continuous-
    matching hot path and _publish_amend_rematch sent PARTIAL_FILL, so a fill on a
    quote leg reported a different status from a fill on an ordinary order.
    Nothing in the system ever branched on PARTIAL_FILL - every consumer passed it
    through - so the two outliers were corrected rather than the six. BREAKING for
    anything matching the string: the ALF FILL line, the REST order cache and a
    bot written against docs-design/EduMatcher-AI-trading-bot-v2.md all carried
    PARTIAL_FILL verbatim. Nothing reads the old spelling any more, pm-audit-
    replay included - a log containing it does not describe a wire this build
    speaks.
    """
    symbol: str | None = Field(default=None, max_length=16)
    side: str | None = Field(default=None, max_length=8)
    order_type: str | None = Field(default=None, max_length=16)
    tif: str | None = Field(default=None, max_length=8)
    qty: int | None = Field(default=None)
    """Unit: shares."""
    price: float | None = Field(default=None)
    """Unit: display_price."""
    client_tag: str | None = Field(default=None, max_length=64)
    oco_group_id: str | None = Field(default=None, max_length=64)
    combo_parent_id: str | None = Field(default=None, max_length=64)
    quote_id: str | None = Field(default=None, max_length=64)
    leg_index: int | None = Field(default=None)
    is_seed: bool
    """True when this order was created by config-driven startup seeding rather than
    a live gateway submission. See OrderDisplay.is_seed for the full rationale;
    carried here too so a fill reached after the originating order.ack has rotated
    out of the audit log still says whether the filled order was a config seed.
    """
    trade_ids: list[str]
    """The public trade.executed id(s) that composed this fill event. Usually one;
    more than one when an aggressor swept several resting orders and the engine
    coalesced them into a single VWAP fill (H5/H6). Every current call site only
    publishes order_fill from a real trade, so in practice this is never empty; it
    is typed as a list (not required) defensively, for a fill notification that
    might one day exist without one. Lets a reader link a private fill to the
    public trade tape without re-deriving the join.
    """
    liquidity_flag: OrderFillLiquidityFlag | None = Field(default=None)
    """Derived from the trade's aggressor side: the aggressor is the TAKER and the
    resting side the MAKER (same derivation as drop_copy.yaml::liquidity_flag).
    Nullable/omit_when_none for the same reason trade_ids is typed as an empty-
    able list: every current call site only publishes order_fill from a real
    trade, so this is never actually absent today, but nothing enforces that a
    future fill notification always has a trade behind it.
    """
    fill_notional_ticks: int | None = Field(default=None, ge=0)
    """Σ price_ticks × quantity of the trades in `trade_ids`: the fill's money
    exactly (`fill_price` is its VWAP, rounded for display). Unit: notional_ticks.
    """
    cum_qty: int | None = Field(default=None, ge=0)
    """Quantity the order has filled in all, this fill included. Unit: shares."""
    cum_notional_ticks: int | None = Field(default=None, ge=0)
    """Σ price_ticks × quantity of every fill of the order so far; with `cum_qty`,
    the exact average price. Unit: notional_ticks.
    """


class OrderCancelled(BaseModel):
    """Confirm that a resting order has been cancelled."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    symbol: str | None = Field(default=None, max_length=16)
    """Instrument this order belonged to. The engine has always had this at the
    publish site (the cancelled Order's own .symbol); it was simply never carried
    on the wire, which made order.cancelled invisible to a --symbol filter
    (AR-0.2). Nullable/omit_when_none, like old_price/old_qty on order.amended
    below, so archived records written before this field existed still parse.
    """
    client_tag: str | None = Field(default=None, max_length=64)
    request_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this cancel request. Engine-initiated cancels
    publish with request_tag=null.
    """
    cancel_reason: OrderCancelledCancelReason | None = Field(default=None)
    """Why the exchange cancelled this order, when the exchange decided it rather
    than the client. Null for a client-requested cancel, and for engine-initiated
    cancels whose cause is not yet classified - so request_tag=null together with
    cancel_reason=null still means "the exchange did this, cause unstated".
    Deliberately not the same vocabulary as order_ack.reject_code: a cancel is not
    a rejection, and most reject codes can never apply to one. New members may be
    added; existing members are never removed or renamed. A client must ignore a
    value it does not recognise.
    """
    oco_group_id: str | None = Field(default=None, max_length=64)
    combo_parent_id: str | None = Field(default=None, max_length=64)
    quote_id: str | None = Field(default=None, max_length=64)
    leg_index: int | None = Field(default=None)
    command_id: str | None = Field(default=None, max_length=64)
    """The admin/kill-switch command_id (see system.admin_action) that caused this
    cancel, when one exists — lets a post-mortem join this event back to the exact
    command that triggered it. Null for a client-requested cancel and for engine-
    initiated cancels with no originating command (e.g. self-match prevention,
    insufficient liquidity, a quote leg cancelled because its sibling filled).
    """
    remaining_qty: int | None = Field(default=None, ge=0)
    """Quantity left unfilled when the order was cancelled. Unit: shares."""
    cum_qty: int | None = Field(default=None, ge=0)
    """Quantity the order had filled before it was cancelled. Unit: shares."""


class OrderExpired(BaseModel):
    """A DAY order that never filled has expired at session end. Same shape as
    order.cancelled - the difference is who ended the order, not what the consumer
    needs to know about it.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    symbol: str | None = Field(default=None, max_length=16)
    """Instrument this order belonged to. Same AR-0.2 rationale as
    order.cancelled.symbol above - the engine already has it at the publish site,
    it was simply never carried.
    """
    client_tag: str | None = Field(default=None, max_length=64)
    oco_group_id: str | None = Field(default=None, max_length=64)
    combo_parent_id: str | None = Field(default=None, max_length=64)
    quote_id: str | None = Field(default=None, max_length=64)
    leg_index: int | None = Field(default=None)
    remaining_qty: int | None = Field(default=None, ge=0)
    """Quantity left unfilled when the order expired. Unit: shares."""
    cum_qty: int | None = Field(default=None, ge=0)
    """Quantity the order had filled before it expired. Unit: shares."""


class OrderTriggered(BaseModel):
    """A stop, stop-limit or trailing stop has fired: the trade that reached its
    trigger, and what the order became. Published before the order's own fills, so
    a client knows why its stop traded -- the FIX analogue is ExecType=L.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    symbol: str = Field(max_length=16)
    order_type: OrderTriggeredOrderType
    """The order as it was armed."""
    stop_price_ticks: int
    """The trigger price it fired at (a trailing stop's ratcheted one). Unit: ticks."""
    trigger_trade_id: str | None = Field(default=None, max_length=64)
    """The trade that reached the trigger; absent when the last price came from a
    restart.
    """
    trigger_price_ticks: int | None = Field(default=None)
    """That trade's price. Unit: ticks."""
    becomes: OrderTriggeredBecomes
    """STOP and TRAILING_STOP become MARKET; STOP_LIMIT becomes LIMIT at its limit."""
    client_tag: str | None = Field(default=None, max_length=64)


class EngineTrace(BaseModel):
    """What the book did that no trade or order message shows, for the audit trail
    (no gateway forwards it): an order resting or arming and the place in the
    queue it got, an iceberg refilling its slice at the back of its level, a
    trailing stop ratcheting its trigger. A replay can then compare its model of
    priority and of trailing triggers with the engine's own, instead of inferring
    them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    kind: EngineTraceKind
    order_id: str = Field(max_length=64)
    priority_seq: int | None = Field(default=None, ge=0)
    displayed_qty: int | None = Field(default=None, ge=0)
    """ICEBERG_REFILL: the new visible slice. Unit: shares."""
    stop_price_ticks: int | None = Field(default=None)
    """TRAILING_RATCHET: the new trigger. Unit: ticks."""
    last_price_ticks: int | None = Field(default=None)
    """TRAILING_RATCHET: the trade price that moved it. Unit: ticks."""


class OrderAmended(BaseModel):
    """Confirm an accepted amendment and report the resulting order."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    symbol: str | None = Field(default=None, max_length=16)
    """Instrument this order belonged to. Same AR-0.2 rationale as
    order.cancelled.symbol above - the engine already has it at the publish site,
    it was simply never carried.
    """
    price: float | None
    """New limit price, or null for an order that has none. Unit: display_price."""
    qty: int
    """Unit: shares."""
    remaining_qty: int
    """Unit: shares."""
    priority_reset: bool
    """True when the amendment lost the order its time priority."""
    old_price: float | None = Field(default=None)
    """The order's limit price immediately before this amendment, or null for an
    order that had none. Lets a post-mortem replay the amend without re-deriving
    the prior state from an earlier message. Absent on records written before this
    field existed. Unit: display_price.
    """
    old_qty: int | None = Field(default=None)
    """The order's qty immediately before this amendment. Same replay rationale as
    old_price; absent on records written before this field existed. Unit: shares.
    """
    client_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for the amended order."""
    request_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this amend request. Engine-initiated cancels
    publish with request_tag=null.
    """
    price_ticks: int | None = Field(default=None)
    """`price` in engine ticks. Canonical; the float beside it is for display. Scale:
    the symbol's tick_decimals. Unit: ticks.
    """
    priority_seq: int | None = Field(default=None, ge=0)
    """The order's place in its book after the amendment (the book's arrival
    sequence): changed when `priority_reset`.
    """


class OrderNew(BaseModel):
    """Submit a new order to the matching engine. Sent over PUSH/PULL rather than the
    pub bus, but it carries a topic so the audit log can classify it alongside
    everything else.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=64)
    """Engine order id; a UUID string."""
    symbol: str = Field(max_length=16)
    side: OrderNewSide
    order_type: OrderNewOrderType
    tif: OrderNewTif
    quantity: int = Field(gt=0)
    """Total original quantity. Unit: shares."""
    remaining_qty: int = Field(ge=0)
    """Quantity yet to be filled; equals quantity on submission. Unit: shares."""
    gateway_id: str = Field(max_length=32)
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for every `_ticks` field below; 1 tick = 10^-tick_decimals.
    Carried so a reader can turn a tick price into money from this message alone.
    Without it the scale has to be recovered from a `book` or `trade.executed` for
    the same symbol, which a reader of a *window* of the audit trail may not have
    - the snapshot that declared it is usually at session start, hours outside the
    window being read.
    """
    trail_offset_ticks: int | None
    """TRAILING_STOP: fixed distance to trail the market price. Unit: ticks."""
    oco_group_id: str | None = Field(max_length=64)
    ts_ns: int = Field(ge=0)
    """Client-supplied submission time. NOT what the book uses for time priority -
    see arrival_seq. BALF has no timestamp field on NEW_ORDER, so balf_gwy stamps
    one at ingress. Unit: epoch_nanos.
    """
    status: OrderNewStatus
    """Always NEW on submission; the enum is the full lifecycle."""
    price_ticks: int | None
    """Limit price in ticks. Null for MARKET, which has none. Unit: ticks."""
    stop_price_ticks: int | None
    """STOP / STOP_LIMIT / TRAILING_STOP trigger. Unit: ticks."""
    visible_qty: int | None
    """ICEBERG: fixed peak size. Unit: shares."""
    displayed_qty: int | None
    """ICEBERG: current visible slice on the book. Unit: shares."""
    smp_action: OrderNewSmpAction | None
    """Self-match prevention. Null means the client did not specify SMP at all, which
    is distinct from an explicit NONE: the engine resolves null to the gateway's
    configured default. See SmpAction's docstring.
    """
    combo_parent_id: str | None = Field(max_length=64)
    leg_index: int | None
    """Position in the parent combo's legs, 0-based."""
    origin: OrderNewOrigin
    """Defaulted rather than nullable: from_dict supplies ORDER."""
    is_seed: bool
    """True when this order was created by config-driven startup seeding rather than
    a live gateway submission. See OrderDisplay.is_seed for the full rationale.
    """
    quote_id: str | None = Field(max_length=64)
    client_tag: str | None = Field(max_length=64)
    """Client correlation tag, echoed on every lifecycle event."""
    arrival_seq: int
    """Engine-assigned monotonic arrival sequence; time priority is keyed on this,
    not on timestamp, so a back-dated payload cannot jump the queue. Zero means
    unassigned, which is what a submission carries.
    """


class OrderCancel(BaseModel):
    """Request cancellation of one resting order by id."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)
    request_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this cancel request, echoed on the resulting
    cancellation event or rejection.
    """


class OrderAmend(BaseModel):
    """Request a price and/or quantity change to a resting order."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)
    price: float | None = Field(default=None)
    """New limit price; absent means the price is unchanged. Unit: display_price."""
    qty: int | None = Field(default=None)
    """New quantity; absent means the quantity is unchanged. Unit: shares."""
    request_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this amend request, echoed on the resulting
    amendment event or rejection.
    """


class OrderComboCancel(BaseModel):
    """Cancel a combo order and all of its resting child legs."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    combo_id: str = Field(max_length=64)
    """Client-supplied combo label, not the internal UUID."""
    gateway_id: str = Field(max_length=32)
    request_tag: str | None = Field(default=None, max_length=64)
    """Echoed on combo.cancel_ack, so the caller can attribute the outcome."""


class OrderCombo(BaseModel):
    """Submit a combo: two or more orders on different instruments that the engine
    posts together and tracks as one aggregate.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    combo_id: str = Field(max_length=64)
    """Client-supplied tracking label, not the engine's internal id."""
    gateway_id: str = Field(max_length=32)
    combo_type: OrderComboComboType
    """All-or-none: the combo completes only when every leg fills."""
    tif: OrderComboTif
    legs: list[ComboLeg] = Field(min_length=2, max_length=10)
    """The child orders. The bounds below were previously enforced only by
    api_gateway's pydantic schema, which left the ALF console and gateway free to
    submit a one-legged combo.
    """
    client_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this combo submission."""


class OrderOco(BaseModel):
    """Submit a One-Cancels-Other pair: two orders on the same instrument, of which a
    fill on either cancels the other.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    oco_id: str = Field(max_length=64)
    """Client-supplied label for the pair, unique among the gateway's live pairs: a
    submit reusing one is refused. Free again once the pair is done.
    """
    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    """Both legs trade this instrument."""
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for both legs' `_ticks` prices; 1 tick = 10^-tick_decimals. One
    value for the pair rather than one per leg, because both legs trade the
    instrument named above.
    """
    quantity: int
    """Size of each leg; they are equal by construction. Unit: shares."""
    tif: OrderOcoTif
    leg1: OcoLeg
    leg2: OcoLeg
    client_tag: str | None = Field(default=None, max_length=64)
    """Client correlation tag for this OCO submission."""


class OrderOcoCancel(BaseModel):
    """Cancel an OCO pair and both of its legs."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    oco_id: str = Field(max_length=64)
    """Client-supplied OCO label. Names a pair of the sending gateway only."""
    gateway_id: str = Field(max_length=32)
    request_tag: str | None = Field(default=None, max_length=64)
    """Echoed on oco.cancel_ack, so the caller can attribute the outcome."""


class OrdersRequest(BaseModel):
    """Caller to engine: the resting (unfilled, non-cancelled) orders a gateway
    currently has on the books, across all symbols.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Whose resting orders to return, and the reply's correlation key."""


class Orders(BaseModel):
    """Engine to caller: the gateway's resting orders in display units, one
    OrderDisplay record each. Empty when the gateway is unknown or flat.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    orders: list[OrderDisplay]
    """Resting orders, as the engine iterates its books."""


class PriceLevelOrdersRequest(BaseModel):
    """ADMIN to engine: every resting order for one symbol, across every gateway,
    optionally narrowed to a single price level. Rejected for any non-ADMIN
    participant (see order.price_level_orders' rejection note) since it exposes
    other participants' resting order detail that order.orders_request
    deliberately withholds.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """The ADMIN participant asking, and the reply's correlation key — not a filter
    on whose orders come back.
    """
    symbol: str = Field(max_length=16)
    """Instrument to inspect."""
    price: float | None = Field(default=None)
    """Narrow to orders resting at exactly this price. Omitted or null returns every
    resting order for the symbol, across all price levels. Unit: display_price.
    """


class PriceLevelOrders(BaseModel):
    """Engine to ADMIN caller: per-order detail (not just the aggregate {price, qty,
    count} book.* already carries) for every resting order matching the request —
    every gateway, ordered by price then by arrival_seq within a price level so
    time priority is visible. Empty, with rejected=true and a reason, when the
    requester is not an ADMIN participant or the symbol is unknown.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    price: float | None = Field(default=None)
    """Echoed from the request when it filtered to one level; omitted when the
    request asked for the whole symbol. Unit: display_price.
    """
    rejected: bool
    """True when the requester was not ADMIN or the symbol is unknown; orders is then
    always empty.
    """
    reason: str | None = Field(default=None, max_length=256)
    """Set only when rejected is true."""
    orders: list[PriceLevelOrder]
    """Matching resting orders, ordered by price then arrival_seq — empty when
    rejected, or when nothing rests at the requested level.
    """
