# GENERATED FROM spec/messages/circuit_breaker.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``circuit_breaker`` message family.

Family version 1. Derived from ``spec/messages/circuit_breaker.yaml`` by the rest
emitter; edit the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CircuitBreakerHaltHaltSource = Literal["CB", "ADMIN"]
CircuitBreakerExtendImbalanceSide = Literal["BUY", "SELL"]
CircuitBreakerResumeHaltSource = Literal["CB", "ADMIN"]


class CircuitBreakerHalt(BaseModel):
    """Engine to all: one symbol has stopped trading. New orders rest rather than
    match until the halt ends, and every resting quote on the symbol has already
    been cancelled by the time this is published.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    trigger_price: float | None = Field(gt=0)
    """The trade price that breached the level. Null on an ADMIN halt. Unit:
    display_price.
    """
    reference_price: float | None = Field(gt=0)
    """The price the breach was measured against. Null on an ADMIN halt. Unit:
    display_price.
    """
    resume_at_ns: int | None
    """When the current call phase ends. Null means indefinite: the halt lasts until
    an operator resumes it. ACE moves this on every extension, so a consumer that
    ignores `circuit_breaker.extend` will hold a value that has already passed.
    Unit: epoch_nanos.
    """
    halt_source: CircuitBreakerHaltHaltSource | None = Field(default=None)
    """What put the symbol into the halt. Mirrors `CircuitBreakerState.halt_source`,
    which is `None` only while no halt is in effect -- so the key is present on
    every halt event.
    """
    level: str | None = Field(default=None, max_length=32)
    """Which rung of the ladder fired -- a name from the symbol's
    `circuit_breaker.levels` config -- or `ADMIN_ALL` / `ADMIN_SYMBOL` for an
    operator halt. Not an enum: the ladder is configuration, so the value set
    differs per deployment.
    """
    corridor_low: float | None = Field(default=None, gt=0)
    """Lower bound of the ACE reopening corridor. Absent when the halt has no
    corridor: either ACE is disabled or the halt began with no reference price to
    centre one on. Unit: display_price.
    """
    corridor_high: float | None = Field(default=None, gt=0)
    """Upper bound of the ACE reopening corridor. Absent with the low. Unit:
    display_price.
    """
    expansion: int | None = Field(default=None, ge=0)
    """Rungs of the expansion ladder consumed so far; 0 in the initial call phase.
    Absent whenever the corridor is, because a halt that cannot have a corridor
    can never widen one.
    """


class CircuitBreakerExtend(BaseModel):
    """Engine to all: the call phase ended with the indicative price outside the
    corridor, so the symbol stays halted, the corridor widens by one rung and a
    fresh call phase begins.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    indicative_price: float = Field(gt=0)
    """Where the symbol would have reopened, outside the corridor. Unit:
    display_price.
    """
    indicative_qty: int = Field(gt=0)
    """Quantity that would have executed. Always above zero: the producer only
    extends when the indicative uncross would have traded. Unit: shares.
    """
    imbalance_side: CircuitBreakerExtendImbalanceSide | None = Field(default=None)
    """Which side is unfilled at the indicative price. Absent when the book is
    balanced there.
    """
    resume_at_ns: int
    """End of the new call phase. Always set; `extend()` computes it. Unit:
    epoch_nanos.
    """
    corridor_low: float = Field(gt=0)
    """Lower bound of the widened corridor. Unit: display_price."""
    corridor_high: float = Field(gt=0)
    """Upper bound of the widened corridor. Unit: display_price."""
    expansion: int = Field(gt=0)
    """Rungs consumed after this widening -- at least 1, since the event is published
    by the widening itself.
    """


class CircuitBreakerResume(BaseModel):
    """Engine to all: the symbol is trading again. It rejoins whatever the exchange
    is currently doing rather than returning to continuous trading -- a halt that
    expires near the close resumes into CLOSING_AUCTION or CLOSED.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    halt_source: CircuitBreakerResumeHaltSource | None = Field(default=None)
    """What had put the symbol into the halt that just ended."""
    reason: str | None = Field(default=None, max_length=64)
    """Why the halt ended, when that is not simply "its call phase expired". Only the
    closing backstop sets it, to CLOSING_BACKSTOP.
    """
    clamped: bool | None = Field(default=None)
    """True when the print price was forced to the corridor boundary instead of the
    equilibrium. A client showing a clamped price as a discovered one would
    mislead. Absent on the three ordinary resumes, where no price is imposed at
    all -- which is a different statement from `false`, and worth keeping
    distinct.
    """
    print_price: float | None = Field(default=None, gt=0)
    """The price the backstop uncross printed at. Absent when there was no crossing
    interest to print, and on the three ordinary resumes. Unit: display_price.
    """
