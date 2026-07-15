"""
Order Book Viewer — live terminal display for a single symbol.

Usage:
  poetry run pm-viewer --symbol AAPL [--depth 10]

Subscribes to book.<SYMBOL> and renders a refreshing rich table showing:
  • Top-N bid/ask price levels (price, qty, #orders)
  • Last trade price and qty
  • 5 most recent trades

Iceberg orders show only displayed_qty — the hidden size is intentionally
invisible, demonstrating the privacy feature of iceberg orders.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import errno
import logging
import threading
import time
from datetime import datetime
from typing import Any
import sys

import zmq
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_PUB_ADDR, ORDERBOOK_DEPTH
from edumatcher.messaging.bus import make_subscriber, make_pusher
from edumatcher.models.message import decode, make_book_snapshot_request_msg

console = Console()
log = logging.getLogger(__name__)

_REFRESH_HZ = 2  # rich Live refresh rate
_MAX_RECENT_TRADES = 5
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


def _build_display(snapshot: dict[str, Any], symbol: str, depth: int) -> Panel:
    bids = snapshot.get("bids", [])[:depth]
    asks = snapshot.get("asks", [])[:depth]
    last_price = snapshot.get("last_price")
    last_qty = snapshot.get("last_qty")
    last_buy = snapshot.get("last_buy_price")
    last_sell = snapshot.get("last_sell_price")
    recent = snapshot.get("recent_trades", [])

    # --- Bids table ---
    bid_tbl = Table(
        title="[bold green]BIDS[/bold green]",
        show_header=True,
        header_style="bold green",
    )
    bid_tbl.add_column("Price", justify="right", style="green", min_width=10)
    bid_tbl.add_column("Qty", justify="right", min_width=8)
    bid_tbl.add_column("#Orders", justify="right", min_width=6)
    for lvl in bids:
        bid_tbl.add_row(f"{lvl['price']:.4f}", str(lvl["qty"]), str(lvl["count"]))

    # --- Asks table ---
    ask_tbl = Table(
        title="[bold red]ASKS[/bold red]", show_header=True, header_style="bold red"
    )
    ask_tbl.add_column("Price", justify="right", style="red", min_width=10)
    ask_tbl.add_column("Qty", justify="right", min_width=8)
    ask_tbl.add_column("#Orders", justify="right", min_width=6)
    for lvl in asks:
        ask_tbl.add_row(f"{lvl['price']:.4f}", str(lvl["qty"]), str(lvl["count"]))

    # --- Recent trades ---
    trades_tbl = Table(
        title="Recent Trades", show_header=True, header_style="bold cyan"
    )
    trades_tbl.add_column("Time", min_width=12)
    trades_tbl.add_column("Price", justify="right", min_width=10)
    trades_tbl.add_column("Qty", justify="right", min_width=8)
    for tr in reversed(recent[-_MAX_RECENT_TRADES:]):
        ts = datetime.fromtimestamp(tr["timestamp"]).strftime("%H:%M:%S.%f")[:-3]
        trades_tbl.add_row(ts, f"{tr['price']:.4f}", str(tr["quantity"]))

    # --- Header line ---
    lp_str = f"{last_price:.4f}" if last_price is not None else "—"
    lq_str = str(last_qty) if last_qty is not None else "—"
    lb_str = f"{last_buy:.4f}" if last_buy is not None else "n/a"
    ls_str = f"{last_sell:.4f}" if last_sell is not None else "n/a"
    header = Text(
        f"  {symbol}   Last: {lp_str}  (qty {lq_str})"
        f"   Last Buy: {lb_str}   Last Sell: {ls_str}"
        f"   Updated: {datetime.now().strftime('%H:%M:%S')}  ",
        style="bold white on dark_blue",
    )

    return Panel(
        Columns([bid_tbl, ask_tbl, trades_tbl], equal=False, expand=False),
        title=header,
        border_style="blue",
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

    # Request the current snapshot so reconnects show the live book immediately.
    # Done in a daemon thread so we don't block the main loop.
    def _request_snapshot() -> None:
        time.sleep(0.15)
        push = make_pusher(ENGINE_PULL_ADDR)
        try:
            push.send_multipart(make_book_snapshot_request_msg(symbol))
        finally:
            push.close()

    threading.Thread(target=_request_snapshot, daemon=True).start()

    latest_snapshot: dict[str, Any] = {"bids": [], "asks": [], "recent_trades": []}
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    # Single-threaded main loop: zmq.Poller.poll() is interrupted by SIGINT
    # (zmq_poll returns EINTR → pyzmq calls PyErr_CheckSignals() → KeyboardInterrupt).
    # Live uses auto_refresh=False so it spawns no background threads of its own.
    try:
        with Live(console=console, auto_refresh=False, screen=False) as live:
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
                    _dbg_count("book_snapshots")
                live.update(_build_display(latest_snapshot, symbol, args.depth))
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
        default=ORDERBOOK_DEPTH,
        help=f"Price levels to display (default {ORDERBOOK_DEPTH})",
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
    if args.log_level:
        level_name = str(args.log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif args.verbose >= 2:
        level = logging.DEBUG
    elif args.verbose == 1:
        level = logging.INFO
    elif args.quiet:
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
