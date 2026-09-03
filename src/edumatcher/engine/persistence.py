"""
GTC order persistence — save/load resting GTC and DAY orders across restarts.
Book stats persistence — save/load per-symbol last buy/sell prices and prev_close.

File format: JSON array of Order.to_dict() entries (GTC and DAY orders).
             JSON object keyed by symbol (book stats).
Orders with TIF=GTC or TIF=DAY and status NEW/PARTIAL are persisted. A
process restart is not itself a day boundary (see
docs-design/EduMatcher-Revised-Quote-Persistence.md §12-§13): DAY orders are
saved here the same as GTC ones, and are only discarded at restore time if
their business day has already passed (Engine._restore_gtc). True
end-of-day expiry remains driven by the scheduler's transition to CLOSED.
"""

from __future__ import annotations

import logging
from typing import Any

import json
import os
import tempfile
from pathlib import Path

from edumatcher.models.combo import ComboOrder, ComboStatus
from edumatcher.models.order import Order, OrderStatus, TIF
from edumatcher.models.price import from_ticks

log = logging.getLogger(__name__)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* so a crash can never leave it truncated.

    ``Path.write_text`` truncates the target before writing, so an interrupted
    write leaves a partial file — and ``load_gtc_orders`` treats an unparseable
    file as an empty book, which silently discards every resting order. Writing
    to a temporary file in the same directory and renaming makes the
    replacement atomic: a reader sees either the whole previous file or the
    whole new one.

    This matters more now that the engine checkpoints periodically rather than
    only at shutdown: more writes means more windows in which to be killed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            # fsync before the rename, or the rename can land while the data
            # is still only in the page cache.
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_and_bump_run_seq(path: Path) -> int:
    """Return the next durable engine-run sequence, persisting it first.

    Corruption is fatal. Continuing after a lost or malformed run-sequence
    file would reissue trade ids that downstream stores treat as durable.
    """
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            current = int(data["run_seq"])
        except Exception as exc:
            raise RuntimeError(f"Corrupt run-sequence file {path}: {exc}") from exc
    else:
        current = 0
    next_seq = current + 1
    if next_seq > 999_999:
        raise RuntimeError(f"Engine run sequence exhausted at {next_seq}")
    _atomic_write_text(path, json.dumps({"run_seq": next_seq}, indent=2))
    return next_seq


def save_gtc_orders(orders: list[Order], path: Path) -> None:
    """Serialize resting GTC and DAY orders to *path*.

    TIF=DAY orders are included alongside TIF=GTC: a process restart is not
    a day boundary, so a resting DAY order must survive it the same as a GTC
    order does. The distinction between a same-day and a stale DAY order is
    applied at restore time (Engine._restore_gtc), not here.
    """
    gtc = [
        o.to_dict()
        for o in orders
        if o.tif in (TIF.GTC, TIF.DAY)
        and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
    ]
    _atomic_write_text(path, json.dumps(gtc, indent=2))


def load_gtc_orders(path: Path) -> list[Order]:
    """
    Load previously persisted GTC and DAY orders.

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
        log.error("Cannot parse GTC orders file %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        log.error(
            "GTC orders file %s has unexpected root type %s — expected list",
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
                "Skipping corrupt GTC order at index %d (id=%r): %s — "
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
    _atomic_write_text(path, json.dumps(stats, indent=2))


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
    _atomic_write_text(path, json.dumps(active, indent=2))


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
        log.error("Cannot parse GTC combos file %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        log.error(
            "GTC combos file %s has unexpected root type %s — expected list",
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
                "Skipping corrupt GTC combo at index %d (id=%r): %s — "
                "check %s for manual recovery",
                idx,
                combo_id,
                exc,
                path,
            )
    return combos
