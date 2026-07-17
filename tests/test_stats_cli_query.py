from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edumatcher.stats.main import SCHEMA
from edumatcher.stats.query import (
    open_readonly_connection,
    query_daily,
    query_dates,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
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

    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14",
            "EDU100",
            1042.10,
            1056.30,
            1040.05,
            1048.73,
            7.3e12,
            7.35e12,
            512,
        ),
    )
    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-15",
            "EDU100",
            1048.73,
            1060.00,
            1045.00,
            1055.20,
            7.35e12,
            7.4e12,
            480,
        ),
    )
    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-06-14", "EDUFIN", 500.0, 505.0, 498.0, 502.0, 1.2e12, 1.21e12, 300),
    )

    conn.execute(
        "INSERT INTO index_level_snapshots "
        "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:00:00.000+00:00",
            "EDU100",
            1042.10,
            7.3e12,
            1.25,
            "OPENING_AUCTION",
            None,
            None,
            None,
        ),
    )
    conn.execute(
        "INSERT INTO index_level_snapshots "
        "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:15:00.000+00:00",
            "EDU100",
            1045.00,
            7.32e12,
            1.25,
            "CONTINUOUS",
            1042.10,
            1045.00,
            1042.10,
        ),
    )
    conn.execute(
        "INSERT INTO index_level_snapshots "
        "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:30:00.000+00:00",
            "EDU100",
            1048.73,
            7.35e12,
            1.25,
            "CONTINUOUS",
            1042.10,
            1048.73,
            1042.10,
        ),
    )
    conn.execute(
        "INSERT INTO index_level_snapshots "
        "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14T09:05:00.000+00:00",
            "EDUFIN",
            500.0,
            1.2e12,
            0.9,
            "CONTINUOUS",
            500.0,
            500.0,
            500.0,
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


# ---------------------------------------------------------------------------
# Index history queries — design intent: correct "latest date" defaulting,
# correct time-range filtering, and correct per-index isolation, mirroring
# the guarantees already proven for symbols above rather than assuming a
# parallel implementation behaves the same without checking.
# ---------------------------------------------------------------------------


def test_query_index_daily_uses_latest_date_when_date_missing(
    seeded_db: Path,
) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_daily(conn, date_value=None, index_id=None, limit=100)
    conn.close()

    # EDU100 has rows on both 2026-06-14 and 2026-06-15; only the latest
    # date's rows should come back when no date is given, same contract as
    # query_daily for symbols.
    assert {row["date"] for row in rows} == {"2026-06-15"}
    assert {row["index_id"] for row in rows} == {"EDU100"}


def test_query_index_daily_index_id_filter_isolates_one_index(
    seeded_db: Path,
) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_daily(
        conn, date_value="2026-06-14", index_id="EDUFIN", limit=100
    )
    conn.close()

    assert len(rows) == 1
    assert rows[0]["index_id"] == "EDUFIN"
    assert rows[0]["close_level"] == 502.0


def test_query_index_daily_without_index_id_returns_all_indexes_for_date(
    seeded_db: Path,
) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_daily(conn, date_value="2026-06-14", index_id=None, limit=100)
    conn.close()

    assert {row["index_id"] for row in rows} == {"EDU100", "EDUFIN"}


def test_query_index_snapshots_filters_by_time_window(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_snapshots(
        conn,
        index_id="EDU100",
        date_value="2026-06-14",
        from_ts="2026-06-14T09:10:00+00:00",
        to_ts="2026-06-14T09:20:00+00:00",
        limit=500,
    )
    conn.close()

    # Three EDU100 snapshots exist on 2026-06-14 (09:00, 09:15, 09:30) — the
    # 09:10-09:20 window should isolate exactly the 09:15 row, proving the
    # range filter actually narrows rather than just filtering by date.
    assert len(rows) == 1
    assert rows[0]["ts"] == "2026-06-14T09:15:00.000+00:00"
    assert rows[0]["level"] == 1045.00


def test_query_index_snapshots_does_not_leak_across_indexes(
    seeded_db: Path,
) -> None:
    """EDU100 and EDUFIN both have a snapshot on 2026-06-14; querying one
    index_id must never return the other's rows — this is the isolation
    guarantee the (index_id, ts) index and WHERE clause are both meant to
    provide.
    """
    conn = open_readonly_connection(seeded_db)
    rows = query_index_snapshots(
        conn,
        index_id="EDUFIN",
        date_value=None,
        from_ts=None,
        to_ts=None,
        limit=500,
    )
    conn.close()

    assert len(rows) == 1
    assert rows[0]["index_id"] == "EDUFIN"


def test_query_index_snapshots_orders_chronologically(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_snapshots(
        conn,
        index_id="EDU100",
        date_value=None,
        from_ts=None,
        to_ts=None,
        limit=500,
    )
    conn.close()

    timestamps = [row["ts"] for row in rows]
    assert timestamps == sorted(timestamps)


def test_query_index_ids_uses_union_across_tables(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows = query_index_ids(conn, date_value=None)
    conn.close()

    index_ids = [row["index_id"] for row in rows]
    assert index_ids == ["EDU100", "EDUFIN"]


def test_query_index_ids_empty_db_returns_no_rows(tmp_path: Path) -> None:
    """An exchange with no configured index should not error — index-ids
    on an otherwise-populated (symbol-only) DB should just come back empty,
    the same way index_daily_stats/index_level_snapshots staying empty is
    documented as expected, not an error state.
    """
    db_path = tmp_path / "no_index.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO daily_stats (date, symbol, open_price, close_price, volume, trade_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-14", "AAPL", 150.0, 152.0, 1000, 5),
    )
    conn.commit()
    conn.close()

    conn = open_readonly_connection(db_path)
    rows = query_index_ids(conn, date_value=None)
    conn.close()

    assert rows == []
