from __future__ import annotations

import time

import pytest

from edumatcher.md_gateway.replay_buffer import ReplayBuffer, ReplayMissError


def test_replay_since_returns_lines_after_seq() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 1, b"A\n")
    rb.append("TOP", "AAPL", 2, b"B\n")
    assert rb.replay_since("TOP", "AAPL", 1, 2) == [b"B\n"]


def test_trade_replay_keeps_one_event_per_trade_id() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    assert rb.append("TRADE", "AAPL", 1, b"first\n", "000001-000000001")
    assert not rb.append("TRADE", "AAPL", 2, b"duplicate\n", "000001-000000001")
    assert rb.replay_since("TRADE", "AAPL", 0, 1) == [b"first\n"]


def test_replay_miss_raises() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 10, b"X\n")
    with pytest.raises(ReplayMissError):
        rb.replay_since("TOP", "AAPL", 1, 10)


def test_prune_by_window() -> None:
    rb = ReplayBuffer(replay_window_sec=1)
    rb.append("TOP", "AAPL", 1, b"A\n")
    time.sleep(1.1)
    rb.append("TOP", "AAPL", 2, b"B\n")
    assert rb.replay_since("TOP", "AAPL", 1, 2) == [b"B\n"]


def test_nothing_new_is_an_empty_replay() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 1, b"A\n")
    assert rb.replay_since("TOP", "AAPL", 1, 1) == []


def test_everything_aged_out_is_a_miss_not_an_empty_replay() -> None:
    """W5: the buffer used to answer [] once a quiet stream's events had all
    expired, so a client silently skipped them."""
    rb = ReplayBuffer(replay_window_sec=1)
    for seq in range(1, 6):
        rb.append("TOP", "AAPL", seq, b"X\n")
    time.sleep(1.1)
    with pytest.raises(ReplayMissError):
        rb.replay_since("TOP", "AAPL", 2, 5)


def test_a_position_ahead_of_the_stream_is_a_miss() -> None:
    """W5: after a gateway restart a client's LASTSEQ is from the old run."""
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 1, b"A\n")
    with pytest.raises(ReplayMissError):
        rb.replay_since("TOP", "AAPL", 500, 1)
    with pytest.raises(ReplayMissError):
        rb.replay_since("TOP", "MSFT", 3, 0)  # never emitted at all


def test_has_trade() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TRADE", "AAPL", 1, b"first\n", "T1")
    assert rb.has_trade("TRADE", "AAPL", "T1")
    assert not rb.has_trade("TRADE", "AAPL", "T2")
