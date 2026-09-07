"""
pm-admin — interactive ADMIN operator console for EduMatcher.

Usage
-----
  poetry run pm-admin --id GW_ADMIN

The gateway ID must match an entry in ``engine_config.yaml`` that has
``role: ADMIN``.  All commands are sent over the same ZeroMQ PUSH/SUB
transport used by ``ExchangeCommandClient``.

Commands
--------
  HALT                          — halt all symbols (manual circuit breaker)
  RESUME                        — resume all symbols halted by HALT
  KILL|GW=<gw>[|SYM=<sym>]     — cancel all orders/quotes for a gateway
  KICK|GW=<gw>[|REASON=<text>] — forcefully disconnect a gateway
  QCANCEL|GW=<gw>|SYM=<sym>    — cancel the active quote for a gateway on one symbol
  BOOK|SYM=<sym>                — print L1/L2 order-book snapshot
  ORDERS|GW=<gw>                — list resting orders for a gateway
  LEVEL|SYM=<sym>[|PRICE=<px>]  — show every resting order making up a symbol
                                   (or one price level), across all gateways
  SYMBOLS                       — list all instruments configured in the engine
  POSITION|GW=<gw>[|SYM=<sym>,..] — net position, avg cost, live bid/ask/spread/mid
  SESSION|STATE=<state>         — advance session phase
  HELP                          — show this reference
  EXIT / QUIT                   — disconnect
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

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

  KILL|GW=<gw>[|SYM=<sym>]     — cancel all resting orders and the active quote for <gw>
                                   (add SYM= to scope to a single instrument)
  KICK|GW=<gw>[|REASON=<text>] — forcefully disconnect gateway <gw>
                                   (applies configured disconnect_behaviour)
  QCANCEL|GW=<gw>|SYM=<sym>    — cancel the active two-sided quote for <gw> on <sym>
                                   without touching resting limit orders

  BOOK|SYM=<sym>                — print the current L1/L2 order-book snapshot for <sym>
  ORDERS|GW=<gw>                — list all resting orders for gateway <gw>
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


def _print_book(book: dict[str, Any]) -> None:
    sym = book.get("symbol", "?")
    bids = book.get("bids", [])
    asks = book.get("asks", [])
    last_price = book.get("last_price")
    last_qty = book.get("last_qty")

    t = Table(
        title=f"Order Book — {sym}",
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
            str(bid["price"]) if bid else "",
            str(ask["price"]) if ask else "",
            str(ask["qty"]) if ask else "",
        )

    console.print(t)
    if not bids and not asks:
        console.print("[dim]  (empty book)[/dim]")
    elif last_price is not None:
        console.print(f"  Last trade: {last_price} × {last_qty}")


def _print_orders(orders: list[dict[str, Any]], gw: str) -> None:
    if not orders:
        console.print(f"[dim]No resting orders for {gw}[/dim]")
        return

    t = Table(
        title=f"Resting orders — {gw}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("ID", style="dim", min_width=12)
    t.add_column("Symbol", min_width=8)
    t.add_column("Side", min_width=6)
    t.add_column("Type", min_width=12)
    t.add_column("Remaining", justify="right", min_width=10)
    t.add_column("Price", justify="right", min_width=10)

    for o in orders:
        side = o.get("side", "")
        side_col = "green" if side == "BUY" else "red"
        price_str = str(o.get("price", "")) if o.get("price") else "—"
        t.add_row(
            o.get("id", "")[:14],
            o.get("symbol", ""),
            f"[{side_col}]{side}[/{side_col}]",
            o.get("order_type", ""),
            str(o.get("remaining_qty", "")),
            price_str,
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
        console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return

    orders = result.get("orders", [])
    label = f"{sym}" + (f" @ {price}" if price else "")
    if not orders:
        console.print(f"[dim]No resting orders for {label}[/dim]")
        return

    t = Table(
        title=f"Price-level composition — {label}",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("ID", style="dim", min_width=12)
    t.add_column("Gateway", min_width=10)
    t.add_column("Side", min_width=6)
    t.add_column("Type", min_width=12)
    t.add_column("Remaining", justify="right", min_width=10)
    t.add_column("Price", justify="right", min_width=10)

    for o in orders:
        side = o.get("side", "")
        side_col = "green" if side == "BUY" else "red"
        price_str = str(o.get("price", "")) if o.get("price") else "—"
        t.add_row(
            o.get("id", "")[:14],
            o.get("gateway_id", ""),
            f"[{side_col}]{side}[/{side_col}]",
            o.get("order_type", ""),
            str(o.get("remaining_qty", "")),
            price_str,
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


def _print_position(gw: str, rows: list[dict[str, Any]]) -> None:
    """Render combined position + live-quote data for one gateway.

    Each *rows* entry has ``symbol``, ``net_qty``, ``avg_cost`` (from
    ``position_snapshot``) merged with ``bid_price``/``ask_price`` (from
    ``quote_bootstrap``, when the gateway has an active quote on that
    symbol) plus derived ``spread``/``mid``. A plain text layout is used
    here rather than a rich table -- table formatting is deferred.
    """
    if not rows:
        console.print(f"[dim]No position or active quotes for {gw}[/dim]")
        return

    for row in rows:
        sym = row.get("symbol", "?")
        net_qty = row.get("net_qty", 0)
        avg_cost = row.get("avg_cost", 0.0)
        bid = row.get("bid_price")
        ask = row.get("ask_price")
        qty_col = "green" if net_qty > 0 else ("red" if net_qty < 0 else "dim")
        console.print(f"[bold]{sym}[/bold]")
        console.print(
            f"  Position : [{qty_col}]{net_qty:+,}[/{qty_col}]"
            f"   Avg cost: {avg_cost:.4f}"
        )
        if bid is not None and ask is not None:
            spread = row.get("spread")
            mid = row.get("mid")
            console.print(
                f"  Quote    : bid {bid:.4f}  ask {ask:.4f}"
                f"   spread {spread:.4f}   mid {mid:.4f}"
            )
        else:
            console.print("  Quote    : [dim](no active quote)[/dim]")


def _print_session_status(result: dict[str, Any]) -> None:
    state = result.get("state", "?")
    enabled = result.get("sessions_enabled", False)
    state_col = "bold green" if state not in ("CLOSED", "PRE_OPEN") else "bold yellow"
    console.print(f"  Session state     : [{state_col}]{state}[/{state_col}]")
    console.print(
        f"  Auto-scheduling   : {'[green]ON[/green]' if enabled else '[dim]off[/dim]'}"
    )


def _print_schedule(result: dict[str, Any]) -> None:
    enabled = result.get("sessions_enabled", False)
    schedule: dict[str, str] = result.get("schedule", {})

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
    t.add_column("Time (HH:MM)", justify="right", min_width=14)

    phase_labels = [
        ("pre_open", "Pre-Open"),
        ("opening_auction_start", "Opening Auction Start"),
        ("continuous_start", "Continuous Trading Start"),
        ("closing_auction_start", "Closing Auction Start"),
        ("closing_auction_end", "Closing Auction End"),
    ]
    for key, label in phase_labels:
        val = schedule.get(key, "") if schedule else ""
        t.add_row(label, val if val else "[dim]—[/dim]")
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
            gw.get("id", ""),
            gw.get("role", ""),
            gw.get("description", ""),
            status_str,
        )
    console.print(t)


def _print_volume(result: dict[str, Any]) -> None:
    symbols: dict[str, dict[str, Any]] = result.get("symbols", {})
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

    for sym, v in symbols.items():
        t.add_row(
            sym,
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
        console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
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
        f"[bold red]HALTED[/bold red]  {result.get('symbol', sym)}  "
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
        f"[bold green]RESUMED[/bold green]  {result.get('symbol', sym)}",
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
        f"[yellow]CANCEL_SYM OK[/yellow]  {result.get('symbol', sym)}  "
        f"orders={result.get('cancelled_orders', 0)}  "
        f"quotes={result.get('cancelled_quotes', 0)}",
        json_output=json_output,
    )


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
    result = client.kill_switch(gw, symbol=fields.get("SYM", ""))
    return _report(
        result,
        f"[yellow]KILL OK[/yellow]  {gw.upper()}  "
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
    client.gateway_kick(gw, reason=fields.get("REASON", ""))
    result = {"gateway_id": gw.upper()}
    if json_output:
        _print_json(result)
    else:
        console.print(f"[yellow]KICK[/yellow]  sent disconnect for {gw.upper()}")
    return True, result


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
    result = client.quote_cancel(gw, sym)
    return _report(
        result,
        f"[yellow]QCANCEL OK[/yellow]  {gw.upper()}  {sym.upper()}",
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


def _cmd_orders(
    client: ExchangeCommandClient,
    fields: dict[str, str],
    symbols_cache: list[str] | None,
    json_output: bool,
) -> tuple[bool, list[dict[str, Any]]]:
    gw = fields.get("GW", "")
    if not gw:
        console.print("[yellow]Usage:[/yellow]  ORDERS|GW=<gw>")
        return False, []
    orders = client.order_list(gw)
    if json_output:
        _print_json(orders)
    else:
        _print_orders(orders, gw.upper())
    return True, orders


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
    price: float | None = None
    if price_str:
        try:
            price = float(price_str)
        except ValueError:
            console.print(f"[red]Invalid PRICE:[/red] {price_str!r} is not a number")
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
    if json_output:
        _print_json(result)
    else:
        console.print(
            f"[bold]SESSION[/bold]  "
            f"{result.get('prev_state', '?')} → {result.get('state', '?')}"
        )
    return True, result


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
) -> tuple[bool, list[dict[str, Any]]]:
    """Query a gateway's per-symbol net position plus its live quote.

    Combines two independent engine round-trips -- ``position_snapshot``
    (signed net qty + VWAP avg cost, from the engine's fill ledger; any
    gateway, not just a market maker) and ``quote_bootstrap`` (live resting
    quote prices, if any) -- into one row per symbol, keyed by symbol. This
    mirrors ``POS|GW=`` on ``pm-alf-console``/``pm-alf-gwy`` and the REST
    ``GET /api/v1/admin/positions`` endpoint, all three built on the same
    ``system.position_request``/``system.position_snapshot.<gw>`` pair, so
    all surfaces agree on the position figures; the bid/ask/spread/mid
    addition here is specific to this command.

    Optional ``SYM=`` narrows to one or more comma-separated symbols; a
    symbol with neither a position nor an active quote is omitted.
    """
    gw = fields.get("GW", "")
    if not gw:
        console.print(
            "[yellow]Usage:[/yellow]  POSITION|GW=<gw>[|SYM=<sym>[,<sym>...]]"
        )
        return False, []

    wanted = {s.strip().upper() for s in fields.get("SYM", "").split(",") if s.strip()}

    positions = client.position_snapshot(gw)
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
            row["spread"] = ask - bid
            row["mid"] = (bid + ask) / 2

    if wanted:
        by_symbol = {sym: row for sym, row in by_symbol.items() if sym in wanted}

    rows = [by_symbol[sym] for sym in sorted(by_symbol)]

    if json_output:
        _print_json(rows)
    else:
        _print_position(gw.upper(), rows)
    return True, rows


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
            console.print(f"[dim]{message}  Type HELP for the command reference.[/dim]")
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
        except CommandTimeoutError as exc:
            console.print(f"[red]TIMEOUT[/red]  {exc}")

    # ------------------------------------------------------------------
    # REPL entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        # Authenticate
        try:
            result = self._client.connect()
        except CommandTimeoutError:
            console.print(
                "[red]Connection timed out.[/red]  "
                "Is the engine running?  (default: tcp://127.0.0.1:5555)"
            )
            self._client.close()
            return

        if not result.get("accepted"):
            console.print(
                f"[red]Auth refused:[/red] {result.get('reason', '')}  "
                "(check role: ADMIN in engine_config.yaml)"
            )
            self._client.close()
            return

        desc = result.get("description", "")
        console.print(
            f"\n[bold green]ADMIN console — {self._gw_id} connected[/bold green]"
            + (f"  {desc}" if desc else "")
            + "\nType [bold]HELP[/bold] for commands.  "
            "[dim]Tab=complete  ↑↓=history  Ctrl-C=exit[/dim]\n"
        )

        # Pre-fetch symbol list so tab completion works immediately
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
        prompt_str = [("class:prompt", f"[{self._gw_id}|ADMIN]> ")]

        try:
            with pt_patch_stdout(raw=True):
                while True:
                    try:
                        line = session.prompt(prompt_str)  # type: ignore[arg-type]
                    except (EOFError, KeyboardInterrupt):
                        break
                    line = line.strip()
                    if not line:
                        continue
                    cmd, fields = _parse(line)
                    if cmd in ("EXIT", "QUIT"):
                        break
                    self._dispatch(cmd, fields)
        finally:
            self._client.disconnect()
            self._client.close()
            console.print(f"\n[bold]ADMIN console {self._gw_id} disconnected.[/bold]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
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
    log.info("starting pm-admin with log level %s", logging.getLevelName(log_level))
    AdminConsole(args.id).run()


if __name__ == "__main__":
    main()
