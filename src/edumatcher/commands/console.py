"""
pm-admin — interactive ADMIN operator console for EduMatcher.

Usage
-----
  poetry run pm-admin --id GW_ADMIN

The gateway ID must match an entry in ``engine_config.yaml``; the commands
that change the market need ``role: ADMIN`` (the engine checks the role per
command, not at connect). All commands are sent over the same ZeroMQ
PUSH/SUB transport used by ``ExchangeCommandClient``. Exit code 0 after
EXIT/EOF/Ctrl-C, 1 when no session was had or the engine was lost.

Commands
--------
  HALT                          — halt all symbols (manual circuit breaker)
  RESUME                        — resume all symbols halted by HALT
  HALT_SYM|SYM=<sym>            — halt one symbol
  RESUME_SYM|SYM=<sym>          — resume one symbol
  CANCEL_SYM|SYM=<sym>          — cancel every resting order on one symbol
  KILL|GW=<gw>[|SYM=<sym>]     — cancel all orders/quotes for a gateway
  KICK|GW=<gw>[|REASON=<text>] — forcefully disconnect a connected gateway
  QCANCEL|GW=<gw>|SYM=<sym>    — cancel the active quote for a gateway on one symbol
  REOPEN|SYM=<sym>[|PRICE=<px>][|DRY_RUN=1][|NOTE=<text>]
                                — force one symbol to uncross now, clearing any halt
  BOOK|SYM=<sym>                — print L1/L2 order-book snapshot
  ORDERS|GW=<gw>                — list resting orders for a gateway
  LEVEL|SYM=<sym>[|PRICE=<px>]  — show every resting order making up a symbol
                                   (or one price level), across all gateways
  SYMBOLS                       — list all instruments configured in the engine
  POSITION|GW=<gw>[|SYM=<sym>,..] — net position, avg cost, live bid/ask/spread/mid
  SESSION|STATE=<state>         — advance session phase
  SESSION_STATUS                — show the current session state
  SCHEDULE                      — show the session-transition schedule
  GATEWAYS                      — list gateways and their connection status
  VOLUME                        — show today's traded volume
  HELP                          — show this reference
  EXIT / QUIT                   — disconnect
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import threading
from typing import Any, Callable

import zmq
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from zmq.utils.monitor import recv_monitor_message

from edumatcher.config import ENGINE_PULL_ADDR
from edumatcher.cli_signals import logout_on_hangup
from edumatcher.config_artifact import exit_on_config_error
from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_pusher
from edumatcher.models.message import (
    INTERACTIVE_HEARTBEAT_INTERVAL_SEC,
    make_gateway_heartbeat_msg,
)

log = logging.getLogger(__name__)

_CLIENT_NAME = "pm-admin"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# ---------------------------------------------------------------------------
# prompt_toolkit / rich integration (same pattern as pm-alf-console)
# ---------------------------------------------------------------------------


class _SysStdoutProxy:
    """
    Write-through proxy that resolves sys.stdout at call time.

    prompt_toolkit's patch_stdout replaces sys.stdout with its own proxy
    during each session.prompt() call.  Without this indirection, rich's
    Console would bypass the patch and corrupt the terminal display.
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

# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------

_SESSION_STATES = [
    "PRE_OPEN",
    "OPENING_AUCTION",
    "CONTINUOUS",
    "CLOSING_AUCTION",
    "CLOSED",
]

_TOP_CMDS = [
    "HALT",
    "RESUME",
    "HALT_SYM",
    "RESUME_SYM",
    "CANCEL_SYM",
    "REOPEN",
    "KILL",
    "KICK",
    "QCANCEL",
    "BOOK",
    "ORDERS",
    "LEVEL",
    "SYMBOLS",
    "SESSION",
    "SESSION_STATUS",
    "SCHEDULE",
    "GATEWAYS",
    "VOLUME",
    "POSITION",
    "HELP",
    "EXIT",
    "QUIT",
]

# Fields expected after each multi-field command (in typical entry order)
_CMD_FIELDS: dict[str, list[str]] = {
    "HALT_SYM": ["SYM="],
    "RESUME_SYM": ["SYM="],
    "CANCEL_SYM": ["SYM="],
    "REOPEN": ["SYM=", "PRICE=", "DRY_RUN=", "NOTE="],
    "KILL": ["GW=", "SYM="],
    "KICK": ["GW=", "REASON="],
    "QCANCEL": ["GW=", "SYM="],
    "BOOK": ["SYM="],
    "ORDERS": ["GW="],
    "LEVEL": ["SYM=", "PRICE="],
    "SESSION": ["STATE="],
    "POSITION": ["GW=", "SYM="],
}

_HELP_TEXT = """
[bold]ADMIN operator console — command reference[/bold]

  HALT                          — halt all symbols (manual circuit breaker, ADMIN halt source)
  RESUME                        — resume all symbols previously halted by HALT

  HALT_SYM|SYM=<sym>            — halt trading on a single symbol only
  RESUME_SYM|SYM=<sym>          — resume a single symbol halted by HALT_SYM or a circuit breaker
  CANCEL_SYM|SYM=<sym>          — cancel ALL resting orders on <sym> across every gateway
  REOPEN|SYM=<sym>[|PRICE=<px>][|DRY_RUN=1][|NOTE=<text>]
                                — force <sym> to uncross now and clear any halt in one
                                   step. Omit PRICE to open at the computed equilibrium,
                                   or set it to assert an operator opening price for a
                                   failed auction. DRY_RUN=1 peeks the indicative print
                                   without changing any state. ADMIN only.
                                   e.g.  REOPEN|SYM=AAPL|DRY_RUN=1
                                         REOPEN|SYM=AAPL|PRICE=100.00|NOTE=manual open

  KILL|GW=<gw>[|SYM=<sym>]     — cancel all resting orders and the active quote for <gw>
                                   (add SYM= to scope to a single instrument)
  KICK|GW=<gw>[|REASON=<text>] — forcefully disconnect gateway <gw>
                                   (applies its disconnect_behaviour; the engine
                                   refuses an unknown, a disconnected or your
                                   own gateway. ADMIN only)
  QCANCEL|GW=<gw>|SYM=<sym>    — cancel the active two-sided quote for <gw> on <sym>
                                   without touching resting limit orders

  BOOK|SYM=<sym>                — print the current L1/L2 order-book snapshot for <sym>
  ORDERS|GW=<gw>                — list all resting orders for gateway <gw>,
                                   connected or not
  LEVEL|SYM=<sym>[|PRICE=<px>]  — show every resting order making up <sym>, across
                                   every gateway (add PRICE= to narrow to one level).
                                   Unlike BOOK, which only aggregates to {price, qty,
                                   count} per level, LEVEL lists each order — id,
                                   gateway, side, remaining qty — in price/time-priority
                                   order. ADMIN only.
                                   e.g.  LEVEL|SYM=AAPL
                                         LEVEL|SYM=AAPL|PRICE=189.50
  SYMBOLS                       — list all instruments configured in the engine

  POSITION|GW=<gw>[|SYM=<sym>,..] — show net position, avg cost, and live
                                   bid/ask/spread/mid per symbol for gateway <gw>
                                   (SYM= narrows to one or more comma-separated
                                   symbols). Works for any gateway, MM bots included.
                                   e.g.  POSITION|GW=MM_AAPL_01
                                         POSITION|GW=MM_AAPL_01|SYM=AAPL,MSFT

  SESSION|STATE=<state>         — request a session-phase transition
    Valid states: PRE_OPEN  OPENING_AUCTION  CONTINUOUS  CLOSING_AUCTION  CLOSED
  SESSION_STATUS                — show the current session state (read-only)
  SCHEDULE                      — show the automatic session-transition schedule
  GATEWAYS                      — list every configured gateway and whether it
                                   is connected
  VOLUME                        — show today's traded volume per symbol and in total

  HELP                          — this message
  EXIT / QUIT                   — disconnect and exit

[dim]Tab=complete  ↑↓=history  Ctrl-A/E=line start/end  Ctrl-C/D=exit[/dim]
"""


class _AdminCompleter(Completer):
    """Context-aware tab completer for the ADMIN console pipe syntax."""

    def __init__(self, known_symbols: list[str]) -> None:
        self.known_symbols = known_symbols

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Any:
        text = document.text_before_cursor
        parts = text.split("|")
        current = parts[-1]

        # ---- Top-level command (nothing before first |) ----
        if len(parts) == 1:
            word = current.upper()
            for cmd in _TOP_CMDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(current))
            return

        cmd = parts[0].upper()
        already_keys = {seg.split("=")[0].upper() for seg in parts[1:] if "=" in seg}

        # ---- Value completion after KEY= ----
        if "=" in current:
            key, partial_val = current.split("=", 1)
            key = key.upper()
            if key == "SYM":
                candidates = self.known_symbols
            elif key == "STATE":
                candidates = _SESSION_STATES
            else:
                candidates = []
            for val in candidates:
                if val.upper().startswith(partial_val.upper()):
                    yield Completion(val, start_position=-len(partial_val))
            return

        # ---- Field-name completion ----
        partial_key = current.upper()
        field_candidates = [
            f for f in _CMD_FIELDS.get(cmd, []) if f.rstrip("=") not in already_keys
        ]
        for c in field_candidates:
            if c.upper().startswith(partial_key):
                yield Completion(c, start_position=-len(current))


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------


def _parse(line: str) -> tuple[str, dict[str, str]]:
    """Parse ``'CMD|K=V|K=V'`` into ``(CMD, {K: V, ...})``."""
    parts = [p.strip() for p in line.split("|")]
    cmd = parts[0].upper()
    fields: dict[str, str] = {}
    for seg in parts[1:]:
        if "=" in seg:
            k, _, v = seg.partition("=")
            fields[k.strip().upper()] = v.strip()
    return cmd, fields


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _px(price: float, decimals: int | None) -> str:
    """*price* at its symbol's scale (L006): 149.8 is 149.80, a 3-decimal
    12.5 is 12.500. ``None`` decimals (an unlisted symbol) prints it as is."""
    return str(price) if decimals is None else f"{price:.{decimals}f}"


def _order_price_cell(o: dict[str, Any]) -> str:
    """The limit price at the order's scale, plus its stop price if any."""
    decimals = o.get("tick_decimals")
    price, stop = o.get("price"), o.get("stop_price")
    cell = "—" if price is None else _px(price, decimals)
    if stop is not None:
        cell = (
            f"stop {_px(stop, decimals)}"
            if price is None
            else f"{cell} stop {_px(stop, decimals)}"
        )
    return cell


def _parse_price(price_str: str) -> tuple[bool, float | None]:
    """``(ok, price)`` for a typed ``PRICE=``: empty is ``(True, None)``. A
    price must be a finite positive number: the wire encodes ``nan``/``inf``
    as no price at all, so ``REOPEN|PRICE=nan`` opened at the equilibrium."""
    if not price_str:
        return True, None
    try:
        price = float(price_str)
    except ValueError:
        price = math.nan
    if not math.isfinite(price) or price <= 0:
        console.print(
            f"[red]Invalid PRICE:[/red] {escape(repr(price_str))} "
            "is not a positive number"
        )
        return False, None
    return True, price


def _print_book(book: dict[str, Any]) -> None:
    sym = book.get("symbol", "?")
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    last_price = book.get("last_price")
    last_qty = book.get("last_qty")
    decimals = int(book.get("tick_decimals", 2))

    def px(price: float) -> str:
        return _px(price, decimals)

    t = Table(
        title=f"Order Book — {escape(str(sym))}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("Bid Qty", justify="right", style="green", min_width=10)
    t.add_column("Bid Price", justify="right", style="bold green", min_width=12)
    t.add_column("Ask Price", justify="right", style="bold red", min_width=12)
    t.add_column("Ask Qty", justify="right", style="red", min_width=10)

    for i in range(max(len(bids), len(asks))):
        bid = bids[i] if i < len(bids) else None
        ask = asks[i] if i < len(asks) else None
        t.add_row(
            str(bid["qty"]) if bid else "",
            px(bid["price"]) if bid else "",
            px(ask["price"]) if ask else "",
            str(ask["qty"]) if ask else "",
        )

    console.print(t)
    if not bids and not asks:
        console.print("[dim]  (empty book)[/dim]")
    elif last_price is not None:
        # After an engine restart the price is restored, its quantity is not
        # (L008): print the price alone rather than "× None".
        qty = f" × {last_qty}" if last_qty is not None else ""
        console.print(f"  Last trade: {px(last_price)}{qty}")


def _print_orders(orders: list[dict[str, Any]], gw: str) -> None:
    if not orders:
        console.print(f"[dim]No resting orders for {escape(gw)}[/dim]")
        return

    t = Table(
        title=f"Resting orders — {escape(gw)}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("ID", style="dim", no_wrap=True)
    t.add_column("Symbol", min_width=8)
    t.add_column("Side", min_width=6)
    t.add_column("Type", min_width=12)
    t.add_column("Remaining", justify="right", min_width=10)
    t.add_column("Price", justify="right", min_width=10)

    for o in orders:
        side = o.get("side", "")
        side_col = "green" if side == "BUY" else "red"
        t.add_row(
            escape(o.get("id", "")),
            escape(o.get("symbol", "")),
            f"[{side_col}]{escape(side)}[/{side_col}]",
            escape(o.get("order_type", "")),
            str(o.get("remaining_qty", "")),
            _order_price_cell(o),
        )
    console.print(t)


def _print_level(result: dict[str, Any], sym: str, price: str) -> None:
    """Render an ``order.price_level_orders`` reply.

    Unlike ``_print_orders`` (single gateway, price implicit per-row from
    each order's own field), this is explicitly cross-gateway, so the
    gateway column is the one addition over ``_print_orders``'s layout —
    rows are already server-side sorted by price then arrival_seq, so
    reading top-to-bottom shows price/time priority directly.
    """
    if result.get("rejected"):
        console.print(f"[red]REJECTED[/red]  {escape(str(result.get('reason', '')))}")
        return

    orders = result.get("orders", [])
    label = escape(sym + (f" @ {price}" if price else ""))
    if not orders:
        console.print(f"[dim]No resting orders for {label}[/dim]")
        return

    t = Table(
        title=f"Price-level composition — {label}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("ID", style="dim", no_wrap=True)
    t.add_column("Gateway", min_width=10)
    t.add_column("Side", min_width=6)
    t.add_column("Type", min_width=12)
    t.add_column("Remaining", justify="right", min_width=10)
    t.add_column("Price", justify="right", min_width=10)

    for o in orders:
        side = o.get("side", "")
        side_col = "green" if side == "BUY" else "red"
        t.add_row(
            escape(o.get("id", "")),
            escape(o.get("gateway_id", "")),
            f"[{side_col}]{escape(side)}[/{side_col}]",
            escape(o.get("order_type", "")),
            str(o.get("remaining_qty", "")),
            _order_price_cell(o),
        )
    console.print(t)


def _print_symbols(symbols: list[str]) -> None:
    if not symbols:
        console.print("[dim]No symbols configured in the engine[/dim]")
        return
    t = Table(
        title="Configured instruments",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("#", style="dim", width=4)
    t.add_column("Symbol", style="bold", min_width=10)
    for i, sym in enumerate(symbols, 1):
        t.add_row(str(i), sym)
    console.print(t)


def _print_position(
    gw: str, rows: list[dict[str, Any]], decimals: dict[str, int | None]
) -> None:
    """Render combined position + live-quote data for one gateway.

    Each *rows* entry has ``symbol``, ``net_qty``, ``avg_cost`` (from
    ``position_snapshot``) merged with ``bid_price``/``ask_price`` (from
    ``quote_bootstrap``, when the gateway has an active quote on that
    symbol) plus derived ``spread``/``mid``. Quote prices are printed at
    the symbol's *decimals* (mid one place finer). A plain text layout is
    used here rather than a rich table -- table formatting is deferred.
    """
    if not rows:
        console.print(f"[dim]No position or active quotes for {escape(gw)}[/dim]")
        return

    for row in rows:
        sym = row.get("symbol", "?")
        net_qty = row.get("net_qty", 0)
        avg_cost = row.get("avg_cost", 0.0)
        bid = row.get("bid_price")
        ask = row.get("ask_price")
        qty_col = "green" if net_qty > 0 else ("red" if net_qty < 0 else "dim")
        console.print(f"[bold]{escape(str(sym))}[/bold]")
        console.print(
            f"  Position : [{qty_col}]{net_qty:+,}[/{qty_col}]"
            f"   Avg cost: {avg_cost:.4f}"
        )
        if bid is not None and ask is not None:
            d = decimals.get(sym)
            spread = row.get("spread", ask - bid)
            mid = row.get("mid", (bid + ask) / 2)
            console.print(
                f"  Quote    : bid {_px(bid, d)}  ask {_px(ask, d)}"
                f"   spread {_px(spread, d)}"
                f"   mid {_px(mid, None if d is None else d + 1)}"
            )
        else:
            console.print("  Quote    : [dim](no active quote)[/dim]")


def _print_session_status(result: dict[str, Any]) -> None:
    state = result.get("state", "?")
    enabled = result.get("sessions_enabled", False)
    state_col = "bold green" if state not in ("CLOSED", "PRE_OPEN") else "bold yellow"
    console.print(
        f"  Session state     : [{state_col}]{escape(str(state))}[/{state_col}]"
    )
    console.print(
        f"  Auto-scheduling   : {'[green]ON[/green]' if enabled else '[dim]off[/dim]'}"
    )


#: (wire key, column header) for every day slot a WeeklySchedule carries.
_SCHEDULE_DAY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("mon", "Mon"),
    ("tue", "Tue"),
    ("wed", "Wed"),
    ("thu", "Thu"),
    ("fri", "Fri"),
    ("sat", "Sat"),
    ("sun", "Sun"),
    ("holidays", "Holidays"),
)

#: (wire key, row label) for the 5 transition times of one day.
_SCHEDULE_PHASES: tuple[tuple[str, str], ...] = (
    ("pre_open", "Pre-Open"),
    ("opening_auction_start", "Opening Auction Start"),
    ("continuous_start", "Continuous Trading Start"),
    ("closing_auction_start", "Closing Auction Start"),
    ("closing_auction_end", "Closing Auction End"),
)


def _print_schedule(result: dict[str, Any]) -> None:
    enabled = result.get("sessions_enabled", False)
    schedule: dict[str, Any] | None = result.get("schedule")

    if not enabled:
        console.print(
            "[dim]Automatic session scheduling is [yellow]disabled[/yellow].[/dim]"
        )
        if not schedule:
            return

    t = Table(
        title="Session schedule",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("Phase", style="bold", min_width=24)
    for _, day_label in _SCHEDULE_DAY_COLUMNS:
        t.add_column(day_label, justify="right")

    schedule = schedule or {}
    for phase_key, phase_label in _SCHEDULE_PHASES:
        row = [phase_label]
        for day_key, _ in _SCHEDULE_DAY_COLUMNS:
            day = schedule.get(day_key)
            val = day.get(phase_key) if day else None
            row.append(val if val else "[dim]—[/dim]")
        t.add_row(*row)
    console.print(t)


def _print_gateways(gateways: list[dict[str, Any]]) -> None:
    if not gateways:
        console.print("[dim]No gateways configured in the engine.[/dim]")
        return

    t = Table(
        title="Configured gateways",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("ID", style="bold", min_width=12)
    t.add_column("Role", min_width=10)
    t.add_column("Description", min_width=20)
    t.add_column("Connected", justify="center", min_width=10)

    for gw in gateways:
        connected = gw.get("connected", False)
        status_str = "[green]YES[/green]" if connected else "[dim]no[/dim]"
        t.add_row(
            escape(gw.get("id", "")),
            escape(gw.get("role", "")),
            escape(gw.get("description", "")),
            status_str,
        )
    console.print(t)


def _print_volume(result: dict[str, Any]) -> None:
    symbols: list[dict[str, Any]] = result.get("symbols", [])
    total_qty = result.get("total_qty", 0)
    total_value = result.get("total_value", 0.0)
    total_trades = result.get("total_trades", 0)

    if not symbols:
        console.print("[dim]No trades today.[/dim]")
        return

    t = Table(
        title="Daily traded volume",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("Symbol", style="bold", min_width=10)
    t.add_column("Qty", justify="right", min_width=12)
    t.add_column("Value", justify="right", min_width=16)
    t.add_column("Trades", justify="right", min_width=8)

    for v in symbols:
        t.add_row(
            escape(str(v.get("symbol", ""))),
            f"{v.get('qty', 0):,}",
            f"{v.get('value', 0.0):,.2f}",
            str(v.get("trades", 0)),
        )

    # Totals row
    t.add_section()
    t.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_qty:,}[/bold]",
        f"[bold]{total_value:,.2f}[/bold]",
        f"[bold]{total_trades}[/bold]",
    )
    console.print(t)


# ---------------------------------------------------------------------------
# Shared command executor — used by both the REPL and the CLI tool
# ---------------------------------------------------------------------------


def _report(
    result: dict[str, Any], accepted_message: str, *, json_output: bool
) -> tuple[bool, dict[str, Any]]:
    """Print *accepted_message* on success, else a REJECTED line with reason
    -- unless *json_output*, in which case *result* is printed as JSON
    instead and no rich-text line is produced."""
    accepted = bool(result.get("accepted"))
    if json_output:
        _print_json(result)
    elif accepted:
        console.print(accepted_message)
    else:
        console.print(f"[red]REJECTED[/red]  {escape(str(result.get('reason', '')))}")
    return accepted, result


def _print_json(result: Any) -> None:
    """Print *result* as JSON to stdout, bypassing the rich console so a
    machine reader gets plain, undecorated output regardless of terminal
    detection."""
    print(json.dumps(result, indent=2, default=str))


def _cmd_halt(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    result = client.halt_all()
    return _report(
        result,
        f"[bold red]HALTED[/bold red]  "
        f"{result.get('halted_symbols', 0)} symbol(s), "
        f"{result.get('cancelled_quotes', 0)} quote leg(s) cancelled",
        json_output=json_output,
    )


def _cmd_resume(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    result = client.resume_all()
    return _report(
        result,
        f"[bold green]RESUMED[/bold green]  "
        f"{result.get('resumed_symbols', 0)} symbol(s)",
        json_output=json_output,
    )


def _cmd_halt_sym(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print("[yellow]Usage:[/yellow]  HALT_SYM|SYM=<sym>")
        return False, {}
    result = client.symbol_halt(sym)
    return _report(
        result,
        f"[bold red]HALTED[/bold red]  {escape(str(result.get('symbol', sym)))}  "
        f"{result.get('cancelled_quotes', 0)} quote leg(s) cancelled",
        json_output=json_output,
    )


def _cmd_resume_sym(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print("[yellow]Usage:[/yellow]  RESUME_SYM|SYM=<sym>")
        return False, {}
    result = client.symbol_resume(sym)
    return _report(
        result,
        f"[bold green]RESUMED[/bold green]  {escape(str(result.get('symbol', sym)))}",
        json_output=json_output,
    )


def _cmd_cancel_sym(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print("[yellow]Usage:[/yellow]  CANCEL_SYM|SYM=<sym>")
        return False, {}
    result = client.cancel_symbol(sym)
    return _report(
        result,
        f"[yellow]CANCEL_SYM OK[/yellow]  {escape(str(result.get('symbol', sym)))}  "
        f"orders={result.get('cancelled_orders', 0)}  "
        f"quotes={result.get('cancelled_quotes', 0)}",
        json_output=json_output,
    )


def _cmd_reopen(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print(
            "[yellow]Usage:[/yellow]  "
            "REOPEN|SYM=<sym>[|PRICE=<px>][|DRY_RUN=1][|NOTE=<text>]"
        )
        return False, {}
    price_ok, price = _parse_price(fields.get("PRICE", ""))
    if not price_ok:
        return False, {}
    dry_run = fields.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    note = fields.get("NOTE", "")
    # The scale for the printed prices, fetched before the uncross: a lookup
    # timing out afterwards would report an executed REOPEN as a TIMEOUT.
    decimals = None if json_output else client.tick_decimals(sym)

    result = client.force_uncross(sym, price, dry_run=dry_run, note=note)

    if json_output:
        _print_json(result)
        return bool(result.get("accepted")), result

    accepted = bool(result.get("accepted"))
    if not accepted:
        console.print(f"[red]REJECTED[/red]  {escape(str(result.get('reason', '')))}")
        return False, result

    symbol = escape(str(result.get("symbol", sym)))
    ind_px = result.get("indicative_price")
    ind_qty = result.get("indicative_qty", 0)
    side = result.get("imbalance_side") or "balanced"
    surplus = result.get("surplus", 0)
    ind_txt = "no cross" if ind_px is None else f"{_px(ind_px, decimals)} x {ind_qty}"
    if result.get("dry_run"):
        console.print(
            f"[cyan]REOPEN DRY-RUN[/cyan]  {symbol}  "
            f"indicative={ind_txt}  imbalance={side} ({surplus})"
        )
    else:
        printed = result.get("printed_price")
        traded = result.get("traded_qty", 0)
        printed_txt = (
            "nothing printed"
            if printed is None
            else f"{_px(printed, decimals)} x {traded}"
        )
        console.print(
            f"[bold green]REOPEN OK[/bold green]  {symbol}  "
            f"printed={printed_txt}  (indicative was {ind_txt})"
        )
    return True, result


def _cmd_kill(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    gw = fields.get("GW", "")
    if not gw:
        console.print("[yellow]Usage:[/yellow]  KILL|GW=<gw>[|SYM=<sym>]")
        return False, {}
    sym = fields.get("SYM", "")
    if gw.upper() == client.gateway_id.upper():
        result = client.kill_switch(gw, symbol=sym)
    else:
        # Another participant: the ADMIN message, so the audit trail names
        # the operator and a disconnected target can still be cleared.
        result = client.kill_switch_gateway(gw, symbol=sym)
    return _report(
        result,
        f"[yellow]KILL OK[/yellow]  {escape(gw.upper())}  "
        f"orders={result.get('cancelled_orders', 0)}  "
        f"quotes={result.get('cancelled_quotes', 0)}",
        json_output=json_output,
    )


def _cmd_kick(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    gw = fields.get("GW", "")
    if not gw:
        console.print("[yellow]Usage:[/yellow]  KICK|GW=<gw>[|REASON=<text>]")
        return False, {}
    # The engine refuses an unknown, a disconnected or our own id itself.
    result = client.gateway_kick(gw, reason=fields.get("REASON", ""))
    target = escape(str(result.get("target_gateway_id") or gw.upper()))
    return _report(
        result, f"[yellow]KICK OK[/yellow]  {target}", json_output=json_output
    )


def _cmd_qcancel(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    gw = fields.get("GW", "")
    sym = fields.get("SYM", "")
    if not gw or not sym:
        console.print("[yellow]Usage:[/yellow]  QCANCEL|GW=<gw>|SYM=<sym>")
        return False, {}
    if gw.upper() == client.gateway_id.upper():
        result = client.quote_cancel(gw, sym)
    else:
        result = client.kill_switch_gateway(gw, symbol=sym, quotes_only=True)
    return _report(
        result,
        f"[yellow]QCANCEL OK[/yellow]  {escape(gw.upper())}  {escape(sym.upper())}",
        json_output=json_output,
    )


def _cmd_book(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print("[yellow]Usage:[/yellow]  BOOK|SYM=<sym>")
        return False, {}
    result = client.book_depth(sym)
    if json_output:
        _print_json(result)
    else:
        _print_book(result)
    return True, result


def _query_status_line(reply: dict[str, Any], json_output: bool) -> bool:
    """Say what an orders/position ``status`` means; ``False`` for an
    unknown gateway, whose empty answer must not read as "nothing"."""
    status = reply.get("status", "OK")
    gw = reply.get("gateway_id", "")
    if status == "UNKNOWN_GATEWAY":
        if not json_output:
            console.print(f"[red]REJECTED[/red]  Gateway not configured: {escape(gw)}")
        return False
    if status == "NOT_CONNECTED" and not json_output:
        console.print(
            f"[yellow]{escape(gw)} is not connected[/yellow] (stored state shown)"
        )
    return True


def _cmd_orders(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    gw = fields.get("GW", "")
    if not gw:
        console.print("[yellow]Usage:[/yellow]  ORDERS|GW=<gw>")
        return False, {}
    reply = client.orders_reply(gw)
    known = _query_status_line(reply, json_output)
    if json_output:
        _print_json(reply)
    elif known:
        _print_orders(list(reply.get("orders", [])), gw.upper())
    return known, reply


def _cmd_level(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    sym = fields.get("SYM", "")
    if not sym:
        console.print("[yellow]Usage:[/yellow]  LEVEL|SYM=<sym>[|PRICE=<px>]")
        return False, {}
    price_str = fields.get("PRICE", "")
    price_ok, price = _parse_price(price_str)
    if not price_ok:
        return False, {}
    result = client.price_level_orders(sym, price)
    if json_output:
        _print_json(result)
    else:
        _print_level(result, sym.upper(), price_str)
    return not result.get("rejected", False), result


def _cmd_symbols(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, list[str]]:
    symbols = client.symbol_list()
    if symbols_cache is not None:
        symbols_cache.clear()
        symbols_cache.extend(symbols)
    if json_output:
        _print_json(symbols)
    else:
        _print_symbols(symbols)
    return True, symbols


def _cmd_session(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    state = fields.get("STATE", "")
    if not state:
        console.print("[yellow]Usage:[/yellow]  SESSION|STATE=<state>")
        return False, {}
    result = client.session_advance(state)
    accepted = bool(result.get("accepted"))
    if json_output:
        _print_json(result)
    elif accepted:
        console.print(
            f"[bold]SESSION[/bold]  now {escape(str(result.get('to_state', state)))}"
        )
    else:
        console.print(
            f"[bold]SESSION[/bold]  [red]REJECTED[/red]  "
            f"{escape(str(result.get('reason', '')))}"
        )
    return accepted, result


def _cmd_session_status(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    result = client.session_status()
    if json_output:
        _print_json(result)
    else:
        _print_session_status(result)
    return True, result


def _cmd_schedule(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    result = client.session_schedule()
    if json_output:
        _print_json(result)
    else:
        _print_schedule(result)
    return True, result


def _cmd_gateways(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, list[dict[str, Any]]]:
    gateways = client.gateway_list()
    if json_output:
        _print_json(gateways)
    else:
        _print_gateways(gateways)
    return True, gateways


def _cmd_volume(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    result = client.volume()
    if json_output:
        _print_json(result)
    else:
        _print_volume(result)
    return True, result


def _cmd_position(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, dict[str, Any]]:
    """Query a gateway's per-symbol net position plus its live quote.

    Combines two independent engine round-trips -- ``position_snapshot``
    (signed net qty + VWAP avg cost, from the engine's fill ledger; any
    gateway, not just a market maker) and ``quote_bootstrap`` (live resting
    quote prices, if any) -- into one row per symbol, keyed by symbol. This
    mirrors ``POS|GW=`` on ``pm-alf-console``/``pm-alf-gwy`` and the REST
    ``GET /api/v1/admin/gateways/{gateway_id}/positions`` endpoint, all three built on the same
    ``system.position_request``/``system.position_snapshot.<gw>`` pair, so
    all surfaces agree on the position figures; the bid/ask/spread/mid
    addition here is specific to this command.

    Optional ``SYM=`` narrows to one or more comma-separated symbols; a
    symbol with neither a position nor an active quote is omitted. The
    result is ``{gateway_id, status, positions}`` with the engine's
    ``status``; an unknown gateway fails instead of looking flat.
    """
    gw = fields.get("GW", "")
    if not gw:
        console.print(
            "[yellow]Usage:[/yellow]  POSITION|GW=<gw>[|SYM=<sym>[,<sym>...]]"
        )
        return False, {}

    wanted = {s.strip().upper() for s in fields.get("SYM", "").split(",") if s.strip()}

    reply = client.positions_reply(gw)
    result: dict[str, Any] = {
        "gateway_id": gw.upper(),
        "status": reply.get("status", "OK"),
        "positions": [],
    }
    if not _query_status_line(result, json_output):
        if json_output:
            _print_json(result)
        return False, result
    positions = list(reply.get("positions", []))
    quotes = client.quote_bootstrap(gw)

    by_symbol: dict[str, dict[str, Any]] = {}
    for pos in positions:
        sym = str(pos.get("symbol", "")).upper()
        if not sym:
            continue
        by_symbol[sym] = {
            "symbol": sym,
            "net_qty": pos.get("net_qty", 0),
            "avg_cost": pos.get("avg_cost", 0.0),
        }

    scale: dict[str, int | None] = {}
    for q in quotes:
        sym = str(q.get("symbol", "")).upper()
        if not sym:
            continue
        row = by_symbol.setdefault(sym, {"symbol": sym, "net_qty": 0, "avg_cost": 0.0})
        bid = q.get("bid_price")
        ask = q.get("ask_price")
        row["bid_price"] = bid
        row["ask_price"] = ask
        if bid is not None and ask is not None:
            # Rounded to the symbol's scale (mid one place finer): the float
            # difference of 149.90 and 149.70 is 0.20000000000000284.
            d = scale.setdefault(sym, client.tick_decimals(sym))
            row["spread"] = ask - bid if d is None else round(ask - bid, d)
            row["mid"] = (bid + ask) / 2 if d is None else round((bid + ask) / 2, d + 1)

    if wanted:
        by_symbol = {sym: row for sym, row in by_symbol.items() if sym in wanted}

    rows = [by_symbol[sym] for sym in sorted(by_symbol)]
    result["positions"] = rows

    if json_output:
        _print_json(result)
    else:
        _print_position(gw.upper(), rows, scale)
    return True, result


# Maps each upper-cased command name to its handler.  Adding a new command
# only requires a new _cmd_* function plus an entry here (and argparse wiring
# in cli.py). Every handler returns (accepted, result) so a caller can get
# the structured data back (used for --format json) without re-parsing
# printed output.
_COMMAND_HANDLERS: dict[
    str,
    Callable[
        [ExchangeCommandClient, dict[str, str], list[str] | None, bool],
        tuple[bool, Any],
    ],
] = {
    "HALT": _cmd_halt,
    "RESUME": _cmd_resume,
    "HALT_SYM": _cmd_halt_sym,
    "RESUME_SYM": _cmd_resume_sym,
    "CANCEL_SYM": _cmd_cancel_sym,
    "REOPEN": _cmd_reopen,
    "KILL": _cmd_kill,
    "KICK": _cmd_kick,
    "QCANCEL": _cmd_qcancel,
    "BOOK": _cmd_book,
    "ORDERS": _cmd_orders,
    "LEVEL": _cmd_level,
    "SYMBOLS": _cmd_symbols,
    "SESSION": _cmd_session,
    "SESSION_STATUS": _cmd_session_status,
    "SCHEDULE": _cmd_schedule,
    "GATEWAYS": _cmd_gateways,
    "VOLUME": _cmd_volume,
    "POSITION": _cmd_position,
}


def execute_command(
    client: ExchangeCommandClient,
    cmd: str,
    fields: dict[str, str],
    *,
    symbols_cache: list[str] | None = None,
    json_output: bool = False,
) -> tuple[bool, Any]:
    """
    Execute one admin command against *client* and print the result.

    This function is the single source of truth for command behaviour.
    Both the interactive REPL (``pm-admin``) and the CLI tool
    (``pm-admin-cli``) call it so that adding a new command only requires
    changes here (a new ``_cmd_*`` handler plus a ``_COMMAND_HANDLERS`` entry)
    plus argparse wiring in ``cli.py``.

    Parameters
    ----------
    client:
        An already-connected ``ExchangeCommandClient``.
    cmd:
        Upper-cased command name, e.g. ``"HALT"``.
    fields:
        Key/value pairs for the command, e.g. ``{"GW": "TRADER01"}``.
    symbols_cache:
        If supplied, the SYMBOLS command will keep this list up to date so
        that the REPL's tab-completer reflects fresh symbol data.
    json_output:
        If ``True``, every command prints its result as JSON to stdout
        (plain ``print``, not the rich console) instead of the normal
        rich-formatted table or status line. The returned data is the same
        either way -- this only changes what gets printed.

    Returns
    -------
    tuple[bool, Any]
        ``(accepted, result)``. ``accepted`` is ``True`` if the command was
        accepted / completed successfully, ``False`` if the engine rejected
        it, a required field was missing, or the command was unrecognised.
        ``result`` is the structured data the command produced (a dict,
        list, or ``{}``/``[]`` for a usage error) -- the same object that
        was (or would have been) rendered.

    Raises
    ------
    CommandTimeoutError
        Propagated from the client when no ack arrives within the timeout.
    """
    handler = _COMMAND_HANDLERS.get(cmd)
    if handler is None:
        message = f"Unknown command '{cmd}'."
        if json_output:
            _print_json({"error": message})
        else:
            console.print(
                f"[dim]{escape(message)}  Type HELP for the command reference.[/dim]"
            )
        return False, {"error": message}
    return handler(client, fields, symbols_cache, json_output)


# ---------------------------------------------------------------------------
# Main console class
# ---------------------------------------------------------------------------

_PROMPT_STYLE = Style.from_dict({"prompt": "bold ansired"})


class AdminConsole:
    """
    Interactive REPL for ADMIN-role exchange operations.

    Wraps :class:`~edumatcher.commands.ExchangeCommandClient` with a
    prompt_toolkit REPL that provides tab completion and command history.
    """

    def __init__(self, gw_id: str) -> None:
        self._gw_id = gw_id.upper()
        self._client = ExchangeCommandClient(self._gw_id)
        self._known_symbols: list[str] = []
        self._connection_lost = False
        self._exit_requested = False
        self._prompt_app: Any = None
        self._heartbeat_stop = threading.Event()

    def _heartbeat_loop(self) -> None:
        """Tell the engine this console is alive, so an idle console keeps its
        ID and a killed one frees it (the engine times out a session that
        stops beating, or never beats). Own socket: a ZMQ socket must not be
        shared across threads, and the client's belongs to the prompt."""
        push_sock = make_pusher(ENGINE_PULL_ADDR)
        try:
            while True:
                try:
                    push_sock.send_multipart(
                        make_gateway_heartbeat_msg(
                            self._gw_id, INTERACTIVE_HEARTBEAT_INTERVAL_SEC
                        )
                    )
                except zmq.Again:
                    log.debug("gateway_id=%s heartbeat dropped: engine unreachable", self._gw_id)  # fmt: skip
                if self._heartbeat_stop.wait(INTERACTIVE_HEARTBEAT_INTERVAL_SEC):
                    return
        finally:
            push_sock.close(linger=0)

    def _request_exit(self) -> None:
        """SIGHUP or SIGTERM: leave the prompt loop as EXIT does, so the
        console logs out instead of the process just ending."""
        log.info("terminal closed or terminated gateway_id=%s", self._gw_id)
        self._exit_requested = True
        app = self._prompt_app
        if app is not None and app.is_running:
            app.loop.call_soon_threadsafe(
                lambda: (
                    app.exit(exception=KeyboardInterrupt) if app.is_running else None
                )
            )

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, cmd: str, fields: dict[str, str]) -> None:
        if cmd in ("HELP", "?"):
            console.print(_HELP_TEXT)
            return
        if cmd in ("EXIT", "QUIT"):
            raise SystemExit(0)
        try:
            execute_command(
                self._client, cmd, fields, symbols_cache=self._known_symbols
            )
        except zmq.Again:
            self._connection_lost = True
            console.print("[red]Engine connection was lost; logging out.[/red]")
        except CommandTimeoutError as exc:
            console.print(f"[red]TIMEOUT[/red]  {escape(str(exc))}")

    async def _watch_engine_disconnect(
        self, app: Any, monitor: zmq.Socket[bytes]
    ) -> None:
        while not self._connection_lost:
            if monitor.poll(0):
                event = recv_monitor_message(monitor)
                if event["event"] == zmq.EVENT_DISCONNECTED:
                    self._connection_lost = True
                    console.print("[red]Engine connection was lost; logging out.[/red]")
                    app.exit(exception=KeyboardInterrupt)
                    return
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # REPL entry point
    # ------------------------------------------------------------------

    def run(self) -> int:
        """Run the REPL; return 0 after EXIT/EOF/Ctrl-C or a hangup, 1 when
        no session was had (timeout, refusal) or the engine was lost."""
        # Authenticate
        try:
            result = self._client.connect()
        except CommandTimeoutError:
            console.print(
                "[red]Connection timed out.[/red]  "
                f"Is the engine running at {escape(ENGINE_PULL_ADDR)}?"
            )
            self._client.close()
            return 1

        if not result.get("accepted"):
            console.print(
                f"[red]Auth refused:[/red] {escape(str(result.get('reason', '')))}"
            )
            self._client.close()
            return 1

        monitor = self._client.engine_disconnect_monitor()
        heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="admin-heartbeat", daemon=True
        )
        heartbeat.start()
        try:
            desc = result.get("description", "")
            console.print(
                f"\n[bold green]ADMIN console — {escape(self._gw_id)} connected"
                "[/bold green]"
                + (f"  {escape(str(desc))}" if desc else "")
                + "\nType [bold]HELP[/bold] for commands.  "
                "[dim]Tab=complete  ↑↓=history  Ctrl-C=exit[/dim]\n"
            )

            try:
                self._known_symbols.extend(self._client.symbol_list())
            except CommandTimeoutError:
                pass

            completer = _AdminCompleter(self._known_symbols)
            session: PromptSession[str] = PromptSession(
                history=InMemoryHistory(),
                completer=completer,
                complete_while_typing=False,
                style=_PROMPT_STYLE,
                mouse_support=False,
            )
            prompt_str = FormattedText([("class:prompt", f"[{self._gw_id}|ADMIN]> ")])

            with logout_on_hangup(self._request_exit), pt_patch_stdout(raw=True):
                while not self._connection_lost and not self._exit_requested:

                    def _start_monitor() -> None:
                        self._prompt_app = session.app
                        session.app.create_background_task(
                            self._watch_engine_disconnect(session.app, monitor)
                        )

                    try:
                        line = session.prompt(prompt_str, pre_run=_start_monitor)
                    except EOFError, KeyboardInterrupt:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    cmd, fields = _parse(line)
                    if cmd in ("EXIT", "QUIT"):
                        break
                    try:
                        self._dispatch(cmd, fields)
                    except Exception as exc:
                        # Leaving the loop would log the operator out in the
                        # middle of whatever they were doing.
                        log.exception(
                            "command failed gateway_id=%s line=%r", self._gw_id, line
                        )
                        console.print(f"[red]Command failed:[/red] {escape(str(exc))}")
        finally:
            self._heartbeat_stop.set()
            heartbeat.join()
            try:
                self._client.close_engine_disconnect_monitor(monitor)
            finally:
                try:
                    if not self._connection_lost:
                        self._client.disconnect()
                except zmq.Again:
                    self._connection_lost = True
                    console.print("[red]Engine connection was lost; logging out.[/red]")
                finally:
                    self._client.close()
                    console.print(
                        f"\n[bold]ADMIN console {escape(self._gw_id)} disconnected.[/bold]"
                    )
        return 1 if self._connection_lost else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EduMatcher ADMIN operator console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  poetry run pm-admin --id GW_ADMIN\n\n"
            "Requires the gateway to be configured with role: ADMIN\n"
            "in engine_config.yaml."
        ),
    )
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-admin")
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="ADMIN gateway ID (e.g. GW_ADMIN)",
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
        help="Explicit WARNING log level (the default)",
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


@exit_on_config_error
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info("starting pm-admin with log level %s", logging.getLevelName(log_level))
    sys.exit(AdminConsole(args.id).run())


if __name__ == "__main__":
    main()
