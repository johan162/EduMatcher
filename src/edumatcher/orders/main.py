"""
Order Monitor — live scrolling table of order events across all gateways.

Usage:
  poetry run pm-orders [--gateway GW01]

Subscribes to all order.* topics, plus quote.status.*, and renders a
full-screen, self-redrawing table of every order event (new/partial/
filled/cancelled/rejected/expired) and every market-maker quote-status
transition (ACTIVE/INACTIVE_BID_FILLED/INACTIVE_ASK_FILLED/CANCELLED) as
they happen, newest at the bottom.

quote.status rows exist because a quote's two legs are ordinary orders
that get their own order.ack/order.fill/order.cancelled rows — but *why*
a leg was cancelled (the other side of the same quote just filled, so the
refresh policy pulled it) is only ever said on quote.status, a message
pm-orders previously never subscribed to. Without it, a quote-driven
order.cancelled row shows no symbol/side/price (order.cancelled's wire
schema deliberately omits them, see spec/messages/order.yaml) and no hint
that it was routine quote housekeeping rather than something to
investigate. The quote.status row for the same quote_id, timestamped
moments earlier or later, supplies that context in the same view.

The cancelled leg's OWN row is also backfilled where possible: order.ack
and order.fill both carry quote_id alongside symbol, so whenever either
leg of a quote is seen with its symbol known, that symbol (and, once one
leg's side is known, the sibling's inferred opposite side) is remembered
against the quote_id and used to fill in a later bare order.cancelled for
the other leg — see _remember_quote_leg/_backfill_from_quote_meta. This is
what makes a seeded quote leg's cancellation show correctly even when
pm-orders started after that leg was seeded and never saw its own ack: the
leg that traded still supplies the quote's symbol.

Display:
  A single-line rounded box, blue border, styled after pm-ticker/pm-viewer:
    • "EduMatcher" brand badge (white on blue) top-left of the title, next
      to the gateway filter.
    • A fixed header row with a rule underneath; the header never scrolls.
    • Order rows fill the remaining box height as they arrive, with no
      lines between rows (maximizes rows shown per screen).
    • The last 1000 events are kept in memory; Up/Down/PageUp/PageDown/
      Home/End scroll the view back through that history. New events keep
      the view pinned to the bottom (live) unless the user has scrolled
      up, in which case the view holds position until they scroll back
      down to the bottom (or press End).
    • "Ctrl-C to quit" is pinned to the bottom-right of the box border.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import zmq
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from edumatcher.config import COMPILED_CONFIG_FILE, ENGINE_PUB_ADDR
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.generated.order import (
    PREFIX_ORDER_ACK,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
)
from edumatcher.models.generated.quote import PREFIX_QUOTE_STATUS
from edumatcher.models.message import decode

console = Console(highlight=False)
log = logging.getLogger(__name__)
_REFRESH_HZ = 4

_CLIENT_NAME = "pm-orders"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# Documented fallback when a symbol's precision is unknown — matches
# edumatcher.models.price.DEFAULT_TICK_DECIMALS /
# edumatcher.calf_client.refdata.DEFAULT_TICK_DECIMALS.
_DEFAULT_TICK_DECIMALS = 2


def _resolve_compiled_config_path(
    warnings: list[str],
) -> Path | None:
    """Find engine_config.json, tolerating a host/container split.

    ``COMPILED_CONFIG_FILE`` (imported from edumatcher.config) is the
    normally-correct answer — it already follows ``EDUMATCHER_DATA_DIR``
    when set. But pm-orders is commonly run on a host that connects to an
    exchange running in a container: the two share a data volume, yet the
    *path* each side resolves for it can differ (a container-local
    EDUMATCHER_DATA_DIR the host doesn't have, or none set on the host at
    all). When the normally-resolved path doesn't exist, fall back to
    ``./data/ref_data/engine_config.json`` under the current directory —
    where a host process sharing that volume is typically launched from.

    Every warning is appended (not printed) to ``warnings`` — this runs at
    import time, before logging is configured, so printing directly here
    would only ever reach stderr. The caller prints immediately (so the
    warning is visible right away, before the Live UI takes over the
    terminal) and replays the same messages through the logger once
    _configure_logging() has wired up the pm-log-srv client, so both the
    operator's terminal and the central log get a record.

    Returns ``None`` when neither candidate exists.
    """
    if COMPILED_CONFIG_FILE.exists():
        return COMPILED_CONFIG_FILE

    cwd_candidate = Path.cwd() / "data" / "ref_data" / "engine_config.json"
    if cwd_candidate.exists():
        warnings.append(
            f"engine config not found at {COMPILED_CONFIG_FILE} (checked "
            f"EDUMATCHER_DATA_DIR / the usual defaults); using "
            f"{cwd_candidate} found in the current directory instead."
        )
        return cwd_candidate

    warnings.append(
        f"engine config not found at {COMPILED_CONFIG_FILE}, and no "
        "./data/ref_data/engine_config.json in the current directory "
        f"either. Prices will fall back to {_DEFAULT_TICK_DECIMALS} "
        "decimals for every symbol until this is fixed — set "
        "EDUMATCHER_DATA_DIR to the exchange's data directory, or run "
        "pm-orders from a directory containing ./data/ref_data/."
    )
    return None


def _load_tick_decimals() -> tuple[dict[str, int], list[str]]:
    """Symbol -> tick_decimals, read from the compiled engine config.

    order.ack's "price" field (the submitted limit price) and the
    aggressor side's "price" on order.fill are published straight from the
    client's request — raw integer ticks, e.g. 12357 for a $123.57 limit —
    never converted to display money. Converting requires knowing each
    symbol's tick precision, which the engine keeps in
    ``<DATA_DIR>/ref_data/engine_config.json`` under
    ``engine.symbols.<SYMBOL>.tick_decimals``. Read directly as JSON here
    rather than importing edumatcher.engine.config_loader — that loader
    pulls in the full engine config schema/validation, far more than a
    display client needs for one integer per symbol.

    Missing file or malformed content is not fatal: individual symbols
    just fall back to ``_DEFAULT_TICK_DECIMALS`` and prices still render,
    only possibly at the wrong precision for that one symbol.

    Returns ``(tick_decimals_by_symbol, warning_messages)`` — see
    ``_resolve_compiled_config_path`` for why warnings are collected
    rather than logged directly.
    """
    warnings: list[str] = []
    config_path = _resolve_compiled_config_path(warnings)
    if config_path is None:
        return {}, warnings  # already warned above — nothing left to try
    try:
        with open(config_path, encoding="utf-8") as f:
            compiled = json.load(f)
        symbols = compiled.get("engine", {}).get("symbols", {})
        decimals = {
            sym.upper(): int(cfg["tick_decimals"])
            for sym, cfg in symbols.items()
            if isinstance(cfg, dict) and "tick_decimals" in cfg
        }
        return decimals, warnings
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(
            f"could not read tick_decimals from {config_path}: {exc} "
            f"(prices will fall back to {_DEFAULT_TICK_DECIMALS} decimals)"
        )
        return {}, warnings


def _log_startup_warnings(warnings: list[str]) -> None:
    """Send collected startup warnings to the logger.

    The stderr copy already happened immediately at import time (see below
    _load_tick_decimals's call site), before logging was configured. Call
    this once from main(), right after _configure_logging() has wired up
    the pm-log-srv-backed handler, so the same messages also reach the
    central log."""
    for msg in warnings:
        log.warning(msg)


# Loaded once at import time — the same convention as every other module
# constant here. tick_decimals is deployed configuration (engine_config.json
# is only written by the deploy step per REF_DATA_DIR's docstring), not
# something that changes while pm-orders is running. The stderr copy of any
# warning happens immediately (print() doesn't need logging configured);
# the log-server copy is deferred to main(), see _startup_warnings below.
_TICK_DECIMALS, _startup_warnings = _load_tick_decimals()
for _msg in _startup_warnings:
    print(f"[pm-orders] WARNING: {_msg}", file=sys.stderr)


def _ticks_to_price(raw: Any, symbol: str | None) -> Any:
    """Convert a raw integer-tick price to real money for display.

    ``symbol`` selects the tick precision; unknown or missing symbols fall
    back to ``_DEFAULT_TICK_DECIMALS``, matching the rest of the codebase's
    documented fallback (edumatcher.models.price, edumatcher.calf_client.
    refdata). A non-numeric ``raw`` is returned unchanged so a malformed
    value stays visible as itself instead of crashing the render loop —
    that's also why this returns ``Any`` rather than ``float | None``: the
    pass-through case is deliberate, not an oversight.
    """
    if raw is None:
        return None
    if not isinstance(raw, (int, float)):
        return raw
    decimals = (
        _TICK_DECIMALS.get(symbol.upper(), _DEFAULT_TICK_DECIMALS)
        if symbol
        else _DEFAULT_TICK_DECIMALS
    )
    return raw / (10**decimals)


def _format_price(value: Any, symbol: str | None) -> str:
    """Render a (already-normalized, real-money) price at the symbol's own
    decimal precision, e.g. 123.5 -> "123.50" for a 2-decimal symbol."""
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return str(value)
    decimals = (
        _TICK_DECIMALS.get(symbol.upper(), _DEFAULT_TICK_DECIMALS)
        if symbol
        else _DEFAULT_TICK_DECIMALS
    )
    return f"{value:.{decimals}f}"


# Chrome (non-data rows) consumed by the outer frame + title + header + rule.
# Used to work out how many order rows fit the current terminal height.
_CHROME_ROWS = 5

_HISTORY_MAXLEN = 1000  # scrollback depth

# Bid/ask green-red convention used everywhere else in the UI (pm-ticker's
# best_bid/best_ask coloring, pm-viewer's _UP/_DOWN) — BUY sides and their
# prices are green, SELL sides and their prices are red.
_UP = "green"
_DOWN = "red"
_FLAT = "grey70"

_SIDE_STYLE = {
    "BUY": _UP,
    "SELL": _DOWN,
}

_STATUS_STYLE = {
    "NEW": "green",
    "PARTIAL": "yellow",
    "FILLED": "bright_green",
    "CANCELLED": "red",
    "REJECTED": "red",
    "EXPIRED": "dim",
    "PENDING": "dim",
    # quote.status values (edumatcher.models.quote.QuoteState) — a quote
    # going INACTIVE_*_FILLED is routine market-making housekeeping, not a
    # problem, so it gets the same "yellow, not red" treatment PARTIAL does;
    # ACTIVE (a fresh/replaced quote) mirrors NEW.
    "ACTIVE": "green",
    "INACTIVE_BID_FILLED": "yellow",
    "INACTIVE_ASK_FILLED": "yellow",
}

# quote.status rows are a different kind of event from order rows — no
# order_id, no symbol/side/price — so they're visually tagged in the ID
# column rather than forced into columns that don't apply to them.
_QUOTE_ROW_TAG = "QUOTE"

# INACTIVE_BID_FILLED / INACTIVE_ASK_FILLED (edumatcher.models.quote.
# QuoteState) name the side that TRADED, not the side that ended up
# cancelled — Engine._on_quote_leg_filled cancels the SIBLING of whichever
# leg filled, so INACTIVE_BID_FILLED means the bid traded and the ask was
# the one pulled. Read cold, the name reads just as plausibly the other way
# (as "the bid is now inactive/cancelled"), so this table spells out both
# halves rather than making every reader re-derive the convention from
# spec/messages/quote.yaml.
_QUOTE_STATUS_TEXT = {
    "ACTIVE": "ACTIVE",
    "INACTIVE_BID_FILLED": "BID filled, ASK cancelled",
    "INACTIVE_ASK_FILLED": "ASK filled, BID cancelled",
    "CANCELLED": "CANCELLED",
}

# The side that went INACTIVE (i.e. was cancelled) is the opposite of the
# side named in the status: INACTIVE_BID_FILLED means the bid traded, so
# the ask leg — SELL — is the one that got pulled, and vice versa. Same
# convention as _QUOTE_STATUS_TEXT above, just distilled to a Side-column
# value so it can share _SIDE_STYLE's colour coding with order rows.
_QUOTE_STATUS_SIDE = {
    "INACTIVE_BID_FILLED": "SELL",
    "INACTIVE_ASK_FILLED": "BUY",
}

_COLUMNS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Time", {"style": "dim", "width": 12, "no_wrap": True}),
    ("ID", {"style": "dim", "width": 10, "no_wrap": True}),
    ("Gateway", {"style": "cyan", "width": 8, "no_wrap": True}),
    ("Symbol", {"style": "bold", "width": 8, "no_wrap": True}),
    ("Side", {"width": 6, "no_wrap": True}),
    ("Type", {"style": "magenta", "width": 12, "no_wrap": True}),
    ("TIF", {"style": "dim", "width": 5, "no_wrap": True}),
    ("Qty", {"justify": "right", "width": 7, "no_wrap": True}),
    ("Remaining", {"justify": "right", "width": 9, "no_wrap": True}),
    ("Price", {"justify": "right", "width": 9, "no_wrap": True}),
    # Widened from 12, then again from 22: a quote row's status is spelled
    # out via _QUOTE_STATUS_TEXT ("BID filled, ASK cancelled" — 26 chars)
    # rather than the raw INACTIVE_BID_FILLED/INACTIVE_ASK_FILLED wire value,
    # since the wire value names the side that traded, not the side that
    # ended up cancelled, and reads plausibly either way to someone who
    # hasn't memorized spec/messages/quote.yaml's convention. Narrower than
    # this truncates the very value this column exists to show for a quote
    # row (order statuses are all <= 9 chars and still fit comfortably).
    ("Status", {"width": 26, "no_wrap": True}),
)


def _build_header(gw_filter: str | None, event_count: int, now: datetime) -> Table:
    """Fixed title/header row: brand + gateway filter on the left, the live
    date/time pinned to the right — same pattern as pm-ticker's header."""
    grid = Table.grid(expand=True)
    grid.add_column(no_wrap=True, overflow="ellipsis")  # brand / filter
    grid.add_column(ratio=1)  # elastic spacer
    grid.add_column(no_wrap=True, justify="right")  # clock

    left = Text.assemble(
        (" EduMatcher ", "bold white on blue"),
        ("  ", ""),
        ("Order Monitor", "bold"),
        ("   │   ", "grey35"),
        ("Gateway ", "grey62"),
        (gw_filter if gw_filter else "all", "cyan"),
        ("   │   ", "grey35"),
        ("Events ", "grey62"),
        (f"{event_count:,}", "white"),
    )
    # Date dimmer than the ticking clock, same contrast as pm-viewer's
    # header (line1's clock is "bold cyan", line2's date is plain "cyan").
    right = Text.assemble(
        (now.strftime("%Y-%m-%d "), "cyan"),
        (now.strftime("%H:%M:%S"), "bold cyan"),
    )
    grid.add_row(left, Text(""), right)
    return grid


def _build_rows_table(rows: list[dict[str, Any]]) -> Table:
    """The header row plus the scrolling body in a single Table instance so
    column widths always line up exactly — a fixed header (Rich redraws the
    header on every frame regardless of how the body scrolls) with no lines
    between data rows so the available height goes to data, not borders."""
    t = Table(
        box=None,
        expand=True,
        show_header=True,
        header_style="bold grey70",
        show_edge=False,
        pad_edge=False,
    )
    for name, kwargs in _COLUMNS:
        t.add_column(name, **kwargs)

    for o in rows:
        st: str = o.get("status", "?")
        status_colour = _STATUS_STYLE.get(st, "white")

        if o.get("kind") == "quote":
            # quote.status carries no order_id/side/price/qty — only
            # quote_id, gateway_id, status, and an optional reason (symbol is
            # backfilled by pm-orders itself from whichever leg's ack/fill
            # already revealed it — see _remember_quote_leg/
            # _handle_quote_status). Render it as its own row shape rather
            # than leaving every order-only column blank with no
            # explanation: the ID column is tagged QUOTE so it's visually
            # distinct from an 8-char order id, and the quote_id rides in
            # the Type column, the one column an order row doesn't need
            # alongside a quote_id-worth of space. Left untruncated (unlike
            # order ids, which are deliberately shortened to 8 chars) since
            # the column's own no_wrap+ellipsis already handles overflow,
            # and unlike an order id a quote_id is often the exact string an
            # operator is searching audit.log for — silently chopping it to
            # a fixed prefix would make that correlation harder to eyeball.
            # reason, when present, rides in the Status cell — that's the
            # one piece of information this row exists to surface.
            status_text: str = _QUOTE_STATUS_TEXT.get(st, st)
            if o.get("reason"):
                status_text = f"{status_text} ({o['reason']})"
            # Side column shows which side of the quote this row is about:
            # for an INACTIVE_*_FILLED transition that's the leg that just
            # went inactive (see _QUOTE_STATUS_SIDE) — deliberately NOT the
            # side that traded, since the cancelled leg is the one an
            # operator needs to re-quote. ACTIVE/CANCELLED apply to the
            # whole quote (both legs), so there's no single side to show.
            quote_side = _QUOTE_STATUS_SIDE.get(st)
            side_cell = (
                Text(quote_side, style=_SIDE_STYLE.get(quote_side, _FLAT))
                if quote_side
                else ""
            )
            t.add_row(
                o.get("time", "?"),
                Text(_QUOTE_ROW_TAG, style="grey58"),
                o.get("gateway_id", "?"),
                o.get("symbol") or "?",
                side_cell,
                Text(o.get("quote_id", "?"), style="grey62"),
                "",
                "",
                "",
                "",
                Text(status_text, style=status_colour),
            )
            continue

        side = o.get("side", "?")
        side_colour = _SIDE_STYLE.get(side, _FLAT)
        t.add_row(
            o.get("time", "?"),
            o.get("order_id", "?")[:8],
            o.get("gateway_id", "?"),
            o.get("symbol", "?"),
            Text(side, style=side_colour),
            o.get("order_type", "?"),
            o.get("tif", "?"),
            str(o.get("qty", "?")),
            str(o.get("remaining", "?")),
            Text(_format_price(o.get("price"), o.get("symbol")), style=side_colour),
            Text(st, style=status_colour),
        )
    return t


def _build_panel(
    gw_filter: str | None,
    event_count: int,
    now: datetime,
    rows: list[dict[str, Any]],
    *,
    height: int,
    scrolled_back: bool,
) -> Panel:
    """Assemble the full-screen order monitor box."""
    subtitle = Text(
        ("↑/↓ scroll  •  " if scrolled_back else "") + "Ctrl-C to quit",
        style="grey58" if scrolled_back else "grey42",
    )
    return Panel(
        Group(
            _build_header(gw_filter, event_count, now),
            Rule(style="grey35"),
            _build_rows_table(rows),
        ),
        box=box.ROUNDED,
        border_style="blue",
        padding=(0, 1),
        height=height,
        title=Text(" pm-orders ", style="grey58"),
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
    )


class OrderMonitor:
    def __init__(self, gw_filter: str | None) -> None:
        self.gw_filter = gw_filter
        self._orders: dict[str, dict[str, Any]] = {}  # order_id -> latest state
        # quote_id -> {symbol, gateway_id, sides: {order_id: side}}, built up
        # from whichever order.* events happen to carry both quote_id and
        # symbol (ack, fill — see the population below). order.cancelled's
        # wire shape deliberately omits symbol/side/price (see
        # spec/messages/order.yaml) for EVERY cancelled order, not just quote
        # legs, so this is quote-specific backfill: a cancelled leg that
        # arrives with only a quote_id can still be shown with its symbol
        # and (inferred) side, even when this monitor never saw that leg's
        # own ack — the common case for a seeded quote leg that rests
        # untouched until its sibling fills and the refresh policy cancels
        # it, which is exactly the sequence a market-sell into a resting
        # quote produces.
        self._quote_meta: dict[str, dict[str, Any]] = {}
        # Ordered scrollback of every event as it was applied, oldest first.
        # Each entry is a full row snapshot (dict) so history never mutates
        # after the fact — only new events are appended.
        self._history: deque[dict[str, Any]] = deque(maxlen=_HISTORY_MAXLEN)
        self._lock = threading.Lock()
        self._running = True

        # Scroll offset in rows, measured from the bottom (0 == live/bottom).
        self._scroll_offset = 0

        # Explicit per-order lifecycle prefixes rather than the bare "order."
        # prefix: that catch-all also matches query REPLIES that happen to
        # live under the order.* namespace — order.orders.{gw} (pm-admin's
        # ORDERS command) and order.price_level_orders(_request).{gw} (the
        # LEVEL command) — neither of which carries an order_id, so each hit
        # rendered a row with an empty ID and every other column "?". Listing
        # the five genuine per-order-event prefixes here means a future
        # order.* query reply can't leak into this view the same way again.
        self.sub = make_subscriber(
            ENGINE_PUB_ADDR,
            PREFIX_ORDER_ACK,
            PREFIX_ORDER_FILL,
            PREFIX_ORDER_CANCELLED,
            PREFIX_ORDER_EXPIRED,
            PREFIX_ORDER_AMENDED,
            PREFIX_QUOTE_STATUS,
        )

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle(self, topic: str, payload: dict[str, Any]) -> None:
        if topic.startswith(PREFIX_QUOTE_STATUS):
            self._handle_quote_status(topic, payload)
            return

        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        oid = payload.get("order_id", "")
        with self._lock:
            entry = self._orders.setdefault(oid, {"order_id": oid})

            # Populate order metadata whenever it's present in the message
            for src_key, dst_key in (
                ("symbol", "symbol"),
                ("side", "side"),
                ("order_type", "order_type"),
                ("tif", "tif"),
                ("qty", "qty"),
            ):
                val = payload.get(src_key)
                if val is not None:
                    entry[dst_key] = val

            quote_id = payload.get("quote_id")
            if quote_id:
                entry["quote_id"] = quote_id
                # Only ack/fill carry symbol on the wire (see the field-
                # population loop above) — remember this leg's symbol/side
                # against its quote_id now, while this message actually has
                # them, so a later bare order.cancelled for the SIBLING leg
                # (same quote_id, no symbol of its own) can still be shown
                # properly instead of falling back to "?" everywhere.
                if "symbol" in entry:
                    self._remember_quote_leg(quote_id, oid, entry)
            if entry.get("quote_id") and "symbol" not in entry:
                self._backfill_from_quote_meta(entry, oid)

            # Price normalization: order.ack's "price" (the submitted limit
            # price) and the aggressor side's "price" on order.fill are both
            # published straight from the client's request payload — raw
            # integer ticks, never converted. order.fill's "fill_price" (and
            # the passive side's "price") ARE already converted to display
            # money via from_ticks() on the engine side. Prefer fill_price
            # when present since it's already correct; otherwise treat the
            # raw value as ticks and convert using this symbol's own
            # tick_decimals so every row ends up in the same real-money
            # units regardless of which upstream field it came from.
            symbol = entry.get("symbol")
            raw_price = payload.get("fill_price", payload.get("price"))
            if raw_price is not None:
                if "fill_price" in payload:
                    entry["price"] = raw_price
                else:
                    entry["price"] = _ticks_to_price(raw_price, symbol)

            if "order.ack" in topic:
                # Extract gateway_id from topic: order.ack.GW01
                parts = topic.split(".")
                if len(parts) >= 3:
                    entry["gateway_id"] = parts[2]
                if payload.get("accepted"):
                    entry["status"] = "NEW"
                    # A freshly accepted order's remaining quantity is its
                    # full quantity — nothing has traded yet. Without this,
                    # "remaining" stays absent (rendered as "?") until the
                    # order's first fill, even though a resting order with
                    # zero fills has a perfectly well-known remaining qty.
                    # Only seed it if not already set: a re-ack (e.g. a
                    # replayed/duplicate accept) must not clobber a
                    # remaining value a prior fill already reduced.
                    if "remaining" not in entry and "qty" in entry:
                        entry["remaining"] = entry["qty"]
                else:
                    entry["status"] = "REJECTED"

            elif "order.fill" in topic:
                # gateway_id from topic for counterparty fills that skipped an ack
                parts = topic.split(".")
                if len(parts) >= 3 and "gateway_id" not in entry:
                    entry["gateway_id"] = parts[2]
                entry["remaining"] = payload.get("remaining_qty", 0)
                entry["status"] = payload.get("status", "PARTIAL")

            elif "order.cancelled" in topic:
                entry["status"] = "CANCELLED"

            elif "order.expired" in topic:
                entry["status"] = "EXPIRED"

            elif "order.amended" in topic:
                # order.amended carries no symbol/side/order_type/tif (same
                # minimal shape as order.cancelled) — remaining/price/qty
                # above are already refreshed by the field-population loop
                # since amended payloads use the same key names (qty, price)
                # as ack/fill. Status is left as whatever it already was;
                # an amendment doesn't change NEW/PARTIAL/FILLED.
                entry["remaining"] = payload.get(
                    "remaining_qty", entry.get("remaining")
                )

            if self.gw_filter is None or entry.get("gateway_id") == self.gw_filter:
                self._append_row({**entry, "time": now})

    def _remember_quote_leg(
        self, quote_id: str, order_id: str, entry: dict[str, Any]
    ) -> None:
        """Record this leg's symbol/side against its quote_id.

        Must be called with self._lock held (only called from _handle,
        which already holds it). A quote has exactly two legs, so once both
        this leg's own side and its quote's symbol are known, the sibling
        leg's side is a plain BUY/SELL flip — no third message needed.
        """
        meta = self._quote_meta.setdefault(
            quote_id,
            {
                "symbol": entry.get("symbol"),
                "gateway_id": entry.get("gateway_id"),
                "legs": {},
            },
        )
        meta["symbol"] = entry.get("symbol", meta["symbol"])
        meta["gateway_id"] = entry.get("gateway_id", meta["gateway_id"])
        if entry.get("side"):
            meta["legs"][order_id] = entry["side"]

    def _backfill_from_quote_meta(self, entry: dict[str, Any], order_id: str) -> None:
        """Fill in symbol/side/gateway_id for a bare order.cancelled/expired
        leg from what an earlier ack/fill for its SIBLING leg revealed about
        this quote — see _remember_quote_leg. Must be called with self._lock
        held.

        A seeded quote leg that this monitor never saw an ack for (it was
        seeded before pm-orders started) still ends up correctly labelled
        once its sibling trades: the sibling's fill records the quote's
        symbol, and since a quote has exactly two legs, this leg's own side
        is simply the other one.
        """
        meta = self._quote_meta.get(entry.get("quote_id", ""))
        if meta is None:
            return
        if meta.get("symbol") is not None:
            entry["symbol"] = meta["symbol"]
        if "gateway_id" not in entry and meta.get("gateway_id") is not None:
            entry["gateway_id"] = meta["gateway_id"]
        if "side" not in entry:
            known_sides = {
                oid: side for oid, side in meta["legs"].items() if oid != order_id
            }
            other_sides = set(known_sides.values())
            if len(other_sides) == 1:
                (sibling_side,) = other_sides
                entry["side"] = "SELL" if sibling_side == "BUY" else "BUY"

    def _handle_quote_status(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a PREFIX_QUOTE_STATUS event — a market-maker quote's lifecycle
        transition (ACTIVE / INACTIVE_BID_FILLED / INACTIVE_ASK_FILLED /
        CANCELLED), published whenever a quote is created, has one leg
        filled (which also cancels its sibling — see
        Engine._on_quote_leg_filled), or is explicitly cancelled/replaced.

        Unlike order.* topics this carries no order_id, so it doesn't
        accumulate onto an existing row in self._orders — it's appended as
        its own standalone history row, tagged in _build_rows_table so it
        reads as quote housekeeping rather than an order with missing
        columns.
        """
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        parts = topic.split(".")
        gateway_id = payload.get("gateway_id") or (parts[2] if len(parts) >= 3 else "?")

        if self.gw_filter is not None and gateway_id != self.gw_filter:
            return

        status = payload.get("status", "?")
        quote_id = payload.get("quote_id", "?")

        with self._lock:
            # _quote_meta[quote_id]["symbol"] is populated the moment any leg
            # of this quote has been seen with symbol known (see
            # _remember_quote_leg) — for a *_FILLED status specifically, the
            # fill that triggered it was just processed by _handle() earlier
            # in the same message stream, so the symbol is reliably there by
            # now even for a quote whose legs were seeded before this
            # monitor started (the QUOTE row previously had no symbol at
            # all, unlike the order rows for its legs, which do get this
            # same backfill).
            meta = self._quote_meta.get(quote_id)
            symbol = meta.get("symbol") if meta else None

            self._append_row(
                {
                    "kind": "quote",
                    "time": now,
                    "gateway_id": gateway_id,
                    "quote_id": quote_id,
                    "symbol": symbol,
                    "status": status,
                    "reason": payload.get("reason") or "",
                }
            )

    def _append_row(self, row: dict[str, Any]) -> None:
        """Append one already-built row to the scrollback history and keep
        the scroll offset valid. Shared by _handle (order.* events, which
        snapshot accumulated per-order state) and _handle_quote_status
        (quote.status events, which are already a complete standalone row)
        so both event kinds interleave chronologically in one buffer.
        Must be called with self._lock held.
        """
        # Snapshot this event as its own scrollback row so past rows are
        # never rewritten by later updates to the same order.
        self._history.append(row)
        # Keep the live view pinned to the bottom unless the user has
        # scrolled back into history; if scrolled back, hold position
        # (re-clamped in case the buffer just hit its maxlen and dropped
        # its oldest row out from under the current offset).
        if self._scroll_offset > 0:
            self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            socks = dict(poller.poll(timeout=300))
            if self.sub in socks:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
                self._handle(topic, payload)

    def _max_scroll_offset(self) -> int:
        """Furthest the view can scroll back, in rows from the bottom.

        Once the oldest row in the current viewport is row 0 of the
        history buffer, scrolling further up would just shrink the
        viewport from the bottom (rows disappearing one at a time) instead
        of moving the window — so the offset must stop at
        ``total - capacity``, not ``total - 1``. Must be called with
        ``self._lock`` held.
        """
        capacity = self._page_size()
        total = len(self._history)
        return max(0, total - capacity)

    # ------------------------------------------------------------------
    # Keyboard scroll thread
    # ------------------------------------------------------------------

    def _read_keys(self) -> None:
        """Background reader for Up/Down arrow scrolling.

        Uses prompt_toolkit's low-level raw-mode input (already a project
        dependency) so keypresses are consumed without echoing to the
        terminal and without blocking the ZMQ receive thread or the render
        loop. Polls the input's file descriptor with select() rather than
        prompt_toolkit's ``attach()`` — that helper hooks into an asyncio
        event loop's reader callbacks, which a plain background thread
        doesn't have. One key event moves the viewport by one row;
        PageUp/PageDown move by a full page for faster scrolling through
        the 1000-row history buffer; Home jumps to the oldest row kept in
        the buffer, End jumps straight back to the live bottom of the feed.
        """
        import select

        try:
            from prompt_toolkit.input import create_input
            from prompt_toolkit.keys import Keys
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("keyboard scrolling unavailable: %s", exc)
            return

        try:
            input_ = create_input()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("could not open keyboard input: %s", exc)
            return

        try:
            with input_.raw_mode():
                fd = input_.fileno()
                while self._running:
                    try:
                        ready, _, _ = select.select([fd], [], [], 0.1)
                    except (OSError, ValueError):
                        break
                    if not ready:
                        continue
                    for key_press in input_.read_keys():
                        key = key_press.key
                        with self._lock:
                            max_offset = self._max_scroll_offset()
                            if key == Keys.Up:
                                self._scroll_offset = min(
                                    max_offset, self._scroll_offset + 1
                                )
                            elif key == Keys.Down:
                                self._scroll_offset = max(0, self._scroll_offset - 1)
                            elif key == Keys.PageUp:
                                self._scroll_offset = min(
                                    max_offset,
                                    self._scroll_offset + self._page_size(),
                                )
                            elif key == Keys.PageDown:
                                self._scroll_offset = max(
                                    0, self._scroll_offset - self._page_size()
                                )
                            elif key == Keys.Home:
                                self._scroll_offset = max_offset
                            elif key == Keys.End:
                                self._scroll_offset = 0
                            elif key == Keys.ControlC:
                                self._running = False
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("keyboard scroll thread stopped: %s", exc)
        finally:
            try:
                input_.close()
            except Exception:
                pass

    def _page_size(self) -> int:
        return max(1, console.size.height - _CHROME_ROWS)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self) -> Panel:
        height = console.size.height
        capacity = max(1, height - _CHROME_ROWS)
        now = datetime.now()

        with self._lock:
            total = len(self._history)
            offset = min(self._scroll_offset, self._max_scroll_offset())
            self._scroll_offset = offset
            # offset is measured from the bottom; end is exclusive.
            end = total - offset
            start = max(0, end - capacity)
            rows = list(self._history)[start:end]
            event_count = total

        return _build_panel(
            self.gw_filter,
            event_count,
            now,
            rows,
            height=height,
            scrolled_back=offset > 0,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        t = threading.Thread(target=self._receive, daemon=True)
        t.start()

        kt = threading.Thread(target=self._read_keys, daemon=True)
        kt.start()

        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))

        try:
            # screen=True paints on the alternate screen buffer and repaints
            # the whole box at the current terminal size every frame, so
            # resizes never leave stale rows behind — same as pm-ticker and
            # pm-viewer. transient=True restores the normal terminal and
            # scrollback on exit.
            with Live(
                console=console, auto_refresh=False, screen=True, transient=True
            ) as live:
                while self._running:
                    live.update(self._render())
                    live.refresh()
                    time.sleep(1 / _REFRESH_HZ)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            t.join(timeout=2.0)
            kt.join(timeout=2.0)
            self.sub.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher order monitor")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-orders")
    parser.add_argument(
        "--gateway",
        "-g",
        metavar="GW_ID",
        default=None,
        help="Filter to a single gateway (default: show all)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce log output to warnings/errors",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-orders with log level %s", logging.getLevelName(log_level))
    _log_startup_warnings(_startup_warnings)
    OrderMonitor(args.gateway).run()


if __name__ == "__main__":
    main()
