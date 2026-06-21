"""Per-stream sequence allocator for CALF.

CALF sequence numbers are maintained independently per (channel, symbol) stream.
The allocator starts streams lazily and supports two operations:

1. ensure_started: return current sequence, initializing to 1 if unseen
2. next_seq: increment and return next sequence for emitted incremental events
"""

from __future__ import annotations

from dataclasses import dataclass, field

StreamKey = tuple[str, str]


@dataclass
class SequenceAllocator:
    """Allocate and track stream-local sequence numbers."""

    _seq: dict[StreamKey, int] = field(default_factory=dict)

    def ensure_started(self, ch: str, sym: str) -> int:
        """Return current sequence for stream, initializing to 1 when unseen.

        This is used for snapshot baselines so a first-time subscriber always
        receives a strictly positive ``SEQ`` and can then expect incrementals at
        ``SEQ + 1``.
        """
        key = (ch, sym)
        cur = self._seq.get(key)
        if cur is None:
            self._seq[key] = 1
            return 1
        return cur

    def next_seq(self, ch: str, sym: str) -> int:
        """Increment and return the next sequence for stream events."""
        key = (ch, sym)
        cur = self._seq.get(key)
        if cur is None:
            nxt = 1
        else:
            nxt = cur + 1
        self._seq[key] = nxt
        return nxt

    def current(self, ch: str, sym: str) -> int | None:
        """Return current sequence for stream if initialized."""
        return self._seq.get((ch, sym))
