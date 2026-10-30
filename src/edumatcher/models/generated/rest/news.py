# GENERATED FROM spec/messages/news.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``news`` message family.

Family version 1. Derived from ``spec/messages/news.yaml`` by the rest emitter; edit the
spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NewsEventScope = Literal["SYMBOL", "SECTOR", "MARKET"]
NewsEventKind = Literal[
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
NewsEventStatus = Literal["RUMOUR", "CONFIRMED", "RETRACTED"]


class NewsEvent(BaseModel):
    """pm-market-sim to everyone: one headline, or a change in what an earlier one is
    known to be (a rumour confirmed or retracted).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=32)
    ts_ns: int
    """Unit: epoch_nanos."""
    scope: NewsEventScope
    targets: list[str]
    """Symbols (SYMBOL) or sector names (SECTOR); empty for MARKET."""
    kind: NewsEventKind
    status: NewsEventStatus
    headline: str = Field(max_length=200)
    sentiment: float = Field(ge=-1, le=1)
    """Tone of the news, -1 (bad) to 1 (good); not its size."""
    credibility: float | None = Field(default=None, ge=0, le=1)
    """How believable a rumour is; absent on confirmed news."""
    related_id: str = Field(max_length=32)
    """The rumour a CONFIRMED or RETRACTED event resolves."""
