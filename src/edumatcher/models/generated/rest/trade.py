# GENERATED FROM spec/messages/trade.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``trade`` message family.

Family version 1. Derived from ``spec/messages/trade.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TradeExecutedMatchType = Literal[
    "CONTINUOUS",
    "OPENING_AUCTION",
    "CLOSING_AUCTION",
    "REOPEN_AUCTION",
    "RECOVERY_AUCTION",
    "BACKSTOP",
    "FORCE_UNCROSS",
]


class TradeExecuted(BaseModel):
    """Public print of a completed match. The authoritative record of what traded,
    consumed by statistics, clearing, index and market data.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=64, pattern="^\\d{6}-\\d{9}$")
    """Durable, sortable trade id. The prefix is the persisted engine-run sequence
    and the suffix is the per-run trade counter.
    """
    run_seq: int = Field(ge=0)
    """Durable engine-run sequence used as the trade id prefix. A change in run_seq
    marks an engine restart explicitly for consumers.
    """
    symbol: str = Field(max_length=16, pattern="^[A-Z0-9._]+$")
    """Instrument the match occurred in."""
    buy_order_id: str = Field(max_length=64)
    """Resting or aggressing order id on the buy side."""
    sell_order_id: str = Field(max_length=64)
    """Resting or aggressing order id on the sell side."""
    buy_gateway_id: str = Field(max_length=32)
    """Gateway that submitted the buy order."""
    sell_gateway_id: str = Field(max_length=32)
    """Gateway that submitted the sell order."""
    price: float = Field(gt=0)
    """Execution price in display money, already converted from ticks by the
    publisher. Contrast trade_log.price, which is ticks - the mismatch this `unit`
    declaration exists to make reviewable. Unit: display_price.
    """
    quantity: int = Field(gt=0)
    """Matched quantity. Unit: shares."""
    aggressor_side: str
    """Side that removed liquidity. AUCTION when both sides rested, which happens on
    an uncross print where there is no true aggressor.
    """
    ts_ns: int = Field(ge=0)
    """Match time in Unix epoch nanoseconds, exactly as the engine's clock read it --
    no scaling at publish time. The whole match batch shares one clock read, so
    trades printed in the same batch carry an identical value; `id` (run_seq +
    dense counter) is what orders them. Named `ts_ns` rather than `timestamp` so
    the unit travels with the field, as it does for `resume_at_ns` and
    `halt_duration_ns`: a bare float `timestamp` was indistinguishable by type
    from millis or nanos, which is what forced clearing's magnitude-guessing guard
    (finding CL-M6) and cost ~238ns of the engine's own precision. Unit:
    epoch_nanos.
    """
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for `price`; 1 tick = 10^-tick_decimals."""
    price_ticks: int | None = Field(default=None)
    """`price` in engine ticks. Canonical; the float beside it is for display. Scale:
    the symbol's tick_decimals. Unit: ticks.
    """
    match_type: TradeExecutedMatchType | None = Field(default=None)
    """How the trade came about; the engine sets it on every trade (absent only on
    prints from before it existed). CONTINUOUS for every match with an aggressor
    (a stop an uncross triggers included); an uncross print (aggressor_side
    AUCTION) names its uncross: the scheduled opening or closing auction, a halted
    symbol's reopening, the restore of a crossed book on an engine without
    sessions, the closing backstop, or an operator's forced uncross.
    """
    auction_id: str | None = Field(default=None, max_length=32)
    """The uncross this print belongs to: `auction.result.auction_id`."""
    trigger_order_id: str | None = Field(default=None, max_length=64)
    """The aggressor's order id when the aggressor is a stop that has triggered;
    absent otherwise.
    """
