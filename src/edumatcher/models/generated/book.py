# GENERATED FROM spec/messages/book.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``book`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/book.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "book"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class BookLevel:
    """One aggregated price level. Iceberg orders contribute only their displayed
    quantity, so `qty` is what a viewer should show rather than what is actually
    resting.
    """

    price: float  # unit: display_price
    qty: int  # unit: shares
    count: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        return None

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "BookLevel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            price=float(p["price"]),
            qty=int(p["qty"]),
            count=int(p["count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "price": self.price,
            "qty": self.qty,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class RecentTrade:
    """One entry of the book's trade tape. A trimmed view of the public
    trade.executed print - the last five, carried with the snapshot so a viewer
    that has just subscribed has some history to draw.
    """

    id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float  # unit: display_price
    quantity: int  # unit: shares
    timestamp: float  # unit: epoch_seconds

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 64:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.buy_order_id) > 64:
            raise MessageValidationError(
                f"buy_order_id: length {len(self.buy_order_id)} exceeds max_len 64"
            )
        if len(self.sell_order_id) > 64:
            raise MessageValidationError(
                f"sell_order_id: length {len(self.sell_order_id)} exceeds max_len 64"
            )
        if len(self.buy_gateway_id) > 32:
            raise MessageValidationError(
                f"buy_gateway_id: length {len(self.buy_gateway_id)} exceeds max_len 32"
            )
        if len(self.sell_gateway_id) > 32:
            raise MessageValidationError(
                f"sell_gateway_id: length {len(self.sell_gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RecentTrade":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            symbol=str(p["symbol"]),
            buy_order_id=str(p["buy_order_id"]),
            sell_order_id=str(p["sell_order_id"]),
            buy_gateway_id=str(p["buy_gateway_id"]),
            sell_gateway_id=str(p["sell_gateway_id"]),
            price=float(p["price"]),
            quantity=int(p["quantity"]),
            timestamp=float(p["timestamp"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_gateway_id": self.buy_gateway_id,
            "sell_gateway_id": self.sell_gateway_id,
            "price": self.price,
            "quantity": self.quantity,
            "timestamp": self.timestamp,
        }


TOPIC_BOOK_SNAPSHOT = "book.{symbol}"
PREFIX_BOOK_SNAPSHOT = "book."
_BOOK_SNAPSHOT_RE = re.compile("book\\.(?P<symbol>[^.]+)")


_BOOK_SNAPSHOT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "tick_decimals",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "The tick scale the display prices here were produced at. Subscribers that store prices exactly need it to convert back to integer ticks; without it they must guess, and guessing 2 for a 4-decimal symbol rounds the price away.",
    },
    {
        "name": "bids",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Descending by price.",
    },
    {
        "name": "asks",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Ascending by price.",
    },
    {
        "name": "last_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "Null until the instrument has traded.",
    },
    {
        "name": "last_qty",
        "type": "int",
        "unit": "shares",
        "required": False,
        "doc": "",
    },
    {
        "name": "last_buy_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "",
    },
    {
        "name": "last_sell_price",
        "type": "float",
        "unit": "display_price",
        "required": False,
        "doc": "",
    },
    {
        "name": "recent_trades",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "The last five prints, oldest first.",
    },
)


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """Broadcast an aggregated view of one instrument's order book, on a timer. What
    every viewer and terminal renders.

    Every key is always present; the four last_* fields carry null on a book that has
    not traded. The payload is OrderBook.snapshot() exactly.
    """

    symbol: str
    tick_decimals: int  # unit: dimensionless
    bids: list[BookLevel]
    asks: list[BookLevel]
    recent_trades: list[RecentTrade]
    last_price: float | None = None  # unit: display_price
    last_qty: int | None = None  # unit: shares
    last_buy_price: float | None = None  # unit: display_price
    last_sell_price: float | None = None  # unit: display_price

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
        for bids_item in self.bids:
            bids_item.validate()
        for asks_item in self.asks:
            asks_item.validate()
        for recent_trades_item in self.recent_trades:
            recent_trades_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "BookSnapshot":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            tick_decimals=int(p["tick_decimals"]),
            bids=[BookLevel.from_dict(item) for item in p["bids"]],
            asks=[BookLevel.from_dict(item) for item in p["asks"]],
            last_price=None if p.get("last_price") is None else float(p["last_price"]),
            last_qty=None if p.get("last_qty") is None else int(p["last_qty"]),
            last_buy_price=(
                None if p.get("last_buy_price") is None else float(p["last_buy_price"])
            ),
            last_sell_price=(
                None
                if p.get("last_sell_price") is None
                else float(p["last_sell_price"])
            ),
            recent_trades=[RecentTrade.from_dict(item) for item in p["recent_trades"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "tick_decimals": self.tick_decimals,
            "bids": [item.to_dict() for item in self.bids],
            "asks": [item.to_dict() for item in self.asks],
            "last_price": self.last_price,
            "last_qty": self.last_qty,
            "last_buy_price": self.last_buy_price,
            "last_sell_price": self.last_sell_price,
            "recent_trades": [item.to_dict() for item in self.recent_trades],
        }


def topic_book_snapshot(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"book.{symbol}"


def match_book_snapshot(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _BOOK_SNAPSHOT_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_book_snapshot(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = BookSnapshot.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_book_snapshot(obj.symbol), obj.to_dict())


def parse_book_snapshot(frames: list[bytes]) -> "BookSnapshot":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_book_snapshot(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_BOOK_SNAPSHOT!r}")
    payload = {**payload, "symbol": matched}
    obj = BookSnapshot.from_dict(payload)
    obj.validate()
    return obj


def describe_book_snapshot() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _BOOK_SNAPSHOT_FIELDS


TOPIC_BOOK_SNAPSHOT_REQUEST = "book.snapshot_request"
_TOPIC_BOOK_SNAPSHOT_REQUEST_BYTES = "book.snapshot_request".encode()


_BOOK_SNAPSHOT_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
)


@dataclass(frozen=True, slots=True)
class BookSnapshotRequest:
    """Ask the engine to publish one symbol's book immediately."""

    symbol: str

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

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "BookSnapshotRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
        }


def is_book_snapshot_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_BOOK_SNAPSHOT_REQUEST


def make_book_snapshot_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = BookSnapshotRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_BOOK_SNAPSHOT_REQUEST, obj.to_dict())


def make_book_snapshot_request_unchecked(
    *,
    symbol: str,
) -> list[bytes]:
    """Identical frames to ``make_book_snapshot_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_BOOK_SNAPSHOT_REQUEST_BYTES,
        _msg.dumps(
            {
                "symbol": str(symbol),
            }
        ),
    ]


def parse_book_snapshot_request(frames: list[bytes]) -> "BookSnapshotRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = BookSnapshotRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_book_snapshot_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _BOOK_SNAPSHOT_REQUEST_FIELDS


TOPIC_DEPTH = "depth.{symbol}"
PREFIX_DEPTH = "depth."
_DEPTH_RE = re.compile("depth\\.(?P<symbol>[^.]+)")


_DEPTH_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 16},
    },
    {
        "name": "mid_price_ticks",
        "type": "ticks",
        "unit": "ticks",
        "required": True,
        "doc": "The last trade price, in ticks; the band is centred here.",
    },
    {
        "name": "mid_price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "",
    },
    {
        "name": "tolerance_ticks",
        "type": "ticks",
        "unit": "ticks",
        "required": True,
        "doc": "Half-width of the band, in ticks.",
    },
    {
        "name": "bid_depth",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Total resting size between mid - tolerance and mid.",
    },
    {
        "name": "ask_depth",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Total resting size between mid and mid + tolerance.",
    },
    {
        "name": "imbalance",
        "type": "float",
        "unit": "dimensionless",
        "required": True,
        "doc": "(bid - ask) / total, in [-1, 1]; positive means more bids.",
        "constraints": {"ge": -1, "le": 1},
    },
    {
        "name": "microprice",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Imbalance-weighted mid; falls back to mid_price.",
    },
    {
        "name": "cost_to_move",
        "type": "float",
        "unit": "money",
        "required": True,
        "doc": "Display notional a buyer must spend to sweep every ask in the band. Summed in ticks and converted once, not per level.",
    },
)


@dataclass(frozen=True, slots=True)
class Depth:
    """Book-depth metrics within a tolerance band of the last trade: how much size
    sits nearby, which way it leans, and what it costs to move.

    Not published at all for a book with no last trade - depth_snapshot returns an empty
    dict and the engine skips it - so every field here is required rather than nullable.
    """

    symbol: str
    mid_price_ticks: int  # unit: ticks
    mid_price: float  # unit: display_price
    tolerance_ticks: int  # unit: ticks
    bid_depth: int  # unit: shares
    ask_depth: int  # unit: shares
    imbalance: float  # unit: dimensionless
    microprice: float  # unit: display_price
    cost_to_move: float  # unit: money

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
        if self.imbalance < -1:
            raise MessageValidationError(f"imbalance: {self.imbalance!r} must be >= -1")
        if self.imbalance > 1:
            raise MessageValidationError(f"imbalance: {self.imbalance!r} must be <= 1")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Depth":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            mid_price_ticks=int(p["mid_price_ticks"]),
            mid_price=float(p["mid_price"]),
            tolerance_ticks=int(p["tolerance_ticks"]),
            bid_depth=int(p["bid_depth"]),
            ask_depth=int(p["ask_depth"]),
            imbalance=float(p["imbalance"]),
            microprice=float(p["microprice"]),
            cost_to_move=float(p["cost_to_move"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "mid_price_ticks": self.mid_price_ticks,
            "mid_price": self.mid_price,
            "tolerance_ticks": self.tolerance_ticks,
            "bid_depth": self.bid_depth,
            "ask_depth": self.ask_depth,
            "imbalance": self.imbalance,
            "microprice": self.microprice,
            "cost_to_move": self.cost_to_move,
        }


def topic_depth(symbol: str) -> str:
    """Build this message's topic without a string literal."""
    return f"depth.{symbol}"


def match_depth(topic: str) -> str | None:
    """Return ``symbol`` when ``topic`` matches, else None."""
    m = _DEPTH_RE.fullmatch(topic)
    return m.group("symbol") if m else None


def make_depth(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Depth.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_depth(obj.symbol), obj.to_dict())


def make_depth_unchecked(
    *,
    symbol: str,
    mid_price_ticks: int,
    mid_price: float,
    tolerance_ticks: int,
    bid_depth: int,
    ask_depth: int,
    imbalance: float,
    microprice: float,
    cost_to_move: float,
) -> list[bytes]:
    """Identical frames to ``make_depth``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_depth(symbol).encode(),
        _msg.dumps(
            {
                "symbol": str(symbol),
                "mid_price_ticks": int(mid_price_ticks),
                "mid_price": float(mid_price),
                "tolerance_ticks": int(tolerance_ticks),
                "bid_depth": int(bid_depth),
                "ask_depth": int(ask_depth),
                "imbalance": float(imbalance),
                "microprice": float(microprice),
                "cost_to_move": float(cost_to_move),
            }
        ),
    ]


def parse_depth(frames: list[bytes]) -> "Depth":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_depth(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_DEPTH!r}")
    payload = {**payload, "symbol": matched}
    obj = Depth.from_dict(payload)
    obj.validate()
    return obj


def describe_depth() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _DEPTH_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_BOOK_SNAPSHOT,
    TOPIC_BOOK_SNAPSHOT_REQUEST,
    TOPIC_DEPTH,
)
