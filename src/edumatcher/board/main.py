"""
Market Board — multi-symbol aggregated display for large screens.

Usage:
  poetry run pm-board [--rows 8] [--interval 10]

Subscribes to all book.* and trade.executed topics and displays a paged table
of all active symbols with exchange-style coloring.

Controls:
  ENTER — advance to next page immediately
  Ctrl-C — exit

Each page shows up to --rows symbols (default 8). Pages auto-rotate every
--interval seconds (default 10).
"""

from __future__ import annotations

import argparse
import select
import sys
import time
from datetime import datetime
from typing import Any

import errno

import zmq
from rich.console import Console
from rich.live import Live
from rich.table import Table

from edumatcher.config import ENGINE_PUB_ADDR
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

console = Console()


def _colour_change(pct: float) -> str:
    """Return rich colour tag for a percentage change."""
    if pct > 0:
        return "bright_green"
    elif pct < 0:
        return "bright_red"
    return "white"


def _fmt_price(price: float | None) -> str:
    if price is None:
        return "—"
    return f"{price:.4f}"


def _build_table(
    symbols: dict[str, dict[str, Any]],
    page: int,
    rows_per_page: int,
    interval: int,
) -> Table:
    """Build the display table for the current page."""
    sorted_syms = sorted(symbols.keys())
    total_pages = max(1, (len(sorted_syms) + rows_per_page - 1) // rows_per_page)
    page = page % total_pages if total_pages > 0 else 0
    start = page * rows_per_page
    page_syms = sorted_syms[start : start + rows_per_page]

    now = datetime.now().strftime("%H:%M:%S")
    title = (
        f"[bold white on dark_blue]  MARKET BOARD  "
        f"Page {page + 1}/{total_pages}  |  "
        f"{len(sorted_syms)} symbols  |  "
        f"Auto-rotate: {interval}s  |  "
        f"{now}  [/bold white on dark_blue]"
    )

    t = Table(title=title, show_header=True, header_style="bold", expand=True)
    t.add_column("Symbol", style="bold white", min_width=8)
    t.add_column("Last", justify="right", min_width=10)
    t.add_column("Chg %", justify="right", min_width=8)
    t.add_column("Bid", justify="right", min_width=10, style="green")
    t.add_column("Ask", justify="right", min_width=10, style="red")
    t.add_column("Spread", justify="right", min_width=8)
    t.add_column("Last Buy", justify="right", min_width=10)
    t.add_column("Last Sell", justify="right", min_width=10)
    t.add_column("Vol", justify="right", min_width=8)
    t.add_column("Updated", justify="right", min_width=10, style="dim")

    for sym in page_syms:
        data = symbols[sym]
        last = data.get("last_price")
        first_price = data.get("first_price")
        last_buy = data.get("last_buy_price")
        last_sell = data.get("last_sell_price")
        best_bid = data.get("best_bid")
        best_ask = data.get("best_ask")
        volume = data.get("volume", 0)
        updated = data.get("updated")

        # Percentage change from first trade
        pct = 0.0
        if last is not None and first_price is not None and first_price > 0:
            pct = ((last - first_price) / first_price) * 100.0

        colour = _colour_change(pct)
        pct_str = f"[{colour}]{pct:+.2f}%[/{colour}]"
        last_str = f"[{colour}]{_fmt_price(last)}[/{colour}]" if last else "—"

        # Spread
        spread = ""
        if best_bid is not None and best_ask is not None:
            s = best_ask - best_bid
            spread = f"{s:.4f}"

        # Last buy/sell coloring
        lb_str = f"[green]{_fmt_price(last_buy)}[/green]" if last_buy else "—"
        ls_str = f"[red]{_fmt_price(last_sell)}[/red]" if last_sell else "—"

        updated_str = updated.strftime("%H:%M:%S") if updated else "—"

        t.add_row(
            sym,
            last_str,
            pct_str,
            _fmt_price(best_bid),
            _fmt_price(best_ask),
            spread,
            lb_str,
            ls_str,
            str(volume),
            updated_str,
        )

    # Pad with empty rows if page is not full
    for _ in range(rows_per_page - len(page_syms)):
        t.add_row("", "", "", "", "", "", "", "", "", "")

    return t


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher multi-symbol board")
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
    args = parser.parse_args()
    rows_per_page = max(1, args.rows)
    interval = max(1, args.interval)

    # Subscribe to all book snapshots and trade feed
    sub = make_subscriber(ENGINE_PUB_ADDR, "book.", "trade.executed")

    # symbol → aggregated data
    symbols: dict[str, dict[str, Any]] = {}
    page = 0
    last_page_change = time.monotonic()

    # Non-blocking stdin for ENTER detection
    def _check_enter() -> bool:
        """Return True if ENTER was pressed (non-blocking)."""
        if sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if ready:
                sys.stdin.readline()
                return True
        return False

    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    try:
        with Live(console=console, auto_refresh=False, screen=True) as live:
            while True:
                # Poll ZMQ for incoming messages (100ms tick)
                try:
                    socks = dict(poller.poll(timeout=100))
                except zmq.ZMQError as exc:
                    if exc.errno != errno.EINTR:
                        raise
                    break

                if sub in socks:
                    frames = sub.recv_multipart()
                    topic_str, payload = decode(frames)

                    if topic_str.startswith("book."):
                        sym = topic_str[5:]  # strip "book."
                        entry = symbols.setdefault(
                            sym,
                            {
                                "first_price": None,
                                "volume": 0,
                            },
                        )
                        entry["last_price"] = payload.get("last_price")
                        entry["last_buy_price"] = payload.get("last_buy_price")
                        entry["last_sell_price"] = payload.get("last_sell_price")
                        entry["updated"] = datetime.now()

                        # Best bid/ask from top of book
                        bids = payload.get("bids", [])
                        asks = payload.get("asks", [])
                        entry["best_bid"] = bids[0].get("price") if bids else None
                        entry["best_ask"] = asks[0].get("price") if asks else None

                        # Track first price for % change
                        if (
                            entry["first_price"] is None
                            and entry["last_price"] is not None
                        ):
                            entry["first_price"] = entry["last_price"]

                    elif topic_str == "trade.executed":
                        trade_sym: str | None = payload.get("symbol")
                        if trade_sym:
                            entry = symbols.setdefault(
                                trade_sym,
                                {
                                    "first_price": None,
                                    "volume": 0,
                                },
                            )
                            trade_price = payload.get("price")
                            trade_qty = payload.get("quantity", 0)
                            entry["last_price"] = trade_price
                            entry["volume"] = entry.get("volume", 0) + trade_qty
                            entry["updated"] = datetime.now()
                            if entry["first_price"] is None and trade_price is not None:
                                entry["first_price"] = trade_price

                # Check for page advance
                now = time.monotonic()
                advance = False
                if now - last_page_change >= interval:
                    advance = True
                if _check_enter():
                    advance = True
                if advance:
                    page += 1
                    last_page_change = now

                # Render
                live.update(_build_table(symbols, page, rows_per_page, interval))
                live.refresh()

    except KeyboardInterrupt:
        pass
    finally:
        sub.close()


if __name__ == "__main__":
    main()
