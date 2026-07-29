"""
Order Book Viewer — live terminal display for a single symbol.

Usage:
  poetry run pm-viewer --symbol AAPL [--depth N]

Subscribes to book.<SYMBOL> and renders a full-screen, self-redrawing order
book showing:
  • A status header: last price, intraday change / %, session O/H/L/C,
    best bid/ask, spread, session volume and a live clock.
  • Three equal-height panels (Bids / Asks / Trades) that fill the terminal
    height and show the top rows that fit.

The header's session OHLC and volume are derived locally from the live
``book.<SYMBOL>`` feed (the engine's book snapshot carries no OHLC), so they
reflect activity observed since the viewer connected. ``prev_close`` is wired
through for a future feed that provides it; until then the percentage change
is measured against the session open.

Iceberg orders show only displayed_qty — the hidden size is intentionally
invisible, demonstrating the privacy feature of iceberg orders.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import errno
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
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

from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_PUB_ADDR, STATS_DB_FILE
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_subscriber, make_pusher
from edumatcher.models.message import decode, make_book_snapshot_request_msg

console = Console()
log = logging.getLogger(__name__)

_CLIENT_NAME = "pm-viewer"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

_REFRESH_HZ = 4  # rich Live refresh rate
_MAX_RECENT_TRADES = 50  # upper bound; actual shown is driven by screen height
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0
_SNAPSHOT_INITIAL_DELAY_SEC = 0.15
_SNAPSHOT_RETRY_TIMEOUT_SEC = 2.0
_SNAPSHOT_RETRY_INTERVAL_SEC = 0.1

# Chrome (non-data rows) consumed by the outer frame + header + column titles.
# Used to work out how many data rows fit the current terminal height.
_CHROME_ROWS = 9
_BAR_WIDTH = 6  # width of the depth micro-bar column, in cells

_UP = "green"
_DOWN = "red"
_FLAT = "grey70"


def request_snapshot_with_retry(
    symbol: str,
    *,
    initial_delay_sec: float = _SNAPSHOT_INITIAL_DELAY_SEC,
    retry_timeout_sec: float = _SNAPSHOT_RETRY_TIMEOUT_SEC,
    retry_interval_sec: float = _SNAPSHOT_RETRY_INTERVAL_SEC,
) -> None:
    """Ask the engine for the current book snapshot for ``symbol``.

    ``make_pusher()`` sets ``IMMEDIATE=1`` + ``SNDTIMEO=0`` (fail-fast, so
    gateways never block their reactor on a slow/absent engine). That means
    ``send_multipart()`` raises :class:`zmq.Again` if the PUSH->PULL
    handshake to the engine hasn't completed yet, which easily races a short
    startup sleep -- especially the first time ``pm-viewer`` connects. Retry
    for up to ``retry_timeout_sec`` instead of letting the caller's thread
    crash with an unhandled traceback; if the engine is genuinely
    unreachable this gives up quietly and logs a warning -- the live
    ``book.<SYMBOL>`` feed will still populate the display once the engine
    is reachable.
    """
    time.sleep(initial_delay_sec)
    push = make_pusher(ENGINE_PULL_ADDR)
    try:
        deadline = time.monotonic() + retry_timeout_sec
        while True:
            try:
                push.send_multipart(make_book_snapshot_request_msg(symbol))
                return
            except zmq.Again:
                if time.monotonic() >= deadline:
                    log.warning(
                        "could not reach engine at %s for initial snapshot "
                        "request (symbol=%s); live updates will still "
                        "populate the book once the engine is reachable",
                        ENGINE_PULL_ADDR,
                        symbol,
                    )
                    return
                time.sleep(retry_interval_sec)
    finally:
        push.close()


def _load_stats_from_db(db_path: Path, symbol: str) -> "_SessionStats":
    """Seed a :class:`_SessionStats` from the stats SQLite database.

    Queries two rows from ``daily_stats``:
    - Today's row  → true intraday O/H/L/C and volume so far.
    - Yesterday's row → previous close for the change % baseline.

    If the DB doesn't exist yet (stats process hasn't run) or the symbol
    has no rows, returns an empty :class:`_SessionStats` and logs a note.
    Both queries are read-only and fail-safe — any error just leaves the
    corresponding fields as ``None``, which the header renders as "—" /
    "n/a", and the live feed fills them in as trades arrive.
    """
    stats = _SessionStats()
    if not db_path.exists():
        log.debug(
            "stats DB not found at %s; OHLC will accumulate from live feed", db_path
        )
        return stats

    today = date.today().isoformat()
    sym = symbol.upper()
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            # Today's intraday row — may be partial (session still live).
            row = conn.execute(
                "SELECT open_price, high_price, low_price, close_price, volume "
                "FROM daily_stats WHERE date = ? AND symbol = ?",
                (today, sym),
            ).fetchone()
            if row:
                op, hi, lo, cl, vol = row
                if isinstance(op, (int, float)):
                    stats.open = float(op)
                if isinstance(hi, (int, float)):
                    stats.high = float(hi)
                if isinstance(lo, (int, float)):
                    stats.low = float(lo)
                if isinstance(cl, (int, float)):
                    stats.close = float(cl)
                if isinstance(vol, (int, float)):
                    stats.volume = int(vol)
                log.debug(
                    "loaded today OHLCV from stats DB symbol=%s O=%s H=%s L=%s C=%s vol=%s",
                    sym,
                    stats.open,
                    stats.high,
                    stats.low,
                    stats.close,
                    stats.volume,
                )

            # Most recent prior-day close for a meaningful % change.
            prev_row = conn.execute(
                "SELECT close_price FROM daily_stats "
                "WHERE symbol = ? AND date < ? AND close_price IS NOT NULL "
                "ORDER BY date DESC LIMIT 1",
                (sym, today),
            ).fetchone()
            if prev_row and isinstance(prev_row[0], (int, float)):
                stats.prev_close = float(prev_row[0])
                log.debug(
                    "loaded prev_close from stats DB symbol=%s prev_close=%s",
                    sym,
                    stats.prev_close,
                )
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        # DB exists but table absent (first run, schema not yet created).
        log.debug("stats DB query failed for %s: %s", sym, exc)
    except Exception as exc:
        log.warning("unexpected error reading stats DB for %s: %s", sym, exc)

    return stats


@dataclass
class _SessionStats:
    """Intraday statistics accumulated from the live book feed.

    The engine book snapshot has no OHLC, so we derive session open / high /
    low / close from the ``last_price`` seen on each snapshot and volume from
    de-duplicated ``recent_trades`` ids.
    """

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    prev_close: float | None = None  # reserved for a future feed
    volume: int = 0
    _seen_trades: set[Any] = field(default_factory=set)

    def update(self, snapshot: dict[str, Any]) -> None:
        last = snapshot.get("last_price")
        if isinstance(last, (int, float)):
            if self.open is None:
                self.open = float(last)
            self.high = float(last) if self.high is None else max(self.high, last)
            self.low = float(last) if self.low is None else min(self.low, last)
            self.close = float(last)

        pc = snapshot.get("prev_close")
        if isinstance(pc, (int, float)):
            self.prev_close = float(pc)

        for tr in snapshot.get("recent_trades", []) or []:
            tid = tr.get("id")
            if tid is None or tid in self._seen_trades:
                continue
            self._seen_trades.add(tid)
            try:
                self.volume += int(tr.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                pass

    @property
    def reference(self) -> float | None:
        """Baseline for the change/percentage: prior close if known, else open."""
        return self.prev_close if self.prev_close is not None else self.open


def _fmt_price(value: Any, prec: int = 4) -> str:
    return f"{value:.{prec}f}" if isinstance(value, (int, float)) else "—"


def _fmt_int(value: Any) -> str:
    return f"{int(value):,}" if isinstance(value, (int, float)) else "—"


def _direction_style(value: float | None, reference: float | None) -> str:
    if value is None or reference is None or value == reference:
        return _FLAT
    return _UP if value > reference else _DOWN


def _bar(qty: Any, max_qty: int, style: str, *, reverse: bool = False) -> Text:
    """A proportional depth micro-bar of block glyphs for one price level."""
    if not isinstance(qty, (int, float)) or max_qty <= 0 or qty <= 0:
        return Text("")
    filled = max(1, round(_BAR_WIDTH * qty / max_qty))
    filled = min(filled, _BAR_WIDTH)
    bar = "\u2588" * filled
    pad = " " * (_BAR_WIDTH - filled)
    return Text((bar + pad) if reverse else (pad + bar), style=style)


def _blank_row(n_cols: int) -> list[str]:
    return [""] * n_cols


def _stat_line(left_cells: list[Text], right_cell: Text) -> Table:
    """One header row: content cells packed left, one cell pinned right."""
    grid = Table.grid(expand=True, padding=(0, 0))
    for _ in left_cells:
        grid.add_column(justify="left", no_wrap=True)
    grid.add_column(justify="left", ratio=1, min_width=3)  # elastic spacer
    grid.add_column(justify="right", no_wrap=True)
    grid.add_row(*left_cells, Text(""), right_cell)
    return grid


def _label(text: str) -> tuple[str, str]:
    return (f"{text} ", "grey62")


def _sep() -> tuple[str, str]:
    return ("   \u2502   ", "grey35")


def _build_header(
    snapshot: dict[str, Any],
    symbol: str,
    stats: _SessionStats,
    best_bid: float | None,
    best_ask: float | None,
) -> Group:
    last = snapshot.get("last_price")
    last_qty = snapshot.get("last_qty")
    reference = stats.reference
    change = (
        last - reference
        if isinstance(last, (int, float)) and reference is not None
        else None
    )
    pct = (change / reference * 100.0) if change is not None and reference else None
    trend = _direction_style(
        last if isinstance(last, (int, float)) else None, reference
    )
    arrow = "\u25b2" if trend == _UP else "\u25bc" if trend == _DOWN else "\u25ac"
    spread = (
        best_ask - best_bid if best_bid is not None and best_ask is not None else None
    )

    line1_left = Text.assemble(
        _label("LAST"),
        (_fmt_price(last), f"bold {trend}"),
        (f" {arrow}  ", trend),
        _label("CHG"),
        ((f"{change:+.4f}" if change is not None else "—"), trend),
        ("  ", ""),
        ((f"{pct:+.2f}%" if pct is not None else "—"), f"bold {trend}"),
        _sep(),
        _label("SIZE"),
        (_fmt_int(last_qty), "white"),
        _sep(),
        _label("BID/ASK"),
        (_fmt_price(best_bid), _UP),
        (" x ", "grey62"),
        (_fmt_price(best_ask), _DOWN),
        _sep(),
        _label("SPRD"),
        (_fmt_price(spread), "yellow"),
    )
    now = datetime.now()
    line1_right = Text(now.strftime("%H:%M:%S"), style="bold cyan")

    line2_left = Text.assemble(
        _label("O"),
        (_fmt_price(stats.open), "white"),
        _label("  H"),
        (_fmt_price(stats.high), _UP),
        _label("  L"),
        (_fmt_price(stats.low), _DOWN),
        _label("  C"),
        (_fmt_price(stats.close), "white"),
        _sep(),
        _label("PREV"),
        (
            _fmt_price(stats.prev_close) if stats.prev_close is not None else "n/a",
            "white",
        ),
        _sep(),
        _label("RANGE"),
        (
            (
                _fmt_price(stats.high - stats.low)
                if isinstance(stats.high, (int, float))
                and isinstance(stats.low, (int, float))
                else "—"
            ),
            "magenta",
        ),
        _sep(),
        _label("VOL"),
        (_fmt_int(stats.volume), "white"),
    )
    line2_right = Text.assemble(
        _label("BASIS"),
        ("prev-close" if stats.prev_close is not None else "session-open", "grey70"),
        _sep(),
        (now.strftime("%Y-%m-%d"), "cyan"),
    )

    return Group(
        _stat_line([line1_left], line1_right),
        _stat_line([line2_left], line2_right),
    )


def _side_table(
    title: str,
    rows: list[dict[str, Any]],
    color: str,
    capacity: int,
    *,
    is_bid: bool,
) -> Table:
    tbl = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        show_edge=False,
        pad_edge=False,
        title=f"[bold {color}]{title}[/]",
        title_justify="center",
        header_style=f"bold {color}",
        row_styles=["", "grey11"],
    )
    max_qty = max((int(r.get("qty", 0) or 0) for r in rows[:capacity]), default=0)

    if is_bid:
        tbl.add_column("Depth", justify="right", width=_BAR_WIDTH, no_wrap=True)
        tbl.add_column("Price", justify="right", style=color, no_wrap=True)
        tbl.add_column("Qty", justify="right", no_wrap=True)
        tbl.add_column("Ord", justify="right", no_wrap=True)
    else:
        tbl.add_column("Price", justify="left", style=color, no_wrap=True)
        tbl.add_column("Qty", justify="left", no_wrap=True)
        tbl.add_column("Ord", justify="left", no_wrap=True)
        tbl.add_column("Depth", justify="left", width=_BAR_WIDTH, no_wrap=True)

    shown = rows[:capacity]
    for lvl in shown:
        price = _fmt_price(lvl.get("price"))
        qty = _fmt_int(lvl.get("qty"))
        cnt = str(lvl.get("count", ""))
        bar = _bar(lvl.get("qty"), max_qty, color, reverse=not is_bid)
        if is_bid:
            tbl.add_row(bar, price, qty, cnt)
        else:
            tbl.add_row(price, qty, cnt, bar)

    for _ in range(capacity - len(shown)):
        tbl.add_row(*_blank_row(4))
    return tbl


def _trades_table(recent: list[dict[str, Any]], capacity: int) -> Table:
    tbl = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        show_edge=False,
        pad_edge=False,
        title="[bold cyan]TRADES[/]",
        title_justify="center",
        header_style="bold cyan",
        row_styles=["", "grey11"],
    )
    tbl.add_column("Time", no_wrap=True)
    tbl.add_column("Price", justify="right", no_wrap=True)
    tbl.add_column("Qty", justify="right", no_wrap=True)

    # Newest first; colour each print by tick direction vs the older trade.
    ordered = list(reversed(recent[-capacity:]))
    for i, tr in enumerate(ordered):
        price = tr.get("price")
        older = ordered[i + 1].get("price") if i + 1 < len(ordered) else None
        style = _direction_style(
            price if isinstance(price, (int, float)) else None,
            older if isinstance(older, (int, float)) else None,
        )
        ts_raw = tr.get("timestamp")
        if isinstance(ts_raw, (int, float)):
            try:
                ts = datetime.fromtimestamp(ts_raw).strftime("%H:%M:%S.%f")[:-3]
            except (ValueError, OSError):
                ts = "—"
        else:
            ts = "—"
        tbl.add_row(
            Text(ts, style="grey70"),
            Text(_fmt_price(price), style=style),
            Text(_fmt_int(tr.get("quantity")), style=style),
        )

    for _ in range(capacity - len(ordered)):
        tbl.add_row(*_blank_row(3))
    return tbl


def _build_display(
    snapshot: dict[str, Any],
    symbol: str,
    depth: int | None = None,
    *,
    stats: _SessionStats | None = None,
    size: tuple[int, int] | None = None,
) -> Panel:
    """Render the full-screen order book as a single :class:`rich.panel.Panel`.

    ``depth`` caps the number of price levels shown; when ``None`` the display
    grows to fill the terminal height. ``stats`` supplies the session OHLC/vol
    accumulated by the caller; when omitted a throwaway one is derived from the
    current snapshot so the function stays pure enough for tests.
    """
    height = size[1] if size is not None else console.size.height

    if stats is None:
        stats = _SessionStats()
        stats.update(snapshot)

    bids = snapshot.get("bids", []) or []
    asks = snapshot.get("asks", []) or []
    best_bid = bids[0].get("price") if bids else None
    best_ask = asks[0].get("price") if asks else None

    # Rows that fit the current height, shared by all three sub-tables.
    capacity = max(1, height - _CHROME_ROWS)
    if depth is not None and depth > 0:
        capacity = min(capacity, depth)

    header = _build_header(snapshot, symbol, stats, best_bid, best_ask)
    bid_tbl = _side_table("BIDS", bids, _UP, capacity, is_bid=True)
    ask_tbl = _side_table("ASKS", asks, _DOWN, capacity, is_bid=False)
    trades_tbl = _trades_table(snapshot.get("recent_trades", []) or [], capacity)

    # A fixed 3-column grid (rather than Columns) guarantees the three panels
    # stay side by side at equal width/height even on narrow terminals, where
    # Columns would otherwise reflow the last panel onto a new line.
    body = Table.grid(expand=True, padding=(0, 1))
    body.add_column(ratio=1)
    body.add_column(ratio=1)
    body.add_column(ratio=1)
    body.add_row(bid_tbl, ask_tbl, trades_tbl)

    reference = stats.reference
    frame_style = _direction_style(stats.close, reference)
    if frame_style == _FLAT:
        frame_style = "blue"

    title = Text.assemble(
        (" EduMatcher ", "bold white on blue"),
        ("  "),
        (symbol, "bold white"),
        ("  Order Book ", "grey70"),
    )
    subtitle = Text(
        "levels fit screen  •  bids/asks/trades equal height  •  Ctrl-C to quit",
        style="grey58",
    )

    return Panel(
        Group(header, Rule(style="grey35"), body),
        title=title,
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
        border_style=frame_style,
        box=box.ROUNDED,
        height=height,
        padding=(0, 1),
    )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-viewer with log level %s", logging.getLevelName(log_level))
    symbol = args.symbol.upper()

    debug_counts: defaultdict[str, int] = defaultdict(int)
    debug_last_summary = time.monotonic()

    def _dbg_count(key: str, amount: int = 1) -> None:
        if not log.isEnabledFor(logging.DEBUG):
            return
        debug_counts[key] += amount
        _flush_debug_summary()

    def _flush_debug_summary(force: bool = False) -> None:
        nonlocal debug_last_summary
        if not log.isEnabledFor(logging.DEBUG):
            return
        now = time.monotonic()
        if not force and now - debug_last_summary < _DEBUG_SUMMARY_INTERVAL_SEC:
            return
        if not debug_counts:
            debug_last_summary = now
            return
        summary = ", ".join(
            f"{key}={value}" for key, value in sorted(debug_counts.items())
        )
        log.debug("viewer flow summary: %s", summary)
        debug_counts.clear()
        debug_last_summary = now

    sub = make_subscriber(ENGINE_PUB_ADDR, f"book.{symbol}")

    # Request the current snapshot so reconnects show the live book
    # immediately. Done in a daemon thread so we don't block the main loop.
    threading.Thread(
        target=lambda: request_snapshot_with_retry(symbol), daemon=True
    ).start()

    latest_snapshot: dict[str, Any] = {"bids": [], "asks": [], "recent_trades": []}
    stats = _load_stats_from_db(Path(str(args.db)), symbol)
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    # Single-threaded main loop: zmq.Poller.poll() is interrupted by SIGINT
    # (zmq_poll returns EINTR → pyzmq calls PyErr_CheckSignals() → KeyboardInterrupt).
    # Live uses auto_refresh=False so it spawns no background threads of its own.
    #
    # screen=True puts rich on the alternate screen buffer and repaints the
    # whole frame at the current terminal size on every refresh — so a resize
    # never leaves stale rows from a previous (larger) render behind.
    try:
        with Live(
            console=console, auto_refresh=False, screen=True, transient=True
        ) as live:
            while True:
                try:
                    socks = dict(poller.poll(timeout=int(1000 / _REFRESH_HZ)))
                except zmq.ZMQError as exc:
                    if exc.errno != errno.EINTR:
                        raise
                    _dbg_count("poll_eintr")
                    break  # EINTR: signal interrupted poll — exit cleanly
                if sub in socks:
                    frames = sub.recv_multipart()
                    _, payload = decode(frames)
                    latest_snapshot = payload
                    stats.update(payload)
                    _dbg_count("book_snapshots")
                live.update(
                    _build_display(latest_snapshot, symbol, args.depth, stats=stats)
                )
                live.refresh()
                _dbg_count("renders")
                _flush_debug_summary()
    except KeyboardInterrupt:
        pass
    finally:
        sub.close()
        _flush_debug_summary(force=True)
        log.info("viewer shutdown complete for symbol=%s", symbol)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher order book viewer")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-viewer")
    parser.add_argument(
        "--symbol",
        "-s",
        required=True,
        metavar="SYMBOL",
        help="Symbol to watch, e.g. AAPL",
    )
    parser.add_argument(
        "--depth",
        "-d",
        type=int,
        default=None,
        help="Max price levels to display (default: fit to terminal height)",
    )
    parser.add_argument(
        "--db",
        default=str(STATS_DB_FILE),
        metavar="PATH",
        help=f"Statistics SQLite DB for seed OHLC (default: {STATS_DB_FILE})",
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
