"""WP-STA07: time-ordered trade reads use an index (P3).

`trades` without a symbol, and the public `GET /history/trades`, scanned and
sorted the whole of trade_log for every page.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timezone
from typing import Any

import pytest

import edumatcher.stats.query as query
from edumatcher.stats.main import SCHEMA


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    yield db
    db.close()


@pytest.fixture
def plans(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The query plan of every statement the query helpers execute."""
    captured: list[list[str]] = []
    original = query._execute_fetchall

    def _spy(
        c: sqlite3.Connection, sql: str, params: list[Any] | tuple[Any, ...]
    ) -> list[sqlite3.Row]:
        plan = c.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
        captured.append([str(row[-1]) for row in plan])
        return original(c, sql, params)

    monkeypatch.setattr(query, "_execute_fetchall", _spy)
    return captured


@pytest.mark.parametrize("newest_first", [True, False])
def test_trades_without_a_symbol_need_no_sort(
    conn: sqlite3.Connection, plans: list[list[str]], newest_first: bool
) -> None:
    query.query_trades(
        conn,
        symbol=None,
        date_value=None,
        from_ts=None,
        to_ts=None,
        limit=200,
        tz=timezone.utc,
        newest_first=newest_first,
    )
    (plan,) = plans
    assert not any("TEMP B-TREE" in step for step in plan), plan


def test_symbols_without_a_date_do_not_scan_the_tape(
    conn: sqlite3.Connection, plans: list[list[str]]
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity) "
            "VALUES ('2026-06-14T09:00:00.000+00:00', '1-1', 'AAPL', 100, 1)"
        )
        # Written in the same transaction as every trade, so it names every
        # symbol that traded, and it is never pruned.
        conn.execute(
            "INSERT INTO daily_stats (date, symbol) VALUES ('2026-06-14', 'AAPL')"
        )
    rows = query.query_symbols(conn, date_value=None, tz=timezone.utc)
    assert [row["symbol"] for row in rows] == ["AAPL"]
    (plan,) = plans
    assert not any("trade_log" in step for step in plan), plan
