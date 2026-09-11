"""Causal envelope: who caused this message, and which chain it belongs to.

Every message the exchange publishes carries an envelope in a dedicated ZMQ
frame, beside the per-topic sequence that ``messaging.bus.SequencedPublisher``
already stamps. The envelope answers three questions the payload cannot:

``msg_id``
    What *is* this message? A ULID, unique across the deployment and sortable
    by generation time.
``causation_id``
    Which message caused it? The ``msg_id`` of the inbound request the engine
    was handling when it published this. ``None`` for a message with no
    external cause -- a scheduler tick, a circuit-breaker trip, anything the
    engine decided on its own.
``correlation_id``
    Which causal chain is it part of? Propagated unchanged from cause to
    effect, so "everything that flowed from this submission" is one indexed
    lookup rather than a graph traversal. A message with no cause starts a new
    chain with ``correlation_id == msg_id``.

Why a frame and not payload fields
----------------------------------
``SequencedPublisher`` set the precedent and gave the reason: envelope data
rides outside the JSON so the hot publish path never decodes and re-encodes a
message. The same argument applies here, with a second one behind it -- the
envelope is uniform across all 114 message types and any added later, so
expressing it per-message in ``spec/messages/*.yaml`` would be 114 copies of
one idea that the generator would then have to keep in step.

Wire format
-----------
One frame, ASCII, three fields separated by ``|``::

    01JR8Z7Q3K5N2X9V4B6C8D0E1F|01JR8Z7Q2A...|01JR8Z7Q1B...

An empty field means absent. Fixed-width and delimiter-separated rather than
JSON: parsing is a single ``split``, which matters on a path that runs for
every published message.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

# Crockford base32: no I, L, O or U, so a ULID cannot be misread aloud or
# mistyped into a different valid id.
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_ULID_LEN = 26
_SEP = "|"

_lock = threading.Lock()
_last_ms = -1
_last_rand = 0

# 80 bits of randomness, per the ULID spec.
_RAND_MAX = (1 << 80) - 1


def _encode_b32(value: int, length: int) -> str:
    out = [""] * length
    for i in range(length - 1, -1, -1):
        out[i] = _B32[value & 0x1F]
        value >>= 5
    return "".join(out)


def new_ulid() -> str:
    """A fresh ULID: 48-bit millisecond timestamp, then 80 random bits.

    Monotonic within a millisecond. Two ULIDs generated in the same
    millisecond would otherwise sort arbitrarily against each other, which
    would undermine the one property that makes a ULID more useful here than a
    UUID4 -- that lexicographic order is generation order. When the clock has
    not advanced, the random component is incremented instead of redrawn.
    """
    global _last_ms, _last_rand
    with _lock:
        ms = int(time.time() * 1000)
        if ms == _last_ms:
            # Same millisecond: step the randomness rather than redraw it.
            _last_rand = (_last_rand + 1) & _RAND_MAX
        elif ms < _last_ms:
            # Clock went backwards (NTP step). Keep issuing monotonic ids
            # rather than emitting one that sorts before its predecessor.
            _last_rand = (_last_rand + 1) & _RAND_MAX
            ms = _last_ms
        else:
            _last_ms = ms
            _last_rand = int.from_bytes(os.urandom(10), "big")
        rand = _last_rand
    return _encode_b32(ms, 10) + _encode_b32(rand, 16)


@dataclass(frozen=True, slots=True)
class Envelope:
    """Causal metadata for one published message."""

    msg_id: str
    causation_id: str | None = None
    correlation_id: str | None = None

    @classmethod
    def root(cls) -> "Envelope":
        """An envelope that starts a new causal chain.

        ``correlation_id`` is the message's own id, so every descendant can
        carry it unchanged and still name the message the chain began with.
        """
        mid = new_ulid()
        return cls(msg_id=mid, causation_id=None, correlation_id=mid)

    def caused(self) -> "Envelope":
        """An envelope for a message published *because of* this one.

        The child cites this message as its cause and inherits the chain.
        """
        return Envelope(
            msg_id=new_ulid(),
            causation_id=self.msg_id,
            correlation_id=self.correlation_id or self.msg_id,
        )

    def to_frame(self) -> bytes:
        return _SEP.join(
            (self.msg_id, self.causation_id or "", self.correlation_id or "")
        ).encode("ascii")

    @classmethod
    def from_frame(cls, frame: bytes) -> "Envelope | None":
        """Parse an envelope frame, or ``None`` if it is not one.

        Returns ``None`` rather than raising: this runs on every received
        message, and a malformed envelope must never stop a subscriber from
        reading a payload it could otherwise have processed.
        """
        try:
            parts = frame.decode("ascii").split(_SEP)
        except (UnicodeDecodeError, AttributeError):
            return None
        if len(parts) != 3 or len(parts[0]) != _ULID_LEN:
            return None
        return cls(
            msg_id=parts[0],
            causation_id=parts[1] or None,
            correlation_id=parts[2] or None,
        )
