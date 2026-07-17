"""
Tests for StatsProcess helper methods (no ZMQ required).

Patches make_subscriber/make_pusher out so the constructor doesn't
need a live ZMQ socket.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

import edumatcher.stats.main as stats_main_mod
from edumatcher.stats.main import (
    SNAPSHOT_INTERVAL_SEC,
    SCHEMA,
    StatsProcess,
    _DayAccum,
    _IndexDayAccum,
    _event_type_from_topic,
    _is_order_event_topic,
    _open_db,
    main as stats_main,
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
        assert {
            "daily_stats",
            "price_snapshots",
            "trade_log",
            "index_daily_stats",
            "index_level_snapshots",
        } <= tables
        conn.close()

    def test_index_tables_have_range_query_indices(self, tmp_path: Path) -> None:
        """The whole point of moving index history off the JSONL file into
        SQLite is fast range lookups — a schema with the tables but no
        indices on (index_id, ts) would silently regress back to a full
        table scan per query. Assert the indices actually exist, not just
        the tables.
        """
        conn = _open_db(tmp_path / "idx_check.db")
        index_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_ids_index_ts" in index_names
        assert "idx_ds_index_id_date" in index_names

        # And confirm SQLite's query planner actually picks the index for the
        # access pattern index-snapshots relies on (index_id + ts range),
        # rather than merely having an index that goes unused.
        plan = conn.execute(
            "EXPLAIN QUERY PLAN "
            "SELECT * FROM index_level_snapshots WHERE index_id = ? AND ts >= ?",
            ("EDU100", "2026-01-01"),
        ).fetchall()
        plan_text = " ".join(str(row) for row in plan)
        assert "idx_ids_index_ts" in plan_text
        conn.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        p = tmp_path / "a" / "b" / "c" / "stats.db"
        conn = _open_db(p)
        assert p.exists()
        conn.close()

    def test_sql_trace_logs_statements(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        p = tmp_path / "stats_sql_trace.db"
        caplog.set_level(logging.DEBUG, logger="edumatcher.stats.sql")
        conn = _open_db(p, sql_trace=True)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        assert any("SELECT 1" in rec.message for rec in caplog.records)


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
# _IndexDayAccum (pure dataclass — day-rollover semantics)
# ---------------------------------------------------------------------------


class TestIndexDayAccum:
    """Design intent: an index has no independent trades/volume of its own,
    but its level history should behave like a symbol's daily OHLC rollup —
    first update opens the day, level extremes track high/low, most recent
    update is the running close. These tests assert that *behavior*, not
    the specific fields, so they'd catch a broken open/high/low/close
    computation even if the implementation were rewritten.
    """

    def test_first_update_sets_open_high_low_close_identically(self) -> None:
        acc = _IndexDayAccum(date="2026-06-14", index_id="EDU100")
        acc.on_update(1000.0, aggregate_cap=5_000_000_000.0)
        assert (
            acc.open_level
            == acc.high_level
            == acc.low_level
            == acc.close_level
            == 1000.0
        )
        assert acc.open_aggregate_cap == 5_000_000_000.0
        assert acc.update_count == 1

    def test_open_level_never_changes_after_first_update(self) -> None:
        acc = _IndexDayAccum(date="2026-06-14", index_id="EDU100")
        acc.on_update(1000.0, aggregate_cap=None)
        acc.on_update(950.0, aggregate_cap=None)  # a later, lower level
        acc.on_update(1100.0, aggregate_cap=None)  # a later, higher level
        assert acc.open_level == 1000.0  # unchanged by subsequent updates

    def test_high_and_low_track_extremes_across_updates(self) -> None:
        acc = _IndexDayAccum(date="2026-06-14", index_id="EDU100")
        for level in (1000.0, 1050.0, 980.0, 1010.0):
            acc.on_update(level, aggregate_cap=None)
        assert acc.high_level == 1050.0
        assert acc.low_level == 980.0

    def test_close_level_is_most_recent_update_not_extreme(self) -> None:
        acc = _IndexDayAccum(date="2026-06-14", index_id="EDU100")
        for level in (1000.0, 1050.0, 980.0, 1010.0):
            acc.on_update(level, aggregate_cap=None)
        assert acc.close_level == 1010.0  # last value, not high or low

    def test_update_count_increments_once_per_update(self) -> None:
        acc = _IndexDayAccum(date="2026-06-14", index_id="EDU100")
        for _ in range(7):
            acc.on_update(1000.0, aggregate_cap=None)
        assert acc.update_count == 7


# ---------------------------------------------------------------------------
# StatsProcess._on_index_update
# ---------------------------------------------------------------------------


class TestOnIndexUpdate:
    """Design intent: every index.update event pm-stats receives should
    become one durable, queryable row — both the intraday time series
    (index_level_snapshots) and the day's rolling OHLC summary
    (index_daily_stats) — without the linear-scan-JSONL problem the
    pre-existing pm-index history file has. These tests exercise that
    contract at the message-handling boundary, the same level the existing
    _on_trade/_on_book tests operate at.
    """

    def _payload(
        self,
        index_id: str = "EDU100",
        level: float = 1048.73,
        **overrides: object,
    ) -> dict:
        base: dict = {
            "index_id": index_id,
            "level": level,
            "aggregate_cap": 7_350_000_000_000.0,
            "divisor": 1.25,
            "session_state": "CONTINUOUS",
            "timestamp": time.time(),
        }
        base.update(overrides)
        return base

    def test_index_update_recorded_in_snapshots(self, sp: StatsProcess) -> None:
        sp._on_index_update(self._payload())
        rows = sp._conn.execute(
            "SELECT index_id, level, session_state FROM index_level_snapshots"
        ).fetchall()
        assert rows == [("EDU100", 1048.73, "CONTINUOUS")]

    def test_index_update_upserts_daily_rollup(self, sp: StatsProcess) -> None:
        sp._on_index_update(self._payload(level=1000.0))
        sp._on_index_update(self._payload(level=1010.0))
        rows = sp._conn.execute(
            "SELECT open_level, close_level, update_count FROM index_daily_stats "
            "WHERE index_id = 'EDU100'"
        ).fetchall()
        assert len(rows) == 1  # one row per (date, index_id), not per update
        assert rows[0] == (1000.0, 1010.0, 2)

    def test_multiple_indexes_tracked_independently(self, sp: StatsProcess) -> None:
        sp._on_index_update(self._payload(index_id="EDU100", level=1000.0))
        sp._on_index_update(self._payload(index_id="EDUFIN", level=500.0))
        rows = sp._conn.execute(
            "SELECT index_id, close_level FROM index_daily_stats ORDER BY index_id"
        ).fetchall()
        assert rows == [("EDU100", 1000.0), ("EDUFIN", 500.0)]

    def test_missing_index_id_ignored_not_raised(self, sp: StatsProcess) -> None:
        sp._on_index_update({"level": 1000.0})  # no index_id
        rows = sp._conn.execute("SELECT * FROM index_level_snapshots").fetchall()
        assert rows == []

    def test_missing_level_ignored_not_raised(self, sp: StatsProcess) -> None:
        sp._on_index_update({"index_id": "EDU100"})  # no level
        rows = sp._conn.execute("SELECT * FROM index_level_snapshots").fetchall()
        assert rows == []

    def test_malformed_payload_is_logged_for_observability(
        self, sp: StatsProcess, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A silently-dropped malformed message is invisible to an operator;
        the whole point of adding observability here is that a bad payload
        shows up in the logs rather than just vanishing.
        """
        caplog.set_level(logging.WARNING, logger="edumatcher.stats.main")
        sp._on_index_update({"index_id": "", "level": None})
        assert any(
            "ignoring malformed index.update" in rec.message for rec in caplog.records
        )

    def test_valid_update_logged_at_debug_for_observability(
        self, sp: StatsProcess, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A successful index update should also be observable — an operator
        running -vv should be able to see index traffic flowing through
        pm-stats the same way book/trade traffic is debug-logged elsewhere.
        """
        caplog.set_level(logging.DEBUG, logger="edumatcher.stats.main")
        sp._on_index_update(self._payload(index_id="EDU100", level=1048.73))
        assert any(
            "recorded index update" in rec.message and "EDU100" in rec.message
            for rec in caplog.records
        )

    def test_optional_fields_persisted_when_present(self, sp: StatsProcess) -> None:
        sp._on_index_update(
            self._payload(day_open=1042.10, day_high=1056.30, day_low=1040.05)
        )
        row = sp._conn.execute(
            "SELECT day_open, day_high, day_low FROM index_level_snapshots"
        ).fetchone()
        assert row == (1042.10, 1056.30, 1040.05)

    def test_optional_fields_null_when_absent(self, sp: StatsProcess) -> None:
        sp._on_index_update(self._payload())  # no day_open/high/low
        row = sp._conn.execute(
            "SELECT day_open, day_high, day_low FROM index_level_snapshots"
        ).fetchone()
        assert row == (None, None, None)


# ---------------------------------------------------------------------------
# StatsProcess._receive_one_index_message (index_sub poll-loop dispatch)
# ---------------------------------------------------------------------------


class TestReceiveOneIndexMessage:
    """The engine-side poll loop (_receive) has no direct test in this file
    — it's thin ZMQ glue exercised at integration level. _receive_one_index_message
    is new, non-trivial dispatch logic of its own (topic routing + a decode
    failure path), so it gets a small, targeted test here rather than being
    left implicitly covered only by the _on_index_update tests above.
    """

    def test_index_update_topic_dispatches_to_handler(self, sp: StatsProcess) -> None:
        from edumatcher.models.message import encode

        frames = encode(
            "index.update",
            {"index_id": "EDU100", "level": 1048.73, "timestamp": time.time()},
        )
        sp.index_sub.recv_multipart = MagicMock(return_value=frames)

        sp._receive_one_index_message()

        rows = sp._conn.execute(
            "SELECT index_id, level FROM index_level_snapshots"
        ).fetchall()
        assert rows == [("EDU100", 1048.73)]

    def test_unrecognized_topic_is_ignored_not_raised(self, sp: StatsProcess) -> None:
        from edumatcher.models.message import encode

        frames = encode("index.corp_action", {"index_id": "EDU100"})
        sp.index_sub.recv_multipart = MagicMock(return_value=frames)

        sp._receive_one_index_message()  # must not raise

        rows = sp._conn.execute("SELECT * FROM index_level_snapshots").fetchall()
        assert rows == []

    def test_decode_failure_is_logged_and_does_not_raise(
        self, sp: StatsProcess, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING, logger="edumatcher.stats.main")
        sp.index_sub.recv_multipart = MagicMock(side_effect=RuntimeError("boom"))

        sp._receive_one_index_message()  # must not raise

        assert any(
            "failed to decode index_sub message" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# StatsProcess._index_accum_for (date rollover, mirrors TestAccumFor)
# ---------------------------------------------------------------------------


class TestIndexAccumFor:
    def test_creates_new_accum_first_time(self, sp: StatsProcess) -> None:
        acc = sp._index_accum_for("EDU100")
        assert acc.index_id == "EDU100"
        assert acc.date == sp._today()

    def test_reuses_existing_accum_same_day(self, sp: StatsProcess) -> None:
        acc1 = sp._index_accum_for("EDU100")
        acc1.on_update(1000.0, aggregate_cap=None)
        acc2 = sp._index_accum_for("EDU100")
        assert acc2 is acc1
        assert acc2.close_level == 1000.0

    def test_day_rollover_flushes_previous_day_and_starts_fresh(
        self, sp: StatsProcess
    ) -> None:
        """Mirrors the equivalent _accum_for rollover behavior for symbols:
        when the calendar date changes, the prior day's accumulator must be
        flushed to index_daily_stats before a fresh one starts, so no data
        is silently lost across midnight.
        """
        acc = sp._index_accum_for("EDU100")
        acc.date = "2020-01-01"  # simulate a stale accumulator from "yesterday"
        acc.on_update(999.0, aggregate_cap=None)

        # Next call detects the date mismatch and rolls over
        new_acc = sp._index_accum_for("EDU100")
        assert new_acc is not acc
        assert new_acc.date == sp._today()

        # The stale day's data must have been flushed to the DB before rollover
        flushed = sp._conn.execute(
            "SELECT close_level FROM index_daily_stats WHERE date = '2020-01-01'"
        ).fetchone()
        assert flushed == (999.0,)


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


# ---------------------------------------------------------------------------
# StatsProcess._on_eod — empty-symbol branch (line 412)
# ---------------------------------------------------------------------------


class TestOnEodEmptySymbol:
    def test_empty_symbol_skipped(self, sp: StatsProcess) -> None:
        sp._on_eod({"books": [{"symbol": "", "bids": [], "asks": []}]})
        rows = sp._conn.execute("SELECT * FROM daily_stats").fetchall()
        assert rows == []


# ---------------------------------------------------------------------------
# StatsProcess._on_order_event
# ---------------------------------------------------------------------------


class TestOnOrderEvent:
    def test_records_ack_accepted(self, sp: StatsProcess) -> None:
        sp._on_order_event(
            "order.ack.GW01",
            {
                "order_id": "O001",
                "accepted": True,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "price": 100.0,
                "quantity": 100,
            },
        )
        rows = sp._conn.execute(
            "SELECT event_type, order_id, gateway_id FROM order_events"
        ).fetchall()
        assert rows == [("ACK", "O001", "GW01")]

    def test_records_fill_event(self, sp: StatsProcess) -> None:
        sp._on_order_event(
            "order.fill.GW01",
            {
                "order_id": "O002",
                "fill_price": 100.0,
                "fill_qty": 50,
                "trade_id": "T001",
                "remaining_qty": 50,
                "status": "PARTIAL",
            },
        )
        rows = sp._conn.execute("SELECT event_type FROM order_events").fetchall()
        assert rows == [("FILL",)]

    def test_records_cancel_event(self, sp: StatsProcess) -> None:
        sp._on_order_event("order.cancelled.GW01", {"order_id": "O003"})
        rows = sp._conn.execute("SELECT event_type FROM order_events").fetchall()
        assert rows == [("CANCEL",)]

    def test_no_order_id_skipped(self, sp: StatsProcess) -> None:
        sp._on_order_event("order.ack.GW01", {"accepted": True})
        rows = sp._conn.execute("SELECT * FROM order_events").fetchall()
        assert rows == []

    def test_short_topic_uses_payload_gateway(self, sp: StatsProcess) -> None:
        # Topic with only 2 parts → falls back to payload gateway_id
        sp._on_order_event(
            "order.ack",
            {"order_id": "O004", "gateway_id": "GW02", "accepted": True},
        )
        rows = sp._conn.execute("SELECT gateway_id FROM order_events").fetchall()
        assert rows == [("GW02",)]

    def test_combo_id_used_as_order_id(self, sp: StatsProcess) -> None:
        sp._on_order_event("combo.ack.GW01", {"combo_id": "C001"})
        rows = sp._conn.execute("SELECT order_id FROM order_events").fetchall()
        assert rows == [("C001",)]

    def test_all_optional_fields_persisted(self, sp: StatsProcess) -> None:
        sp._on_order_event(
            "order.fill.GW01",
            {
                "order_id": "O005",
                "symbol": "MSFT",
                "side": "SELL",
                "order_type": "MARKET",
                "tif": "IOC",
                "price": None,
                "quantity": 200,
                "remaining_qty": 0,
                "status": "FILLED",
                "fill_price": 250.0,
                "fill_qty": 200,
                "trade_id": "T002",
                "reason": None,
                "client_order_id": "CL001",
                "combo_parent_id": None,
                "oco_group_id": None,
                "priority_reset": True,
            },
        )
        rows = sp._conn.execute(
            "SELECT fill_price, fill_qty, priority_reset FROM order_events"
        ).fetchall()
        assert rows == [(250.0, 200, 1)]


# ---------------------------------------------------------------------------
# _is_order_event_topic
# ---------------------------------------------------------------------------


class TestIsOrderEventTopic:
    def test_recognizes_all_order_topics(self) -> None:
        for topic in [
            "order.ack.GW01",
            "order.fill.GW01",
            "order.cancelled.GW01",
            "order.expired.GW01",
            "order.amended.GW01",
            "combo.ack.GW01",
            "combo.status.GW01",
            "oco.ack.GW01",
            "oco.cancelled.GW01",
            "quote.ack.GW01",
            "quote.status.GW01",
        ]:
            assert _is_order_event_topic(topic), f"Should match: {topic}"

    def test_rejects_other_topics(self) -> None:
        assert not _is_order_event_topic("trade.executed")
        assert not _is_order_event_topic("book.AAPL")
        assert not _is_order_event_topic("system.eod")


# ---------------------------------------------------------------------------
# _event_type_from_topic
# ---------------------------------------------------------------------------


class TestEventTypeFromTopic:
    def test_ack_accepted(self) -> None:
        assert _event_type_from_topic("order.ack.GW01", {"accepted": True}) == "ACK"

    def test_ack_rejected(self) -> None:
        assert _event_type_from_topic("order.ack.GW01", {"accepted": False}) == "REJECT"

    def test_fill(self) -> None:
        assert _event_type_from_topic("order.fill.GW01", {}) == "FILL"

    def test_amend(self) -> None:
        assert _event_type_from_topic("order.amended.GW01", {}) == "AMEND"

    def test_cancel(self) -> None:
        assert _event_type_from_topic("order.cancelled.GW01", {}) == "CANCEL"

    def test_expire(self) -> None:
        assert _event_type_from_topic("order.expired.GW01", {}) == "EXPIRE"

    def test_combo(self) -> None:
        assert _event_type_from_topic("combo.ack.GW01", {}) == "COMBO"

    def test_oco(self) -> None:
        assert _event_type_from_topic("oco.ack.GW01", {}) == "OCO"

    def test_quote(self) -> None:
        assert _event_type_from_topic("quote.ack.GW01", {}) == "QUOTE"

    def test_unknown(self) -> None:
        assert _event_type_from_topic("system.eod", {}) == "EVENT"


# ---------------------------------------------------------------------------
# StatsProcess.run — verify cleanup and signal registration
# ---------------------------------------------------------------------------


class TestStatsRun:
    @patch("edumatcher.stats.main.threading.Thread")
    @patch("edumatcher.stats.main.time.sleep")
    def test_run_closes_sockets_on_exit(
        self, mock_sleep: MagicMock, mock_thread_cls: MagicMock, sp: StatsProcess
    ) -> None:
        mock_t = MagicMock()
        mock_thread_cls.return_value = mock_t

        # Make join() stop the loop on the first call (inside while self._running)
        def _stop_on_first_join(*args: object, **kwargs: object) -> None:
            sp._running = False

        mock_t.join.side_effect = _stop_on_first_join

        sp.run()

        cast(MagicMock, sp.sub.close).assert_called()
        cast(MagicMock, sp.push.close).assert_called()

    def test_close_shuts_down_index_sub_independently_of_sub(
        self, tmp_path: Path
    ) -> None:
        """Design intent: pm-index publishes on its own PUB endpoint, so
        pm-stats needs a genuinely independent second subscriber socket, not
        a second topic filter reusing the engine's socket. Use distinct
        mocks (rather than this file's usual single-fake-socket `sp`
        fixture, where both calls happen to return the same object and
        could mask a bug where index_sub was silently aliased to sub) to
        prove close() shuts each one down on its own.
        """
        engine_sock = MagicMock(name="engine_sub")
        index_sock = MagicMock(name="index_sub")
        push_sock = MagicMock(name="push")
        with (
            patch(
                "edumatcher.stats.main.make_subscriber",
                side_effect=[engine_sock, index_sock],
            ),
            patch("edumatcher.stats.main.make_pusher", return_value=push_sock),
        ):
            proc = StatsProcess(tmp_path / "close_test.db")

        assert proc.sub is engine_sock
        assert proc.index_sub is index_sock
        assert proc.sub is not proc.index_sub

        proc.close()

        cast(MagicMock, engine_sock.close).assert_called_once()
        cast(MagicMock, index_sock.close).assert_called_once()

    def test_index_sub_connects_to_index_pub_addr_not_engine_addr(
        self, tmp_path: Path
    ) -> None:
        """Assert the two subscriber sockets are wired to the two distinct
        addresses this design depends on — if a future refactor accidentally
        pointed index_sub at ENGINE_PUB_ADDR, index.update would silently
        never arrive (wrong topic namespace) rather than raising an error,
        so this is worth asserting explicitly.
        """
        from edumatcher.config import ENGINE_PUB_ADDR, INDEX_PUB_CONNECT_ADDR

        calls: list[tuple[str, tuple[str, ...]]] = []

        def _record_call(addr: str, *topics: str) -> MagicMock:
            calls.append((addr, topics))
            return MagicMock()

        with (
            patch("edumatcher.stats.main.make_subscriber", side_effect=_record_call),
            patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        ):
            StatsProcess(tmp_path / "addr_test.db")

        addrs = [addr for addr, _topics in calls]
        assert ENGINE_PUB_ADDR in addrs
        assert INDEX_PUB_CONNECT_ADDR in addrs
        assert addrs.count(INDEX_PUB_CONNECT_ADDR) == 1

        index_call = next(c for c in calls if c[0] == INDEX_PUB_CONNECT_ADDR)
        assert "index.update" in index_call[1]


# ---------------------------------------------------------------------------
# stats main()
# ---------------------------------------------------------------------------


class TestStatsMain:
    def test_build_parser_logging_flags(self) -> None:
        parser = stats_main_mod._build_parser()
        args = parser.parse_args(
            ["-vv", "--quiet", "--log-level", "ERROR", "--sql-trace"]
        )
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"
        assert args.sql_trace is True

    def test_configure_logging_prefers_explicit_level(self) -> None:
        from argparse import Namespace
        from edumatcher.stats.main import _configure_logging

        args = Namespace(log_level="INFO", verbose=2, quiet=True)
        assert _configure_logging(args) == 20

    @patch("edumatcher.stats.main.StatsProcess.run", return_value=None)
    @patch("edumatcher.stats.main.make_pusher", return_value=MagicMock())
    @patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock())
    def test_main_creates_process_and_runs(
        self,
        mock_sub: MagicMock,
        mock_push: MagicMock,
        mock_run: MagicMock,
        tmp_path: Path,
    ) -> None:
        with patch("sys.argv", ["pm-stats", "--db", str(tmp_path / "test.db")]):
            stats_main()
        mock_run.assert_called_once()
