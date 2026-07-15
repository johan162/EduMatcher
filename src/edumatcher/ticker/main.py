"""
Ticker Process — scrolling terminal market data display.

Usage:
  poetry run pm-ticker [--db data/stats.db] [--interval 30] [--db-interval 900]

Subscribes to:
  book.*  — live last price, best bid/ask per symbol

Queries:
  daily_stats table in the statistics SQLite DB every --db-interval seconds
  (default 900 = 15 minutes) for OHLCV, VWAP, and trade count.

Output:
  One rich colour line is printed every --interval seconds (default 30):

    09:15:00  ◆  MSFT  415.00  +0.48%  H:418.00  L:412.00  Vol:52,400 (8T)  414.50/415.50  ◆  AAPL …

  Lines scroll up naturally as new ones appear — giving a classic terminal
  ticker-tape effect.  Each line is a complete point-in-time snapshot.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import errno
import logging
import signal
import sqlite3
import sys
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import zmq
from rich.console import Console
from rich.text import Text

from edumatcher.config import ENGINE_PUB_ADDR, STATS_DB_FILE
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DISPLAY_INTERVAL_DEFAULT = 30  # seconds between printed ticker lines
_DB_REFRESH_DEFAULT = 900  # seconds between daily_stats re-queries (15 min)
_MAIN_LOOP_SLEEP_SEC = 0.1  # main-loop polling granularity
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0

console = Console(highlight=False)
log = logging.getLogger(__name__)


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
# Line builder
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


def _build_line(
    symbols: list[str],
    daily: dict[str, dict[str, Any]],
    live: dict[str, dict[str, Any]],
) -> Text:
    """Compose one rich Text ticker line for all symbols."""
    line = Text()
    ts = datetime.now().strftime("%H:%M:%S")
    line.append(f"{ts}  ", style="dim")
    for i, sym in enumerate(symbols):
        if i > 0:
            line.append("  ◆  ", style="dim")
        line.append_text(_format_symbol(sym, daily.get(sym, {}), live.get(sym, {})))
    return line


# ---------------------------------------------------------------------------
# Ticker process
# ---------------------------------------------------------------------------


class TickerProcess:
    def __init__(
        self,
        db_path: Path,
        display_interval: float,
        db_interval: float,
    ) -> None:
        self._db_path = db_path
        self._display_interval = display_interval
        self._db_interval = db_interval
        self._running = True
        self._lock = threading.Lock()

        # Live data populated from ZMQ book updates
        self._live: dict[str, dict[str, Any]] = {}
        # Daily OHLCV from SQLite
        self._daily: dict[str, dict[str, Any]] = {}
        # Stable sorted list of known symbols
        self._symbols: list[str] = []

        self._last_db_refresh = 0.0
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        self.sub = make_subscriber(ENGINE_PUB_ADDR, "book.")

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
                today = date.today().isoformat()
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
            console.print(f"[TICKER] DB read error: {exc}", style="dim red")

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

            if topic.startswith("book."):
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
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())
        log.info(
            "starting ticker runtime db=%s interval=%s db_interval=%s",
            self._db_path,
            self._display_interval,
            self._db_interval,
        )

        t = threading.Thread(target=self._receive, daemon=True)
        t.start()
        try:
            console.print(
                "[bold cyan]◆ EduMatcher Ticker[/bold cyan]  —  "
                f"display every [bold]{self._display_interval}s[/bold], "
                f"DB refresh every [bold]{self._db_interval}s[/bold]  "
                "(Ctrl-C to stop)",
            )

            # Initial DB load — show data immediately if available
            self._refresh_db()
            self._last_db_refresh = time.monotonic()

            # Print first line right away (set last_display far enough in the past)
            last_display = time.monotonic() - self._display_interval

            while self._running:
                now = time.monotonic()

                # Periodic DB refresh
                if now - self._last_db_refresh >= self._db_interval:
                    self._refresh_db()
                    self._last_db_refresh = now

                # Print ticker line
                if now - last_display >= self._display_interval:
                    with self._lock:
                        syms = list(self._symbols)
                        daily = dict(self._daily)
                        live = dict(self._live)
                    if syms:
                        console.print(_build_line(syms, daily, live))
                        self._dbg_count("lines_printed")
                    else:
                        console.print(
                            f"[dim]{datetime.now().strftime('%H:%M:%S')}  "
                            "waiting for market data…[/dim]"
                        )
                        self._dbg_count("lines_waiting")
                    last_display = now

                self._flush_debug_summary()
                time.sleep(_MAIN_LOOP_SLEEP_SEC)
        finally:
            self._running = False  # ensure _receive exits even on exception
            t.join(timeout=2.0)  # wait for thread before touching the socket
            self.sub.close()  # safe: _receive is no longer polling
            self._flush_debug_summary(force=True)
        console.print("\n[TICKER] Stopped.", style="dim")
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
    TickerProcess(
        db_path=Path(args.db),
        display_interval=args.interval,
        db_interval=args.db_interval,
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
        "--interval",
        type=float,
        default=_DISPLAY_INTERVAL_DEFAULT,
        metavar="SEC",
        help=f"Seconds between printed ticker lines (default: {_DISPLAY_INTERVAL_DEFAULT})",
    )
    parser.add_argument(
        "--db-interval",
        type=float,
        default=_DB_REFRESH_DEFAULT,
        metavar="SEC",
        help=f"Seconds between daily_stats DB re-queries (default: {_DB_REFRESH_DEFAULT})",
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

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        stream=sys.stdout,
    )
    return int(level)


if __name__ == "__main__":
    main()
