# GENERATED FROM spec/messages/book.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``book`` message family.

Family version 1. Derived from ``spec/messages/book.yaml`` by the rest emitter; edit the
spec, not this file.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BookLevel(BaseModel):
    """One aggregated price level. Iceberg orders contribute only their displayed
    quantity, so `qty` is what a viewer should show rather than what is actually
    resting.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    price: float
    """Unit: display_price."""
    qty: int
    """Aggregate visible size at this level. Unit: shares."""
    count: int
    """How many orders make up the level."""


class RecentTrade(BaseModel):
    """One entry of the book's trade tape. A trimmed view of the public
    trade.executed print - the last five, carried with the snapshot so a viewer
    that has just subscribed has some history to draw.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=64)
    symbol: str = Field(max_length=16)
    buy_order_id: str = Field(max_length=64)
    sell_order_id: str = Field(max_length=64)
    buy_gateway_id: str = Field(max_length=32)
    sell_gateway_id: str = Field(max_length=32)
    price: float
    """Unit: display_price."""
    quantity: int
    """Unit: shares."""
    ts_ns: int = Field(ge=0)
    """Epoch nanoseconds, carried through unscaled -- identical to the trade.executed
    print this row mirrors. Unit: epoch_nanos.
    """


class BookSnapshot(BaseModel):
    """Broadcast an aggregated view of one instrument's order book, on a timer. What
    every viewer and terminal renders.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    tick_decimals: int
    """The tick scale the display prices here were produced at. Subscribers that
    store prices exactly need it to convert back to integer ticks; without it they
    must guess, and guessing 2 for a 4-decimal symbol rounds the price away.
    """
    ts_ns: int = Field(ge=0)
    """When this snapshot was produced (AR-0.4). Previously book.{symbol} carried no
    time field at all, so nothing could establish whether a snapshot reflects a
    given trade; ordering against trade.executed.ts_ns (and recent_trades[].ts_ns,
    which this mirrors) was impossible. Monotonic per
    edumatcher.models.clock.now_ns(). Unit: epoch_nanos.
    """
    bids: list[BookLevel]
    """Descending by price."""
    asks: list[BookLevel]
    """Ascending by price."""
    last_price: float | None
    """Null until the instrument has traded. Unit: display_price."""
    last_qty: int | None
    """Unit: shares."""
    last_buy_price: float | None
    """Unit: display_price."""
    last_sell_price: float | None
    """Unit: display_price."""
    recent_trades: list[RecentTrade]
    """The last five prints, oldest first."""


class BookSnapshotRequest(BaseModel):
    """Ask the engine to publish one symbol's book immediately."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)


class Depth(BaseModel):
    """Book-depth metrics within a tolerance band of the last trade: how much size
    sits nearby, which way it leans, and what it costs to move.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    ts_ns: int = Field(ge=0)
    """When this depth snapshot was produced (AR-0.4). Previously depth.{symbol}
    carried no time field at all. Monotonic per edumatcher.models.clock.now_ns().
    Unit: epoch_nanos.
    """
    tick_decimals: int = Field(ge=0, le=8)
    """Decimal scale for the `_ticks` fields below; 1 tick = 10^-tick_decimals. Same
    field, same name and same meaning as `book.tick_decimals`.
    """
    mid_price_ticks: int
    """The last trade price, in ticks; the band is centred here. Unit: ticks."""
    mid_price: float
    """Unit: display_price."""
    tolerance_ticks: int
    """Half-width of the band, in ticks. Unit: ticks."""
    bid_depth: int
    """Total resting size between mid - tolerance and mid. Unit: shares."""
    ask_depth: int
    """Total resting size between mid and mid + tolerance. Unit: shares."""
    imbalance: float = Field(ge=-1, le=1)
    """(bid - ask) / total, in [-1, 1]; positive means more bids."""
    microprice: float
    """Imbalance-weighted mid; falls back to mid_price. Unit: display_price."""
    cost_to_move: float
    """Display notional a buyer must spend to sweep every ask in the band. Summed in
    ticks and converted once, not per level. Unit: money.
    """
