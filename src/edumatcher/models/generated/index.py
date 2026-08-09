# GENERATED FROM spec/messages/index.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``index`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/index.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "index"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class DaySummary:
    """The session's open, high and low index level. All three arrive together or not
    at all: _update_day_ohlc sets open, high and low in one branch and
    _reset_for_new_session clears all three, so there has never been a state where
    one is known and another is not. As three flat keys under one guard that was a
    convention; as a nullable record it is unrepresentable otherwise, which is
    design section 16.2's whole argument.
    """

    open: float  # unit: dimensionless
    high: float  # unit: dimensionless
    low: float  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        return None

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "DaySummary":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            open=float(p["open"]),
            high=float(p["high"]),
            low=float(p["low"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
        }


_HISTORY_RECORD_TYPE_VALUES = (
    "INIT",
    "CORP_ACTION",
    "ADD_CONSTITUENT",
    "DELIST",
    "REBALANCE",
)
HistoryRecordType = Literal[
    "INIT",
    "CORP_ACTION",
    "ADD_CONSTITUENT",
    "DELIST",
    "REBALANCE",
]


@dataclass(frozen=True, slots=True)
class HistoryRecord:
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

    type: HistoryRecordType
    timestamp: float  # unit: epoch_seconds
    index_id: str
    level: float  # unit: dimensionless
    symbol: str = ""
    action: str = ""
    detail: str = ""
    old_divisor: float | None = None  # unit: dimensionless
    new_divisor: float | None = None  # unit: dimensionless
    base_value: float | None = None  # unit: dimensionless
    divisor: float | None = None  # unit: dimensionless
    constituents: list[str] = field(default_factory=list)
    shares_outstanding: int | None = None  # unit: shares
    reference_price: float | None = None  # unit: display_price
    symbols: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.type not in _HISTORY_RECORD_TYPE_VALUES:
            raise MessageValidationError(
                f"type: {self.type!r} is not one of {_HISTORY_RECORD_TYPE_VALUES!r}"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.action) > 32:
            raise MessageValidationError(
                f"action: length {len(self.action)} exceeds max_len 32"
            )
        if len(self.detail) > 128:
            raise MessageValidationError(
                f"detail: length {len(self.detail)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HistoryRecord":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            type=cast(HistoryRecordType, str(p["type"])),
            timestamp=float(p["timestamp"]),
            index_id=str(p["index_id"]),
            level=float(p["level"]),
            symbol=str(p.get("symbol", "")),
            action=str(p.get("action", "")),
            detail=str(p.get("detail", "")),
            old_divisor=(
                None if p.get("old_divisor") is None else float(p["old_divisor"])
            ),
            new_divisor=(
                None if p.get("new_divisor") is None else float(p["new_divisor"])
            ),
            base_value=None if p.get("base_value") is None else float(p["base_value"]),
            divisor=None if p.get("divisor") is None else float(p["divisor"]),
            constituents=[str(item) for item in p.get("constituents", [])],
            shares_outstanding=(
                None
                if p.get("shares_outstanding") is None
                else int(p["shares_outstanding"])
            ),
            reference_price=(
                None
                if p.get("reference_price") is None
                else float(p["reference_price"])
            ),
            symbols=[str(item) for item in p.get("symbols", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "type": self.type,
            "timestamp": self.timestamp,
            "index_id": self.index_id,
            "level": self.level,
        }
        if self.symbol:
            payload["symbol"] = self.symbol
        if self.action:
            payload["action"] = self.action
        if self.detail:
            payload["detail"] = self.detail
        if self.old_divisor is not None:
            payload["old_divisor"] = self.old_divisor
        if self.new_divisor is not None:
            payload["new_divisor"] = self.new_divisor
        if self.base_value is not None:
            payload["base_value"] = self.base_value
        if self.divisor is not None:
            payload["divisor"] = self.divisor
        if self.constituents:
            payload["constituents"] = self.constituents
        if self.shares_outstanding is not None:
            payload["shares_outstanding"] = self.shares_outstanding
        if self.reference_price is not None:
            payload["reference_price"] = self.reference_price
        if self.symbols:
            payload["symbols"] = self.symbols
        return payload


@dataclass(frozen=True, slots=True)
class RebalanceUpdate:
    """One entry of a rebalance batch. Mechanically a SHARES_ISSUANCE corporate
    action, applied to every named existing constituent as one batch with a single
    recompute and publish rather than one round-trip per symbol.
    """

    symbol: str
    new_shares_outstanding: int  # unit: shares

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.new_shares_outstanding <= 0:
            raise MessageValidationError(
                f"new_shares_outstanding: {self.new_shares_outstanding!r} must be > 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RebalanceUpdate":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            new_shares_outstanding=int(p["new_shares_outstanding"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "new_shares_outstanding": self.new_shares_outstanding,
        }


TOPIC_INDEX_UPDATE = "index.update"
_TOPIC_INDEX_UPDATE_BYTES = "index.update".encode()


_INDEX_UPDATE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "level",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
    },
    {
        "name": "aggregate_cap",
        "type": "float",
        "unit": "money",
        "required": True,
        "doc": "Sum of constituent market capitalisations.",
    },
    {
        "name": "divisor",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "Level = aggregate_cap / divisor.",
    },
    {
        "name": "session_state",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Mirrors session.state; a plain string there and here.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "day",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class IndexUpdate:
    """pm-index to subscribers: the current level of one index, published on every
    constituent trade subject to a rate limit, and forced on a structural change
    or at end of day.

    `day` is absent before the first level of a session is computed and after
    _reset_for_new_session clears it. All three consumers - alf_console's display, pm-
    stats' snapshot writer and md_gateway's CALF normaliser - read it with `.get` and
    test `is not None`, so absent and null are the same thing to every one of them.
    """

    index_id: str
    level: float  # unit: dimensionless
    aggregate_cap: float  # unit: money
    divisor: float  # unit: dimensionless
    session_state: str
    timestamp: float  # unit: epoch_seconds
    day: DaySummary | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.session_state) > 32:
            raise MessageValidationError(
                f"session_state: length {len(self.session_state)} exceeds max_len 32"
            )
        if self.day is not None:
            self.day.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexUpdate":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            index_id=str(p["index_id"]),
            level=float(p["level"]),
            aggregate_cap=float(p["aggregate_cap"]),
            divisor=float(p["divisor"]),
            session_state=str(p["session_state"]),
            timestamp=float(p["timestamp"]),
            day=None if p.get("day") is None else DaySummary.from_dict(p["day"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "index_id": self.index_id,
            "level": self.level,
            "aggregate_cap": self.aggregate_cap,
            "divisor": self.divisor,
            "session_state": self.session_state,
            "timestamp": self.timestamp,
        }
        if self.day is not None:
            payload["day"] = self.day.to_dict()
        return payload


def is_index_update(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_INDEX_UPDATE


def make_index_update(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexUpdate.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_INDEX_UPDATE, obj.to_dict())


def parse_index_update(frames: list[bytes]) -> "IndexUpdate":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = IndexUpdate.from_dict(payload)
    obj.validate()
    return obj


def describe_index_update() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_UPDATE_FIELDS


TOPIC_INDEX_HISTORY_REQUEST = "index.history_request"
_TOPIC_INDEX_HISTORY_REQUEST_BYTES = "index.history_request".encode()


_INDEX_HISTORY_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "from_ts",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "to_ts",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "types",
        "type": "list",
        "unit": None,
        "required": False,
        "doc": "Record types to include; omitted means all structural types.",
    },
    {
        "name": "max_records",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"gt": 0},
    },
)


@dataclass(frozen=True, slots=True)
class IndexHistoryRequest:
    """Gateway or operator to pm-index: replay the structural audit log.

    pm-index's history is structural only - index creation, corporate actions,
    constituent changes, rebalances. Level and end-of-day time-series history lives in
    pm-stats. `types` is omitted when unset rather than sent as a default. The hand-
    written builder defaulted it to four of the five structural types and silently
    dropped REBALANCE from every reply that took the default; the server's own default
    is the full set, and it cannot tell an omitted `types` from a deliberate one.
    `max_records` keeps its default because the builder's value and the server's agree.
    """

    gateway_id: str
    index_id: str
    from_ts: float  # unit: epoch_seconds
    to_ts: float  # unit: epoch_seconds
    types: list[str] = field(default_factory=list)
    max_records: int = 10000  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if self.max_records <= 0:
            raise MessageValidationError(
                f"max_records: {self.max_records!r} must be > 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexHistoryRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            index_id=str(p["index_id"]),
            from_ts=float(p["from_ts"]),
            to_ts=float(p["to_ts"]),
            types=[str(item) for item in p.get("types", [])],
            max_records=int(p.get("max_records", 10000)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "index_id": self.index_id,
            "from_ts": self.from_ts,
            "to_ts": self.to_ts,
            "max_records": self.max_records,
        }
        if self.types:
            payload["types"] = self.types
        return payload


def is_index_history_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_INDEX_HISTORY_REQUEST


def make_index_history_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexHistoryRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_INDEX_HISTORY_REQUEST, obj.to_dict())


def make_index_history_request_unchecked(
    *,
    gateway_id: str,
    index_id: str,
    from_ts: float,
    to_ts: float,
    types: list[str] = [],
    max_records: int = 10000,
) -> list[bytes]:
    """Identical frames to ``make_index_history_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "gateway_id": str(gateway_id),
        "index_id": str(index_id),
        "from_ts": float(from_ts),
        "to_ts": float(to_ts),
        "max_records": int(max_records),
    }
    if types:
        payload["types"] = [str(item) for item in types]
    return [
        _TOPIC_INDEX_HISTORY_REQUEST_BYTES,
        _msg.dumps(payload),
    ]


def parse_index_history_request(frames: list[bytes]) -> "IndexHistoryRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = IndexHistoryRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_index_history_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_HISTORY_REQUEST_FIELDS


TOPIC_INDEX_HISTORY = "index.history.{gateway_id}"
PREFIX_INDEX_HISTORY = "index.history."
_INDEX_HISTORY_RE = re.compile("index\\.history\\.(?P<gateway_id>[^.]+)")


_INDEX_HISTORY_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "records",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "warnings",
        "type": "list",
        "unit": None,
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class IndexHistory:
    """pm-index to requestor: the matching audit records.

    `warnings` reports lines the archive could not parse and record types it did not
    recognise. It is omitted when there are none, which is what the hand-written
    builder's `if warnings:` did.
    """

    gateway_id: str
    index_id: str
    records: list[HistoryRecord]
    warnings: list[str] = field(default_factory=list)

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        for records_item in self.records:
            records_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexHistory":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            index_id=str(p["index_id"]),
            records=[HistoryRecord.from_dict(item) for item in p["records"]],
            warnings=[str(item) for item in p.get("warnings", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "index_id": self.index_id,
            "records": [item.to_dict() for item in self.records],
        }
        if self.warnings:
            payload["warnings"] = self.warnings
        return payload


def topic_index_history(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"index.history.{gateway_id}"


def match_index_history(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _INDEX_HISTORY_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_index_history(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexHistory.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_index_history(obj.gateway_id), obj.to_dict())


def parse_index_history(frames: list[bytes]) -> "IndexHistory":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_index_history(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_INDEX_HISTORY!r}")
    payload = {**payload, "gateway_id": matched}
    obj = IndexHistory.from_dict(payload)
    obj.validate()
    return obj


def describe_index_history() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_HISTORY_FIELDS


TOPIC_INDEX_CORP_ACTION = "index.corp_action"
_TOPIC_INDEX_CORP_ACTION_BYTES = "index.corp_action".encode()
_INDEX_CORP_ACTION_ACTION_VALUES = ("SPLIT", "CASH_DIVIDEND", "SHARES_ISSUANCE")
IndexCorpActionAction = Literal["SPLIT", "CASH_DIVIDEND", "SHARES_ISSUANCE"]


_INDEX_CORP_ACTION_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "action",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _INDEX_CORP_ACTION_ACTION_VALUES,
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "ratio_numerator",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "SPLIT.",
        "constraints": {"gt": 0},
    },
    {
        "name": "ratio_denominator",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "SPLIT.",
        "constraints": {"gt": 0},
    },
    {
        "name": "dividend_per_share",
        "type": "float",
        "unit": "money",
        "required": False,
        "doc": "CASH_DIVIDEND.",
        "constraints": {"gt": 0},
    },
    {
        "name": "new_shares_outstanding",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "SHARES_ISSUANCE.",
        "constraints": {"gt": 0},
    },
)


@dataclass(frozen=True, slots=True)
class IndexCorpAction:
    """Operator to pm-index: apply a corporate action.

    The four parameters are action-specific and flat: SPLIT reads the two ratio fields,
    CASH_DIVIDEND reads dividend_per_share, SHARES_ISSUANCE reads
    new_shares_outstanding, and each is read with `.get(key, 0)` inside its own branch
    of _handle_corp_action. A discriminated union would say that properly and the IDL
    has none - see design section 20.3 for why one was not built for a single family.
    """

    action: IndexCorpActionAction
    index_id: str
    symbol: str
    gateway_id: str
    ratio_numerator: int | None = None  # unit: dimensionless
    ratio_denominator: int | None = None  # unit: dimensionless
    dividend_per_share: float | None = None  # unit: money
    new_shares_outstanding: int | None = None  # unit: shares

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.action not in _INDEX_CORP_ACTION_ACTION_VALUES:
            raise MessageValidationError(
                f"action: {self.action!r} is not one of {_INDEX_CORP_ACTION_ACTION_VALUES!r}"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.ratio_numerator is not None:
            if self.ratio_numerator <= 0:
                raise MessageValidationError(
                    f"ratio_numerator: {self.ratio_numerator!r} must be > 0"
                )
        if self.ratio_denominator is not None:
            if self.ratio_denominator <= 0:
                raise MessageValidationError(
                    f"ratio_denominator: {self.ratio_denominator!r} must be > 0"
                )
        if self.dividend_per_share is not None:
            if self.dividend_per_share <= 0:
                raise MessageValidationError(
                    f"dividend_per_share: {self.dividend_per_share!r} must be > 0"
                )
        if self.new_shares_outstanding is not None:
            if self.new_shares_outstanding <= 0:
                raise MessageValidationError(
                    f"new_shares_outstanding: {self.new_shares_outstanding!r} must be > 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexCorpAction":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            action=cast(IndexCorpActionAction, str(p["action"])),
            index_id=str(p["index_id"]),
            symbol=str(p["symbol"]),
            gateway_id=str(p["gateway_id"]),
            ratio_numerator=(
                None if p.get("ratio_numerator") is None else int(p["ratio_numerator"])
            ),
            ratio_denominator=(
                None
                if p.get("ratio_denominator") is None
                else int(p["ratio_denominator"])
            ),
            dividend_per_share=(
                None
                if p.get("dividend_per_share") is None
                else float(p["dividend_per_share"])
            ),
            new_shares_outstanding=(
                None
                if p.get("new_shares_outstanding") is None
                else int(p["new_shares_outstanding"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "action": self.action,
            "index_id": self.index_id,
            "symbol": self.symbol,
            "gateway_id": self.gateway_id,
        }
        if self.ratio_numerator is not None:
            payload["ratio_numerator"] = self.ratio_numerator
        if self.ratio_denominator is not None:
            payload["ratio_denominator"] = self.ratio_denominator
        if self.dividend_per_share is not None:
            payload["dividend_per_share"] = self.dividend_per_share
        if self.new_shares_outstanding is not None:
            payload["new_shares_outstanding"] = self.new_shares_outstanding
        return payload


def is_index_corp_action(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_INDEX_CORP_ACTION


def make_index_corp_action(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexCorpAction.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_INDEX_CORP_ACTION, obj.to_dict())


def make_index_corp_action_unchecked(
    *,
    action: IndexCorpActionAction,
    index_id: str,
    symbol: str,
    gateway_id: str,
    ratio_numerator: int | None = None,
    ratio_denominator: int | None = None,
    dividend_per_share: float | None = None,
    new_shares_outstanding: int | None = None,
) -> list[bytes]:
    """Identical frames to ``make_index_corp_action``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "action": str(action),
        "index_id": str(index_id),
        "symbol": str(symbol),
        "gateway_id": str(gateway_id),
    }
    if ratio_numerator is not None:
        payload["ratio_numerator"] = int(ratio_numerator)
    if ratio_denominator is not None:
        payload["ratio_denominator"] = int(ratio_denominator)
    if dividend_per_share is not None:
        payload["dividend_per_share"] = float(dividend_per_share)
    if new_shares_outstanding is not None:
        payload["new_shares_outstanding"] = int(new_shares_outstanding)
    return [
        _TOPIC_INDEX_CORP_ACTION_BYTES,
        _msg.dumps(payload),
    ]


def parse_index_corp_action(frames: list[bytes]) -> "IndexCorpAction":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = IndexCorpAction.from_dict(payload)
    obj.validate()
    return obj


def describe_index_corp_action() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_CORP_ACTION_FIELDS


TOPIC_INDEX_CONSTITUENT_CHANGE = "index.constituent_change"
_TOPIC_INDEX_CONSTITUENT_CHANGE_BYTES = "index.constituent_change".encode()
_INDEX_CONSTITUENT_CHANGE_CHANGE_TYPE_VALUES = ("ADD", "DELIST")
IndexConstituentChangeChangeType = Literal["ADD", "DELIST"]


_INDEX_CONSTITUENT_CHANGE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "change_type",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "",
        "values": _INDEX_CONSTITUENT_CHANGE_CHANGE_TYPE_VALUES,
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "shares_outstanding",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "ADD.",
        "constraints": {"gt": 0},
    },
    {
        "name": "initial_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "ADD.",
        "constraints": {"gt": 0},
    },
)


@dataclass(frozen=True, slots=True)
class IndexConstituentChange:
    """Operator to pm-index: add or delist a constituent.

    Both parameters belong to ADD and neither to DELIST, and the hand-written builder
    omitted each independently rather than as a pair - so unlike DaySummary they are two
    guards, not one, and stay flat.
    """

    change_type: IndexConstituentChangeChangeType
    index_id: str
    symbol: str
    gateway_id: str
    shares_outstanding: int | None = None  # unit: shares
    initial_price: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.change_type not in _INDEX_CONSTITUENT_CHANGE_CHANGE_TYPE_VALUES:
            raise MessageValidationError(
                f"change_type: {self.change_type!r} is not one of {_INDEX_CONSTITUENT_CHANGE_CHANGE_TYPE_VALUES!r}"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.shares_outstanding is not None:
            if self.shares_outstanding <= 0:
                raise MessageValidationError(
                    f"shares_outstanding: {self.shares_outstanding!r} must be > 0"
                )
        if self.initial_price is not None:
            if self.initial_price <= 0:
                raise MessageValidationError(
                    f"initial_price: {self.initial_price!r} must be > 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexConstituentChange":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            change_type=cast(IndexConstituentChangeChangeType, str(p["change_type"])),
            index_id=str(p["index_id"]),
            symbol=str(p["symbol"]),
            gateway_id=str(p["gateway_id"]),
            shares_outstanding=(
                None
                if p.get("shares_outstanding") is None
                else int(p["shares_outstanding"])
            ),
            initial_price=(
                None if p.get("initial_price") is None else float(p["initial_price"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "change_type": self.change_type,
            "index_id": self.index_id,
            "symbol": self.symbol,
            "gateway_id": self.gateway_id,
        }
        if self.shares_outstanding is not None:
            payload["shares_outstanding"] = self.shares_outstanding
        if self.initial_price is not None:
            payload["initial_price"] = self.initial_price
        return payload


def is_index_constituent_change(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_INDEX_CONSTITUENT_CHANGE


def make_index_constituent_change(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexConstituentChange.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_INDEX_CONSTITUENT_CHANGE, obj.to_dict())


def make_index_constituent_change_unchecked(
    *,
    change_type: IndexConstituentChangeChangeType,
    index_id: str,
    symbol: str,
    gateway_id: str,
    shares_outstanding: int | None = None,
    initial_price: float | None = None,
) -> list[bytes]:
    """Identical frames to ``make_index_constituent_change``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "change_type": str(change_type),
        "index_id": str(index_id),
        "symbol": str(symbol),
        "gateway_id": str(gateway_id),
    }
    if shares_outstanding is not None:
        payload["shares_outstanding"] = int(shares_outstanding)
    if initial_price is not None:
        payload["initial_price"] = float(initial_price)
    return [
        _TOPIC_INDEX_CONSTITUENT_CHANGE_BYTES,
        _msg.dumps(payload),
    ]


def parse_index_constituent_change(frames: list[bytes]) -> "IndexConstituentChange":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = IndexConstituentChange.from_dict(payload)
    obj.validate()
    return obj


def describe_index_constituent_change() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_CONSTITUENT_CHANGE_FIELDS


TOPIC_INDEX_REBALANCE = "index.rebalance"
_TOPIC_INDEX_REBALANCE_BYTES = "index.rebalance".encode()


_INDEX_REBALANCE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "updates",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Never empty; the handler rejects an empty batch.",
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Echoed on the ack so a caller can correlate.",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class IndexRebalance:
    """ADMIN to pm-index: set shares outstanding for several constituents in one
    batch.

    The whole batch is validated before any of it is applied, so an invalid entry
    anywhere rejects all of it - the all-or-nothing guarantee the single-action handlers
    get for free by only ever doing one mutation.
    """

    index_id: str
    gateway_id: str
    updates: list[RebalanceUpdate]
    command_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.updates) < 1:
            raise MessageValidationError("updates: fewer than 1 item(s)")
        for updates_item in self.updates:
            updates_item.validate()
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexRebalance":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            index_id=str(p["index_id"]),
            gateway_id=str(p["gateway_id"]),
            updates=[RebalanceUpdate.from_dict(item) for item in p["updates"]],
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "index_id": self.index_id,
            "gateway_id": self.gateway_id,
            "updates": [item.to_dict() for item in self.updates],
        }
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def is_index_rebalance(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_INDEX_REBALANCE


def make_index_rebalance(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexRebalance.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_INDEX_REBALANCE, obj.to_dict())


def parse_index_rebalance(frames: list[bytes]) -> "IndexRebalance":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = IndexRebalance.from_dict(payload)
    obj.validate()
    return obj


def describe_index_rebalance() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_REBALANCE_FIELDS


TOPIC_INDEX_CORP_ACTION_ACK = "index.corp_action_ack.{gateway_id}"
PREFIX_INDEX_CORP_ACTION_ACK = "index.corp_action_ack."
_INDEX_CORP_ACTION_ACK_RE = re.compile(
    "index\\.corp_action_ack\\.(?P<gateway_id>[^.]+)"
)


_INDEX_CORP_ACTION_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "level",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
    {
        "name": "divisor",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class IndexCorpActionAck:
    """pm-index to requestor: the corporate action's outcome.

    level and divisor are the recomputed values and are present only on acceptance;
    index_id is absent on the paths that reject before resolving one. reason is always
    emitted, as "" on success, because the hand-written builder put it in the base
    payload rather than under a guard.
    """

    gateway_id: str
    accepted: bool
    timestamp: float  # unit: epoch_seconds
    reason: str = ""
    index_id: str = ""
    level: float | None = None  # unit: dimensionless
    divisor: float | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexCorpActionAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            timestamp=float(p["timestamp"]),
            index_id=str(p.get("index_id", "")),
            level=None if p.get("level") is None else float(p["level"]),
            divisor=None if p.get("divisor") is None else float(p["divisor"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
        if self.index_id:
            payload["index_id"] = self.index_id
        if self.level is not None:
            payload["level"] = self.level
        if self.divisor is not None:
            payload["divisor"] = self.divisor
        return payload


def topic_index_corp_action_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"index.corp_action_ack.{gateway_id}"


def match_index_corp_action_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _INDEX_CORP_ACTION_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_index_corp_action_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexCorpActionAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_index_corp_action_ack(obj.gateway_id), obj.to_dict())


def make_index_corp_action_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    timestamp: float,
    reason: str = "",
    index_id: str = "",
    level: float | None = None,
    divisor: float | None = None,
) -> list[bytes]:
    """Identical frames to ``make_index_corp_action_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "reason": str(reason),
        "timestamp": float(timestamp),
    }
    if index_id:
        payload["index_id"] = str(index_id)
    if level is not None:
        payload["level"] = float(level)
    if divisor is not None:
        payload["divisor"] = float(divisor)
    return [
        topic_index_corp_action_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_index_corp_action_ack(frames: list[bytes]) -> "IndexCorpActionAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_index_corp_action_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_INDEX_CORP_ACTION_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = IndexCorpActionAck.from_dict(payload)
    obj.validate()
    return obj


def describe_index_corp_action_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_CORP_ACTION_ACK_FIELDS


TOPIC_INDEX_CONSTITUENT_CHANGE_ACK = "index.constituent_change_ack.{gateway_id}"
PREFIX_INDEX_CONSTITUENT_CHANGE_ACK = "index.constituent_change_ack."
_INDEX_CONSTITUENT_CHANGE_ACK_RE = re.compile(
    "index\\.constituent_change_ack\\.(?P<gateway_id>[^.]+)"
)


_INDEX_CONSTITUENT_CHANGE_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "level",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
    {
        "name": "divisor",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class IndexConstituentChangeAck:
    """pm-index to requestor: the constituent change's outcome.

    Field for field the same payload as index.corp_action_ack, on its own topic. Two
    topics rather than one because a caller waits on the specific reply to the command
    it sent, and commands/client.py names that topic when it registers the future.
    """

    gateway_id: str
    accepted: bool
    timestamp: float  # unit: epoch_seconds
    reason: str = ""
    index_id: str = ""
    level: float | None = None  # unit: dimensionless
    divisor: float | None = None  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexConstituentChangeAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            timestamp=float(p["timestamp"]),
            index_id=str(p.get("index_id", "")),
            level=None if p.get("level") is None else float(p["level"]),
            divisor=None if p.get("divisor") is None else float(p["divisor"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
        if self.index_id:
            payload["index_id"] = self.index_id
        if self.level is not None:
            payload["level"] = self.level
        if self.divisor is not None:
            payload["divisor"] = self.divisor
        return payload


def topic_index_constituent_change_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"index.constituent_change_ack.{gateway_id}"


def match_index_constituent_change_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _INDEX_CONSTITUENT_CHANGE_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_index_constituent_change_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexConstituentChangeAck.from_dict(kw)
    obj.validate()
    return _msg.encode(
        topic_index_constituent_change_ack(obj.gateway_id), obj.to_dict()
    )


def make_index_constituent_change_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    timestamp: float,
    reason: str = "",
    index_id: str = "",
    level: float | None = None,
    divisor: float | None = None,
) -> list[bytes]:
    """Identical frames to ``make_index_constituent_change_ack``, without
    ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "reason": str(reason),
        "timestamp": float(timestamp),
    }
    if index_id:
        payload["index_id"] = str(index_id)
    if level is not None:
        payload["level"] = float(level)
    if divisor is not None:
        payload["divisor"] = float(divisor)
    return [
        topic_index_constituent_change_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_index_constituent_change_ack(
    frames: list[bytes],
) -> "IndexConstituentChangeAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_index_constituent_change_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_INDEX_CONSTITUENT_CHANGE_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = IndexConstituentChangeAck.from_dict(payload)
    obj.validate()
    return obj


def describe_index_constituent_change_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_CONSTITUENT_CHANGE_ACK_FIELDS


TOPIC_INDEX_REBALANCE_ACK = "index.rebalance_ack.{gateway_id}"
PREFIX_INDEX_REBALANCE_ACK = "index.rebalance_ack."
_INDEX_REBALANCE_ACK_RE = re.compile("index\\.rebalance_ack\\.(?P<gateway_id>[^.]+)")


_INDEX_REBALANCE_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
    {
        "name": "updated_symbols",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "index_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "level",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
    {
        "name": "divisor",
        "type": "float",
        "unit": "dimensionless",
        "required": False,
        "doc": "",
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class IndexRebalanceAck:
    """pm-index to ADMIN: the batch's outcome.

    updated_symbols is always emitted, as 0 on rejection: the builder puts it in the
    base payload beside accepted and reason, and a rejected batch applied nothing.
    """

    gateway_id: str
    accepted: bool
    timestamp: float  # unit: epoch_seconds
    reason: str = ""
    updated_symbols: int = 0  # unit: dimensionless
    index_id: str = ""
    level: float | None = None  # unit: dimensionless
    divisor: float | None = None  # unit: dimensionless
    command_id: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if self.updated_symbols < 0:
            raise MessageValidationError(
                f"updated_symbols: {self.updated_symbols!r} must be >= 0"
            )
        if len(self.index_id) > 32:
            raise MessageValidationError(
                f"index_id: length {len(self.index_id)} exceeds max_len 32"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexRebalanceAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            timestamp=float(p["timestamp"]),
            updated_symbols=int(p.get("updated_symbols", 0)),
            index_id=str(p.get("index_id", "")),
            level=None if p.get("level") is None else float(p["level"]),
            divisor=None if p.get("divisor") is None else float(p["divisor"]),
            command_id=str(p.get("command_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "updated_symbols": self.updated_symbols,
        }
        if self.index_id:
            payload["index_id"] = self.index_id
        if self.level is not None:
            payload["level"] = self.level
        if self.divisor is not None:
            payload["divisor"] = self.divisor
        if self.command_id:
            payload["command_id"] = self.command_id
        return payload


def topic_index_rebalance_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"index.rebalance_ack.{gateway_id}"


def match_index_rebalance_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _INDEX_REBALANCE_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_index_rebalance_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexRebalanceAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_index_rebalance_ack(obj.gateway_id), obj.to_dict())


def make_index_rebalance_ack_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    timestamp: float,
    reason: str = "",
    updated_symbols: int = 0,
    index_id: str = "",
    level: float | None = None,
    divisor: float | None = None,
    command_id: str = "",
) -> list[bytes]:
    """Identical frames to ``make_index_rebalance_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "accepted": bool(accepted),
        "reason": str(reason),
        "timestamp": float(timestamp),
        "updated_symbols": int(updated_symbols),
    }
    if index_id:
        payload["index_id"] = str(index_id)
    if level is not None:
        payload["level"] = float(level)
    if divisor is not None:
        payload["divisor"] = float(divisor)
    if command_id:
        payload["command_id"] = str(command_id)
    return [
        topic_index_rebalance_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_index_rebalance_ack(frames: list[bytes]) -> "IndexRebalanceAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_index_rebalance_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_INDEX_REBALANCE_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = IndexRebalanceAck.from_dict(payload)
    obj.validate()
    return obj


def describe_index_rebalance_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_REBALANCE_ACK_FIELDS


TOPIC_INDEX_ERROR = "index.error.{gateway_id}"
PREFIX_INDEX_ERROR = "index.error."
_INDEX_ERROR_RE = re.compile("index\\.error\\.(?P<gateway_id>[^.]+)")


_INDEX_ERROR_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "Always false; present so every reply has the same first key.",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 512},
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class IndexError:
    """pm-index to requestor: the request could not be routed to an index at all.

    Distinct from a rejecting ack. An unknown index_id means pm-index cannot know which
    ack topic the caller is waiting on, so it answers on the one topic every index
    caller subscribes to. Once the index is known, a bad symbol or parameter comes back
    as accepted: false on the specific ack instead.
    """

    gateway_id: str
    accepted: bool
    reason: str
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexError":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            accepted=bool(p["accepted"]),
            reason=str(p["reason"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


def topic_index_error(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"index.error.{gateway_id}"


def match_index_error(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _INDEX_ERROR_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_index_error(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = IndexError.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_index_error(obj.gateway_id), obj.to_dict())


def make_index_error_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    reason: str,
    timestamp: float,
) -> list[bytes]:
    """Identical frames to ``make_index_error``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_index_error(gateway_id).encode(),
        _msg.dumps(
            {
                "accepted": bool(accepted),
                "reason": str(reason),
                "timestamp": float(timestamp),
            }
        ),
    ]


def parse_index_error(frames: list[bytes]) -> "IndexError":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_index_error(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_INDEX_ERROR!r}")
    payload = {**payload, "gateway_id": matched}
    obj = IndexError.from_dict(payload)
    obj.validate()
    return obj


def describe_index_error() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _INDEX_ERROR_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_INDEX_UPDATE,
    TOPIC_INDEX_HISTORY_REQUEST,
    TOPIC_INDEX_HISTORY,
    TOPIC_INDEX_CORP_ACTION,
    TOPIC_INDEX_CONSTITUENT_CHANGE,
    TOPIC_INDEX_REBALANCE,
    TOPIC_INDEX_CORP_ACTION_ACK,
    TOPIC_INDEX_CONSTITUENT_CHANGE_ACK,
    TOPIC_INDEX_REBALANCE_ACK,
    TOPIC_INDEX_ERROR,
)
