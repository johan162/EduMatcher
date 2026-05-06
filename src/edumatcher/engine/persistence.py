"""
GTC order persistence — save/load resting GTC orders across trading days.
Book stats persistence — save/load per-symbol last buy/sell prices.

File format: JSON array of Order.to_dict() entries (GTC orders).
             JSON object keyed by symbol (book stats).
Only orders with TIF=GTC and status NEW/PARTIAL are persisted.
"""

from __future__ import annotations

from typing import Any

import json
from pathlib import Path

from edumatcher.models.combo import ComboOrder, ComboStatus
from edumatcher.models.order import Order, OrderStatus, TIF


def save_gtc_orders(orders: list[Order], path: Path) -> None:
    """Serialize resting GTC orders to *path*."""
    gtc = [
        o.to_dict()
        for o in orders
        if o.tif == TIF.GTC and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gtc, indent=2))


def load_gtc_orders(path: Path) -> list[Order]:
    """
    Load previously persisted GTC orders.
    Returns an empty list if the file does not exist or is malformed.
    Original timestamps are preserved so price-time priority carries over.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [Order.from_dict(d) for d in data]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Book statistics
# ---------------------------------------------------------------------------


def save_book_stats(
    books: dict[str, Any],  # dict[symbol, OrderBook]
    path: Path,
) -> None:
    """Persist per-symbol last_buy_price / last_sell_price."""
    stats: dict[str, dict[str, Any]] = {}
    for symbol, book in books.items():
        stats[symbol] = {
            "last_buy_price": book.last_buy_price,
            "last_sell_price": book.last_sell_price,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2))


def load_book_stats(path: Path) -> dict[str, dict[str, Any]]:
    """
    Load persisted book statistics.
    Returns an empty dict if the file does not exist or is malformed.
    Each value is {"last_buy_price": float|None, "last_sell_price": float|None}.
    """
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Combo-order persistence
# ---------------------------------------------------------------------------


def save_gtc_combos(combos: list[ComboOrder], path: Path) -> None:
    """Persist resting GTC combos that are still PENDING or PARTIALLY_MATCHED."""
    active = [
        c.to_dict()
        for c in combos
        if c.tif == TIF.GTC
        and c.status
        in (
            ComboStatus.PENDING,
            ComboStatus.PARTIALLY_MATCHED,
        )
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(active, indent=2))


def load_gtc_combos(path: Path) -> list[ComboOrder]:
    """
    Load previously persisted GTC combos.
    Returns an empty list if the file does not exist or is malformed.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [ComboOrder.from_dict(d) for d in data]
    except Exception:
        return []
