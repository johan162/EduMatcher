from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edumatcher.stats.main import SCHEMA
from edumatcher.stats.query import (
    open_readonly_connection,
    query_daily,
    query_dates,
    query_snapshots,
    query_symbols,
    query_trades,
)


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    conn.execute(
        "INSERT INTO daily_stats "
        "(date, symbol, open_price, high_price, low_price, close_price, volume, trade_count, vwap) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-06-14", "AAPL", 150.0, 153.25, 149.5, 152.75, 5000, 12, 151.82),
    )
    conn.execute(
        "INSERT INTO daily_stats "
        "(date, symbol, open_price, high_price, low_price, close_price, volume, trade_count, vwap) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-06-15", "AAPL", 153.0, 154.0, 151.0, 152.0, 2300, 7, 152.4),
    )

    conn.execute(
        "INSERT INTO price_snapshots (ts, symbol, mid_price, best_bid, best_ask, pct_change) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-14T09:00:00+00:00", "AAPL", 150.5, 150.0, 151.0, None),
    )
    conn.execute(
        "INSERT INTO price_snapshots (ts, symbol, mid_price, best_bid, best_ask, pct_change) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-14T09:15:00+00:00", "AAPL", 151.0, 150.5, 151.5, 0.3322),
    )
    conn.execute(
        "INSERT INTO price_snapshots (ts, symbol, mid_price, best_bid, best_ask, pct_change) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-14T09:30:00+00:00", "MSFT", 414.5, 414.0, 415.0, None),
    )

    conn.execute(
        "INSERT INTO trade_log "
        "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:00:01.000+00:00",
            "T-AAPL-1",
            "AAPL",
            150.0,
            100,
            "GW01",
            "GW02",
        ),
    )
    conn.execute(
        "INSERT INTO trade_log "
        "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:01:01.000+00:00",
            "T-ONLY-TRADELOG",
            "TSLA",
            250.0,
            20,
            "GW03",
            "GW04",
        ),
    )

    conn.commit()
    conn.close()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "stats.db"
    _seed_db(db_path)
    return db_path


def test_open_readonly_connection_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_readonly_connection(tmp_path / "missing.db")


def test_query_daily_uses_latest_date_when_date_missing(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_daily(conn, date_value=None, symbol=None, limit=100)
    conn.close()

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-15"


def test_query_daily_symbol_filter(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_daily(conn, date_value="2026-06-14", symbol="AAPL", limit=100)
    conn.close()

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_query_snapshots_filters_by_date_and_time_window(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_snapshots(
        conn,
        symbol="AAPL",
        date_value="2026-06-14",
        from_ts="2026-06-14T09:10:00+00:00",
        to_ts="2026-06-14T09:20:00+00:00",
        limit=500,
    )
    conn.close()

    assert len(rows) == 1
    assert rows[0]["ts"] == "2026-06-14T09:15:00+00:00"


def test_query_trades_symbol_and_date_filter(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_trades(
        conn,
        symbol="AAPL",
        date_value="2026-06-14",
        from_ts=None,
        to_ts=None,
        limit=200,
    )
    conn.close()

    assert len(rows) == 1
    assert rows[0]["trade_id"] == "T-AAPL-1"


def test_query_symbols_uses_union_across_tables(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_symbols(conn, date_value=None)
    conn.close()

    symbols = [row["symbol"] for row in rows]
    assert symbols == ["AAPL", "MSFT", "TSLA"]


def test_query_dates_uses_daily_stats_as_canonical_source(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_dates(conn, symbol=None)
    conn.close()

    dates = [row["date"] for row in rows]
    assert dates == ["2026-06-15", "2026-06-14"]
