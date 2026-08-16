"""In-gateway market-data stream cache for snapshot / resume.

Backs the snapshot-on-subscribe, explicit ``snapshot``, and ``resume`` verbs
on ``WS /api/v1/market-data`` (see
``docs-design/EduMatcher-MarketData-Snapshot-Resume.md``).

The cache is deliberately asymmetric, because the four subscribable channels
are not the same kind of stream:

* ``book``, ``depth``, ``auction`` (and its ``auction.indicative`` tense) are
  **full snapshots** republished on a timer — a gap is self-healing, so the
  cache keeps only the *latest* envelope per topic and a "resume" is answered
  by re-sending it.
* ``trades`` is a genuine append-only stream — the cache keeps a
  time-bounded tail so a client can replay the prints it missed.

Only the ``trades`` tail is aged out; the latest snapshot per topic is kept
regardless of age so a snapshot is always available even for a quiet symbol.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from edumatcher.api_gateway.events import market_data_symbol
from edumatcher.models.generated.auction import (
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
    topic_auction_indicative,
    topic_auction_result,
)
from edumatcher.models.generated.book import (
    PREFIX_BOOK_SNAPSHOT,
    PREFIX_DEPTH,
    topic_book_snapshot,
    topic_depth,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

#: The channels this cache serves. ``session`` / ``circuit_breaker`` are
#: always-on venue status, not subscribable, and are not cached here.
CACHED_CHANNELS: frozenset[str] = frozenset({"book", "depth", "trades", "auction"})


class ReplayMiss(RuntimeError):
    """Raised when a trade resume falls before the oldest retained print.

    Named to parallel ``md_gateway.replay_buffer.ReplayMissError``; the caller
    turns it into a ``resume.rejected`` / ``*.reset`` on the wire.
    """


@dataclass(frozen=True)
class _BufferedTrade:
    """One retained ``trade`` envelope with its arrival time and sequence."""

    seq: int
    created_mono: float
    event: dict[str, Any]


def event_channel(event_type: str) -> str | None:
    """Map a WebSocket envelope ``type`` to the client-facing channel name.

    Canonical classifier shared by the cache and the WS router so the two
    cannot disagree about which channel an event belongs to. Returns ``None``
    for anything that is not one of the cached market-data channels.
    """
    if event_type == "trade":
        return "trades"
    if event_type in {"auction", "auction.indicative"}:
        return "auction"
    if event_type in {"book", "depth"}:
        return event_type
    return None


def channel_for_topic(topic: str) -> str | None:
    """Map an engine topic to the client-facing channel, or ``None``.

    Used by the explicit ``resume`` verb, which names a topic rather than a
    channel. Mirrors ``event_channel`` but works from the topic string. Uses
    the generated topic constants rather than string literals (the pm-msgen
    literal gate forbids hard-coding migrated families' topics).
    """
    if topic == TOPIC_TRADE_EXECUTED:
        return "trades"
    if topic.startswith(PREFIX_AUCTION_RESULT) or topic.startswith(
        PREFIX_AUCTION_INDICATIVE
    ):
        return "auction"
    if topic.startswith(PREFIX_BOOK_SNAPSHOT):
        return "book"
    if topic.startswith(PREFIX_DEPTH):
        return "depth"
    return None


class MarketDataCache:
    """Latest-snapshot-per-topic plus a time-bounded ``trades`` tail."""

    def __init__(self, window_sec: int = 60) -> None:
        self._window_sec = window_sec
        # topic -> latest envelope, for book/depth/auction(.indicative).
        self._snapshots: dict[str, dict[str, Any]] = {}
        # symbol -> recent trade envelopes, oldest first, aged by window.
        self._trades: dict[str, deque[_BufferedTrade]] = defaultdict(deque)
        # channel -> symbols seen, so a wildcard subscribe can enumerate them.
        self._symbols_by_channel: dict[str, set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def record(self, event: dict[str, Any]) -> None:
        """Fold one outgoing market-data envelope into the cache.

        Accepts the envelope built by ``events.envelope`` (has ``type``,
        ``topic``, ``seq``, ``data``). Events on channels the cache does not
        serve are ignored.
        """
        channel = event_channel(str(event.get("type", "")))
        if channel is None:
            return
        topic = str(event.get("topic", ""))
        data = event.get("data", {})
        symbol = market_data_symbol(topic, data if isinstance(data, dict) else {})
        if symbol is None:
            return
        self._symbols_by_channel[channel].add(symbol)
        if channel == "trades":
            self._record_trade(symbol, event)
        else:
            # book / depth / auction(.indicative): keep only the latest, keyed
            # by topic so the two auction tenses coexist.
            self._snapshots[topic] = event

    def _record_trade(self, symbol: str, event: dict[str, Any]) -> None:
        if self._window_sec <= 0:
            return
        seq = int(event.get("seq", 0) or 0)
        buf = self._trades[symbol]
        buf.append(_BufferedTrade(seq=seq, created_mono=time.monotonic(), event=event))
        self._prune(symbol)

    def _prune(self, symbol: str) -> None:
        cutoff = time.monotonic() - self._window_sec
        buf = self._trades.get(symbol)
        if buf is None:
            return
        while buf and buf[0].created_mono < cutoff:
            buf.popleft()

    # ------------------------------------------------------------------
    # Serve
    # ------------------------------------------------------------------

    def snapshot(self, symbol: str, channel: str) -> list[dict[str, Any]]:
        """Current snapshot(s) for one ``(symbol, channel)`` pair.

        For ``trades`` this is the retained tail; for the snapshot channels it
        is the latest envelope(s). Returns ``[]`` when nothing is cached.
        """
        symbol = symbol.upper()
        if channel == "trades":
            self._prune(symbol)
            return [b.event for b in self._trades.get(symbol, deque())]
        out: list[dict[str, Any]] = []
        for topic in self._topics_for(symbol, channel):
            event = self._snapshots.get(topic)
            if event is not None:
                out.append(event)
        return out

    def snapshot_channel(self, channel: str) -> list[dict[str, Any]]:
        """Snapshots for every symbol the cache has seen on ``channel``.

        Backs a wildcard (``*``) subscribe: only symbols actually observed are
        expanded, so a cold cache produces an empty burst rather than a scan of
        every configured symbol.
        """
        out: list[dict[str, Any]] = []
        for symbol in sorted(self._symbols_by_channel.get(channel, set())):
            out.extend(self.snapshot(symbol, channel))
        return out

    def resume_trades(self, symbol: str, from_seq: int) -> list[dict[str, Any]]:
        """Replay ``trade`` envelopes with ``seq > from_seq``.

        Raises ``ReplayMiss`` when ``from_seq`` precedes the oldest retained
        print (the window has rolled past it), so the caller can fall back to a
        reset + fresh snapshot.
        """
        symbol = symbol.upper()
        self._prune(symbol)
        buf = self._trades.get(symbol)
        if not buf:
            return []
        oldest = buf[0].seq
        if from_seq < oldest - 1:
            raise ReplayMiss(
                f"from_seq={from_seq} precedes oldest retained seq={oldest}"
            )
        return [b.event for b in buf if b.seq > from_seq]

    def has_topic(self, topic: str) -> bool:
        """Whether a snapshot topic has ever been cached."""
        return topic in self._snapshots

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _topics_for(symbol: str, channel: str) -> tuple[str, ...]:
        if channel == "book":
            return (topic_book_snapshot(symbol),)
        if channel == "depth":
            return (topic_depth(symbol),)
        if channel == "auction":
            # Both tenses ride the one client channel.
            return (topic_auction_result(symbol), topic_auction_indicative(symbol))
        return ()
