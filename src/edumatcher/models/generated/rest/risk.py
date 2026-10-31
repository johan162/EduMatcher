# GENERATED FROM spec/messages/risk.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``risk`` message family.

Family version 1. Derived from ``spec/messages/risk.yaml`` by the rest emitter; edit the
spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BandKind = Literal["COLLAR"]
ForceUncrossAckImbalanceSide = Literal["BUY", "SELL"]


class KillSwitch(BaseModel):
    """Gateway or admin to engine: cancel a gateway's open risk-bearing exposure. The
    gateway is NOT halted - it may submit again as soon as the ack arrives.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    """Scope to one instrument; "" cancels across all of them."""
    note: str | None = Field(default=None, max_length=256)
    """Free-text reason, recorded on the admin monitor."""
    command_id: str | None = Field(default=None, max_length=64)
    """Echoed on the ack. A kill-switch ack carries no natural identifier - unlike
    the symbol acks, which carry `symbol` - so without this two concurrent mass
    cancels for one gateway are indistinguishable once both acks are in flight.
    """


class KillSwitchAck(BaseModel):
    """Engine to caller: what the kill switch cancelled."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    cancelled_orders: int = Field(ge=0)
    cancelled_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_orders, so a caller can tell which
    orders were hit rather than only how many. A list whose length disagrees with
    cancelled_orders is itself a detectable defect.
    """
    cancelled_quotes: int = Field(ge=0)
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """
    command_id: str | None = Field(default=None, max_length=64)


class KillSwitchGateway(BaseModel):
    """ADMIN to engine: cancel every order and quote belonging to one named
    participant.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """The ADMIN caller; the ack is addressed to this id."""
    target_gateway_id: str = Field(max_length=32)
    """Whose orders and quotes are cancelled."""
    symbol: str | None = Field(default=None, max_length=16)
    """Scope the cancel to one instrument; omitted cancels across all."""
    quotes_only: bool
    """Cancel only the target's quotes, leaving its other resting orders. With
    `symbol`, this is an admin pulling one market maker's quote on one instrument
    -- through this ADMIN message rather than by sending the participant's own
    quote.cancel, which would put the target's name on the audit trail and fail
    while it is disconnected.
    """
    note: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=64)


class KillSwitchGatewayAck(BaseModel):
    """Engine to ADMIN: what the gateway-targeted kill switch cancelled."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    target_gateway_id: str = Field(max_length=32)
    symbol: str | None = Field(default=None, max_length=16)
    """Echoed when the cancel was scoped."""
    quotes_only: bool
    """Echoed: whether only quotes were cancelled."""
    reason: str = Field(max_length=512)
    cancelled_orders: int = Field(ge=0)
    cancelled_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_orders, so a caller can tell which
    orders were hit rather than only how many. A list whose length disagrees with
    cancelled_orders is itself a detectable defect.
    """
    cancelled_quotes: int = Field(ge=0)
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """
    command_id: str | None = Field(default=None, max_length=64)


class KillSwitchGlobal(BaseModel):
    """ADMIN to engine: cancel every resting order and quote, for every gateway. The
    full-market emergency stop.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """The ADMIN caller; the ack is addressed to this id."""
    note: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=64)


class KillSwitchGlobalAck(BaseModel):
    """Engine to ADMIN: what the market-wide kill switch cancelled."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    cancelled_orders: int = Field(ge=0)
    cancelled_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_orders, so a caller can tell which
    orders were hit rather than only how many. A list whose length disagrees with
    cancelled_orders is itself a detectable defect.
    """
    cancelled_quotes: int = Field(ge=0)
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """
    affected_gateways: int = Field(ge=0)
    affected_gateway_ids: list[str]
    """AR-0.5: the gateway ids counted in affected_gateways — every gateway that had
    at least one order or quote leg cancelled by this sweep.
    """
    command_id: str | None = Field(default=None, max_length=64)


class Band(BaseModel):
    """A symbol's collar, as the engine will apply it: published once per collared
    symbol at startup (a reference reload leaves collars as they are). The static
    band is fixed from these; the dynamic band is `dynamic_band_pct` around each
    last trade price, so a reader derives it from the trades rather than from a
    message per trade. Circuit-breaker corridors travel on
    circuit_breaker.halt/extend.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    kind: BandKind
    reference_price_ticks: int
    """The static band's reference (last close or the config seed). Unit: ticks."""
    static_low_ticks: int
    """Unit: ticks."""
    static_high_ticks: int
    """Unit: ticks."""
    dynamic_band_pct: float = Field(ge=0)
    """The dynamic band's half-width as a fraction of the last trade price (0.02 = 2
    %).
    """


class SymbolHalt(BaseModel):
    """ADMIN to engine: halt trading on one instrument."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    level: str | None = Field(default=None, max_length=32)
    """A configured circuit-breaker level; omitted halts indefinitely."""
    note: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=64)


class SymbolHaltAck(BaseModel):
    """Engine to ADMIN: the per-symbol halt's outcome."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    symbol: str = Field(max_length=16)
    reason: str = Field(max_length=512)
    cancelled_quotes: int = Field(ge=0)
    """Quotes pulled because the instrument stopped trading."""
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """
    command_id: str | None = Field(default=None, max_length=64)


class SymbolResume(BaseModel):
    """ADMIN to engine: resume trading on one halted instrument."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    note: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=64)


class SymbolResumeAck(BaseModel):
    """Engine to ADMIN: the per-symbol resume's outcome."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    symbol: str = Field(max_length=16)
    reason: str = Field(max_length=512)
    command_id: str | None = Field(default=None, max_length=64)


class CancelSymbol(BaseModel):
    """ADMIN to engine: cancel every resting order for one instrument, across every
    gateway.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    note: str | None = Field(default=None, max_length=256)
    command_id: str | None = Field(default=None, max_length=64)


class CancelSymbolAck(BaseModel):
    """Engine to ADMIN: what the symbol-wide mass cancel removed."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    symbol: str = Field(max_length=16)
    reason: str = Field(max_length=512)
    cancelled_orders: int = Field(ge=0)
    cancelled_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_orders, so a caller can tell which
    orders were hit rather than only how many. A list whose length disagrees with
    cancelled_orders is itself a detectable defect.
    """
    cancelled_quotes: int = Field(ge=0)
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """
    command_id: str | None = Field(default=None, max_length=64)


class ForceUncross(BaseModel):
    """ADMIN to engine: force one symbol to uncross now, optionally asserting the
    print price, and clear any halt in the same step. The operational recovery for
    an auction that failed to discover a price - see risk.cancel_symbol for the
    "abandon and re-collect" alternative.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    price: float | None = Field(default=None, gt=0)
    """Operator print price; null opens at the computed equilibrium. Unit:
    display_price.
    """
    dry_run: bool
    """Peek the indicative print without changing any state."""
    note: str | None = Field(default=None, max_length=256)
    """Free-text reason, recorded on the admin monitor."""
    command_id: str | None = Field(default=None, max_length=64)


class ForceUncrossAck(BaseModel):
    """Engine to ADMIN: the outcome of a force-uncross. On a dry run it carries the
    indicative figures only; on a live run it also reports what actually printed.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    symbol: str = Field(max_length=16)
    reason: str = Field(max_length=512)
    dry_run: bool
    """True when this ack answers a peek rather than a live uncross."""
    indicative_price: float | None = Field(gt=0)
    """Indicative equilibrium, or null if the book would not cross. Unit:
    display_price.
    """
    indicative_qty: int = Field(ge=0)
    """Quantity that would execute at the indicative price. Unit: shares."""
    surplus: int = Field(ge=0)
    """Surplus on `imbalance_side`; zero when balanced. Unit: shares."""
    imbalance_side: ForceUncrossAckImbalanceSide | None = Field(default=None)
    """Which side would be left unfilled; absent when balanced."""
    printed_price: float | None = Field(gt=0)
    """Live-run print price, or null on a dry run or rejection. Unit: display_price."""
    traded_qty: int = Field(ge=0)
    """Quantity that actually executed on a live run. Unit: shares."""
    command_id: str | None = Field(default=None, max_length=64)


class CircuitBreakerHaltAll(BaseModel):
    """ADMIN to engine: halt trading on every known symbol."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class CircuitBreakerHaltAllAck(BaseModel):
    """Engine to ADMIN: how wide the market-wide halt reached."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    halted_symbols: int = Field(ge=0)
    halted_symbol_ids: list[str]
    """AR-0.5: the symbols counted in halted_symbols, by name."""
    cancelled_quotes: int = Field(ge=0)
    cancelled_quote_order_ids: list[str]
    """AR-0.5: the order ids counted in cancelled_quotes. Named "*_order_ids" rather
    than "*_quote_ids" on purpose: cancelled_quotes has always counted cancelled
    quote LEGS, each an independent Order with its own order_id, not quote objects
    — a quote's own quote_id is client-supplied and optional (see quote.yaml), so
    it cannot serve as this list's key even when present.
    """


class CircuitBreakerResumeAll(BaseModel):
    """ADMIN to engine: resume every symbol halted by the market-wide halt."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class CircuitBreakerResumeAllAck(BaseModel):
    """Engine to ADMIN: how many symbols came back."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    resumed_symbols: int = Field(ge=0)
    resumed_symbol_ids: list[str]
    """AR-0.5: the symbols counted in resumed_symbols, by name."""
