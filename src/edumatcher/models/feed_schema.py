"""
Shared PUB-feed payload schemas.

These dataclasses define the canonical payload shape for the cross-process
topics consumed by clearing.  They make the contract explicit in one place and
document units per field:

- trade.executed:
  - price: display price (float, not ticks)
  - timestamp: Unix epoch seconds (float, not ns)
  - tick_decimals: decimal scale for display<->ticks conversion
- system.eod:
  - books[*].last_price / bids[*].price / asks[*].price: display price (float)
- session.state:
  - state / prev_state: phase labels
- system.gateway_auth.{id}:
  - connect lifecycle payload
- system.gateway_bye.{id}:
  - disconnect lifecycle payload
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class TradeExecutedPayload:
    """Payload for topic ``trade.executed``.

    Units:
    - ``price`` is display float.
    - ``timestamp`` is Unix epoch seconds (float).
    """

    id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float
    quantity: int
    aggressor_side: str
    timestamp: float
    tick_decimals: int = 2

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TradeExecutedPayload":
        return cls(
            id=str(payload["id"]),
            symbol=str(payload["symbol"]),
            buy_order_id=str(payload["buy_order_id"]),
            sell_order_id=str(payload["sell_order_id"]),
            buy_gateway_id=str(payload["buy_gateway_id"]),
            sell_gateway_id=str(payload["sell_gateway_id"]),
            price=float(payload["price"]),
            quantity=int(payload["quantity"]),
            aggressor_side=str(payload.get("aggressor_side", "")),
            timestamp=float(payload["timestamp"]),
            tick_decimals=int(payload.get("tick_decimals", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
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


@dataclass(frozen=True)
class BookLevelPayload:
    """One price level inside ``system.eod`` book snapshots.

    Unit: ``price`` is display float when present.
    """

    price: float | None = None
    qty: int = 0
    count: int = 0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BookLevelPayload":
        raw_price = payload.get("price")
        price = float(raw_price) if raw_price is not None else None
        return cls(
            price=price,
            qty=int(payload.get("qty", 0)),
            count=int(payload.get("count", 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "qty": self.qty,
            "count": self.count,
        }
        if self.price is not None:
            result["price"] = self.price
        return result


@dataclass(frozen=True)
class EodBookPayload:
    """One symbol book snapshot entry in ``system.eod``.

    Unit: ``last_price`` and level prices are display floats.
    """

    symbol: str
    last_price: float | None = None
    bids: list[BookLevelPayload] = field(default_factory=list)
    asks: list[BookLevelPayload] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EodBookPayload":
        raw_last = payload.get("last_price")
        last_price = float(raw_last) if raw_last is not None else None
        bids = [
            BookLevelPayload.from_dict(level)
            for level in payload.get("bids", [])
            if isinstance(level, Mapping)
        ]
        asks = [
            BookLevelPayload.from_dict(level)
            for level in payload.get("asks", [])
            if isinstance(level, Mapping)
        ]
        return cls(
            symbol=str(payload.get("symbol", "")),
            last_price=last_price,
            bids=bids,
            asks=asks,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "symbol": self.symbol,
            "bids": [b.to_dict() for b in self.bids],
            "asks": [a.to_dict() for a in self.asks],
        }
        if self.last_price is not None:
            result["last_price"] = self.last_price
        return result


@dataclass(frozen=True)
class SystemEodPayload:
    """Payload for topic ``system.eod``."""

    books: list[EodBookPayload]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SystemEodPayload":
        books = [
            EodBookPayload.from_dict(book)
            for book in payload.get("books", [])
            if isinstance(book, Mapping)
        ]
        return cls(books=books)

    def to_dict(self) -> dict[str, Any]:
        return {"books": [book.to_dict() for book in self.books]}


@dataclass(frozen=True)
class SessionStatePayload:
    """Payload for topic ``session.state``."""

    state: str
    prev_state: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SessionStatePayload":
        return cls(
            state=str(payload.get("state", "")),
            prev_state=str(payload.get("prev_state", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {"state": self.state}
        if self.prev_state:
            result["prev_state"] = self.prev_state
        return result


@dataclass(frozen=True)
class GatewayAuthPayload:
    """Payload for topic ``system.gateway_auth.{gateway_id}``."""

    gateway_id: str
    accepted: bool
    reason: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GatewayAuthPayload":
        return cls(
            gateway_id=str(payload.get("gateway_id", "")),
            accepted=bool(payload.get("accepted", False)),
            reason=str(payload.get("reason", "")),
            description=str(payload.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gateway_id": self.gateway_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "description": self.description,
        }


@dataclass(frozen=True)
class GatewayByePayload:
    """Payload for topic ``system.gateway_bye.{gateway_id}``."""

    gateway_id: str
    reason: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GatewayByePayload":
        return cls(
            gateway_id=str(payload.get("gateway_id", "")),
            reason=str(payload.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"gateway_id": self.gateway_id, "reason": self.reason}
