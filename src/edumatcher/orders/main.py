"""
Order Status Monitor — live table of all order events across all gateways.

Usage:
  poetry run pm-orders [--gateway GW01]

Subscribes to all order.* topics and maintains a live rich table showing
every order's current status, quantity, and last-update time.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from datetime import datetime
from typing import Any

import zmq
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from edumatcher.config import ENGINE_PUB_ADDR
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode

console = Console()
log = logging.getLogger(__name__)
_REFRESH_HZ = 2

_CLIENT_NAME = "pm-orders"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

_STATUS_STYLE = {
    "NEW": "green",
    "PARTIAL": "yellow",
    "FILLED": "bright_green",
    "CANCELLED": "red",
    "REJECTED": "red",
    "EXPIRED": "dim",
    "PENDING": "dim",
}


def _build_table(orders: dict[str, Any], gw_filter: str | None) -> Table:
    t = Table(
        title="[bold]Order Monitor[/bold]  \u2014 "
        + (f"gateway [cyan]{gw_filter}[/cyan]" if gw_filter else "all gateways"),
        show_lines=True,
        expand=True,
    )
    t.add_column("ID", style="dim", width=10)
    t.add_column("Gateway", style="cyan", width=8)
    t.add_column("Symbol", style="bold", width=8)
    t.add_column("Side", style="cyan", width=6)
    t.add_column("Type", style="magenta", width=12)
    t.add_column("TIF", style="dim", width=5)
    t.add_column("Qty", justify="right", width=7)
    t.add_column("Remaining", justify="right", width=9)
    t.add_column("Price", justify="right", width=9)
    t.add_column("Status", width=12)
    t.add_column("Updated", style="dim", width=12)

    visible = [
        o
        for o in orders.values()
        if gw_filter is None or o.get("gateway_id") == gw_filter
    ]
    visible.sort(key=lambda x: x.get("updated", ""), reverse=True)

    for o in visible:
        st = o.get("status", "?")
        colour = _STATUS_STYLE.get(st, "white")
        t.add_row(
            o.get("order_id", "?")[:8],
            o.get("gateway_id", "?"),
            o.get("symbol", "?"),
            o.get("side", "?"),
            o.get("order_type", "?"),
            o.get("tif", "?"),
            str(o.get("qty", "?")),
            str(o.get("remaining", "?")),
            str(o.get("price", "—")),
            Text(st, style=colour),
            o.get("updated", "?"),
        )
    return t


class OrderMonitor:
    def __init__(self, gw_filter: str | None) -> None:
        self.gw_filter = gw_filter
        self._orders: dict[str, dict[str, Any]] = {}  # order_id → state dict
        self._lock = threading.Lock()
        self._running = True

        self.sub = make_subscriber(ENGINE_PUB_ADDR, "order.")

    def _handle(self, topic: str, payload: dict[str, Any]) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        oid = payload.get("order_id", "")
        with self._lock:
            entry = self._orders.setdefault(oid, {"order_id": oid})

            # Populate order metadata whenever it's present in the message
            for src_key, dst_key in (
                ("symbol", "symbol"),
                ("side", "side"),
                ("order_type", "order_type"),
                ("tif", "tif"),
                ("qty", "qty"),
                ("price", "price"),
            ):
                val = payload.get(src_key)
                if val is not None:
                    entry[dst_key] = val

            if "order.ack" in topic:
                # Extract gateway_id from topic: order.ack.GW01
                parts = topic.split(".")
                if len(parts) >= 3:
                    entry["gateway_id"] = parts[2]
                if payload.get("accepted"):
                    entry["status"] = "NEW"
                else:
                    entry["status"] = "REJECTED"

            elif "order.fill" in topic:
                # gateway_id from topic for counterparty fills that skipped an ack
                parts = topic.split(".")
                if len(parts) >= 3 and "gateway_id" not in entry:
                    entry["gateway_id"] = parts[2]
                entry["remaining"] = payload.get("remaining_qty", 0)
                entry["status"] = payload.get("status", "PARTIAL")

            elif "order.cancelled" in topic:
                entry["status"] = "CANCELLED"

            elif "order.expired" in topic:
                entry["status"] = "EXPIRED"

            entry["updated"] = now

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            socks = dict(poller.poll(timeout=300))
            if self.sub in socks:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
                self._handle(topic, payload)

    def run(self) -> None:
        t = threading.Thread(target=self._receive, daemon=True)
        t.start()

        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_running", False))

        _resize_pending = False

        def _on_resize(signum: int, frame: object) -> None:
            nonlocal _resize_pending
            _resize_pending = True

        signal.signal(signal.SIGWINCH, _on_resize)

        try:
            with Live(
                console=console, refresh_per_second=_REFRESH_HZ, screen=False
            ) as live:
                while self._running:
                    if _resize_pending:
                        _resize_pending = False
                        console.clear()
                    with self._lock:
                        snapshot = dict(self._orders)
                    live.update(_build_table(snapshot, self.gw_filter))
                    time.sleep(1 / _REFRESH_HZ)
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.sub.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher order status monitor")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-orders")
    parser.add_argument(
        "--gateway",
        "-g",
        metavar="GW_ID",
        default=None,
        help="Filter to a single gateway (default: show all)",
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
    log.info("starting pm-orders with log level %s", logging.getLevelName(log_level))
    OrderMonitor(args.gateway).run()


if __name__ == "__main__":
    main()
