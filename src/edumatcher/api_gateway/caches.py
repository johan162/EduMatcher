"""Per-gateway session caches maintained from engine events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edumatcher.api_gateway.events import (
    ORDER_ACK_PREFIX,
    ORDER_AMENDED_PREFIX,
    ORDER_CANCELLED_PREFIX,
    ORDER_EXPIRED_PREFIX,
    ORDER_FILL_PREFIX,
    SYSTEM_SYMBOLS_PREFIX,
)


@dataclass
class SessionCaches:
    """Small in-memory read model for one engine gateway id."""

    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    quote_legs: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    known_symbols: dict[str, dict[str, Any]] = field(default_factory=dict)

    def apply(self, topic: str, payload: dict[str, Any]) -> None:
        """Fold one engine event into the local cache."""
        if topic.startswith(ORDER_ACK_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                current["status"] = "NEW" if payload.get("accepted") else "REJECTED"
        elif topic.startswith(ORDER_FILL_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                current["status"] = payload.get(
                    "status", current.get("status", "PARTIAL")
                )
            symbol = str(payload.get("symbol", ""))
            side = str(payload.get("side", ""))
            qty = int(payload.get("fill_qty", 0) or 0)
            if symbol and qty:
                signed = qty if side == "BUY" else -qty if side == "SELL" else 0
                self.positions[symbol] = self.positions.get(symbol, 0) + signed
        elif topic.startswith(ORDER_AMENDED_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                current["status"] = "AMENDED"
        elif topic.startswith(ORDER_CANCELLED_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                current["status"] = "CANCELLED"
        elif topic.startswith(ORDER_EXPIRED_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                current["status"] = "EXPIRED"
        elif topic.startswith("quote."):
            quote_id = str(payload.get("quote_id", ""))
            if quote_id:
                current = self.quote_legs.setdefault(quote_id, {"quote_id": quote_id})
                current.update(payload)
        elif topic.startswith(SYSTEM_SYMBOLS_PREFIX):
            symbols = payload.get("symbols", [])
            meta = payload.get("symbol_meta", {})
            if isinstance(symbols, list):
                for symbol in symbols:
                    sym = str(symbol).upper()
                    details = meta.get(sym, {}) if isinstance(meta, dict) else {}
                    self.known_symbols[sym] = (
                        details if isinstance(details, dict) else {}
                    )
        elif topic == "trade.executed":
            symbol = str(payload.get("symbol", ""))
            price = payload.get("price")
            if symbol and isinstance(price, (int, float)):
                self.last_prices[symbol] = float(price)

    def status(self) -> dict[str, Any]:
        """Return a compact summary for the status endpoint."""
        return {
            "orders": len(self.orders),
            "quote_legs": len(self.quote_legs),
            "positions": self.positions,
            "known_symbols": sorted(self.known_symbols),
        }
