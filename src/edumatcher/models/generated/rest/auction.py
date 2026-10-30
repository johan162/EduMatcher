# GENERATED FROM spec/messages/auction.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``auction`` message family.

Family version 1. Derived from ``spec/messages/auction.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AuctionIndicativePhase = Literal["OPENING_AUCTION", "CLOSING_AUCTION"]
AuctionIndicativeImbalanceSide = Literal["BUY", "SELL"]
AuctionResultImbalanceSide = Literal["BUY", "SELL"]
AuctionResultReason = Literal[
    "SCHEDULED",
    "REOPEN",
    "RECOVERY",
    "BACKSTOP",
    "ADMIN_MANUAL",
]


class AuctionIndicative(BaseModel):
    """Engine to all: where one symbol would uncross if the call phase ended now.
    Published repeatedly while an opening or closing auction collects orders.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    phase: AuctionIndicativePhase
    """Which call phase is running. These are the only two states
    `models/session.py::is_auction_phase` admits, and the producer returns early
    for every other one.
    """
    eq_price: float | None = Field(gt=0)
    """Indicative equilibrium price, or null if the book would not cross. Unit:
    display_price.
    """
    eq_qty: int = Field(ge=0)
    """Quantity that would execute. Zero is a true reading and is always emitted,
    unlike `eq_price`, which has no zero. Unit: shares.
    """
    imbalance_side: AuctionIndicativeImbalanceSide | None = Field(default=None)
    """Which side would be left unfilled. Absent when the book is balanced at the
    indicative price.
    """
    imbalance_qty: int = Field(ge=0)
    """Surplus on `imbalance_side`; zero when balanced. Unit: shares."""
    eq_price_ticks: int | None = Field(default=None)
    """`eq_price` in engine ticks. Canonical; the float beside it is for display.
    Scale: the symbol's tick_decimals. Unit: ticks.
    """


class AuctionResult(BaseModel):
    """Engine to all: one symbol's uncross has completed. Published for every
    uncross, including the ones that printed nothing.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    eq_price: float | None = Field(gt=0)
    """Uncross price, or null when there was no crossable interest. Unit:
    display_price.
    """
    eq_qty: int = Field(ge=0)
    """Quantity executed; zero when nothing crossed. Unit: shares."""
    trades_count: int = Field(ge=0)
    """How many trades the uncross printed."""
    imbalance_side: AuctionResultImbalanceSide | None = Field(default=None)
    """Which side was left unfilled. Absent when the book was balanced at the uncross
    price.
    """
    imbalance_qty: int = Field(ge=0)
    """Surplus on `imbalance_side`; zero when balanced. Unit: shares."""
    reason: AuctionResultReason
    """Which of the five uncross paths produced this event."""
    eq_price_ticks: int | None = Field(default=None)
    """`eq_price` in engine ticks. Canonical; the float beside it is for display.
    Scale: the symbol's tick_decimals. Unit: ticks.
    """
    auction_id: str | None = Field(default=None, max_length=32)
    """This uncross, `AUC-<run_seq>-<n>`: every print it made carries it as
    `trade.executed.auction_id`.
    """
