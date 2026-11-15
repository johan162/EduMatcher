"""WP-STA01: a rollup survives a day change in either direction (C1, C4).

pm-stats used to rehydrate a symbol's accumulator only on its first touch in
the process. Moving the accumulator to another day and back started a blank
one, whose next flush overwrote the stored row with a handful of trades.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.stats.main import StatsProcess


@pytest.fixture
def sp(tmp_path: Path) -> Iterator[StatsProcess]:
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        proc = StatsProcess(tmp_path / "stats.db")
    yield proc
    proc._running = False
    proc.close()


def _ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1_000_000_000)


def _trade(sp: StatsProcess, n: int, iso: str, qty: int, price: float = 100.0) -> None:
    sp._on_trade(
        {
            "id": f"000001-{n:09d}",
            "symbol": "AAPL",
            "price": price,
            "quantity": qty,
            "ts_ns": _ns(iso),
            "tick_decimals": 2,
        }
    )


def _index(sp: StatsProcess, iso: str, level: float) -> None:
    sp._on_index_update({"index_id": "EDU100", "level": level, "ts_ns": _ns(iso)})


def test_a_late_trade_for_the_previous_day_keeps_both_days_whole(
    sp: StatsProcess,
) -> None:
    _trade(sp, 1, "2026-11-10T23:59:58+00:00", 10, 101.0)
    _trade(sp, 2, "2026-11-10T23:59:59+00:00", 10, 99.0)
    _trade(sp, 3, "2026-11-11T00:00:01+00:00", 5)
    _trade(sp, 4, "2026-11-11T00:00:02+00:00", 5)
    _trade(sp, 5, "2026-11-10T23:59:59.900+00:00", 1, 98.0)  # late print, day 10
    _trade(sp, 6, "2026-11-11T00:00:03+00:00", 5, 102.0)

    daily = {
        row[0]: row[1:]
        for row in sp._conn.execute(
            "SELECT date, volume, trade_count, turnover, open_price, high_price, "
            "low_price FROM daily_stats"
        )
    }
    tape = {
        row[0]: row[1:]
        for row in sp._conn.execute(
            "SELECT substr(ts, 1, 10), SUM(quantity), COUNT(*), "
            "SUM(price * quantity), NULL, MAX(price), MIN(price) "
            "FROM trade_log GROUP BY 1"
        )
    }
    assert set(daily) == {"2026-11-10", "2026-11-11"}
    for day, row in daily.items():
        volume, count, turnover, _open, high, low = tape[day]
        assert row[:3] == (volume, count, turnover), day
        assert (row[4], row[5]) == (high, low), day
    assert daily["2026-11-10"][3] == 10100  # the first print of day 10
    assert daily["2026-11-11"][3] == 10000


def test_a_late_index_update_keeps_both_days_whole(sp: StatsProcess) -> None:
    _index(sp, "2026-11-10T23:59:58+00:00", 1000.0)
    _index(sp, "2026-11-10T23:59:59+00:00", 1001.0)
    _index(sp, "2026-11-11T00:00:01+00:00", 1002.0)
    _index(sp, "2026-11-10T23:59:59.900+00:00", 999.0)
    _index(sp, "2026-11-11T00:00:02+00:00", 1003.0)

    counts = dict(sp._conn.execute("SELECT date, update_count FROM index_daily_stats"))
    assert counts == {"2026-11-10": 3, "2026-11-11": 2}
    lows = dict(sp._conn.execute("SELECT date, low_level FROM index_daily_stats"))
    assert lows == {"2026-11-10": 999.0, "2026-11-11": 1002.0}


def test_a_forward_rollover_starts_the_new_day_empty(sp: StatsProcess) -> None:
    _trade(sp, 1, "2026-11-10T12:00:00+00:00", 10)
    _trade(sp, 2, "2026-11-11T12:00:00+00:00", 3)
    volumes = dict(sp._conn.execute("SELECT date, volume FROM daily_stats"))
    assert volumes == {"2026-11-10": 10, "2026-11-11": 3}


def _eod(sp: StatsProcess, at: str) -> None:
    received = datetime.fromisoformat(at).timestamp()
    with patch("edumatcher.stats.main.time.time", return_value=received):
        sp._on_eod(
            {
                "books": [
                    {
                        "symbol": "AAPL",
                        "tick_decimals": 2,
                        "bids": [{"price": 99.5, "qty": 1}],
                        "asks": [{"price": 100.5, "qty": 1}],
                    }
                ]
            }
        )


def test_eod_after_midnight_closes_the_session_the_symbol_was_in(
    sp: StatsProcess,
) -> None:
    _trade(sp, 1, "2026-11-10T23:59:58+00:00", 10)
    _eod(sp, "2026-11-11T00:00:00.200+00:00")
    rows = sp._conn.execute(
        "SELECT date, close_bid, close_ask, volume FROM daily_stats"
    ).fetchall()
    assert rows == [("2026-11-10", 9950, 10050, 10)]


def test_eod_for_an_untouched_symbol_uses_the_receipt_date(sp: StatsProcess) -> None:
    _eod(sp, "2026-11-11T08:00:00+00:00")
    rows = sp._conn.execute("SELECT date, close_bid FROM daily_stats").fetchall()
    assert rows == [("2026-11-11", 9950)]
