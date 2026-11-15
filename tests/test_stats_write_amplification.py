"""WP-STA03: the book and trade paths write only what changed (P1, C12).

Every book message used to commit a daily_stats upsert (once an opening quote
was known) and an instruments upsert, neither of which changed anything.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.stats.main import StatsProcess

TS_NS = 1_792_850_048_220_023_754


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


def _book(i: int, tick_decimals: int = 2) -> dict[str, object]:
    return {
        "symbol": "AAPL",
        "tick_decimals": tick_decimals,
        "ts_ns": TS_NS + i,
        "bids": [{"price": 99.5, "qty": 10}],
        "asks": [{"price": 100.5, "qty": 10}],
    }


def _trade(i: int, tick_decimals: int = 2) -> dict[str, object]:
    return {
        "id": f"000001-{i:09d}",
        "symbol": "AAPL",
        "price": 100.0,
        "quantity": 1,
        "ts_ns": TS_NS + i,
        "tick_decimals": tick_decimals,
    }


def _count_writes(sp: StatsProcess) -> dict[str, int]:
    counts = {"daily_stats": 0, "instruments": 0}

    def _trace(statement: str) -> None:
        for table in counts:
            if statement.lstrip().startswith(f"INSERT INTO {table}"):
                counts[table] += 1

    sp._conn.set_trace_callback(_trace)
    return counts


def test_unchanged_book_messages_write_nothing_after_the_opening_quote(
    sp: StatsProcess,
) -> None:
    counts = _count_writes(sp)
    for i in range(1_000):
        sp._on_book("AAPL", _book(i))
    assert counts == {"daily_stats": 1, "instruments": 1}
    (open_bid,) = sp._conn.execute("SELECT open_bid FROM daily_stats").fetchone()
    assert open_bid == 9950


def test_trades_record_the_instrument_once(sp: StatsProcess) -> None:
    counts = _count_writes(sp)
    for i in range(1, 101):
        sp._on_trade(_trade(i))
    assert counts["instruments"] == 1
    assert counts["daily_stats"] == 100  # every trade changes the rollup


def test_config_scale_is_still_never_overwritten_by_an_observed_one(
    sp: StatsProcess,
) -> None:
    sp._on_trade(_trade(1))
    sp._on_startup_symbols({"symbols": [{"symbol": "AAPL", "tick_decimals": 4}]})
    sp._on_trade(_trade(2))
    row = sp._conn.execute(
        "SELECT tick_decimals, source FROM instruments WHERE symbol = 'AAPL'"
    ).fetchone()
    assert row == (4, "config")


def test_a_mid_day_scale_change_is_reported_once(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    sp._on_trade(_trade(1, tick_decimals=2))
    with caplog.at_level(logging.ERROR, logger="edumatcher.stats.main"):
        for i in range(2, 102):
            sp._on_trade(_trade(i, tick_decimals=4))
    changed = [r for r in caplog.records if "changed from" in r.getMessage()]
    assert len(changed) == 1
