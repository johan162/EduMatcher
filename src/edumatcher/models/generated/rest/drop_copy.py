# GENERATED FROM spec/messages/drop_copy.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``drop_copy`` message family.

Family version 1. Derived from ``spec/messages/drop_copy.yaml`` by the rest emitter;
edit the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DropCopyEventEventType = Literal["order.fill"]
DropCopyEventLiquidityFlag = Literal["MAKER", "TAKER"]
DropCopyReplayEventType = Literal["order.fill"]
DropCopyReplayLiquidityFlag = Literal["MAKER", "TAKER"]


class DropCopyEvent(BaseModel):
    """Engine to a participant's clearing broker, prime broker or in-house risk
    system: one execution, as it happens.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    seq: int = Field(gt=0)
    """Process-wide monotone counter, starting at 1 so that 0 can mean "no events
    yet". Never resets while the engine lives. A recipient detects loss from a gap
    and a duplicate from a repeat, which is the whole reason the feed is
    sequenced.
    """
    timestamp: int
    """When the engine published the event (`models/clock.py::now_ns`). Unit:
    epoch_nanos.
    """
    gateway_id: str = Field(max_length=32)
    """The participant whose order executed. Carried in the body as well as in the
    topic, because `drop_copy.replay` names the *recipient* in its topic instead
    and a replayed event would otherwise not say whose fill it was.
    """
    event_type: DropCopyEventEventType
    """One value today. An enum rather than a free string so that a second event type
    is a spec change with a regenerated binding, rather than a new dict key no
    reader knows about -- `DropCopyPublisher`'s own docstring promised "every fill
    and cancel" while only fills existed, which is how the gap went unnoticed.
    Section 27.3.
    """
    order_id: str = Field(max_length=64)
    """The resting or aggressing order this execution belongs to."""
    trade_ids: list[str] = Field(min_length=1)
    """Public trade.executed id(s) for this execution. One ID today; kept as a list
    so consumers can use the same representation as coalesced order.fill messages
    when an order sweeps multiple price levels.
    """
    symbol: str = Field(max_length=16)
    fill_qty: int = Field(gt=0)
    """Unit: shares."""
    fill_price: float = Field(gt=0)
    """Display money, not ticks -- converted once in `_publish_trade`. Unit:
    display_price.
    """
    liquidity_flag: DropCopyEventLiquidityFlag
    """Derived from the trade's aggressor side: the aggressor is the TAKER and the
    resting side the MAKER. Exactly one of the two events a trade produces is
    TAKER.
    """


class DropCopyReplay(BaseModel):
    """Engine to one named recipient: buffered events re-published on request, so a
    participant that reconnects mid-session can close its sequence gap.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    seq: int = Field(gt=0)
    timestamp: int
    """Unit: epoch_nanos."""
    gateway_id: str = Field(max_length=32)
    """Whose fill this was — not the recipient the topic names."""
    event_type: DropCopyReplayEventType
    order_id: str = Field(max_length=64)
    trade_ids: list[str] = Field(min_length=1)
    symbol: str = Field(max_length=16)
    fill_qty: int = Field(gt=0)
    """Unit: shares."""
    fill_price: float = Field(gt=0)
    """Unit: display_price."""
    liquidity_flag: DropCopyReplayLiquidityFlag
