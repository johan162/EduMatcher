from __future__ import annotations

import time

import pytest

from edumatcher.md_gateway.replay_buffer import ReplayBuffer, ReplayMissError


def test_replay_since_returns_lines_after_seq() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 1, b"A\n")
    rb.append("TOP", "AAPL", 2, b"B\n")
    assert rb.replay_since("TOP", "AAPL", 1) == [b"B\n"]


def test_replay_miss_raises() -> None:
    rb = ReplayBuffer(replay_window_sec=30)
    rb.append("TOP", "AAPL", 10, b"X\n")
    with pytest.raises(ReplayMissError):
        rb.replay_since("TOP", "AAPL", 1)


def test_prune_by_window() -> None:
    rb = ReplayBuffer(replay_window_sec=1)
    rb.append("TOP", "AAPL", 1, b"A\n")
    time.sleep(1.1)
    rb.append("TOP", "AAPL", 2, b"B\n")
    assert rb.replay_since("TOP", "AAPL", 1) == [b"B\n"]
