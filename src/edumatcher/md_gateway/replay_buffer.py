"""Time-bounded replay buffers for CALF streams.

Replay is kept per (channel, symbol) stream in memory and evicted by age.
This keeps implementation simple, deterministic, and easy to reason about.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

StreamKey = tuple[str, str]


@dataclass(frozen=True)
class ReplayEvent:
    """One replayable stream event."""

    seq: int
    created_mono: float
    line: bytes
    trade_id: Optional[str] = None


class ReplayMissError(RuntimeError):
    """Raised when replay cannot satisfy the requested ``last_seq``."""


class ReplayBuffer:
    """Per-stream, time-bounded replay storage."""

    def __init__(self, replay_window_sec: int) -> None:
        self._window_sec = replay_window_sec
        self._events: dict[StreamKey, deque[ReplayEvent]] = defaultdict(deque)
        self._trade_ids: dict[StreamKey, set[str]] = defaultdict(set)

    def append(
        self,
        ch: str,
        sym: str,
        seq: int,
        line: bytes,
        trade_id: Optional[str] = None,
    ) -> bool:
        """Append one stream event and prune expired entries."""
        key = (ch, sym)
        now = time.monotonic()
        self._prune_stream(key, now)
        if trade_id is not None and trade_id in self._trade_ids[key]:
            return False
        self._events[key].append(
            ReplayEvent(seq=seq, created_mono=now, line=line, trade_id=trade_id)
        )
        if trade_id is not None:
            self._trade_ids[key].add(trade_id)
        return True

    def replay_since(self, ch: str, sym: str, last_seq: int) -> list[bytes]:
        """Return events with sequence > ``last_seq`` for stream.

        Raises
        ------
        ReplayMissError
            If requested history falls before oldest retained sequence.
        """
        key = (ch, sym)
        now = time.monotonic()
        self._prune_stream(key, now)

        events = self._events.get(key)
        if not events:
            return []

        oldest = events[0].seq
        if last_seq < oldest - 1:
            raise ReplayMissError(
                f"requested last_seq={last_seq} before oldest retained={oldest}"
            )

        return [event.line for event in events if event.seq > last_seq]

    def _prune_stream(self, key: StreamKey, now: float) -> None:
        cutoff = now - self._window_sec
        q = self._events.get(key)
        if q is None:
            return
        while q and q[0].created_mono < cutoff:
            event = q.popleft()
            if event.trade_id is not None:
                self._trade_ids[key].discard(event.trade_id)
