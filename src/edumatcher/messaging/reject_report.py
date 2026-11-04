"""Tell the engine about a request a gateway refused itself (A3).

Authentication, role and rate-limit refusals are decided in the gateways and
never reach the engine, so the audit trail would not hold them.  A gateway
sends ``system.gateway_reject`` over its PUSH socket; the engine echoes it onto
the bus like any command.

A client can provoke these at the speed it can send, and each one costs the
engine a receive, so a reporter sends at most one record per peer and code per
``interval`` seconds and carries the number it folded in as ``count``.  The
count of the final burst is lost if the peer then goes quiet; the first record
of the burst, with its time, is not.
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
        #: (peer, code) -> (time of last record, refusals folded in since)
        self._state: dict[tuple[str, str], tuple[float, int]] = {}

    @property
    def tracked(self) -> int:
        return len(self._state)

    def report(self, code: str, gateway_id: str, peer: str, reason: str) -> None:
        """Record one refusal; never raises."""
        if code not in REPORTED_CODES:
            return
        now = self._clock()
        key = (peer, code)
        last, folded = self._state.get(key, (None, 0))
        if last is not None and now - last < self._interval:
            self._state[key] = (last, folded + 1)
            return
        if len(self._state) >= _MAX_TRACKED:
            self._state.clear()
        self._state[key] = (now, 0)
        try:
            self._send(
                make_gateway_reject_msg(
                    source=self._source,
                    gateway_id=gateway_id[:32],
                    peer=peer[:64],
                    reject_code=code,
                    reason=reason[:256],
                    count=folded + 1,
                    ts_ns=time.time_ns(),
                )
            )
        except Exception as exc:  # recording must never stop a gateway
            log.warning("cannot report %s from %s to the engine: %s", code, peer, exc)
