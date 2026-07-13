"""
SQLite schema, DDL helpers, write operations, and read-only queries
for the pm-clearing v2 process.

Separation of concerns
-----------------------
- ``apply_schema``         — idempotent DDL: create tables, indexes, views
- ``open_writer_connection``  — connection used by pm-clearing (read/write)
- ``open_readonly_connection``  — connection used by pm-clearing-cli
- ``flush_batch``          — atomic write of one buffer-worth of trades
- ``prune_old_events``     — delete trade_events rows older than N days
- ``query_*``              — read-only SELECT helpers for each CLI verb

Price note
----------
``trade.price`` arrives from the engine as an integer (raw int, no implicit
decimal scaling).  All price-derived columns (``price``, ``mark_price``,
``traded_notional``, ``buy_notional``, ``sell_notional``, ``net_amount``) are
stored as INTEGER.  Columns derived from weighted-average math (``avg_cost``,
``realized_pnl``, ``unrealized_pnl`` and their end-of-day variants) are REAL.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Pragmas — applied to every new connection.
# ---------------------------------------------------------------------------
_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;
"""

# ---------------------------------------------------------------------------
# Schema DDL — idempotent: safe to run on every startup.
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_events (
  -- Composite identity (id, ts_ns).  The engine's trade ``id`` is only unique
  -- *within a single engine run* (models/trade.py uses a per-process counter
  -- that restarts from 1 on every launch), so ``id`` alone is NOT safe as the
  -- archive's key.  A run-2 trade "1" would otherwise collide with a run-1
  -- trade "1" and be silently dropped by INSERT OR IGNORE (finding CL-C1).
  -- Keying on (id, ts_ns) means a genuine duplicate delivery repeats both and
  -- is deduped, while a post-restart id reuse carries a different timestamp and
  -- is preserved as a distinct row.
  id               TEXT    NOT NULL,
  ts_ns            INTEGER NOT NULL,
  trade_date       TEXT    NOT NULL,
  symbol           TEXT    NOT NULL,
  quantity         INTEGER NOT NULL,
  price            INTEGER NOT NULL,
    tick_decimals    INTEGER NOT NULL DEFAULT 2,
  buy_order_id     TEXT,
  sell_order_id    TEXT,
  buy_gateway_id   TEXT    NOT NULL,
  sell_gateway_id  TEXT    NOT NULL,
  aggressor_side   TEXT,
  ingest_ts_ns     INTEGER NOT NULL,
  PRIMARY KEY (id, ts_ns)
);

CREATE INDEX IF NOT EXISTS ix_trade_events_date
  ON trade_events(trade_date);
CREATE INDEX IF NOT EXISTS ix_trade_events_symbol_date
  ON trade_events(symbol, trade_date);
CREATE INDEX IF NOT EXISTS ix_trade_events_buy_gw_date
  ON trade_events(buy_gateway_id, trade_date);
CREATE INDEX IF NOT EXISTS ix_trade_events_sell_gw_date
  ON trade_events(sell_gateway_id, trade_date);

CREATE TABLE IF NOT EXISTS gateway_symbol_positions (
  gateway_id       TEXT    NOT NULL,
  symbol           TEXT    NOT NULL,
  net_qty          INTEGER NOT NULL,
  avg_cost         REAL    NOT NULL,
  realized_pnl     REAL    NOT NULL,
  unrealized_pnl   REAL    NOT NULL,
  mark_price       INTEGER,
    tick_decimals    INTEGER NOT NULL DEFAULT 2,
  buy_qty          INTEGER NOT NULL,
  sell_qty         INTEGER NOT NULL,
  buy_notional     INTEGER NOT NULL,
  sell_notional    INTEGER NOT NULL,
  last_trade_ts_ns INTEGER,
  updated_ts_ns    INTEGER NOT NULL,
  PRIMARY KEY (gateway_id, symbol)
);

CREATE INDEX IF NOT EXISTS ix_gsp_gateway
  ON gateway_symbol_positions(gateway_id);
CREATE INDEX IF NOT EXISTS ix_gsp_symbol
  ON gateway_symbol_positions(symbol);

CREATE TABLE IF NOT EXISTS gateway_daily_summary (
  trade_date         TEXT    NOT NULL,
  gateway_id         TEXT    NOT NULL,
  symbol             TEXT    NOT NULL,
  traded_qty         INTEGER NOT NULL,
  traded_notional    INTEGER NOT NULL,
  buy_qty            INTEGER NOT NULL,
  sell_qty           INTEGER NOT NULL,
  buy_notional       INTEGER NOT NULL,
  sell_notional      INTEGER NOT NULL,
  net_amount         INTEGER NOT NULL,
  realized_pnl       REAL    NOT NULL,
  end_net_qty        INTEGER NOT NULL,
  end_avg_cost       REAL    NOT NULL,
  end_unrealized_pnl REAL    NOT NULL,
    tick_decimals      INTEGER NOT NULL DEFAULT 2,
  last_trade_ts_ns   INTEGER,
  updated_ts_ns      INTEGER NOT NULL,
  PRIMARY KEY (trade_date, gateway_id, symbol)
);

CREATE INDEX IF NOT EXISTS ix_gds_gateway_date
  ON gateway_daily_summary(gateway_id, trade_date);
CREATE INDEX IF NOT EXISTS ix_gds_symbol_date
  ON gateway_daily_summary(symbol, trade_date);

CREATE VIEW IF NOT EXISTS gateway_pnl_totals AS
SELECT
  gateway_id,
  SUM(realized_pnl)                     AS realized_pnl_total,
  SUM(unrealized_pnl)                   AS unrealized_pnl_total,
  SUM(realized_pnl + unrealized_pnl)    AS total_pnl,
  SUM(net_qty)                          AS net_qty_total
FROM gateway_symbol_positions
GROUP BY gateway_id;

CREATE VIEW IF NOT EXISTS daily_exchange_totals AS
SELECT
  trade_date,
  SUM(traded_qty)       AS traded_qty_total,
  SUM(traded_notional)  AS traded_notional_total,
  SUM(net_amount)       AS net_amount_total,
  SUM(realized_pnl)     AS realized_pnl_total
FROM gateway_daily_summary
GROUP BY trade_date;

CREATE TABLE IF NOT EXISTS session_events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type   TEXT    NOT NULL,
  ts_ns        INTEGER NOT NULL,
  trade_date   TEXT    NOT NULL,
  payload_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_session_events_date
  ON session_events(trade_date);
CREATE INDEX IF NOT EXISTS ix_session_events_type
  ON session_events(event_type);

CREATE TABLE IF NOT EXISTS gateway_sessions (
  gateway_id        TEXT    NOT NULL,
  connected_at_ns   INTEGER NOT NULL,
  disconnected_at_ns INTEGER,
  disconnect_reason TEXT,
  PRIMARY KEY (gateway_id, connected_at_ns)
);

CREATE INDEX IF NOT EXISTS ix_gateway_sessions_gateway
  ON gateway_sessions(gateway_id);
"""

# ---------------------------------------------------------------------------
# Row dataclasses used by the flush pipeline.
# ---------------------------------------------------------------------------


@dataclass
class TradeEventRow:
    """One row to INSERT into trade_events."""

    id: str
    ts_ns: int
    trade_date: str
    symbol: str
    quantity: int
    price: int
    buy_order_id: str | None
    sell_order_id: str | None
    buy_gateway_id: str
    sell_gateway_id: str
    aggressor_side: str | None
    ingest_ts_ns: int
    tick_decimals: int = 2


@dataclass
class PositionRow:
    """Full current state for one (gateway_id, symbol) — replaces the existing row."""

    gateway_id: str
    symbol: str
    net_qty: int
    avg_cost: float
    realized_pnl: float
    unrealized_pnl: float
    mark_price: int | None
    buy_qty: int
    sell_qty: int
    buy_notional: int
    sell_notional: int
    last_trade_ts_ns: int | None
    updated_ts_ns: int
    tick_decimals: int = 2


@dataclass
class DailySummaryRow:
    """
    Incremental delta amounts + end-of-day snapshot for one
    (trade_date, gateway_id, symbol) key within the current flush batch.
    """

    trade_date: str
    gateway_id: str
    symbol: str
    # deltas — accumulated for all fills in this batch
    delta_traded_qty: int
    delta_traded_notional: int
    delta_buy_qty: int
    delta_sell_qty: int
    delta_buy_notional: int
    delta_sell_notional: int
    delta_net_amount: int
    delta_realized_pnl: float
    # snapshots — latest position state after this batch
    end_net_qty: int
    end_avg_cost: float
    end_unrealized_pnl: float
    last_trade_ts_ns: int | None
    updated_ts_ns: int
    tick_decimals: int = 2


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def apply_schema(conn: sqlite3.Connection) -> None:
    """Apply WAL pragmas and create all tables, indexes, and views."""
    conn.executescript(_PRAGMAS)
    conn.executescript(SCHEMA)
    _add_column_if_missing(
        conn, "trade_events", "tick_decimals", "INTEGER NOT NULL DEFAULT 2"
    )
    # Rebuild pre-CL-C1 trade_events (single-column ``id`` PRIMARY KEY) into the
    # collision-safe surrogate-key layout.  No-op for fresh or already-migrated
    # DBs.  Runs after the tick_decimals back-fill so legacy rows copy cleanly.
    _migrate_trade_events_schema(conn)
    _add_column_if_missing(
        conn,
        "gateway_symbol_positions",
        "tick_decimals",
        "INTEGER NOT NULL DEFAULT 2",
    )
    _add_column_if_missing(
        conn,
        "gateway_daily_summary",
        "tick_decimals",
        "INTEGER NOT NULL DEFAULT 2",
    )
    # Ensure session / gateway-lifecycle tables exist on DB files created
    # before these tables were added to SCHEMA.
    _create_table_if_missing(
        conn,
        "session_events",
        """
        CREATE TABLE IF NOT EXISTS session_events (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          event_type   TEXT    NOT NULL,
          ts_ns        INTEGER NOT NULL,
          trade_date   TEXT    NOT NULL,
          payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_session_events_date
          ON session_events(trade_date);
        CREATE INDEX IF NOT EXISTS ix_session_events_type
          ON session_events(event_type);
        """,
    )
    _create_table_if_missing(
        conn,
        "gateway_sessions",
        """
        CREATE TABLE IF NOT EXISTS gateway_sessions (
          gateway_id         TEXT    NOT NULL,
          connected_at_ns    INTEGER NOT NULL,
          disconnected_at_ns INTEGER,
          disconnect_reason  TEXT,
          PRIMARY KEY (gateway_id, connected_at_ns)
        );
        CREATE INDEX IF NOT EXISTS ix_gateway_sessions_gateway
          ON gateway_sessions(gateway_id);
        """,
    )


def _create_table_if_missing(
    conn: sqlite3.Connection,
    table: str,
    ddl: str,
) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if table not in existing:
        conn.executescript(ddl)


def _migrate_trade_events_schema(conn: sqlite3.Connection) -> None:
    """
    Migrate a legacy ``trade_events`` table (single-column ``id TEXT PRIMARY
    KEY``) to the CL-C1 layout (composite ``PRIMARY KEY (id, ts_ns)``).

    Detection is by primary-key composition: the legacy table has exactly one PK
    column (``id``) while the new one has two (``id``, ``ts_ns``).  This is a
    no-op on fresh databases (created directly from ``SCHEMA``) and on
    already-migrated ones.  Rows are copied with ``INSERT OR IGNORE`` on the new
    key, harmless for a well-formed legacy archive (its ids were already unique).
    """
    info = list(conn.execute("PRAGMA table_info(trade_events)"))
    if not info:
        return  # fresh DB — SCHEMA already built the new-layout table
    pk_columns = {row[1] for row in info if row[5]}  # row[5] = pk position (>0)
    if pk_columns == {"id", "ts_ns"}:
        return  # already the composite-key layout

    with conn:
        conn.execute("ALTER TABLE trade_events RENAME TO _trade_events_legacy")
        # SCHEMA's CREATE TABLE IF NOT EXISTS now builds the new-layout table
        # (the old name is free) and recreates the trade_events indexes.
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO trade_events ("
            "  id, ts_ns, trade_date, symbol, quantity, price, tick_decimals,"
            "  buy_order_id, sell_order_id, buy_gateway_id, sell_gateway_id,"
            "  aggressor_side, ingest_ts_ns"
            ") SELECT"
            "  id, ts_ns, trade_date, symbol, quantity, price,"
            "  COALESCE(tick_decimals, 2),"
            "  buy_order_id, sell_order_id, buy_gateway_id, sell_gateway_id,"
            "  aggressor_side, ingest_ts_ns"
            " FROM _trade_events_legacy"
        )
        conn.execute("DROP TABLE _trade_events_legacy")


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_ddl: str,
) -> None:
    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_ddl}")


def open_writer_connection(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the clearing DB for read/write access."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        apply_schema(conn)
    except Exception:
        conn.close()
        raise
    return conn


def open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    """Open an existing clearing DB in read-only mode for pm-clearing-cli."""
    if not db_path.exists():
        raise FileNotFoundError(f"Clearing DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

_INSERT_TRADE = """
INSERT OR IGNORE INTO trade_events (
  id, ts_ns, trade_date, symbol, quantity, price,
    tick_decimals,
  buy_order_id, sell_order_id,
  buy_gateway_id, sell_gateway_id,
  aggressor_side, ingest_ts_ns
) VALUES (
  :id, :ts_ns, :trade_date, :symbol, :quantity, :price,
    :tick_decimals,
  :buy_order_id, :sell_order_id,
  :buy_gateway_id, :sell_gateway_id,
  :aggressor_side, :ingest_ts_ns
)
"""

_UPSERT_POSITION = """
INSERT INTO gateway_symbol_positions (
  gateway_id, symbol,
  net_qty, avg_cost, realized_pnl, unrealized_pnl, mark_price,
    tick_decimals,
  buy_qty, sell_qty, buy_notional, sell_notional,
  last_trade_ts_ns, updated_ts_ns
) VALUES (
  :gateway_id, :symbol,
  :net_qty, :avg_cost, :realized_pnl, :unrealized_pnl, :mark_price,
    :tick_decimals,
  :buy_qty, :sell_qty, :buy_notional, :sell_notional,
  :last_trade_ts_ns, :updated_ts_ns
)
ON CONFLICT(gateway_id, symbol) DO UPDATE SET
  net_qty          = excluded.net_qty,
  avg_cost         = excluded.avg_cost,
  realized_pnl     = excluded.realized_pnl,
  unrealized_pnl   = excluded.unrealized_pnl,
  mark_price       = excluded.mark_price,
    tick_decimals    = excluded.tick_decimals,
  buy_qty          = excluded.buy_qty,
  sell_qty         = excluded.sell_qty,
  buy_notional     = excluded.buy_notional,
  sell_notional    = excluded.sell_notional,
  last_trade_ts_ns = excluded.last_trade_ts_ns,
  updated_ts_ns    = excluded.updated_ts_ns
"""

_UPSERT_DAILY = """
INSERT INTO gateway_daily_summary (
  trade_date, gateway_id, symbol,
  traded_qty, traded_notional,
  buy_qty, sell_qty, buy_notional, sell_notional, net_amount,
  realized_pnl,
  end_net_qty, end_avg_cost, end_unrealized_pnl,
    tick_decimals,
  last_trade_ts_ns, updated_ts_ns
) VALUES (
  :trade_date, :gateway_id, :symbol,
  :delta_traded_qty, :delta_traded_notional,
  :delta_buy_qty, :delta_sell_qty,
  :delta_buy_notional, :delta_sell_notional, :delta_net_amount,
  :delta_realized_pnl,
  :end_net_qty, :end_avg_cost, :end_unrealized_pnl,
    :tick_decimals,
  :last_trade_ts_ns, :updated_ts_ns
)
ON CONFLICT(trade_date, gateway_id, symbol) DO UPDATE SET
  traded_qty         = traded_qty         + excluded.traded_qty,
  traded_notional    = traded_notional    + excluded.traded_notional,
  buy_qty            = buy_qty            + excluded.buy_qty,
  sell_qty           = sell_qty           + excluded.sell_qty,
  buy_notional       = buy_notional       + excluded.buy_notional,
  sell_notional      = sell_notional      + excluded.sell_notional,
  net_amount         = (buy_notional      + excluded.buy_notional)
                       - (sell_notional   + excluded.sell_notional),
  realized_pnl       = realized_pnl       + excluded.realized_pnl,
  end_net_qty        = excluded.end_net_qty,
  end_avg_cost       = excluded.end_avg_cost,
  end_unrealized_pnl = excluded.end_unrealized_pnl,
    tick_decimals      = excluded.tick_decimals,
  last_trade_ts_ns   = MAX(last_trade_ts_ns, excluded.last_trade_ts_ns),
  updated_ts_ns      = excluded.updated_ts_ns
"""


def _record_id_collisions(
    conn: sqlite3.Connection, trades: list[TradeEventRow]
) -> None:
    """
    Write a ``session_events`` row of type ``ID_COLLISION`` for every incoming
    trade whose ``id`` already exists in the archive under a *different* ts_ns.

    This is the loud counterpart to the old silent ``INSERT OR IGNORE`` drop:
    the row is still archived (the surrogate PK + ``UNIQUE (id, ts_ns)`` key
    guarantee that), and the operator gets a durable, queryable alert that the
    engine reused a trade id across a restart.  Must be called inside the flush
    transaction, before the trade INSERT, so ``existing`` reflects prior state.
    """
    if not trades:
        return
    ids = [t.id for t in trades]
    placeholders = ",".join("?" * len(ids))
    existing: dict[str, set[int]] = {}
    for row in conn.execute(
        f"SELECT id, ts_ns FROM trade_events WHERE id IN ({placeholders})", ids
    ):
        existing.setdefault(row[0], set()).add(row[1])

    for t in trades:
        seen = existing.get(t.id)
        if seen and t.ts_ns not in seen:
            conn.execute(
                "INSERT INTO session_events"
                " (event_type, ts_ns, trade_date, payload_json)"
                " VALUES (?, ?, ?, ?)",
                (
                    "ID_COLLISION",
                    t.ts_ns,
                    t.trade_date,
                    json.dumps(
                        {
                            "id": t.id,
                            "new_ts_ns": t.ts_ns,
                            "existing_ts_ns": sorted(seen),
                        }
                    ),
                ),
            )


def flush_batch(
    conn: sqlite3.Connection,
    trades: list[TradeEventRow],
    positions: list[PositionRow],
    daily_rows: list[DailySummaryRow],
) -> None:
    """
    Atomically persist one buffer-worth of trades in a single transaction.

    Steps:
    0. Alert (not silently ignore) any incoming id that collides with an
       already-archived row carrying a different timestamp — the CL-C1
       engine-restart signature.
    1. INSERT OR IGNORE trade_events (idempotent on (id, ts_ns))
    2. UPSERT gateway_symbol_positions (full replace with current state)
    3. UPSERT gateway_daily_summary (increment deltas, update snapshots)
    4. COMMIT
    """
    with conn:
        _record_id_collisions(conn, trades)
        conn.executemany(
            _INSERT_TRADE,
            [_trade_row_to_dict(t) for t in trades],
        )
        conn.executemany(
            _UPSERT_POSITION,
            [_position_row_to_dict(p) for p in positions],
        )
        conn.executemany(
            _UPSERT_DAILY,
            [_daily_row_to_dict(d) for d in daily_rows],
        )


def fetch_all_positions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Return every persisted row of ``gateway_symbol_positions`` as a dict.

    Used at clearing startup to warm-start the in-memory ledger (finding CL-C4)
    so a restart accumulates onto durable position state instead of overwriting
    it from flat.  Every column the ledger needs to reconstruct a position is
    already stored, so no ``trade_events`` replay is required.
    """
    rows = conn.execute(
        "SELECT gateway_id, symbol, net_qty, avg_cost, realized_pnl,"
        " unrealized_pnl, mark_price, tick_decimals,"
        " buy_qty, sell_qty, buy_notional, sell_notional, last_trade_ts_ns"
        " FROM gateway_symbol_positions"
    ).fetchall()
    return [dict(r) for r in rows]


def prune_old_events(conn: sqlite3.Connection, retention_days: int = 90) -> int:
    """
    Delete trade_events rows older than ``retention_days`` days (UTC).

    Aggregate tables (gateway_daily_summary, gateway_symbol_positions) are
    NOT pruned — they remain for long-running reporting beyond the raw window.

    Returns the number of rows deleted.
    """
    cur = conn.execute(
        "DELETE FROM trade_events WHERE trade_date < date('now', ?)",
        (f"-{retention_days} days",),
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------------------
# Session-event and gateway-lifecycle write helpers
# ---------------------------------------------------------------------------


def record_session_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    ts_ns: int,
    trade_date: str,
    payload_json: str | None = None,
) -> None:
    """Insert one row into session_events (EOD marker, phase transition, etc.)."""
    conn.execute(
        "INSERT INTO session_events (event_type, ts_ns, trade_date, payload_json)"
        " VALUES (?, ?, ?, ?)",
        (event_type, ts_ns, trade_date, payload_json),
    )
    conn.commit()


def record_gateway_connect(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    connected_at_ns: int,
) -> None:
    """Insert a connect row into gateway_sessions."""
    conn.execute(
        "INSERT OR IGNORE INTO gateway_sessions"
        " (gateway_id, connected_at_ns)"
        " VALUES (?, ?)",
        (gateway_id, connected_at_ns),
    )
    conn.commit()


def record_gateway_disconnect(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    connected_at_ns: int,
    disconnected_at_ns: int,
    reason: str | None,
) -> None:
    """Update the matching connect row with disconnect timestamp and reason."""
    conn.execute(
        "UPDATE gateway_sessions"
        " SET disconnected_at_ns = ?, disconnect_reason = ?"
        " WHERE gateway_id = ? AND connected_at_ns = ?",
        (disconnected_at_ns, reason, gateway_id, connected_at_ns),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Private dict conversion helpers
# ---------------------------------------------------------------------------


def _trade_row_to_dict(t: TradeEventRow) -> dict[str, Any]:
    return {
        "id": t.id,
        "ts_ns": t.ts_ns,
        "trade_date": t.trade_date,
        "symbol": t.symbol,
        "quantity": t.quantity,
        "price": t.price,
        "tick_decimals": t.tick_decimals,
        "buy_order_id": t.buy_order_id,
        "sell_order_id": t.sell_order_id,
        "buy_gateway_id": t.buy_gateway_id,
        "sell_gateway_id": t.sell_gateway_id,
        "aggressor_side": t.aggressor_side,
        "ingest_ts_ns": t.ingest_ts_ns,
    }


def _position_row_to_dict(p: PositionRow) -> dict[str, Any]:
    return {
        "gateway_id": p.gateway_id,
        "symbol": p.symbol,
        "net_qty": p.net_qty,
        "avg_cost": p.avg_cost,
        "realized_pnl": p.realized_pnl,
        "unrealized_pnl": p.unrealized_pnl,
        "mark_price": p.mark_price,
        "tick_decimals": p.tick_decimals,
        "buy_qty": p.buy_qty,
        "sell_qty": p.sell_qty,
        "buy_notional": p.buy_notional,
        "sell_notional": p.sell_notional,
        "last_trade_ts_ns": p.last_trade_ts_ns,
        "updated_ts_ns": p.updated_ts_ns,
    }


def _daily_row_to_dict(d: DailySummaryRow) -> dict[str, Any]:
    return {
        "trade_date": d.trade_date,
        "gateway_id": d.gateway_id,
        "symbol": d.symbol,
        "delta_traded_qty": d.delta_traded_qty,
        "delta_traded_notional": d.delta_traded_notional,
        "delta_buy_qty": d.delta_buy_qty,
        "delta_sell_qty": d.delta_sell_qty,
        "delta_buy_notional": d.delta_buy_notional,
        "delta_sell_notional": d.delta_sell_notional,
        "delta_net_amount": d.delta_net_amount,
        "delta_realized_pnl": d.delta_realized_pnl,
        "end_net_qty": d.end_net_qty,
        "end_avg_cost": d.end_avg_cost,
        "end_unrealized_pnl": d.end_unrealized_pnl,
        "tick_decimals": d.tick_decimals,
        "last_trade_ts_ns": d.last_trade_ts_ns,
        "updated_ts_ns": d.updated_ts_ns,
    }


# ---------------------------------------------------------------------------
# Read-only query helpers (used by pm-clearing-cli)
# ---------------------------------------------------------------------------


def validate_date(raw: str) -> None:
    """Raise ValueError if ``raw`` is not a valid YYYY-MM-DD string."""
    import re

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError(f"Invalid date format: {raw!r} (expected YYYY-MM-DD)")


def query_gateways(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT gateway_id, realized_pnl_total, unrealized_pnl_total,"
        " total_pnl, net_qty_total"
        " FROM gateway_pnl_totals"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        " ORDER BY gateway_id ASC"
        " LIMIT :limit"
    )
    rows = conn.execute(sql, {"gateway": gateway, "limit": limit}).fetchall()
    return [dict(r) for r in rows]


def query_positions(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT gateway_id, symbol, net_qty, avg_cost, mark_price,"
        " tick_decimals,"
        " realized_pnl, unrealized_pnl,"
        " buy_qty, sell_qty, buy_notional, sell_notional,"
        " last_trade_ts_ns, updated_ts_ns"
        " FROM gateway_symbol_positions"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        "   AND (:symbol IS NULL OR symbol = :symbol)"
        " ORDER BY gateway_id ASC, symbol ASC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql, {"gateway": gateway, "symbol": symbol, "limit": limit}
    ).fetchall()
    return [dict(r) for r in rows]


def query_pnl(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT gateway_id, symbol, realized_pnl, unrealized_pnl,"
        " (realized_pnl + unrealized_pnl) AS total_pnl,"
        " net_qty, mark_price, tick_decimals"
        " FROM gateway_symbol_positions"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        "   AND (:symbol IS NULL OR symbol = :symbol)"
        " ORDER BY gateway_id ASC, symbol ASC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql, {"gateway": gateway, "symbol": symbol, "limit": limit}
    ).fetchall()
    return [dict(r) for r in rows]


def query_daily(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    date_value: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT trade_date, gateway_id, symbol,"
        " traded_qty, traded_notional,"
        " buy_qty, sell_qty, buy_notional, sell_notional, net_amount,"
        " realized_pnl, end_net_qty, end_avg_cost, end_unrealized_pnl,"
        " tick_decimals,"
        " last_trade_ts_ns, updated_ts_ns"
        " FROM gateway_daily_summary"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        "   AND (:symbol IS NULL OR symbol = :symbol)"
        "   AND (:date_value IS NULL OR trade_date = :date_value)"
        "   AND (:from_date IS NULL OR trade_date >= :from_date)"
        "   AND (:to_date IS NULL OR trade_date <= :to_date)"
        " ORDER BY trade_date DESC, gateway_id ASC, symbol ASC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql,
        {
            "gateway": gateway,
            "symbol": symbol,
            "date_value": date_value,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def query_trades(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    date_value: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, ts_ns, trade_date, symbol, quantity, price, tick_decimals,"
        " buy_order_id, sell_order_id,"
        " buy_gateway_id, sell_gateway_id,"
        " aggressor_side, ingest_ts_ns"
        " FROM trade_events"
        " WHERE (:symbol IS NULL OR symbol = :symbol)"
        "   AND (:gateway IS NULL OR buy_gateway_id = :gateway"
        "       OR sell_gateway_id = :gateway)"
        "   AND (:date_value IS NULL OR trade_date = :date_value)"
        "   AND (:from_date IS NULL OR trade_date >= :from_date)"
        "   AND (:to_date IS NULL OR trade_date <= :to_date)"
        " ORDER BY ts_ns DESC, id ASC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql,
        {
            "gateway": gateway,
            "symbol": symbol,
            "date_value": date_value,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        },
    ).fetchall()
    return [dict(r) for r in rows]


# Sort-field whitelists — map CLI string to ORDER BY clause.
_EXPOSURE_SORT: dict[str, str] = {
    "gross_notional": "ABS(net_qty * mark_price) DESC, gateway_id ASC, symbol ASC",
    "net_notional": "(net_qty * mark_price) DESC, gateway_id ASC, symbol ASC",
    "realized_pnl": "realized_pnl DESC, gateway_id ASC, symbol ASC",
    "unrealized_pnl": "unrealized_pnl DESC, gateway_id ASC, symbol ASC",
    "total_pnl": "(realized_pnl + unrealized_pnl) DESC, gateway_id ASC, symbol ASC",
}

_SYMBOLS_SORT: dict[str, str] = {
    "symbol": "d.symbol ASC",
    "traded_qty": "d.traded_qty DESC, d.symbol ASC",
    "traded_notional": "d.traded_notional DESC, d.symbol ASC",
    "realized_pnl": "d.realized_pnl DESC, d.symbol ASC",
    "open_net_qty": "o.open_net_qty DESC, d.symbol ASC",
}


def query_exposure(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    sort: str = "gross_notional",
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if sort not in _EXPOSURE_SORT:
        raise ValueError(
            f"Invalid --sort value {sort!r}. Allowed: {sorted(_EXPOSURE_SORT)}"
        )
    order_by = _EXPOSURE_SORT[sort]
    sql = (
        "SELECT gateway_id, symbol, net_qty, mark_price, tick_decimals,"
        " (net_qty * mark_price) AS net_notional,"
        " ABS(net_qty * mark_price) AS gross_notional,"
        " realized_pnl, unrealized_pnl,"
        " (realized_pnl + unrealized_pnl) AS total_pnl"
        " FROM gateway_symbol_positions"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        "   AND (:symbol IS NULL OR symbol = :symbol)"
        f" ORDER BY {order_by}"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql, {"gateway": gateway, "symbol": symbol, "limit": limit}
    ).fetchall()
    return [dict(r) for r in rows]


def query_symbols(
    conn: sqlite3.Connection,
    *,
    date_value: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    sort: str = "symbol",
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if sort not in _SYMBOLS_SORT:
        raise ValueError(
            f"Invalid --sort value {sort!r}. Allowed: {sorted(_SYMBOLS_SORT)}"
        )
    order_by = _SYMBOLS_SORT[sort]
    sql = (
        "WITH daily_totals AS ("
        "  SELECT symbol,"
        "    SUM(traded_qty) AS traded_qty,"
        "    SUM(traded_notional) AS traded_notional,"
        "    SUM(realized_pnl) AS realized_pnl,"
        "    MAX(tick_decimals) AS tick_decimals"
        "  FROM gateway_daily_summary"
        "  WHERE (:date_value IS NULL OR trade_date = :date_value)"
        "    AND (:from_date IS NULL OR trade_date >= :from_date)"
        "    AND (:to_date IS NULL OR trade_date <= :to_date)"
        "  GROUP BY symbol"
        "),"
        "open_totals AS ("
        "  SELECT symbol,"
        "    SUM(net_qty) AS open_net_qty,"
        "    SUM(unrealized_pnl) AS open_unrealized_pnl"
        "  FROM gateway_symbol_positions"
        "  GROUP BY symbol"
        ")"
        " SELECT d.symbol, d.traded_qty, d.traded_notional, d.realized_pnl,"
        "  d.tick_decimals,"
        "  COALESCE(o.open_net_qty, 0) AS open_net_qty,"
        "  COALESCE(o.open_unrealized_pnl, 0.0) AS open_unrealized_pnl"
        " FROM daily_totals d"
        " LEFT JOIN open_totals o ON o.symbol = d.symbol"
        f" ORDER BY {order_by}"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql,
        {
            "date_value": date_value,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def query_dates(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    with_totals: bool = False,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    if with_totals:
        sql = (
            "SELECT trade_date, traded_qty_total,"
            " traded_notional_total, net_amount_total"
            " FROM daily_exchange_totals"
            " WHERE (:from_date IS NULL OR trade_date >= :from_date)"
            "   AND (:to_date IS NULL OR trade_date <= :to_date)"
            " ORDER BY trade_date DESC"
            " LIMIT :limit"
        )
        rows = conn.execute(
            sql, {"from_date": from_date, "to_date": to_date, "limit": limit}
        ).fetchall()
    else:
        sql = (
            "SELECT DISTINCT trade_date"
            " FROM trade_events"
            " WHERE (:symbol IS NULL OR symbol = :symbol)"
            "   AND (:gateway IS NULL OR buy_gateway_id = :gateway"
            "       OR sell_gateway_id = :gateway)"
            "   AND (:from_date IS NULL OR trade_date >= :from_date)"
            "   AND (:to_date IS NULL OR trade_date <= :to_date)"
            " ORDER BY trade_date DESC"
            " LIMIT :limit"
        )
        rows = conn.execute(
            sql,
            {
                "symbol": symbol,
                "gateway": gateway,
                "from_date": from_date,
                "to_date": to_date,
                "limit": limit,
            },
        ).fetchall()
    return [dict(r) for r in rows]


def query_health(
    conn: sqlite3.Connection,
    db_path: Path,
) -> list[dict[str, Any]]:
    wal_mode_row = conn.execute("PRAGMA journal_mode").fetchone()
    wal_mode = wal_mode_row[0] if wal_mode_row else "unknown"

    row = conn.execute("""
        WITH
        trade_rows AS (
          SELECT COUNT(*) AS c, MAX(ts_ns) AS max_ts FROM trade_events
        ),
        gsp_rows AS (
          SELECT COUNT(*) AS c FROM gateway_symbol_positions
        ),
        gds_rows AS (
          SELECT COUNT(*) AS c, MAX(updated_ts_ns) AS max_flush
          FROM gateway_daily_summary
        )
        SELECT
          trade_rows.c    AS trade_events_rows,
          gsp_rows.c      AS gateway_symbol_positions_rows,
          gds_rows.c      AS gateway_daily_summary_rows,
          trade_rows.max_ts   AS last_trade_ts_ns,
          gds_rows.max_flush  AS last_flush_ts_ns
        FROM trade_rows, gsp_rows, gds_rows
        """).fetchone()

    result = dict(row) if row else {}
    result["db_path"] = str(db_path)
    result["wal_mode"] = wal_mode
    return [result]


def query_session_events(
    conn: sqlite3.Connection,
    *,
    event_type: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Return rows from session_events (EOD markers, phase transitions).

    Filtering by event_type allows targeted queries such as:
      event_type='EOD'   — end-of-day markers only
      event_type='PHASE' — session-phase transitions only
    """
    sql = (
        "SELECT id, event_type, ts_ns, trade_date, payload_json"
        " FROM session_events"
        " WHERE (:event_type IS NULL OR event_type = :event_type)"
        "   AND (:from_date IS NULL OR trade_date >= :from_date)"
        "   AND (:to_date IS NULL OR trade_date <= :to_date)"
        " ORDER BY ts_ns DESC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql,
        {
            "event_type": event_type,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def query_sessions(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    connected_only: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Return gateway connection/disconnection history from gateway_sessions.

    connected_only=True filters to sessions where disconnected_at_ns IS NULL
    (gateways still connected or whose disconnect was not recorded).
    """
    sql = (
        "SELECT gateway_id, connected_at_ns, disconnected_at_ns, disconnect_reason,"
        "  date(connected_at_ns / 1000000000, 'unixepoch') AS connect_date"
        " FROM gateway_sessions"
        " WHERE (:gateway IS NULL OR gateway_id = :gateway)"
        "   AND (:connected_only = 0 OR disconnected_at_ns IS NULL)"
        "   AND (:from_date IS NULL"
        "       OR date(connected_at_ns / 1000000000, 'unixepoch') >= :from_date)"
        "   AND (:to_date IS NULL"
        "       OR date(connected_at_ns / 1000000000, 'unixepoch') <= :to_date)"
        " ORDER BY connected_at_ns DESC"
        " LIMIT :limit"
    )
    rows = conn.execute(
        sql,
        {
            "gateway": gateway,
            "connected_only": 1 if connected_only else 0,
            "from_date": from_date,
            "to_date": to_date,
            "limit": limit,
        },
    ).fetchall()
    return [dict(r) for r in rows]


def query_reconcile(
    conn: sqlite3.Connection,
    *,
    gateway: str | None = None,
    symbol: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    """
    Compare raw trade_events totals against gateway_daily_summary aggregates
    for both the buy side and the sell side.

    Returns rows only where a discrepancy is found.  Zero rows means the
    dataset is internally consistent for all (trade_date, gateway_id, symbol)
    keys on both sides.

    Output columns:
      side              — 'BUY' or 'SELL'
      trade_date        — date bucket
      gateway_id        — gateway identifier
      symbol            — instrument
      raw_qty           — quantity counted directly from trade_events
      summary_qty       — quantity stored in gateway_daily_summary
      qty_diff          — raw_qty - summary_qty (non-zero = discrepancy)
      raw_notional      — notional counted directly from trade_events
      summary_notional  — notional stored in gateway_daily_summary
      notional_diff     — raw_notional - summary_notional
    """
    sql = """
    WITH
    -- Buy-side raw counts from trade_events
    raw_buy AS (
      SELECT
        'BUY'            AS side,
        trade_date,
        buy_gateway_id   AS gateway_id,
        symbol,
        SUM(quantity)            AS raw_qty,
        SUM(quantity * price)    AS raw_notional
      FROM trade_events
      WHERE (:from_date IS NULL OR trade_date >= :from_date)
        AND (:to_date   IS NULL OR trade_date <= :to_date)
        AND (:gateway   IS NULL OR buy_gateway_id = :gateway)
        AND (:symbol    IS NULL OR symbol = :symbol)
      GROUP BY trade_date, buy_gateway_id, symbol
    ),
    -- Sell-side raw counts from trade_events
    raw_sell AS (
      SELECT
        'SELL'           AS side,
        trade_date,
        sell_gateway_id  AS gateway_id,
        symbol,
        SUM(quantity)            AS raw_qty,
        SUM(quantity * price)    AS raw_notional
      FROM trade_events
      WHERE (:from_date IS NULL OR trade_date >= :from_date)
        AND (:to_date   IS NULL OR trade_date <= :to_date)
        AND (:gateway   IS NULL OR sell_gateway_id = :gateway)
        AND (:symbol    IS NULL OR symbol = :symbol)
      GROUP BY trade_date, sell_gateway_id, symbol
    ),
    -- Union both sides into a single raw set
    raw_all AS (
      SELECT * FROM raw_buy
      UNION ALL
      SELECT * FROM raw_sell
    ),
    -- Summary aggregates for buy and sell sides from gateway_daily_summary
    summary_buy AS (
      SELECT
        'BUY'        AS side,
        trade_date,
        gateway_id,
        symbol,
        buy_qty      AS summary_qty,
        buy_notional AS summary_notional
      FROM gateway_daily_summary
      WHERE (:from_date IS NULL OR trade_date >= :from_date)
        AND (:to_date   IS NULL OR trade_date <= :to_date)
        AND (:gateway   IS NULL OR gateway_id = :gateway)
        AND (:symbol    IS NULL OR symbol = :symbol)
    ),
    summary_sell AS (
      SELECT
        'SELL'        AS side,
        trade_date,
        gateway_id,
        symbol,
        sell_qty      AS summary_qty,
        sell_notional AS summary_notional
      FROM gateway_daily_summary
      WHERE (:from_date IS NULL OR trade_date >= :from_date)
        AND (:to_date   IS NULL OR trade_date <= :to_date)
        AND (:gateway   IS NULL OR gateway_id = :gateway)
        AND (:symbol    IS NULL OR symbol = :symbol)
    ),
    summary_all AS (
      SELECT * FROM summary_buy
      UNION ALL
      SELECT * FROM summary_sell
    )
    SELECT
      r.side,
      r.trade_date,
      r.gateway_id,
      r.symbol,
      r.raw_qty,
      COALESCE(s.summary_qty, 0)       AS summary_qty,
      (r.raw_qty - COALESCE(s.summary_qty, 0)) AS qty_diff,
      r.raw_notional,
      COALESCE(s.summary_notional, 0)  AS summary_notional,
      ROUND(
        r.raw_notional - COALESCE(s.summary_notional, 0),
        8
      ) AS notional_diff
    FROM raw_all r
    LEFT JOIN summary_all s
      ON  s.side       = r.side
      AND s.trade_date = r.trade_date
      AND s.gateway_id = r.gateway_id
      AND s.symbol     = r.symbol
    WHERE ABS(r.raw_qty - COALESCE(s.summary_qty, 0)) > 0
       -- Notional values are stored as REAL after dividing by tick scale, so
       -- floating-point rounding can produce sub-cent differences.  0.0001 is
       -- well below any meaningful tick increment (minimum tick = 0.01) while
       -- still catching genuine mismatches.
       OR ABS(r.raw_notional - COALESCE(s.summary_notional, 0)) > 0.0001
    ORDER BY r.trade_date ASC, r.side ASC, r.gateway_id ASC, r.symbol ASC
    """
    rows = conn.execute(
        sql,
        {
            "from_date": from_date,
            "to_date": to_date,
            "gateway": gateway,
            "symbol": symbol,
        },
    ).fetchall()
    return [dict(r) for r in rows]
