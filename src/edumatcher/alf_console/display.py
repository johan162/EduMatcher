"""Console display helpers and the Rich console instance for the gateway."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table


class _SysStdoutProxy:
    """
    Write-through proxy that resolves sys.stdout at *call time*, not at
    construction time.  This is necessary because prompt_toolkit's
    patch_stdout=True replaces sys.stdout with a StdoutProxy during each
    session.prompt() call.  Rich's Console stores the file reference at
    construction; without this proxy it would bypass the patch and its output
    would overwrite (and be overwritten by) prompt_toolkit's prompt redraws,
    making background responses like SYMBOLS appear empty.
    """

    def write(self, s: str) -> int:
        return sys.stdout.write(s)

    def flush(self) -> None:
        sys.stdout.flush()

    def fileno(self) -> int:
        return sys.stdout.fileno()

    def isatty(self) -> bool:
        return getattr(sys.stdout, "isatty", lambda: False)()

    @property
    def encoding(self) -> str:
        return getattr(sys.stdout, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(sys.stdout, "errors", "replace")


# force_terminal=True so rich always emits ANSI even through the proxy.
console = Console(file=_SysStdoutProxy(), force_terminal=True)  # type: ignore[arg-type]

PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold ansigreen",
    }
)

HELP_TEXT = """
[bold]FIX-like command reference[/bold]

  NEW|SYM=<sym>|SIDE=BUY|SELL|TYPE=<type>|QTY=<n>[|PRICE=<p>][|STOP=<p>][|TRAIL=<offset>][|TIF=DAY|GTC][|VISIBLE=<n>][|SMP=<action>]

  AMEND|ID=<order-id>[|PRICE=<new-price>][|QTY=<new-qty>]
    • Amend a resting LIMIT or ICEBERG order in-place (no cancel+resubmit needed)
    • At least one of PRICE= or QTY= must be specified
    • Quantity decrease only (same price): priority is PRESERVED
    • Price change or quantity increase: priority is LOST (back of queue)
    • New QTY must exceed already-filled quantity

  Types:
    MARKET        — execute immediately, discard unfilled remainder
    LIMIT         — rest at PRICE= until filled or cancelled
    IOC           — Immediate-Or-Cancel: fill what you can at PRICE=, cancel the rest
    FOK           — Fill-Or-Kill: fill entire QTY= at PRICE= or cancel whole order
    STOP          — trigger as MARKET when price crosses STOP=
    STOP_LIMIT    — trigger as LIMIT at PRICE= when price crosses STOP=
    ICEBERG       — show only VISIBLE= qty; hidden remainder auto-replenishes
    TRAILING_STOP — stop that trails market by TRAIL= offset; provide initial STOP= or
                    omit for automatic initialisation from last trade price

  TIF  : DAY (default)  GTC
  SMP  : NONE (default)  CANCEL_AGGRESSOR  CANCEL_RESTING  CANCEL_BOTH

  [bold]OCO orders (One-Cancels-Other — two linked orders):[/bold]
  NEW|TYPE=OCO|OCO_ID=<label>|SYM=<sym>|QTY=<n>|TIF=DAY|GTC|LEG1_SIDE=BUY|SELL|LEG1_TYPE=<type>[|LEG1_PRICE=<p>][|LEG1_STOP=<p>]|LEG2_SIDE=...
    • Both legs on the same symbol, same quantity
    • When one leg fills or is cancelled, the other is auto-cancelled
    • Classic use: take-profit limit + stop-loss (sell side)
  CANCEL|OCO_ID=<label>   — cancel an OCO pair and both its legs

  [bold]Combo orders (multi-leg):[/bold]
  NEW|TYPE=COMBO|COMBO_ID=<label>|COMBO_TYPE=AON|TIF=DAY|GTC|LEG_COUNT=<n>|LEG0.SYM=<sym>|LEG0.SIDE=BUY|LEG0.QTY=<n>|LEG0.PRICE=<p>|LEG1.SYM=...
    • 2–10 legs, each on a different symbol
    • Child orders are posted to books and fill independently
    • If any leg is cancelled/expires, all remaining legs are cascade-cancelled

  CANCEL|ID=<order-id>
  CANCEL|COMBO_ID=<combo-label>   — cancel a combo and all its legs
    QUOTE|SYM=<sym>|BID=<p>|ASK=<p>|BID_QTY=<n>|ASK_QTY=<n>[|TIF=DAY|GTC][|QUOTE_ID=<label>]
    QUOTE_CANCEL|SYM=<sym>          — cancel active quote for a symbol
    QBOOT[|SYM=<sym>]               — request active quote bootstrap state from engine
        QLEGS[|SYM=<sym>][|SHOW=ACTIVE|RECENT|ALL]  — show MM quote legs and fill flags
    KILL[|SYM=<sym>]                — kill-switch cancel for this gateway
    STATUS      — show gateway/session summary (identity, symbols, order counts)
    ORDERS      — inspect this gateway's order table with IDs, quantities, and status
  POS         — show current positions with P&L
  SYMBOLS     — list all active instruments in the engine
    INDEX       — show current cached index level
    INDEX|HISTORY|INDEX=<id>[|FROM=YYYY-MM-DD|TO=YYYY-MM-DD] — query index history
  HELP        — this message
  EXIT / QUIT — disconnect
"""


def is_active_leg_status(status: str) -> bool:
    return status in {"NEW", "PARTIAL", "PENDING"}


def print_quote_legs(
    gateway_id: str,
    quote_leg_cache: dict[str, dict[str, Any]],
    symbol: str | None,
    show: str,
) -> None:
    rows = list(quote_leg_cache.values())
    if symbol:
        rows = [r for r in rows if str(r.get("symbol", "")).upper() == symbol]

    if show == "ACTIVE":
        rows = [
            r
            for r in rows
            if is_active_leg_status(str(r.get("status", "")))
            or int(r.get("remaining", 0)) > 0
        ]
    elif show == "RECENT":
        rows = [
            r
            for r in rows
            if not is_active_leg_status(str(r.get("status", "")))
            and int(r.get("remaining", 0)) <= 0
        ]

    if not rows:
        console.print("[dim]No quote legs match this filter.[/dim]")
        return

    rows.sort(key=lambda r: str(r.get("last_event_time", "")), reverse=True)

    title = f"Quote legs — {gateway_id}  (show={show}"
    if symbol:
        title += f", sym={symbol}"
    title += ")"
    t = Table(title=title, show_lines=True)
    t.add_column("Symbol", style="bold")
    t.add_column("Quote", style="cyan")
    t.add_column("Leg", style="magenta")
    t.add_column("Order", style="dim", width=10)
    t.add_column("Qty", justify="right")
    t.add_column("Rem", justify="right")
    t.add_column("Filled", justify="right")
    t.add_column("Filled?", justify="center")
    t.add_column("Leg status", style="bold")
    t.add_column("Quote status", style="dim")
    t.add_column("Time", style="dim")

    status_colour = {
        "NEW": "green",
        "PARTIAL": "yellow",
        "FILLED": "bright_green",
        "CANCELLED": "red",
        "EXPIRED": "dim",
        "PENDING": "dim",
    }

    for row in rows:
        leg_status = str(row.get("status", "?"))
        colour = status_colour.get(leg_status, "white")
        filled_qty = int(row.get("filled", 0))
        fill_flag = "YES" if filled_qty > 0 else "NO"
        t.add_row(
            str(row.get("symbol", "?")),
            str(row.get("quote_id", "?")),
            str(row.get("leg_side", "?")),
            str(row.get("order_id", "?"))[:8],
            str(row.get("qty", "?")),
            str(row.get("remaining", "?")),
            str(filled_qty),
            fill_flag,
            f"[{colour}]{leg_status}[/{colour}]",
            str(row.get("quote_status", "")) or "—",
            str(row.get("last_event_time", "")),
        )
    console.print(t)


def print_quote_bootstrap(gateway_id: str, quotes: list[dict[str, Any]]) -> None:
    if not quotes:
        console.print("[dim]No active quote bootstrap entries returned.[/dim]")
        return

    t = Table(
        title=f"Quote bootstrap - {gateway_id}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("Symbol", style="bold")
    t.add_column("Quote", style="cyan")
    t.add_column("State", style="white")
    t.add_column("Bid", style="green")
    t.add_column("Ask", style="red")
    t.add_column("BidRem", justify="right")
    t.add_column("AskRem", justify="right")

    for q in quotes:
        bid_px = q.get("bid_price")
        ask_px = q.get("ask_price")
        bid_txt = f"{bid_px:.2f}" if isinstance(bid_px, (int, float)) else "-"
        ask_txt = f"{ask_px:.2f}" if isinstance(ask_px, (int, float)) else "-"
        t.add_row(
            str(q.get("symbol", "?")),
            str(q.get("quote_id", "?")),
            str(q.get("state", "?")),
            bid_txt,
            ask_txt,
            str(q.get("bid_remaining_qty", 0)),
            str(q.get("ask_remaining_qty", 0)),
        )

    console.print(t)


def print_symbols_table(
    symbols: list[str], symbol_meta: dict[str, dict[str, Any]]
) -> None:
    t = Table(
        title="Active Instruments",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("#", style="dim", width=4)
    t.add_column("Symbol", style="bold", min_width=10)
    t.add_column("Tick", justify="right")
    t.add_column("MM Enforced", justify="center")
    t.add_column("Max Spread", justify="right")
    t.add_column("Min Qty", justify="right")

    for i, sym in enumerate(symbols, 1):
        meta = symbol_meta.get(sym, {})
        tick_size = meta.get("tick_size")
        enforce_mm = meta.get("enforce_mm_obligation")
        mm_max_spread_ticks = meta.get("mm_max_spread_ticks")
        mm_min_qty = meta.get("mm_min_qty")

        tick_text = str(tick_size) if tick_size is not None else "—"
        if isinstance(enforce_mm, bool):
            enforced_text = "YES" if enforce_mm else "NO"
        else:
            enforced_text = "—"

        t.add_row(
            str(i),
            sym,
            tick_text,
            enforced_text,
            str(mm_max_spread_ticks) if mm_max_spread_ticks is not None else "—",
            str(mm_min_qty) if mm_min_qty is not None else "—",
        )

    console.print(t)


def print_positions(
    positions: dict[str, dict[str, Any]],
    last_prices: dict[str, float],
) -> None:
    active = {s: p for s, p in positions.items() if p["net_qty"] != 0}
    flat = {
        s: p
        for s, p in positions.items()
        if p["net_qty"] == 0 and p["realized_pnl"] != 0.0
    }

    if not active and not flat:
        console.print("[dim]No positions.[/dim]")
        return

    t = Table(title="Positions", show_header=True, header_style="bold magenta")
    t.add_column("Symbol", style="bold", min_width=8)
    t.add_column("Net Qty", justify="right", min_width=8)
    t.add_column("Avg Cost", justify="right", min_width=10)
    t.add_column("Last Px", justify="right", min_width=10)
    t.add_column("Unreal P&L", justify="right", min_width=12)
    t.add_column("Real P&L", justify="right", min_width=12)

    for symbol in sorted(active.keys()):
        pos = active[symbol]
        net = pos["net_qty"]
        avg = pos["avg_cost"]
        last = last_prices.get(symbol)
        unreal = ""
        if last is not None and avg > 0:
            upnl = (last - avg) * net
            colour = "green" if upnl >= 0 else "red"
            unreal = f"[{colour}]{upnl:+.2f}[/{colour}]"
        last_str = f"{last:.2f}" if last is not None else "—"
        rpnl = pos["realized_pnl"]
        rpnl_colour = "green" if rpnl >= 0 else "red"

        t.add_row(
            symbol,
            f"{net:+d}",
            f"{avg:.2f}",
            last_str,
            unreal or "—",
            f"[{rpnl_colour}]{rpnl:+.2f}[/{rpnl_colour}]",
        )

    for symbol in sorted(flat.keys()):
        pos = flat[symbol]
        rpnl = pos["realized_pnl"]
        rpnl_colour = "green" if rpnl >= 0 else "red"
        t.add_row(
            f"[dim]{symbol}[/dim]",
            "0",
            "—",
            "—",
            "—",
            f"[{rpnl_colour}]{rpnl:+.2f}[/{rpnl_colour}]",
        )

    console.print(t)


def print_status(
    gateway_id: str,
    authenticated: bool,
    known_symbols: list[str],
    order_cache: dict[str, dict[str, Any]],
    quote_leg_cache: dict[str, dict[str, Any]],
    positions: dict[str, dict[str, Any]],
) -> None:
    status_counts: dict[str, int] = {}
    for order in order_cache.values():
        status = str(order.get("status", "UNKNOWN"))
        status_counts[status] = status_counts.get(status, 0) + 1

    active_orders = sum(
        count
        for status, count in status_counts.items()
        if status in {"NEW", "PARTIAL", "PENDING"}
    )
    active_quote_legs = sum(
        1
        for leg in quote_leg_cache.values()
        if is_active_leg_status(str(leg.get("status", "")))
    )

    table = Table(title=f"Gateway status — {gateway_id}", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Gateway ID", gateway_id)
    table.add_row("Authenticated", "yes" if authenticated else "no")
    table.add_row(
        "Known symbols",
        ", ".join(known_symbols) if known_symbols else "—",
    )
    table.add_row("Cached orders", str(len(order_cache)))
    table.add_row("Active/resting orders", str(active_orders))
    table.add_row("Cached quote legs", str(len(quote_leg_cache)))
    table.add_row("Active quote legs", str(active_quote_legs))
    table.add_row(
        "Position symbols",
        ", ".join(sorted(positions)) if positions else "—",
    )
    if status_counts:
        counts = ", ".join(
            f"{status}={count}" for status, count in sorted(status_counts.items())
        )
    else:
        counts = "—"
    table.add_row("Order status counts", counts)
    console.print(table)
    console.print(
        "[dim]Use ORDERS for detailed order inspection and POS for P&L.[/dim]"
    )


def print_current_index(last_index_update: dict[str, Any] | None) -> None:
    payload = last_index_update
    if not payload:
        console.print("[dim]No index data received yet. Is pm-index running?[/dim]")
        return

    ts_raw = payload.get("timestamp")
    if isinstance(ts_raw, (int, float)):
        ts = datetime.fromtimestamp(float(ts_raw)).strftime("%H:%M:%S.%f")[:-3]
    else:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

    index_id = str(payload.get("index_id", "INDEX"))
    level = float(payload.get("level", 0.0))
    session_state = str(payload.get("session_state", "?"))

    change_txt = ""
    day_open = payload.get("day_open")
    if isinstance(day_open, (int, float)) and day_open > 0.0:
        delta = level - float(day_open)
        pct = (delta / float(day_open)) * 100
        colour = "green" if delta >= 0 else "red"
        change_txt = f" [{colour}]{delta:+.2f} {pct:+.2f}%[/{colour}]"

    ohlc_txt = ""
    day_high = payload.get("day_high")
    day_low = payload.get("day_low")
    if (
        isinstance(day_open, (int, float))
        and isinstance(day_high, (int, float))
        and isinstance(day_low, (int, float))
    ):
        ohlc_txt = (
            f" [dim]O={float(day_open):.2f} H={float(day_high):.2f} "
            f"L={float(day_low):.2f}[/dim]"
        )

    console.print(
        f"[{ts}] [bold cyan]{index_id}[/bold cyan] [bold]{level:.2f}[/bold]"
        f"{change_txt}{ohlc_txt} [dim]{session_state}[/dim]"
    )


def print_index_history(records: list[dict[str, Any]]) -> None:
    if not records:
        console.print("[dim]No index history records returned.[/dim]")
        return

    table = Table(title="Index history", show_header=True, header_style="bold magenta")
    table.add_column("Type", style="bold")
    table.add_column("Time", style="dim")
    table.add_column("Level", justify="right")
    table.add_column("Session", style="dim")

    for rec in records:
        rec_type = str(rec.get("type", "?"))
        ts = rec.get("timestamp")
        if isinstance(ts, (int, float)):
            ts_txt = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_txt = "?"
        level = rec.get("level")
        level_txt = f"{float(level):.2f}" if isinstance(level, (int, float)) else "-"
        session_state = str(rec.get("session_state", "-"))
        table.add_row(rec_type, ts_txt, level_txt, session_state)

    console.print(table)


def print_orders(gateway_id: str, order_cache: dict[str, dict[str, Any]]) -> None:
    if not order_cache:
        console.print("[dim]No outstanding orders for this gateway.[/dim]")
        return
    t = Table(title=f"Orders — {gateway_id}", show_lines=True)
    t.add_column("ID", style="dim", width=10)
    t.add_column("Symbol", style="bold")
    t.add_column("Side", style="cyan")
    t.add_column("Type", style="magenta")
    t.add_column("TIF", style="dim")
    t.add_column("Qty", justify="right")
    t.add_column("Rem", justify="right")
    t.add_column("Price", justify="right")
    t.add_column("Status", style="bold")
    t.add_column("Time", style="dim")

    status_colour = {
        "NEW": "green",
        "PARTIAL": "yellow",
        "FILLED": "bright_green",
        "CANCELLED": "red",
        "REJECTED": "red",
        "EXPIRED": "dim",
        "PENDING": "dim",
    }

    for o in sorted(order_cache.values(), key=lambda x: x["time"], reverse=True):
        st = o["status"]
        colour = status_colour.get(st, "white")
        t.add_row(
            o["id"][:8],
            o["symbol"],
            o["side"],
            o["type"],
            o["tif"],
            str(o["qty"]),
            str(o["remaining"]),
            str(o["price"]) if o["price"] else "—",
            f"[{colour}]{st}[/{colour}]",
            o["time"],
        )
    console.print(t)
