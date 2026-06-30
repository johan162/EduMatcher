"""
Statistics Process — records market data to a SQLite database.

Usage:
  poetry run pm-stats [--db data/stats.db]

Subscribes to:
  trade.executed  — to track OHLCV, VWAP, min/max, volume
  book.*          — to record 15-minute price snapshots
  system.eod      — engine shutdown: record closing bid/ask/last price

SQLite tables
-------------
  daily_stats
    Columns: date, symbol, open_price, high_price, low_price, close_price,
             open_bid, open_ask, close_bid, close_ask, volume, trade_count,
             vwap, largest_trade_qty, largest_trade_price
    One row per (date, symbol), upserted on each trade / EOD event.

  price_snapshots
    Columns: ts, symbol, mid_price, best_bid, best_ask, pct_change
    One row every 15 minutes per symbol (based on last book snapshot seen).

  trade_log
    Columns: ts, trade_id, symbol, price, quantity,
             buy_gateway_id, sell_gateway_id
    Append-only log of every individual trade.
"""

from __future__ import annotations

import argparse
import signal
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import errno

import zmq

from edumatcher.config import (
    ENGINE_PULL_ADDR,
    ENGINE_PUB_ADDR,
    STATS_DB_FILE,
)
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_symbols_request_msg,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_INTERVAL_SEC = 15 * 60  # 15 minutes


# ---------------------------------------------------------------------------
# Per-symbol intraday accumulator
# ---------------------------------------------------------------------------


@dataclass
class _DayAccum:
    """Holds intraday statistics for one symbol on one calendar date."""

    date: str  # ISO date string YYYY-MM-DD
    symbol: str

    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None

    open_bid: Optional[float] = None
    open_ask: Optional[float] = None
    close_bid: Optional[float] = None
    close_ask: Optional[float] = None

    volume: int = 0
    trade_count: int = 0

    # For VWAP: sum(price*qty) / sum(qty)
    _pv_sum: float = field(default=0.0, repr=False)
    _q_sum: int = field(default=0, repr=False)

    largest_trade_qty: int = 0
    largest_trade_price: Optional[float] = None

    def on_trade(self, price: float, qty: int) -> None:
        if self.open_price is None:
            self.open_price = price
        self.close_price = price
        self.high_price = (
            price if self.high_price is None else max(self.high_price, price)
        )
        self.low_price = price if self.low_price is None else min(self.low_price, price)
        self.volume += qty
        self.trade_count += 1
        self._pv_sum += price * qty
        self._q_sum += qty
        if qty > self.largest_trade_qty:
            self.largest_trade_qty = qty
            self.largest_trade_price = price

    @property
    def vwap(self) -> Optional[float]:
        return self._pv_sum / self._q_sum if self._q_sum else None

    def on_eod_book(self, best_bid: Optional[float], best_ask: Optional[float]) -> None:
        self.close_bid = best_bid
        self.close_ask = best_ask


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_stats (
    date                TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    open_price          REAL,
    high_price          REAL,
    low_price           REAL,
    close_price         REAL,
    open_bid            REAL,
    open_ask            REAL,
    close_bid           REAL,
    close_ask           REAL,
    volume              INTEGER NOT NULL DEFAULT 0,
    trade_count         INTEGER NOT NULL DEFAULT 0,
    vwap                REAL,
    largest_trade_qty   INTEGER,
    largest_trade_price REAL,
    PRIMARY KEY (date, symbol)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    ts          TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    mid_price   REAL,
    best_bid    REAL,
    best_ask    REAL,
    pct_change  REAL,
    PRIMARY KEY (ts, symbol)
);

CREATE TABLE IF NOT EXISTS trade_log (
    ts              TEXT NOT NULL,
    trade_id        TEXT NOT NULL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    price           REAL NOT NULL,
    quantity        INTEGER NOT NULL,
    buy_gateway_id  TEXT,
    sell_gateway_id TEXT
);

CREATE TABLE IF NOT EXISTS order_events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    order_id        TEXT NOT NULL,
    gateway_id      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT,
    order_type      TEXT,
    tif             TEXT,
    price           REAL,
    quantity        INTEGER,
    remaining_qty   INTEGER,
    status          TEXT,
    fill_price      REAL,
    fill_qty        INTEGER,
    trade_id        TEXT,
    reason          TEXT,
    client_order_id TEXT,
    combo_parent_id TEXT,
    oco_group_id    TEXT,
    priority_reset  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_oe_order_id ON order_events(order_id);
CREATE INDEX IF NOT EXISTS idx_oe_gateway_ts ON order_events(gateway_id, ts);
CREATE INDEX IF NOT EXISTS idx_oe_symbol_ts ON order_events(symbol, ts);
CREATE INDEX IF NOT EXISTS idx_oe_type_ts ON order_events(event_type, ts);
"""

UPSERT_DAILY = """
INSERT INTO daily_stats
    (date, symbol, open_price, high_price, low_price, close_price,
     open_bid, open_ask, close_bid, close_ask,
     volume, trade_count, vwap, largest_trade_qty, largest_trade_price)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(date, symbol) DO UPDATE SET
    open_price          = excluded.open_price,
    high_price          = excluded.high_price,
    low_price           = excluded.low_price,
    close_price         = excluded.close_price,
    open_bid            = excluded.open_bid,
    open_ask            = excluded.open_ask,
    close_bid           = excluded.close_bid,
    close_ask           = excluded.close_ask,
    volume              = excluded.volume,
    trade_count         = excluded.trade_count,
    vwap                = excluded.vwap,
    largest_trade_qty   = excluded.largest_trade_qty,
    largest_trade_price = excluded.largest_trade_price
"""

INSERT_SNAPSHOT = """
INSERT OR IGNORE INTO price_snapshots (ts, symbol, mid_price, best_bid, best_ask, pct_change)
VALUES (?,?,?,?,?,?)
"""

INSERT_TRADE = """
INSERT OR IGNORE INTO trade_log (ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id)
VALUES (?,?,?,?,?,?,?)
"""

INSERT_ORDER_EVENT = """
INSERT INTO order_events
    (ts, event_type, order_id, gateway_id, symbol, side, order_type, tif, price,
     quantity, remaining_qty, status, fill_price, fill_qty, trade_id, reason,
     client_order_id, combo_parent_id, oco_group_id, priority_reset)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Stats process
# ---------------------------------------------------------------------------


class StatsProcess:
    def __init__(self, db_path: Path) -> None:
        self._conn = _open_db(db_path)
        self._lock = threading.Lock()
        self._running = True

        # symbol → _DayAccum for current calendar date
        self._accum: dict[str, _DayAccum] = {}

        # symbol → last snapshot mid_price (for % change)
        self._last_snap_mid: dict[str, float] = {}

        # symbol → timestamp of last snapshot written
        self._last_snap_ts: dict[str, float] = defaultdict(float)

        self.sub = make_subscriber(
            ENGINE_PUB_ADDR,
            "trade.executed",
            "book.",
            "system.eod",
            "system.symbols.STATS",
            "order.ack.",
            "order.fill.",
            "order.amended.",
            "order.cancelled.",
            "order.expired.",
            "combo.ack.",
            "combo.status.",
            "oco.ack.",
            "oco.cancelled.",
            "quote.ack.",
            "quote.status.",
        )
        self.push = make_pusher(ENGINE_PULL_ADDR)
        self._push_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Accumulator helpers
    # ------------------------------------------------------------------

    def _today(self) -> str:
        return date.today().isoformat()

    def _accum_for(self, symbol: str) -> _DayAccum:
        today = self._today()
        acc = self._accum.get(symbol)
        if acc is None or acc.date != today:
            # New day (or first time) — flush old if any
            if acc is not None:
                self._flush_daily(acc)
            acc = _DayAccum(date=today, symbol=symbol)
            self._accum[symbol] = acc
        return acc

    def _flush_daily(self, acc: _DayAccum) -> None:
        with self._conn:
            self._conn.execute(
                UPSERT_DAILY,
                (
                    acc.date,
                    acc.symbol,
                    acc.open_price,
                    acc.high_price,
                    acc.low_price,
                    acc.close_price,
                    acc.open_bid,
                    acc.open_ask,
                    acc.close_bid,
                    acc.close_ask,
                    acc.volume,
                    acc.trade_count,
                    acc.vwap,
                    acc.largest_trade_qty,
                    acc.largest_trade_price,
                ),
            )

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def _on_trade(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "")
        price = payload.get("price")
        qty = payload.get("quantity")
        if not symbol or price is None or qty is None:
            return

        ts = datetime.fromtimestamp(
            payload.get("timestamp", time.time()), tz=timezone.utc
        ).isoformat(timespec="milliseconds")
        with self._lock:
            acc = self._accum_for(symbol)
            acc.on_trade(price, qty)
            self._flush_daily(acc)

            with self._conn:
                self._conn.execute(
                    INSERT_TRADE,
                    (
                        ts,
                        payload.get("id", ""),
                        symbol,
                        price,
                        qty,
                        payload.get("buy_gateway_id"),
                        payload.get("sell_gateway_id"),
                    ),
                )

    def _on_book(self, symbol: str, payload: dict[str, Any]) -> None:
        with self._lock:
            # Record opening bid/ask once per day
            acc = self._accum_for(symbol)
            bids = payload.get("bids", [])
            asks = payload.get("asks", [])
            best_bid = bids[0].get("price") if bids else None
            best_ask = asks[0].get("price") if asks else None

            if acc.open_bid is None and best_bid is not None:
                acc.open_bid = best_bid
            if acc.open_ask is None and best_ask is not None:
                acc.open_ask = best_ask
            # Persist opening prices as soon as we know them, so the row
            # exists in daily_stats even if no trades occur today.
            if acc.open_bid is not None or acc.open_ask is not None:
                self._flush_daily(acc)

            # 15-minute price snapshot
            now = time.monotonic()
            if now - self._last_snap_ts[symbol] >= SNAPSHOT_INTERVAL_SEC:
                self._last_snap_ts[symbol] = now
                mid: Optional[float] = None
                if best_bid is not None and best_ask is not None:
                    mid = round((best_bid + best_ask) / 2, 6)
                elif best_bid is not None:
                    mid = best_bid
                elif best_ask is not None:
                    mid = best_ask
                elif payload.get("last_price") is not None:
                    mid = payload["last_price"]

                prev = self._last_snap_mid.get(symbol)
                pct = None
                if mid is not None and prev is not None and prev != 0:
                    pct = round((mid - prev) / prev * 100, 4)
                if mid is not None:
                    self._last_snap_mid[symbol] = mid

                snap_ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
                with self._conn:
                    self._conn.execute(
                        INSERT_SNAPSHOT, (snap_ts, symbol, mid, best_bid, best_ask, pct)
                    )

    def _on_eod(self, payload: dict[str, Any]) -> None:
        with self._lock:
            for book in payload.get("books", []):
                symbol = book.get("symbol", "")
                if not symbol:
                    continue
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                best_bid = bids[0].get("price") if bids else None
                best_ask = asks[0].get("price") if asks else None
                acc = self._accum_for(symbol)
                acc.on_eod_book(best_bid, best_ask)
                # close_price already set by last trade; if no trades today keep None
                self._flush_daily(acc)
            print(
                f"[STATS] EOD received — flushed {len(payload.get('books', []))} symbol(s)."
            )

    def _on_order_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Persist one private order lifecycle event for history queries."""
        parts = topic.split(".")
        gateway_id = (
            parts[-1] if len(parts) >= 3 else str(payload.get("gateway_id", ""))
        )
        event_name = _event_type_from_topic(topic, payload)
        order_id = str(
            payload.get("order_id")
            or payload.get("combo_id")
            or payload.get("oco_id")
            or payload.get("quote_id")
            or ""
        )
        if not order_id or not gateway_id:
            return
        ts = datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds")
        with self._lock, self._conn:
            self._conn.execute(
                INSERT_ORDER_EVENT,
                (
                    ts,
                    event_name,
                    order_id,
                    gateway_id,
                    str(payload.get("symbol", "")),
                    payload.get("side"),
                    payload.get("order_type"),
                    payload.get("tif"),
                    payload.get("price"),
                    payload.get("quantity") or payload.get("qty"),
                    payload.get("remaining_qty"),
                    payload.get("status"),
                    payload.get("fill_price"),
                    payload.get("fill_qty"),
                    payload.get("trade_id"),
                    payload.get("reason"),
                    payload.get("client_order_id"),
                    payload.get("combo_parent_id"),
                    payload.get("oco_group_id"),
                    (
                        int(bool(payload.get("priority_reset")))
                        if "priority_reset" in payload
                        else None
                    ),
                ),
            )

    # ------------------------------------------------------------------
    # Main receive loop
    # ------------------------------------------------------------------

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
            if self.sub not in socks:
                continue
            try:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
            except Exception:
                continue

            try:
                if topic.startswith("trade.executed"):
                    self._on_trade(payload)
                elif topic.startswith("book."):
                    symbol = topic.split(".", 1)[1]
                    self._on_book(symbol, payload)
                elif topic == "system.eod":
                    self._on_eod(payload)
                elif topic == "system.symbols.STATS":
                    self._on_startup_symbols(payload)
                elif _is_order_event_topic(topic):
                    self._on_order_event(topic, payload)
            except Exception as exc:
                print(f"[STATS] WARNING: error handling {topic}: {exc}", flush=True)

    def _on_startup_symbols(self, payload: dict[str, Any]) -> None:
        """Received in response to our startup symbols request.
        Request a current book snapshot for every symbol so opening bid/ask
        and an initial price_snapshots row are recorded even if no new orders
        arrive after the stats process starts.
        """
        symbols = payload.get("symbols", [])
        with self._push_lock:
            for sym in symbols:
                self.push.send_multipart(make_book_snapshot_request_msg(sym))
        if symbols:
            print(f"[STATS] Requested opening snapshots for: {', '.join(symbols)}")

    def run(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self._stop())
        signal.signal(signal.SIGTERM, lambda *_: self._stop())

        t = threading.Thread(target=self._receive, daemon=True)
        t.start()

        # Give the SUB socket time to connect and filters to propagate,
        # then request the symbol list so we can pull opening book snapshots.
        # This handles the race where the engine seeded MM orders before we started.
        time.sleep(0.3)
        with self._push_lock:
            self.push.send_multipart(make_symbols_request_msg("STATS"))

        print("[STATS] Recording market statistics …  (Ctrl-C to stop)")
        try:
            while self._running:
                t.join(timeout=0.5)
        finally:
            # Wait for the receive thread to finish its current message before
            # closing the database and sockets to avoid mid-transaction errors.
            t.join(timeout=1.0)
            self._conn.close()
            self.sub.close()
            self.push.close()

    def _stop(self) -> None:
        self._running = False
        print("\n[STATS] Stopped.")


def _is_order_event_topic(topic: str) -> bool:
    return topic.startswith(
        (
            "order.ack.",
            "order.fill.",
            "order.amended.",
            "order.cancelled.",
            "order.expired.",
            "combo.ack.",
            "combo.status.",
            "oco.ack.",
            "oco.cancelled.",
            "quote.ack.",
            "quote.status.",
        )
    )


def _event_type_from_topic(topic: str, payload: dict[str, Any]) -> str:
    if topic.startswith("order.ack."):
        return "ACK" if payload.get("accepted") else "REJECT"
    if topic.startswith("order.fill."):
        return "FILL"
    if topic.startswith("order.amended."):
        return "AMEND"
    if topic.startswith("order.cancelled."):
        return "CANCEL"
    if topic.startswith("order.expired."):
        return "EXPIRE"
    if topic.startswith("combo."):
        return "COMBO"
    if topic.startswith("oco."):
        return "OCO"
    if topic.startswith("quote."):
        return "QUOTE"
    return "EVENT"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher statistics recorder")
    parser.add_argument(
        "--db",
        default=str(STATS_DB_FILE),
        metavar="PATH",
        help=f"SQLite database path (default: {STATS_DB_FILE})",
    )
    args = parser.parse_args()
    try:
        process = StatsProcess(Path(args.db))
    except Exception as exc:
        print(f"[STATS] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    process.run()


if __name__ == "__main__":
    main()
