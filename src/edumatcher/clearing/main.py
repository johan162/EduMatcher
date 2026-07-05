"""
pm-clearing v2 — SQLite-backed trade clearing process.

Architecture
------------
One subscriber thread receives ``trade.executed`` messages from the engine and
appends them to an in-memory buffer.  A separate timer thread flushes the
buffer to SQLite every ``FLUSH_INTERVAL_SEC`` seconds even when the buffer is
partially filled.  The buffer is also flushed immediately when it reaches
``FLUSH_SIZE`` trades.

The flush transaction atomically writes:
1. raw trade rows  (INSERT OR IGNORE into trade_events)
2. current position snapshots  (UPSERT into gateway_symbol_positions)
3. incremental daily deltas    (UPSERT into gateway_daily_summary)

On startup the process prunes trade_events rows older than 90 days and logs
the count of deleted rows.
"""

from __future__ import annotations

import errno
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import zmq
from rich.console import Console
from rich.table import Table

from edumatcher.clearing.ledger import Ledger, trade_date_utc
from edumatcher.clearing.store import (
    TradeEventRow,
    flush_batch,
    open_writer_connection,
    prune_old_events,
    record_gateway_connect,
    record_gateway_disconnect,
    record_session_event,
)
from edumatcher.messaging.bus import make_subscriber
from edumatcher.models.clock import now_ns  # used in _flush
from edumatcher.models.message import decode
from edumatcher.models.trade import Trade

FLUSH_SIZE: int = 100
FLUSH_INTERVAL_SEC: float = 5.0
_TIMER_POLL_SEC: float = 0.5
_RETENTION_DAYS: int = 90

console = Console()


# ---------------------------------------------------------------------------
# Trade → TradeEventRow conversion
# ---------------------------------------------------------------------------


def _to_trade_event_row(trade: Trade, ingest_ts_ns: int) -> TradeEventRow:
    """Convert a Trade model to the DB row type, deriving trade_date from ts_ns."""
    return TradeEventRow(
        id=trade.id,
        ts_ns=trade.timestamp,
        trade_date=trade_date_utc(trade.timestamp),
        symbol=trade.symbol,
        quantity=trade.quantity,
        price=trade.price,
        tick_decimals=trade.tick_decimals,
        buy_order_id=trade.buy_order_id or None,
        sell_order_id=trade.sell_order_id or None,
        buy_gateway_id=trade.buy_gateway_id,
        sell_gateway_id=trade.sell_gateway_id,
        aggressor_side=trade.aggressor_side or None,
        ingest_ts_ns=ingest_ts_ns,
    )


def _parse_tick_decimals(payload: dict[str, Any]) -> int:
    raw = payload.get("tick_decimals", 2)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return 2
    return parsed if 0 <= parsed <= 8 else 2


def _to_timestamp_ns(raw: Any) -> int:
    if isinstance(raw, float):
        if raw > 1_000_000_000_000:
            return int(raw)
        return int(raw * 1_000_000_000)
    ts = int(raw)
    if ts > 1_000_000_000_000:
        return ts
    return ts * 1_000_000_000


def _trade_from_payload(payload: dict[str, Any]) -> Trade:
    normalized = dict(payload)
    tick_decimals = _parse_tick_decimals(normalized)
    scale = 10**tick_decimals

    price_raw = normalized.get("price", 0)
    if isinstance(price_raw, float):
        normalized["price"] = int(round(price_raw * scale))
    else:
        normalized["price"] = int(price_raw)

    normalized["timestamp"] = _to_timestamp_ns(normalized.get("timestamp", 0))
    normalized["tick_decimals"] = tick_decimals
    return Trade.from_dict(normalized)


# ---------------------------------------------------------------------------
# Main process class
# ---------------------------------------------------------------------------


class ClearingProcess:
    """
    Buffered clearing process — subscribe, buffer, and flush to SQLite.

    Parameters
    ----------
    pub_addr:
        ZMQ PUB address to subscribe to.
    db_path:
        Path to the SQLite clearing database.
    flush_size:
        Maximum number of buffered trades before an immediate flush.
    flush_interval_sec:
        Maximum seconds between flushes when buffer is non-empty.
    print_every:
        Print a P&L summary table to the console every N trades (0 = never).
    retention_days:
        Trade events older than this many days are pruned on startup.
    """

    def __init__(
        self,
        pub_addr: str,
        db_path: Path,
        *,
        flush_size: int = FLUSH_SIZE,
        flush_interval_sec: float = FLUSH_INTERVAL_SEC,
        print_every: int = 100,
        retention_days: int = _RETENTION_DAYS,
    ) -> None:
        self._pub_addr = pub_addr
        self._db_path = Path(db_path)
        self._flush_size = flush_size
        self._flush_interval_sec = flush_interval_sec
        self._print_every = print_every
        self._retention_days = retention_days

        self._buffer: list[Trade] = []
        self._ledger = Ledger()
        self._trade_count = 0

        self._running = False
        self._lock = threading.Lock()
        self._last_flush_mono = time.monotonic()

        # Track the latest connect_at_ns per gateway so we can match the
        # corresponding row when a disconnect message arrives.
        self._gw_connect_ts: dict[str, int] = {}

        self._conn = open_writer_connection(self._db_path)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the clearing process; blocks until stop() is called."""
        pruned = prune_old_events(self._conn, retention_days=self._retention_days)
        if pruned:
            console.print(
                f"[CLEARING] Pruned {pruned} trade_events rows older than"
                f" {self._retention_days} days."
            )

        console.print(f"[CLEARING] DB: {self._db_path}")
        console.print(
            f"[CLEARING] Flush policy: size={self._flush_size},"
            f" interval={self._flush_interval_sec}s"
        )

        # Signal handlers may only be installed from the main thread.
        # When run() is called from a test thread, skip graceful-signal setup.
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda *_: self.stop())
            signal.signal(signal.SIGTERM, lambda *_: self.stop())

        self._running = True

        timer = threading.Thread(
            target=self._timer_loop, daemon=True, name="clearing-timer"
        )
        timer.start()

        sub = make_subscriber(
            self._pub_addr,
            "trade.executed",
            "system.eod",
            "system.gateway_connect",
            "system.gateway_disconnect",
        )
        try:
            self._receive_loop(sub)
        finally:
            sub.close()
            self._force_flush()
            self._conn.close()
            console.print("[CLEARING] Shutdown complete.")

    def stop(self) -> None:
        """Signal the receive loop to exit cleanly."""
        self._running = False

    def flush_now(self) -> int:
        """
        Flush the current buffer immediately.  Returns the number of trades flushed.
        Thread-safe; may be called from tests.
        """
        with self._lock:
            return self._flush()

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    def _receive_loop(self, sub: zmq.Socket) -> None:  # type: ignore[type-arg]
        poller = zmq.Poller()
        poller.register(sub, zmq.POLLIN)

        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break

            if sub not in socks:
                continue

            frames = sub.recv_multipart()
            try:
                topic, payload = decode(frames)
            except Exception as exc:
                console.print(
                    f"[CLEARING] WARNING: failed to decode frame: {exc}",
                    style="yellow",
                )
                continue

            if topic == "trade.executed":
                try:
                    trade = _trade_from_payload(payload)
                except Exception as exc:
                    console.print(
                        f"[CLEARING] WARNING: failed to parse trade: {exc}",
                        style="yellow",
                    )
                    continue

                with self._lock:
                    self._buffer.append(trade)
                    self._trade_count += 1
                    if len(self._buffer) >= self._flush_size:
                        self._flush()

                if (
                    self._print_every > 0
                    and self._trade_count % self._print_every == 0
                ):
                    self._print_pnl_table()

            elif topic == "system.eod":
                self._handle_eod(payload)

            elif topic == "system.gateway_connect":
                self._handle_gateway_connect(payload)

            elif topic == "system.gateway_disconnect":
                self._handle_gateway_disconnect(payload)

    # ------------------------------------------------------------------
    # Timer loop
    # ------------------------------------------------------------------

    def _timer_loop(self) -> None:
        while self._running:
            time.sleep(_TIMER_POLL_SEC)
            with self._lock:
                elapsed = time.monotonic() - self._last_flush_mono
                if elapsed >= self._flush_interval_sec and self._buffer:
                    self._flush()

    # ------------------------------------------------------------------
    # Flush (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _flush(self) -> int:
        """Flush the buffer to SQLite. Returns the number of trades written."""
        if not self._buffer:
            return 0

        updated_ts = now_ns()

        trade_rows = [_to_trade_event_row(t, updated_ts) for t in self._buffer]

        for trade in self._buffer:
            self._ledger.apply_trade(
                symbol=trade.symbol,
                buy_gateway_id=trade.buy_gateway_id,
                sell_gateway_id=trade.sell_gateway_id,
                price=trade.price,
                tick_decimals=trade.tick_decimals,
                quantity=trade.quantity,
                ts_ns=trade.timestamp,
                ingest_ts_ns=updated_ts,
            )

        position_rows, daily_rows = self._ledger.get_flush_rows(
            updated_ts_ns=updated_ts
        )

        flush_batch(self._conn, trade_rows, position_rows, daily_rows)

        count = len(self._buffer)
        self._buffer.clear()
        self._ledger.clear_batch()
        self._last_flush_mono = time.monotonic()

        return count

    def _force_flush(self) -> None:
        """Flush remaining buffer on shutdown (called without lock)."""
        with self._lock:
            self._flush()

    # ------------------------------------------------------------------
    # Secondary event handlers
    # ------------------------------------------------------------------

    def _handle_eod(self, payload: dict[str, Any]) -> None:
        """
        Handle system.eod — engine end-of-day shutdown event.

        Actions:
        1. Force-flush any buffered trades immediately.
        2. Perform a final mark-to-market pass using EOD last-traded prices
           from the payload and write updated positions to the DB.
        3. Write an EOD sentinel row to session_events so pm-clearing-cli
           can report exact session close times.
        """
        try:
            import json

            ts_ns = now_ns()
            trade_date = trade_date_utc(ts_ns)

            # 1. Flush all buffered trades first.
            with self._lock:
                self._flush()

            # 2. EOD mark-to-market: update mark_price from EOD snapshot.
            # payload typically carries a list of book snapshots under key
            # 'books', each with 'symbol', 'last_trade_price', 'best_bid',
            # 'best_ask'.  Apply whatever is present.
            eod_marks: dict[str, int] = {}
            books = payload.get("books") or []
            for book in books:
                sym = book.get("symbol", "")
                ltp = book.get("last_trade_price")
                best_bid = book.get("best_bid")
                best_ask = book.get("best_ask")
                if sym and ltp is not None:
                    eod_marks[sym] = int(ltp)
                elif sym and best_bid is not None and best_ask is not None:
                    eod_marks[sym] = (int(best_bid) + int(best_ask)) // 2

            if eod_marks:
                with self._lock:
                    for pos in self._ledger.all_positions():
                        mark = eod_marks.get(pos.symbol)
                        if mark is not None:
                            pos.mark_price = mark
                            pos.unrealized_pnl = pos.net_qty * (
                                float(mark) - pos.avg_cost
                            )
                    # Flush updated position snapshots to DB.
                    position_rows, daily_rows = self._ledger.get_flush_rows(
                        updated_ts_ns=ts_ns
                    )
                    flush_batch(self._conn, [], position_rows, daily_rows)
                    self._ledger.clear_batch()

            # 3. Write EOD sentinel row.
            record_session_event(
                self._conn,
                event_type="EOD",
                ts_ns=ts_ns,
                trade_date=trade_date,
                payload_json=json.dumps({
                    "eod_marks": eod_marks,
                    "symbols_count": len(eod_marks),
                }),
            )
            console.print(
                f"[CLEARING] EOD received — {len(eod_marks)} symbol mark(s) applied,"
                f" session_events row written for {trade_date}."
            )
        except Exception as exc:
            console.print(
                f"[CLEARING] WARNING: error handling system.eod: {exc}",
                style="yellow",
            )

    def _handle_gateway_connect(self, payload: dict[str, Any]) -> None:
        """
        Handle system.gateway_connect — record connect timestamp in DB.
        """
        try:
            gateway_id = str(payload.get("gateway_id", "")).upper()
            if not gateway_id:
                return
            ts_ns = now_ns()
            self._gw_connect_ts[gateway_id] = ts_ns
            record_gateway_connect(
                self._conn,
                gateway_id=gateway_id,
                connected_at_ns=ts_ns,
            )
        except Exception as exc:
            console.print(
                f"[CLEARING] WARNING: error handling gateway_connect: {exc}",
                style="yellow",
            )

    def _handle_gateway_disconnect(self, payload: dict[str, Any]) -> None:
        """
        Handle system.gateway_disconnect — update disconnect timestamp and reason.
        Also force-flush buffered trades for that gateway before the engine
        cancels its resting orders.
        """
        try:
            gateway_id = str(payload.get("gateway_id", "")).upper()
            if not gateway_id:
                return

            # Force flush so any buffered fills for this gateway are persisted
            # before the engine-side order cancellations arrive.
            with self._lock:
                self._flush()

            ts_ns = now_ns()
            reason = payload.get("reason") or payload.get("disconnect_reason")
            connect_ts = self._gw_connect_ts.pop(gateway_id, 0)

            if connect_ts:
                record_gateway_disconnect(
                    self._conn,
                    gateway_id=gateway_id,
                    connected_at_ns=connect_ts,
                    disconnected_at_ns=ts_ns,
                    reason=str(reason) if reason else None,
                )
        except Exception as exc:
            console.print(
                f"[CLEARING] WARNING: error handling gateway_disconnect: {exc}",
                style="yellow",
            )

    # ------------------------------------------------------------------
    # Console P&L table
    # ------------------------------------------------------------------

    def _print_pnl_table(self) -> None:
        positions = self._ledger.all_positions()
        if not positions:
            return

        t = Table(title="[bold]P&L Summary[/bold]", show_lines=True)
        t.add_column("Gateway", style="cyan")
        t.add_column("Symbol", style="bold")
        t.add_column("Net Qty", justify="right")
        t.add_column("Avg Cost", justify="right")
        t.add_column("Mark", justify="right")
        t.add_column("Realized", justify="right")
        t.add_column("Unrealized", justify="right")
        t.add_column("Total P&L", justify="right")

        for pos in sorted(positions, key=lambda p: (p.gateway_id, p.symbol)):
            scale = float(10**pos.tick_decimals)
            real = pos.realized_pnl / scale
            unreal = pos.unrealized_pnl / scale
            total = real + unreal
            colour = "green" if total >= 0 else "red"
            mark = (
                f"{(pos.mark_price / scale):.{pos.tick_decimals}f}"
                if pos.mark_price is not None
                else "—"
            )
            avg_cost = (
                f"{(pos.avg_cost / scale):.{pos.tick_decimals}f}"
                if pos.avg_cost
                else "—"
            )
            t.add_row(
                pos.gateway_id,
                pos.symbol,
                f"{pos.net_qty:+d}",
                avg_cost,
                mark,
                f"[{colour}]{real:+.2f}[/{colour}]",
                f"[{colour}]{unreal:+.2f}[/{colour}]",
                f"[bold {colour}]{total:+.2f}[/bold {colour}]",
            )

        console.print(t)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    from edumatcher.cli_version import add_version_argument
    from edumatcher.config import DATA_DIR, ENGINE_PUB_ADDR

    parser = argparse.ArgumentParser(
        prog="pm-clearing",
        description="EduMatcher clearing process — SQLite-backed trade P&L tracker",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    add_version_argument(parser, "pm-clearing")

    parser.add_argument(
        "--datapath",
        metavar="PATH",
        default=None,
        help="Data directory or explicit .db file path",
    )
    parser.add_argument(
        "--db-name",
        metavar="NAME",
        default="clearing.db",
        help="SQLite filename within data directory (default: clearing.db)",
    )
    parser.add_argument(
        "--flush-size",
        type=int,
        default=FLUSH_SIZE,
        metavar="N",
        help=f"Max buffered trades before flush (1..100, default: {FLUSH_SIZE})",
    )
    parser.add_argument(
        "--flush-interval",
        type=float,
        default=FLUSH_INTERVAL_SEC,
        metavar="SEC",
        help=f"Max seconds between flushes (>=0.1, default: {FLUSH_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--print-every",
        type=int,
        default=100,
        metavar="N",
        help="Print P&L summary every N trades (0 = never, default: 100)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=_RETENTION_DAYS,
        metavar="N",
        help=(
            f"Delete trade_events rows older than N days on startup"
            f" (default: {_RETENTION_DAYS}; 0 = disable pruning)"
        ),
    )

    args = parser.parse_args()

    if not (1 <= args.flush_size <= 100):
        print("[ERROR] --flush-size must be 1..100", file=sys.stderr)
        raise SystemExit(2)
    if args.flush_interval < 0.1:
        print("[ERROR] --flush-interval must be >= 0.1", file=sys.stderr)
        raise SystemExit(2)
    if args.retention_days < 0:
        print("[ERROR] --retention-days must be >= 0", file=sys.stderr)
        raise SystemExit(2)

    if args.datapath is not None:
        dp = Path(args.datapath).expanduser()
        db_path = dp if dp.suffix == ".db" else dp / args.db_name
    else:
        db_path = DATA_DIR / args.db_name

    try:
        process = ClearingProcess(
            pub_addr=ENGINE_PUB_ADDR,
            db_path=db_path,
            flush_size=args.flush_size,
            flush_interval_sec=args.flush_interval,
            print_every=args.print_every,
            retention_days=args.retention_days,
        )
    except Exception as exc:
        print(f"[CLEARING] FATAL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    process.run()


if __name__ == "__main__":
    main()
