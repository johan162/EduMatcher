from __future__ import annotations

from edumatcher.md_gateway.sequencer import SequenceAllocator


def test_ensure_started_initializes_to_one() -> None:
    seq = SequenceAllocator()
    assert seq.ensure_started("TOP", "AAPL") == 1
    assert seq.current("TOP", "AAPL") == 1


def test_next_seq_increments_per_stream() -> None:
    seq = SequenceAllocator()
    assert seq.next_seq("TOP", "AAPL") == 1
    assert seq.next_seq("TOP", "AAPL") == 2
    assert seq.next_seq("TOP", "MSFT") == 1
