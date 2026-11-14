"""A settled day's baseline cannot change under the ledger (EOD review H1).

pm-clearing rewrites a date's close snapshot whenever that date closes again:
after a reopen with a scheduler, or after another graceful shutdown without
one.  The next day must still be measured from what was settled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from edumatcher.clearing.store import (
    close_snapshot_is_final,
    flush_batch,
    open_writer_connection,
    record_session_event,
    write_close_snapshot,
)
from edumatcher.eod.ledger import balances, open_ledger, settled_dates
from edumatcher.eod.runner import Options, Paths, pending_dates, run_day
from tests.test_eod_runner import pos

NOW = datetime(2026, 7, 5, 12, tzinfo=UTC)
D, D1 = "2026-07-01", "2026-07-02"


class _Exchange:
    """pm-clearing's snapshot rule, driven the way the engine drives it."""

    def __init__(self, data: Path) -> None:
        self.data = data
        self.ts = 0

    def _phase(self, conn: object, day: str, state: str) -> None:
        self.ts += 1
        final = state == "CLOSED" and close_snapshot_is_final(conn, day)  # type: ignore[arg-type]
        record_session_event(
            conn,  # type: ignore[arg-type]
            event_type="PHASE",
            ts_ns=self.ts,
            trade_date=day,
            payload_json=json.dumps({"state": state}),
        )
        if state == "CLOSED" and not final:
            write_close_snapshot(conn, day)  # type: ignore[arg-type]

    def trading_day(self, day: str, unreal: float) -> None:
        """Open, trade to A's equity ``unreal`` ticks, close (with a scheduler)."""
        conn = open_writer_connection(self.data / "clearing.db")
        self._phase(conn, day, "CONTINUOUS")
        flush_batch(conn, [], [pos("A", 100, unreal), pos("B", -100, -unreal)], [])
        self._phase(conn, day, "CLOSED")
        conn.close()

    def shutdown(self, day: str, unreal: float) -> None:
        """A graceful shutdown without a scheduler (pm-clearing's system.eod)."""
        conn = open_writer_connection(self.data / "clearing.db")
        flush_batch(conn, [], [pos("A", 100, unreal), pos("B", -100, -unreal)], [])
        if not close_snapshot_is_final(conn, day):
            write_close_snapshot(conn, day)
        conn.close()


def _run(data: Path, day: str, **kw: object) -> dict[str, tuple[str, str]]:
    outcome = run_day(
        Paths(data), day, Options(**kw), today="2026-07-05", now=NOW  # type: ignore[arg-type]
    )
    return {s.step: (s.status, s.message) for s in outcome.steps}


def _pending(data: Path) -> None:
    for day in pending_dates(Paths(data)):
        _run(data, day)


def _balances(data: Path) -> dict[str, int]:
    ledger = open_ledger(data / "eod.db")
    try:
        return balances(ledger)
    finally:
        ledger.close()


def test_a_reopened_day_is_not_lost(tmp_path: Path) -> None:
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    ex.trading_day(D, 3000.0)  # pm-scheduler --speed: the same date again
    assert pending_dates(Paths(tmp_path)) == []
    ex.trading_day(D1, 3500.0)
    _pending(tmp_path)
    assert _balances(tmp_path) == {"A": 3500, "B": -3500}


def test_a_second_shutdown_after_a_forced_settle_is_not_lost(tmp_path: Path) -> None:
    ex = _Exchange(tmp_path)
    ex.shutdown(D, 1000.0)
    _run(tmp_path, D, force=True)
    ex.shutdown(D, 3000.0)  # restarted, traded, stopped again on D
    ex.shutdown(D1, 3500.0)
    _run(tmp_path, D1, force=True)
    assert _balances(tmp_path) == {"A": 3500, "B": -3500}


def test_the_settle_step_names_the_changed_snapshot(tmp_path: Path) -> None:
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    ex.trading_day(D, 3000.0)
    ex.trading_day(D1, 3500.0)
    status, message = _run(tmp_path, D1)["settle"]
    assert status == "warn"
    assert f"close snapshot of {D} changed after it was settled" in message


def test_an_unchanged_baseline_says_nothing(tmp_path: Path) -> None:
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    ex.trading_day(D1, 3500.0)
    assert _run(tmp_path, D1)["settle"] == ("ok", "settled")


def test_a_reset_clearing_db_starts_from_zero(tmp_path: Path) -> None:
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    (tmp_path / "clearing.db").unlink()  # emo clear --state
    ex.trading_day(D1, 500.0)
    _pending(tmp_path)
    assert _balances(tmp_path) == {"A": 1500, "B": -1500}


def test_redo_settles_from_the_rewritten_snapshot_and_drops_later_days(
    tmp_path: Path,
) -> None:
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    ex.trading_day(D, 3000.0)
    ex.trading_day(D1, 3500.0)
    _pending(tmp_path)
    assert _run(tmp_path, D, redo=True)["settle"][0] == "ok"
    ledger = open_ledger(tmp_path / "eod.db")
    try:
        assert settled_dates(ledger) == [D]
        assert balances(ledger) == {"A": 3000, "B": -3000}
        rows = ledger.execute(
            "SELECT DISTINCT trade_date FROM eod_close_equity"
        ).fetchall()
        assert [r[0] for r in rows] == [D]
    finally:
        ledger.close()
    _pending(tmp_path)
    assert _balances(tmp_path) == {"A": 3500, "B": -3500}


def test_a_reset_then_the_same_date_again_starts_from_zero(tmp_path: Path) -> None:
    # pm-opctl-cli clear --state keeps eod.db; trading resumes on the same date.
    ex = _Exchange(tmp_path)
    ex.trading_day(D, 1000.0)
    _pending(tmp_path)
    (tmp_path / "clearing.db").unlink()
    ex.trading_day(D, 300.0)  # a new clearing.db: equity starts again from 0
    ex.trading_day(D1, 500.0)
    status, message = _run(tmp_path, D1)["settle"]
    assert _balances(tmp_path) == {"A": 1500, "B": -1500}
    assert status == "warn" and f"clearing.db was replaced after {D}" in message
