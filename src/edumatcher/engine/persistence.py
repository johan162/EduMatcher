"""
GTC order persistence — save/load resting GTC orders across trading days.
Book stats persistence — save/load per-symbol last buy/sell prices and prev_close.

File format: JSON array of Order.to_dict() entries (GTC orders).
             JSON object keyed by symbol (book stats).
Only orders with TIF=GTC and status NEW/PARTIAL are persisted.
"""

from __future__ import annotations

import logging
from typing import Any

import json
from pathlib import Path

from edumatcher.models.combo import ComboOrder, ComboStatus
from edumatcher.models.order import Order, OrderStatus, TIF
from edumatcher.models.price import from_ticks

log = logging.getLogger(__name__)


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

    - Returns an empty list if the file does not exist.
    - Returns an empty list if the file cannot be parsed as a JSON array
      (truncated, binary garbage, wrong root type).
    - Individual corrupt entries are logged at CRITICAL level and skipped;
      the remaining valid orders are still returned so the engine can start.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.error("[PERSISTENCE] Cannot parse GTC orders file %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        log.error(
            "[PERSISTENCE] GTC orders file %s has unexpected root type %s — expected list",
            path,
            type(data).__name__,
        )
        return []
    orders: list[Order] = []
    for idx, d in enumerate(data):
        try:
            orders.append(Order.from_dict(d))
        except Exception as exc:
            order_id = (
                d.get("id", "<unknown>") if isinstance(d, dict) else "<not a dict>"
            )
            log.critical(
                "[PERSISTENCE] Skipping corrupt GTC order at index %d (id=%r): %s — "
                "check %s for manual recovery",
                idx,
                order_id,
                exc,
                path,
            )
    return orders


# ---------------------------------------------------------------------------
# Book statistics
# ---------------------------------------------------------------------------


def save_book_stats(
    books: dict[str, Any],  # dict[symbol, OrderBook]
    path: Path,
) -> None:
    """Persist per-symbol last_buy_price / last_sell_price / prev_close."""
    stats: dict[str, dict[str, Any]] = {}
    for symbol, book in books.items():
        prev_close = (
            from_ticks(book.last_trade_price, symbol)
            if book.last_trade_price is not None
            else None
        )
        # Persist last buy/sell as *display* floats (not raw ticks) so the
        # load path — which does to_ticks(float(...)) — round-trips exactly.
        # Writing raw ticks here caused #2: to_ticks re-multiplied by
        # 10^tick_decimals, inflating references 10^N× on restart.
        stats[symbol] = {
            "last_buy_price": (
                from_ticks(book.last_buy_price, symbol)
                if book.last_buy_price is not None
                else None
            ),
            "last_sell_price": (
                from_ticks(book.last_sell_price, symbol)
                if book.last_sell_price is not None
                else None
            ),
            "prev_close": prev_close,
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

    - Returns an empty list if the file does not exist or is unparseable.
    - Individual corrupt entries are logged at CRITICAL level and skipped.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.error("[PERSISTENCE] Cannot parse GTC combos file %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        log.error(
            "[PERSISTENCE] GTC combos file %s has unexpected root type %s — expected list",
            path,
            type(data).__name__,
        )
        return []
    combos: list[ComboOrder] = []
    for idx, d in enumerate(data):
        try:
            combos.append(ComboOrder.from_dict(d))
        except Exception as exc:
            combo_id = (
                d.get("id", "<unknown>") if isinstance(d, dict) else "<not a dict>"
            )
            log.critical(
                "[PERSISTENCE] Skipping corrupt GTC combo at index %d (id=%r): %s — "
                "check %s for manual recovery",
                idx,
                combo_id,
                exc,
                path,
            )
    return combos
