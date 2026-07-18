from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest

from edumatcher.stats.main import SCHEMA
from edumatcher.stats.query import (
    InvalidCursorError,
    encode_cursor,
    open_readonly_connection,
    query_daily,
    query_dates,
    query_index_daily,
    query_index_ids,
    query_index_snapshots,
    query_order_events,
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
        " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14",
            "EDU100",
            1042.10,
            1056.30,
            1040.05,
            1048.73,
            "CLOSED",
            7.3e12,
            7.35e12,
            512,
        ),
    )
    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-15",
            "EDU100",
            1048.73,
            1060.00,
            1045.00,
            1055.20,
            "CONTINUOUS",  # simulates "today, still trading" — not yet final
            7.35e12,
            7.4e12,
            480,
        ),
    )
    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "2026-06-14",
            "EDUFIN",
            500.0,
            505.0,
            498.0,
            502.0,
            "CLOSED",
            1.2e12,
            1.21e12,
            300,
        ),
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
    rows, next_cursor = query_daily(conn, date_value=None, symbol=None, limit=100)
    conn.close()

    assert len(rows) == 1
    assert rows[0]["date"] == "2026-06-15"
    assert next_cursor is None


def test_query_daily_symbol_filter(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows, _next_cursor = query_daily(
        conn, date_value="2026-06-14", symbol="AAPL", limit=100
    )
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
    rows, next_cursor = query_trades(
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
    assert next_cursor is None


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
    rows, _next_cursor = query_index_daily(
        conn, date_value=None, index_id=None, limit=100
    )
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
    rows, _next_cursor = query_index_daily(
        conn, date_value="2026-06-14", index_id="EDUFIN", limit=100
    )
    conn.close()

    assert len(rows) == 1
    assert rows[0]["index_id"] == "EDUFIN"
    assert rows[0]["close_level"] == 502.0


def test_query_index_daily_returns_close_session_state_for_finality_check(
    seeded_db: Path,
) -> None:
    """Design intent: a caller must be able to tell, from index-daily alone,
    whether close_level for a given date is a finalized EOD print (CLOSED)
    or just the most recent tick received so far (any other state) —
    without a second query against index_level_snapshots.
    """
    conn = open_readonly_connection(seeded_db)

    closed_rows, _ = query_index_daily(
        conn, date_value="2026-06-14", index_id="EDU100", limit=100
    )
    assert closed_rows[0]["close_session_state"] == "CLOSED"

    still_trading_rows, _ = query_index_daily(
        conn, date_value="2026-06-15", index_id="EDU100", limit=100
    )
    assert still_trading_rows[0]["close_session_state"] == "CONTINUOUS"

    conn.close()


def test_query_index_daily_without_index_id_returns_all_indexes_for_date(
    seeded_db: Path,
) -> None:
    conn = open_readonly_connection(seeded_db)
    rows, _next_cursor = query_index_daily(
        conn, date_value="2026-06-14", index_id=None, limit=100
    )
    conn.close()

    assert {row["index_id"] for row in rows} == {"EDU100", "EDUFIN"}


def test_query_index_daily_paginates_across_index_id(seeded_db: Path) -> None:
    """Two indexes exist on 2026-06-14 (EDU100, EDUFIN); limit=1 should
    force a second page, and the cursor should hand back exactly the
    remaining index without repeating or skipping either one. A third page
    fetch (past the last row) must come back empty with no further cursor —
    ``next_cursor`` on a full page means "maybe more", confirmed only once
    an actually-short page is seen.
    """
    conn = open_readonly_connection(seeded_db)
    page1, cursor1 = query_index_daily(
        conn, date_value="2026-06-14", index_id=None, limit=1
    )
    assert len(page1) == 1
    assert cursor1 is not None

    page2, cursor2 = query_index_daily(
        conn, date_value="2026-06-14", index_id=None, limit=1, after=cursor1
    )
    assert len(page2) == 1
    assert {page1[0]["index_id"], page2[0]["index_id"]} == {"EDU100", "EDUFIN"}
    assert page1[0]["index_id"] != page2[0]["index_id"]

    if cursor2 is not None:
        page3, cursor3 = query_index_daily(
            conn, date_value="2026-06-14", index_id=None, limit=1, after=cursor2
        )
        assert page3 == []
        assert cursor3 is None
    conn.close()


def test_query_index_snapshots_filters_by_time_window(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    rows, _next_cursor = query_index_snapshots(
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
    rows, _next_cursor = query_index_snapshots(
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
    rows, _next_cursor = query_index_snapshots(
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


def test_query_index_snapshots_paginates_without_gaps_or_duplicates(
    seeded_db: Path,
) -> None:
    """Walk every page for EDU100 with limit=1 and confirm the full,
    unpaginated result set is reproduced exactly once each, in order —
    the core correctness property of keyset pagination.
    """
    conn = open_readonly_connection(seeded_db)
    full_rows, _ = query_index_snapshots(
        conn, index_id="EDU100", date_value=None, from_ts=None, to_ts=None, limit=500
    )

    paged_ts: list[str] = []
    after = None
    for _ in range(len(full_rows) + 1):
        page, next_cursor = query_index_snapshots(
            conn,
            index_id="EDU100",
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=1,
            after=after,
        )
        if not page:
            break
        paged_ts.extend(row["ts"] for row in page)
        after = next_cursor
        if next_cursor is None:
            break
    conn.close()

    assert paged_ts == [row["ts"] for row in full_rows]


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


# ---------------------------------------------------------------------------
# Keyset pagination — design intent: walking every page reproduces the full,
# unpaginated result set exactly once each and in order, even when several
# rows share the same primary sort key (same ``ts``), which is where a naive
# ``ts``-only cursor would silently skip or repeat rows. Malformed cursors
# must fail clearly rather than being silently ignored or crashing with a
# raw SQL/decoding error.
# ---------------------------------------------------------------------------


def _seed_same_timestamp_trades(path: Path, count: int) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # All rows share one ts on purpose — forces the tiebreaker (rowid) to do
    # all of the ordering work, since ts alone cannot distinguish them.
    for i in range(count):
        conn.execute(
            "INSERT INTO trade_log "
            "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.000+00:00",
                f"T-{i:03d}",
                "EDU100",
                100.0 + i,
                10,
                "GW01",
                "GW02",
            ),
        )
    conn.commit()
    conn.close()


def test_query_trades_paginates_same_timestamp_rows_without_gaps_or_duplicates(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "same_ts_trades.db"
    _seed_same_timestamp_trades(db_path, count=7)
    conn = open_readonly_connection(db_path)

    seen_ids: list[str] = []
    after = None
    for _ in range(10):
        page, next_cursor = query_trades(
            conn,
            symbol=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=3,
            after=after,
        )
        seen_ids.extend(row["trade_id"] for row in page)
        if next_cursor is None:
            break
        after = next_cursor
    conn.close()

    assert seen_ids == [f"T-{i:03d}" for i in range(7)]
    assert len(seen_ids) == len(set(seen_ids))


def test_query_trades_rejects_malformed_cursor(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    with pytest.raises(InvalidCursorError):
        query_trades(
            conn,
            symbol=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=10,
            after="not-a-real-cursor",
        )
    conn.close()


def test_query_trades_rejects_cursor_missing_required_fields(
    seeded_db: Path,
) -> None:
    """A cursor decodable as JSON but missing the fields this query expects
    (e.g. one produced for a different endpoint) must be rejected, not
    silently treated as "no filter" or crash with a KeyError.
    """
    bogus = base64.urlsafe_b64encode(json.dumps({"unrelated": 1}).encode()).decode()
    conn = open_readonly_connection(seeded_db)
    with pytest.raises(InvalidCursorError):
        query_trades(
            conn,
            symbol=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=10,
            after=bogus,
        )
    conn.close()


def _seed_order_events(path: Path, count: int) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for i in range(count):
        conn.execute(
            "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.000+00:00",
                "NEW",
                f"O-{i:03d}",
                "GW01",
                "EDU100",
            ),
        )
    conn.commit()
    conn.close()


def test_query_order_events_paginates_using_seq_tiebreaker(tmp_path: Path) -> None:
    db_path = tmp_path / "order_events.db"
    _seed_order_events(db_path, count=5)
    conn = open_readonly_connection(db_path)

    seen_ids: list[str] = []
    after = None
    for _ in range(10):
        page, next_cursor = query_order_events(
            conn,
            gateway_id="GW01",
            symbol=None,
            event_type=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=2,
            after=after,
        )
        seen_ids.extend(row["order_id"] for row in page)
        if next_cursor is None:
            break
        after = next_cursor
    conn.close()

    assert seen_ids == [f"O-{i:03d}" for i in range(5)]


def test_query_daily_paginates_across_symbols(seeded_db: Path) -> None:
    """query_daily's tiebreaker is symbol itself (already unique per date);
    confirm a small limit still walks every symbol for that date exactly
    once.
    """
    conn = open_readonly_connection(seeded_db)
    page1, cursor1 = query_daily(conn, date_value="2026-06-14", symbol=None, limit=1)
    assert len(page1) == 1
    assert cursor1 is not None

    page2, cursor2 = query_daily(
        conn, date_value="2026-06-14", symbol=None, limit=1, after=cursor1
    )
    conn.close()

    # Only AAPL exists on 2026-06-14 in the shared fixture, so the second
    # page should come back empty with no further cursor.
    assert page2 == []
    assert cursor2 is None


def _seed_daily_multi_symbol(path: Path, date: str, symbols: list[str]) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for symbol in symbols:
        conn.execute(
            "INSERT INTO daily_stats "
            "(date, symbol, open_price, high_price, low_price, close_price, "
            "volume, trade_count, vwap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date, symbol, 100.0, 101.0, 99.0, 100.5, 10, 1, 100.2),
        )
    conn.commit()
    conn.close()


def test_query_daily_cursor_pins_resolved_date_across_pages(tmp_path: Path) -> None:
    """If the caller omits ``date``, the first page pins the resolved
    "latest" date into its cursor; a day rollover between page fetches must
    not silently switch a still-in-progress pagination walk onto the new
    date (which would produce a wrong or emptied-out page).
    """
    db_path = tmp_path / "daily_rollover.db"
    _seed_daily_multi_symbol(db_path, "2026-06-14", ["AAPL", "MSFT", "TSLA"])
    conn = open_readonly_connection(db_path)
    page1, cursor1 = query_daily(conn, date_value=None, symbol=None, limit=1)
    conn.close()
    assert [row["symbol"] for row in page1] == ["AAPL"]
    assert cursor1 is not None

    # Simulate a day rollover: a new, later date now has rows too, so
    # re-resolving "latest" blind would pick 2026-06-15 instead.
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO daily_stats "
        "(date, symbol, open_price, high_price, low_price, close_price, "
        "volume, trade_count, vwap) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-06-15", "ZZZZ", 1.0, 1.0, 1.0, 1.0, 1, 1, 1.0),
    )
    conn.commit()
    conn.close()

    conn = open_readonly_connection(db_path)
    page2, _cursor2 = query_daily(
        conn, date_value=None, symbol=None, limit=1, after=cursor1
    )
    conn.close()

    # Must continue walking the pinned 2026-06-14 page, not jump to the new
    # "latest" 2026-06-15 (which would either return ZZZZ or nothing).
    assert [row["symbol"] for row in page2] == ["MSFT"]


def test_query_daily_explicit_date_overrides_cursor_pin(tmp_path: Path) -> None:
    """An explicit ``date`` always wins over any date pinned in the cursor."""
    db_path = tmp_path / "daily_explicit.db"
    _seed_daily_multi_symbol(db_path, "2026-06-14", ["AAPL", "MSFT"])
    _seed_daily_multi_symbol(db_path, "2026-06-15", ["AAPL", "MSFT"])
    conn = open_readonly_connection(db_path)
    cursor = encode_cursor({"symbol": "AAPL", "date": "2026-06-14"})
    rows, _next_cursor = query_daily(
        conn, date_value="2026-06-15", symbol=None, limit=100, after=cursor
    )
    conn.close()
    assert [row["symbol"] for row in rows] == ["MSFT"]
    assert all(row["date"] == "2026-06-15" for row in rows)


def test_query_daily_cursor_without_date_field_still_works(tmp_path: Path) -> None:
    """Cursors minted before this fix (no 'date' field) must remain valid —
    they fall back to re-resolving 'latest', exactly as before.
    """
    db_path = tmp_path / "daily_legacy_cursor.db"
    _seed_daily_multi_symbol(db_path, "2026-06-14", ["AAPL", "MSFT"])
    conn = open_readonly_connection(db_path)
    legacy_cursor = encode_cursor({"symbol": "AAPL"})
    rows, _next_cursor = query_daily(
        conn, date_value=None, symbol=None, limit=100, after=legacy_cursor
    )
    conn.close()
    assert [row["symbol"] for row in rows] == ["MSFT"]


def test_query_daily_rejects_wrong_typed_cursor_fields(seeded_db: Path) -> None:
    conn = open_readonly_connection(seeded_db)
    bad_symbol = encode_cursor({"symbol": 123})
    with pytest.raises(InvalidCursorError):
        query_daily(
            conn, date_value="2026-06-14", symbol=None, limit=10, after=bad_symbol
        )
    bad_date = encode_cursor({"symbol": "AAPL", "date": 20260614})
    with pytest.raises(InvalidCursorError):
        query_daily(conn, date_value=None, symbol=None, limit=10, after=bad_date)
    conn.close()


def test_query_index_daily_cursor_pins_resolved_date_across_pages(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "index_daily_rollover.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for index_id in ("EDU100", "EDUFIN"):
        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14",
                index_id,
                100.0,
                105.0,
                98.0,
                102.0,
                "CLOSED",
                1e12,
                1.1e12,
                1,
            ),
        )
    conn.commit()
    conn.close()

    conn = open_readonly_connection(db_path)
    page1, cursor1 = query_index_daily(conn, date_value=None, index_id=None, limit=1)
    conn.close()
    assert [row["index_id"] for row in page1] == ["EDU100"]
    assert cursor1 is not None

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO index_daily_stats "
        "(date, index_id, open_level, high_level, low_level, close_level, "
        " close_session_state, open_aggregate_cap, close_aggregate_cap, update_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("2026-06-15", "ZZZ999", 1.0, 1.0, 1.0, 1.0, "CLOSED", 1.0, 1.0, 1),
    )
    conn.commit()
    conn.close()

    conn = open_readonly_connection(db_path)
    page2, _cursor2 = query_index_daily(
        conn, date_value=None, index_id=None, limit=1, after=cursor1
    )
    conn.close()
    assert [row["index_id"] for row in page2] == ["EDUFIN"]


def test_query_trades_rejects_wrong_typed_tiebreaker(seeded_db: Path) -> None:
    """A cursor whose rowid is a string (not int) must be rejected rather
    than flowing into the SQL comparison and silently mis-ordering/mis-
    filtering results.
    """
    conn = open_readonly_connection(seeded_db)
    bad_rowid = encode_cursor({"ts": "2026-06-14T09:00:01.000+00:00", "rowid": "1"})
    with pytest.raises(InvalidCursorError):
        query_trades(
            conn,
            symbol=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=10,
            after=bad_rowid,
        )
    bad_ts = encode_cursor({"ts": 12345, "rowid": 1})
    with pytest.raises(InvalidCursorError):
        query_trades(
            conn,
            symbol=None,
            date_value=None,
            from_ts=None,
            to_ts=None,
            limit=10,
            after=bad_ts,
        )
    conn.close()
