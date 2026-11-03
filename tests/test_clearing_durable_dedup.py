"""K4 (C1, C2): durable write ordering and duplicate protection in clearing.

C1: ``_flush`` applied every buffered trade to the in-memory ledger before the
database commit, so a failed commit followed by a retry applied them twice.
C2: duplicates were recognised by a bounded in-memory LRU keyed on
``(id, ts_ns)``, while the archive's identity is ``id`` alone; a restart, an
eviction or a replay with a new timestamp bypassed it and the ledger counted
the trade twice (the archive ignored the second row, the positions did not).
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K4.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from edumatcher.clearing import main as clearing_main
from edumatcher.clearing.main import ClearingProcess
from edumatcher.models.trade import Trade, reset_trade_ids_for_tests, set_run_seq

from tests.support.faults import fail_once
from tests.support.restart import restart_equivalence


def _process(db_path: Path) -> ClearingProcess:
    return ClearingProcess(
        pub_addr="inproc://k4-unused",
        db_path=db_path,
        flush_size=1_000,
        flush_interval_sec=3600.0,
        print_every=0,
        retention_days=3650,
    )


def _trade(trade_id: str, qty: int = 10, price: int = 1000, ts_ns: int = 0) -> Trade:
    reset_trade_ids_for_tests()
    set_run_seq(1)
    t = Trade.create(
        symbol="AAPL",
        buy_order_id="O_BUY",
        sell_order_id="O_SELL",
        buy_gateway_id="GW_BUY",
        sell_gateway_id="GW_SELL",
        price=price,
        quantity=qty,
        aggressor_side="BUY",
    )
    return replace(t, id=trade_id, ts_ns=ts_ns or t.ts_ns)


def _receive(process: ClearingProcess, trade: Trade) -> None:
    """What the receive loop does with one decoded trade."""
    with process._lock:
        if not process._is_duplicate(trade):
            process._buffer.append(trade)


def _positions(process: ClearingProcess) -> dict[tuple[str, str], tuple[int, float]]:
    return {
        (p.gateway_id, p.symbol): (p.net_qty, p.realized_pnl)
        for p in process._ledger.all_positions()
    }


def _db_positions(db_path: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT gateway_id, symbol, net_qty, buy_qty, sell_qty, realized_pnl"
            " FROM gateway_symbol_positions ORDER BY 1, 2"
        ).fetchall()
    finally:
        conn.close()


def test_failed_flush_then_retry_applies_each_trade_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _process(tmp_path / "c.db")
    _receive(process, _trade("1-1", qty=10))

    with fail_once(
        monkeypatch, clearing_main, "flush_batch", sqlite3.OperationalError("disk")
    ):
        with pytest.raises(sqlite3.OperationalError):
            process._flush()
        process._flush()

    assert _positions(process) == {
        ("GW_BUY", "AAPL"): (10, 0.0),
        ("GW_SELL", "AAPL"): (-10, 0.0),
    }
    assert [r[2:5] for r in _db_positions(tmp_path / "c.db")] == [
        (10, 10, 0),
        (-10, 0, 10),
    ]
    process._conn.close()


def test_failed_rollback_keeps_the_ledger_instead_of_emptying_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The flush fails and so does the rollback's re-read of the positions.
    The ledger must not be left empty: the next flush would write positions
    rebuilt from zero over the persisted ones (K1-K10 review #2)."""
    db = tmp_path / "c.db"
    process = _process(db)
    for n in range(3):
        _receive(process, _trade(f"1-{n}", qty=10))
    process._flush()
    _receive(process, _trade("1-9", qty=1))

    error = sqlite3.OperationalError("disk I/O error")
    with fail_once(monkeypatch, clearing_main, "flush_batch", error):
        with fail_once(monkeypatch, clearing_main, "fetch_all_positions", error):
            with pytest.raises(sqlite3.OperationalError):
                process._flush()
    process._flush()

    assert [(r[0], r[2]) for r in _db_positions(db)] == [
        ("GW_BUY", 31),
        ("GW_SELL", -31),
    ]
    process._conn.close()


def test_replay_after_restart_is_not_applied_again(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    first = _process(db)
    _receive(first, _trade("1-1", qty=10))
    first._flush()
    first._conn.close()

    second = _process(db)
    _receive(second, _trade("1-1", qty=10))
    second._flush()

    assert _positions(second)[("GW_BUY", "AAPL")] == (10, 0.0)
    assert [r[2] for r in _db_positions(db)] == [10, -10]
    second._conn.close()


def test_replay_after_lru_eviction_is_not_applied_again(tmp_path: Path) -> None:
    process = _process(tmp_path / "c.db")
    process._seen_cap = 2
    _receive(process, _trade("1-1", qty=10))
    process._flush()
    for n in (2, 3, 4):
        _receive(process, _trade(f"1-{n}", qty=1))
    process._flush()
    before = _positions(process)

    _receive(process, _trade("1-1", qty=10))  # evicted from the LRU by now
    process._flush()

    assert _positions(process) == before
    process._conn.close()


def test_replay_with_a_different_timestamp_is_not_applied_again(
    tmp_path: Path,
) -> None:
    process = _process(tmp_path / "c.db")
    _receive(process, _trade("1-1", qty=10, ts_ns=1_000))
    process._flush()
    before = _positions(process)

    _receive(process, _trade("1-1", qty=10, ts_ns=2_000))
    process._flush()

    assert _positions(process) == before
    process._conn.close()


def test_duplicate_inside_one_unflushed_batch_is_applied_once(tmp_path: Path) -> None:
    process = _process(tmp_path / "c.db")
    process._buffer.extend([_trade("1-1", qty=10), _trade("1-1", qty=10)])

    process._flush()

    assert _positions(process)[("GW_BUY", "AAPL")] == (10, 0.0)
    process._conn.close()


def test_restart_with_interleaved_replay_is_equivalent(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    process = _process(db)
    for n in (1, 2, 3):
        _receive(process, _trade(f"1-{n}", qty=n))
    process._flush()
    live: list[ClearingProcess] = []

    def restart() -> ClearingProcess:
        restarted = _process(db)
        for n in (2, 1, 3, 2):  # replay, out of order, with repeats
            _receive(restarted, _trade(f"1-{n}", qty=n))
        restarted._flush()
        live.append(restarted)
        return restarted

    restart_equivalence(
        process,
        restart=restart,
        snapshot=_positions,
        durable=lambda: _db_positions(db),
    )
    for p in (process, *live):
        p._conn.close()


@pytest.mark.parametrize("seed", range(5))
def test_applying_a_stream_twice_in_any_order_equals_once(
    tmp_path: Path, seed: int
) -> None:
    rng = random.Random(seed)
    stream = [
        _trade(f"1-{n}", qty=rng.randint(1, 50), price=rng.randint(900, 1100))
        for n in range(1, 31)
    ]
    once = _process(tmp_path / "once.db")
    for t in stream:
        _receive(once, t)
    once._flush()

    twice = _process(tmp_path / "twice.db")
    doubled = stream + stream
    rng.shuffle(doubled)
    for i, t in enumerate(doubled):
        _receive(twice, t)
        if rng.random() < 0.2:
            twice._flush()
        if i == len(doubled) // 2:  # a mid-stream restart
            twice._flush()
            twice._conn.close()
            twice = _process(tmp_path / "twice.db")
    twice._flush()

    # Order differs, so compare the order-independent totals.
    def totals(p: ClearingProcess) -> dict[tuple[str, str], tuple[int, int, int]]:
        return {
            (x.gateway_id, x.symbol): (x.net_qty, x.buy_qty, x.sell_qty)
            for x in p._ledger.all_positions()
        }

    assert totals(twice) == totals(once)
    once._conn.close()
    twice._conn.close()
