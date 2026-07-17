"""
Statistics Process — records market data to a SQLite database.

Usage:
  poetry run pm-stats [--db data/stats.db] [--snapshot-interval SEC]

Subscribes to (engine PUB, ENGINE_PUB_ADDR):
  trade.executed  — to track OHLCV, VWAP, min/max, volume
  book.*          — to record periodic price snapshots (default: every 15 min)
  system.eod      — engine shutdown: record closing bid/ask/last price

Subscribes to (pm-index PUB, INDEX_PUB_CONNECT_ADDR — a separate socket,
since pm-index binds its own PUB endpoint distinct from the engine's):
  index.update    — every throttled index level publication from pm-index

SQLite tables
-------------
  daily_stats
    Columns: date, symbol, open_price, high_price, low_price, close_price,
             open_bid, open_ask, close_bid, close_ask, volume, trade_count,
             vwap, largest_trade_qty, largest_trade_price
    One row per (date, symbol), upserted on each trade / EOD event.

  price_snapshots
    Columns: ts, symbol, mid_price, best_bid, best_ask, pct_change
    One row every N seconds per symbol (default: 900 s / 15 minutes).
    Override with --snapshot-interval.

  trade_log
    Columns: ts, trade_id, symbol, price, quantity,
             buy_gateway_id, sell_gateway_id
    Append-only log of every individual trade.

  index_daily_stats
    Columns: date, index_id, open_level, high_level, low_level, close_level,
             open_aggregate_cap, close_aggregate_cap, update_count
    One row per (date, index_id), upserted on each index.update event.

  index_level_snapshots
    Columns: ts, index_id, level, aggregate_cap, divisor, session_state,
             day_open, day_high, day_low
    One row per index.update event received (no additional throttling —
    pm-index already throttles via its own publish_interval_sec before
    publishing). Indexed on (index_id, ts) for fast range queries, unlike
    pm-index's own JSONL history file which pm-stats does not replace but
    complements: the JSONL file remains the source for corporate-action /
    constituent-change audit records, while this table is the queryable
    time series for index level history.
"""

from __future__ import annotations

import argparse
import logging
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
    INDEX_PUB_CONNECT_ADDR,
    STATS_DB_FILE,
)
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_book_snapshot_request_msg,
    make_symbols_request_msg,
)

log = logging.getLogger(__name__)
_sql_log = logging.getLogger("edumatcher.stats.sql")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_INTERVAL_SEC = 15 * 60  # 15 minutes — overridable via --snapshot-interval
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0


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
# Per-index intraday accumulator
# ---------------------------------------------------------------------------


@dataclass
class _IndexDayAccum:
    """Holds intraday OHLC statistics for one index on one calendar date.

    Mirrors ``_DayAccum``'s day-rollover/upsert shape, but tracks index
    *level* (a computed, dimensionless value) rather than instrument price,
    and has no volume/trade_count concept — an index has no independent
    trades of its own, only updates driven by its constituents.
    """

    date: str  # ISO date string YYYY-MM-DD
    index_id: str

    open_level: Optional[float] = None
    high_level: Optional[float] = None
    low_level: Optional[float] = None
    close_level: Optional[float] = None

    open_aggregate_cap: Optional[float] = None
    close_aggregate_cap: Optional[float] = None

    update_count: int = 0

    def on_update(self, level: float, aggregate_cap: Optional[float]) -> None:
        if self.open_level is None:
            self.open_level = level
            self.open_aggregate_cap = aggregate_cap
        self.close_level = level
        self.close_aggregate_cap = aggregate_cap
        self.high_level = (
            level if self.high_level is None else max(self.high_level, level)
        )
        self.low_level = level if self.low_level is None else min(self.low_level, level)
        self.update_count += 1


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

CREATE TABLE IF NOT EXISTS index_daily_stats (
    date                TEXT NOT NULL,
    index_id            TEXT NOT NULL,
    open_level          REAL,
    high_level          REAL,
    low_level           REAL,
    close_level         REAL,
    open_aggregate_cap  REAL,
    close_aggregate_cap REAL,
    update_count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, index_id)
);

CREATE TABLE IF NOT EXISTS index_level_snapshots (
    ts              TEXT NOT NULL,
    index_id        TEXT NOT NULL,
    level           REAL NOT NULL,
    aggregate_cap   REAL,
    divisor         REAL,
    session_state   TEXT,
    day_open        REAL,
    day_high        REAL,
    day_low         REAL,
    PRIMARY KEY (ts, index_id)
);

CREATE INDEX IF NOT EXISTS idx_ids_index_ts ON index_level_snapshots(index_id, ts);
CREATE INDEX IF NOT EXISTS idx_ds_index_id_date ON index_daily_stats(index_id, date);
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

UPSERT_INDEX_DAILY = """
INSERT INTO index_daily_stats
    (date, index_id, open_level, high_level, low_level, close_level,
     open_aggregate_cap, close_aggregate_cap, update_count)
VALUES (?,?,?,?,?,?,?,?,?)
ON CONFLICT(date, index_id) DO UPDATE SET
    open_level          = excluded.open_level,
    high_level           = excluded.high_level,
    low_level            = excluded.low_level,
    close_level          = excluded.close_level,
    open_aggregate_cap   = excluded.open_aggregate_cap,
    close_aggregate_cap  = excluded.close_aggregate_cap,
    update_count         = excluded.update_count
"""

INSERT_INDEX_SNAPSHOT = """
INSERT OR IGNORE INTO index_level_snapshots
    (ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low)
VALUES (?,?,?,?,?,?,?,?,?)
"""


def _configure_sql_trace(conn: sqlite3.Connection, enabled: bool) -> None:
    """Enable/disable SQLite statement trace logging for this connection."""
    if not enabled:
        conn.set_trace_callback(None)
        return

    def _trace(statement: str) -> None:
        stmt = statement.strip()
        if not stmt:
            return
        _sql_log.debug("sqlite: %s", stmt)

    conn.set_trace_callback(_trace)


def _open_db(path: Path, *, sql_trace: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path = path.resolve()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    _configure_sql_trace(conn, enabled=sql_trace)
    conn.commit()
    log.info("opened stats DB connection path=%s", resolved_path)
    return conn


# ---------------------------------------------------------------------------
# Stats process
# ---------------------------------------------------------------------------


class StatsProcess:
    def __init__(
        self,
        db_path: Path,
        snapshot_interval_sec: float = SNAPSHOT_INTERVAL_SEC,
        sql_trace: bool = False,
    ) -> None:
        self._db_path = db_path
        self._sql_trace = bool(sql_trace)
        self._conn = _open_db(db_path, sql_trace=self._sql_trace)
        self._lock = threading.Lock()
        self._running = True
        self._snapshot_interval_sec = snapshot_interval_sec

        # symbol → _DayAccum for current calendar date
        self._accum: dict[str, _DayAccum] = {}

        # symbol → last snapshot mid_price (for % change)
        self._last_snap_mid: dict[str, float] = {}

        # symbol → timestamp of last snapshot written
        self._last_snap_ts: dict[str, float] = defaultdict(float)

        # index_id → _IndexDayAccum for current calendar date
        self._index_accum: dict[str, _IndexDayAccum] = {}

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
        # Separate socket: pm-index binds its own PUB endpoint, distinct from
        # the engine's PUB (mirrors md_gateway's two-subscriber pattern for
        # the same reason — index.update is not an engine topic).
        self.index_sub = make_subscriber(
            INDEX_PUB_CONNECT_ADDR,
            "index.update",
        )
        self.push = make_pusher(ENGINE_PULL_ADDR)
        self._push_lock = threading.Lock()
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()
        log.debug(
            "stats process initialized db=%s snapshot_interval=%ss sub=%s push=%s index_sub=%s",
            self._db_path,
            self._snapshot_interval_sec,
            ENGINE_PUB_ADDR,
            ENGINE_PULL_ADDR,
            INDEX_PUB_CONNECT_ADDR,
        )
        if self._sql_trace:
            log.info("SQLite SQL trace enabled for stats writer connection")

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
        log.debug("stats flow summary: %s", summary)
        self._debug_counts.clear()
        self._debug_last_summary = now

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

    def _index_accum_for(self, index_id: str) -> _IndexDayAccum:
        today = self._today()
        acc = self._index_accum.get(index_id)
        if acc is None or acc.date != today:
            # New day (or first time) — flush old if any
            if acc is not None:
                self._flush_index_daily(acc)
            acc = _IndexDayAccum(date=today, index_id=index_id)
            self._index_accum[index_id] = acc
        return acc

    def _flush_index_daily(self, acc: _IndexDayAccum) -> None:
        with self._conn:
            self._conn.execute(
                UPSERT_INDEX_DAILY,
                (
                    acc.date,
                    acc.index_id,
                    acc.open_level,
                    acc.high_level,
                    acc.low_level,
                    acc.close_level,
                    acc.open_aggregate_cap,
                    acc.close_aggregate_cap,
                    acc.update_count,
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
        self._dbg_count("trades_persisted")

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
            if now - self._last_snap_ts[symbol] >= self._snapshot_interval_sec:
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
                log.debug(
                    "wrote snapshot symbol=%s ts=%s",
                    symbol,
                    snap_ts,
                )
                self._dbg_count("snapshots_written")

    def _on_index_update(self, payload: dict[str, Any]) -> None:
        """Persist one throttled index.update event from pm-index.

        Every message received here already represents one throttled
        publication (pm-index applies its own publish_interval_sec before
        emitting index.update), so — unlike price_snapshots, which further
        throttles a firehose of book updates — every index.update we see is
        recorded as its own index_level_snapshots row with no additional
        throttling in pm-stats.
        """
        index_id = str(payload.get("index_id", "")).strip()
        level = payload.get("level")
        if not index_id or level is None:
            log.warning(
                "ignoring malformed index.update payload (missing index_id/level): %s",
                payload,
            )
            self._dbg_count("index_updates_ignored")
            return

        aggregate_cap = payload.get("aggregate_cap")
        divisor = payload.get("divisor")
        session_state = payload.get("session_state")
        day_open = payload.get("day_open")
        day_high = payload.get("day_high")
        day_low = payload.get("day_low")

        ts = datetime.fromtimestamp(
            payload.get("timestamp", time.time()), tz=timezone.utc
        ).isoformat(timespec="milliseconds")

        with self._lock:
            acc = self._index_accum_for(index_id)
            acc.on_update(level, aggregate_cap)
            self._flush_index_daily(acc)

            with self._conn:
                self._conn.execute(
                    INSERT_INDEX_SNAPSHOT,
                    (
                        ts,
                        index_id,
                        level,
                        aggregate_cap,
                        divisor,
                        session_state,
                        day_open,
                        day_high,
                        day_low,
                    ),
                )
        log.debug(
            "recorded index update index_id=%s level=%s session_state=%s ts=%s",
            index_id,
            level,
            session_state,
            ts,
        )
        self._dbg_count("index_updates_persisted")

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
            log.info(
                "EOD received; flushed %d symbol(s)",
                len(payload.get("books", [])),
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
        self._dbg_count("order_events_written")

    # ------------------------------------------------------------------
    # Main receive loop
    # ------------------------------------------------------------------

    def _receive(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        poller.register(self.index_sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                break

            if self.index_sub in socks:
                self._receive_one_index_message()

            if self.sub not in socks:
                continue
            try:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
            except Exception:
                continue

            self._dbg_count("messages_received")

            try:
                if topic.startswith("trade.executed"):
                    self._dbg_count("trade_topics")
                    self._on_trade(payload)
                elif topic.startswith("book."):
                    self._dbg_count("book_topics")
                    symbol = topic.split(".", 1)[1]
                    self._on_book(symbol, payload)
                elif topic == "system.eod":
                    self._dbg_count("eod_topics")
                    self._on_eod(payload)
                elif topic == "system.symbols.STATS":
                    self._dbg_count("startup_symbols_topics")
                    self._on_startup_symbols(payload)
                elif _is_order_event_topic(topic):
                    self._dbg_count("order_event_topics")
                    self._on_order_event(topic, payload)
            except Exception as exc:
                log.warning("error handling topic=%s err=%s", topic, exc)

    def _receive_one_index_message(self) -> None:
        try:
            frames = self.index_sub.recv_multipart()
            topic, payload = decode(frames)
        except Exception as exc:
            log.warning("failed to decode index_sub message: %s", exc)
            return

        self._dbg_count("index_messages_received")
        try:
            if topic == "index.update":
                self._dbg_count("index_update_topics")
                self._on_index_update(payload)
        except Exception as exc:
            log.warning("error handling index topic=%s err=%s", topic, exc)

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
            log.info("requested opening snapshots for: %s", ", ".join(symbols))

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
        log.debug("requested startup symbols for gateway_id=STATS")

        log.info("recording market statistics (Ctrl-C to stop)")
        try:
            while self._running:
                t.join(timeout=0.5)
        finally:
            # Wait for the receive thread to finish its current message before
            # closing the database and sockets to avoid mid-transaction errors.
            t.join(timeout=1.0)
            self.close()

    def _stop(self) -> None:
        self._running = False
        log.info("stopped")

    def close(self) -> None:
        self._flush_debug_summary(force=True)
        log.info("closing stats process")
        if hasattr(self, "_conn"):
            self._conn.close()
        if hasattr(self, "sub") and getattr(self.sub, "closed", False) is not True:
            self.sub.close()
        if (
            hasattr(self, "index_sub")
            and getattr(self.index_sub, "closed", False) is not True
        ):
            self.index_sub.close()
        if hasattr(self, "push") and getattr(self.push, "closed", False) is not True:
            self.push.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Never raise during GC finalization.
            pass


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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher statistics recorder")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-stats")
    parser.add_argument(
        "--db",
        default=str(STATS_DB_FILE),
        metavar="PATH",
        help=f"SQLite database path (default: {STATS_DB_FILE})",
    )
    parser.add_argument(
        "--snapshot-interval",
        type=float,
        default=SNAPSHOT_INTERVAL_SEC,
        metavar="SEC",
        help=(
            f"Seconds between price_snapshots rows per symbol "
            f"(default: {SNAPSHOT_INTERVAL_SEC} = 15 min). "
            "Use a smaller value for higher-resolution intraday history, "
            "e.g. 60 for one-minute snapshots."
        ),
    )
    parser.add_argument(
        "--sql-trace",
        action="store_true",
        help="Log executed SQLite statements from the stats writer connection",
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


def _enable_sql_trace_logging() -> None:
    """Install a dedicated handler for verbose SQLite statement tracing."""
    _sql_log.setLevel(logging.DEBUG)
    _sql_log.propagate = False
    if _sql_log.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    )
    _sql_log.addHandler(handler)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    log_level = _configure_logging(args)
    if args.sql_trace:
        _enable_sql_trace_logging()
    log.info("starting pm-stats with log level %s", logging.getLevelName(log_level))
    log.debug(
        "resolved stats config: db=%s snapshot_interval=%s",
        args.db,
        args.snapshot_interval,
    )
    if args.snapshot_interval <= 0:
        parser.error("--snapshot-interval must be greater than 0")
    try:
        process = StatsProcess(
            Path(args.db),
            snapshot_interval_sec=args.snapshot_interval,
            sql_trace=args.sql_trace,
        )
    except Exception as exc:
        log.error("fatal startup error: %s", exc)
        sys.exit(1)
    process.run()


if __name__ == "__main__":
    main()
