# GENERATED FROM spec/messages/sim.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``sim`` message family.

Family version 1. Derived from ``spec/messages/sim.yaml`` by the rest emitter; edit the
spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NewsRequestScope = Literal["SYMBOL", "SECTOR", "MARKET"]
NewsRequestKind = Literal[
    "EARNINGS",
    "GUIDANCE",
    "MNA",
    "REGULATORY",
    "PRODUCT",
    "LEGAL",
    "MANAGEMENT",
    "MACRO",
    "OPERATIONS",
    "RESEARCH",
    "CONTRACT",
    "ESG",
]
SimStateState = Literal["RUNNING", "PAUSED"]
SimCommandAction = Literal["STATUS", "NEWS_INJECT", "NEWS_CONFIRM", "NEWS_RETRACT"]


class NewsRequest(BaseModel):
    """A headline the instructor wants published (NEWS_INJECT)."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    scope: NewsRequestScope
    targets: list[str]
    """Symbols (SYMBOL) or sector names (SECTOR); empty for MARKET."""
    kind: NewsRequestKind
    sentiment: float = Field(ge=-1, le=1)
    impact: float = Field(ge=-1, le=1)
    """Move of the log true value when the news is (or becomes) confirmed: 0.10 is
    about +10.5%. Sector and market news move each symbol by its beta to that
    factor. Never published.
    """
    headline: str = Field(max_length=200)
    """Empty: pm-market-sim writes one from the kind and sentiment."""
    rumour: bool
    """Publish as a RUMOUR; the value moves only on NEWS_CONFIRM."""
    credibility: float | None = Field(default=None, ge=0, le=1)


class SymbolValue(BaseModel):
    """One symbol's true value at the step's simulated time."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    value: float = Field(gt=0)
    """Display money, like every price on the engine bus. Unit: display_price."""


class SimValue(BaseModel):
    """pm-market-sim to the bots, the market makers that anchor to it and the
    instructor's tools: every symbol's true value after one model step.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    seq: int = Field(gt=0)
    """Step counter; continues across a pm-market-sim restart."""
    ts_ns: int
    """Publication time. Unit: epoch_nanos."""
    values: list[SymbolValue] = Field(min_length=1)


class SimState(BaseModel):
    """pm-market-sim's heartbeat: whether the model is stepping and how far it has
    got.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    state: SimStateState
    """RUNNING during continuous trading, PAUSED otherwise."""
    session: str = Field(max_length=32)
    """The engine session state the model follows."""
    seq: int
    """The last sim.value published (0 = none yet)."""
    ts_ns: int
    """Unit: epoch_nanos."""
    step_ns: int = Field(gt=0)
    """Time between steps while running. Unit: duration_nanos."""
    symbols: int
    seed: int


class SimCommand(BaseModel):
    """Instructor tooling to pm-market-sim: one command."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)
    """The sender; the reply goes to sim.command_ack.<gateway_id>."""
    action: SimCommandAction
    news: NewsRequest | None = Field(default=None)
    """The headline to publish (NEWS_INJECT)."""
    news_id: str = Field(max_length=32)
    """The rumour to confirm or retract."""


class SimCommandAck(BaseModel):
    """pm-market-sim to the commanding tool: the outcome of one command."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    accepted: bool
    reason: str = Field(max_length=256)
    """Refusal detail, or what was done."""
    news_id: str = Field(max_length=32)
    """The news.event published, if any."""
