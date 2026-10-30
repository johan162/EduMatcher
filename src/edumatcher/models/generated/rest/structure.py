# GENERATED FROM spec/messages/structure.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``structure`` message family.

Family version 1. Derived from ``spec/messages/structure.yaml`` by the rest emitter;
edit the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ComboStatusStatus = Literal[
    "PENDING",
    "PARTIALLY_MATCHED",
    "MATCHED",
    "FAILED",
    "CANCELLED",
    "REJECTED",
]


class ComboAck(BaseModel):
    """Engine to gateway: a combo submission was accepted or rejected."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    combo_id: str = Field(max_length=64)
    accepted: bool
    reason: str = Field(max_length=512)


class ComboStatus(BaseModel):
    """Engine to gateway: a combo moved to a new lifecycle state."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    combo_id: str = Field(max_length=64)
    status: ComboStatusStatus
    """Mirrors models/combo.py::ComboStatus."""
    reason: str | None = Field(default=None, max_length=512)
    """Why a terminal status was reached; absent on the happy path."""


class OcoAck(BaseModel):
    """Engine to gateway: an OCO pair was accepted or rejected."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    oco_id: str = Field(max_length=64)
    accepted: bool
    reason: str = Field(max_length=512)
    order_id_1: str = Field(max_length=64)
    """The first leg's engine order id."""
    order_id_2: str = Field(max_length=64)
    """The second leg's engine order id."""


class OcoCancelled(BaseModel):
    """Engine to gateway: one leg of an OCO pair was cancelled because the other was
    actioned.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    oco_id: str = Field(max_length=64)
    cancelled_order_id: str = Field(max_length=64)
    reason: str = Field(max_length=512)
