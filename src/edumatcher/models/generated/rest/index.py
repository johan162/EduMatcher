# GENERATED FROM spec/messages/index.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``index`` message family.

Family version 1. Derived from ``spec/messages/index.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HistoryRecordType = Literal[
    "INIT",
    "CORP_ACTION",
    "ADD_CONSTITUENT",
    "DELIST",
    "REBALANCE",
]
IndexCorpActionAction = Literal["SPLIT", "CASH_DIVIDEND", "SHARES_ISSUANCE"]
IndexConstituentChangeChangeType = Literal["ADD", "DELIST"]


class DaySummary(BaseModel):
    """The session's open, high and low index level. All three arrive together or not
    at all: _update_day_ohlc sets open, high and low in one branch and
    _reset_for_new_session clears all three, so there has never been a state where
    one is known and another is not. As three flat keys under one guard that was a
    convention; as a nullable record it is unrepresentable otherwise, which is
    design section 16.2's whole argument.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    open: float
    """The first level computed this session."""
    high: float
    low: float


class HistoryRecord(BaseModel):
    """One structural audit entry, replayed verbatim from pm-index's append-only
    JSONL archive. This is a union of five shapes discriminated by `type`, and the
    IDL has no variant construct (section 20.3). Every field the five do not share
    is therefore optional, and the spec cannot state "a CORP_ACTION always carries
    action and detail" - that rule lives in _handle_corp_action. What it can state
    is the field set, the units and the types, which is what every consumer needs:
    all six read the records with `.get(key, default)` and dispatch on `type`. The
    optional fields omit rather than null because the archive omits: a record
    written before this spec existed must read back and re-emit unchanged, or
    specifying the family would rewrite history.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    type: HistoryRecordType
    """The discriminator. IndexHistory.query drops any other value with a warning, so
    an unknown type never reaches the wire.
    """
    ts_ns: int
    """Unit: epoch_nanos."""
    index_id: str = Field(max_length=32)
    level: float
    """The index level immediately after the event was applied."""
    symbol: str | None = Field(default=None, max_length=16)
    """CORP_ACTION, ADD_CONSTITUENT and DELIST."""
    action: str | None = Field(default=None, max_length=32)
    """CORP_ACTION only."""
    detail: str | None = Field(default=None, max_length=128)
    """CORP_ACTION only; a rendered summary such as 'shares=1000'."""
    old_divisor: float | None = Field(default=None)
    """Every type but INIT."""
    new_divisor: float | None = Field(default=None)
    """Every type but INIT."""
    base_value: float | None = Field(default=None)
    """INIT only."""
    divisor: float | None = Field(default=None)
    """INIT only, and the odd one out: every other type reports the divisor as an
    old/new pair. Kept as written rather than normalised, because the archive on
    disk already says this.
    """
    constituents: list[str] | None = Field(default=None)
    """INIT only."""
    shares_outstanding: int | None = Field(default=None)
    """ADD_CONSTITUENT only, and absent on records written before 5.2e: the handler
    used the share count to weight the constituent and then dropped it from the
    audit entry, so what a constituent was added with was durably recorded
    nowhere. Optional rather than required because the archive on disk still holds
    records without it. Unit: shares.
    """
    reference_price: float | None = Field(default=None)
    """ADD_CONSTITUENT only. Unit: display_price."""
    symbols: list[str] | None = Field(default=None)
    """REBALANCE only: the symbols the batch actually applied to."""


class RebalanceUpdate(BaseModel):
    """One entry of a rebalance batch. Mechanically a SHARES_ISSUANCE corporate
    action, applied to every named existing constituent as one batch with a single
    recompute and publish rather than one round-trip per symbol.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    new_shares_outstanding: int = Field(gt=0)
    """Unit: shares."""


class IndexUpdate(BaseModel):
    """pm-index to subscribers: the current level of one index, published on every
    constituent trade subject to a rate limit, and forced on a structural change
    or at end of day.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    index_id: str = Field(max_length=32)
    level: float
    aggregate_cap: float
    """Sum of constituent market capitalisations. Unit: money."""
    divisor: float
    """Level = aggregate_cap / divisor."""
    session_state: str = Field(max_length=32)
    """Mirrors session.state; a plain string there and here."""
    ts_ns: int
    """Unit: epoch_nanos."""
    day: DaySummary | None = Field(default=None)


class IndexHistoryRequest(BaseModel):
    """Gateway or operator to pm-index: replay the structural audit log."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    index_id: str = Field(max_length=32)
    from_ts_ns: int
    """Unit: epoch_nanos."""
    to_ts_ns: int
    """Unit: epoch_nanos."""
    types: list[str] | None = Field(default=None)
    """Record types to include; omitted means all structural types."""
    max_records: int = Field(gt=0)


class IndexHistory(BaseModel):
    """pm-index to requestor: the matching audit records."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    index_id: str = Field(max_length=32)
    records: list[HistoryRecord]
    warnings: list[str] | None = Field(default=None)


class IndexCorpAction(BaseModel):
    """Operator to pm-index: apply a corporate action."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    action: IndexCorpActionAction
    index_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    gateway_id: str = Field(max_length=32)
    ratio_numerator: int | None = Field(default=None, gt=0)
    """SPLIT."""
    ratio_denominator: int | None = Field(default=None, gt=0)
    """SPLIT."""
    dividend_per_share: float | None = Field(default=None, gt=0)
    """CASH_DIVIDEND. Unit: money."""
    new_shares_outstanding: int | None = Field(default=None, gt=0)
    """SHARES_ISSUANCE. Unit: shares."""
    command_id: str | None = Field(default=None, max_length=64)
    """Echoed on the ack so a caller can correlate."""


class IndexConstituentChange(BaseModel):
    """Operator to pm-index: add or delist a constituent."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    change_type: IndexConstituentChangeChangeType
    index_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    gateway_id: str = Field(max_length=32)
    shares_outstanding: int | None = Field(default=None, gt=0)
    """ADD. Unit: shares."""
    initial_price: float | None = Field(default=None, gt=0)
    """ADD. Unit: display_price."""
    command_id: str | None = Field(default=None, max_length=64)
    """Echoed on the ack so a caller can correlate."""


class IndexRebalance(BaseModel):
    """ADMIN to pm-index: set shares outstanding for several constituents in one
    batch.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    index_id: str = Field(max_length=32)
    gateway_id: str = Field(max_length=32)
    updates: list[RebalanceUpdate] = Field(min_length=1)
    """Never empty; the handler rejects an empty batch."""
    command_id: str | None = Field(default=None, max_length=64)
    """Echoed on the ack so a caller can correlate."""


class IndexCorpActionAck(BaseModel):
    """pm-index to requestor: the corporate action's outcome."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    ts_ns: int
    """Unit: epoch_nanos."""
    index_id: str | None = Field(default=None, max_length=32)
    level: float | None = Field(default=None)
    divisor: float | None = Field(default=None)
    old_divisor: float | None = Field(default=None)
    """The divisor immediately before this action was applied. Same field name and
    purpose as HistoryRecord.old_divisor, so a post-mortem does not need pm-
    index's local JSONL archive to see what changed — the wire event is self-
    contained. Present only alongside divisor, i.e. on acceptance.
    """
    command_id: str | None = Field(default=None, max_length=64)


class IndexConstituentChangeAck(BaseModel):
    """pm-index to requestor: the constituent change's outcome."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    ts_ns: int
    """Unit: epoch_nanos."""
    index_id: str | None = Field(default=None, max_length=32)
    level: float | None = Field(default=None)
    divisor: float | None = Field(default=None)
    old_divisor: float | None = Field(default=None)
    """The divisor immediately before this action was applied. Same field name and
    purpose as HistoryRecord.old_divisor, so a post-mortem does not need pm-
    index's local JSONL archive to see what changed — the wire event is self-
    contained. Present only alongside divisor, i.e. on acceptance.
    """
    command_id: str | None = Field(default=None, max_length=64)


class IndexRebalanceAck(BaseModel):
    """pm-index to ADMIN: the batch's outcome."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    reason: str = Field(max_length=512)
    ts_ns: int
    """Unit: epoch_nanos."""
    updated_symbols: int = Field(ge=0)
    index_id: str | None = Field(default=None, max_length=32)
    level: float | None = Field(default=None)
    divisor: float | None = Field(default=None)
    old_divisor: float | None = Field(default=None)
    """The divisor immediately before this action was applied. Same field name and
    purpose as HistoryRecord.old_divisor, so a post-mortem does not need pm-
    index's local JSONL archive to see what changed — the wire event is self-
    contained. Present only alongside divisor, i.e. on acceptance.
    """
    command_id: str | None = Field(default=None, max_length=64)


class IndexError(BaseModel):
    """pm-index to requestor: the request could not be routed to an index at all."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    accepted: bool
    """Always false; present so every reply has the same first key."""
    reason: str = Field(max_length=512)
    ts_ns: int
    """Unit: epoch_nanos."""
