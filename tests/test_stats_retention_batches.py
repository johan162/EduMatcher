"""WP-STA04: retention deletes in bounded batches; one wake-up drains many
messages (P2, P4).

A single prune transaction of 900 000 order_events took 3.4 s on the receive
thread, long enough to overflow the SUB high-water mark under a swarm.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq

import edumatcher.stats.main as stats_main
from edumatcher.models.message import encode
from edumatcher.stats.main import StatsProcess

OLD = "2000-01-03T10:00:00.000+00:00"
NEW = "2999-01-03T10:00:00.000+00:00"
BATCH = 1_000


@pytest.fixture
def sp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[StatsProcess]:
    monkeypatch.setattr(stats_main, "_PRUNE_BATCH_ROWS", BATCH)
    with (
        patch(
            "edumatcher.stats.main.make_subscriber",
            side_effect=[MagicMock(name="sub"), MagicMock(name="index_sub")],
        ),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        proc = StatsProcess(tmp_path / "stats.db", keep_days=2)
    yield proc
    proc._running = False
    proc.close()


def _fill_order_events(sp: StatsProcess, old: int, new: int) -> None:
    rows = [(OLD, f"O{i}") for i in range(old)] + [(NEW, f"N{i}") for i in range(new)]
    with sp._conn:
        sp._conn.executemany(
            "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol)"
            " VALUES (?, 'ACK', ?, 'AI001', 'AAPL')",
            rows,
        )


def _count(sp: StatsProcess, ts: str) -> int:
    (n,) = sp._conn.execute(
        "SELECT COUNT(*) FROM order_events WHERE ts = ?", (ts,)
    ).fetchone()
    return int(n)


def test_one_prune_call_deletes_at_most_one_batch(sp: StatsProcess) -> None:
    _fill_order_events(sp, old=5 * BATCH, new=10)
    sp._prune_if_due()
    assert _count(sp, OLD) == 4 * BATCH


def test_repeated_calls_finish_the_round_and_spare_undue_rows(
    sp: StatsProcess,
) -> None:
    _fill_order_events(sp, old=5 * BATCH + 7, new=10)
    for _ in range(6):
        sp._prune_if_due()
    assert (_count(sp, OLD), _count(sp, NEW)) == (0, 10)
    # The round is over: new old rows wait for the next hourly round.
    _fill_order_events(sp, old=3, new=0)
    sp._prune_if_due()
    assert _count(sp, OLD) == 3


def test_messages_are_recorded_between_prune_batches(sp: StatsProcess) -> None:
    _fill_order_events(sp, old=5 * BATCH, new=0)
    sub: Any = sp.sub
    trades = iter(range(1, 100))
    sub.recv_multipart.side_effect = lambda: encode(
        "trade.executed",
        {
            "id": f"000001-{next(trades):09d}",
            "symbol": "AAPL",
            "price": 1.0,
            "quantity": 1,
            "ts_ns": 1_792_850_048_220_023_754,
            "tick_decimals": 2,
        },
    )
    sub.poll.return_value = False
    wakes = {"n": 0}

    def _poll(timeout: int = 0) -> dict[Any, int]:
        wakes["n"] += 1
        if wakes["n"] == 2:
            sp._running = False
        return {sp.sub: zmq.POLLIN}

    poller = MagicMock()
    poller.poll.side_effect = _poll
    with patch("edumatcher.stats.main.zmq.Poller", return_value=poller):
        sp._receive_loop()
    (traded,) = sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()
    assert traded == 2
    assert _count(sp, OLD) == 3 * BATCH  # two batches, one per iteration


def test_one_wake_up_drains_the_queued_messages(sp: StatsProcess) -> None:
    queue = [
        encode(
            "trade.executed",
            {
                "id": f"000001-{i:09d}",
                "symbol": "AAPL",
                "price": 1.0,
                "quantity": 1,
                "ts_ns": 1_792_850_048_220_023_754 + i,
                "tick_decimals": 2,
            },
        )
        for i in range(1, 301)
    ]
    sub: Any = sp.sub
    sub.recv_multipart.side_effect = lambda: queue.pop(0)
    sub.poll.side_effect = lambda timeout=0: bool(queue)

    def _poll(timeout: int = 0) -> dict[Any, int]:
        sp._running = False
        return {sp.sub: zmq.POLLIN}

    poller = MagicMock()
    poller.poll.side_effect = _poll
    with (
        patch("edumatcher.stats.main.zmq.Poller", return_value=poller),
        patch.object(sp, "_drain"),
    ):
        sp._receive_loop()
    (traded,) = sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()
    assert traded == 300
    assert poller.poll.call_count == 1
