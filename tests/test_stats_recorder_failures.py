"""WP-STA02: every recorder failure is visible (C2, C8, C13).

- C2: a receive loop that died while pm-stats waited for the engine ended
  the process with status 0.
- C8: index-stream failures were counted nowhere, and events_recorded
  counted ignored messages as recorded.
- C13: EINTR on poll ended recording.
"""

from __future__ import annotations

import errno
import logging
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq

from edumatcher.models.message import encode
from edumatcher.stats.main import StatsProcess

TRADE = {
    "id": "000001-000000001",
    "symbol": "AAPL",
    "price": 100.0,
    "quantity": 10,
    "ts_ns": 1_792_850_048_220_023_754,
    "tick_decimals": 2,
}


@pytest.fixture
def sp(tmp_path: Path) -> Iterator[StatsProcess]:
    """Distinct socket mocks, so the engine and index paths can be told apart."""
    with (
        patch(
            "edumatcher.stats.main.make_subscriber",
            side_effect=[MagicMock(name="sub"), MagicMock(name="index_sub")],
        ),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        proc = StatsProcess(tmp_path / "stats.db")
    yield proc
    proc._running = False
    proc.close()


def _metrics(sp: StatsProcess) -> dict[str, float]:
    return {m.name: m.value for m in sp.metric_samples()}


# --- C2 ----------------------------------------------------------------------


def test_a_receive_loop_that_dies_during_the_engine_wait_exits_non_zero(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch.object(
            sp, "_receive_loop", side_effect=sqlite3.OperationalError("disk I/O error")
        ),
        patch.object(sp, "_request_startup_symbols", return_value=False),
        patch("edumatcher.stats.main.time.sleep"),
        caplog.at_level(logging.CRITICAL, logger="edumatcher.stats.main"),
    ):
        assert sp.run() == 1
    assert "stopped recording" in caplog.text


def test_a_stop_during_the_engine_wait_still_exits_zero(sp: StatsProcess) -> None:
    def _wait() -> None:
        while sp._running:
            pass

    def _refuse_and_stop() -> bool:
        sp._stop()
        return False

    with (
        patch.object(sp, "_receive_loop", side_effect=_wait),
        patch.object(sp, "_request_startup_symbols", side_effect=_refuse_and_stop),
        patch("edumatcher.stats.main.time.sleep"),
    ):
        assert sp.run() == 0


# --- C8 ----------------------------------------------------------------------


def test_an_index_write_failure_is_counted_as_dropped(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    index_sub: Any = sp.index_sub
    index_sub.recv_multipart.return_value = encode(
        "index.update", {"index_id": "EDU100", "level": 1000.0, "ts_ns": 1}
    )
    with (
        patch.object(sp, "_on_index_update", side_effect=RuntimeError("boom")),
        caplog.at_level(logging.ERROR, logger="edumatcher.stats.main"),
    ):
        sp._receive_one_index_message()
    assert _metrics(sp)["stats.records_dropped"] == 1
    assert "boom" in caplog.text


def test_an_undecodable_index_message_is_counted(sp: StatsProcess) -> None:
    index_sub: Any = sp.index_sub
    index_sub.recv_multipart.return_value = [b"index.update", b"{not json"]
    sp._receive_one_index_message()
    assert sp._debug_counts["messages_undecodable"] == 1


def test_a_recorded_index_update_counts_as_recorded(sp: StatsProcess) -> None:
    index_sub: Any = sp.index_sub
    index_sub.recv_multipart.return_value = encode(
        "index.update", {"index_id": "EDU100", "level": 1000.0, "ts_ns": 1}
    )
    sp._receive_one_index_message()
    assert _metrics(sp)["stats.events_recorded"] == 1


def test_an_ignored_trade_is_not_counted_as_recorded(sp: StatsProcess) -> None:
    sub: Any = sp.sub
    sub.recv_multipart.return_value = encode("trade.executed", {**TRADE, "symbol": ""})
    sp._receive_one_engine_message()
    assert _metrics(sp)["stats.events_recorded"] == 0
    sub.recv_multipart.return_value = encode("trade.executed", TRADE)
    sp._receive_one_engine_message()
    assert _metrics(sp)["stats.events_recorded"] == 1


def test_a_duplicate_trade_is_not_counted_twice(sp: StatsProcess) -> None:
    sub: Any = sp.sub
    sub.recv_multipart.return_value = encode("trade.executed", TRADE)
    sp._receive_one_engine_message()
    sp._receive_one_engine_message()
    assert _metrics(sp)["stats.events_recorded"] == 1


# --- C13 ---------------------------------------------------------------------


def test_eintr_on_poll_does_not_end_recording(sp: StatsProcess) -> None:
    sub: Any = sp.sub
    sub.recv_multipart.return_value = encode("trade.executed", TRADE)
    sub.poll.return_value = False  # nothing left to drain
    calls = {"n": 0}

    def _poll(timeout: int = 0) -> list[tuple[Any, int]]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise zmq.ZMQError(errno.EINTR)
        sp._running = False
        return [(sp.sub, zmq.POLLIN)]

    poller = MagicMock()
    poller.poll.side_effect = _poll
    with patch("edumatcher.stats.main.zmq.Poller", return_value=poller):
        sp._receive()
    assert sp._receive_failure is None
    (count,) = sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()
    assert count == 1
