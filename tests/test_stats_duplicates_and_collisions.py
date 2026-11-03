"""K9 (S1, S4): duplicate trades and same-millisecond index updates in pm-stats.

S1: ``_on_trade`` mutated the accumulator and wrote ``daily_stats`` *before* the
    ``INSERT OR IGNORE`` that discarded a repeated ``trade_id``, so a duplicate
    delivery was counted in the rollup though it never reached ``trade_log``
    (the existing test asserted only the row count).
S4: ``index_level_snapshots`` was keyed ``(ts, index_id)`` at millisecond
    resolution and written ``OR IGNORE``, while the rollup counted the update:
    after a restart the rollup, rebuilt from the snapshots, lost it.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K9.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.stats.main import StatsProcess

from tests.support.faults import fail_once
from tests.support.restart import restart_equivalence

_BASE = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()


def _ns(offset_sec: float) -> int:
    return int((_BASE + offset_sec) * 1_000_000_000)


def _open(db: Path) -> StatsProcess:
    fake = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake),
        patch("edumatcher.stats.main.make_pusher", return_value=fake),
        patch("edumatcher.stats.main.make_replier", return_value=fake),
    ):
        return StatsProcess(db, session_tz=timezone.utc)


def _trade(trade_id: str, price: float, qty: int, at: float) -> dict[str, Any]:
    return {
        "id": trade_id,
        "symbol": "AAPL",
        "price": price,
        "quantity": qty,
        "ts_ns": _ns(at),
    }


def _daily(conn: sqlite3.Connection) -> tuple[Any, ...]:
    return conn.execute(
        "SELECT trade_count, volume, turnover, vwap, open_price, close_price,"
        " high_price, low_price, largest_trade_qty FROM daily_stats"
    ).fetchone()


def _index_update(proc: StatsProcess, level: float, at: float) -> None:
    proc._on_index_update({"index_id": "EDU100", "level": level, "ts_ns": _ns(at)})


# --- S1 ---------------------------------------------------------------------


def test_duplicate_trade_is_counted_once_in_the_rollup(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    payload = _trade("1-1", 100.0, 10, 0)

    proc._on_trade(payload)
    proc._on_trade(payload)

    assert proc._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] == 1
    single = _daily(proc._conn)
    assert single[0] == 1  # trade_count
    assert single[1] == 10  # volume
    assert single[2] == 10 * 10_000  # turnover in ticks
    assert single[3] == 10_000  # vwap
    proc.close()


def test_duplicate_with_other_values_does_not_move_the_rollup(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    proc._on_trade(_trade("1-1", 100.0, 10, 0))
    before = _daily(proc._conn)

    proc._on_trade(_trade("1-1", 150.0, 99, 1))  # same id, different print

    assert _daily(proc._conn) == before
    proc.close()


def test_live_rollup_equals_the_rehydrated_rollup_after_duplicates(
    tmp_path: Path,
) -> None:
    db = tmp_path / "s.db"
    proc = _open(db)
    for n, (price, qty) in enumerate([(100.0, 10), (101.0, 20), (99.0, 5)], start=1):
        payload = _trade(f"1-{n}", price, qty, n)
        proc._on_trade(payload)
        proc._on_trade(payload)
    live = _daily(proc._conn)
    proc.close()

    restarted = _open(db)
    restarted._on_trade(_trade("1-3", 99.0, 5, 3))  # a replay after restart
    after = _daily(restarted._conn)
    restarted.close()

    assert after == live


def test_a_duplicate_does_not_register_as_a_feed_gap(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    for n in (1, 2, 3):
        proc._on_trade(_trade(f"1-{n}", 100.0, 1, n))
    proc._on_trade(_trade("1-1", 100.0, 1, 1))  # replay of an old trade
    proc._on_trade(_trade("1-4", 100.0, 1, 4))  # the genuine next one

    assert proc._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0
    proc.close()


def test_failed_write_leaves_the_rollup_matching_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    proc = _open(tmp_path / "s.db")
    proc._on_trade(_trade("1-1", 100.0, 10, 0))

    with fail_once(
        monkeypatch, proc, "_write_daily", sqlite3.OperationalError("disk full")
    ):
        with pytest.raises(sqlite3.OperationalError):
            proc._on_trade(_trade("1-2", 110.0, 20, 1))
        proc._on_trade(_trade("1-2", 110.0, 20, 1))  # the redelivery

    row = _daily(proc._conn)
    assert (row[0], row[1]) == (2, 30)
    proc.close()


# --- S4 ---------------------------------------------------------------------


def test_same_millisecond_index_updates_are_all_kept(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    _index_update(proc, 1000.0, 0)
    _index_update(proc, 1010.0, 0.0001)  # same millisecond
    _index_update(proc, 1020.0, 0.0002)

    snapshots = proc._conn.execute(
        "SELECT level FROM index_level_snapshots ORDER BY rowid"
    ).fetchall()
    assert [r[0] for r in snapshots] == [1000.0, 1010.0, 1020.0]
    proc.close()


def test_rehydrated_index_rollup_counts_same_millisecond_updates(
    tmp_path: Path,
) -> None:
    db = tmp_path / "s.db"
    proc = _open(db)
    _index_update(proc, 1000.0, 0)
    _index_update(proc, 1010.0, 0.0001)
    live = proc._conn.execute(
        "SELECT open_level, high_level, low_level, close_level, update_count"
        " FROM index_daily_stats"
    ).fetchone()
    assert live[4] == 2
    proc.close()

    restarted = _open(db)
    _index_update(restarted, 1005.0, 5)
    row = restarted._conn.execute(
        "SELECT open_level, high_level, low_level, close_level, update_count"
        " FROM index_daily_stats"
    ).fetchone()
    restarted.close()

    assert row == (1000.0, 1010.0, 1000.0, 1005.0, 3)


def test_stats_restart_equivalence_with_duplicates_and_collisions(
    tmp_path: Path,
) -> None:
    db = tmp_path / "s.db"
    proc = _open(db)
    for n in (1, 2):
        payload = _trade(f"1-{n}", 100.0 + n, 10 * n, n)
        proc._on_trade(payload)
        proc._on_trade(payload)
    _index_update(proc, 1000.0, 0)
    _index_update(proc, 1010.0, 0.0001)
    opened: list[StatsProcess] = []
    day = "2026-06-14"

    def observed(p: StatsProcess) -> tuple[Any, Any]:
        # The accumulators, rebuilt from the tables on a fresh process.
        return p._accum_for("AAPL", day), p._index_accum_for("EDU100", day)

    def restart() -> StatsProcess:
        proc.close()  # the writer lock allows one recorder per database
        p = _open(db)
        opened.append(p)
        return p

    def durable() -> Any:
        conn = sqlite3.connect(db)
        try:
            return [
                conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in ("trade_log", "index_level_snapshots")
            ]
        finally:
            conn.close()

    try:
        restart_equivalence(proc, restart=restart, snapshot=observed, durable=durable)
    finally:
        proc.close()
        for p in opened:
            p.close()
