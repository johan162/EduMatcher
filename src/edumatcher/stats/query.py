"""Read-only query helpers for pm-stats-cli."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _execute_fetchall(
    conn: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...]
) -> list[sqlite3.Row]:
    log.debug("executing SQL: %s | params=%s", sql, list(params))
    rows = conn.execute(sql, params).fetchall()
    log.debug("SQL returned %d row(s)", len(rows))
    return rows


def open_readonly_connection(db_path: Path) -> sqlite3.Connection:
    """Open stats SQLite DB in read-only mode."""
    if not db_path.exists():
        raise FileNotFoundError(f"Statistics DB not found: {db_path}")
    resolved_path = db_path.resolve()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    log.info("opened read-only stats DB connection path=%s", resolved_path)
    return conn


def validate_date(raw: str) -> None:
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {raw} (expected YYYY-MM-DD)") from exc


def validate_iso_ts(raw: str) -> None:
    candidate = raw.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            f"Invalid timestamp format: {raw} (expected ISO timestamp)"
        ) from exc


def latest_daily_date(conn: sqlite3.Connection) -> str | None:
    rows = _execute_fetchall(conn, "SELECT MAX(date) AS d FROM daily_stats", [])
    row = rows[0] if rows else None
    if row is None:
        return None
    value = row["d"]
    return str(value) if value is not None else None


def query_daily(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    symbol: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    selected_date = date_value or latest_daily_date(conn)
    if selected_date is None:
        return []

    sql = (
        "SELECT date, symbol, open_price, high_price, low_price, close_price, "
        "open_bid, open_ask, close_bid, close_ask, volume, trade_count, vwap, "
        "largest_trade_qty, largest_trade_price "
        "FROM daily_stats WHERE date = ?"
    )
    params: list[Any] = [selected_date]
    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)

    sql += " ORDER BY date DESC, symbol ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_snapshots(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT ts, symbol, mid_price, best_bid, best_ask, pct_change "
        "FROM price_snapshots WHERE symbol = ?"
    )
    params: list[Any] = [symbol]

    if date_value is not None:
        sql += " AND substr(ts, 1, 10) = ?"
        params.append(date_value)
    if from_ts is not None:
        sql += " AND ts >= ?"
        params.append(from_ts)
    if to_ts is not None:
        sql += " AND ts <= ?"
        params.append(to_ts)

    sql += " ORDER BY ts ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_trades(
    conn: sqlite3.Connection,
    *,
    symbol: str | None,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT ts, trade_id, symbol, price, quantity, buy_gateway_id, "
        "sell_gateway_id FROM trade_log WHERE 1=1"
    )
    params: list[Any] = []

    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    if date_value is not None:
        sql += " AND substr(ts, 1, 10) = ?"
        params.append(date_value)
    if from_ts is not None:
        sql += " AND ts >= ?"
        params.append(from_ts)
    if to_ts is not None:
        sql += " AND ts <= ?"
        params.append(to_ts)

    sql += " ORDER BY ts ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_order_events(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    symbol: str | None,
    event_type: str | None,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM order_events WHERE gateway_id = ?"
    params: list[Any] = [gateway_id]
    if symbol is not None:
        sql += " AND symbol = ?"
        params.append(symbol)
    if event_type is not None:
        sql += " AND event_type = ?"
        params.append(event_type)
    if date_value is not None:
        sql += " AND substr(ts, 1, 10) = ?"
        params.append(date_value)
    if from_ts is not None:
        sql += " AND ts >= ?"
        params.append(from_ts)
    if to_ts is not None:
        sql += " AND ts <= ?"
        params.append(to_ts)
    sql += " ORDER BY ts ASC, seq ASC LIMIT ?"
    params.append(limit)
    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_order_lifecycle(
    conn: sqlite3.Connection,
    *,
    gateway_id: str,
    order_id: str,
) -> list[dict[str, Any]]:
    rows = _execute_fetchall(
        conn,
        "SELECT * FROM order_events WHERE gateway_id = ? AND order_id = ? "
        "ORDER BY ts ASC, seq ASC",
        (gateway_id, order_id),
    )
    return [dict(row) for row in rows]


def query_symbols(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
) -> list[dict[str, Any]]:
    if date_value is None:
        sql = (
            "SELECT symbol FROM daily_stats "
            "UNION SELECT symbol FROM price_snapshots "
            "UNION SELECT symbol FROM trade_log "
            "ORDER BY symbol ASC"
        )
        params: list[Any] = []
    else:
        sql = (
            "SELECT symbol FROM daily_stats WHERE date = ? "
            "UNION SELECT symbol FROM price_snapshots WHERE substr(ts, 1, 10) = ? "
            "UNION SELECT symbol FROM trade_log WHERE substr(ts, 1, 10) = ? "
            "ORDER BY symbol ASC"
        )
        params = [date_value, date_value, date_value]

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_dates(
    conn: sqlite3.Connection,
    *,
    symbol: str | None,
) -> list[dict[str, Any]]:
    sql = "SELECT DISTINCT date FROM daily_stats"
    params: list[Any] = []
    if symbol is not None:
        sql += " WHERE symbol = ?"
        params.append(symbol)
    sql += " ORDER BY date DESC"

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def latest_index_daily_date(conn: sqlite3.Connection) -> str | None:
    rows = _execute_fetchall(conn, "SELECT MAX(date) AS d FROM index_daily_stats", [])
    row = rows[0] if rows else None
    if row is None:
        return None
    value = row["d"]
    return str(value) if value is not None else None


def query_index_daily(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
    index_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    selected_date = date_value or latest_index_daily_date(conn)
    if selected_date is None:
        return []

    sql = (
        "SELECT date, index_id, open_level, high_level, low_level, close_level, "
        "open_aggregate_cap, close_aggregate_cap, update_count "
        "FROM index_daily_stats WHERE date = ?"
    )
    params: list[Any] = [selected_date]
    if index_id is not None:
        sql += " AND index_id = ?"
        params.append(index_id)

    sql += " ORDER BY date DESC, index_id ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_index_snapshots(
    conn: sqlite3.Connection,
    *,
    index_id: str,
    date_value: str | None,
    from_ts: str | None,
    to_ts: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT ts, index_id, level, aggregate_cap, divisor, session_state, "
        "day_open, day_high, day_low "
        "FROM index_level_snapshots WHERE index_id = ?"
    )
    params: list[Any] = [index_id]

    if date_value is not None:
        sql += " AND substr(ts, 1, 10) = ?"
        params.append(date_value)
    if from_ts is not None:
        sql += " AND ts >= ?"
        params.append(from_ts)
    if to_ts is not None:
        sql += " AND ts <= ?"
        params.append(to_ts)

    sql += " ORDER BY ts ASC LIMIT ?"
    params.append(limit)

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]


def query_index_ids(
    conn: sqlite3.Connection,
    *,
    date_value: str | None,
) -> list[dict[str, Any]]:
    if date_value is None:
        sql = (
            "SELECT index_id FROM index_daily_stats "
            "UNION SELECT index_id FROM index_level_snapshots "
            "ORDER BY index_id ASC"
        )
        params: list[Any] = []
    else:
        sql = (
            "SELECT index_id FROM index_daily_stats WHERE date = ? "
            "UNION SELECT index_id FROM index_level_snapshots WHERE substr(ts, 1, 10) = ? "
            "ORDER BY index_id ASC"
        )
        params = [date_value, date_value]

    rows = _execute_fetchall(conn, sql, params)
    return [dict(row) for row in rows]
