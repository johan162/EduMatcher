"""pm-eod's day-scoped reads use the trade_date index (EOD review P2)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from edumatcher.clearing.store import (
    open_writer_connection,
    query_close_snapshots,
    query_reconcile,
)


@pytest.fixture()
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = open_writer_connection(tmp_path / "clearing.db")
    yield c
    c.close()


def _plans(conn: sqlite3.Connection, run: object) -> list[str]:
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    run()  # type: ignore[operator]
    conn.set_trace_callback(None)
    (sql,) = [s for s in seen if s.lstrip().upper().startswith(("SELECT", "WITH"))]
    return [r[3] for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}")]


def test_one_days_snapshot_is_read_by_index(conn: sqlite3.Connection) -> None:
    plans = _plans(conn, lambda: query_close_snapshots(conn, date_value="2026-07-01"))
    assert not any(p.startswith("SCAN position_close_snapshot") for p in plans), plans


def test_one_days_reconcile_reads_trades_by_index(conn: sqlite3.Connection) -> None:
    plans = _plans(
        conn,
        lambda: query_reconcile(conn, from_date="2026-07-01", to_date="2026-07-01"),
    )
    assert not any(p.startswith("SCAN trade_events") for p in plans), plans
    assert not any(p.startswith("SCAN gateway_daily_summary") for p in plans), plans


def test_unfiltered_reads_still_return_everything(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO position_close_snapshot VALUES"
        " ('2026-07-01', 'A', 'AAPL', 1, 0, 0, 100, 2),"
        " ('2026-07-02', 'A', 'AAPL', 1, 0, 0, 100, 2)"
    )
    assert len(query_close_snapshots(conn)) == 2
    assert len(query_close_snapshots(conn, gateway="A", from_date="2026-07-02")) == 1


def test_each_clearing_db_has_its_own_instance_id(tmp_path: Path) -> None:
    from edumatcher.clearing.store import clearing_instance

    first = open_writer_connection(tmp_path / "a.db")
    again = open_writer_connection(tmp_path / "a.db")
    other = open_writer_connection(tmp_path / "b.db")
    try:
        assert clearing_instance(first) is not None
        assert clearing_instance(first) == clearing_instance(again)
        assert clearing_instance(first) != clearing_instance(other)
    finally:
        for c in (first, again, other):
            c.close()


# --- WP-CLR06 (clearing review P2): one day's trades from that day ----------


def _seed_days(conn: sqlite3.Connection) -> None:
    from edumatcher.clearing.store import TradeEventRow, flush_batch

    rows = []
    for d, day in enumerate(("2026-07-01", "2026-07-02", "2026-07-03")):
        for i in range(5):
            rows.append(
                TradeEventRow(
                    id=f"{d + 1:06d}-{i + 1:09d}",
                    ts_ns=1_751_000_000_000_000_000 + d * 86_400 * 10**9 + i // 2,
                    trade_date=day,
                    symbol="AAPL",
                    quantity=1,
                    price=100,
                    buy_order_id=None,
                    sell_order_id=None,
                    buy_gateway_id="GW01" if i % 2 else "GW02",
                    sell_gateway_id="GW03",
                    aggressor_side="BUY",
                    ingest_ts_ns=1,
                )
            )
    flush_batch(conn, rows, [], [])


@pytest.mark.parametrize("gateway", [None, "GW01"], ids=["day", "day+gateway"])
def test_one_days_trades_are_read_from_that_days_index(
    conn: sqlite3.Connection, gateway: str | None
) -> None:
    from edumatcher.clearing.store import query_trades

    plans = _plans(
        conn,
        lambda: query_trades(conn, date_value="2026-07-01", gateway=gateway),
    )
    assert not any(p.startswith("SCAN trade_events") for p in plans), plans
    assert not any("TEMP B-TREE" in p for p in plans), plans


def test_paging_one_day_matches_paging_everything_filtered(
    conn: sqlite3.Connection,
) -> None:
    from edumatcher.clearing.store import query_trades

    _seed_days(conn)

    def pages(**filters: object) -> list[str]:
        out: list[str] = []
        after = None
        while True:
            page = query_trades(conn, limit=2, after=after, **filters)  # type: ignore[arg-type]
            if not page:
                return out
            out += [r["id"] for r in page]
            last = page[-1]
            after = (last["ts_ns"], last["ingest_ts_ns"], last["id"])

    everything = pages()
    one_day = pages(date_value="2026-07-02")
    assert one_day == [i for i in everything if i.startswith("000002-")]
    assert len(one_day) == 5
    assert pages(date_value="2026-07-02", gateway="GW01") == [
        i for i in one_day if int(i[-1]) % 2 == 0
    ]
