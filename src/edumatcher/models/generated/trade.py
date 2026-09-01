# GENERATED FROM spec/messages/trade.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``trade`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/trade.yaml``; edit
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

FAMILY = "trade"
FAMILY_VERSION = 1


TOPIC_TRADE_EXECUTED = "trade.executed"
_TOPIC_TRADE_EXECUTED_BYTES = "trade.executed".encode()
_TRADE_EXECUTED_ID_RE = re.compile("^\\d{6}-\\d{9}$")
_TRADE_EXECUTED_SYMBOL_RE = re.compile("^[A-Z0-9._]+$")
_TRADE_EXECUTED_AGGRESSOR_SIDE_VALUES = ("BUY", "SELL", "AUCTION")


_TRADE_EXECUTED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Durable, sortable trade id. The prefix is the persisted engine-run sequence and the suffix is the per-run trade counter.",
        "constraints": {"max_len": 64, "pattern": "^\\d{6}-\\d{9}$"},
    },
    {
        "name": "run_seq",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Durable engine-run sequence used as the trade id prefix. A change in run_seq marks an engine restart explicitly for consumers.",
        "constraints": {"ge": 0},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Instrument the match occurred in.",
        "constraints": {"max_len": 16, "pattern": "^[A-Z0-9._]+$"},
    },
    {
        "name": "buy_order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Resting or aggressing order id on the buy side.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "sell_order_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Resting or aggressing order id on the sell side.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "buy_gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Gateway that submitted the buy order.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "sell_gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Gateway that submitted the sell order.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "price",
        "type": "float",
        "unit": "display_price",
        "required": True,
        "doc": "Execution price in display money, already converted from ticks by the publisher. Contrast trade_log.price, which is ticks - the mismatch this `unit` declaration exists to make reviewable.",
        "constraints": {"gt": 0},
    },
    {
        "name": "quantity",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "Matched quantity.",
        "constraints": {"gt": 0},
    },
    {
        "name": "aggressor_side",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Side that removed liquidity. AUCTION when both sides rested, which happens on an uncross print where there is no true aggressor.",
        "values": _TRADE_EXECUTED_AGGRESSOR_SIDE_VALUES,
    },
    {
        "name": "timestamp",
        "type": "float",
        "unit": "epoch_seconds",
        "required": True,
        "doc": "Match time in Unix epoch seconds. The engine divides its nanosecond clock by 1e9 at publish time.",
    },
    {
        "name": "tick_decimals",
        "type": "int",
        "unit": "dimensionless",
        "required": False,
        "doc": "Decimal scale for `price`; 1 tick = 10^-tick_decimals.",
        "constraints": {"ge": 0, "le": 8},
    },
)


@dataclass(frozen=True, slots=True)
class TradeExecuted:
    """Public print of a completed match. The authoritative record of what traded,
    consumed by statistics, clearing, index and market data.

    aggressor_side is AUCTION for uncross prints, where both sides rested and there is
    no true aggressor.
    """

    id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float  # unit: display_price
    quantity: int  # unit: shares
    aggressor_side: str
    timestamp: float  # unit: epoch_seconds
    run_seq: int = 0  # unit: dimensionless
    tick_decimals: int = 2  # unit: dimensionless

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
        if not _TRADE_EXECUTED_ID_RE.fullmatch(self.id):
            raise MessageValidationError(
                f"id: {self.id!r} does not match {_TRADE_EXECUTED_ID_RE.pattern!r}"
            )
        if self.run_seq < 0:
            raise MessageValidationError(f"run_seq: {self.run_seq!r} must be >= 0")
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if not _TRADE_EXECUTED_SYMBOL_RE.fullmatch(self.symbol):
            raise MessageValidationError(
                f"symbol: {self.symbol!r} does not match {_TRADE_EXECUTED_SYMBOL_RE.pattern!r}"
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
        if self.price <= 0:
            raise MessageValidationError(f"price: {self.price!r} must be > 0")
        if self.quantity <= 0:
            raise MessageValidationError(f"quantity: {self.quantity!r} must be > 0")
        if self.aggressor_side not in _TRADE_EXECUTED_AGGRESSOR_SIDE_VALUES:
            raise MessageValidationError(
                f"aggressor_side: {self.aggressor_side!r} is not one of {_TRADE_EXECUTED_AGGRESSOR_SIDE_VALUES!r}"
            )
        if self.tick_decimals < 0:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be >= 0"
            )
        if self.tick_decimals > 8:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be <= 8"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "TradeExecuted":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            run_seq=int(p.get("run_seq", 0)),
            symbol=str(p["symbol"]),
            buy_order_id=str(p["buy_order_id"]),
            sell_order_id=str(p["sell_order_id"]),
            buy_gateway_id=str(p["buy_gateway_id"]),
            sell_gateway_id=str(p["sell_gateway_id"]),
            price=float(p["price"]),
            quantity=int(p["quantity"]),
            aggressor_side=str(p.get("aggressor_side", "")),
            timestamp=float(p["timestamp"]),
            tick_decimals=int(p.get("tick_decimals", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "run_seq": self.run_seq,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_gateway_id": self.buy_gateway_id,
            "sell_gateway_id": self.sell_gateway_id,
            "price": self.price,
            "quantity": self.quantity,
            "aggressor_side": self.aggressor_side,
            "timestamp": self.timestamp,
            "tick_decimals": self.tick_decimals,
        }


def is_trade_executed(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_TRADE_EXECUTED


def make_trade_executed(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = TradeExecuted.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_TRADE_EXECUTED, obj.to_dict())


def make_trade_executed_unchecked(
    *,
    id: str,
    symbol: str,
    buy_order_id: str,
    sell_order_id: str,
    buy_gateway_id: str,
    sell_gateway_id: str,
    price: float,
    quantity: int,
    aggressor_side: str,
    timestamp: float,
    run_seq: int = 0,
    tick_decimals: int = 2,
) -> list[bytes]:
    """Identical frames to ``make_trade_executed``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_TRADE_EXECUTED_BYTES,
        _msg.dumps(
            {
                "id": str(id),
                "run_seq": int(run_seq),
                "symbol": str(symbol),
                "buy_order_id": str(buy_order_id),
                "sell_order_id": str(sell_order_id),
                "buy_gateway_id": str(buy_gateway_id),
                "sell_gateway_id": str(sell_gateway_id),
                "price": float(price),
                "quantity": int(quantity),
                "aggressor_side": str(aggressor_side),
                "timestamp": float(timestamp),
                "tick_decimals": int(tick_decimals),
            }
        ),
    ]


def parse_trade_executed(frames: list[bytes]) -> "TradeExecuted":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = TradeExecuted.from_dict(payload)
    obj.validate()
    return obj


def describe_trade_executed() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _TRADE_EXECUTED_FIELDS


MSGTYPE_TRADE_EXECUTED_CALF = "TRADE"


def project_trade_executed_calf(
    payload: Mapping[str, Any],
) -> dict[str, str]:
    """Project a bus payload onto the CALF TRADE field map.

    Reads **only** the fields this transport carries, so a caller needs nothing the
    projection does not use. That is what makes this a projection rather than a rename
    of the whole message: a gateway feeding this transport should not have to hold
    fields the transport drops (design section 4.6).

    Values are coerced to their declared types first, so this and the typed binding
    never disagree. The gateway supplies CH, SYM, SEQ, TS in its own envelope; they are
    not payload keys.
    """
    return {
        "PX": str(float(payload["price"])),
        "QTY": str(int(payload["quantity"])),
        "SIDE": str(payload.get("aggressor_side", "")).upper(),
    }


def parse_trade_executed_calf(
    fields: Mapping[str, str],
) -> "TradeExecuted":
    """Rebuild this message from a CALF payload field map.

    Only the projected fields can be recovered; anything this transport does not carry
    takes its declared default. Coerces without validating, like ``from_dict`` (design
    section 5.1.1).
    """
    return TradeExecuted(
        id="",
        run_seq=0,
        symbol="",
        buy_order_id="",
        sell_order_id="",
        buy_gateway_id="",
        sell_gateway_id="",
        price=float(fields["PX"]),
        quantity=int(fields["QTY"]),
        aggressor_side=str(fields["SIDE"]),
        timestamp=0.0,
        tick_decimals=2,
    )


FAMILY_TOPICS: tuple[str, ...] = (TOPIC_TRADE_EXECUTED,)
