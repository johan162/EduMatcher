"""The eod.db ledger: one zero-sum row set per trading date, running balances."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import pytest

from edumatcher.eod.ledger import (
    LedgerError,
    balances,
    check_zero_sum,
    day_amounts,
    open_ledger,
    record_day,
    redo_from,
    settled_dates,
)
from edumatcher.eod.settle import EXCHANGE, Settlement


@pytest.fixture()
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = open_ledger(tmp_path / "eod.db")
    yield c
    c.close()


def day(a: int, b: int, rounding: int = 0) -> Settlement:
    detail = {"A": {"AAPL": Decimal(a) / 100}, "B": {"AAPL": Decimal(b) / 100}}
    return Settlement({"A": a, "B": b}, rounding, detail)


class TestRecordDay:
    def test_round_trip(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        assert day_amounts(conn, "2026-07-01") == {"A": 500, "B": -500}
        assert settled_dates(conn) == ["2026-07-01"]

    def test_rounding_is_booked_to_the_exchange(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(501, -500, rounding=-1))
        assert day_amounts(conn, "2026-07-01")[EXCHANGE] == -1

    def test_a_day_that_does_not_sum_to_zero_is_refused(
        self, conn: sqlite3.Connection
    ) -> None:
        with pytest.raises(LedgerError, match="zero"):
            record_day(conn, "2026-07-01", day(500, -400))
        assert settled_dates(conn) == []

    def test_a_date_is_settled_once(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        with pytest.raises(LedgerError, match="already"):
            record_day(conn, "2026-07-01", day(100, -100))

    def test_dates_must_not_go_backwards(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-02", day(500, -500))
        with pytest.raises(LedgerError, match="later"):
            record_day(conn, "2026-07-01", day(100, -100))

    def test_detail_is_kept(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        row = conn.execute(
            "SELECT detail_json FROM eod_settlement WHERE account = 'A'"
        ).fetchone()
        assert row[0] == '{"AAPL": "5"}'


class TestBalances:
    def test_running_balance(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        record_day(conn, "2026-07-02", day(-200, 200))
        assert balances(conn) == {"A": 300, "B": -300}
        assert balances(conn, as_of="2026-07-01") == {"A": 500, "B": -500}

    def test_opening_balances_are_added_once(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        got = balances(conn, openings={"A": 10_000, "C": 7})
        assert got == {"A": 10_500, "B": -500, "C": 7}

    def test_no_days_gives_just_the_openings(self, conn: sqlite3.Connection) -> None:
        assert balances(conn, openings={"A": 5}) == {"A": 5}


class TestRedoAndCheck:
    def test_redo_deletes_that_day_and_later(self, conn: sqlite3.Connection) -> None:
        for d in ("2026-07-01", "2026-07-02", "2026-07-03"):
            record_day(conn, d, day(100, -100))
        assert redo_from(conn, "2026-07-02") == ["2026-07-02", "2026-07-03"]
        assert settled_dates(conn) == ["2026-07-01"]
        record_day(conn, "2026-07-02", day(1, -1))

    def test_check_finds_a_corrupt_day(self, conn: sqlite3.Connection) -> None:
        record_day(conn, "2026-07-01", day(500, -500))
        assert check_zero_sum(conn) == []
        conn.execute("UPDATE eod_settlement SET amount_minor = 1 WHERE account = 'A'")
        conn.commit()
        assert check_zero_sum(conn) == ["2026-07-01"]
