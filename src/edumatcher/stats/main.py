"""
Statistics Process — records market data to a SQLite database.

Usage:
  poetry run pm-stats [--db data/stats.db] [--snapshot-interval SEC]
                      [--timezone TZ]

Dates and timestamps
--------------------
  ``ts`` columns are UTC instants. ``date`` columns hold the *trading date* —
  the calendar date in the exchange's session timezone (``--timezone``,
  default UTC) that the event's own timestamp falls on. Start pm-stats and
  pm-clearing with the same ``--timezone`` or their daily rollups will not
  reconcile. See edumatcher/stats/trading_day.py.

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
             close_session_state, open_aggregate_cap, close_aggregate_cap,
             update_count
    One row per (date, index_id), upserted on each index.update event.
    IMPORTANT: close_level (and close_session_state) reflect the *most
    recent* update received for that day, not necessarily the final EOD
    print. For today's date, while the session is still open, close_level
    is a live "last level so far" and will keep changing. It only becomes
    the true end-of-day close once no further updates arrive for that date
    — which is guaranteed once the date has rolled over, or can be
    confirmed immediately by checking close_session_state == "CLOSED"
    (set from pm-index's forced EOD publish). See pm-stats-cli's
    index-daily command and docs/user-guide/140-statistics-and-reporting.md
    for how to query this reliably.

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
from datetime import datetime, timezone, tzinfo
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
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    decode_sequence,
    make_book_snapshot_request_msg,
    make_symbols_request_msg,
)
from edumatcher.models.price import DEFAULT_TICK_DECIMALS
from edumatcher.stats.event_types import UNKNOWN_EVENT_TYPE
from edumatcher.stats.trading_day import (
    resolve_timezone,
    timezone_name,
    trading_date,
    trading_day_bounds,
)

_CLIENT_NAME = "pm-stats"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)
_sql_log = logging.getLogger("edumatcher.stats.sql")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_INTERVAL_SEC = 15 * 60  # 15 minutes — overridable via --snapshot-interval

#: Floor for --snapshot-interval. price_snapshots' primary key is (ts, symbol)
#: with ts at second precision, so one second is the finest resolution the
#: table can actually represent.
MIN_SNAPSHOT_INTERVAL_SEC = 1.0
_DEBUG_SUMMARY_INTERVAL_SEC = 5.0

# Receive high-water mark for both subscriber sockets. ZMQ's default of 1000
# messages is shallow for a recorder that also writes to SQLite between reads:
# a burst deeper than the mark is dropped silently at the socket. Matches the
# order of magnitude pm-log-srv already uses for its publisher.
_SUB_RCVHWM = 100_000


# ---------------------------------------------------------------------------
# Per-symbol intraday accumulator
# ---------------------------------------------------------------------------


@dataclass
class _DayAccum:
    """Holds intraday statistics for one symbol on one trading date.

    Every price here is an integer count of ticks, never display money. The
    engine matches in ticks and only converts to a float to publish, so
    converting straight back at ingress keeps the arithmetic exact: the day's
    turnover is an integer sum that cannot drift however many fills it spans.
    """

    date: str  # ISO date string YYYY-MM-DD
    symbol: str
    #: Decimal scale these ticks were captured at, carried through to the row
    #: so a reader can turn them back into display money.
    tick_decimals: int = DEFAULT_TICK_DECIMALS

    open_price: Optional[int] = None
    high_price: Optional[int] = None
    low_price: Optional[int] = None
    close_price: Optional[int] = None

    open_bid: Optional[int] = None
    open_ask: Optional[int] = None
    close_bid: Optional[int] = None
    close_ask: Optional[int] = None

    volume: int = 0
    trade_count: int = 0

    # VWAP numerator, sum(price_ticks * qty). An exact integer.
    _pv_sum: int = field(default=0, repr=False)
    _q_sum: int = field(default=0, repr=False)

    largest_trade_qty: int = 0
    largest_trade_price: Optional[int] = None

    def on_trade(self, price: int, qty: int) -> None:
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
        """Volume-weighted average price in ticks — derived, so a float.

        Both inputs are stored exactly, so a consumer needing full precision
        computes ``turnover / volume`` itself rather than reading this.
        """
        return self._pv_sum / self._q_sum if self._q_sum else None

    @property
    def turnover(self) -> int:
        """Traded notional in ticks x quantity — the exact VWAP numerator."""
        return self._pv_sum

    def restore_totals(self, *, trade_count: int, volume: int, pv_sum: int) -> None:
        """Seed the running totals from already-persisted trades.

        Used when rebuilding this accumulator after a restart. ``pv_sum`` is
        the VWAP numerator, ``sum(price * qty)``; the denominator is always
        the traded volume, so it is derived rather than passed separately.
        """
        self.trade_count = trade_count
        self.volume = volume
        self._pv_sum = pv_sum
        self._q_sum = volume

    def on_eod_book(self, best_bid: Optional[int], best_ask: Optional[int]) -> None:
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
    close_session_state: Optional[str] = None

    open_aggregate_cap: Optional[float] = None
    close_aggregate_cap: Optional[float] = None

    update_count: int = 0

    def on_update(
        self,
        level: float,
        aggregate_cap: Optional[float],
        session_state: Optional[str] = None,
    ) -> None:
        if self.open_level is None:
            self.open_level = level
            self.open_aggregate_cap = aggregate_cap
        self.close_level = level
        self.close_aggregate_cap = aggregate_cap
        # close_session_state mirrors close_level: it always reflects the
        # most recent update. It only means "final" once it equals CLOSED
        # (set by pm-index's forced EOD publish) — see the module docstring
        # and the index_daily_stats column comment below.
        self.close_session_state = session_state
        self.high_level = (
            level if self.high_level is None else max(self.high_level, level)
        )
        self.low_level = level if self.low_level is None else min(self.low_level, level)
        self.update_count += 1


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

#: Bumped whenever the DDL below changes in a way that makes an older file
#: unreadable, or whenever the *meaning* of stored values changes. Stamped into
#: ``PRAGMA user_version`` at creation and checked on every open — see
#: :func:`_check_schema_version`.
#:
#: 2 — ``order_events.event_type`` gained distinct accept/reject/cancel/status
#:     values for combo, OCO and quote events. The DDL is unchanged, but a file
#:     holding both the old collapsed values and the new ones would filter
#:     inconsistently, so old files are refused rather than appended to.
#: 3 — added ``feed_gaps``; ``trade_log``'s primary key widened from
#:     ``trade_id`` to ``(trade_id, ts)`` so post-restart id reuse is no longer
#:     silently discarded.
#: 4 — prices are stored as INTEGER ticks with a per-row ``tick_decimals``,
#:     replacing REAL display floats. Index levels stay REAL: a level is a
#:     computed, dimensionless number, not a price on a tick grid.
SCHEMA_VERSION = 4

#: Stream name recorded in ``feed_gaps.stream`` for engine trade prints.
TRADE_STREAM = "trade.executed"


def _payload_tick_decimals(payload: dict[str, Any]) -> int:
    """Read the tick scale a payload's display prices were produced at.

    Taken from the message rather than from the local tick registry: that
    registry is populated from engine config at startup, which pm-stats does
    not load, so trusting it would mean guessing. Every message carrying a
    price now carries its scale.
    """
    try:
        return int(payload.get("tick_decimals", DEFAULT_TICK_DECIMALS))
    except (TypeError, ValueError):
        return DEFAULT_TICK_DECIMALS


def _to_ticks(price: float | int | None, tick_decimals: int) -> Optional[int]:
    """Convert a published display price back to exact integer ticks.

    The engine holds the price as an integer and divides by 10^tick_decimals
    to publish it, so multiplying back and rounding to nearest recovers the
    original integer exactly — the float only ever has to be within half a
    tick of the true value, which it is by orders of magnitude.
    """
    if price is None:
        return None
    if isinstance(price, int):
        # Already ticks — the engine never publishes an int price, so this is
        # a caller passing through a value that was converted upstream.
        return price
    return int(round(price * (10**tick_decimals)))


SCHEMA = """
CREATE TABLE IF NOT EXISTS stats_meta (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT
);

-- Price columns below are INTEGER *ticks*, not display money. Divide by
-- 10^tick_decimals to get a display price. See the tick handling section of
-- docs/user-guide/140-statistics-and-reporting.md.
CREATE TABLE IF NOT EXISTS daily_stats (
    date                TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    open_price          INTEGER,
    high_price          INTEGER,
    low_price           INTEGER,
    close_price         INTEGER,
    open_bid            INTEGER,
    open_ask            INTEGER,
    close_bid           INTEGER,
    close_ask           INTEGER,
    volume              INTEGER NOT NULL DEFAULT 0,
    trade_count         INTEGER NOT NULL DEFAULT 0,
    -- Traded notional in ticks x quantity: sum(price_ticks * quantity). Exact,
    -- and the VWAP numerator — so vwap is exactly reproducible as
    -- turnover / volume without any float round-trip.
    turnover            INTEGER NOT NULL DEFAULT 0,
    -- Derived, therefore REAL: turnover / volume is a ratio and lands between
    -- ticks far more often than on one. The exact inputs are stored alongside,
    -- so a consumer needing full precision computes it rather than reading it.
    vwap                REAL,
    largest_trade_qty   INTEGER,
    largest_trade_price INTEGER,
    tick_decimals       INTEGER NOT NULL DEFAULT 2,
    PRIMARY KEY (date, symbol)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    ts            TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    -- Derived, therefore REAL and expressed in ticks: the midpoint of two
    -- adjacent ticks is a half tick, which no integer can hold. best_bid and
    -- best_ask beside it are exact.
    mid_price     REAL,
    best_bid      INTEGER,
    best_ask      INTEGER,
    -- A percentage, not money — never converted.
    pct_change    REAL,
    tick_decimals INTEGER NOT NULL DEFAULT 2,
    PRIMARY KEY (ts, symbol)
);

CREATE INDEX IF NOT EXISTS idx_ps_symbol_ts ON price_snapshots(symbol, ts);

CREATE TABLE IF NOT EXISTS trade_log (
    -- Composite identity (trade_id, ts). The engine's trade id is only unique
    -- *within a single engine run* — models/trade.py numbers trades with a
    -- per-process counter that restarts from 1 on every launch — so trade_id
    -- alone is NOT safe as a key. Keyed on trade_id alone, a run-2 trade "1"
    -- collides with a run-1 trade "1" and is silently discarded by INSERT OR
    -- IGNORE, understating volume for the rest of the day. Adding ts keeps a
    -- post-restart id reuse as a distinct row while still deduplicating a
    -- genuine duplicate delivery, which repeats both fields. This is the same
    -- defect clearing/store.py records as CL-C1.
    ts              TEXT NOT NULL,
    trade_id        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    price           INTEGER NOT NULL,
    quantity        INTEGER NOT NULL,
    tick_decimals   INTEGER NOT NULL DEFAULT 2,
    buy_gateway_id  TEXT,
    sell_gateway_id TEXT,
    -- Mirrored from the engine payload verbatim: BUY or SELL for a
    -- continuous match, AUCTION for an uncross print where both sides were
    -- resting and there is no true aggressor. Without this column the table
    -- cannot support trade classification or order-flow imbalance, and
    -- auction prints are indistinguishable from continuous ones.
    aggressor_side  TEXT,
    PRIMARY KEY (trade_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_tl_symbol_ts ON trade_log(symbol, ts);

CREATE TABLE IF NOT EXISTS feed_gaps (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    stream          TEXT    NOT NULL,
    -- The id we expected next, the one that actually arrived, and how many
    -- are unaccounted for between them.
    expected_id     INTEGER NOT NULL,
    received_id     INTEGER NOT NULL,
    missing_count   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fg_ts ON feed_gaps(ts);

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
    -- session_state as of the most recent update, i.e. the one that set
    -- close_level. Only means "close_level is final" when this is CLOSED;
    -- for the current trading day it will typically show CONTINUOUS or
    -- another intraday state until pm-index's forced EOD publish arrives.
    close_session_state TEXT,
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
     volume, trade_count, turnover, vwap,
     largest_trade_qty, largest_trade_price, tick_decimals)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
    turnover            = excluded.turnover,
    vwap                = excluded.vwap,
    largest_trade_qty   = excluded.largest_trade_qty,
    largest_trade_price = excluded.largest_trade_price,
    tick_decimals       = excluded.tick_decimals
"""

INSERT_SNAPSHOT = """
INSERT OR IGNORE INTO price_snapshots
    (ts, symbol, mid_price, best_bid, best_ask, pct_change, tick_decimals)
VALUES (?,?,?,?,?,?,?)
"""

INSERT_TRADE = """
INSERT OR IGNORE INTO trade_log
    (ts, trade_id, symbol, price, quantity, tick_decimals,
     buy_gateway_id, sell_gateway_id, aggressor_side)
VALUES (?,?,?,?,?,?,?,?,?)
"""

UPSERT_META = """
INSERT INTO stats_meta (key, value) VALUES (?,?)
ON CONFLICT(key) DO UPDATE SET value = excluded.value
"""

INSERT_FEED_GAP = """
INSERT INTO feed_gaps (ts, stream, expected_id, received_id, missing_count)
VALUES (?,?,?,?,?)
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
     close_session_state, open_aggregate_cap, close_aggregate_cap, update_count)
VALUES (?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(date, index_id) DO UPDATE SET
    open_level           = excluded.open_level,
    high_level           = excluded.high_level,
    low_level            = excluded.low_level,
    close_level          = excluded.close_level,
    close_session_state  = excluded.close_session_state,
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


_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
"""


class IncompatibleDatabaseError(RuntimeError):
    """Raised when an existing stats DB cannot be safely written to."""


class DatabaseInUseError(RuntimeError):
    """Raised when another pm-stats process already owns the database."""


def _acquire_writer_lock(db_path: Path) -> sqlite3.Connection:
    """Take an exclusive, process-lifetime lock on *db_path*.

    Two recorders against one file each keep their own in-memory rollup and
    overwrite the other's ``daily_stats`` rows, so the figures end up
    describing neither process. Nothing about that is visible in the output,
    which makes it worth refusing outright.

    The lock is an exclusive SQLite transaction on a sidecar ``.lock`` file
    rather than an OS file lock: ``fcntl`` is not available on Windows, which
    is a supported platform, whereas SQLite already implements whatever
    locking the host provides. It lives in a separate file because an
    exclusive transaction on ``stats.db`` itself would block every reader for
    as long as the recorder ran.

    Returns the connection holding the lock; closing it releases the lock, so
    the caller must keep it alive.
    """
    # This runs before _open_db, so it is now the first thing to touch the
    # path and owns creating the directory — otherwise pointing --db at a
    # not-yet-existing directory fails here instead of being created.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = db_path.with_name(db_path.name + ".lock")
    conn = sqlite3.connect(str(lock_path))
    # Fail immediately rather than waiting: a second recorder is a
    # configuration mistake, not congestion to be ridden out.
    conn.execute("PRAGMA busy_timeout = 0")
    try:
        conn.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        conn.close()
        raise DatabaseInUseError(
            f"another pm-stats process is already recording to {db_path} "
            f"(lock held on {lock_path}). Two recorders on one database "
            f"overwrite each other's daily rollups — use a different --db."
        ) from exc
    return conn


def _check_schema_version(conn: sqlite3.Connection, path: Path) -> bool:
    """Validate ``user_version``. Returns True if the file is newly created.

    A file whose version does not match this build is refused outright rather
    than opened optimistically. Silently writing new-format rows into an
    old-format file is exactly the kind of failure that produces a database
    that looks fine and reports wrong numbers.
    """
    found = int(conn.execute("PRAGMA user_version").fetchone()[0])
    is_new = found == 0 and not _has_tables(conn)
    if is_new:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return True
    if found != SCHEMA_VERSION:
        raise IncompatibleDatabaseError(
            f"{path} was written with statistics schema version {found}, "
            f"but this build requires version {SCHEMA_VERSION}. "
            f"Move or delete the file and let pm-stats create a new one."
        )
    return False


def _has_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchone()
    return bool(row[0])


def _reconcile_meta(conn: sqlite3.Connection, path: Path, session_tz_name: str) -> None:
    """Record the session timezone, or refuse if it contradicts the file.

    The session timezone determines which trading date every rollup is filed
    under, so it cannot change part-way through a database's life without
    making the ``date`` column mean two different things. Recording it also
    lets readers resolve it themselves instead of relying on every operator
    passing a matching ``--timezone``.
    """
    row = conn.execute(
        "SELECT value FROM stats_meta WHERE key = 'session_timezone'"
    ).fetchone()
    if row is not None and row[0] != session_tz_name:
        raise IncompatibleDatabaseError(
            f"{path} was recorded with session timezone {row[0]!r}, but "
            f"pm-stats was started with {session_tz_name!r}. Its date columns "
            f"would then mean two different things. Use --timezone {row[0]} or "
            f"record into a different --db."
        )
    conn.execute(UPSERT_META, ("session_timezone", session_tz_name))


def _open_db(
    path: Path,
    *,
    sql_trace: bool = False,
    session_tz_name: str = "UTC",
    snapshot_interval_sec: float = SNAPSHOT_INTERVAL_SEC,
) -> sqlite3.Connection:
    """Open the writer connection.

    WAL matters for correctness here, not just speed: in the default rollback
    journal a concurrent reader (pm-stats-cli, pm-ticker) holds a lock that
    makes the recorder's write fail, and the receive loop's catch-all handler
    would swallow that failure and silently drop the record. WAL lets readers
    and the single writer proceed together, and busy_timeout absorbs the brief
    exclusive lock taken during a checkpoint instead of failing instantly.
    Mirrors clearing/store.py, which already runs this way.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path = path.resolve()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    # Everything from here on can reject the file. Close the connection before
    # letting that escape: the caller only ever sees the exception, so it has
    # no handle to close, and the orphan lingers until GC (which on Python
    # 3.13+ also raises a "unclosed database" ResourceWarning).
    try:
        conn.executescript(_PRAGMAS)
        is_new = _check_schema_version(conn, resolved_path)
        conn.executescript(SCHEMA)
        _reconcile_meta(conn, resolved_path, session_tz_name)
        conn.execute(UPSERT_META, ("snapshot_interval_sec", str(snapshot_interval_sec)))
        conn.execute(UPSERT_META, ("recorder", _CLIENT_NAME))
        _configure_sql_trace(conn, enabled=sql_trace)
        conn.commit()
    except BaseException:
        conn.close()
        raise
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    log.info(
        "opened stats DB connection path=%s journal_mode=%s schema_version=%d "
        "session_timezone=%s%s",
        resolved_path,
        journal_mode,
        SCHEMA_VERSION,
        session_tz_name,
        " (new file)" if is_new else "",
    )
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
        session_tz: tzinfo = timezone.utc,
    ) -> None:
        self._db_path = db_path
        self._sql_trace = bool(sql_trace)
        # Taken before the database is opened, so a rejected second recorder
        # never touches the file at all.
        self._lock_conn = _acquire_writer_lock(db_path)
        try:
            self._conn = _open_db(
                db_path,
                sql_trace=self._sql_trace,
                session_tz_name=timezone_name(session_tz),
                snapshot_interval_sec=snapshot_interval_sec,
            )
        except BaseException:
            # A refused database must not leave the lock held, or a corrected
            # restart would report the file as in use by a process that no
            # longer exists.
            self._lock_conn.close()
            raise
        self._lock = threading.Lock()
        self._running = True
        self._snapshot_interval_sec = snapshot_interval_sec
        self._tz = session_tz
        # Set when the receive thread stops for any reason other than a clean
        # shutdown request, so run() can exit non-zero instead of reporting
        # success after having recorded nothing.
        self._receive_failure: str | None = None

        # symbol → _DayAccum for current calendar date
        self._accum: dict[str, _DayAccum] = {}

        # symbol → last snapshot mid_price (for % change)
        # symbol → mid_price of the last *persisted* snapshot row. The value
        # may be None: a row with no usable mid still becomes the baseline, so
        # pct_change always refers to the immediately preceding row.
        self._last_snap_mid: dict[str, Optional[float]] = {}

        # symbol → timestamp of last snapshot written
        # symbol → time.monotonic() of the last snapshot written. A plain dict
        # with an explicit "absent means never" check, not defaultdict(float):
        # monotonic() is seconds since boot on Linux/macOS, so a 0.0 default
        # made the first snapshot wait until the *host* had been up for a full
        # snapshot interval. On a fresh VM or container that silently skipped
        # the opening snapshot the startup book request exists to capture.
        self._last_snap_ts: dict[str, float] = {}

        # index_id → _IndexDayAccum for current calendar date
        self._index_accum: dict[str, _IndexDayAccum] = {}

        # Last engine trade id seen, for gap detection. None until the first
        # trade; _trade_seq_disabled latches when ids are not the engine's
        # numeric counter so the warning is logged once rather than per trade.
        self._last_trade_id: int | None = None
        self._trade_seq_disabled = False

        # topic -> last publisher sequence seen, for detecting drops on every
        # subscribed stream. _unsequenced_topics latches topics with no
        # sequence frame so the warning is logged once per topic.
        self._last_topic_seq: dict[str, int] = {}
        self._unsequenced_topics: set[str] = set()

        # Initialised before the sockets so close() is safe to call for
        # cleanup if socket construction fails part-way — it flushes the
        # debug counters, which must therefore already exist.
        self._push_lock = threading.Lock()
        self._debug_counts: defaultdict[str, int] = defaultdict(int)
        self._debug_last_summary = time.monotonic()

        # The database is already open at this point, and each socket after
        # the first compounds what is left dangling if a later one fails.
        # close() guards every attribute with hasattr, so it handles a
        # partially-built instance.
        try:
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
                rcvhwm=_SUB_RCVHWM,
            )
            # Separate socket: pm-index binds its own PUB endpoint, distinct
            # from the engine's PUB (mirrors md_gateway's two-subscriber
            # pattern for the same reason — index.update is not an engine
            # topic).
            self.index_sub = make_subscriber(
                INDEX_PUB_CONNECT_ADDR,
                "index.update",
                rcvhwm=_SUB_RCVHWM,
            )
            self.push = make_pusher(ENGINE_PULL_ADDR)
        except BaseException:
            self.close()
            raise

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
        """Count an event. Always counts; only the *summary* needs DEBUG.

        Counting used to be skipped entirely unless DEBUG was on, which meant
        a production run had no record of how many messages it handled or
        dropped — exactly the numbers you want when asking whether the
        recording is complete. A dict increment is far too cheap to gate.
        """
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

    def _check_topic_sequence(self, topic: str, seq: int | None) -> None:
        """Detect messages dropped between a publisher and this recorder.

        Publishers stamp a per-topic monotonic counter (``messaging/bus.py``),
        so a jump means ZeroMQ discarded messages at the high-water mark —
        the one failure mode that otherwise leaves no trace at all. Covers
        every subscribed stream, not just trades.

        A counter that moves *backwards* is a publisher restart, since
        sequences begin again at 1. Runs on the receive thread, outside the
        write lock, so it takes the lock itself.
        """
        if seq is None:
            if topic not in self._unsequenced_topics:
                self._unsequenced_topics.add(topic)
                log.warning(
                    "topic %s carries no sequence frame; loss on it cannot be "
                    "detected",
                    topic,
                )
            return

        last = self._last_topic_seq.get(topic)
        self._last_topic_seq[topic] = seq
        if last is None or seq <= last:
            if last is not None and seq <= last:
                log.info(
                    "%s sequence went from %d to %d — publisher restart",
                    topic,
                    last,
                    seq,
                )
            return
        missing = seq - last - 1
        if not missing:
            return

        log.error(
            "detected %d missing message(s) on %s: expected %d, received %d",
            missing,
            topic,
            last + 1,
            seq,
        )
        with self._lock, self._conn:
            self._conn.execute(
                INSERT_FEED_GAP,
                (
                    datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds"),
                    topic,
                    last + 1,
                    seq,
                    missing,
                ),
            )
        self._dbg_count("messages_missing", missing)

    def _check_trade_sequence(self, raw_id: str, ts: str) -> None:
        """Detect trades the recorder never received.

        The engine numbers trades with a monotonic counter starting at 1
        (``models/trade.py``), so a jump in the id means messages were lost
        between the engine and here — ZMQ PUB/SUB drops silently once a
        subscriber falls behind its high-water mark, and nothing else in the
        pipeline would reveal it. Recording the gap is what lets a reader
        distinguish "this is the whole session" from "this is what survived".

        The counter restarts at 1 on every engine run, so an id that moves
        *backwards* is a restart rather than a gap. Callers must hold the lock.
        """
        try:
            received = int(raw_id)
        except (TypeError, ValueError):
            # Not the engine's counter — a synthetic or gateway-supplied id.
            # Sequence checking does not apply; say so once, not per trade.
            if not self._trade_seq_disabled:
                self._trade_seq_disabled = True
                log.warning(
                    "trade id %r is not the engine's numeric counter; "
                    "trade-gap detection disabled for this run",
                    raw_id,
                )
            return

        last = self._last_trade_id
        self._last_trade_id = received
        if last is None:
            return
        if received <= last:
            log.info(
                "trade id went from %d to %d — engine restart; "
                "resuming gap detection from the new sequence",
                last,
                received,
            )
            return
        missing = received - last - 1
        if not missing:
            return

        log.error(
            "detected %d missing trade(s): expected id %d, received %d",
            missing,
            last + 1,
            received,
        )
        self._conn.execute(
            INSERT_FEED_GAP, (ts, TRADE_STREAM, last + 1, received, missing)
        )
        self._dbg_count("trades_missing", missing)

    def _note_tick_decimals(self, acc: _DayAccum, tick_decimals: int) -> None:
        """Record the scale this symbol's prices are being captured at.

        A symbol's tick size changing mid-day would silently make the day's
        integers incomparable with each other, so it is worth saying out loud
        rather than quietly re-scaling. Callers must hold the lock.
        """
        if acc.trade_count == 0 and acc.open_bid is None and acc.open_ask is None:
            acc.tick_decimals = tick_decimals
        elif acc.tick_decimals != tick_decimals:
            log.error(
                "%s tick_decimals changed from %d to %d mid-day; "
                "keeping %d so today's stored ticks stay comparable",
                acc.symbol,
                acc.tick_decimals,
                tick_decimals,
                acc.tick_decimals,
            )

    def _trading_date(self, epoch_sec: float) -> str:
        """Trading date for an instant, in the configured session timezone."""
        return trading_date(epoch_sec, self._tz)

    def _accum_for(self, symbol: str, day: str) -> _DayAccum:
        """Return the accumulator for *symbol* on trading date *day*.

        On the *first* touch in this process the accumulator is rebuilt from
        what is already in the database. Without that, a mid-session restart
        starts from a blank accumulator and the next flush overwrites the
        day's real open/high/low/volume/VWAP with post-restart-only figures —
        silently, and with volume going *down*.

        A same-process day rollover does not rehydrate: the outgoing day was
        fully accumulated in memory and has just been flushed, so the incoming
        day genuinely starts empty.
        """
        acc = self._accum.get(symbol)
        if acc is not None and acc.date == day:
            return acc
        if acc is None:
            acc = self._rehydrate_daily(symbol, day)
        else:
            self._flush_daily(acc)
            acc = _DayAccum(date=day, symbol=symbol)
        self._accum[symbol] = acc
        return acc

    def _rehydrate_daily(self, symbol: str, day: str) -> _DayAccum:
        """Rebuild one symbol's accumulator for *day* from persisted rows.

        Trade-derived fields come from ``trade_log`` rather than from
        ``daily_stats``: it is keyed on ``trade_id`` with ``INSERT OR IGNORE``,
        so it is a lossless per-trade record and reproduces the running sums
        exactly, including the VWAP numerator. The bid/ask fields have no
        per-event table behind them and are carried over from the existing
        ``daily_stats`` row.
        """
        acc = _DayAccum(date=day, symbol=symbol)
        day_start, day_end = trading_day_bounds(day, self._tz)
        window = (symbol, day_start, day_end)

        count, volume, pv_sum, acc.low_price, acc.high_price = self._conn.execute(
            "SELECT COUNT(*) , COALESCE(SUM(quantity), 0), "
            "COALESCE(SUM(price * quantity), 0), MIN(price), MAX(price) "
            "FROM trade_log WHERE symbol = ? AND ts >= ? AND ts < ?",
            window,
        ).fetchone()
        acc.restore_totals(trade_count=count, volume=volume, pv_sum=pv_sum)

        if acc.trade_count:
            acc.open_price = self._conn.execute(
                "SELECT price FROM trade_log WHERE symbol = ? AND ts >= ? AND ts < ? "
                "ORDER BY ts ASC, rowid ASC LIMIT 1",
                window,
            ).fetchone()[0]
            acc.close_price = self._conn.execute(
                "SELECT price FROM trade_log WHERE symbol = ? AND ts >= ? AND ts < ? "
                "ORDER BY ts DESC, rowid DESC LIMIT 1",
                window,
            ).fetchone()[0]
            # Ties go to the earliest trade, matching _DayAccum.on_trade's
            # strict `>` comparison.
            acc.largest_trade_qty, acc.largest_trade_price = self._conn.execute(
                "SELECT quantity, price FROM trade_log "
                "WHERE symbol = ? AND ts >= ? AND ts < ? "
                "ORDER BY quantity DESC, ts ASC, rowid ASC LIMIT 1",
                window,
            ).fetchone()

        quotes = self._conn.execute(
            "SELECT open_bid, open_ask, close_bid, close_ask, tick_decimals "
            "FROM daily_stats WHERE date = ? AND symbol = ?",
            (day, symbol),
        ).fetchone()
        if quotes is not None:
            (
                acc.open_bid,
                acc.open_ask,
                acc.close_bid,
                acc.close_ask,
                # Restored so the day continues on the scale its stored
                # integers were captured at, rather than silently reverting
                # to the default and mixing two scales in one row.
                acc.tick_decimals,
            ) = quotes

        if acc.trade_count or quotes is not None:
            log.info(
                "rehydrated %s for %s: %d trade(s), volume=%d",
                symbol,
                day,
                acc.trade_count,
                acc.volume,
            )
        return acc

    def _flush_daily(self, acc: _DayAccum) -> None:
        """Persist *acc* in its own transaction."""
        with self._conn:
            self._write_daily(acc)

    def _write_daily(self, acc: _DayAccum) -> None:
        """Persist *acc* without opening a transaction — caller owns one."""
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
                acc.turnover,
                acc.vwap,
                acc.largest_trade_qty,
                acc.largest_trade_price,
                acc.tick_decimals,
            ),
        )

    def _index_accum_for(self, index_id: str, day: str) -> _IndexDayAccum:
        """Index counterpart of :meth:`_accum_for`, with the same restart rule."""
        acc = self._index_accum.get(index_id)
        if acc is not None and acc.date == day:
            return acc
        if acc is None:
            acc = self._rehydrate_index_daily(index_id, day)
        else:
            self._flush_index_daily(acc)
            acc = _IndexDayAccum(date=day, index_id=index_id)
        self._index_accum[index_id] = acc
        return acc

    def _rehydrate_index_daily(self, index_id: str, day: str) -> _IndexDayAccum:
        """Rebuild one index's accumulator for *day* from persisted snapshots.

        ``update_count`` is recovered as the number of retained snapshot rows.
        ``index_level_snapshots`` inserts are ``OR IGNORE`` on ``(ts,
        index_id)``, so two updates landing in the same millisecond leave only
        one row and the recovered count can be a shade lower than the number
        of updates originally received.
        """
        acc = _IndexDayAccum(date=day, index_id=index_id)
        day_start, day_end = trading_day_bounds(day, self._tz)
        window = (index_id, day_start, day_end)

        acc.update_count, acc.low_level, acc.high_level = self._conn.execute(
            "SELECT COUNT(*), MIN(level), MAX(level) FROM index_level_snapshots "
            "WHERE index_id = ? AND ts >= ? AND ts < ?",
            window,
        ).fetchone()
        if not acc.update_count:
            return acc

        acc.open_level, acc.open_aggregate_cap = self._conn.execute(
            "SELECT level, aggregate_cap FROM index_level_snapshots "
            "WHERE index_id = ? AND ts >= ? AND ts < ? "
            "ORDER BY ts ASC, rowid ASC LIMIT 1",
            window,
        ).fetchone()
        (
            acc.close_level,
            acc.close_aggregate_cap,
            acc.close_session_state,
        ) = self._conn.execute(
            "SELECT level, aggregate_cap, session_state FROM index_level_snapshots "
            "WHERE index_id = ? AND ts >= ? AND ts < ? "
            "ORDER BY ts DESC, rowid DESC LIMIT 1",
            window,
        ).fetchone()
        log.info(
            "rehydrated index %s for %s: %d update(s)",
            index_id,
            day,
            acc.update_count,
        )
        return acc

    def _flush_index_daily(self, acc: _IndexDayAccum) -> None:
        """Persist *acc* in its own transaction."""
        with self._conn:
            self._write_index_daily(acc)

    def _write_index_daily(self, acc: _IndexDayAccum) -> None:
        """Persist *acc* without opening a transaction — caller owns one."""
        self._conn.execute(
            UPSERT_INDEX_DAILY,
            (
                acc.date,
                acc.index_id,
                acc.open_level,
                acc.high_level,
                acc.low_level,
                acc.close_level,
                acc.close_session_state,
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

        epoch_sec = payload.get("timestamp")
        if epoch_sec is None:
            epoch_sec = time.time()
            log.warning(
                "trade %s has no engine timestamp; using receipt time",
                payload.get("id", ""),
            )
        ts = datetime.fromtimestamp(epoch_sec, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )
        with self._lock:
            # Bucket on the trade's own timestamp, not on wall-clock time at
            # the moment of processing: a trade printed just before the
            # trading day rolls over must not be booked into the next day
            # because it happened to be handled a few milliseconds late.
            acc = self._accum_for(symbol, self._trading_date(epoch_sec))
            self._note_tick_decimals(acc, _payload_tick_decimals(payload))
            # Convert with the accumulator's scale, not the payload's, so the
            # integer written and the tick_decimals written beside it always
            # describe each other — even if a payload disagrees mid-day.
            tick_decimals = acc.tick_decimals
            price_ticks = _to_ticks(price, tick_decimals)
            assert price_ticks is not None  # price is not None, checked above
            acc.on_trade(price_ticks, qty)
            # One transaction for both writes. The rollup is reconstructed
            # from trade_log on restart, so committing them separately would
            # let a crash in between leave the two permanently disagreeing.
            with self._conn:
                # Inside the same transaction as the trade itself, so a
                # recorded gap can never survive without the trade that
                # revealed it, or vice versa.
                self._check_trade_sequence(str(payload.get("id", "")), ts)
                self._write_daily(acc)
                self._conn.execute(
                    INSERT_TRADE,
                    (
                        ts,
                        payload.get("id", ""),
                        symbol,
                        price_ticks,
                        qty,
                        tick_decimals,
                        payload.get("buy_gateway_id"),
                        payload.get("sell_gateway_id"),
                        payload.get("aggressor_side"),
                    ),
                )
        self._dbg_count("trades_persisted")

    def _on_book(self, symbol: str, payload: dict[str, Any]) -> None:
        # A book message is a snapshot of "now" and carries no timestamp of
        # its own, so receipt time is the event time.
        now_epoch = time.time()
        with self._lock:
            # Record opening bid/ask once per day
            acc = self._accum_for(symbol, self._trading_date(now_epoch))
            self._note_tick_decimals(acc, _payload_tick_decimals(payload))
            tick_decimals = acc.tick_decimals
            bids = payload.get("bids", [])
            asks = payload.get("asks", [])
            best_bid = _to_ticks(bids[0].get("price") if bids else None, tick_decimals)
            best_ask = _to_ticks(asks[0].get("price") if asks else None, tick_decimals)

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
            last_snap = self._last_snap_ts.get(symbol)
            if last_snap is None or now - last_snap >= self._snapshot_interval_sec:
                self._last_snap_ts[symbol] = now
                # In ticks, and a float: the midpoint of two adjacent ticks
                # is a half tick, which no integer can hold.
                mid: Optional[float] = None
                if best_bid is not None and best_ask is not None:
                    mid = (best_bid + best_ask) / 2
                elif best_bid is not None:
                    mid = float(best_bid)
                elif best_ask is not None:
                    mid = float(best_ask)
                elif payload.get("last_price") is not None:
                    last_ticks = _to_ticks(payload["last_price"], tick_decimals)
                    mid = None if last_ticks is None else float(last_ticks)

                # pct_change is the move since the *immediately preceding
                # persisted row* for this symbol, so a reader can reproduce it
                # from two consecutive rows. That means the baseline may only
                # advance once a row is actually written, and a row whose mid
                # is NULL becomes the new baseline rather than being skipped
                # over — otherwise a percentage silently spans several
                # intervals while still looking like a one-interval move.
                prev = self._last_snap_mid.get(symbol)
                pct = None
                if mid is not None and prev is not None and prev != 0:
                    pct = round((mid - prev) / prev * 100, 4)

                snap_ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
                with self._conn:
                    cursor = self._conn.execute(
                        INSERT_SNAPSHOT,
                        (
                            snap_ts,
                            symbol,
                            mid,
                            best_bid,
                            best_ask,
                            pct,
                            tick_decimals,
                        ),
                    )
                if not cursor.rowcount:
                    # INSERT OR IGNORE dropped it — another row already holds
                    # this (ts, symbol). Advancing the baseline to a value that
                    # was never stored would make the next row's percentage
                    # reference something absent from the table.
                    self._dbg_count("snapshots_deduplicated")
                    return
                self._last_snap_mid[symbol] = mid
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

        epoch_sec = payload.get("timestamp")
        if epoch_sec is None:
            # Receipt time is a different clock from the rest of the series;
            # silently mixing the two would make an index history that looks
            # continuous but is not.
            epoch_sec = time.time()
            log.warning(
                "index.update for %s has no timestamp; using receipt time",
                index_id,
            )
        ts = datetime.fromtimestamp(epoch_sec, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )

        with self._lock:
            acc = self._index_accum_for(index_id, self._trading_date(epoch_sec))
            acc.on_update(level, aggregate_cap, session_state)
            # Single transaction — the rollup is reconstructed from these
            # snapshot rows on restart, so the two must not diverge.
            with self._conn:
                self._write_index_daily(acc)
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
        day = self._trading_date(time.time())
        with self._lock:
            for book in payload.get("books", []):
                symbol = book.get("symbol", "")
                if not symbol:
                    continue
                acc = self._accum_for(symbol, day)
                self._note_tick_decimals(acc, _payload_tick_decimals(book))
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                best_bid = _to_ticks(
                    bids[0].get("price") if bids else None, acc.tick_decimals
                )
                best_ask = _to_ticks(
                    asks[0].get("price") if asks else None, acc.tick_decimals
                )
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
        # `or` would treat a legitimate quantity of 0 as absent and fall
        # through to `qty`, recording NULL when that is missing too.
        quantity = payload.get("quantity")
        if quantity is None:
            quantity = payload.get("qty")

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
                    quantity,
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
        """Poll both sockets until stopped.

        Any exit other than ``self._running`` going false is a failure that
        must stop the whole process. Leaving ``_running`` set here would park
        run() in a busy loop joining a dead thread: the process would stay up,
        keep logging "recording market statistics", record nothing at all, and
        eventually exit 0 — invisible to anything watching the process table.
        """
        try:
            self._receive_loop()
        except Exception as exc:
            self._receive_failure = f"{type(exc).__name__}: {exc}"
            log.exception("stats receive loop terminated")
        finally:
            self._running = False

    def _receive_loop(self) -> None:
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        poller.register(self.index_sub, zmq.POLLIN)
        while self._running:
            try:
                socks = dict(poller.poll(timeout=300))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                self._receive_failure = "interrupted while polling (EINTR)"
                return

            if self.index_sub in socks:
                self._receive_one_index_message()

            if self.sub not in socks:
                continue
            try:
                frames = self.sub.recv_multipart()
                topic, payload = decode(frames)
            except Exception as exc:
                log.warning("failed to decode engine message: %s", exc)
                self._dbg_count("messages_undecodable")
                continue

            self._dbg_count("messages_received")
            self._check_topic_sequence(topic, decode_sequence(frames))

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
                # Reaching here means the event was not persisted. That is a
                # dropped record, not a warning-level curiosity.
                log.error("failed to record topic=%s err=%s", topic, exc)
                self._dbg_count("records_dropped")

    def _receive_one_index_message(self) -> None:
        try:
            frames = self.index_sub.recv_multipart()
            topic, payload = decode(frames)
        except Exception as exc:
            log.warning("failed to decode index_sub message: %s", exc)
            return

        self._dbg_count("index_messages_received")
        self._check_topic_sequence(topic, decode_sequence(frames))
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

    def run(self) -> int:
        """Run until stopped. Returns the intended process exit code."""
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
            if t.is_alive():
                log.error(
                    "receive thread did not stop within 1s; "
                    "closing anyway may abort an in-flight write"
                )
            self.close()

        if self._receive_failure is not None:
            log.error("pm-stats stopped recording: %s", self._receive_failure)
            return 1
        return 0

    def _stop(self) -> None:
        self._running = False
        log.info("stopped")

    def _log_session_totals(self) -> None:
        """Report what this run actually recorded, at INFO.

        The per-interval summary is DEBUG-only, so without this a normal run
        ends having said nothing about how much it handled or dropped — the
        first question anyone asks when checking whether a session's figures
        are complete.
        """
        counts = getattr(self, "_debug_counts", None)
        if not counts:
            return
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        log.info("session totals: %s", summary)
        missing = counts.get("trades_missing", 0)
        if missing:
            log.error(
                "%d trade(s) were never received this session; see the "
                "feed_gaps table for the affected id ranges",
                missing,
            )

    def close(self) -> None:
        self._flush_debug_summary(force=True)
        self._log_session_totals()
        log.info("closing stats process")
        # Held so the connection cannot be closed out from under a receive
        # thread that is still inside a transaction.
        with self._lock:
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
        # Released last: no other recorder should be able to take over until
        # this one has finished writing and closed its sockets.
        if hasattr(self, "_lock_conn"):
            self._lock_conn.close()


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


def _accept_reject(
    topic: str,
    payload: dict[str, Any],
    accepted_value: str,
    rejected_value: str,
) -> str:
    """Resolve an ack-style event to its accepted or rejected type.

    A missing ``accepted`` flag records :data:`UNKNOWN_EVENT_TYPE` rather than
    falling through to the rejected value. Every one of these payloads carries
    the flag today, so its absence means a bug or a corrupted message — and
    writing a confident "rejected" into an audit trail on that basis fabricates
    a fact. Missing information is recoverable; wrong information is not.
    """
    accepted = payload.get("accepted")
    if accepted is None:
        log.error(
            "%s carries no 'accepted' flag; recording %s rather than assuming "
            "a rejection",
            topic,
            UNKNOWN_EVENT_TYPE,
        )
        return UNKNOWN_EVENT_TYPE
    return accepted_value if accepted else rejected_value


def _event_type_from_topic(topic: str, payload: dict[str, Any]) -> str:
    """Map a private engine topic to a normalized ``order_events.event_type``.

    Combo, OCO and quote topics resolve to their own accept / reject / cancel /
    status values instead of collapsing to a bare family name. Collapsing them
    made a rejected combo indistinguishable from an accepted one, and filed
    ``oco.cancelled`` under ``OCO``, where no cancel-oriented filter could
    find it.
    """
    if topic.startswith("order.ack."):
        return _accept_reject(topic, payload, "ACK", "REJECT")
    if topic.startswith("order.fill."):
        return "FILL"
    if topic.startswith("order.amended."):
        return "AMEND"
    if topic.startswith("order.cancelled."):
        return "CANCEL"
    if topic.startswith("order.expired."):
        return "EXPIRE"
    if topic.startswith("combo.ack."):
        return _accept_reject(topic, payload, "COMBO_ACK", "COMBO_REJECT")
    if topic.startswith("combo.status."):
        return "COMBO_STATUS"
    if topic.startswith("oco.ack."):
        return _accept_reject(topic, payload, "OCO_ACK", "OCO_REJECT")
    if topic.startswith("oco.cancelled."):
        return "OCO_CANCEL"
    if topic.startswith("quote.ack."):
        return _accept_reject(topic, payload, "QUOTE_ACK", "QUOTE_REJECT")
    if topic.startswith("quote.status."):
        return "QUOTE_STATUS"
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
        "--timezone",
        metavar="TZ",
        default="UTC",
        help=(
            "Exchange session timezone that defines the trading date used by "
            "the date columns of daily_stats and index_daily_stats (IANA name, "
            "e.g. Europe/Stockholm; default: UTC). Must match pm-clearing's "
            "--timezone or the two daily rollups will not reconcile."
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
        "resolved stats config: db=%s snapshot_interval=%s timezone=%s",
        args.db,
        args.snapshot_interval,
        args.timezone,
    )
    if args.snapshot_interval < MIN_SNAPSHOT_INTERVAL_SEC:
        # price_snapshots is keyed on (ts, symbol) at second precision, so a
        # sub-second interval asks for rows the table cannot hold: the extras
        # collide and INSERT OR IGNORE discards them without a word. Refuse
        # rather than accept a setting that silently does not work.
        parser.error(
            f"--snapshot-interval must be at least {MIN_SNAPSHOT_INTERVAL_SEC} "
            f"second: price_snapshots stores at most one row per second per "
            f"symbol, so a shorter interval would silently discard rows"
        )
    session_tz = resolve_timezone(args.timezone)
    if session_tz is None:
        parser.error(f"--timezone: unknown timezone {args.timezone!r}")
    try:
        process = StatsProcess(
            Path(args.db),
            snapshot_interval_sec=args.snapshot_interval,
            sql_trace=args.sql_trace,
            session_tz=session_tz,
        )
    except Exception as exc:
        log.error("fatal startup error: %s", exc)
        sys.exit(1)
    sys.exit(process.run())


if __name__ == "__main__":
    main()
