"""
Market Board — multi-symbol aggregated display for large screens.

Usage:
  poetry run pm-board [--rows 8] [--interval 10]

Subscribes to all book.* and trade.executed topics and displays a paged table
of all active symbols with exchange-style coloring.

Controls:
  PgUp / PgDn — page backward / forward immediately
  ENTER       — advance to the next page immediately (kept for muscle memory)
  Ctrl-C      — exit

Any manual page change (PgUp/PgDn/ENTER) resets the auto-rotate countdown, so
someone actively paging through the board on a TV isn't fighting the timer —
auto-rotate resumes forward from wherever they left off once they stop
interacting.

Each page shows up to --rows symbols (default 8). Pages auto-rotate every
--interval seconds (default 10) while nobody is paging manually.

Display:
  A single-line rounded box, blue border, styled after pm-ticker/pm-orders/
  pm-viewer:
    • "EduMatcher" brand badge (white on blue) top-left of the title, next
      to the page indicator and auto-rotate interval.
    • A fixed header row with a rule underneath; the header never scrolls.
    • Symbol rows fill the remaining box height, with no lines between rows.
    • "Ctrl-C to quit" is pinned to the bottom-right of the box border.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

import zmq
from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

import errno

from edumatcher.config import COMPILED_CONFIG_FILE, ENGINE_PULL_ADDR, ENGINE_PUB_ADDR
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_symbols_request_msg,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT
from edumatcher.models.generated.system import topic_symbols

console = Console(highlight=False)
log = logging.getLogger(__name__)

_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
_CLIENT_NAME = "pm-board"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"
_REFRESH_HZ = 4

#: Fixed id pm-board identifies itself with when requesting the symbol list.
BOARD_GATEWAY_ID = "BOARD"
_SYMBOLS_REQUEST_RETRY_SEC = 1.0

# Chrome (non-data rows) consumed by the outer frame + title + header + rule.
# Used to work out how many symbol rows fit the current terminal height.
_CHROME_ROWS = 5

# Bid/ask green-red convention used everywhere else in the UI (pm-ticker's
# best_bid/best_ask coloring, pm-viewer's _UP/_DOWN, pm-orders' Side/Price).
_UP = "bright_green"
_DOWN = "bright_red"
_FLAT = "white"

# Documented fallback when a symbol's precision is unknown — matches
# edumatcher.models.price.DEFAULT_TICK_DECIMALS /
# edumatcher.calf_client.refdata.DEFAULT_TICK_DECIMALS, and pm-orders'
# own _DEFAULT_TICK_DECIMALS.
_DEFAULT_TICK_DECIMALS = 2


def _load_tick_decimals() -> dict[str, int]:
    """Symbol -> tick_decimals, read from the compiled engine config.

    Mirrors pm-orders' loader of the same name: book.* and trade.executed
    prices are already converted to display money by the engine's
    from_ticks() before publish, but the board still needs each symbol's
    own precision to format them consistently (123.57 rather than a
    hardcoded 123.5700) instead of guessing one fixed decimal count for
    every instrument. Read directly as JSON from
    ``<DATA_DIR>/ref_data/engine_config.json`` rather than importing
    edumatcher.engine.config_loader, which pulls in the full engine config
    schema/validation for far more than a display client needs.

    Missing file or malformed content is not fatal: symbols just fall back
    to ``_DEFAULT_TICK_DECIMALS`` and prices still render.
    """
    try:
        with open(COMPILED_CONFIG_FILE, encoding="utf-8") as f:
            compiled = json.load(f)
        symbols = compiled.get("engine", {}).get("symbols", {})
        return {
            sym.upper(): int(cfg["tick_decimals"])
            for sym, cfg in symbols.items()
            if isinstance(cfg, dict) and "tick_decimals" in cfg
        }
    except Exception as exc:  # pragma: no cover - defensive
        log.warning(
            "could not read tick_decimals from %s: %s "
            "(prices will fall back to %d decimals)",
            COMPILED_CONFIG_FILE,
            exc,
            _DEFAULT_TICK_DECIMALS,
        )
        return {}


# Loaded once at import time — same convention as pm-orders. tick_decimals is
# deployed configuration, not something that changes while pm-board runs.
_TICK_DECIMALS: dict[str, int] = _load_tick_decimals()


def _format_price(value: Any, symbol: str | None) -> str:
    """Render a display-money price at the symbol's own decimal precision."""
    if value is None:
        return "—"
    if not isinstance(value, (int, float)):
        return str(value)
    decimals = _TICK_DECIMALS.get(
        symbol.upper() if symbol else None, _DEFAULT_TICK_DECIMALS
    )
    return f"{value:.{decimals}f}"


def _colour_change(pct: float) -> str:
    if pct > 0:
        return _UP
    if pct < 0:
        return _DOWN
    return _FLAT


_COLUMNS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("Symbol", {"style": "bold", "min_width": 8, "no_wrap": True}),
    ("Last", {"justify": "right", "min_width": 10, "no_wrap": True}),
    ("Chg %", {"justify": "right", "min_width": 8, "no_wrap": True}),
    ("Bid", {"justify": "right", "min_width": 10, "no_wrap": True}),
    ("Ask", {"justify": "right", "min_width": 10, "no_wrap": True}),
    ("Spread", {"justify": "right", "min_width": 8, "no_wrap": True}),
    ("Last Buy", {"justify": "right", "min_width": 10, "no_wrap": True}),
    ("Last Sell", {"justify": "right", "min_width": 10, "no_wrap": True}),
    ("Vol", {"justify": "right", "min_width": 8, "no_wrap": True}),
    ("Updated", {"justify": "right", "min_width": 14, "style": "dim", "no_wrap": True}),
)


def _build_header(
    page: int, total_pages: int, symbol_count: int, interval: int, now: datetime
) -> Table:
    """Fixed title/header row: brand + page indicator on the left, the live
    date/time pinned to the right — same pattern as pm-ticker/pm-orders."""
    grid = Table.grid(expand=True)
    grid.add_column(no_wrap=True, overflow="ellipsis")  # brand / page info
    grid.add_column(ratio=1)  # elastic spacer
    grid.add_column(no_wrap=True, justify="right")  # clock

    left = Text.assemble(
        (" EduMatcher ", "bold white on blue"),
        ("  ", ""),
        ("Market Board", "bold"),
        ("   │   ", "grey35"),
        ("Page ", "grey62"),
        (f"{page + 1}/{total_pages}", "cyan"),
        ("   │   ", "grey35"),
        ("Symbols ", "grey62"),
        (f"{symbol_count}", "white"),
        ("   │   ", "grey35"),
        ("Auto-rotate ", "grey62"),
        (f"{interval}s", "white"),
    )
    # Date dimmer than the ticking clock, same contrast as pm-viewer's
    # header (line1's clock is "bold cyan", line2's date is plain "cyan").
    right = Text.assemble(
        (now.strftime("%Y-%m-%d "), "cyan"),
        (now.strftime("%H:%M:%S"), "bold cyan"),
    )
    grid.add_row(left, Text(""), right)
    return grid


def _build_rows_table(page_symbols: list[tuple[str, dict[str, Any]]]) -> Table:
    """The header row plus the scrolling body in a single Table instance so
    column widths always line up exactly — no lines between data rows so
    the available height goes to data, not borders. Same construction
    pattern as pm-orders' _build_rows_table."""
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

    for sym, data in page_symbols:
        last = data.get("last_price")
        first_price = data.get("first_price")
        last_buy = data.get("last_buy_price")
        last_sell = data.get("last_sell_price")
        best_bid = data.get("best_bid")
        best_ask = data.get("best_ask")
        volume = data.get("volume", 0)
        updated = data.get("updated")

        pct = 0.0
        if last is not None and first_price is not None and first_price > 0:
            pct = ((last - first_price) / first_price) * 100.0
        colour = _colour_change(pct)

        spread = None
        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid

        updated_str = (
            updated.strftime("%H:%M:%S.%f")[:-3] if updated else "—"
        )

        t.add_row(
            sym,
            Text(_format_price(last, sym), style=colour),
            Text(f"{pct:+.2f}%", style=colour),
            Text(_format_price(best_bid, sym), style=_UP),
            Text(_format_price(best_ask, sym), style=_DOWN),
            _format_price(spread, sym),
            Text(_format_price(last_buy, sym), style=_UP),
            Text(_format_price(last_sell, sym), style=_DOWN),
            f"{volume:,}" if volume else "0",
            updated_str,
        )

    return t


def _build_panel(
    page: int,
    total_pages: int,
    symbol_count: int,
    interval: int,
    now: datetime,
    page_symbols: list[tuple[str, dict[str, Any]]],
    *,
    height: int,
) -> Panel:
    """Assemble the full-screen market board box."""
    subtitle = Text("PgUp/PgDn to page  •  Ctrl-C to quit", style="grey42")
    return Panel(
        Group(
            _build_header(page, total_pages, symbol_count, interval, now),
            Rule(style="grey35"),
            _build_rows_table(page_symbols),
        ),
        box=box.ROUNDED,
        border_style="blue",
        padding=(0, 1),
        height=height,
        title=Text(" pm-board ", style="grey58"),
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
    )


class MarketBoard:
    def __init__(self, rows_per_page: int, interval: float) -> None:
        self.rows_per_page = max(1, rows_per_page)
        self.interval = max(1, interval)
        self._lock = threading.Lock()
        self._running = True

        # symbol -> aggregated data
        self._symbols: dict[str, dict[str, Any]] = {}
        self._page = 0
        self._last_page_change = time.monotonic()

        self.sub = make_subscriber(
            ENGINE_PUB_ADDR,
            PREFIX_BOOK_SNAPSHOT,
            TOPIC_TRADE_EXECUTED,
            topic_symbols(BOARD_GATEWAY_ID),
        )
        # PUSH socket to ask the engine for the symbol list and, per symbol,
        # a book snapshot — otherwise symbols whose book was only ever
        # seeded with startup market-maker quotes (no order/trade since)
        # never publish a book.* message and stay invisible.
        self.push = make_pusher(ENGINE_PULL_ADDR)
        self._symbols_requested_at = 0.0
        self._symbols_received = False

        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

    def _dbg_count(self, key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        self._debug_counts[key] += amount
        self._flush_debug_summary()

    def _flush_debug_summary(self, force: bool = False) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if not force and now - self._debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not self._debug_counts:
            self._debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(self._debug_counts.items())
        )
        log.debug("board flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    # ------------------------------------------------------------------
    # Symbol request / retry
    # ------------------------------------------------------------------

    def _request_symbols(self) -> None:
        try:
            self.push.send_multipart(make_symbols_request_msg(BOARD_GATEWAY_ID))
            self._symbols_requested_at = time.monotonic()
        except zmq.Again:
            log.debug("engine not reachable yet for symbols request")

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle(self, topic_str: str, payload: dict[str, Any]) -> None:
        self._dbg_count("incoming_total")

        if topic_str.startswith(PREFIX_BOOK_SNAPSHOT):
            self._dbg_count("incoming_book")
            sym = topic_str[len(PREFIX_BOOK_SNAPSHOT) :]
            with self._lock:
                entry = self._symbols.setdefault(
                    sym, {"first_price": None, "volume": 0}
                )
                entry["last_price"] = payload.get("last_price")
                entry["last_buy_price"] = payload.get("last_buy_price")
                entry["last_sell_price"] = payload.get("last_sell_price")
                entry["updated"] = datetime.now()

                bids = payload.get("bids", [])
                asks = payload.get("asks", [])
                entry["best_bid"] = bids[0].get("price") if bids else None
                entry["best_ask"] = asks[0].get("price") if asks else None

                if entry["first_price"] is None and entry["last_price"] is not None:
                    entry["first_price"] = entry["last_price"]

        elif topic_str == TOPIC_TRADE_EXECUTED:
            self._dbg_count("incoming_trade")
            trade_sym: str | None = payload.get("symbol")
            if trade_sym:
                with self._lock:
                    entry = self._symbols.setdefault(
                        trade_sym, {"first_price": None, "volume": 0}
                    )
                    trade_price = payload.get("price")
                    trade_qty = payload.get("quantity", 0)
                    entry["last_price"] = trade_price
                    entry["volume"] = entry.get("volume", 0) + trade_qty
                    entry["updated"] = datetime.now()
                    if entry["first_price"] is None and trade_price is not None:
                        entry["first_price"] = trade_price

        elif topic_str == topic_symbols(BOARD_GATEWAY_ID):
            self._dbg_count("incoming_symbols")
            self._symbols_received = True
            for entry in payload.get("symbols", []):
                sym = str(entry.get("symbol", ""))
                if sym:
                    self.push.send_multipart(make_book_snapshot_request_msg(sym))
        else:
            self._dbg_count("incoming_unhandled")

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                self._dbg_count("receive_poll_eintr")
                break
            if self.sub not in socks:
                continue
            frames = self.sub.recv_multipart()
            topic_str, payload = decode(frames)
            self._handle(topic_str, payload)
        self._flush_debug_summary(force=True)

    # ------------------------------------------------------------------
    # Paging
    # ------------------------------------------------------------------

    def _total_pages(self) -> int:
        with self._lock:
            n = len(self._symbols)
        return max(1, (n + self.rows_per_page - 1) // self.rows_per_page)

    def _advance_page(self, delta: int) -> None:
        """Move the current page by ``delta`` (wrapping) and restart the
        auto-rotate countdown from this moment — called both by the timer
        (delta=+1) and by manual PgUp/PgDn/ENTER (delta=-1/+1), so a manual
        page change always buys a full --interval of undisturbed reading
        before the next rotation, timer- or key-driven alike."""
        total = self._total_pages()
        with self._lock:
            self._page = (self._page + delta) % total
            self._last_page_change = time.monotonic()

    # ------------------------------------------------------------------
    # Keyboard paging thread
    # ------------------------------------------------------------------

    def _read_keys(self) -> None:
        """Background reader for manual PgUp/PgDn/ENTER paging.

        Same select()-on-fd pattern as pm-orders' key-reader thread: raw
        prompt_toolkit input (already a project dependency) polled with
        select() rather than prompt_toolkit's attach(), which needs an
        asyncio event loop a plain background thread doesn't have. Any
        manual page change resets the auto-rotate countdown so a person
        paging through the board isn't fighting the timer.
        """
        import select

        try:
            from prompt_toolkit.input import create_input
            from prompt_toolkit.keys import Keys
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("keyboard paging unavailable: %s", exc)
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
                        if key == Keys.PageDown or key == Keys.ControlM:
                            # ControlM is ENTER in prompt_toolkit's raw-mode
                            # key names — kept for the documented shortcut.
                            self._advance_page(1)
                            self._dbg_count("manual_page_advances")
                        elif key == Keys.PageUp:
                            self._advance_page(-1)
                            self._dbg_count("manual_page_advances")
                        elif key == Keys.ControlC:
                            self._running = False
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("keyboard paging thread stopped: %s", exc)
        finally:
            try:
                input_.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(self) -> Panel:
        height = console.size.height
        now = datetime.now()

        with self._lock:
            sorted_syms = sorted(self._symbols.keys())
            total_pages = max(
                1, (len(sorted_syms) + self.rows_per_page - 1) // self.rows_per_page
            )
            page = self._page % total_pages
            self._page = page
            start = page * self.rows_per_page
            page_syms = sorted_syms[start : start + self.rows_per_page]
            page_symbols = [(sym, dict(self._symbols[sym])) for sym in page_syms]
            symbol_count = len(sorted_syms)

        return _build_panel(
            page,
            total_pages,
            symbol_count,
            int(self.interval),
            now,
            page_symbols,
            height=height,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))

        self._request_symbols()

        t = threading.Thread(target=self._receive, daemon=True)
        t.start()

        kt = threading.Thread(target=self._read_keys, daemon=True)
        kt.start()

        try:
            # screen=True paints on the alternate screen buffer and repaints
            # the whole box at the current terminal size every frame — same
            # as pm-ticker/pm-viewer/pm-orders. transient=True restores the
            # normal terminal and scrollback on exit.
            with Live(
                console=console, auto_refresh=False, screen=True, transient=True
            ) as live:
                while self._running:
                    # Retry the symbols request until the engine answers —
                    # it may not have been up yet when the board started.
                    if (
                        not self._symbols_received
                        and time.monotonic() - self._symbols_requested_at
                        >= _SYMBOLS_REQUEST_RETRY_SEC
                    ):
                        self._request_symbols()

                    # Auto-rotate on the timer, unless a manual page change
                    # (PgUp/PgDn/ENTER) restarted the countdown more
                    # recently — _advance_page is the single place that
                    # touches _last_page_change, whether the rotation was
                    # driven by the clock or by a keypress.
                    if time.monotonic() - self._last_page_change >= self.interval:
                        self._advance_page(1)
                        self._dbg_count("auto_page_advances")

                    live.update(self._render())
                    live.refresh()
                    self._dbg_count("renders")
                    self._flush_debug_summary()
                    time.sleep(1 / _REFRESH_HZ)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            t.join(timeout=2.0)
            kt.join(timeout=2.0)
            self.sub.close()
            self.push.close()
            self._flush_debug_summary(force=True)
            log.info("board shutdown complete")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher multi-symbol board")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-board")
    parser.add_argument(
        "--rows",
        "-r",
        type=int,
        default=8,
        help="Max symbols (rows) per page (default 8)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=10,
        help="Auto-rotate interval in seconds (default 10)",
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
    log.info("starting pm-board with log level %s", logging.getLevelName(log_level))
    MarketBoard(rows_per_page=args.rows, interval=args.interval).run()


if __name__ == "__main__":
    main()
