"""
Tests for StatsProcess helper methods (no ZMQ required).

Patches make_subscriber/make_pusher out so the constructor doesn't
need a live ZMQ socket.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.stats.main import (
    SNAPSHOT_INTERVAL_SEC,
    SCHEMA,
    StatsProcess,
    _DayAccum,
    _open_db,
)
from edumatcher.ticker.main import _query_daily_stats

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sp(tmp_path: Path):
    """StatsProcess with fake ZMQ sockets; _conn closed after each test."""
    fake_sock = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        proc = StatsProcess(tmp_path / "test.db")
    yield proc
    proc._conn.close()


def _in_memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# _open_db
# ---------------------------------------------------------------------------


class TestOpenDb:
    def test_creates_schema(self, tmp_path: Path) -> None:
        conn = _open_db(tmp_path / "sub" / "stats.db")
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"daily_stats", "price_snapshots", "trade_log"} <= tables
        conn.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "a" / "b" / "c" / "stats.db"
        conn = _open_db(p)
        assert p.exists()
        conn.close()


# ---------------------------------------------------------------------------
# _query_daily_stats
# ---------------------------------------------------------------------------


class TestQueryDailyStats:
    def test_empty_db_returns_empty_dict(self) -> None:
        conn = _in_memory_conn()
        result = _query_daily_stats(conn, "2026-05-06")
        assert result == {}
        conn.close()

    def test_returns_row_for_today(self) -> None:
        conn = _in_memory_conn()
        conn.execute(
            "INSERT INTO daily_stats (date, symbol, open_price, close_price, volume, trade_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-05-06", "AAPL", 145.0, 150.0, 1000, 10),
        )
        conn.commit()
        result = _query_daily_stats(conn, "2026-05-06")
        assert "AAPL" in result
        assert result["AAPL"]["open_price"] == 145.0
        assert result["AAPL"]["close_price"] == 150.0
        conn.close()

    def test_ignores_other_dates(self) -> None:
        conn = _in_memory_conn()
        conn.execute(
            "INSERT INTO daily_stats (date, symbol, open_price, close_price, volume, trade_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-05-05", "AAPL", 140.0, 142.0, 500, 5),
        )
        conn.commit()
        result = _query_daily_stats(conn, "2026-05-06")
        assert result == {}
        conn.close()


# ---------------------------------------------------------------------------
# StatsProcess._on_trade
# ---------------------------------------------------------------------------


class TestOnTrade:
    def test_trade_recorded_in_db(self, sp: StatsProcess) -> None:
        payload = {
            "id": "T001",
            "symbol": "AAPL",
            "price": 150.0,
            "quantity": 100,
            "timestamp": time.time(),
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
        }
        sp._on_trade(payload)
        rows = sp._conn.execute("SELECT * FROM trade_log").fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "AAPL"  # symbol column

    def test_trade_updates_accumulator(self, sp: StatsProcess) -> None:
        payload = {
            "id": "T002",
            "symbol": "MSFT",
            "price": 200.0,
            "quantity": 50,
            "timestamp": time.time(),
        }
        sp._on_trade(payload)
        acc = sp._accum.get("MSFT")
        assert acc is not None
        assert acc.close_price == 200.0
        assert acc.volume == 50

    def test_trade_missing_price_ignored(self, sp: StatsProcess) -> None:
        sp._on_trade({"symbol": "AAPL", "id": "T003"})
        rows = sp._conn.execute("SELECT * FROM trade_log").fetchall()
        assert rows == []

    def test_trade_missing_symbol_ignored(self, sp: StatsProcess) -> None:
        sp._on_trade({"price": 100.0, "quantity": 10, "id": "T004"})
        rows = sp._conn.execute("SELECT * FROM trade_log").fetchall()
        assert rows == []

    def test_duplicate_trade_id_ignored(self, sp: StatsProcess) -> None:
        payload = {
            "id": "T005",
            "symbol": "AAPL",
            "price": 100.0,
            "quantity": 10,
            "timestamp": time.time(),
        }
        sp._on_trade(payload)
        sp._on_trade(payload)  # duplicate
        rows = sp._conn.execute("SELECT * FROM trade_log").fetchall()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# StatsProcess._on_book
# ---------------------------------------------------------------------------


class TestOnBook:
    def _book_payload(
        self,
        bid: float | None = 149.5,
        ask: float | None = 150.5,
        last: float | None = 150.0,
    ) -> dict:
        result: dict = {
            "symbol": "AAPL",
            "bids": [{"price": bid, "qty": 100, "count": 1}] if bid else [],
            "asks": [{"price": ask, "qty": 100, "count": 1}] if ask else [],
            "last_price": last,
        }
        return result

    def test_records_opening_bid_ask(self, sp: StatsProcess) -> None:
        sp._on_book("AAPL", self._book_payload())
        acc = sp._accum["AAPL"]
        assert acc.open_bid == 149.5
        assert acc.open_ask == 150.5

    def test_does_not_overwrite_opening_bid(self, sp: StatsProcess) -> None:
        sp._on_book("AAPL", self._book_payload(bid=149.5, ask=150.5))
        sp._on_book("AAPL", self._book_payload(bid=148.0, ask=151.0))
        acc = sp._accum["AAPL"]
        assert acc.open_bid == 149.5  # first value preserved
        assert acc.open_ask == 150.5

    def test_writes_snapshot_when_interval_elapsed(self, sp: StatsProcess) -> None:
        # Force interval to have elapsed (last snap was long ago)
        sp._last_snap_ts["AAPL"] = time.monotonic() - SNAPSHOT_INTERVAL_SEC - 1
        sp._on_book("AAPL", self._book_payload())
        rows = sp._conn.execute("SELECT * FROM price_snapshots").fetchall()
        assert len(rows) == 1

    def test_no_snapshot_before_interval_elapsed(self, sp: StatsProcess) -> None:
        # Set last snapshot to "just now"
        sp._last_snap_ts["AAPL"] = time.monotonic()
        sp._on_book("AAPL", self._book_payload())
        rows = sp._conn.execute("SELECT * FROM price_snapshots").fetchall()
        assert rows == []

    def test_snapshot_mid_uses_last_price_fallback(self, sp: StatsProcess) -> None:
        sp._last_snap_ts["AAPL"] = time.monotonic() - SNAPSHOT_INTERVAL_SEC - 1
        snap = self._book_payload(bid=None, ask=None, last=155.0)
        sp._on_book("AAPL", snap)
        rows = sp._conn.execute("SELECT mid_price FROM price_snapshots").fetchall()
        assert rows[0][0] == 155.0

    def test_pct_change_computed_when_prev_mid_exists(self, sp: StatsProcess) -> None:
        sp._last_snap_ts["AAPL"] = time.monotonic() - SNAPSHOT_INTERVAL_SEC - 1
        sp._last_snap_mid["AAPL"] = 100.0  # previous mid
        # new mid = (150 + 151) / 2 = 150.5
        sp._on_book("AAPL", self._book_payload(bid=150.0, ask=151.0))
        rows = sp._conn.execute("SELECT pct_change FROM price_snapshots").fetchall()
        assert rows[0][0] is not None


# ---------------------------------------------------------------------------
# StatsProcess._on_eod
# ---------------------------------------------------------------------------


class TestOnEod:
    def test_eod_flushes_daily_stats(self, sp: StatsProcess) -> None:
        # Seed an accumulator first
        sp._on_trade(
            {
                "id": "T1",
                "symbol": "AAPL",
                "price": 150.0,
                "quantity": 100,
                "timestamp": time.time(),
            }
        )
        sp._on_eod(
            {
                "books": [
                    {
                        "symbol": "AAPL",
                        "bids": [{"price": 149.5, "qty": 10}],
                        "asks": [{"price": 150.5, "qty": 10}],
                    }
                ]
            }
        )
        rows = sp._conn.execute(
            "SELECT close_bid, close_ask FROM daily_stats"
        ).fetchall()
        assert rows[0] == (149.5, 150.5)

    def test_eod_ignores_empty_books(self, sp: StatsProcess) -> None:
        # Should not raise
        sp._on_eod({"books": []})

    def test_eod_symbol_with_no_bid_ask(self, sp: StatsProcess) -> None:
        sp._on_eod(
            {
                "books": [
                    {
                        "symbol": "AAPL",
                        "bids": [],
                        "asks": [],
                    }
                ]
            }
        )
        # Should still upsert with None bid/ask
        rows = sp._conn.execute(
            "SELECT close_bid, close_ask FROM daily_stats"
        ).fetchall()
        assert rows[0] == (None, None)


# ---------------------------------------------------------------------------
# StatsProcess._accum_for (date rollover)
# ---------------------------------------------------------------------------


class TestAccumFor:
    def test_creates_new_accum_first_time(self, sp: StatsProcess) -> None:
        acc = sp._accum_for("AAPL")
        assert acc.symbol == "AAPL"
        assert acc is sp._accum["AAPL"]

    def test_returns_existing_accum_same_day(self, sp: StatsProcess) -> None:
        acc1 = sp._accum_for("AAPL")
        acc2 = sp._accum_for("AAPL")
        assert acc1 is acc2

    def test_rolls_over_on_new_date(self, sp: StatsProcess) -> None:
        # Seed yesterday's accumulator
        sp._accum["AAPL"] = _DayAccum(date="2000-01-01", symbol="AAPL")
        sp._accum["AAPL"].open_price = 100.0
        new_acc = sp._accum_for("AAPL")
        assert new_acc.date != "2000-01-01"
        # Old data should have been flushed
        rows = sp._conn.execute("SELECT date, symbol FROM daily_stats").fetchall()
        assert ("2000-01-01", "AAPL") in rows


# ---------------------------------------------------------------------------
# orders/main._build_table (orders monitor helper)
# ---------------------------------------------------------------------------


class TestOrdersBuildTable:
    def test_build_table_empty(self) -> None:
        from edumatcher.orders.main import _build_table
        from rich.table import Table

        t = _build_table({}, None)
        assert isinstance(t, Table)

    def test_build_table_with_filter(self) -> None:
        from edumatcher.orders.main import _build_table

        orders = {
            "O1": {
                "order_id": "O1",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 100,
                "remaining": 100,
                "price": 100.0,
                "status": "NEW",
                "updated": "09:30:00",
            },
            "O2": {
                "order_id": "O2",
                "gateway_id": "GW02",
                "symbol": "MSFT",
                "side": "SELL",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 50,
                "remaining": 50,
                "price": 200.0,
                "status": "FILLED",
                "updated": "09:31:00",
            },
        }
        t = _build_table(orders, "GW01")
        assert t.row_count == 1

    def test_build_table_all_status_styles(self) -> None:
        from edumatcher.orders.main import _build_table

        orders = {
            f"O{i}": {
                "order_id": f"O{i}",
                "gateway_id": "GW01",
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "qty": 10,
                "remaining": 10,
                "price": 100.0,
                "status": st,
                "updated": "09:30:00",
            }
            for i, st in enumerate(
                ["NEW", "PARTIAL", "FILLED", "CANCELLED", "REJECTED", "EXPIRED"]
            )
        }
        t = _build_table(orders, None)
        assert t.row_count == 6
