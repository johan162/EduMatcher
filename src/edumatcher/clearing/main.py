"""
Clearing Process — financial settlement sink with P&L tracking.

Usage:
  poetry run pm-clearing

Subscribes to trade.executed events and maintains per-user (gateway) P&L:
  position    — net quantity (positive = long, negative = short)
  avg_cost    — VWAP-updated cost basis
  realized_pnl   — from closed/reduced position legs
  unrealized_pnl — position × (last_price − avg_cost)

All trades are appended to data/clearing_report.csv.
A rich P&L summary table is printed every CLEARING_PRINT_EVERY trades
and in full on Ctrl-C exit.
"""

from __future__ import annotations

import csv
import errno
import signal
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

import zmq
from rich.console import Console
from rich.table import Table

from edumatcher.config import (
    CLEARING_PRINT_EVERY,
    CLEARING_REPORT_FILE,
    DATA_DIR,
    ENGINE_PUB_ADDR,
)
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.message import decode
from edumatcher.models.trade import Trade

console = Console()

# ---------------------------------------------------------------------------
# Per-symbol position record
# ---------------------------------------------------------------------------


@dataclass
class PositionRecord:
    symbol: str
    gateway_id: str
    position: float = 0.0  # net qty (+ = long, - = short)
    avg_cost: float = 0.0  # VWAP cost basis
    realized_pnl: float = 0.0
    last_price: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        if self.position == 0:
            return 0.0
        return self.position * (self.last_price - self.avg_cost)

    def apply_fill(self, qty: int, price: float, is_buy: bool) -> None:
        """
        Update position, avg_cost, and realized_pnl for a single fill leg.
        qty is always positive; is_buy indicates direction.
        """
        signed_qty = qty if is_buy else -qty
        self.last_price = price

        if self.position == 0:
            # Opening a new position
            self.avg_cost = price
            self.position = signed_qty
            return

        if (self.position > 0 and is_buy) or (self.position < 0 and not is_buy):
            # Adding to existing position — update VWAP avg_cost
            total_cost = self.avg_cost * abs(self.position) + price * qty
            self.position += signed_qty
            self.avg_cost = total_cost / abs(self.position)
        else:
            # Reducing or reversing position — realize P&L
            reduce_qty = min(qty, abs(self.position))
            if self.position > 0:
                self.realized_pnl += (price - self.avg_cost) * reduce_qty
            else:
                self.realized_pnl += (self.avg_cost - price) * reduce_qty

            self.position += signed_qty
            if abs(self.position) < 1e-9:
                self.position = 0.0
                self.avg_cost = 0.0
            elif (signed_qty > 0 and self.position > 0) or (
                signed_qty < 0 and self.position < 0
            ):
                # Reversed — set new avg_cost for the remaining position
                self.avg_cost = price
                # Re-base: only the excess qty contributes
                # (simple approximation: new basis = fill price)


# ---------------------------------------------------------------------------
# Clearing process
# ---------------------------------------------------------------------------


class ClearingProcess:
    def __init__(self) -> None:
        # ledger[gateway_id][symbol] → PositionRecord
        self._ledger: dict[str, dict[str, PositionRecord]] = defaultdict(dict)
        self._trade_count = 0
        self._lock = threading.Lock()
        self._running = True

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._csv_path = CLEARING_REPORT_FILE
        self._init_csv()

        self.sub = make_subscriber(ENGINE_PUB_ADDR, "trade.executed")

    def _init_csv(self) -> None:
        """Write CSV header if the file is new."""
        write_header = not self._csv_path.exists() or self._csv_path.stat().st_size == 0
        self._csv_file = open(self._csv_path, "a", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)
        if write_header:
            self._csv_writer.writerow(
                [
                    "trade_id",
                    "symbol",
                    "buy_order_id",
                    "sell_order_id",
                    "buy_gateway",
                    "sell_gateway",
                    "price",
                    "quantity",
                    "timestamp",
                ]
            )

    def _record_trade(self, trade: Trade) -> None:
        ts_raw = trade.timestamp
        ts_sec = ts_raw / 1_000_000_000 if ts_raw > 1_000_000_000_000 else ts_raw
        self._csv_writer.writerow(
            [
                trade.id,
                trade.symbol,
                trade.buy_order_id,
                trade.sell_order_id,
                trade.buy_gateway_id,
                trade.sell_gateway_id,
                trade.price,
                trade.quantity,
                datetime.fromtimestamp(ts_sec, timezone.utc).isoformat(),
            ]
        )
        self._csv_file.flush()

    def _update_ledger(self, trade: Trade) -> None:
        with self._lock:
            for gw_id, is_buy in [
                (trade.buy_gateway_id, True),
                (trade.sell_gateway_id, False),
            ]:
                if trade.symbol not in self._ledger[gw_id]:
                    self._ledger[gw_id][trade.symbol] = PositionRecord(
                        symbol=trade.symbol, gateway_id=gw_id
                    )
                rec = self._ledger[gw_id][trade.symbol]
                rec.apply_fill(trade.quantity, trade.price, is_buy)

    def _print_pnl_table(self) -> None:
        t = Table(title="[bold]P&L Summary[/bold]", show_lines=True)
        t.add_column("Gateway", style="cyan")
        t.add_column("Symbol", style="bold")
        t.add_column("Position", justify="right")
        t.add_column("Avg Cost", justify="right")
        t.add_column("Last Price", justify="right")
        t.add_column("Realized", justify="right")
        t.add_column("Unrealized", justify="right")
        t.add_column("Total P&L", justify="right")

        with self._lock:
            ledger_copy = {
                gw: {sym: rec for sym, rec in syms.items()}
                for gw, syms in self._ledger.items()
            }

        for gw_id in sorted(ledger_copy):
            for sym in sorted(ledger_copy[gw_id]):
                rec = ledger_copy[gw_id][sym]
                real = rec.realized_pnl
                unreal = rec.unrealized_pnl
                total = real + unreal
                colour = "green" if total >= 0 else "red"
                t.add_row(
                    gw_id,
                    sym,
                    f"{rec.position:+.0f}",
                    f"{rec.avg_cost:.4f}" if rec.avg_cost else "—",
                    f"{rec.last_price:.4f}",
                    f"[{colour}]{real:+.2f}[/{colour}]",
                    f"[{colour}]{unreal:+.2f}[/{colour}]",
                    f"[bold {colour}]{total:+.2f}[/bold {colour}]",
                )

        console.print(t)

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break
            if self.sub in socks:
                frames = self.sub.recv_multipart()
                try:
                    _, payload = decode(frames)
                    trade = Trade.from_dict(payload)
                except Exception as exc:
                    print(
                        f"[CLEARING] WARNING: failed to decode trade: {exc}",
                        flush=True,
                    )
                    continue
                self._record_trade(trade)
                self._update_ledger(trade)
                self._trade_count += 1
                ts_raw = trade.timestamp
                ts_sec = (
                    ts_raw / 1_000_000_000 if ts_raw > 1_000_000_000_000 else ts_raw
                )
                ts = datetime.fromtimestamp(ts_sec, timezone.utc).strftime("%H:%M:%S")
                console.print(
                    f"[CLEARING] [{ts}] TRADE {trade.id[:8]}  "
                    f"{trade.symbol}  qty={trade.quantity} @{trade.price:.4f}  "
                    f"buyer={trade.buy_gateway_id}  seller={trade.sell_gateway_id}"
                )
                if self._trade_count % CLEARING_PRINT_EVERY == 0:
                    self._print_pnl_table()

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())
        t = threading.Thread(target=self._receive, daemon=True)
        t.start()
        console.print(f"[CLEARING] Recording trades → {self._csv_path}")
        try:
            t.join()
        finally:
            self._csv_file.close()
            self.sub.close()
        if not self._running:
            print("\n[CLEARING] Final P&L:")
            self._print_pnl_table()
            print(f"[CLEARING] Trades saved to {self._csv_path}")

    def _stop(self) -> None:
        self._running = False


def main() -> None:
    try:
        process = ClearingProcess()
    except Exception as exc:
        print(f"[CLEARING] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    process.run()


if __name__ == "__main__":
    main()
