"""
GTC order persistence — save/load resting GTC and DAY orders across restarts.
Book stats persistence — save/load per-symbol last buy/sell prices and prev_close.

File format: JSON array of Order.to_dict() entries (GTC and DAY orders),
             each with the order's ``cum_notional_ticks`` beside them.
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
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from edumatcher.engine.circuit_breaker import CircuitBreakerState
from edumatcher.models.clock import now_ns
from edumatcher.models.combo import ComboOrder, ComboStatus
from edumatcher.models.order import Order, OrderStatus, TIF
from edumatcher.models.price import from_ticks

log = logging.getLogger(__name__)


def atomic_write_text(path: Path, text: str) -> None:
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
    atomic_write_text(path, json.dumps({"run_seq": next_seq}, indent=2))
    return next_seq


def save_gtc_orders(orders: list[Order], path: Path) -> None:
    """Serialize resting GTC and DAY orders to *path*.

    TIF=DAY orders are included alongside TIF=GTC: a process restart is not
    a day boundary, so a resting DAY order must survive it the same as a GTC
    order does. The distinction between a same-day and a stale DAY order is
    applied at restore time (Engine._restore_gtc), not here.
    """
    gtc = [
        {**o.to_dict(), "cum_notional_ticks": o.cum_notional_ticks}
        for o in orders
        if o.tif in (TIF.GTC, TIF.DAY)
        and o.status in (OrderStatus.NEW, OrderStatus.PARTIAL)
    ]
    atomic_write_text(path, json.dumps(gtc, indent=2))


def keep_corrupt_copy(path: Path) -> Path:
    """Copy an unreadable persistence file aside before the engine overwrites it.

    The engine's first checkpoint rewrites ``path`` seconds after startup, so
    whatever could not be restored would otherwise be lost for good. The copy
    is ``<name>.corrupt-<UTC timestamp>`` beside it. A failed copy raises: the
    engine then does not start, rather than start and destroy the evidence.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    copy = path.with_name(f"{path.name}.corrupt-{stamp}")
    shutil.copy2(path, copy)
    return copy


_MAX_TS_NS = 2**63 - 1  # datetime.fromtimestamp overflows far above this


def _is_tick(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check(ok: bool, field: str, value: Any) -> None:
    if not ok:
        raise ValueError(f"bad {field}: {value!r}")


def _checked_order(o: Order) -> Order:
    """Refuse an order whose fields the restore uses before (or without) the
    book's guard: ``from_dict`` copies values as they are, unchecked."""
    for name in ("id", "symbol", "gateway_id"):
        _check(isinstance(getattr(o, name), str), name, getattr(o, name))
    for name in ("oco_group_id", "quote_id"):
        value = getattr(o, name)
        _check(value is None or isinstance(value, str), name, value)
    for name in ("price_ticks", "stop_price_ticks"):
        value = getattr(o, name)
        _check(value is None or _is_tick(value), name, value)
    _check(_is_tick(o.quantity) and o.quantity > 0, "quantity", o.quantity)
    _check(
        _is_tick(o.remaining_qty) and 0 < o.remaining_qty <= o.quantity,
        "remaining_qty",
        o.remaining_qty,
    )
    _check(_is_tick(o.ts_ns) and 0 <= o.ts_ns <= _MAX_TS_NS, "ts_ns", o.ts_ns)
    _check(_is_tick(o.arrival_seq), "arrival_seq", o.arrival_seq)
    return o


def _checked_combo(c: ComboOrder) -> ComboOrder:
    """As :func:`_checked_order`, for the fields the restore reads off a combo."""
    _check(
        _is_tick(c.timestamp) and 0 <= c.timestamp <= _MAX_TS_NS,
        "timestamp",
        c.timestamp,
    )
    ids: Any = c.child_order_ids  # as the file had it, whatever the annotation
    _check(
        isinstance(ids, list) and all(isinstance(i, str) for i in ids),
        "child_order_ids",
        ids,
    )
    return c


def load_gtc_orders(path: Path) -> list[Order]:
    """
    Load previously persisted GTC and DAY orders.

    - Returns an empty list if the file does not exist.
    - Returns an empty list if the file cannot be parsed as a JSON array
      (truncated, binary garbage, wrong root type).
    - Individual corrupt entries (unparseable, or a field of the wrong type
      or range, see :func:`_checked_order`) are logged at CRITICAL level and
      skipped; the remaining valid orders are still returned so the engine
      can start.
    - Either way the file is first copied aside by :func:`keep_corrupt_copy`,
      since the engine's first checkpoint overwrites it.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.critical(
            "Cannot parse GTC orders file %s: %s — none restored; the file is kept as %s",
            path,
            exc,
            keep_corrupt_copy(path),
        )
        return []
    if not isinstance(data, list):
        log.critical(
            "GTC orders file %s has unexpected root type %s — expected list; "
            "none restored; the file is kept as %s",
            path,
            type(data).__name__,
            keep_corrupt_copy(path),
        )
        return []
    orders: list[Order] = []
    kept: Path | None = None
    for idx, d in enumerate(data):
        try:
            orders.append(_checked_order(Order.from_dict(d)))
        except Exception as exc:
            order_id = (
                d.get("id", "<unknown>") if isinstance(d, dict) else "<not a dict>"
            )
            if kept is None:
                kept = keep_corrupt_copy(path)
            log.critical(
                "Skipping corrupt GTC order at index %d (id=%r): %s — "
                "the original file is kept as %s",
                idx,
                order_id,
                exc,
                kept,
            )
    return orders


# ---------------------------------------------------------------------------
# Book statistics
# ---------------------------------------------------------------------------


def save_book_stats(
    books: dict[str, Any],  # dict[symbol, OrderBook]
    breakers: dict[str, CircuitBreakerState],
    path: Path,
) -> None:
    """Persist per-symbol last_buy_price / last_sell_price / prev_close, and
    each circuit breaker's reference window (``cb_window``: when it was
    saved, its trades in ticks, its reference), so a restart the same day
    goes on with the reference the market had."""
    saved_ns = now_ns()
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
        cb = breakers.get(symbol)
        if cb is not None:
            stats[symbol]["cb_window"] = {
                "saved_ns": saved_ns,
                "trades": [[ts, price] for ts, price in cb.trade_history],
                "reference_price": cb.reference_price,
            }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(stats, indent=2))


_PRICE_KEYS = ("last_buy_price", "last_sell_price", "prev_close")


def _is_price(value: Any) -> bool:
    """A display price as ``save_book_stats`` writes it: a positive finite
    number (``bool`` is an ``int`` to Python, not a price)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _is_cb_window(window: Any) -> bool:
    """``cb_window`` as ``save_book_stats`` writes it: ``saved_ns``, the
    ``trades`` as ``[ts_ns, price_ticks]`` pairs, ``reference_price`` in
    ticks or null."""
    if not isinstance(window, dict):
        return False
    trades = window.get("trades")
    reference = window.get("reference_price")
    return (
        _is_tick(window.get("saved_ns"))
        and isinstance(trades, list)
        and all(
            isinstance(t, list) and len(t) == 2 and all(_is_tick(v) for v in t)
            for t in trades
        )
        and (reference is None or _is_tick(reference))
    )


def load_book_stats(path: Path) -> tuple[dict[str, dict[str, Any]], int]:
    """
    Load persisted book statistics: ``(stats, failed)``.

    ``stats`` maps symbol to the entry ``save_book_stats`` wrote:

    - ``last_buy_price``, ``last_sell_price``, ``prev_close``: display price
      (positive finite number) or null; a missing key is null.
    - ``cb_window`` (only for a symbol with a breaker): ``saved_ns`` (int),
      ``trades`` (list of ``[ts_ns, price_ticks]`` int pairs),
      ``reference_price`` (ticks or null).

    Per-entry policy, so that file *content* can never stop the engine:

    - No file: ``({}, 0)``.
    - Unparseable, or a root that is not an object: ``({}, 1)``.
    - An entry that is not an object, or has a bad price: the symbol is
      skipped (its book starts from the config seed).
    - A bad ``cb_window``: only the window is dropped; the breaker is then
      seeded from the last price, as on a new day.

    Each failure is logged at CRITICAL and counted in ``failed`` (one per
    symbol), which ``system.startup_recovery`` reports as
    ``failed_book_stats``. Either way the file is first copied aside by
    :func:`keep_corrupt_copy`, since the engine's first checkpoint
    overwrites it.
    """
    if not path.exists():
        return {}, 0
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.critical(
            "Cannot parse book statistics file %s: %s — none restored; "
            "the file is kept as %s",
            path,
            exc,
            keep_corrupt_copy(path),
        )
        return {}, 1
    if not isinstance(data, dict):
        log.critical(
            "Book statistics file %s has unexpected root type %s — expected "
            "object; none restored; the file is kept as %s",
            path,
            type(data).__name__,
            keep_corrupt_copy(path),
        )
        return {}, 1
    stats: dict[str, dict[str, Any]] = {}
    failed = 0
    kept: Path | None = None
    for symbol, entry in data.items():
        prices_ok = isinstance(entry, dict) and all(
            entry.get(k) is None or _is_price(entry.get(k)) for k in _PRICE_KEYS
        )
        window_ok = prices_ok and (
            "cb_window" not in entry or _is_cb_window(entry["cb_window"])
        )
        if window_ok:
            stats[symbol] = entry
            continue
        failed += 1
        if kept is None:
            kept = keep_corrupt_copy(path)
        if not prices_ok:
            log.critical(
                "Skipping corrupt book statistics for %s — the original file is kept as %s",
                symbol,
                kept,
            )
        else:
            stats[symbol] = {k: v for k, v in entry.items() if k != "cb_window"}
            log.critical(
                "Dropping corrupt circuit-breaker window for %s — the breaker "
                "starts from the last price; the original file is kept as %s",
                symbol,
                kept,
            )
    return stats, failed


# ---------------------------------------------------------------------------
# Combo-order persistence
# ---------------------------------------------------------------------------


def save_gtc_combos(combos: list[ComboOrder], path: Path) -> None:
    """Persist resting combos (GTC or DAY) that are still PENDING or
    PARTIALLY_MATCHED; their DAY legs persist as orders, so the parent must."""
    active = [
        c.to_dict()
        for c in combos
        if c.status
        in (
            ComboStatus.PENDING,
            ComboStatus.PARTIALLY_MATCHED,
        )
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(active, indent=2))


def load_gtc_combos(path: Path) -> list[ComboOrder]:
    """
    Load previously persisted GTC combos.

    - Returns an empty list if the file does not exist or is unparseable.
    - Individual corrupt entries (see :func:`_checked_combo`) are logged at
      CRITICAL level and skipped.
    - Either way the file is first copied aside by :func:`keep_corrupt_copy`.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.critical(
            "Cannot parse GTC combos file %s: %s — none restored; the file is kept as %s",
            path,
            exc,
            keep_corrupt_copy(path),
        )
        return []
    if not isinstance(data, list):
        log.critical(
            "GTC combos file %s has unexpected root type %s — expected list; "
            "none restored; the file is kept as %s",
            path,
            type(data).__name__,
            keep_corrupt_copy(path),
        )
        return []
    combos: list[ComboOrder] = []
    kept: Path | None = None
    for idx, d in enumerate(data):
        try:
            combos.append(_checked_combo(ComboOrder.from_dict(d)))
        except Exception as exc:
            combo_id = (
                d.get("id", "<unknown>") if isinstance(d, dict) else "<not a dict>"
            )
            if kept is None:
                kept = keep_corrupt_copy(path)
            log.critical(
                "Skipping corrupt GTC combo at index %d (id=%r): %s — "
                "the original file is kept as %s",
                idx,
                combo_id,
                exc,
                kept,
            )
    return combos
