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

Health rules (§10)
------------------
:meth:`ProcessState.evaluate` applies the rules in order, first match wins:
STOPPED (final beacon), DEAD / SILENT (no beacon for ``silent_after_beacons``
x the *sender's* interval, told apart by whether the PID still runs),
HUNG (``loop_age_ms`` over ``hung_after_sec``, or over the start-up grace
while the beacon says ``starting``), DEGRADED (a threshold breach or
``loop_lag_ms`` over 1 s), else HEALTHY. MISSING has no source by
definition; :func:`missing_health` builds that record.

HUNG judges ``loop_age_ms`` as the beacon carried it, not aged further by the
time since it arrived: a beacon arrives every interval while the sampler
thread runs, so the figure is never more than one interval old, and adding
that interval would turn the scheduler's ~4 s engine round-trip (I40) into a
HUNG at the 5 s default.

A process that stood still as a whole -- SIGSTOP, a suspended host -- sends
no beacon and is reported SILENT. When it runs again, its first beacons carry
a loop age (and then a worst gap) that includes the time it stood still,
which would read as HUNG and then DEGRADED although the loop never stalled
while the process ran (found end to end, I108). That silence was already
reported, so it is credited: ``loop_age_ms`` loses it until the loop has
ticked again, and the beacon whose worst gap spans it loses it from
``loop_lag_ms``. The whole silence is credited -- the process stood still
for most of it and ran for at most one interval -- so a loop that was hung
before the stillness is seen HUNG at most one interval later than without
it. Whether the loop has ticked since is not read from the credit but from
the resume: a loop age shorter than the time since the first beacon after
the silence, plus one interval, means a tick after it (the stillness itself
lasted longer than that interval). Only a silence past the SILENT limit is
credited, so no time is hidden that was not shown as SILENT.

Exchange status
---------------
:func:`exchange_status` -- see the rule in ``spec/messages/health.yaml``
(``ExchangeStatus.status``). Participant bots never count.
"""

from __future__ import annotations

import enum
from collections import deque
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field
from typing import Any

import psutil

from edumatcher.models.generated.health import HealthBeacon
from edumatcher.monitor.config import DEFAULT_SILENT_AFTER_BEACONS, MonitorConfig

#: Readings kept per process for the sparklines (``Sparkline`` max_items).
SPARK_LEN = 60
#: Distinct sources tracked at most. A misconfigured client loop inventing
#: identities must not grow pm-monitor's memory without limit; beyond this a
#: new source is rejected and counted (``monitor.sources_rejected``).
MAX_SOURCES = 256
#: How long the RESTARTED badge stays on after a ``boot_id`` change (§10).
RESTART_BADGE_SEC = 600.0
#: RSS history for the growth-over-one-hour threshold (§9.6): one reading per
#: minute, a little over an hour of them.
RSS_HISTORY_EVERY_SEC = 60.0
RSS_GROWTH_WINDOW_SEC = 3600.0
#: RSS history starts this long after pm-monitor first heard from an
#: incarnation (and never while it is ``starting``): a process loading its
#: configuration, books or caches grows by design, and judging that against a
#: just-started baseline would read every start-up as a leak (review R4).
RSS_WARMUP_SEC = 600.0

#: Participant bots: clients of the exchange, shown in their own group and
#: never counted in the exchange status (design Q2).
BOT_PROCESSES = frozenset({"pm-mm-bot", "pm-ai-swarm"})

#: While a beacon says ``starting``, HUNG waits this long instead of
#: ``hung_after_sec``: start-up work (engine GTC restore, clearing prune) is
#: not a hung loop, but a process stuck starting must still surface (I45).
STARTUP_GRACE_SEC = 120.0
#: DEGRADED when the worst gap between two loop iterations exceeds this. Every
#: loop's designed wait is well below it (I36).
LOOP_LAG_DEGRADED_MS = 1000.0
#: How far a same-host process's start time may differ from the beacon's
#: ``started_at_ns`` and still be the same process (PID reuse check).
START_TIME_TOLERANCE_SEC = 1.0

#: States in which a process is not doing its job.
DOWN_STATES = frozenset({"DEAD", "SILENT", "HUNG", "MISSING"})

SourceKey = tuple[str, str | None, str]
#: ``(process, instance)``: an identity without its host, as the roster has it.
Identity = tuple[str, str | None]


def group_of(process: str) -> str:
    return "BOT" if process in BOT_PROCESSES else "EXCHANGE"


@dataclass(frozen=True)
class HealthRules:
    """The §10 parameters, from the ``monitor`` section."""

    hung_after_sec: float
    silent_after_beacons: int
    #: pm-monitor's own ``socket.gethostname()``: a beacon from this host can
    #: be checked against the process table, one from elsewhere cannot.
    local_host: str
    startup_grace_sec: float = STARTUP_GRACE_SEC

    @classmethod
    def from_config(cls, config: MonitorConfig, local_host: str) -> HealthRules:
        return cls(
            hung_after_sec=config.hung_after_sec,
            silent_after_beacons=config.silent_after_beacons,
            local_host=local_host,
        )


def process_alive(pid: int, started_at_ns: int) -> bool:
    """Whether the process that sent a beacon still runs on this host.

    A PID alone is not enough: after a crash the number can be reused by an
    unrelated process, which would turn DEAD into SILENT. The start time must
    match the beacon's ``started_at_ns`` (read from the same kernel clock).
    An exited process its parent has not reaped yet (a zombie) still holds
    its PID but runs nothing, so it is dead too.
    """
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            created = proc.create_time()
            zombie = proc.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:  # AccessDenied and the like: it exists
        return True
    return not zombie and abs(created - started_at_ns / 1e9) <= START_TIME_TOLERANCE_SEC


class Ingest(enum.Enum):
    """What :meth:`ProcessTable.ingest` did with a beacon."""

    NEW = "new"  # first beacon of a source
    UPDATED = "updated"  # newer beacon of the running incarnation
    RESTARTED = "restarted"  # first beacon of a new incarnation
    STALE = "stale"  # out of order, repeated, or from an older incarnation
    REJECTED = "rejected"  # MAX_SOURCES reached


def process_key(process: str, instance: str | None, host: str) -> str:
    """``process/instance@host``, or ``process@host`` without an instance.

    A MISSING process has no host, and its key no ``@``.
    """
    name = process if instance is None else f"{process}/{instance}"
    return f"{name}@{host}" if host else name


def missing_health(process: str, instance: str | None) -> dict[str, Any]:
    """The ``ProcessHealth`` record of an expected process never heard from."""
    return {
        "key": process_key(process, instance, ""),
        "process": process,
        "instance": instance,
        "host": "",
        "group": group_of(process),
        "pid": 0,
        "state": "MISSING",
        "restarted_recently": False,
        "starting": False,
        "uptime_sec": 0.0,
        "rss_bytes": 0,
        "cpu_pct": 0.0,
        "threads": 0,
        "fds": None,
        "loop_age_ms": 0.0,
        "loop_lag_ms": 0.0,
        "last_beacon_age_ms": 0.0,
        "spark": {"rss": [], "cpu": []},
        "metrics": [],
    }


def exchange_status(
    processes: Iterable[dict[str, Any]],
    expected: Collection[Identity] | None,
    *,
    degraded: bool = False,
) -> str:
    """OPERATIONAL / DEGRADED / IMPAIRED / DOWN from ``ProcessHealth`` records.

    ``expected`` is the roster (``None`` without an active profile). With a
    roster, only its processes can impair the exchange, and a STOPPED one
    does; without one, every exchange process that beacons counts, and a
    STOPPED one was stopped on purpose. ``degraded`` is a threshold breach
    that belongs to no process (the host, the reject ratio, a book).
    """
    exchange = [p for p in processes if p["group"] == "EXCHANGE"]
    engines = [p for p in exchange if p["process"] == "pm-engine"]
    if not any(p["state"] not in DOWN_STATES | {"STOPPED"} for p in engines):
        return "DOWN"
    for p in exchange:
        if p["process"] == "pm-engine":
            continue
        if expected is None:
            if p["state"] in DOWN_STATES:
                return "IMPAIRED"
        elif (p["process"], p["instance"]) in expected and (
            p["state"] in DOWN_STATES or p["state"] == "STOPPED"
        ):
            return "IMPAIRED"
    if degraded or any(p["state"] == "DEGRADED" for p in exchange):
        return "DEGRADED"
    return "OPERATIONAL"


@dataclass
class ProcessState:
    """What pm-monitor knows about one source."""

    beacon: HealthBeacon
    received_at: float  # pm-monitor monotonic clock
    restarted_at: float | None = None  # monotonic; None until a boot_id change
    #: When pm-monitor first heard from the current incarnation (monotonic).
    boot_seen_at: float = -1.0
    rss: deque[int] = field(default_factory=lambda: deque(maxlen=SPARK_LEN))
    cpu: deque[float] = field(default_factory=lambda: deque(maxlen=SPARK_LEN))
    #: Silence credited to the loop figures; see the module docstring.
    age_credit_sec: float = 0.0
    lag_credit_sec: float = 0.0
    #: Receive time of the first beacon after the last credited silence.
    resumed_at: float = 0.0
    #: ``(receive time, rss)`` once a minute, for the RSS growth rule.
    rss_history: deque[tuple[float, int]] = field(
        default_factory=lambda: deque(
            maxlen=int(RSS_GROWTH_WINDOW_SEC / RSS_HISTORY_EVERY_SEC) + 2
        )
    )

    def __post_init__(self) -> None:
        if self.boot_seen_at < 0:
            self.boot_seen_at = self.received_at
        self._record(self.beacon, self.received_at)

    @property
    def boot_id(self) -> str:
        return self.beacon.boot_id

    @property
    def key(self) -> str:
        b = self.beacon
        return process_key(b.process, b.instance, b.host)

    @property
    def group(self) -> str:
        return group_of(self.beacon.process)

    @property
    def identity(self) -> Identity:
        return self.beacon.process, self.beacon.instance

    @property
    def loop_age_ms(self) -> float:
        """The beacon's loop age less any credited silence."""
        return max(0.0, self.beacon.loop_age_ms - self.age_credit_sec * 1000.0)

    @property
    def loop_lag_ms(self) -> float:
        """The beacon's worst gap less any credited silence."""
        return max(0.0, self.beacon.loop_lag_ms - self.lag_credit_sec * 1000.0)

    def evaluate(
        self,
        now: float,
        rules: HealthRules,
        *,
        breached: bool = False,
        alive: Callable[[int, int], bool] = process_alive,
    ) -> str:
        """This source's §10 state; ``now`` is pm-monitor's monotonic clock.

        ``breached`` is whether a threshold on this process is in breach (B3).
        """
        b = self.beacon
        if b.final:
            return "STOPPED"
        silence = now - self.received_at
        limit = rules.silent_after_beacons * b.interval_sec
        if silence > limit:
            if b.host == rules.local_host:
                return "SILENT" if alive(b.pid, b.started_at_ns) else "DEAD"
            # Another host: no process table to ask, so time decides.
            return "DEAD" if silence > 2 * limit else "SILENT"
        hung_after = rules.startup_grace_sec if b.starting else rules.hung_after_sec
        if self.loop_age_ms > hung_after * 1000.0:
            return "HUNG"
        if breached or self.loop_lag_ms > LOOP_LAG_DEGRADED_MS:
            return "DEGRADED"
        return "HEALTHY"

    def accept(
        self,
        beacon: HealthBeacon,
        now: float,
        silent_after_beacons: int = DEFAULT_SILENT_AFTER_BEACONS,
    ) -> Ingest:
        """Fold in a beacon of this source; see the module docstring."""
        current = self.beacon
        credit = 0.0
        if beacon.boot_id == current.boot_id:
            if beacon.seq <= current.seq:
                return Ingest.STALE
            outcome = Ingest.UPDATED
            credit = self.age_credit_sec
            silence = now - self.received_at
            if silence > silent_after_beacons * current.interval_sec:
                # It stood still for (nearly all of) the silence, and its
                # loop with it.
                credit += silence
                self.resumed_at = now
        else:
            if beacon.started_at_ns < current.started_at_ns:
                return Ingest.STALE
            self.restarted_at = now
            self.boot_seen_at = now
            self.rss.clear()
            self.cpu.clear()
            self.rss_history.clear()
            outcome = Ingest.RESTARTED
        self.lag_credit_sec = 0.0
        since_resume = now - self.resumed_at + beacon.interval_sec
        if credit and beacon.loop_age_ms < since_resume * 1000.0:
            # The loop has ticked since: its age is its own again, and this
            # beacon's worst gap is the one that spans the stillness.
            self.lag_credit_sec = credit
            credit = 0.0
        self.age_credit_sec = credit
        self.beacon = beacon
        self.received_at = now
        self._record(beacon, now)
        return outcome

    def is_live(self, now: float, rules: HealthRules) -> bool:
        """Beacons still arrive and the process has not stopped: its figures
        are current, so thresholds may judge them."""
        b = self.beacon
        return (
            not b.final
            and now - self.received_at <= rules.silent_after_beacons * b.interval_sec
        )

    def rss_growth_pct(self, now: float) -> float | None:
        """RSS growth over the last hour in percent; ``None`` before an hour
        of history (or after a restart, which clears it)."""
        base: int | None = None
        for t, rss in self.rss_history:
            if t > now - RSS_GROWTH_WINDOW_SEC:
                break
            base = rss
        if not base:
            return None
        return 100.0 * (self.beacon.rss_bytes - base) / base

    def restarted_recently(self, now: float) -> bool:
        return (
            self.restarted_at is not None
            and now - self.restarted_at < RESTART_BADGE_SEC
        )

    def health(self, now: float, now_wall: float, state: str) -> dict[str, Any]:
        """This source as a ``ProcessHealth`` record (wire dict).

        ``state`` comes from :meth:`evaluate`. ``loop_age_ms`` is the value the
        beacon carried, less any credited silence (see the module docstring).
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
            "starting": b.starting,
            "uptime_sec": max(0.0, now_wall - b.started_at_ns / 1e9),
            "rss_bytes": b.rss_bytes,
            "cpu_pct": b.cpu_pct,
            "threads": b.threads,
            "fds": b.fds,
            "loop_age_ms": self.loop_age_ms,
            "loop_lag_ms": self.loop_lag_ms,
            "last_beacon_age_ms": max(0.0, (now - self.received_at) * 1000.0),
            "spark": {"rss": list(self.rss), "cpu": list(self.cpu)},
            "metrics": [m.to_dict() for m in b.metrics],
        }

    def _record(self, beacon: HealthBeacon, now: float) -> None:
        self.rss.append(beacon.rss_bytes)
        self.cpu.append(beacon.cpu_pct)
        if beacon.starting or now - self.boot_seen_at < RSS_WARMUP_SEC:
            return
        history = self.rss_history
        if not history or now - history[-1][0] >= RSS_HISTORY_EVERY_SEC:
            history.append((now, beacon.rss_bytes))


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

    def forget(self, keep: Callable[[ProcessState], bool]) -> list[ProcessState]:
        """Drop every source ``keep`` rejects; return the dropped ones."""
        dropped = [s for s in self._states.values() if not keep(s)]
        for state in dropped:
            b = state.beacon
            del self._states[(b.process, b.instance, b.host)]
        return dropped

    def ingest(
        self,
        beacon: HealthBeacon,
        now: float,
        silent_after_beacons: int = DEFAULT_SILENT_AFTER_BEACONS,
    ) -> Ingest:
        """Fold one received beacon in; ``now`` is pm-monitor's receive time."""
        source: SourceKey = (beacon.process, beacon.instance, beacon.host)
        state = self._states.get(source)
        if state is not None:
            return state.accept(beacon, now, silent_after_beacons)
        if len(self._states) >= self.max_sources:
            return Ingest.REJECTED
        self._states[source] = ProcessState(beacon=beacon, received_at=now)
        return Ingest.NEW
