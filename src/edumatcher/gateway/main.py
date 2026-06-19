"""
Gateway — user-facing terminal process.

Usage:
  poetry run pm-gateway --id GW01

Accepts FIX-like text commands on stdin, sends to engine, prints responses.

Commands
--------
  NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50|TIF=GTC
  NEW|SYM=MSFT|SIDE=SELL|TYPE=MARKET|QTY=50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP|QTY=100|STOP=148.00
  NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
  NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00|VISIBLE=100
  AMEND|ID=ORD-xxxx|PRICE=151.00
  AMEND|ID=ORD-xxxx|QTY=200
  AMEND|ID=ORD-xxxx|PRICE=151.00|QTY=200
  CANCEL|ID=ORD-xxxx
    STATUS                 — print gateway/session summary
  ORDERS                 — print table of this session's orders
  HELP                   — show command reference
  EXIT / QUIT            — disconnect
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import zmq
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table

from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_PUB_ADDR


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


from edumatcher.messaging.bus import make_pusher, make_subscriber  # noqa: E402
from edumatcher.models.message import (  # noqa: E402
    decode,
    make_combo_cancel_msg,
    make_combo_order_msg,
    make_gateway_connect_msg,
    make_gateway_disconnect_msg,
    make_kill_switch_msg,
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_request_msg,
    make_quote_bootstrap_request_msg,
    make_quote_cancel_msg,
    make_quote_new_msg,
    make_symbols_request_msg,
    make_oco_order_msg,
    make_oco_cancel_msg,
)
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType  # noqa: E402
from edumatcher.models.order import (  # noqa: E402
    Order,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.price import to_ticks  # noqa: E402

# force_terminal=True so rich always emits ANSI even through the proxy.
console = Console(file=_SysStdoutProxy(), force_terminal=True)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Tab-completion
# ---------------------------------------------------------------------------

_TOP_LEVEL_CMDS = [
    "NEW",
    "QUOTE",
    "QUOTE_CANCEL",
    "QBOOT",
    "QLEGS",
    "KILL",
    "AMEND",
    "CANCEL",
    "STATUS",
    "ORDERS",
    "POS",
    "SYMBOLS",
    "HELP",
    "EXIT",
    "QUIT",
]

_FIELD_COMPLETIONS: dict[str, list[str]] = {
    # after NEW|
    "SYM": [],  # populated dynamically from known symbols
    "SIDE": ["BUY", "SELL"],
    "TYPE": [
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "FOK",
        "ICEBERG",
        "IOC",
        "TRAILING_STOP",
    ],
    "TIF": ["DAY", "GTC", "ATO", "ATC"],
    "QTY": [],
    "PRICE": [],
    "STOP": [],
    "TRAIL": [],
    "VISIBLE": [],
    "SMP": ["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"],
    # after CANCEL|
    "ID": [],
}

# Fields that follow each order type (in typical order)
_TYPE_FIELDS: dict[str, list[str]] = {
    "MARKET": ["SYM=", "SIDE=", "QTY=", "TIF=", "SMP="],
    "LIMIT": ["SYM=", "SIDE=", "QTY=", "PRICE=", "TIF=", "SMP="],
    "STOP": ["SYM=", "SIDE=", "QTY=", "STOP=", "TIF=", "SMP="],
    "STOP_LIMIT": ["SYM=", "SIDE=", "QTY=", "STOP=", "PRICE=", "TIF=", "SMP="],
    "FOK": ["SYM=", "SIDE=", "QTY=", "PRICE=", "SMP="],
    "ICEBERG": ["SYM=", "SIDE=", "QTY=", "PRICE=", "VISIBLE=", "TIF=", "SMP="],
    "IOC": ["SYM=", "SIDE=", "QTY=", "PRICE=", "SMP="],
    "TRAILING_STOP": ["SYM=", "SIDE=", "QTY=", "TRAIL=", "STOP=", "TIF="],
}


class GatewayCompleter(Completer):
    """
    Context-aware tab completer for the FIX-like command format.

    Completion rules:
      - Empty or partial first word → top-level commands
      - After NEW|  or CANCEL| → suggest untyped field names (KEY=)
      - After KEY=  with known values → suggest values
    """

    def __init__(self, known_symbols: list[str]) -> None:
        self.known_symbols = known_symbols  # updated by gateway on SYMBOLS reply

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        parts = text.split("|")
        current = parts[-1]  # fragment being typed right now

        # ---- Top-level command (first segment, no | yet) ----
        if len(parts) == 1:
            word = current.upper()
            for cmd in _TOP_LEVEL_CMDS:
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(current))
            return

        cmd = parts[0].upper()
        already_keys = {seg.split("=")[0].upper() for seg in parts[1:] if "=" in seg}

        # ---- Value completion: cursor is after KEY= ----
        if "=" in current:
            key, partial_val = current.split("=", 1)
            key = key.upper()
            partial_val_up = partial_val.upper()

            # Strip LEG{i}. prefix for combo leg field value suggestions
            field = key.split(".")[-1] if "." in key else key

            if field == "SYM":
                candidates = self.known_symbols
            elif field == "SIDE":
                candidates = ["BUY", "SELL"]
            elif key == "TYPE":
                candidates = list(_TYPE_FIELDS.keys()) + ["COMBO", "OCO"]
            elif field == "TYPE":
                # LEG{i}.TYPE= values
                candidates = ["LIMIT", "MARKET", "STOP", "STOP_LIMIT"]
            elif key == "TIF":
                candidates = ["DAY", "GTC", "ATO", "ATC"]
            elif key == "COMBO_TYPE":
                candidates = ["AON"]
            elif cmd == "QLEGS" and key == "SHOW":
                candidates = ["ACTIVE", "RECENT", "ALL"]
            elif field == "SMP" or key == "SMP":
                candidates = [
                    "NONE",
                    "CANCEL_AGGRESSOR",
                    "CANCEL_RESTING",
                    "CANCEL_BOTH",
                ]
            else:
                candidates = []

            for val in candidates:
                if val.upper().startswith(partial_val_up):
                    yield Completion(val, start_position=-len(partial_val))
            return

        # ---- Field-name completion: cursor is at start of a new segment ----
        partial_key = current.upper()

        if cmd == "CANCEL":
            candidates = [
                f
                for f in ["ID=", "COMBO_ID=", "OCO_ID="]
                if f.rstrip("=") not in already_keys
            ]
        elif cmd == "QLEGS":
            candidates = [
                f for f in ["SYM=", "SHOW="] if f.rstrip("=") not in already_keys
            ]
        elif cmd == "QBOOT":
            candidates = [f for f in ["SYM="] if f.rstrip("=") not in already_keys]
        elif cmd == "AMEND":
            candidates = [
                f
                for f in ["ID=", "PRICE=", "QTY="]
                if f.rstrip("=") not in already_keys
            ]
        elif cmd == "NEW":
            # Infer order type from already-entered TYPE= field
            type_val = next(
                (
                    seg.split("=", 1)[1].upper()
                    for seg in parts[1:]
                    if seg.upper().startswith("TYPE=")
                ),
                None,
            )
            if type_val == "COMBO":
                candidates = self._combo_completions(parts, already_keys, partial_key)
                for c in candidates:
                    if c.upper().startswith(partial_key):
                        yield Completion(c, start_position=-len(current))
                return
            elif type_val and type_val in _TYPE_FIELDS:
                candidates = [
                    f
                    for f in _TYPE_FIELDS[type_val]
                    if f.rstrip("=") not in already_keys
                ]
            else:
                # Before TYPE is known, suggest all field names
                candidates = [
                    f"{k}=" for k in _FIELD_COMPLETIONS if k not in already_keys
                ]
        else:
            candidates = []

        for c in candidates:
            if c.upper().startswith(partial_key):
                yield Completion(c, start_position=-len(current))

    @staticmethod
    def _combo_completions(
        parts: list[str], already_keys: set[str], partial_key: str
    ) -> list[str]:
        """Generate completion candidates for TYPE=COMBO fields."""
        # Top-level combo fields
        combo_meta = ["COMBO_ID=", "COMBO_TYPE=", "TIF=", "LEG_COUNT=", "SMP="]
        candidates = [f for f in combo_meta if f.rstrip("=") not in already_keys]

        # Determine LEG_COUNT to know how many legs to suggest
        leg_count = 2  # default suggestion range
        for seg in parts[1:]:
            if seg.upper().startswith("LEG_COUNT="):
                try:
                    leg_count = int(seg.split("=", 1)[1])
                except ValueError:
                    pass
                break

        # Collect already-used LEG{i}.FIELD keys (with dots)
        already_leg_keys = {
            seg.split("=", 1)[0].upper() for seg in parts[1:] if "=" in seg
        }

        leg_fields = ["SYM=", "SIDE=", "QTY=", "PRICE=", "TYPE="]
        for i in range(leg_count):
            for field in leg_fields:
                key = f"LEG{i}.{field}"
                if key.rstrip("=") not in already_leg_keys:
                    candidates.append(key)

        return candidates


_PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "bold ansigreen",
    }
)

_HELP_TEXT = """
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
  HELP        — this message
  EXIT / QUIT — disconnect
"""


class Gateway:
    def __init__(self, gateway_id: str) -> None:
        self.gateway_id = gateway_id.upper()
        self.order_cache: dict[str, dict[str, Any]] = {}  # order_id → state dict
        self.quote_leg_cache: dict[str, dict[str, Any]] = (
            {}
        )  # order_id → quote leg state
        self._quote_id_by_order_id: dict[str, str] = {}  # order_id → quote_id
        self._known_symbols: list[str] = []
        self._known_symbol_meta: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, dict[str, Any]] = (
            {}
        )  # symbol → {net_qty, avg_cost, realized_pnl}
        self._last_prices: dict[str, float] = {}  # symbol → last trade price
        self._running = True

        self.push_sock = make_pusher(ENGINE_PULL_ADDR)
        # Subscribe to all order events for this gateway + trade feed for last prices
        self.sub_sock = make_subscriber(
            ENGINE_PUB_ADDR,
            f"order.ack.{self.gateway_id}",
            f"order.fill.{self.gateway_id}",
            f"order.amended.{self.gateway_id}",
            f"order.cancelled.{self.gateway_id}",
            f"order.expired.{self.gateway_id}",
            f"order.orders.{self.gateway_id}",
            f"combo.ack.{self.gateway_id}",
            f"combo.status.{self.gateway_id}",
            f"oco.ack.{self.gateway_id}",
            f"oco.cancelled.{self.gateway_id}",
            f"quote.ack.{self.gateway_id}",
            f"quote.status.{self.gateway_id}",
            f"risk.kill_switch_ack.{self.gateway_id}",
            f"system.symbols.{self.gateway_id}",
            f"system.quote_bootstrap.{self.gateway_id}",
            f"system.gateway_auth.{self.gateway_id}",
            "trade.executed",
        )
        self._auth_reason: str = ""
        self._auth_description: str = ""

    # ------------------------------------------------------------------
    # Quote-leg tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _is_active_leg_status(status: str) -> bool:
        return status in {"NEW", "PARTIAL", "PENDING"}

    def _upsert_quote_leg(
        self,
        *,
        order_id: str,
        quote_id: str,
        symbol: str,
        leg_side: str,
        quantity: int,
        remaining_qty: int,
        status: str,
        event_time: str,
        quote_status: str = "",
    ) -> None:
        existing = self.quote_leg_cache.get(order_id, {})
        filled_qty = max(0, quantity - remaining_qty)
        self.quote_leg_cache[order_id] = {
            "order_id": order_id,
            "quote_id": quote_id,
            "symbol": symbol,
            "leg_side": leg_side,
            "qty": quantity,
            "remaining": remaining_qty,
            "filled": filled_qty,
            "status": status,
            "quote_status": quote_status or str(existing.get("quote_status", "")),
            "last_event_time": event_time,
        }
        self._quote_id_by_order_id[order_id] = quote_id

    def _mark_quote_status(
        self, quote_id: str, quote_status: str, event_time: str
    ) -> None:
        for row in self.quote_leg_cache.values():
            if row.get("quote_id") != quote_id:
                continue
            row["quote_status"] = quote_status
            row["last_event_time"] = event_time
            if quote_status == "CANCELLED" and self._is_active_leg_status(
                str(row.get("status", ""))
            ):
                row["status"] = "CANCELLED"
                row["remaining"] = 0

    def _record_fill_for_quote_leg(
        self,
        *,
        order_id: str,
        fill_qty: int,
        remaining_qty: int,
        status: str,
        symbol: str,
        side: str,
        qty: int | None,
        event_time: str,
    ) -> None:
        if order_id in self.quote_leg_cache:
            row = self.quote_leg_cache[order_id]
            row["remaining"] = remaining_qty
            row["status"] = status
            row["filled"] = int(row.get("filled", 0)) + fill_qty
            if qty is not None and int(row.get("qty", 0)) <= 0:
                row["qty"] = qty
            row["last_event_time"] = event_time
            return

        quote_id = self._quote_id_by_order_id.get(order_id, "?")
        base_qty = qty if qty is not None else fill_qty + max(0, remaining_qty)
        self._upsert_quote_leg(
            order_id=order_id,
            quote_id=quote_id,
            symbol=symbol,
            leg_side=side,
            quantity=base_qty,
            remaining_qty=remaining_qty,
            status=status,
            event_time=event_time,
        )
        self.quote_leg_cache[order_id]["filled"] = fill_qty

    def _print_quote_legs(self, symbol: str | None, show: str) -> None:
        rows = list(self.quote_leg_cache.values())
        if symbol:
            rows = [r for r in rows if str(r.get("symbol", "")).upper() == symbol]

        if show == "ACTIVE":
            rows = [
                r
                for r in rows
                if self._is_active_leg_status(str(r.get("status", "")))
                or int(r.get("remaining", 0)) > 0
            ]
        elif show == "RECENT":
            rows = [
                r
                for r in rows
                if not self._is_active_leg_status(str(r.get("status", "")))
                and int(r.get("remaining", 0)) <= 0
            ]

        if not rows:
            console.print("[dim]No quote legs match this filter.[/dim]")
            return

        rows.sort(key=lambda r: str(r.get("last_event_time", "")), reverse=True)

        title = f"Quote legs — {self.gateway_id}  (show={show}"
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

    def _print_quote_bootstrap(self, quotes: list[dict[str, Any]]) -> None:
        if not quotes:
            console.print("[dim]No active quote bootstrap entries returned.[/dim]")
            return

        t = Table(
            title=f"Quote bootstrap - {self.gateway_id}",
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

    def _print_symbols_table(
        self, symbols: list[str], symbol_meta: dict[str, dict[str, Any]]
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

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        # Give sockets time to connect and SUB filters to propagate.
        time.sleep(0.1)
        self.push_sock.send_multipart(make_gateway_connect_msg(self.gateway_id))

        poller = zmq.Poller()
        poller.register(self.sub_sock, zmq.POLLIN)
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            socks = dict(poller.poll(timeout=min(remaining_ms, 200)))
            if self.sub_sock not in socks:
                continue
            frames = self.sub_sock.recv_multipart()
            topic, payload = decode(frames)
            if topic == f"system.gateway_auth.{self.gateway_id}":
                accepted = bool(payload.get("accepted", False))
                self._auth_reason = str(payload.get("reason", ""))
                self._auth_description = str(payload.get("description", ""))
                return accepted
            # Ignore unrelated early messages during handshake window.
        self._auth_reason = "Gateway authentication timed out"
        return False

    # ------------------------------------------------------------------
    # Background SUB listener
    # ------------------------------------------------------------------

    def _listen(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub_sock, zmq.POLLIN)
        while self._running:
            socks = dict(poller.poll(timeout=200))
            if self.sub_sock in socks:
                frames = self.sub_sock.recv_multipart()
                topic, payload = decode(frames)
                self._handle_event(topic, payload)

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        oid = payload.get("order_id", "?")[:8]

        if "order.ack" in topic:
            if payload.get("accepted"):
                console.print(f"[{ts}] [green]ACK[/green]       {oid}  order accepted")
                # Register in cache
                full_id = payload.get("order_id", "?")
                if full_id in self.order_cache:
                    self.order_cache[full_id]["status"] = "NEW"
            else:
                reason = payload.get("reason", "")
                console.print(f"[{ts}] [red]REJECTED[/red]  {oid}  {reason}")
                full_id = payload.get("order_id", "?")
                if full_id in self.order_cache:
                    self.order_cache[full_id]["status"] = "REJECTED"

        elif "order.fill" in topic:
            qty = payload.get("fill_qty")
            price = payload.get("fill_price")
            rem = payload.get("remaining_qty")
            status = payload.get("status")
            console.print(
                f"[{ts}] [cyan]FILL[/cyan]      {oid}  qty={qty} @{price}  remaining={rem}  [{status}]"
            )
            full_id = payload.get("order_id", "?")
            if full_id in self.order_cache:
                self.order_cache[full_id]["status"] = status
                self.order_cache[full_id]["remaining"] = rem
            # Update position tracker
            symbol = payload.get("symbol")
            side = payload.get("side")
            if symbol and side and qty and price:
                self._update_position(symbol, side, qty, price)

            if (
                isinstance(qty, int)
                and isinstance(rem, int)
                and isinstance(status, str)
                and isinstance(symbol, str)
                and isinstance(side, str)
            ):
                qty_total = payload.get("qty")
                self._record_fill_for_quote_leg(
                    order_id=payload.get("order_id", "?"),
                    fill_qty=qty,
                    remaining_qty=rem,
                    status=status,
                    symbol=symbol,
                    side=side,
                    qty=qty_total if isinstance(qty_total, int) else None,
                    event_time=ts,
                )

        elif "order.cancelled" in topic:
            console.print(f"[{ts}] [yellow]CANCELLED[/yellow] {oid}")
            full_id = payload.get("order_id", "?")
            if full_id in self.order_cache:
                self.order_cache[full_id]["status"] = "CANCELLED"
            if full_id in self.quote_leg_cache:
                self.quote_leg_cache[full_id]["status"] = "CANCELLED"
                self.quote_leg_cache[full_id]["remaining"] = 0
                self.quote_leg_cache[full_id]["last_event_time"] = ts

        elif "order.amended" in topic:
            new_price = payload.get("price")
            new_qty = payload.get("qty")
            rem = payload.get("remaining_qty")
            prio = (
                " [dim](priority reset)[/dim]" if payload.get("priority_reset") else ""
            )
            console.print(
                f"[{ts}] [magenta]AMENDED[/magenta]   {oid}  "
                f"price={new_price} qty={new_qty} remaining={rem}{prio}"
            )
            full_id = payload.get("order_id", "?")
            if full_id in self.order_cache:
                self.order_cache[full_id]["price"] = new_price
                self.order_cache[full_id]["qty"] = new_qty
                self.order_cache[full_id]["remaining"] = rem

        elif "order.expired" in topic:
            console.print(
                f"[{ts}] [dim]EXPIRED[/dim]   {oid}  (DAY order — trading day ended)"
            )
            full_id = payload.get("order_id", "?")
            if full_id in self.order_cache:
                self.order_cache[full_id]["status"] = "EXPIRED"

        elif "system.symbols" in topic:
            symbols = payload.get("symbols", [])
            symbol_meta = payload.get("symbol_meta", {})
            # Update completer's known symbols list
            self._known_symbols.clear()
            self._known_symbols.extend(symbols)
            self._known_symbol_meta = (
                symbol_meta if isinstance(symbol_meta, dict) else {}
            )
            if symbols:
                self._print_symbols_table(symbols, self._known_symbol_meta)
            else:
                console.print(
                    "[dim]No active instruments yet — submit an order to create a book.[/dim]"
                )

        elif "system.quote_bootstrap" in topic:
            quotes = payload.get("quotes", [])
            if isinstance(quotes, list):
                self._print_quote_bootstrap(quotes)
            else:
                console.print("[red]Malformed quote bootstrap response.[/red]")

        elif "order.orders" in topic:
            orders = payload.get("orders", [])
            for od in orders:
                oid = od["id"]
                if oid not in self.order_cache:
                    ts = datetime.fromtimestamp(od["timestamp"]).strftime("%H:%M:%S")
                    self.order_cache[oid] = {
                        "id": oid,
                        "symbol": od["symbol"],
                        "side": od["side"],
                        "type": od["order_type"],
                        "tif": od["tif"],
                        "qty": od["quantity"],
                        "remaining": od["remaining_qty"],
                        "price": od["price"],
                        "status": od["status"],
                        "time": ts,
                    }

                if od.get("origin") == "QUOTE":
                    quote_id = str(od.get("quote_id") or "?")
                    symbol = str(od.get("symbol") or "?")
                    leg_side = str(od.get("side") or "?")
                    quantity = int(od.get("quantity") or 0)
                    remaining = int(od.get("remaining_qty") or 0)
                    status = str(od.get("status") or "NEW")
                    self._upsert_quote_leg(
                        order_id=oid,
                        quote_id=quote_id,
                        symbol=symbol,
                        leg_side=leg_side,
                        quantity=quantity,
                        remaining_qty=remaining,
                        status=status,
                        event_time=ts,
                    )

        elif "combo.ack" in topic:
            cid = payload.get("combo_id", "?")
            if payload.get("accepted"):
                console.print(f"[{ts}] [green]COMBO ACK[/green]  {cid}  combo accepted")
            else:
                reason = payload.get("reason", "")
                console.print(f"[{ts}] [red]COMBO REJ[/red]  {cid}  {reason}")

        elif "combo.status" in topic:
            cid = payload.get("combo_id", "?")
            status = payload.get("status", "?")
            details = payload.get("details", {})
            reason = details.get("reason", "") if details else ""
            colour_map = {
                "MATCHED": "bright_green",
                "PARTIALLY_MATCHED": "yellow",
                "FAILED": "red",
                "CANCELLED": "red",
            }
            colour = colour_map.get(status, "white")
            msg = f"[{ts}] [{colour}]COMBO {status}[/{colour}]  {cid}"
            if reason:
                msg += f"  {reason}"
            console.print(msg)

        elif "oco.ack" in topic:
            oco_id = payload.get("oco_id", "?")
            if payload.get("accepted"):
                id1 = payload.get("order_id_1", "")[:8]
                id2 = payload.get("order_id_2", "")[:8]
                console.print(
                    f"[{ts}] [green]OCO ACK[/green]    {oco_id}  legs={id1}/{id2}"
                )
            else:
                reason = payload.get("reason", "")
                console.print(f"[{ts}] [red]OCO REJ[/red]    {oco_id}  {reason}")

        elif "oco.cancelled" in topic:
            oco_id = payload.get("oco_id", "?")
            sibling = payload.get("cancelled_order_id", "?")[:8]
            reason = payload.get("reason", "")
            console.print(
                f"[{ts}] [yellow]OCO CANCEL[/yellow] {oco_id}  sibling={sibling}  {reason}"
            )

        elif "quote.ack" in topic:
            quote_id = payload.get("quote_id", "?")
            if payload.get("accepted"):
                bid_id = payload.get("bid_order_id", "")[:8]
                ask_id = payload.get("ask_order_id", "")[:8]
                console.print(
                    f"[{ts}] [green]QUOTE ACK[/green]  {quote_id}  bid={bid_id} ask={ask_id}"
                )

                full_bid = payload.get("bid_order_id", "")
                full_ask = payload.get("ask_order_id", "")
                if isinstance(full_bid, str) and full_bid:
                    self._quote_id_by_order_id[full_bid] = str(quote_id)
                    if full_bid in self.quote_leg_cache:
                        self.quote_leg_cache[full_bid]["quote_id"] = str(quote_id)
                        self.quote_leg_cache[full_bid]["leg_side"] = "BUY"
                    else:
                        self._upsert_quote_leg(
                            order_id=full_bid,
                            quote_id=str(quote_id),
                            symbol="?",
                            leg_side="BUY",
                            quantity=0,
                            remaining_qty=0,
                            status="PENDING",
                            event_time=ts,
                        )

                if isinstance(full_ask, str) and full_ask:
                    self._quote_id_by_order_id[full_ask] = str(quote_id)
                    if full_ask in self.quote_leg_cache:
                        self.quote_leg_cache[full_ask]["quote_id"] = str(quote_id)
                        self.quote_leg_cache[full_ask]["leg_side"] = "SELL"
                    else:
                        self._upsert_quote_leg(
                            order_id=full_ask,
                            quote_id=str(quote_id),
                            symbol="?",
                            leg_side="SELL",
                            quantity=0,
                            remaining_qty=0,
                            status="PENDING",
                            event_time=ts,
                        )
            else:
                console.print(
                    f"[{ts}] [red]QUOTE REJ[/red]  {quote_id}  {payload.get('reason', '')}"
                )

        elif "quote.status" in topic:
            quote_id = payload.get("quote_id", "?")
            status = payload.get("status", "?")
            reason = payload.get("reason", "")
            msg = f"[{ts}] [cyan]QUOTE {status}[/cyan]  {quote_id}"
            if reason:
                msg += f"  {reason}"
            console.print(msg)
            self._mark_quote_status(str(quote_id), str(status), ts)

        elif "risk.kill_switch_ack" in topic:
            if payload.get("accepted"):
                console.print(
                    f"[{ts}] [yellow]KILL ACK[/yellow]  orders={payload.get('cancelled_orders', 0)} "
                    f"quote_legs={payload.get('cancelled_quotes', 0)}"
                )
            else:
                console.print(
                    f"[{ts}] [red]KILL REJ[/red]  {payload.get('reason', '')}"
                )

        elif "trade.executed" in topic:
            # Track last price per symbol for unrealized P&L
            symbol = payload.get("symbol")
            price = payload.get("price")
            if symbol and price:
                self._last_prices[symbol] = price

    # ------------------------------------------------------------------
    # Position tracking
    # ------------------------------------------------------------------

    def _update_position(
        self, symbol: str, side: str, fill_qty: int, fill_price: float
    ) -> None:
        """Update position after a fill. Uses average cost accounting."""
        pos = self._positions.setdefault(
            symbol, {"net_qty": 0, "avg_cost": 0.0, "realized_pnl": 0.0}
        )
        signed_qty = fill_qty if side == "BUY" else -fill_qty
        old_qty = pos["net_qty"]
        new_qty = old_qty + signed_qty

        # Realize P&L when reducing or flipping position
        if old_qty != 0 and (
            (old_qty > 0 and signed_qty < 0) or (old_qty < 0 and signed_qty > 0)
        ):
            close_qty = min(abs(signed_qty), abs(old_qty))
            pnl_per_unit = (
                (fill_price - pos["avg_cost"])
                if old_qty > 0
                else (pos["avg_cost"] - fill_price)
            )
            pos["realized_pnl"] += pnl_per_unit * close_qty

        # Update average cost
        if new_qty == 0:
            pos["avg_cost"] = 0.0
        elif (old_qty >= 0 and signed_qty > 0) or (old_qty <= 0 and signed_qty < 0):
            # Adding to position — weighted average
            total_cost = pos["avg_cost"] * abs(old_qty) + fill_price * abs(signed_qty)
            pos["avg_cost"] = total_cost / abs(new_qty)
        elif abs(new_qty) > abs(old_qty):
            # Flipped through zero — new avg cost is the fill price
            pos["avg_cost"] = fill_price

        pos["net_qty"] = new_qty

    def _print_positions(self) -> None:
        """Display current positions with P&L."""
        active = {s: p for s, p in self._positions.items() if p["net_qty"] != 0}
        flat = {
            s: p
            for s, p in self._positions.items()
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
            last = self._last_prices.get(symbol)
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

    # ------------------------------------------------------------------
    # Command parser
    # ------------------------------------------------------------------

    def _parse_and_send(self, line: str) -> None:
        parts = line.strip().split("|")
        cmd = parts[0].upper()

        if cmd == "HELP":
            console.print(_HELP_TEXT)
            return

        if cmd in ("EXIT", "QUIT"):
            self._running = False
            return

        if cmd == "STATUS":
            self._print_status()
            return

        if cmd == "ORDERS":
            self._print_orders()
            return

        if cmd == "QLEGS":
            kv = self._kv(parts[1:])
            symbol = kv.get("SYM")
            show = kv.get("SHOW", "ACTIVE").upper()
            if show not in {"ACTIVE", "RECENT", "ALL"}:
                console.print("[red]QLEGS SHOW must be ACTIVE, RECENT, or ALL[/red]")
                return
            self._print_quote_legs(symbol=symbol, show=show)
            return

        if cmd == "QBOOT":
            kv = self._kv(parts[1:])
            symbol = kv.get("SYM", "")
            self.push_sock.send_multipart(
                make_quote_bootstrap_request_msg(self.gateway_id, symbol)
            )
            return

        if cmd == "POS":
            self._print_positions()
            return

        if cmd == "SYMBOLS":
            self.push_sock.send_multipart(make_symbols_request_msg(self.gateway_id))
            return

        if cmd == "QUOTE":
            kv = self._kv(parts[1:])
            self._send_quote(kv)
            return

        if cmd == "QUOTE_CANCEL":
            kv = self._kv(parts[1:])
            symbol = kv.get("SYM")
            if not symbol:
                console.print("[red]QUOTE_CANCEL requires SYM=<symbol>[/red]")
                return
            self.push_sock.send_multipart(
                make_quote_cancel_msg(self.gateway_id, symbol)
            )
            return

        if cmd == "KILL":
            kv = self._kv(parts[1:])
            self.push_sock.send_multipart(
                make_kill_switch_msg(self.gateway_id, kv.get("SYM", ""))
            )
            return

        if cmd == "CANCEL":
            kv = self._kv(parts[1:])
            combo_id = kv.get("COMBO_ID")
            if combo_id:
                self.push_sock.send_multipart(
                    make_combo_cancel_msg(combo_id, self.gateway_id)
                )
                return
            oco_id = kv.get("OCO_ID")
            if oco_id:
                self.push_sock.send_multipart(
                    make_oco_cancel_msg(oco_id, self.gateway_id)
                )
                return
            order_id = kv.get("ID")
            if not order_id:
                console.print("[red]CANCEL requires ID=, COMBO_ID=, or OCO_ID=[/red]")
                return
            self.push_sock.send_multipart(
                make_order_cancel_msg(order_id, self.gateway_id)
            )
            return

        if cmd == "AMEND":
            kv = self._kv(parts[1:])
            order_id = kv.get("ID")
            if not order_id:
                console.print("[red]AMEND requires ID=<order-id>[/red]")
                return
            new_price = float(kv["PRICE"]) if "PRICE" in kv else None
            new_qty = int(kv["QTY"]) if "QTY" in kv else None
            if new_price is None and new_qty is None:
                console.print("[red]AMEND requires at least PRICE= or QTY=[/red]")
                return
            self.push_sock.send_multipart(
                make_order_amend_msg(
                    order_id, self.gateway_id, price=new_price, qty=new_qty
                )
            )
            return

        if cmd == "NEW":
            kv = self._kv(parts[1:])
            if kv.get("TYPE") == "COMBO":
                self._send_combo(kv)
            elif kv.get("TYPE") == "OCO":
                self._send_oco(kv)
            else:
                self._send_new(parts[1:])
            return

        console.print(f"[red]Unknown command: {cmd}[/red]  (type HELP)")

    @staticmethod
    def _kv(parts: list[str]) -> dict[str, str]:
        kv: dict[str, str] = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                kv[k.upper()] = v.upper()
        return kv

    def _send_new(self, parts: list[str]) -> None:
        kv = self._kv(parts)
        try:
            symbol = kv["SYM"]
            side = Side(kv["SIDE"])
            order_type = OrderType(kv["TYPE"])
            quantity = int(kv["QTY"])
            tif = TIF(kv.get("TIF", "DAY"))
            price = float(kv["PRICE"]) if "PRICE" in kv else None
            stop_price = float(kv["STOP"]) if "STOP" in kv else None
            visible = int(kv["VISIBLE"]) if "VISIBLE" in kv else None
            smp_action = SmpAction(kv.get("SMP", SmpAction.NONE))
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Parse error: {exc}[/red]")
            return

        # Validation
        if (
            order_type
            in (OrderType.LIMIT, OrderType.FOK, OrderType.ICEBERG, OrderType.IOC)
            and price is None
        ):
            console.print("[red]LIMIT / FOK / ICEBERG / IOC require PRICE=[/red]")
            return
        if order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and stop_price is None:
            console.print("[red]STOP / STOP_LIMIT require STOP=[/red]")
            return
        if order_type == OrderType.STOP_LIMIT and price is None:
            console.print(
                "[red]STOP_LIMIT requires PRICE= (limit price after trigger)[/red]"
            )
            return
        if order_type == OrderType.ICEBERG and visible is None:
            console.print("[red]ICEBERG requires VISIBLE=<peak size>[/red]")
            return
        if (
            order_type == OrderType.ICEBERG
            and visible is not None
            and visible >= quantity
        ):
            console.print("[red]ICEBERG VISIBLE must be less than total QTY[/red]")
            return
        if order_type == OrderType.TRAILING_STOP:
            trail_offset_raw = kv.get("TRAIL")
            if trail_offset_raw is None:
                console.print("[red]TRAILING_STOP requires TRAIL=<offset>[/red]")
                return

        order = Order.create(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            gateway_id=self.gateway_id,
            tif=tif,
            price=to_ticks(price, symbol) if price is not None else None,
            stop_price=to_ticks(stop_price, symbol) if stop_price is not None else None,
            visible_qty=visible,
            smp_action=smp_action,
            trail_offset=(
                to_ticks(float(kv["TRAIL"]), symbol) if "TRAIL" in kv else None
            ),
        )

        # Pre-register in cache before ACK arrives
        self.order_cache[order.id] = {
            "id": order.id,
            "symbol": symbol,
            "side": side.value,
            "type": order_type.value,
            "tif": tif.value,
            "qty": quantity,
            "remaining": quantity,
            "price": price,
            "status": "PENDING",
            "time": datetime.now().strftime("%H:%M:%S"),
        }

        self.push_sock.send_multipart(make_order_new_msg(order.to_dict()))

    def _send_quote(self, kv: dict[str, str]) -> None:
        try:
            symbol = kv["SYM"]
            bid_price = float(kv["BID"])
            ask_price = float(kv["ASK"])
            bid_qty = int(kv["BID_QTY"])
            ask_qty = int(kv["ASK_QTY"])
            tif = TIF(kv.get("TIF", "DAY"))
        except (KeyError, ValueError) as exc:
            console.print(f"[red]QUOTE parse error: {exc}[/red]")
            return

        if bid_qty <= 0 or ask_qty <= 0:
            console.print("[red]QUOTE requires positive BID_QTY and ASK_QTY[/red]")
            return
        if bid_price >= ask_price:
            console.print("[red]QUOTE requires BID < ASK[/red]")
            return

        payload: dict[str, Any] = {
            "gateway_id": self.gateway_id,
            "symbol": symbol,
            "bid_price": bid_price,
            "bid_qty": bid_qty,
            "ask_price": ask_price,
            "ask_qty": ask_qty,
            "tif": tif.value,
        }
        quote_id = kv.get("QUOTE_ID")
        if quote_id:
            payload["quote_id"] = quote_id

        self.push_sock.send_multipart(make_quote_new_msg(payload))

    def _send_oco(self, kv: dict[str, str]) -> None:
        """Parse and send an OCO pair from TYPE=OCO format."""
        oco_id = kv.get("OCO_ID", "")
        symbol = kv.get("SYM", "")
        tif_str = kv.get("TIF", "DAY")

        if not oco_id:
            console.print("[red]OCO requires OCO_ID=<label>[/red]")
            return
        if not symbol:
            console.print("[red]OCO requires SYM=<symbol>[/red]")
            return

        try:
            quantity = int(kv["QTY"])
            tif_val = TIF(tif_str)
        except (KeyError, ValueError) as exc:
            console.print(f"[red]Parse error: {exc}[/red]")
            return

        def _parse_leg(prefix: str) -> dict[str, Any] | None:
            side_key = f"{prefix}SIDE"
            type_key = f"{prefix}TYPE"
            price_key = f"{prefix}PRICE"
            stop_key = f"{prefix}STOP"
            trail_key = f"{prefix}TRAIL"
            if side_key not in kv or type_key not in kv:
                return None
            leg: dict[str, Any] = {
                "side": kv[side_key],
                "order_type": kv[type_key],
            }
            if price_key in kv:
                leg["price"] = float(kv[price_key])
            if stop_key in kv:
                leg["stop_price"] = float(kv[stop_key])
            if trail_key in kv:
                leg["trail_offset"] = float(kv[trail_key])
            return leg

        leg1 = _parse_leg("LEG1_")
        leg2 = _parse_leg("LEG2_")

        if leg1 is None or leg2 is None:
            console.print(
                "[red]OCO requires LEG1_SIDE= LEG1_TYPE= LEG2_SIDE= LEG2_TYPE=[/red]"
            )
            return

        payload = {
            "oco_id": oco_id,
            "gateway_id": self.gateway_id,
            "symbol": symbol,
            "quantity": quantity,
            "tif": tif_val.value,
            "leg1": leg1,
            "leg2": leg2,
        }
        self.push_sock.send_multipart(make_oco_order_msg(payload))

    def _send_combo(self, kv: dict[str, str]) -> None:
        """Parse and send a combo order from TYPE=COMBO format."""

        combo_id = kv.get("COMBO_ID", "")
        combo_type = kv.get("COMBO_TYPE", "AON")
        tif_str = kv.get("TIF", "DAY")
        smp_str = kv.get("SMP", "NONE")

        if not combo_id:
            console.print("[red]COMBO requires COMBO_ID=<label>[/red]")
            return

        try:
            combo_type_val = ComboType(combo_type)
            tif_val = TIF(tif_str)
        except ValueError as exc:
            console.print(f"[red]Parse error: {exc}[/red]")
            return

        leg_count_str = kv.get("LEG_COUNT", "0")
        try:
            leg_count = int(leg_count_str)
        except ValueError:
            console.print(
                f"[red]LEG_COUNT must be an integer, got '{leg_count_str}'[/red]"
            )
            return

        if leg_count < 2 or leg_count > 10:
            console.print("[red]LEG_COUNT must be between 2 and 10[/red]")
            return

        legs: list[ComboLeg] = []
        for i in range(leg_count):
            prefix = f"LEG{i}"
            sym = kv.get(f"{prefix}.SYM")
            side = kv.get(f"{prefix}.SIDE")
            qty = kv.get(f"{prefix}.QTY")
            price = kv.get(f"{prefix}.PRICE")
            leg_type = kv.get(f"{prefix}.TYPE", "LIMIT")

            if not sym or not side or not qty:
                console.print(f"[red]Leg {i} missing SYM, SIDE, or QTY[/red]")
                return
            try:
                leg = ComboLeg(
                    symbol=sym,
                    side=Side(side),
                    order_type=OrderType(leg_type),
                    quantity=int(qty),
                    price=to_ticks(float(price), sym) if price else None,
                    smp_action=SmpAction(smp_str),
                )
            except (ValueError, KeyError) as exc:
                console.print(f"[red]Leg {i} parse error: {exc}[/red]")
                return
            legs.append(leg)

        combo = ComboOrder.create(
            combo_id=combo_id,
            gateway_id=self.gateway_id,
            combo_type=combo_type_val,
            tif=tif_val,
            legs=legs,
        )

        self.push_sock.send_multipart(make_combo_order_msg(combo.to_dict()))

    # ------------------------------------------------------------------
    # Gateway status summary
    # ------------------------------------------------------------------

    def _print_status(self) -> None:
        status_counts: dict[str, int] = {}
        for order in self.order_cache.values():
            status = str(order.get("status", "UNKNOWN"))
            status_counts[status] = status_counts.get(status, 0) + 1

        active_orders = sum(
            count
            for status, count in status_counts.items()
            if status in {"NEW", "PARTIAL", "PENDING"}
        )
        active_quote_legs = sum(
            1
            for leg in self.quote_leg_cache.values()
            if self._is_active_leg_status(str(leg.get("status", "")))
        )

        table = Table(title=f"Gateway status — {self.gateway_id}", show_lines=True)
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Gateway ID", self.gateway_id)
        table.add_row("Authenticated", "yes" if self._running else "no")
        table.add_row(
            "Known symbols",
            ", ".join(self._known_symbols) if self._known_symbols else "—",
        )
        table.add_row("Cached orders", str(len(self.order_cache)))
        table.add_row("Active/resting orders", str(active_orders))
        table.add_row("Cached quote legs", str(len(self.quote_leg_cache)))
        table.add_row("Active quote legs", str(active_quote_legs))
        table.add_row(
            "Position symbols",
            ", ".join(sorted(self._positions)) if self._positions else "—",
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

    # ------------------------------------------------------------------
    # ORDERS table
    # ------------------------------------------------------------------

    def _print_orders(self) -> None:
        if not self.order_cache:
            console.print("[dim]No outstanding orders for this gateway.[/dim]")
            return
        t = Table(title=f"Orders — {self.gateway_id}", show_lines=True)
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

        for o in sorted(
            self.order_cache.values(), key=lambda x: x["time"], reverse=True
        ):
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

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        if not self._authenticate():
            reason = self._auth_reason or f"Gateway not allowed: {self.gateway_id}"
            console.print(f"[red]Connection refused:[/red] {reason}")
            self._running = False
            self.push_sock.close()
            self.sub_sock.close()
            return

        # Request outstanding resting orders so reconnects restore order history
        self.push_sock.send_multipart(make_orders_request_msg(self.gateway_id))

        listener = threading.Thread(target=self._listen, daemon=True)
        listener.start()

        desc = f" — {self._auth_description}" if self._auth_description else ""
        console.print(
            f"\n[bold green]Gateway {self.gateway_id} connected.[/bold green]  "
            f"{desc} "
            f"Type [bold]HELP[/bold] for commands.  "
            f"[dim]Tab=complete  ↑↓=history  Ctrl-A/E=line start/end[/dim]\n"
        )

        completer = GatewayCompleter(self._known_symbols)
        session: PromptSession[str] = PromptSession(
            history=InMemoryHistory(),
            completer=completer,
            complete_while_typing=False,  # only complete on Tab
            style=_PROMPT_STYLE,
            mouse_support=False,
        )
        prompt_str = [("class:prompt", f"[{self.gateway_id}]> ")]

        try:
            with pt_patch_stdout(raw=True):
                while self._running:
                    try:
                        line = session.prompt(prompt_str)  # type: ignore[arg-type]
                    except (EOFError, KeyboardInterrupt):
                        break
                    if line.strip():
                        self._parse_and_send(line)
        finally:
            self._running = False
            try:
                self.push_sock.send_multipart(
                    make_gateway_disconnect_msg(self.gateway_id, reason="client_exit")
                )
            except Exception:
                pass
            self.push_sock.close()
            self.sub_sock.close()
            console.print(f"\n[bold]Gateway {self.gateway_id} disconnected.[/bold]")


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher gateway")
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="Unique gateway identifier, e.g. GW01",
    )
    args = parser.parse_args()
    Gateway(args.id).run()


if __name__ == "__main__":
    main()
