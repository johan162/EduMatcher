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
    make_order_amend_msg,
    make_order_cancel_msg,
    make_order_new_msg,
    make_orders_request_msg,
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

# force_terminal=True so rich always emits ANSI even through the proxy.
console = Console(file=_SysStdoutProxy(), force_terminal=True)  # type: ignore[arg-type]

# ---------------------------------------------------------------------------
# Tab-completion
# ---------------------------------------------------------------------------

_TOP_LEVEL_CMDS = [
    "NEW",
    "AMEND",
    "CANCEL",
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
  ORDERS      — show all outstanding orders for this gateway
  POS         — show current positions with P&L
  SYMBOLS     — list all active instruments in the engine
  HELP        — this message
  EXIT / QUIT — disconnect
"""


class Gateway:
    def __init__(self, gateway_id: str) -> None:
        self.gateway_id = gateway_id.upper()
        self.order_cache: dict[str, dict[str, Any]] = {}  # order_id → state dict
        self._known_symbols: list[str] = []
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
            f"system.symbols.{self.gateway_id}",
            f"system.gateway_auth.{self.gateway_id}",
            "trade.executed",
        )
        self._auth_reason: str = ""
        self._auth_description: str = ""

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

        elif "order.cancelled" in topic:
            console.print(f"[{ts}] [yellow]CANCELLED[/yellow] {oid}")
            full_id = payload.get("order_id", "?")
            if full_id in self.order_cache:
                self.order_cache[full_id]["status"] = "CANCELLED"

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
            # Update completer's known symbols list
            self._known_symbols.clear()
            self._known_symbols.extend(symbols)
            if symbols:
                from rich.table import Table

                t = Table(
                    title="Active Instruments",
                    show_header=True,
                    header_style="bold magenta",
                )
                t.add_column("#", style="dim", width=4)
                t.add_column("Symbol", style="bold", min_width=10)
                for i, sym in enumerate(symbols, 1):
                    t.add_row(str(i), sym)
                console.print(t)
            else:
                console.print(
                    "[dim]No active instruments yet — submit an order to create a book.[/dim]"
                )

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

        if cmd == "ORDERS":
            self._print_orders()
            return

        if cmd == "POS":
            self._print_positions()
            return

        if cmd == "SYMBOLS":
            self.push_sock.send_multipart(make_symbols_request_msg(self.gateway_id))
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
            price=price,
            stop_price=stop_price,
            visible_qty=visible,
            smp_action=smp_action,
            trail_offset=float(kv["TRAIL"]) if "TRAIL" in kv else None,
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
                    price=float(price) if price else None,
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
