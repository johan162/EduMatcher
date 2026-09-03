# GENERATED FROM spec/messages/auction.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``auction`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/auction.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "auction"
FAMILY_VERSION = 1


TOPIC_AUCTION_INDICATIVE = "auction.indicative.{symbol}"
PREFIX_AUCTION_INDICATIVE = "auction.indicative."
_AUCTION_INDICATIVE_RE = re.compile("auction\\.indicative\\.(?P<symbol>[^.]+)")
_AUCTION_INDICATIVE_PHASE_VALUES = ("OPENING_AUCTION", "CLOSING_AUCTION")
AuctionIndicativePhase = Literal["OPENING_AUCTION", "CLOSING_AUCTION"]
_AUCTION_INDICATIVE_IMBALANCE_SIDE_VALUES = ("BUY", "SELL")
AuctionIndicativeImbalanceSide = Literal["BUY", "SELL"]


_AUCTION_INDICATIVE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "phase",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Which call phase is running. These are the only two states `models/session.py::is_auction_phase` admits, and the producer returns early for every other one.",
        "values": _AUCTION_INDICATIVE_PHASE_VALUES,
    },
    {
        "name": "eq_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Indicative equilibrium price, or null if the book would not cross.",
        "constraints": {"gt": 0},
    },
    {
        "name": "eq_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Quantity that would execute. Zero is a true reading and is always emitted, unlike `eq_price`, which has no zero.",
        "constraints": {"ge": 0},
    },
    {
        "name": "imbalance_side",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Which side would be left unfilled. Absent when the book is balanced at the indicative price.",
        "values": _AUCTION_INDICATIVE_IMBALANCE_SIDE_VALUES,
    },
    {
        "name": "imbalance_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Surplus on `imbalance_side`; zero when balanced.",
        "constraints": {"ge": 0},
    },
)


@dataclass(frozen=True, slots=True)
class AuctionIndicative:
    """Engine to all: where one symbol would uncross if the call phase ended now.
    Published repeatedly while an opening or closing auction collects orders.

    The difference from `auction.result` is tense. That one reports what happened; this
    one reports what would happen if the phase ended now, and a client must not mistake
    the second for the first -- which is why `md_gateway` projects it to a CALF `INDIC`
    rather than an `AUCTION`. `eq_price` is null when the book would not cross at all.
    That is a real and informative state during a call phase -- nothing would trade yet
    -- and is not the same as a price of zero, so it is a null rather than an omission.
    Field names are shared with `circuit_breaker.extend`'s indicative deliberately. A
    reopening auction and a scheduled one are the same mechanism, and a client that
    learned to read one should not have to learn the other.
    """

    symbol: str
    phase: AuctionIndicativePhase
    eq_qty: int  # unit: shares
    imbalance_qty: int  # unit: shares
    eq_price: float | None = None  # unit: display_price
    imbalance_side: AuctionIndicativeImbalanceSide | None = None

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
        if self.phase not in _AUCTION_INDICATIVE_PHASE_VALUES:
            raise MessageValidationError(
                f"phase: {self.phase!r} is not one of {_AUCTION_INDICATIVE_PHASE_VALUES!r}"
            )
        if self.eq_price is not None:
            if self.eq_price <= 0:
                raise MessageValidationError(f"eq_price: {self.eq_price!r} must be > 0")
        if self.eq_qty < 0:
            raise MessageValidationError(f"eq_qty: {self.eq_qty!r} must be >= 0")
        if self.imbalance_side is not None:
            if self.imbalance_side not in _AUCTION_INDICATIVE_IMBALANCE_SIDE_VALUES:
                raise MessageValidationError(
                    f"imbalance_side: {self.imbalance_side!r} is not one of {_AUCTION_INDICATIVE_IMBALANCE_SIDE_VALUES!r}"
                )
        if self.imbalance_qty < 0:
            raise MessageValidationError(
                f"imbalance_qty: {self.imbalance_qty!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "AuctionIndicative":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            phase=cast(AuctionIndicativePhase, str(p["phase"])),
            eq_price=None if p.get("eq_price") is None else float(p["eq_price"]),
            eq_qty=int(p["eq_qty"]),
            imbalance_side=(
                None
                if p.get("imbalance_side") is None
                else cast(AuctionIndicativeImbalanceSide, str(p["imbalance_side"]))
            ),
            imbalance_qty=int(p["imbalance_qty"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "phase": self.phase,
            "eq_price": self.eq_price,
            "eq_qty": self.eq_qty,
            "imbalance_qty": self.imbalance_qty,
        }
        if self.imbalance_side is not None:
            payload["imbalance_side"] = self.imbalance_side
        return payload


def topic_auction_indicative(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"auction.indicative.{symbol}"


def match_auction_indicative(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _AUCTION_INDICATIVE_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_auction_indicative(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = AuctionIndicative.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_auction_indicative(obj.symbol), obj.to_dict())


def make_auction_indicative_unchecked(
    *,
    symbol: str,
    phase: AuctionIndicativePhase,
    eq_qty: int,
    imbalance_qty: int,
    eq_price: float | None = None,
    imbalance_side: AuctionIndicativeImbalanceSide | None = None,
) -> list[bytes]:
    """Identical frames to ``make_auction_indicative``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "symbol": str(symbol),
        "phase": str(phase),
        "eq_price": None if eq_price is None else float(eq_price),
        "eq_qty": int(eq_qty),
        "imbalance_qty": int(imbalance_qty),
    }
    if imbalance_side is not None:
        payload["imbalance_side"] = str(imbalance_side)
    return [
        topic_auction_indicative(symbol).encode(),
        _msg.dumps(payload),
    ]


def parse_auction_indicative(frames: list[bytes]) -> "AuctionIndicative":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_auction_indicative(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_AUCTION_INDICATIVE!r}"
        )
    payload = {**payload, "symbol": matched}
    obj = AuctionIndicative.from_dict(payload)
    obj.validate()
    return obj


def describe_auction_indicative() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _AUCTION_INDICATIVE_FIELDS


TOPIC_AUCTION_RESULT = "auction.result.{symbol}"
PREFIX_AUCTION_RESULT = "auction.result."
_AUCTION_RESULT_RE = re.compile("auction\\.result\\.(?P<symbol>[^.]+)")
_AUCTION_RESULT_IMBALANCE_SIDE_VALUES = ("BUY", "SELL")
AuctionResultImbalanceSide = Literal["BUY", "SELL"]
_AUCTION_RESULT_REASON_VALUES = ("SCHEDULED", "REOPEN", "RECOVERY", "BACKSTOP")
AuctionResultReason = Literal["SCHEDULED", "REOPEN", "RECOVERY", "BACKSTOP"]


_AUCTION_RESULT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "eq_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Uncross price, or null when there was no crossable interest.",
        "constraints": {"gt": 0},
    },
    {
        "name": "eq_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Quantity executed; zero when nothing crossed.",
        "constraints": {"ge": 0},
    },
    {
        "name": "trades_count",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "How many trades the uncross printed.",
        "constraints": {"ge": 0},
    },
    {
        "name": "imbalance_side",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Which side was left unfilled. Absent when the book was balanced at the uncross price.",
        "values": _AUCTION_RESULT_IMBALANCE_SIDE_VALUES,
    },
    {
        "name": "imbalance_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Surplus on `imbalance_side`; zero when balanced.",
        "constraints": {"ge": 0},
    },
    {
        "name": "reason",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Which of the four uncross paths produced this event.",
        "values": _AUCTION_RESULT_REASON_VALUES,
    },
)


@dataclass(frozen=True, slots=True)
class AuctionResult:
    """Engine to all: one symbol's uncross has completed. Published for every
    uncross, including the ones that printed nothing.

    `reason` says which uncross this was, because the four are otherwise
    indistinguishable to a consumer and a client cannot tell a circuit breaker reopening
    from the closing one: SCHEDULED - leaving an auction or other non-matching session
    phase REOPEN - a halted symbol reopening at the end of its halt RECOVERY - restored
    GTC orders uncrossed at engine startup BACKSTOP - the closing backstop forcing a
    still-halted symbol to reopen, printing at the corridor boundary rather than at the
    outlying equilibrium There is no persistent state to snapshot here, unlike TOP or
    DEPTH: every event is forwarded as its own independent CALF event.
    """

    symbol: str
    eq_qty: int  # unit: shares
    trades_count: int  # unit: dimensionless
    imbalance_qty: int  # unit: shares
    reason: AuctionResultReason
    eq_price: float | None = None  # unit: display_price
    imbalance_side: AuctionResultImbalanceSide | None = None

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
        if self.eq_price is not None:
            if self.eq_price <= 0:
                raise MessageValidationError(f"eq_price: {self.eq_price!r} must be > 0")
        if self.eq_qty < 0:
            raise MessageValidationError(f"eq_qty: {self.eq_qty!r} must be >= 0")
        if self.trades_count < 0:
            raise MessageValidationError(
                f"trades_count: {self.trades_count!r} must be >= 0"
            )
        if self.imbalance_side is not None:
            if self.imbalance_side not in _AUCTION_RESULT_IMBALANCE_SIDE_VALUES:
                raise MessageValidationError(
                    f"imbalance_side: {self.imbalance_side!r} is not one of {_AUCTION_RESULT_IMBALANCE_SIDE_VALUES!r}"
                )
        if self.imbalance_qty < 0:
            raise MessageValidationError(
                f"imbalance_qty: {self.imbalance_qty!r} must be >= 0"
            )
        if self.reason not in _AUCTION_RESULT_REASON_VALUES:
            raise MessageValidationError(
                f"reason: {self.reason!r} is not one of {_AUCTION_RESULT_REASON_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "AuctionResult":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            eq_price=None if p.get("eq_price") is None else float(p["eq_price"]),
            eq_qty=int(p["eq_qty"]),
            trades_count=int(p["trades_count"]),
            imbalance_side=(
                None
                if p.get("imbalance_side") is None
                else cast(AuctionResultImbalanceSide, str(p["imbalance_side"]))
            ),
            imbalance_qty=int(p["imbalance_qty"]),
            reason=cast(AuctionResultReason, str(p["reason"])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "eq_price": self.eq_price,
            "eq_qty": self.eq_qty,
            "trades_count": self.trades_count,
            "imbalance_qty": self.imbalance_qty,
            "reason": self.reason,
        }
        if self.imbalance_side is not None:
            payload["imbalance_side"] = self.imbalance_side
        return payload


def topic_auction_result(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"auction.result.{symbol}"


def match_auction_result(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _AUCTION_RESULT_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_auction_result(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = AuctionResult.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_auction_result(obj.symbol), obj.to_dict())


def make_auction_result_unchecked(
    *,
    symbol: str,
    eq_qty: int,
    trades_count: int,
    imbalance_qty: int,
    reason: AuctionResultReason,
    eq_price: float | None = None,
    imbalance_side: AuctionResultImbalanceSide | None = None,
) -> list[bytes]:
    """Identical frames to ``make_auction_result``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "symbol": str(symbol),
        "eq_price": None if eq_price is None else float(eq_price),
        "eq_qty": int(eq_qty),
        "trades_count": int(trades_count),
        "imbalance_qty": int(imbalance_qty),
        "reason": str(reason),
    }
    if imbalance_side is not None:
        payload["imbalance_side"] = str(imbalance_side)
    return [
        topic_auction_result(symbol).encode(),
        _msg.dumps(payload),
    ]


def parse_auction_result(frames: list[bytes]) -> "AuctionResult":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_auction_result(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_AUCTION_RESULT!r}")
    payload = {**payload, "symbol": matched}
    obj = AuctionResult.from_dict(payload)
    obj.validate()
    return obj


def describe_auction_result() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _AUCTION_RESULT_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (TOPIC_AUCTION_INDICATIVE, TOPIC_AUCTION_RESULT)
