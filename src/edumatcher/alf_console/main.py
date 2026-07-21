"""
Gateway — user-facing terminal process.

Usage:
  poetry run pm-alf-console --id GW01

Accepts FIX-like text commands on stdin, sends to engine, prints responses.

Commands
--------
  NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.50|TIF=GTC
  NEW|SYM=MSFT|SIDE=SELL|TYPE=MARKET|QTY=50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP|QTY=100|STOP=148.00
  NEW|SYM=AAPL|SIDE=BUY|TYPE=STOP_LIMIT|QTY=100|STOP=148.00|PRICE=147.50
  NEW|SYM=AAPL|SIDE=BUY|TYPE=FOK|QTY=100|PRICE=150.00
  NEW|SYM=AAPL|SIDE=BUY|TYPE=IOC|QTY=100|PRICE=150.00
  NEW|SYM=AAPL|SIDE=BUY|TYPE=ICEBERG|QTY=1000|PRICE=150.00|VISIBLE=100
  NEW|SYM=AAPL|SIDE=BUY|TYPE=TRAILING_STOP|QTY=100|TRAIL=0.50
  NEW|TYPE=OCO|OCO_ID=<label>|SYM=AAPL|QTY=100|TIF=DAY|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=150.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=148.00
  NEW|TYPE=COMBO|COMBO_ID=<label>|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=100|LEG0.PRICE=150.00|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=50|LEG1.PRICE=300.00
  AMEND|ID=ORD-xxxx|PRICE=151.00
  AMEND|ID=ORD-xxxx|QTY=200
  AMEND|ID=ORD-xxxx|PRICE=151.00|QTY=200
  CANCEL|ID=ORD-xxxx
  CANCEL|COMBO_ID=<label>
  CANCEL|OCO_ID=<label>
  QUOTE|SYM=AAPL|BID=150.00|ASK=150.10|BID_QTY=500|ASK_QTY=500
  QUOTE_CANCEL|SYM=AAPL
  QBOOT[|SYM=AAPL]         — request active quote bootstrap state from engine
  QLEGS[|SYM=AAPL][|SHOW=ACTIVE|RECENT|ALL]  — show MM quote legs
  KILL[|SYM=AAPL]          — kill-switch cancel for this gateway
  STATUS                   — print gateway/session summary
  ORDERS                   — print table of this session's orders
  POS                      — print current positions with P&L
  SYMBOLS                  — list all active instruments in the engine
    INDEX                    — show current index level
    INDEX|HISTORY|INDEX=<id>[|FROM=YYYY-MM-DD|TO=YYYY-MM-DD] — query index structural/audit history
                                (corporate actions, constituent changes — not level ticks;
                                 use pm-stats-cli for level/EOD history)
  HELP                     — show command reference
  EXIT / QUIT              — disconnect
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import logging
import sys
import threading
import time
from datetime import datetime
from typing import Any

import zmq
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout as pt_patch_stdout

from edumatcher.cli_version import add_version_argument
from edumatcher.config import (
    ENGINE_PULL_ADDR,
    ENGINE_PUB_ADDR,
    INDEX_PUB_CONNECT_ADDR,
    INDEX_PULL_CONNECT_ADDR,
)
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import (
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
    make_index_history_request_msg,
    make_oco_order_msg,
    make_oco_cancel_msg,
)
from edumatcher.models.order import (
    Order,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.price import to_ticks

# Extracted submodules — re-exported here so that existing
# ``from edumatcher.alf_console.main import ...`` imports keep working.
from .completer import GatewayCompleter as GatewayCompleter  # noqa: F401
from .display import _SysStdoutProxy as _SysStdoutProxy  # noqa: F401  # type: ignore
from .display import (
    HELP_TEXT,
    PROMPT_STYLE,
    console,
    is_active_leg_status,
    print_current_index,
    print_index_history,
    print_orders,
    print_positions,
    print_quote_bootstrap,
    print_quote_legs,
    print_status,
    print_symbols_table,
)

_DEBUG_SUMMARY_INTERVAL_SEC = 5.0

log = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher gateway")
    add_version_argument(parser, "pm-alf-console")
    parser.add_argument(
        "--id",
        required=True,
        metavar="GW_ID",
        help="Unique gateway identifier, e.g. GW01",
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
        help="Reduce output to warnings/errors",
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
        self._last_index_update: dict[str, Any] | None = None
        self._default_index_id: str | None = None
        self._running = True
        self._authenticated: bool = False

        self.push_sock = make_pusher(ENGINE_PULL_ADDR)
        self._index_push_sock = make_pusher(INDEX_PULL_CONNECT_ADDR)
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
        self._index_sub_sock = make_subscriber(
            INDEX_PUB_CONNECT_ADDR,
            "index.update",
            f"index.history.{self.gateway_id}",
            f"index.error.{self.gateway_id}",
        )
        self._auth_reason: str = ""
        self._auth_description: str = ""
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

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
        log.debug("alf_console flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

    @staticmethod
    def _topic_family(topic: str) -> str:
        if topic.startswith("order."):
            return "order"
        if topic.startswith("combo."):
            return "combo"
        if topic.startswith("oco."):
            return "oco"
        if topic.startswith("quote."):
            return "quote"
        if topic.startswith("risk."):
            return "risk"
        if topic.startswith("system."):
            return "system"
        if topic.startswith("trade."):
            return "trade"
        if topic.startswith("index."):
            return "index"
        return "other"

    # ------------------------------------------------------------------
    # Quote-leg tracking
    # ------------------------------------------------------------------

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
            if quote_status == "CANCELLED" and is_active_leg_status(
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

    def _authenticate(self, timeout_sec: float = 3.0) -> bool:
        # Give sockets time to connect and SUB filters to propagate.
        log.info("starting gateway authentication gateway_id=%s", self.gateway_id)
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
                if accepted:
                    log.info(
                        "gateway authentication accepted gateway_id=%s", self.gateway_id
                    )
                else:
                    log.warning(
                        "gateway authentication rejected gateway_id=%s reason=%s",
                        self.gateway_id,
                        self._auth_reason,
                    )
                return accepted
            # Ignore unrelated early messages during handshake window.
        self._auth_reason = "Gateway authentication timed out"
        log.warning("gateway authentication timed out gateway_id=%s", self.gateway_id)
        return False

    # ------------------------------------------------------------------
    # Background SUB listener
    # ------------------------------------------------------------------

    def _listen(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub_sock, zmq.POLLIN)
        poller.register(self._index_sub_sock, zmq.POLLIN)
        log.info("gateway listeners started gateway_id=%s", self.gateway_id)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=200))
            except zmq.ZMQError:
                log.warning("listener poll interrupted gateway_id=%s", self.gateway_id)
                break
            if self.sub_sock in socks:
                try:
                    frames = self.sub_sock.recv_multipart()
                    topic, payload = decode(frames)
                    self._dbg_count("events_main_socket")
                    self._handle_event(topic, payload)
                except Exception as exc:
                    if self._running:
                        self._dbg_count("listener_errors")
                        log.warning(
                            "listener error gateway_id=%s: %s", self.gateway_id, exc
                        )
                        console.print(f"[dim][WARN] listener error: {exc}[/dim]")
            if self._index_sub_sock in socks:
                try:
                    frames = self._index_sub_sock.recv_multipart()
                    topic, payload = decode(frames)
                    self._dbg_count("events_index_socket")
                    self._handle_event(topic, payload)
                except Exception as exc:
                    if self._running:
                        self._dbg_count("index_listener_errors")
                        log.warning(
                            "index listener error gateway_id=%s: %s",
                            self.gateway_id,
                            exc,
                        )
                        console.print(f"[dim][WARN] index listener error: {exc}[/dim]")
        self._flush_debug_summary(force=True)
        log.info("gateway listeners stopped gateway_id=%s", self.gateway_id)

    def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        oid = payload.get("order_id", "?")[:8]
        self._dbg_count("events_total")
        self._dbg_count(f"topic_family_{self._topic_family(topic)}")

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
                if new_price is not None:
                    self.order_cache[full_id]["price"] = new_price
                if new_qty is not None:
                    self.order_cache[full_id]["qty"] = new_qty
                if rem is not None:
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
                print_symbols_table(symbols, self._known_symbol_meta)
            else:
                console.print(
                    "[dim]No active instruments yet — submit an order to create a book.[/dim]"
                )

        elif "system.quote_bootstrap" in topic:
            quotes = payload.get("quotes", [])
            if isinstance(quotes, list):
                print_quote_bootstrap(self.gateway_id, quotes)
            else:
                console.print("[red]Malformed quote bootstrap response.[/red]")

        elif "order.orders" in topic:
            orders = payload.get("orders", [])
            for od in orders:
                oid = str(od.get("id") or "")
                if not oid:
                    continue
                raw_ts = od.get("timestamp") or 0
                try:
                    ts_str = datetime.fromtimestamp(float(raw_ts)).strftime("%H:%M:%S")
                except (ValueError, OSError):
                    ts_str = "?"
                if oid in self.order_cache:
                    # Sync mutable fields from the engine's authoritative snapshot
                    self.order_cache[oid].update(
                        {
                            "qty": od.get(
                                "quantity", self.order_cache[oid].get("qty", 0)
                            ),
                            "remaining": od.get(
                                "remaining_qty",
                                self.order_cache[oid].get("remaining", 0),
                            ),
                            "price": od.get(
                                "price", self.order_cache[oid].get("price")
                            ),
                            "status": od.get(
                                "status", self.order_cache[oid].get("status", "?")
                            ),
                        }
                    )
                else:
                    self.order_cache[oid] = {
                        "id": oid,
                        "symbol": od.get("symbol", "?"),
                        "side": od.get("side", "?"),
                        "type": od.get("order_type", "?"),
                        "tif": od.get("tif", "?"),
                        "qty": od.get("quantity", 0),
                        "remaining": od.get("remaining_qty", 0),
                        "price": od.get("price"),
                        "status": od.get("status", "?"),
                        "time": ts_str,
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

        elif topic == "index.update":
            self._last_index_update = payload
            index_id = payload.get("index_id")
            if isinstance(index_id, str) and index_id:
                self._default_index_id = index_id.upper()

        elif topic == f"index.history.{self.gateway_id}":
            records = payload.get("records", [])
            if isinstance(records, list):
                print_index_history(records)
            else:
                console.print("[red]Malformed index history response.[/red]")

        elif topic == f"index.error.{self.gateway_id}":
            reason = payload.get("reason", "")
            console.print(f"[{ts}] [red]INDEX ERROR[/red] {reason}")

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

    # ------------------------------------------------------------------
    # Command parser
    # ------------------------------------------------------------------

    def _parse_and_send(self, line: str) -> None:
        parts = line.strip().split("|")
        cmd = parts[0].upper()
        self._dbg_count("commands_total")
        self._dbg_count(f"command_{cmd.lower()}")

        if cmd == "HELP":
            console.print(HELP_TEXT)
            return

        if cmd in ("EXIT", "QUIT"):
            self._running = False
            return

        if cmd == "STATUS":
            print_status(
                self.gateway_id,
                self._authenticated,
                self._known_symbols,
                self.order_cache,
                self.quote_leg_cache,
                self._positions,
            )
            return

        if cmd == "ORDERS":
            print_orders(self.gateway_id, self.order_cache)
            return

        if cmd == "QLEGS":
            kv = self._kv(parts[1:])
            symbol = kv.get("SYM")
            show = kv.get("SHOW", "ACTIVE").upper()
            if show not in {"ACTIVE", "RECENT", "ALL"}:
                console.print("[red]QLEGS SHOW must be ACTIVE, RECENT, or ALL[/red]")
                return
            print_quote_legs(self.gateway_id, self.quote_leg_cache, symbol, show)
            return

        if cmd == "QBOOT":
            kv = self._kv(parts[1:])
            symbol = kv.get("SYM", "")
            self.push_sock.send_multipart(
                make_quote_bootstrap_request_msg(self.gateway_id, symbol)
            )
            return

        if cmd == "POS":
            print_positions(self._positions, self._last_prices)
            return

        if cmd == "SYMBOLS":
            self.push_sock.send_multipart(make_symbols_request_msg(self.gateway_id))
            return

        if cmd == "INDEX":
            kv = self._kv(parts[1:])
            if len(parts) > 1 and parts[1].upper() == "HISTORY":
                index_id = kv.get("INDEX") or self._default_index_id or ""
                if not index_id:
                    console.print(
                        "[red]INDEX|HISTORY requires INDEX=<id> or prior index.update.[/red]"
                    )
                    return
                from_ts = self._parse_date(kv.get("FROM"))
                to_ts = self._parse_date(kv.get("TO"))
                if from_ts is None:
                    from_ts = time.time() - 30 * 86400
                if to_ts is None:
                    to_ts = time.time()
                self._index_push_sock.send_multipart(
                    make_index_history_request_msg(
                        gateway_id=self.gateway_id,
                        index_id=index_id,
                        from_ts=from_ts,
                        to_ts=to_ts,
                    )
                )
                return
            print_current_index(self._last_index_update)
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

        log.warning("unknown command gateway_id=%s command=%s", self.gateway_id, cmd)
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
            # SMP omitted entirely means "let the engine apply this
            # gateway's configured smp_action default" -- distinct from an
            # explicit SMP=NONE. See SmpAction's docstring in
            # models/order.py.
            smp_action = SmpAction(kv["SMP"]) if "SMP" in kv else None
        except (KeyError, ValueError) as exc:
            log.warning(
                "NEW parse error gateway_id=%s input=%s error=%s",
                self.gateway_id,
                "|".join(parts),
                exc,
            )
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
            "stop_price": stop_price,
            "status": "PENDING",
            "time": datetime.now().strftime("%H:%M:%S"),
        }

        self.push_sock.send_multipart(make_order_new_msg(order.to_dict()))
        self._dbg_count("orders_submitted")

    def _send_quote(self, kv: dict[str, str]) -> None:
        try:
            symbol = kv["SYM"]
            bid_price = float(kv["BID"])
            ask_price = float(kv["ASK"])
            bid_qty = int(kv["BID_QTY"])
            ask_qty = int(kv["ASK_QTY"])
            tif = TIF(kv.get("TIF", "DAY"))
        except (KeyError, ValueError) as exc:
            log.warning(
                "QUOTE parse error gateway_id=%s error=%s", self.gateway_id, exc
            )
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
        self._dbg_count("quotes_submitted")

    def _send_oco(self, kv: dict[str, str]) -> None:
        """Parse and send an OCO pair from TYPE=OCO format."""
        oco_id = kv.get("OCO_ID", "")
        symbol = kv.get("SYM", "")
        tif_str = kv.get("TIF", "DAY")

        if not oco_id:
            log.warning(
                "OCO rejected gateway_id=%s reason=missing_oco_id", self.gateway_id
            )
            console.print("[red]OCO requires OCO_ID=<label>[/red]")
            return
        if not symbol:
            log.warning(
                "OCO rejected gateway_id=%s reason=missing_symbol", self.gateway_id
            )
            console.print("[red]OCO requires SYM=<symbol>[/red]")
            return

        try:
            quantity = int(kv["QTY"])
            tif_val = TIF(tif_str)
        except (KeyError, ValueError) as exc:
            log.warning("OCO parse error gateway_id=%s error=%s", self.gateway_id, exc)
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
            log.warning(
                "OCO rejected gateway_id=%s reason=missing_required_legs",
                self.gateway_id,
            )
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
        self._dbg_count("oco_submitted")

    def _send_combo(self, kv: dict[str, str]) -> None:
        """Parse and send a combo order from TYPE=COMBO format."""

        combo_id = kv.get("COMBO_ID", "")
        combo_type = kv.get("COMBO_TYPE", "AON")
        tif_str = kv.get("TIF", "DAY")
        # SMP omitted entirely means "let the engine apply this gateway's
        # configured smp_action default" to every leg -- distinct from an
        # explicit SMP=NONE. See SmpAction's docstring in models/order.py.
        smp_str = kv.get("SMP")

        if not combo_id:
            log.warning(
                "COMBO rejected gateway_id=%s reason=missing_combo_id", self.gateway_id
            )
            console.print("[red]COMBO requires COMBO_ID=<label>[/red]")
            return

        try:
            combo_type_val = ComboType(combo_type)
            tif_val = TIF(tif_str)
        except ValueError as exc:
            log.warning(
                "COMBO parse error gateway_id=%s error=%s", self.gateway_id, exc
            )
            console.print(f"[red]Parse error: {exc}[/red]")
            return

        leg_count_str = kv.get("LEG_COUNT", "0")
        try:
            leg_count = int(leg_count_str)
        except ValueError:
            log.warning(
                "COMBO rejected gateway_id=%s reason=invalid_leg_count value=%s",
                self.gateway_id,
                leg_count_str,
            )
            console.print(
                f"[red]LEG_COUNT must be an integer, got '{leg_count_str}'[/red]"
            )
            return

        if leg_count < 2 or leg_count > 10:
            log.warning(
                "COMBO rejected gateway_id=%s reason=leg_count_out_of_range count=%d",
                self.gateway_id,
                leg_count,
            )
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
                log.warning(
                    "COMBO rejected gateway_id=%s reason=missing_leg_fields leg=%d",
                    self.gateway_id,
                    i,
                )
                console.print(f"[red]Leg {i} missing SYM, SIDE, or QTY[/red]")
                return
            try:
                leg = ComboLeg(
                    symbol=sym,
                    side=Side(side),
                    order_type=OrderType(leg_type),
                    quantity=int(qty),
                    price=to_ticks(float(price), sym) if price else None,
                    smp_action=SmpAction(smp_str) if smp_str is not None else None,
                )
            except (ValueError, KeyError) as exc:
                log.warning(
                    "COMBO leg parse error gateway_id=%s leg=%d error=%s",
                    self.gateway_id,
                    i,
                    exc,
                )
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
        self._dbg_count("combo_submitted")

    @staticmethod
    def _parse_date(raw: str | None) -> float | None:
        if not raw:
            return None
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
        return dt.timestamp()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        if not self._authenticate():
            reason = self._auth_reason or f"Gateway not allowed: {self.gateway_id}"
            log.error(
                "gateway startup refused gateway_id=%s reason=%s",
                self.gateway_id,
                reason,
            )
            console.print(f"[red]Connection refused:[/red] {reason}")
            self._running = False
            self.push_sock.close()
            self.sub_sock.close()
            return

        self._authenticated = True
        # Request outstanding resting orders so reconnects restore order history
        self.push_sock.send_multipart(make_orders_request_msg(self.gateway_id))

        listener = threading.Thread(target=self._listen, daemon=True)
        listener.start()
        log.info("gateway command loop started gateway_id=%s", self.gateway_id)

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
            style=PROMPT_STYLE,
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
            self._flush_debug_summary(force=True)
            self._index_push_sock.close()
            self.push_sock.close()
            self.sub_sock.close()
            self._index_sub_sock.close()
            log.info("gateway shutdown complete gateway_id=%s", self.gateway_id)
            console.print(f"\n[bold]Gateway {self.gateway_id} disconnected.[/bold]")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    log.info(
        "starting pm-alf-console with log level %s",
        logging.getLevelName(log_level),
    )
    log.debug("resolved gateway args: id=%s", args.id)
    Gateway(args.id).run()


if __name__ == "__main__":
    main()
