"""Tell the engine about a request a gateway refused itself (A3).

Authentication, role and rate-limit refusals are decided in the gateways and
never reach the engine, so the audit trail would not hold them.  A gateway
sends ``system.gateway_reject`` over its PUSH socket; the engine echoes it onto
the bus like any command.

A client can provoke these at the speed it can send, and each one costs the
engine a receive, so a reporter sends at most one record per peer host and code
per ``interval`` seconds and carries the number it folded in as ``count``.  The
host, not ``host:port``: a client that opens a new connection per request (any
plain HTTP client against the REST gateway) comes from a new source port each
time.  The record still names the full peer of the refusal that sent it.  The
count of the final burst is lost if the peer then goes quiet; the first record
of the burst, with its time, is not.  That is the only loss: a record the
engine could not take is retried, with everything folded since, at the next
refusal after ``interval``, and a full table sends what it folded before it
forgets it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Literal

from edumatcher.models.message import make_gateway_reject_msg

log = logging.getLogger(__name__)

#: The refusals a participant can dispute.  Anything else a gateway refuses
#: (malformed frames, field validation) is counted by the gateway, not sent.
REPORTED_CODES = frozenset(
    {"AUTH_REQUIRED", "AUTH_FAILED", "ROLE_DENIED", "RATE_LIMITED"}
)

_MAX_TRACKED = 4096


class RejectReporter:
    def __init__(
        self,
        source: Literal["ALF", "BALF", "REST"],
        send: Callable[[list[bytes]], None],
        *,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._send = send
        self._interval = interval
        self._clock = clock
        #: (peer host, code) -> (time of the last record tried, refusals folded
        #: in since, and the gateway id, peer and reason of the last of them)
        self._state: dict[tuple[str, str], tuple[float, int, str, str, str]] = {}

    @property
    def tracked(self) -> int:
        return len(self._state)

    def report(self, code: str, gateway_id: str, peer: str, reason: str) -> None:
        """Record one refusal; never raises."""
        if code not in REPORTED_CODES:
            return
        now = self._clock()
        key = (_host(peer), code)
        entry = self._state.get(key)
        folded = 0
        if entry is not None:
            last, folded = entry[0], entry[1]
            if now - last < self._interval:
                self._state[key] = (last, folded + 1, gateway_id, peer, reason)
                return
        elif len(self._state) >= _MAX_TRACKED:
            self._flush()
        if self._record(code, gateway_id, peer, reason, folded + 1):
            self._state[key] = (now, 0, gateway_id, peer, reason)
        else:
            # Not sent: keep the refusal for the next try, an interval on.
            self._state[key] = (now, folded + 1, gateway_id, peer, reason)

    def _flush(self) -> None:
        """Send every folded count, then forget every peer.  With the engine
        away the counts are lost, said once rather than once a peer."""
        lost = 0
        for (_host_key, code), (_, folded, gateway_id, peer, reason) in list(
            self._state.items()
        ):
            if folded and not self._record(
                code, gateway_id, peer, reason, folded, warn=False
            ):
                lost += folded
        self._state.clear()
        if lost:
            log.warning("cannot report %d folded refusals to the engine", lost)

    def _record(
        self,
        code: str,
        gateway_id: str,
        peer: str,
        reason: str,
        count: int,
        *,
        warn: bool = True,
    ) -> bool:
        """Send one record; whether it went."""
        try:
            self._send(
                make_gateway_reject_msg(
                    source=self._source,
                    gateway_id=gateway_id[:32],
                    peer=peer[:64],
                    reject_code=code,
                    reason=reason[:256],
                    count=count,
                    ts_ns=time.time_ns(),
                )
            )
        except Exception as exc:  # recording must never stop a gateway
            if warn:
                log.warning(
                    "cannot report %s from %s to the engine: %s", code, peer, exc
                )
            return False
        return True


def _host(peer: str) -> str:
    """The address of a ``host:port`` peer (the whole of one without a port)."""
    host, sep, _port = peer.rpartition(":")
    return host if sep else peer
