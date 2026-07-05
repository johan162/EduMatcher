"""Tests for the clearing v2 SQLite store — schema, write operations, queries."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from edumatcher.clearing.store import (
    SCHEMA,
    DailySummaryRow,
    PositionRow,
    TradeEventRow,
    apply_schema,
    flush_batch,
    open_readonly_connection,
    open_writer_connection,
    prune_old_events,
    query_daily,
    query_dates,
    query_exposure,
    query_gateways,
    query_health,
    query_positions,
    query_pnl,
    query_reconcile,
    query_symbols,
    query_trades,
    validate_date,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "clearing.db"


@pytest.fixture()
def conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = open_writer_connection(db_path)
    yield c
    c.close()


def _trade_row(
    trade_id: str = "T1",
    symbol: str = "AAPL",
    price: int = 1000,
    qty: int = 100,
    buy_gw: str = "GW_BUY",
    sell_gw: str = "GW_SELL",
    trade_date: str = "2026-07-01",
    ts_ns: int = 1_000_000_000,
    ingest_ts_ns: int = 1_000_000_001,
) -> TradeEventRow:
    return TradeEventRow(
        id=trade_id,
        ts_ns=ts_ns,
        trade_date=trade_date,
        symbol=symbol,
        quantity=qty,
        price=price,
        buy_order_id="O_BUY",
        sell_order_id="O_SELL",
        buy_gateway_id=buy_gw,
        sell_gateway_id=sell_gw,
        aggressor_side="BUY",
        ingest_ts_ns=ingest_ts_ns,
    )


def _position_row(
    gateway_id: str = "GW_BUY",
    symbol: str = "AAPL",
    net_qty: int = 100,
    avg_cost: float = 1000.0,
    realized_pnl: float = 0.0,
    unrealized_pnl: float = 500.0,
    mark_price: int = 1005,
    buy_qty: int = 100,
    sell_qty: int = 0,
    buy_notional: int = 100_000,
    sell_notional: int = 0,
    ts_ns: int = 1_000_000_000,
    updated_ts_ns: int = 1_000_000_002,
) -> PositionRow:
    return PositionRow(
        gateway_id=gateway_id,
        symbol=symbol,
        net_qty=net_qty,
        avg_cost=avg_cost,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        mark_price=mark_price,
        buy_qty=buy_qty,
        sell_qty=sell_qty,
        buy_notional=buy_notional,
        sell_notional=sell_notional,
        last_trade_ts_ns=ts_ns,
        updated_ts_ns=updated_ts_ns,
    )


def _daily_row(
    trade_date: str = "2026-07-01",
    gateway_id: str = "GW_BUY",
    symbol: str = "AAPL",
    delta_traded_qty: int = 100,
    delta_traded_notional: int = 100_000,
    delta_buy_qty: int = 100,
    delta_sell_qty: int = 0,
    delta_buy_notional: int = 100_000,
    delta_sell_notional: int = 0,
    delta_net_amount: int = 100_000,
    delta_realized_pnl: float = 0.0,
    end_net_qty: int = 100,
    end_avg_cost: float = 1000.0,
    end_unrealized_pnl: float = 500.0,
    ts_ns: int = 1_000_000_000,
    updated_ts_ns: int = 1_000_000_002,
) -> DailySummaryRow:
    return DailySummaryRow(
        trade_date=trade_date,
        gateway_id=gateway_id,
        symbol=symbol,
        delta_traded_qty=delta_traded_qty,
        delta_traded_notional=delta_traded_notional,
        delta_buy_qty=delta_buy_qty,
        delta_sell_qty=delta_sell_qty,
        delta_buy_notional=delta_buy_notional,
        delta_sell_notional=delta_sell_notional,
        delta_net_amount=delta_net_amount,
        delta_realized_pnl=delta_realized_pnl,
        end_net_qty=end_net_qty,
        end_avg_cost=end_avg_cost,
        end_unrealized_pnl=end_unrealized_pnl,
        last_trade_ts_ns=ts_ns,
        updated_ts_ns=updated_ts_ns,
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchema:
    def test_apply_schema_creates_tables(self, conn: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "trade_events" in tables
        assert "gateway_symbol_positions" in tables
        assert "gateway_daily_summary" in tables

    def test_apply_schema_creates_views(self, conn: sqlite3.Connection) -> None:
        views = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        }
        assert "gateway_pnl_totals" in views
        assert "daily_exchange_totals" in views

    def test_apply_schema_idempotent(self, db_path: Path) -> None:
        c = open_writer_connection(db_path)
        apply_schema(c)  # second call must not raise
        c.close()

    def test_schema_constant_contains_key_tables(self) -> None:
        assert "CREATE TABLE IF NOT EXISTS trade_events" in SCHEMA
        assert "CREATE TABLE IF NOT EXISTS gateway_symbol_positions" in SCHEMA
        assert "CREATE TABLE IF NOT EXISTS gateway_daily_summary" in SCHEMA


# ---------------------------------------------------------------------------
# Connection helper tests
# ---------------------------------------------------------------------------


class TestConnections:
    def test_readonly_raises_if_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            open_readonly_connection(tmp_path / "no.db")

    def test_readonly_opens_existing(self, db_path: Path) -> None:
        open_writer_connection(db_path).close()
        conn = open_readonly_connection(db_path)
        assert conn is not None
        conn.close()

    def test_readonly_cannot_write(self, db_path: Path) -> None:
        open_writer_connection(db_path).close()
        ro = open_readonly_connection(db_path)
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("INSERT INTO trade_events(id) VALUES ('x')")
        ro.close()


# ---------------------------------------------------------------------------
# flush_batch tests
# ---------------------------------------------------------------------------


class TestFlushBatch:
    def test_inserts_trade_event(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [_trade_row()], [_position_row()], [_daily_row()])
        count = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        assert count == 1

    def test_idempotent_on_duplicate_trade(self, conn: sqlite3.Connection) -> None:
        t = _trade_row(trade_id="DUP")
        flush_batch(conn, [t], [_position_row()], [_daily_row()])
        flush_batch(conn, [t], [_position_row()], [_daily_row()])
        count = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        assert count == 1

    def test_upserts_position(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [], [_position_row(net_qty=50)], [])
        row = conn.execute(
            "SELECT net_qty FROM gateway_symbol_positions"
            " WHERE gateway_id='GW_BUY' AND symbol='AAPL'"
        ).fetchone()
        assert row["net_qty"] == 50

    def test_position_upsert_replaces(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [], [_position_row(net_qty=50)], [])
        flush_batch(conn, [], [_position_row(net_qty=80)], [])
        row = conn.execute(
            "SELECT net_qty FROM gateway_symbol_positions"
            " WHERE gateway_id='GW_BUY' AND symbol='AAPL'"
        ).fetchone()
        assert row["net_qty"] == 80

    def test_daily_upsert_increments_qty(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [], [], [_daily_row(delta_traded_qty=100)])
        flush_batch(conn, [], [], [_daily_row(delta_traded_qty=50)])
        row = conn.execute(
            "SELECT traded_qty FROM gateway_daily_summary"
            " WHERE trade_date='2026-07-01' AND gateway_id='GW_BUY' AND symbol='AAPL'"
        ).fetchone()
        assert row["traded_qty"] == 150

    def test_daily_upsert_increments_notional(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [], [], [_daily_row(delta_buy_notional=100_000)])
        flush_batch(conn, [], [], [_daily_row(delta_buy_notional=50_000)])
        row = conn.execute(
            "SELECT buy_notional FROM gateway_daily_summary"
            " WHERE trade_date='2026-07-01' AND gateway_id='GW_BUY'"
        ).fetchone()
        assert row["buy_notional"] == 150_000

    def test_daily_upsert_updates_end_snapshot(self, conn: sqlite3.Connection) -> None:
        flush_batch(conn, [], [], [_daily_row(end_net_qty=100, end_avg_cost=1000.0)])
        flush_batch(conn, [], [], [_daily_row(end_net_qty=60, end_avg_cost=1000.0)])
        row = conn.execute(
            "SELECT end_net_qty FROM gateway_daily_summary"
            " WHERE trade_date='2026-07-01' AND gateway_id='GW_BUY'"
        ).fetchone()
        assert row["end_net_qty"] == 60

    def test_daily_net_amount_computed_correctly(
        self, conn: sqlite3.Connection
    ) -> None:
        flush_batch(
            conn,
            [],
            [],
            [
                _daily_row(
                    delta_buy_notional=100_000,
                    delta_sell_notional=60_000,
                    delta_net_amount=40_000,
                )
            ],
        )
        flush_batch(
            conn,
            [],
            [],
            [
                _daily_row(
                    delta_buy_notional=20_000,
                    delta_sell_notional=30_000,
                    delta_net_amount=-10_000,
                )
            ],
        )
        # net_amount = (100000+20000) - (60000+30000) = 120000 - 90000 = 30000
        row = conn.execute(
            "SELECT net_amount FROM gateway_daily_summary"
            " WHERE trade_date='2026-07-01' AND gateway_id='GW_BUY'"
        ).fetchone()
        assert row["net_amount"] == 30_000

    def test_multiple_symbols_in_one_batch(self, conn: sqlite3.Connection) -> None:
        flush_batch(
            conn,
            [
                _trade_row("T1", "AAPL"),
                _trade_row("T2", "MSFT", buy_gw="GW2", sell_gw="GW3"),
            ],
            [_position_row("GW_BUY", "AAPL"), _position_row("GW2", "MSFT")],
            [
                _daily_row("2026-07-01", "GW_BUY", "AAPL"),
                _daily_row("2026-07-01", "GW2", "MSFT"),
            ],
        )
        count = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# Prune tests
# ---------------------------------------------------------------------------


class TestPrune:
    def test_prune_removes_old_rows(self, conn: sqlite3.Connection) -> None:
        old_trade = _trade_row("OLD", trade_date="2020-01-01")
        new_trade = _trade_row("NEW", trade_date="2026-07-01")
        flush_batch(conn, [old_trade, new_trade], [], [])

        deleted = prune_old_events(conn, retention_days=90)
        assert deleted == 1

        remaining = conn.execute("SELECT id FROM trade_events").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "NEW"

    def test_prune_keeps_recent_rows(self, conn: sqlite3.Connection) -> None:
        new_trade = _trade_row("RECENT", trade_date="2026-07-01")
        flush_batch(conn, [new_trade], [], [])
        deleted = prune_old_events(conn, retention_days=90)
        assert deleted == 0

    def test_prune_does_not_touch_aggregate_tables(
        self, conn: sqlite3.Connection
    ) -> None:
        old_daily = _daily_row(trade_date="2020-01-01")
        flush_batch(conn, [], [], [old_daily])
        prune_old_events(conn, retention_days=90)
        count = conn.execute("SELECT COUNT(*) FROM gateway_daily_summary").fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Query tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Connection with a minimal realistic dataset."""
    flush_batch(
        conn,
        [
            _trade_row("T1", "AAPL", price=1000, qty=100, trade_date="2026-07-01"),
            _trade_row(
                "T2",
                "AAPL",
                price=1050,
                qty=50,
                buy_gw="GW_SELL",
                sell_gw="GW_BUY",
                trade_date="2026-07-01",
                ts_ns=2_000_000_000,
            ),
            _trade_row(
                "T3",
                "MSFT",
                price=4000,
                qty=25,
                buy_gw="GW_BUY",
                sell_gw="GW_OTHER",
                trade_date="2026-07-02",
                ts_ns=3_000_000_000,
            ),
        ],
        [
            _position_row(
                "GW_BUY", "AAPL", net_qty=50, realized_pnl=2500.0, mark_price=1050
            ),
            _position_row(
                "GW_SELL", "AAPL", net_qty=-50, avg_cost=1050.0, mark_price=1050
            ),
            _position_row(
                "GW_BUY",
                "MSFT",
                net_qty=25,
                avg_cost=4000.0,
                mark_price=4000,
                buy_qty=25,
                buy_notional=100_000,
                sell_notional=0,
            ),
            _position_row(
                "GW_OTHER",
                "MSFT",
                net_qty=-25,
                avg_cost=4000.0,
                mark_price=4000,
                sell_qty=25,
                sell_notional=100_000,
                buy_notional=0,
            ),
        ],
        [
            _daily_row(
                "2026-07-01",
                "GW_BUY",
                "AAPL",
                delta_traded_qty=100,
                end_net_qty=50,
                delta_buy_notional=100_000,
                delta_sell_notional=52_500,
                delta_net_amount=47_500,
            ),
            _daily_row(
                "2026-07-01",
                "GW_SELL",
                "AAPL",
                delta_traded_qty=100,
                end_net_qty=-50,
                delta_sell_notional=100_000,
                delta_buy_notional=52_500,
                delta_net_amount=-47_500,
            ),
            _daily_row(
                "2026-07-02",
                "GW_BUY",
                "MSFT",
                delta_traded_qty=25,
                end_net_qty=25,
                delta_buy_notional=100_000,
                delta_sell_notional=0,
                delta_net_amount=100_000,
            ),
        ],
    )
    return conn


class TestQueryGateways:
    def test_returns_all_gateways(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_gateways(seeded_conn)
        gw_ids = {r["gateway_id"] for r in rows}
        assert "GW_BUY" in gw_ids
        assert "GW_SELL" in gw_ids

    def test_filter_by_gateway(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_gateways(seeded_conn, gateway="GW_BUY")
        assert len(rows) == 1
        assert rows[0]["gateway_id"] == "GW_BUY"

    def test_empty_db(self, conn: sqlite3.Connection) -> None:
        rows = query_gateways(conn)
        assert rows == []


class TestQueryPositions:
    def test_all_positions(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_positions(seeded_conn)
        assert len(rows) == 4

    def test_filter_gateway(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_positions(seeded_conn, gateway="GW_BUY")
        assert all(r["gateway_id"] == "GW_BUY" for r in rows)

    def test_filter_symbol(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_positions(seeded_conn, symbol="MSFT")
        assert all(r["symbol"] == "MSFT" for r in rows)


class TestQueryPnl:
    def test_includes_total_pnl(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_pnl(seeded_conn, gateway="GW_BUY")
        for row in rows:
            assert "total_pnl" in row

    def test_filter_by_symbol(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_pnl(seeded_conn, symbol="AAPL")
        assert all(r["symbol"] == "AAPL" for r in rows)


class TestQueryDaily:
    def test_returns_rows(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_daily(seeded_conn)
        assert len(rows) >= 2

    def test_filter_date(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_daily(seeded_conn, date_value="2026-07-01")
        assert all(r["trade_date"] == "2026-07-01" for r in rows)

    def test_filter_from_to(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_daily(seeded_conn, from_date="2026-07-02", to_date="2026-07-02")
        assert all(r["trade_date"] == "2026-07-02" for r in rows)


class TestQueryTrades:
    def test_returns_all_trades(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_trades(seeded_conn)
        assert len(rows) == 3

    def test_filter_symbol(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_trades(seeded_conn, symbol="MSFT")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "MSFT"

    def test_filter_gateway_matches_buy_or_sell(
        self, seeded_conn: sqlite3.Connection
    ) -> None:
        rows = query_trades(seeded_conn, gateway="GW_BUY")
        assert len(rows) >= 2

    def test_filter_date(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_trades(seeded_conn, date_value="2026-07-02")
        assert len(rows) == 1


class TestQueryExposure:
    def test_returns_rows_with_notional(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_exposure(seeded_conn)
        for row in rows:
            assert "net_notional" in row
            assert "gross_notional" in row

    def test_invalid_sort_raises(self, seeded_conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="Invalid --sort"):
            query_exposure(seeded_conn, sort="bad_field")


class TestQuerySymbols:
    def test_returns_symbols(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_symbols(seeded_conn)
        symbols = {r["symbol"] for r in rows}
        assert "AAPL" in symbols

    def test_sort_by_traded_qty(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_symbols(seeded_conn, sort="traded_qty")
        assert len(rows) >= 1

    def test_invalid_sort_raises(self, seeded_conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="Invalid --sort"):
            query_symbols(seeded_conn, sort="no_such_field")


class TestQueryDates:
    def test_default_mode(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_dates(seeded_conn)
        dates = {r["trade_date"] for r in rows}
        assert "2026-07-01" in dates
        assert "2026-07-02" in dates

    def test_with_totals(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_dates(seeded_conn, with_totals=True)
        for row in rows:
            assert "traded_qty_total" in row
            assert "net_amount_total" in row

    def test_filter_from_date(self, seeded_conn: sqlite3.Connection) -> None:
        rows = query_dates(seeded_conn, from_date="2026-07-02")
        assert all(r["trade_date"] >= "2026-07-02" for r in rows)


class TestQueryHealth:
    def test_returns_one_row(
        self, seeded_conn: sqlite3.Connection, db_path: Path
    ) -> None:
        rows = query_health(seeded_conn, db_path)
        assert len(rows) == 1

    def test_row_contains_counts(
        self, seeded_conn: sqlite3.Connection, db_path: Path
    ) -> None:
        row = query_health(seeded_conn, db_path)[0]
        assert row["trade_events_rows"] == 3
        assert row["gateway_symbol_positions_rows"] == 4
        assert row["wal_mode"] in ("wal", "memory")  # in-memory test DBs may differ

    def test_row_contains_db_path(
        self, seeded_conn: sqlite3.Connection, db_path: Path
    ) -> None:
        row = query_health(seeded_conn, db_path)[0]
        assert str(db_path) in row["db_path"]


class TestQueryReconcile:
    def test_no_discrepancy_on_clean_data(
        self, seeded_conn: sqlite3.Connection
    ) -> None:
        """With correct aggregates the reconcile query returns no rows."""
        # Re-seed with perfectly matching data.
        c = seeded_conn
        c.execute("DELETE FROM trade_events")
        c.execute("DELETE FROM gateway_daily_summary")
        c.commit()

        flush_batch(
            c,
            [_trade_row("X1", "AAPL", price=100, qty=10, trade_date="2026-07-01")],
            [],
            [
                _daily_row(
                    "2026-07-01",
                    "GW_BUY",
                    "AAPL",
                    delta_buy_qty=10,
                    delta_buy_notional=1000,
                )
            ],
        )
        rows = query_reconcile(c)
        assert rows == []

    def test_detects_injected_discrepancy(self, conn: sqlite3.Connection) -> None:
        """Manually corrupt the summary and verify the discrepancy surfaces."""
        flush_batch(
            conn,
            [_trade_row("Z1", "AAPL", price=100, qty=10, trade_date="2026-07-01")],
            [],
            [
                _daily_row(
                    "2026-07-01",
                    "GW_BUY",
                    "AAPL",
                    delta_buy_qty=5,  # wrong — should be 10
                    delta_buy_notional=500,  # wrong — should be 1000
                )
            ],
        )
        rows = query_reconcile(conn)
        assert len(rows) == 1
        assert rows[0]["qty_diff"] == 5  # 10 raw − 5 summary = 5


class TestValidateDate:
    def test_valid_date_passes(self) -> None:
        validate_date("2026-07-01")  # should not raise

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_date("01-07-2026")

    def test_non_date_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_date("not-a-date")
