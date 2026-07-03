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
  SYMBOLS                       — list all instruments configured in the engine
  SESSION|STATE=<state>         — advance session phase
  HELP                          — show this reference
  EXIT / QUIT                   — disconnect
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient

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
    "SYMBOLS",
    "SESSION",
    "SESSION_STATUS",
    "SCHEDULE",
    "GATEWAYS",
    "VOLUME",
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
    "SESSION": ["STATE="],
}

_HELP_TEXT = """
[bold]ADMIN operator console — command reference[/bold]

  HALT                          — halt all symbols (manual circuit breaker, MANUAL resumption)
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
  SYMBOLS                       — list all instruments configured in the engine

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


def execute_command(  # noqa: C901
    client: ExchangeCommandClient,
    cmd: str,
    fields: dict[str, str],
    *,
    symbols_cache: list[str] | None = None,
) -> bool:
    """
    Execute one admin command against *client* and print the result.

    This function is the single source of truth for command behaviour.
    Both the interactive REPL (``pm-admin``) and the CLI tool
    (``pm-admin-cli``) call it so that adding a new command only requires
    changes here (plus argparse wiring in ``cli.py``).

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

    Returns
    -------
    bool
        ``True`` if the command was accepted / completed successfully,
        ``False`` if the engine rejected it or the command was unrecognised.

    Raises
    ------
    CommandTimeoutError
        Propagated from the client when no ack arrives within the timeout.
    """
    if cmd == "HALT":
        result = client.halt_all()
        if result.get("accepted"):
            console.print(
                f"[bold red]HALTED[/bold red]  "
                f"{result.get('halted_symbols', 0)} symbol(s), "
                f"{result.get('cancelled_quotes', 0)} quote leg(s) cancelled"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "RESUME":
        result = client.resume_all()
        if result.get("accepted"):
            console.print(
                f"[bold green]RESUMED[/bold green]  "
                f"{result.get('resumed_symbols', 0)} symbol(s)"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "HALT_SYM":
        sym = fields.get("SYM", "")
        if not sym:
            console.print("[yellow]Usage:[/yellow]  HALT_SYM|SYM=<sym>")
            return False
        result = client.symbol_halt(sym)
        if result.get("accepted"):
            console.print(
                f"[bold red]HALTED[/bold red]  {result.get('symbol', sym)}  "
                f"{result.get('cancelled_quotes', 0)} quote leg(s) cancelled"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "RESUME_SYM":
        sym = fields.get("SYM", "")
        if not sym:
            console.print("[yellow]Usage:[/yellow]  RESUME_SYM|SYM=<sym>")
            return False
        result = client.symbol_resume(sym)
        if result.get("accepted"):
            console.print(
                f"[bold green]RESUMED[/bold green]  {result.get('symbol', sym)}"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "CANCEL_SYM":
        sym = fields.get("SYM", "")
        if not sym:
            console.print("[yellow]Usage:[/yellow]  CANCEL_SYM|SYM=<sym>")
            return False
        result = client.cancel_symbol(sym)
        if result.get("accepted"):
            console.print(
                f"[yellow]CANCEL_SYM OK[/yellow]  {result.get('symbol', sym)}  "
                f"orders={result.get('cancelled_orders', 0)}  "
                f"quotes={result.get('cancelled_quotes', 0)}"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "KILL":
        gw = fields.get("GW", "")
        if not gw:
            console.print("[yellow]Usage:[/yellow]  KILL|GW=<gw>[|SYM=<sym>]")
            return False
        result = client.kill_switch(gw, symbol=fields.get("SYM", ""))
        if result.get("accepted"):
            console.print(
                f"[yellow]KILL OK[/yellow]  {gw.upper()}  "
                f"orders={result.get('cancelled_orders', 0)}  "
                f"quotes={result.get('cancelled_quotes', 0)}"
            )
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "KICK":
        gw = fields.get("GW", "")
        if not gw:
            console.print("[yellow]Usage:[/yellow]  KICK|GW=<gw>[|REASON=<text>]")
            return False
        client.gateway_kick(gw, reason=fields.get("REASON", ""))
        console.print(f"[yellow]KICK[/yellow]  sent disconnect for {gw.upper()}")
        return True

    elif cmd == "QCANCEL":
        gw = fields.get("GW", "")
        sym = fields.get("SYM", "")
        if not gw or not sym:
            console.print("[yellow]Usage:[/yellow]  QCANCEL|GW=<gw>|SYM=<sym>")
            return False
        result = client.quote_cancel(gw, sym)
        if result.get("accepted"):
            console.print(f"[yellow]QCANCEL OK[/yellow]  {gw.upper()}  {sym.upper()}")
        else:
            console.print(f"[red]REJECTED[/red]  {result.get('reason', '')}")
        return bool(result.get("accepted"))

    elif cmd == "BOOK":
        sym = fields.get("SYM", "")
        if not sym:
            console.print("[yellow]Usage:[/yellow]  BOOK|SYM=<sym>")
            return False
        _print_book(client.book_depth(sym))
        return True

    elif cmd == "ORDERS":
        gw = fields.get("GW", "")
        if not gw:
            console.print("[yellow]Usage:[/yellow]  ORDERS|GW=<gw>")
            return False
        _print_orders(client.order_list(gw), gw.upper())
        return True

    elif cmd == "SYMBOLS":
        symbols = client.symbol_list()
        if symbols_cache is not None:
            symbols_cache.clear()
            symbols_cache.extend(symbols)
        _print_symbols(symbols)
        return True

    elif cmd == "SESSION":
        state = fields.get("STATE", "")
        if not state:
            console.print("[yellow]Usage:[/yellow]  SESSION|STATE=<state>")
            return False
        result = client.session_advance(state)
        console.print(
            f"[bold]SESSION[/bold]  "
            f"{result.get('prev_state', '?')} → {result.get('state', '?')}"
        )
        return True
    elif cmd == "SESSION_STATUS":
        _print_session_status(client.session_status())
        return True

    elif cmd == "SCHEDULE":
        _print_schedule(client.session_schedule())
        return True

    elif cmd == "GATEWAYS":
        _print_gateways(client.gateway_list())
        return True

    elif cmd == "VOLUME":
        _print_volume(client.volume())
        return True
    else:
        console.print(
            f"[dim]Unknown command '{cmd}'.  Type HELP for the command reference.[/dim]"
        )
        return False


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


def main() -> None:
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
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="ADMIN gateway ID (e.g. GW_ADMIN)",
    )
    args = parser.parse_args()
    AdminConsole(args.id).run()


if __name__ == "__main__":
    main()
