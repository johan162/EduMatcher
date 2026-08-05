"""Sequence tracking, gap detection and replay reconciliation for CALF.

This module is the part of a CALF client that is easy to get subtly wrong,
so it is kept free of sockets and testable on its own: feed it the
``(msg_type, CH, SYM, SEQ)`` of each inbound message and it says whether to
process that message, and whether a ``RESUME`` should go out.

Three rules drive everything here, all normative in
``docs/user-guide/920-app-calf-protocol.md`` §"Reconnect behavior":

1. **A replay is not disjoint from live traffic.** ``RESUME|LASTSEQ=n``
   returns *everything* the gateway still buffers past ``n``, and ``n`` is
   the client's position from before the gap -- so the reply re-sends the
   message that revealed the gap, plus anything delivered live while the
   request was in flight. Replayed and live lines share one ordered
   connection, so a duplicate always arrives after its original.
   :class:`StreamPosition.holes` is what separates the backfill actually
   wanted from a message already handled. Without it a client either
   processes every trade twice or discards the repair it just asked for.

2. **A ``SNAP`` re-baselines and is never a gap.** It re-anchors the stream
   wherever the gateway now is. Gap-checking one would ask to replay
   history it just superseded -- and since ``REPLAY_MISS`` is answered with
   a ``SNAP`` on the snapshot-backed channels, would loop ``RESUME``
   against a window already known to be too old.

3. **A sequence never moves backward within one connection.** Letting it
   turn the next ordinary message into a phantom gap, or hides a real one.
   Across connections it *can* move backward, and that means something
   different -- see :attr:`StreamPosition.generation`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# Channels whose current state a SNAP can express, and so the only ones a
# REPLAY_MISS is followed by a fresh baseline on. TRADE and AUCTION carry
# discrete events: there is no snapshot of a print that already happened,
# so a gap on those is permanent once it falls out of the replay window.
SNAPSHOT_CHANNELS = frozenset({"TOP", "STATE", "INDEX", "DEPTH", "CB"})

# Channels worth repairing with RESUME rather than leaving to the next SNAP.
# The snapshot-backed channels self-heal: the SUB that follows a reconnect
# triggers a fresh baseline, so replaying them would only re-send data that
# baseline is about to supersede. TRADE has no baseline and is the one
# channel read as a *record* rather than as current state, so a missed
# print is gone unless replayed. AUCTION shares that shape and is included
# for the same reason.
RESUMABLE_CHANNELS = frozenset({"TRADE", "AUCTION"})


@dataclass(frozen=True)
class Gap:
    """A hole in one stream that could not be closed.

    Emitted only when repair failed or was never possible -- a successful
    ``RESUME`` backfills the messages themselves and needs no marker.
    """

    channel: str
    symbol: str
    #: First and last sequence known to be missing, inclusive.
    first_seq: int
    last_seq: int
    #: ``TS`` of the message that revealed the hole, so a viewer can place
    #: it in time against the gateway's clock rather than the client's.
    ts: str

    @property
    def count(self) -> int:
        return self.last_seq - self.first_seq + 1


@dataclass
class StreamPosition:
    """Where one ``(channel, symbol)`` stream stands, and what it is owed."""

    #: Highest ``SEQ`` seen.
    seq: int
    #: Which connection :attr:`seq` was observed on.
    #:
    #: A sequence can only move backward two ways: a ``RESUME`` replaying
    #: history, or a gateway process restarting and beginning its counters
    #: again at 1 (they live in its memory, not in the connection). The
    #: first is only possible within the connection that asked -- so a
    #: backward step on a *later* connection is the second, and the new
    #: numbering must be adopted. Treating it as duplicates would black the
    #: stream out for as long as the new gateway lives.
    generation: int
    #: Sequence ranges a ``RESUME`` was sent for and which have not arrived
    #: yet, as inclusive ``(low, high)`` pairs.
    holes: list[tuple[int, int]] = field(default_factory=list)


class SequenceTracker:
    """Per-``(channel, symbol)`` sequence state for one client.

    Not thread-safe: drive it from the single thread that reads the socket.
    """

    def __init__(self) -> None:
        self._streams: dict[tuple[str, str], StreamPosition] = {}
        self._generation = 0

    def new_connection(self) -> None:
        """Note that a fresh connection was established.

        Positions are deliberately **kept** across a reconnect: the
        gateway's counters live in its process, not the socket, so the
        value from before a drop is exactly what reveals whether the drop
        cost anything. Clearing them would make every reconnect look
        gap-free by definition. Only the generation moves, which is what
        allows a restarted gateway's renumbering to be told apart from a
        replayed duplicate.
        """
        self._generation += 1

    def position(self, channel: str, symbol: str) -> int | None:
        """Highest sequence seen on a stream, or ``None`` if never seen."""
        entry = self._streams.get((channel, symbol))
        return None if entry is None else entry.seq

    def observe(
        self, msg_type: str, channel: str, symbol: str, seq: int
    ) -> tuple[bool, Gap | None]:
        """Account for one inbound message.

        Returns ``(process, gap)``:

        * ``process`` is ``False`` for a replayed duplicate the caller has
          already handled, and ``True`` for everything else -- including
          backfill that arrives below the current position.
        * ``gap`` is set when a hole was found. The caller should send a
          ``RESUME`` for it if :func:`is_resumable` says the channel
          supports one, and report it otherwise.

        ``seq <= 0`` means the field was absent or unparseable rather than
        a position, so the message passes through unsequenced: baselining
        at zero would make the next real sequence look like a gap and send
        a ``RESUME|LASTSEQ=0``, which the gateway rejects with
        ``BAD_MESSAGE`` rather than ``REPLAY_MISS`` -- leaving a hole
        nobody is told about.
        """
        if not channel or seq <= 0:
            return True, None

        key = (channel, symbol)
        entry = self._streams.get(key)

        if entry is None:
            # The first message on a stream establishes the baseline. It is
            # never a gap, because there is nothing yet for it to be a gap in.
            self._streams[key] = StreamPosition(seq=seq, generation=self._generation)
            return True, None

        if msg_type == "SNAP":  # rule 2
            entry.seq = seq
            entry.generation = self._generation
            entry.holes.clear()
            return True, None

        if seq <= entry.seq:
            if entry.generation != self._generation:
                # rule 3, across connections: a restarted gateway.
                log.info(
                    "stream (%s,%s) renumbered from %d to %d; adopting the "
                    "new sequence (gateway restart)",
                    channel,
                    symbol,
                    entry.seq,
                    seq,
                )
                entry.seq = seq
                entry.generation = self._generation
                entry.holes.clear()
                return True, None
            # rule 1: backfill inside a hole is wanted, anything else is a
            # duplicate. Either way the baseline stays put.
            return self._take_from_hole(entry, seq), None

        previous = entry.seq
        entry.seq = seq
        entry.generation = self._generation

        if seq == previous + 1:
            return True, None

        entry.holes.append((previous + 1, seq - 1))
        return True, Gap(
            channel=channel,
            symbol=symbol,
            first_seq=previous + 1,
            last_seq=seq - 1,
            ts="",
        )

    def abandon_holes(self, channel: str, symbol: str) -> None:
        """Give up on repairing this stream's outstanding holes.

        Called on ``ERR|CODE=REPLAY_MISS``: nothing is coming to fill them,
        and a range left open would mislabel a later redelivery as
        backfill.
        """
        entry = self._streams.get((channel, symbol))
        if entry is not None:
            entry.holes.clear()

    @staticmethod
    def _take_from_hole(entry: StreamPosition, seq: int) -> bool:
        """Whether ``seq`` is backfill that was asked for, marking it taken.

        Replay arrives in sequence order on one ordered connection, so
        everything below ``seq`` within the same hole has already been
        handed over and the range can simply advance past it.
        """
        for index, (low, high) in enumerate(entry.holes):
            if low <= seq <= high:
                if seq + 1 > high:
                    entry.holes.pop(index)
                else:
                    entry.holes[index] = (seq + 1, high)
                return True
        return False


def is_resumable(channel: str) -> bool:
    """Whether a gap on this channel is worth a ``RESUME``.

    False for the snapshot-backed channels, whose gaps close themselves.
    """
    return channel in RESUMABLE_CHANNELS


def has_snapshot(channel: str) -> bool:
    """Whether a ``REPLAY_MISS`` on this channel is followed by a ``SNAP``."""
    return channel in SNAPSHOT_CHANNELS
