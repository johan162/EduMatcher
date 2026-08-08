"""Per-gateway session caches maintained from engine events."""

from __future__ import annotations

import time
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
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

#: Statuses after which an order can no longer change. Only these are eligible
#: for eviction — a resting order is live state whatever its age.
TERMINAL_ORDER_STATUSES = frozenset({"FILLED", "CANCELLED", "EXPIRED", "REJECTED"})


@dataclass
class SessionCaches:
    """Small in-memory read model for one engine gateway id."""

    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    quote_legs: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    known_symbols: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: order_id -> monotonic-ish wall time the order became terminal, used
    #: only for eviction. Kept beside `orders` rather than inside the order
    #: dicts so it never reaches the wire.
    terminal_at: dict[str, float] = field(default_factory=dict)

    def apply(self, topic: str, payload: dict[str, Any]) -> None:
        """Fold one engine event into the local cache."""
        if topic.startswith(ORDER_ACK_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                self._set_status(
                    order_id,
                    current,
                    "NEW" if payload.get("accepted") else "REJECTED",
                )
        elif topic.startswith(ORDER_FILL_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                self._set_status(
                    order_id,
                    current,
                    str(payload.get("status", current.get("status", "PARTIAL"))),
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
                self._set_status(order_id, current, "AMENDED")
        elif topic.startswith(ORDER_CANCELLED_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                self._set_status(order_id, current, "CANCELLED")
        elif topic.startswith(ORDER_EXPIRED_PREFIX):
            order_id = str(payload.get("order_id", ""))
            if order_id:
                current = self.orders.setdefault(order_id, {"order_id": order_id})
                current.update(payload)
                self._set_status(order_id, current, "EXPIRED")
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
        elif topic == TOPIC_TRADE_EXECUTED:
            symbol = str(payload.get("symbol", ""))
            price = payload.get("price")
            if symbol and isinstance(price, (int, float)):
                self.last_prices[symbol] = float(price)

    def _set_status(self, order_id: str, order: dict[str, Any], status: str) -> None:
        """Record a status transition, noting when it became terminal.

        The first terminal timestamp wins: a FILLED order that later receives
        a duplicate event should age from when it actually finished, not from
        the last message about it.
        """
        order["status"] = status
        if status in TERMINAL_ORDER_STATUSES:
            self.terminal_at.setdefault(order_id, time.time())
        else:
            self.terminal_at.pop(order_id, None)

    def evict_terminal_orders(
        self, retention_sec: int, now: float | None = None
    ) -> int:
        """Drop terminal orders older than *retention_sec*. Returns the count.

        Without this the cache grows for the lifetime of the process: nothing
        ever removed a filled or cancelled order. That was an invisible slow
        leak while the cache only backed `GET /orders`; it becomes a visible
        defect once the admin order table reads the same structure, because
        an operator would see this morning's fills in a table of "active"
        orders.

        Only *terminal* orders are evicted — a resting order is live state and
        must never disappear from the cache regardless of age. `retention_sec`
        of 0 disables eviction entirely.

        Positions are deliberately untouched: they are an aggregate, and
        forgetting the order that produced one would not un-do it.
        """
        if retention_sec <= 0:
            return 0
        cutoff = (now if now is not None else time.time()) - retention_sec
        stale = [
            order_id
            for order_id, at in self.terminal_at.items()
            if at < cutoff and order_id in self.orders
        ]
        for order_id in stale:
            del self.orders[order_id]
            del self.terminal_at[order_id]
        return len(stale)

    def status(self) -> dict[str, Any]:
        """Return a compact summary for the status endpoint."""
        return {
            "orders": len(self.orders),
            "quote_legs": len(self.quote_legs),
            "positions": self.positions,
            "known_symbols": sorted(self.known_symbols),
        }
