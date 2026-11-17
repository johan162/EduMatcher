"""WP-CLR02 (clearing review H2): a trade missed while pm-clearing was down
is reported as a feed gap.

The in-run gap check kept the last trade id in memory only, so the first
trade after a restart was compared with nothing: trades published while
pm-clearing was down left no GAP, no reconcile difference and a short
position. See docs-design/reviews/EduMatcher-Clearing-Review-2026-11.md.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import pytest

from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.store import prune_old_events, query_feed_gaps
from edumatcher.models.message import make_trade_msg
from tests.conftest import opened

_NOW = time.time_ns()


def _trade(seq: int, run: int = 3, ts_ns: int | None = None) -> list[bytes]:
    return make_trade_msg(
        {
            "id": f"{run:06d}-{seq:09d}",
            "run_seq": run,
            "symbol": "AAPL",
            "buy_order_id": "b",
            "sell_order_id": "s",
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
            "price": 100.0,
            "quantity": 10,
            "aggressor_side": "BUY",
            "ts_ns": _NOW + seq if ts_ns is None else ts_ns,
            "tick_decimals": 2,
            "price_ticks": 10000,
            "match_type": "CONTINUOUS",
        }
    )


def _process(db: Path) -> ClearingProcess:
    proc = ClearingProcess(pub_addr="inproc://unused", db_path=db, print_every=0)
    opened(proc._conn)
    return proc


def _feed(proc: ClearingProcess, *seqs: int, run: int = 3) -> None:
    for seq in seqs:
        proc._handle_message(_trade(seq, run))
    proc.flush_now()


def _restart(proc: ClearingProcess, db: Path) -> ClearingProcess:
    proc._conn.close()
    return _process(db)


def _gaps(proc: ClearingProcess) -> list[dict[str, Any]]:
    return query_feed_gaps(proc._conn)


def test_trades_missed_during_a_restart_are_a_gap(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = tmp_path / "clearing.db"
    first = _process(db)
    _feed(first, 1, 2, 3, 4, 5)
    second = _restart(first, db)

    with caplog.at_level(logging.ERROR, logger="edumatcher.clearing.main"):
        _feed(second, 11, 12, 13, 14, 15)

    (gap,) = _gaps(second)
    assert gap["run_seq"] == 3
    assert (gap["last_seq"], gap["next_seq"], gap["missing_trades"]) == (5, 11, 5)
    assert gap["reason"] == "restart"
    assert "missing" in caplog.text


def test_an_in_run_gap_is_a_feed_gap(tmp_path: Path) -> None:
    proc = _process(tmp_path / "clearing.db")
    _feed(proc, 1, 2, 5)
    (gap,) = _gaps(proc)
    assert (gap["missing_trades"], gap["reason"]) == (2, "feed")


@pytest.mark.parametrize(
    ("after_restart", "run"), [((6, 7), 3), ((1, 2), 4)], ids=["next-id", "new-run"]
)
def test_a_contiguous_restart_or_a_new_run_is_not_a_gap(
    tmp_path: Path, after_restart: tuple[int, ...], run: int
) -> None:
    db = tmp_path / "clearing.db"
    first = _process(db)
    _feed(first, 1, 2, 3, 4, 5)
    second = _restart(first, db)

    _feed(second, *after_restart, run=run)

    assert _gaps(second) == []


def test_an_empty_ledger_has_nothing_to_compare(tmp_path: Path) -> None:
    proc = _process(tmp_path / "clearing.db")
    _feed(proc, 40, 41)
    assert _gaps(proc) == []


def test_pruned_history_is_compared_with_what_is_retained(tmp_path: Path) -> None:
    """The run's old trades were pruned; its newest retained one is the base."""
    db = tmp_path / "clearing.db"
    first = _process(db)
    old = _NOW - 30 * 86_400 * 10**9
    for seq in (1, 2):
        first._handle_message(_trade(seq, ts_ns=old + seq))
    _feed(first, 3, 4)
    prune_old_events(first._conn, retention_days=7)
    second = _restart(first, db)

    _feed(second, 5)

    assert _gaps(second) == []


def test_the_gaps_verb_shows_the_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from edumatcher.clearing import cli

    db = tmp_path / "clearing.db"
    first = _process(db)
    _feed(first, 1, 2)
    second = _restart(first, db)
    _feed(second, 9)
    second._conn.close()

    monkeypatch.setattr(
        "sys.argv",
        ["pm-clearing-cli", "--datapath", str(db), "--format", "json", "gaps"],
    )
    cli.main()

    (row,) = json.loads(capsys.readouterr().out)
    assert row["reason"] == "restart"
    assert row["missing_trades"] == 6


# --- WP-FL04 (L022): the end of an engine run ---------------------------------


def _eod(proc: ClearingProcess, last_trade_id: str | None) -> None:
    from edumatcher.models.message import make_eod_msg

    proc._handle_message(make_eod_msg([], last_trade_id=last_trade_id))


def test_trades_lost_before_the_engine_stopped_are_a_gap(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    proc = _process(tmp_path / "clearing.db")
    _feed(proc, 1, 2, 3, 4, 5)

    with caplog.at_level(logging.ERROR, logger="edumatcher.clearing.main"):
        _eod(proc, "000003-000000007")

    (gap,) = _gaps(proc)
    assert gap["run_seq"] == 3
    assert (gap["last_seq"], gap["next_seq"], gap["missing_trades"]) == (5, 8, 2)
    assert gap["reason"] == "end_of_run"
    assert "missing" in caplog.text


def test_a_complete_run_is_no_gap(tmp_path: Path) -> None:
    proc = _process(tmp_path / "clearing.db")
    _feed(proc, 1, 2, 3)
    _eod(proc, "000003-000000003")
    _eod(proc, None)  # a run without trades says so
    assert _gaps(proc) == []


def test_the_end_of_run_check_survives_a_clearing_restart(tmp_path: Path) -> None:
    db = tmp_path / "clearing.db"
    first = _process(db)
    _feed(first, 1, 2, 3)
    second = _restart(first, db)

    _eod(second, "000003-000000004")

    (gap,) = _gaps(second)
    assert (gap["last_seq"], gap["next_seq"], gap["missing_trades"]) == (3, 5, 1)


def test_a_run_none_of_whose_trades_arrived_is_a_gap_of_all_of_them(
    tmp_path: Path,
) -> None:
    proc = _process(tmp_path / "clearing.db")
    _feed(proc, 1, 2, run=2)
    _eod(proc, "000003-000000004")

    (gap,) = _gaps(proc)
    assert gap["run_seq"] == 3
    assert (gap["last_seq"], gap["next_seq"], gap["missing_trades"]) == (0, 5, 4)
    # The next run starts clean.
    _feed(proc, 1, run=4)
    assert len(_gaps(proc)) == 1
