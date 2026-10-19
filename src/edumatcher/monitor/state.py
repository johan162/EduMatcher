"""Per-process state ``pm-monitor`` keeps from the beacons it receives.

One :class:`ProcessState` per ``(process, instance, host)``: the latest beacon,
when *pm-monitor* received it, the ``boot_id`` that identifies the running
incarnation, and the last 60 RSS/CPU readings for the sparklines. See
docs-design/EduMatcher-Operator-Dashboard.md §9.1 and §10.

Ages are always measured on pm-monitor's own monotonic clock at receive time
(K6). A sender's clock is only trusted for ``started_at_ns`` (uptime, and
telling an older incarnation from a newer one on the same host).

Which beacon counts
-------------------
A process that beaconed while pm-monitor was down has up to ``SNDHWM`` (10)
beacons queued, delivered as one burst when the PULL binds. They are all real
samples, so each one feeds the sparkline, but only the beacon with the highest
``seq`` of the current ``boot_id`` is "the latest": an out-of-order or
repeated ``seq`` is ignored, and so is a beacon from an *older* incarnation
(lower ``started_at_ns``) that arrives after a newer one. Two live processes
claiming the same identity therefore show as one, with the stale counter
rising -- never as a process restarting every two seconds.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from edumatcher.models.generated.health import HealthBeacon

#: Readings kept per process for the sparklines (``Sparkline`` max_items).
SPARK_LEN = 60
#: Distinct sources tracked at most. A misconfigured client loop inventing
#: identities must not grow pm-monitor's memory without limit; beyond this a
#: new source is rejected and counted (``monitor.sources_rejected``).
MAX_SOURCES = 256
#: How long the RESTARTED badge stays on after a ``boot_id`` change (§10).
RESTART_BADGE_SEC = 600.0

#: Participant bots: clients of the exchange, shown in their own group and
#: never counted in the exchange status (design Q2).
BOT_PROCESSES = frozenset({"pm-mm-bot", "pm-ai-swarm"})

SourceKey = tuple[str, str | None, str]


class Ingest(enum.Enum):
    """What :meth:`ProcessTable.ingest` did with a beacon."""

    NEW = "new"  # first beacon of a source
    UPDATED = "updated"  # newer beacon of the running incarnation
    RESTARTED = "restarted"  # first beacon of a new incarnation
    STALE = "stale"  # out of order, repeated, or from an older incarnation
    REJECTED = "rejected"  # MAX_SOURCES reached


def process_key(process: str, instance: str | None, host: str) -> str:
    """``process/instance@host``, or ``process@host`` without an instance."""
    name = process if instance is None else f"{process}/{instance}"
    return f"{name}@{host}"


@dataclass
class ProcessState:
    """What pm-monitor knows about one source."""

    beacon: HealthBeacon
    received_at: float  # pm-monitor monotonic clock
    restarted_at: float | None = None  # monotonic; None until a boot_id change
    rss: deque[int] = field(default_factory=lambda: deque(maxlen=SPARK_LEN))
    cpu: deque[float] = field(default_factory=lambda: deque(maxlen=SPARK_LEN))

    def __post_init__(self) -> None:
        self._record(self.beacon)

    @property
    def boot_id(self) -> str:
        return self.beacon.boot_id

    @property
    def key(self) -> str:
        b = self.beacon
        return process_key(b.process, b.instance, b.host)

    @property
    def group(self) -> str:
        return "BOT" if self.beacon.process in BOT_PROCESSES else "EXCHANGE"

    def accept(self, beacon: HealthBeacon, now: float) -> Ingest:
        """Fold in a beacon of this source; see the module docstring."""
        current = self.beacon
        if beacon.boot_id == current.boot_id:
            if beacon.seq <= current.seq:
                return Ingest.STALE
            outcome = Ingest.UPDATED
        else:
            if beacon.started_at_ns < current.started_at_ns:
                return Ingest.STALE
            self.restarted_at = now
            self.rss.clear()
            self.cpu.clear()
            outcome = Ingest.RESTARTED
        self.beacon = beacon
        self.received_at = now
        self._record(beacon)
        return outcome

    def restarted_recently(self, now: float) -> bool:
        return (
            self.restarted_at is not None
            and now - self.restarted_at < RESTART_BADGE_SEC
        )

    def health(self, now: float, now_wall: float, state: str) -> dict[str, Any]:
        """This source as a ``ProcessHealth`` record (wire dict).

        ``state`` is decided by the caller: the health rules (§10) are B2's.
        ``loop_age_ms`` is the value the beacon carried, not aged further here.
        """
        b = self.beacon
        return {
            "key": self.key,
            "process": b.process,
            "instance": b.instance,
            "host": b.host,
            "group": self.group,
            "pid": b.pid,
            "state": state,
            "restarted_recently": self.restarted_recently(now),
            "uptime_sec": max(0.0, now_wall - b.started_at_ns / 1e9),
            "rss_bytes": b.rss_bytes,
            "cpu_pct": b.cpu_pct,
            "threads": b.threads,
            "fds": b.fds,
            "loop_age_ms": b.loop_age_ms,
            "loop_lag_ms": b.loop_lag_ms,
            "last_beacon_age_ms": max(0.0, (now - self.received_at) * 1000.0),
            "spark": {"rss": list(self.rss), "cpu": list(self.cpu)},
            "metrics": [m.to_dict() for m in b.metrics],
        }

    def _record(self, beacon: HealthBeacon) -> None:
        self.rss.append(beacon.rss_bytes)
        self.cpu.append(beacon.cpu_pct)


class ProcessTable:
    """Every source pm-monitor has heard from, bounded by ``max_sources``."""

    def __init__(self, max_sources: int = MAX_SOURCES) -> None:
        self.max_sources = max_sources
        self._states: dict[SourceKey, ProcessState] = {}

    def __len__(self) -> int:
        return len(self._states)

    def get(self, process: str, instance: str | None, host: str) -> ProcessState | None:
        return self._states.get((process, instance, host))

    def states(self) -> list[ProcessState]:
        """Every source, exchange processes first, then by name, instance, host."""
        return sorted(
            self._states.values(),
            key=lambda s: (
                s.group != "EXCHANGE",
                s.beacon.process,
                s.beacon.instance or "",
                s.beacon.host,
            ),
        )

    def ingest(self, beacon: HealthBeacon, now: float) -> Ingest:
        """Fold one received beacon in; ``now`` is pm-monitor's receive time."""
        source: SourceKey = (beacon.process, beacon.instance, beacon.host)
        state = self._states.get(source)
        if state is not None:
            return state.accept(beacon, now)
        if len(self._states) >= self.max_sources:
            return Ingest.REJECTED
        self._states[source] = ProcessState(beacon=beacon, received_at=now)
        return Ingest.NEW
