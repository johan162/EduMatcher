# GENERATED FROM spec/messages/quote.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``quote`` message family.

Family version 1. Derived from ``spec/messages/quote.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QuoteNewTif = Literal["DAY", "GTC", "ATO", "ATC"]
QuoteStatusStatus = Literal[
    "ACTIVE",
    "INACTIVE_BID_FILLED",
    "INACTIVE_ASK_FILLED",
    "CANCELLED",
]


class QuoteNew(BaseModel):
    """Market maker to engine: submit or replace a two-sided quote on one instrument.
    A quote is a bid and an ask posted as a pair; replacing one cancels the
    previous pair for that gateway and symbol.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for both `_ticks` prices; 1 tick = 10^-tick_decimals. Carried so
    a reader can turn a tick price into money from this message alone, rather than
    recovering the scale from a `book` for the same symbol that may be outside the
    window being read.
    """
    bid_price_ticks: int = Field(gt=0)
    """Unit: ticks."""
    bid_qty: int = Field(gt=0)
    """Unit: shares."""
    ask_price_ticks: int = Field(gt=0)
    """Unit: ticks."""
    ask_qty: int = Field(gt=0)
    """Unit: shares."""
    tif: QuoteNewTif
    """Applies to both legs; the engine reads it once. Same four values as
    models/order.py::TIF and order.combo's own tif - a quote's legs are ordinary
    orders once they rest.
    """
    quote_id: str | None = Field(default=None, max_length=64)


class QuoteCancel(BaseModel):
    """Market maker to engine: pull the active quote on one symbol."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    request_tag: str | None = Field(default=None, max_length=64)
    """Echoed on quote.cancel_ack, so the caller can attribute the outcome."""


class QuoteAck(BaseModel):
    """Engine to market maker: the quote was accepted or rejected."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_id: str = Field(max_length=64)
    accepted: bool
    symbol: str = Field(max_length=16)
    """Instrument the quote was for. `order.ack` has always carried this; `quote.ack`
    did not, which left every market-making client to work out for itself which
    symbol an ack belonged to -- the topic is per-gateway, not per-symbol. Empty
    only on a rejection raised before the symbol was known (a malformed payload,
    or a missing SYM).
    """
    reason: str = Field(max_length=512)
    bid_order_id: str = Field(max_length=64)
    ask_order_id: str = Field(max_length=64)


class QuoteStatus(BaseModel):
    """Engine to market maker: the quote left the book, and why."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_id: str = Field(max_length=64)
    status: QuoteStatusStatus
    """Mirrors models/quote.py::QuoteState."""
    reason: str = Field(max_length=512)
    command_id: str | None = Field(default=None, max_length=64)
    """The admin/kill-switch command_id (see system.admin_action) that caused this
    quote to leave the book, when one exists — same correlation purpose as
    order.cancelled.command_id. Null when the quote left for a reason with no
    originating command (participant cancel, replacement by a new quote, a leg
    fill).
    """


class QuoteCancelAck(BaseModel):
    """Engine to market maker: the outcome of a quote.cancel."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    quote_id: str = Field(max_length=64)
    """The withdrawn quote's id; "" when there was none."""
    accepted: bool
    reason: str = Field(max_length=512)
    reject_code: str | None = Field(default=None, max_length=32)
    """On a refusal, a member of order.ack's `reject_code` vocabulary
    (ORDER_NOT_FOUND, ORDER_ALREADY_TERMINAL, GATEWAY_NOT_CONFIGURED,
    AUTH_REQUIRED); absent when accepted. A string rather than that enum only
    because the IDL has no shared enum type: the engine is held to the vocabulary
    by tests/test_engine_structure_cancel_acks.py.
    """
    request_tag: str | None = Field(default=None, max_length=64)
    """Echoed from the cancel request, so the caller can attribute the outcome."""
    cancelled_order_ids: list[str]
    """The engine order ids the cancel removed; empty on a refusal."""
