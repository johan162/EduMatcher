"""
Ticker Process — old-fashioned scrolling market ticker in the terminal.

Usage:
  poetry run pm-ticker [--db data/stats.db] [--db-interval 900]

Subscribes to:
  book.*  — live last price, best bid/ask per symbol

Queries:
  daily_stats table in the statistics SQLite DB every --db-interval seconds
  (default 900 = 15 minutes) for OHLCV, VWAP, and trade count.

Display:
  A bordered box is drawn across the top rows of the terminal. It holds a
  header (the "EduMatcher" brand, today's total trade volume and the current
  date/time) and a single ticker line that scrolls the symbols leftward like
  a classic ticker tape.

  • If every symbol fits within the current width the line stays static and
    does not scroll.
  • Scrolling only starts once the symbols are wider than the box.
  • The box re-draws to the terminal width on resize; below a minimum width
    the ticker line is truncated with an ellipsis ("…").
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import errno
import logging
import signal
import sqlite3
import threading
import time
from datetime import datetime, tzinfo
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

from edumatcher.config import ENGINE_PUB_ADDR, STATS_DB_FILE, resolve_data_path
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode
from edumatcher.stats.query import resolve_session_timezone
from edumatcher.stats.trading_day import resolve_timezone, trading_date
from edumatcher.models.generated.book import PREFIX_BOOK_SNAPSHOT

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DB_REFRESH_DEFAULT = 900  # seconds between daily_stats re-queries (15 min)

_DEBUG_SUMMARY_INTERVAL_SEC = 5.0

_SCROLL_FPS = 12  # marquee refresh rate
_SCROLL_STEP = 1  # columns advanced per frame while scrolling
_MIN_TICKER_WIDTH = 24  # below this inner width the line is ellipsised
_BOX_HEIGHT = 5  # header + rule + ticker + top/bottom border
_FRAME_PADDING = 4  # 2 border cells + 2 horizontal padding cells
_SEP = "  \u25c6  "  # inter-symbol separator (also the marquee wrap gap)
_GAP_LEN = len(_SEP)

console = Console(highlight=False)
log = logging.getLogger(__name__)

_CLIENT_NAME = "pm-ticker"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _query_daily_stats(
    conn: sqlite3.Connection, today: str
) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT symbol, open_price, high_price, low_price, close_price, "
        "       volume, trade_count, vwap "
        "FROM daily_stats WHERE date = ?",
        (today,),
    ).fetchall()
    return {
        sym: {
            "open_price": op,
            "high_price": hi,
            "low_price": lo,
            "close_price": cl,
            "volume": vol or 0,
            "trade_count": tc or 0,
            "vwap": vwap,
        }
        for sym, op, hi, lo, cl, vol, tc, vwap in rows
    }


# ---------------------------------------------------------------------------
# Line builders
# ---------------------------------------------------------------------------


def _format_symbol(
    sym: str,
    d: dict[str, Any],
    lv: dict[str, Any],
) -> Text:
    """Format one symbol's data as a Rich Text segment."""
    frag = Text()

    last_price = lv.get("last_price") or d.get("close_price")
    open_price = d.get("open_price")
    high_price = d.get("high_price")
    low_price = d.get("low_price")
    volume = d.get("volume", 0)
    trade_count = d.get("trade_count", 0)
    best_bid = lv.get("best_bid")
    best_ask = lv.get("best_ask")

    # Symbol name
    frag.append(sym, style="bold cyan")

    # Last price
    if last_price is not None:
        frag.append(f"  {last_price:>8.2f}", style="bold white")
    else:
        frag.append("        —", style="dim")

    # % change vs open
    if last_price is not None and open_price and open_price != 0:
        pct = (last_price - open_price) / open_price * 100
        sign = "+" if pct >= 0 else ""
        color = "bright_green" if pct > 0 else ("bright_red" if pct < 0 else "white")
        frag.append(f"  {sign}{pct:.2f}%", style=color)
    else:
        frag.append("       —  ", style="dim")

    # High / Low
    if high_price is not None:
        frag.append(f"  H:{high_price:.2f}", style="green")
    if low_price is not None:
        frag.append(f"  L:{low_price:.2f}", style="red")

    # Volume + trade count
    if volume:
        frag.append(f"  Vol:{volume:,}", style="dim")
    if trade_count:
        frag.append(f" ({trade_count}T)", style="dim")

    # Bid / Ask spread
    if best_bid is not None and best_ask is not None:
        frag.append(f"  {best_bid:.2f}", style="green")
        frag.append("/", style="dim")
        frag.append(f"{best_ask:.2f}", style="red")
    elif best_bid is not None:
        frag.append(f"  {best_bid:.2f}/—", style="green")
    elif best_ask is not None:
        frag.append(f"  —/{best_ask:.2f}", style="red")

    return frag


def _build_ticker_text(
    symbols: list[str],
    daily: dict[str, dict[str, Any]],
    live: dict[str, dict[str, Any]],
) -> Text:
    """Concatenate every symbol into one Text, joined by the ◆ separator."""
    line = Text()
    for i, sym in enumerate(symbols):
        if i > 0:
            line.append(_SEP, style="dim")
        line.append_text(_format_symbol(sym, daily.get(sym, {}), live.get(sym, {})))
    return line


def _build_line(  # pyright: ignore[reportUnusedFunction]
    symbols: list[str],
    daily: dict[str, dict[str, Any]],
    live: dict[str, dict[str, Any]],
) -> Text:
    """Compose one timestamped ticker line for all symbols.

    Retained as a stable helper: a leading ``HH:MM:SS`` timestamp followed by
    the symbol run produced by :func:`_build_ticker_text`.
    """
    line = Text()
    line.append(f"{datetime.now().strftime('%H:%M:%S')}  ", style="dim")
    line.append_text(_build_ticker_text(symbols, daily, live))
    return line


# ---------------------------------------------------------------------------
# Marquee / framing
# ---------------------------------------------------------------------------


def _marquee_window(full: Text, width: int, offset: int) -> Text:
    """Return a ``width``-column slice of ``full`` starting at ``offset``.

    A separator gap is appended so the run repeats seamlessly, and the text
    is tiled enough times to always cover ``offset + width`` before slicing —
    giving a continuous left-scrolling marquee.
    """
    one = full.copy()
    one.append(_SEP, style="dim")
    period = len(one.plain)
    if period <= 0 or width <= 0:
        return Text("")
    copies = (offset + width) // period + 2
    loop = Text()
    for _ in range(copies):
        loop.append_text(one)
    window = loop.divide([offset, offset + width])[1]
    window.no_wrap = True
    window.overflow = "crop"
    return window


def _fit_static(full: Text, inner: int) -> Text:
    """Non-scrolling content: the full run, ellipsised if too narrow to fit."""
    if full.cell_len <= inner:
        text = full
    else:
        text = full.copy()
        text.truncate(max(1, inner), overflow="ellipsis")
    text.no_wrap = True
    text.overflow = "crop"
    return text


def _build_header(total_volume: int, symbol_count: int, now: datetime) -> Table:
    """The header row: brand + total volume + symbol count on the left, the
    live date/time pinned to the right."""
    grid = Table.grid(expand=True)
    grid.add_column(no_wrap=True, overflow="ellipsis")  # brand / stats
    grid.add_column(ratio=1)  # elastic spacer
    grid.add_column(no_wrap=True, justify="right")  # clock

    left = Text.assemble(
        (" EduMatcher ", "bold white on blue"),
        ("  ", ""),
        ("Total Vol ", "grey62"),
        (f"{total_volume:,}", "bold white"),
        ("   \u2502   ", "grey35"),
        ("Symbols ", "grey62"),
        (f"{symbol_count}", "white"),
    )
    # Date dimmer than the ticking clock, same contrast as pm-viewer's
    # header (line1's clock is "bold cyan", line2's date is plain "cyan").
    right = Text.assemble(
        (now.strftime("%Y-%m-%d "), "cyan"),
        (now.strftime("%H:%M:%S"), "bold cyan"),
    )
    grid.add_row(left, Text(""), right)
    return grid


def _build_panel(
    total_volume: int, symbol_count: int, now: datetime, ticker_line: Text
) -> Panel:
    """Assemble the full top-of-screen ticker box."""
    return Panel(
        Group(
            _build_header(total_volume, symbol_count, now),
            Rule(style="grey35"),
            ticker_line,
        ),
        box=box.ROUNDED,
        border_style="blue",
        padding=(0, 1),
        height=_BOX_HEIGHT,
        title=Text(" pm-ticker ", style="grey58"),
        title_align="left",
        subtitle=Text("Ctrl-C to quit", style="grey42"),
        subtitle_align="right",
    )


# ---------------------------------------------------------------------------
# Ticker process
# ---------------------------------------------------------------------------


class TickerProcess:
    def __init__(
        self,
        db_path: Path,
        db_interval: float,
        session_tz: tzinfo | None = None,
    ) -> None:
        self._db_path = db_path
        self._db_interval = db_interval
        #: ``None`` means "use whatever the database was recorded with",
        #: resolved per refresh so a ticker started before pm-stats created
        #: the file still picks it up.
        self._tz_override = session_tz
        self._running = True
        self._lock = threading.Lock()

        # Live data populated from ZMQ book updates
        self._live: dict[str, dict[str, Any]] = {}
        # Daily OHLCV from SQLite
        self._daily: dict[str, dict[str, Any]] = {}
        # Stable sorted list of known symbols
        self._symbols: list[str] = []

        # Marquee horizontal scroll offset (columns)
        self._scroll_offset = 0

        self._last_db_refresh = 0.0
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        self.sub = make_subscriber(ENGINE_PUB_ADDR, PREFIX_BOOK_SNAPSHOT)

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
        log.debug("ticker flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    # ------------------------------------------------------------------
    # DB refresh
    # ------------------------------------------------------------------

    def _refresh_db(self) -> None:
        if not self._db_path.exists():
            self._dbg_count("db_refresh_skipped_missing_file")
            return
        try:
            conn = sqlite3.connect(str(self._db_path))
            try:
                # daily_stats.date holds the trading date in the exchange's
                # session timezone, so resolve "today" the same way pm-stats
                # wrote it — the host's local date is a different clock. The
                # timezone is read from the database rather than configured
                # here, so the ticker cannot disagree with the recorder.
                tz = self._tz_override
                if tz is None:
                    tz, _warning = resolve_session_timezone(conn)
                today = trading_date(time.time(), tz)
                daily = _query_daily_stats(conn, today)
            finally:
                conn.close()
            with self._lock:
                self._daily = daily
                for sym in daily:
                    if sym not in self._symbols:
                        self._symbols.append(sym)
                self._symbols.sort()
            self._dbg_count("db_refresh_ok")
            self._dbg_count("db_rows_loaded", len(daily))
        except Exception as exc:
            self._dbg_count("db_refresh_errors")
            log.warning("ticker DB read error: %s", exc)

    # ------------------------------------------------------------------
    # ZMQ receive thread
    # ------------------------------------------------------------------

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        log.info("ticker receive loop started")
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
            try:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
            except Exception:
                self._dbg_count("receive_decode_errors")
                continue

            if topic.startswith(PREFIX_BOOK_SNAPSHOT):
                symbol = topic.split(".", 1)[1]
                bids = payload.get("bids", [])
                asks = payload.get("asks", [])
                with self._lock:
                    self._live[symbol] = {
                        "last_price": payload.get("last_price"),
                        "best_bid": bids[0].get("price") if bids else None,
                        "best_ask": asks[0].get("price") if asks else None,
                    }
                    if symbol not in self._symbols:
                        self._symbols.append(symbol)
                        self._symbols.sort()
                self._dbg_count("book_events")
                self._dbg_count("symbols_seen", 1 if symbol not in self._daily else 0)
        self._flush_debug_summary(force=True)
        log.info("ticker receive loop stopped")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render(
        self,
        symbols: list[str],
        daily: dict[str, dict[str, Any]],
        live: dict[str, dict[str, Any]],
    ) -> Panel:
        """Build the ticker box for the current terminal width, advancing the
        marquee offset only when the content is wider than the box."""
        inner = max(1, console.size.width - _FRAME_PADDING)
        now = datetime.now()
        total_volume = sum(int(d.get("volume") or 0) for d in daily.values())

        if symbols:
            full = _build_ticker_text(symbols, daily, live)
            if full.cell_len > inner and inner >= _MIN_TICKER_WIDTH:
                period = full.cell_len + _GAP_LEN
                self._scroll_offset = (self._scroll_offset + _SCROLL_STEP) % max(
                    1, period
                )
                ticker = _marquee_window(full, inner, self._scroll_offset)
            else:
                self._scroll_offset = 0
                ticker = _fit_static(full, inner)
        else:
            self._scroll_offset = 0
            ticker = Text("waiting for market data…", style="dim italic")
            ticker.no_wrap = True

        return _build_panel(total_volume, len(symbols), now, ticker)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())
        log.info(
            "starting ticker runtime db=%s db_interval=%s",
            self._db_path,
            self._db_interval,
        )

        t = threading.Thread(target=self._receive, daemon=True)
        t.start()

        # Initial DB load so the box shows data immediately if available.
        self._refresh_db()
        self._last_db_refresh = time.monotonic()

        frame_interval = 1.0 / _SCROLL_FPS

        # screen=True paints on the alternate screen buffer and repaints the
        # whole box at the current terminal size every frame, so resizes never
        # leave stale columns behind. transient=True restores the normal
        # terminal (and scrollback) on exit.
        try:
            with Live(
                console=console, auto_refresh=False, screen=True, transient=True
            ) as live:
                while self._running:
                    now = time.monotonic()
                    if now - self._last_db_refresh >= self._db_interval:
                        self._refresh_db()
                        self._last_db_refresh = now

                    with self._lock:
                        syms = list(self._symbols)
                        daily = dict(self._daily)
                        live_data = dict(self._live)

                    live.update(self._render(syms, daily, live_data))
                    live.refresh()
                    self._dbg_count("frames_rendered")
                    self._flush_debug_summary()
                    time.sleep(frame_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False  # ensure _receive exits even on exception
            t.join(timeout=2.0)  # wait for thread before touching the socket
            self.sub.close()  # safe: _receive is no longer polling
            self._flush_debug_summary(force=True)
        log.info("ticker shutdown complete")

    def _stop(self) -> None:
        self._running = False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-ticker with log level %s", logging.getLevelName(log_level))
    session_tz = None
    if args.timezone is not None:
        session_tz = resolve_timezone(args.timezone)
        if session_tz is None:
            parser.error(f"--timezone: unknown timezone {args.timezone!r}")
    TickerProcess(
        db_path=resolve_data_path(args.db),
        db_interval=args.db_interval,
        session_tz=session_tz,
    ).run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher scrolling market ticker")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ticker")
    parser.add_argument(
        "--db",
        default=str(STATS_DB_FILE),
        metavar="PATH",
        help=f"Statistics SQLite database (default: {STATS_DB_FILE})",
    )
    parser.add_argument(
        "--db-interval",
        type=float,
        default=_DB_REFRESH_DEFAULT,
        metavar="SEC",
        help=f"Seconds between daily_stats DB re-queries (default: {_DB_REFRESH_DEFAULT})",
    )
    parser.add_argument(
        "--timezone",
        metavar="TZ",
        default=None,
        help=(
            "Override the session timezone used to resolve today's trading "
            "date. By default the timezone the statistics database was "
            "recorded with is used, which is almost always what you want"
        ),
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


if __name__ == "__main__":
    main()
