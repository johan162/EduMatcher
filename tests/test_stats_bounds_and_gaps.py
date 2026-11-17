"""WP-STA06: an inclusive ``--to`` includes its own second's ``.000`` row, and
each feed_gaps row says which check found it (C5, C6, D6)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.stats.main import StatsProcess
from edumatcher.stats.query import (
    query_feed_gaps,
    query_price_snapshots,
    query_trades,
)


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


def _trade(sp: StatsProcess, n: int, iso: str) -> None:
    sp._on_trade(
        {
            "id": f"000001-{n:09d}",
            "symbol": "AAPL",
            "price": 1.0,
            "quantity": 1,
            "ts_ns": int(datetime.fromisoformat(iso).timestamp() * 1e9),
            "tick_decimals": 2,
        }
    )


def _reader(sp: StatsProcess) -> sqlite3.Connection:
    conn = sqlite3.connect(sp._db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_an_inclusive_to_bound_includes_the_rows_of_its_own_instant(
    sp: StatsProcess,
) -> None:
    _trade(sp, 1, "2026-11-10T08:59:59.999+00:00")
    _trade(sp, 2, "2026-11-10T09:00:00.000+00:00")
    _trade(sp, 3, "2026-11-10T09:00:00.001+00:00")
    with sp._conn:
        sp._conn.execute(
            "INSERT INTO price_snapshots (ts, symbol) VALUES "
            "('2026-11-10T09:00:00+00:00', 'AAPL'), "
            "('2026-11-10T09:00:01+00:00', 'AAPL')"
        )
    conn = _reader(sp)
    trades, _ = query_trades(
        conn,
        symbol=None,
        date_value=None,
        from_ts=None,
        to_ts="2026-11-10T09:00:00Z",
        limit=10,
        tz=timezone.utc,
    )
    snaps, _ = query_price_snapshots(
        conn,
        symbol="AAPL",
        date_value=None,
        from_ts=None,
        to_ts="2026-11-10T09:00:00Z",
        limit=10,
        tz=timezone.utc,
    )
    conn.close()
    assert [row["ts"] for row in trades] == [
        "2026-11-10T08:59:59.999+00:00",
        "2026-11-10T09:00:00.000+00:00",
    ]
    assert [row["ts"] for row in snaps] == ["2026-11-10T09:00:00+00:00"]


def test_a_from_bound_still_includes_both_precisions_of_its_second(
    sp: StatsProcess,
) -> None:
    _trade(sp, 1, "2026-11-10T09:00:00.000+00:00")
    _trade(sp, 2, "2026-11-10T08:59:59.999+00:00")
    conn = _reader(sp)
    trades, _ = query_trades(
        conn,
        symbol=None,
        date_value=None,
        from_ts="2026-11-10T09:00:00Z",
        to_ts=None,
        limit=10,
        tz=timezone.utc,
    )
    conn.close()
    assert [row["ts"] for row in trades] == ["2026-11-10T09:00:00.000+00:00"]


def test_each_gap_row_names_the_check_that_found_it(sp: StatsProcess) -> None:
    for seq, n in ((1, 1), (2, 2), (5, 5)):
        sp._check_topic_sequence("trade.executed", seq)
        _trade(sp, n, "2026-11-10T10:00:00+00:00")
    conn = _reader(sp)
    gaps, _ = query_feed_gaps(
        conn, date_value=None, from_ts=None, to_ts=None, limit=10, tz=timezone.utc
    )
    conn.close()
    assert sorted((g["stream"], g["source"], g["missing_count"]) for g in gaps) == [
        ("trade.executed", "publisher_seq", 2),
        ("trade.executed", "trade_id", 2),
    ]


# --- WP-FL04 (L022): the end of an engine run ---------------------------------


def _gap_rows(sp: StatsProcess) -> list[tuple[str, int, int, int]]:
    conn = _reader(sp)
    gaps, _ = query_feed_gaps(
        conn, date_value=None, from_ts=None, to_ts=None, limit=10, tz=timezone.utc
    )
    conn.close()
    return [
        (g["source"], g["expected_id"], g["received_id"], g["missing_count"])
        for g in gaps
    ]


def test_trades_lost_before_the_engine_stopped_are_a_gap(sp: StatsProcess) -> None:
    for n in (1, 2, 3):
        _trade(sp, n, "2026-11-10T10:00:00+00:00")
    sp._on_eod({"books": [], "last_trade_id": "000001-000000005"})
    assert _gap_rows(sp) == [("run_end", 4, 6, 2)]


def test_a_complete_run_is_no_gap(sp: StatsProcess) -> None:
    for n in (1, 2, 3):
        _trade(sp, n, "2026-11-10T10:00:00+00:00")
    sp._on_eod({"books": [], "last_trade_id": "000001-000000003"})
    sp._on_eod({"books": [], "last_trade_id": None})
    assert _gap_rows(sp) == []


def test_the_last_trade_id_survives_a_stats_restart(tmp_path: Path) -> None:
    """Seeded from trade_log, as pm-clearing's from trade_events: the run's
    end, and its next trade, are compared with what was recorded before."""
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        first = StatsProcess(tmp_path / "stats.db")
        for n in (1, 2):
            _trade(first, n, "2026-11-10T10:00:00+00:00")
        first._running = False
        first.close()
        second = StatsProcess(tmp_path / "stats.db")
    try:
        assert second._last_trade_id == (1, 2)
        second._on_eod({"books": [], "last_trade_id": "000001-000000004"})
        assert _gap_rows(second) == [("run_end", 3, 5, 2)]
    finally:
        second._running = False
        second.close()
