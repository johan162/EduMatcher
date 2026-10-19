"""The ``pm-monitor`` collector loop: receive beacons, publish snapshots.

See docs-design/EduMatcher-Operator-Dashboard.md §9.1. One thread, one
``zmq.Poller`` with a 200 ms timeout -- the EduMatcher norm:

1. Drain the ``PULL`` (beacons from every process) into the
   :class:`~edumatcher.monitor.state.ProcessTable`.
2. Once a second, drain again (so a burst that has just arrived is judged by
   its newest beacon, never by a stale one), re-read the expected roster if
   the active ``emo`` profile changed, judge every process (§10), ``PUB`` a
   ``health.event`` for each state change and then the ``health.snapshot``.

Processes, their health and the exchange status are complete (WP-B1, B2).
The host, trading, participant, book, gateway and threshold blocks are zero
placeholders until B3 fills them; the wire shape is final already.

MISSING waits for one silence period after pm-monitor starts: every process
of a running exchange needs a beacon interval to be heard from, and judging
earlier would announce each of them MISSING and then back.
"""

from __future__ import annotations

import errno
import logging
import socket
import time
from collections.abc import Callable
from datetime import datetime, timezone, tzinfo
from typing import Any

import zmq

from edumatcher.config import resolve_gateway_bind_host
from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.messaging.bus import get_context
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.health import (
    TOPIC_HEALTH_BEACON,
    MetricSample,
    make_health_event,
    make_health_snapshot,
    parse_health_beacon,
)
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.roster import ExpectedRoster, Roster
from edumatcher.monitor.state import (
    HealthRules,
    Ingest,
    ProcessState,
    ProcessTable,
    exchange_status,
    missing_health,
    process_alive,
    process_key,
)
from edumatcher.stats.trading_day import timezone_name, trading_date

log = logging.getLogger(__name__)

#: Poll timeout of the main loop (design §9.1).
POLL_MS = 200
#: Snapshot period (design §9.1: 1 Hz).
SNAPSHOT_INTERVAL_SEC = 1.0
#: Beacons read per drain at most, so a flood cannot starve the snapshot.
#: Comfortably above MAX_SOURCES x SNDHWM (256 x 10), a full start-up burst.
DRAIN_BUDGET = 4096
#: At most one warning per this many seconds per kind of problem.
WARN_EVERY_SEC = 60.0
#: A source the roster does not expect is forgotten after this long without a
#: beacon, so a process stopped or killed by hand does not stay listed (and
#: hold one of MAX_SOURCES) for the life of pm-monitor.
FORGET_AFTER_SEC = 3600.0
#: How a state change is coloured in the event log.
STATE_SEVERITY = {
    "HEALTHY": "INFO",
    "STOPPED": "INFO",
    "DEGRADED": "WARN",
    "HUNG": "CRIT",
    "SILENT": "CRIT",
    "DEAD": "CRIT",
    "MISSING": "CRIT",
}


def iso_utc(epoch_sec: float) -> str:
    """ISO-8601 UTC with milliseconds and a ``Z``, as every health timestamp."""
    return (
        datetime.fromtimestamp(epoch_sec, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _zero_rates() -> dict[str, Any]:
    return {
        "today": 0,
        "per_sec_now": 0.0,
        "avg_per_min": 0.0,
        "avg_per_hour": 0.0,
        "avg_per_day": None,
    }


def _placeholder_host() -> dict[str, Any]:
    """HostStats until B3's host sampler."""
    return {
        "cpu_pct": 0.0,
        "cpu_per_core": [],
        "load1": 0.0,
        "load5": 0.0,
        "load15": 0.0,
        "mem_total_bytes": 0,
        "mem_used_bytes": 0,
        "mem_available_bytes": 0,
        "swap_used_bytes": 0,
        "disk_free_bytes": 0,
        "disk_total_bytes": 0,
        "files": [],
    }


def _placeholder_trading() -> dict[str, Any]:
    """TradingStats until B3's rates."""
    return {
        "orders": _zero_rates(),
        "trades": _zero_rates(),
        "traded_value_today": 0.0,
        "reject_pct_5m": 0.0,
        "handle_p50_us": 0.0,
        "handle_p99_us": 0.0,
        "busy_pct": 0.0,
    }


class Monitor:
    """Binds pm-monitor's two sockets and runs the collector loop."""

    def __init__(
        self,
        config: MonitorConfig,
        session_tz: tzinfo,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        roster: ExpectedRoster | None = None,
        local_host: str | None = None,
        alive: Callable[[int, int], bool] = process_alive,
    ) -> None:
        self.config = config
        self.session_tz = session_tz
        self._clock = clock
        self._wall_clock = wall_clock
        self.roster: ExpectedRoster = Roster() if roster is None else roster
        self.rules = HealthRules.from_config(
            config, (local_host or socket.gethostname() or "unknown")[:128]
        )
        self._alive = alive
        self._started_at = clock()
        #: The state each process key was last published with.
        self._last_states: dict[str, str] = {}

        # MonitorConfig.bind_address is the authored value (I12): this is the
        # one place EDUMATCHER_GATEWAY_BIND_HOST applies to pm-monitor.
        bind_host = resolve_gateway_bind_host(config.bind_address)
        self.pull_endpoint = f"tcp://{bind_host}:{config.pull_port}"
        self.pub_endpoint = f"tcp://{bind_host}:{config.pub_port}"

        ctx = get_context()
        self._pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
        self._pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
        for sock in (self._pull, self._pub):
            sock.setsockopt(zmq.LINGER, 0)
        try:
            self._pull.bind(self.pull_endpoint)
            self._pub.bind(self.pub_endpoint)
        except zmq.ZMQError:
            self._pull.close()
            self._pub.close()
            raise

        self.table = ProcessTable()
        self._running = True
        self._reporter: HealthReporter | None = None
        self._snapshot_seq = 0
        #: Per pm-monitor start until WP-B4 makes it metrics.db's events.seq.
        self._event_seq = 0
        self._last_warning: dict[str, float] = {}

        # Counters for pm-monitor's own beacon.
        self.beacons_in = 0
        self.beacons_invalid = 0
        self.beacons_stale = 0
        self.sources_rejected = 0
        self.restarts_seen = 0
        self.snapshots_out = 0
        self.snapshot_errors = 0
        self.snapshot_bytes = 0
        self.snapshot_build_ms = 0.0
        self.events_out = 0
        self.sources_forgotten = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def attach_reporter(self, reporter: HealthReporter) -> None:
        """Ship pm-monitor's own beacon through ``reporter`` (``main()``).

        It sends to this process's own PULL, so pm-monitor lists itself and is
        judged by the same rules as everyone else."""
        self._reporter = reporter

    def run(self) -> None:
        log.info(
            "pm-monitor collecting beacons on %s, publishing on %s",
            self.pull_endpoint,
            self.pub_endpoint,
        )
        poller = zmq.Poller()
        poller.register(self._pull, zmq.POLLIN)
        reporter = self._reporter
        next_snapshot = self._clock()
        while self._running:
            if reporter is not None:
                reporter.tick_and_publish(self.metric_samples)
            wait_ms = (next_snapshot - self._clock()) * 1000.0
            try:
                events = dict(poller.poll(timeout=max(0, min(POLL_MS, int(wait_ms)))))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                continue  # a signal; stop() has cleared _running
            if self._pull in events:
                self.drain()
            now = self._clock()
            if now >= next_snapshot:
                self.drain()
                self.publish_snapshot()
                # Fixed cadence; after a stall resume from now, never burst.
                next_snapshot += SNAPSHOT_INTERVAL_SEC
                if next_snapshot <= now:
                    next_snapshot = now + SNAPSHOT_INTERVAL_SEC

    def stop(self) -> None:
        """Ask the loop to exit; ``run()`` returns within one poll timeout."""
        log.info("stop requested")
        self._running = False

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
            self._reporter = None
        self._pull.close()
        self._pub.close()

    # ------------------------------------------------------------------
    # beacons in
    # ------------------------------------------------------------------

    def drain(self) -> int:
        """Read every queued beacon (up to ``DRAIN_BUDGET``); return the count."""
        n = 0
        while n < DRAIN_BUDGET:
            try:
                frames = self._pull.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
            n += 1
            self.receive(frames, self._clock())
        return n

    def receive(self, frames: list[bytes], now: float) -> Ingest | None:
        """Validate and fold in one beacon; ``None`` when it was invalid."""
        self.beacons_in += 1
        try:
            if frames[0] != TOPIC_HEALTH_BEACON.encode():
                raise ValueError(f"unexpected topic {frames[0][:64]!r}")
            beacon = parse_health_beacon(frames)
        except Exception as exc:  # anything a peer sends must not stop us
            self.beacons_invalid += 1
            self._warn("invalid", "invalid health beacon dropped: %s", exc)
            return None
        outcome = self.table.ingest(beacon, now)
        if outcome is Ingest.STALE:
            self.beacons_stale += 1
        elif outcome is Ingest.REJECTED:
            self.sources_rejected += 1
            self._warn(
                "rejected",
                "tracking %d sources already; beacon from %s/%s@%s rejected",
                self.table.max_sources,
                beacon.process,
                beacon.instance,
                beacon.host,
            )
        elif outcome is Ingest.RESTARTED:
            self.restarts_seen += 1
            log.info(
                "%s restarted (pid %d, boot %s)",
                (
                    beacon.process
                    if beacon.instance is None
                    else f"{beacon.process}/{beacon.instance}"
                ),
                beacon.pid,
                beacon.boot_id,
            )
        return outcome

    # ------------------------------------------------------------------
    # snapshot out
    # ------------------------------------------------------------------

    def processes(self, now: float) -> list[dict[str, Any]]:
        """Every process as a judged ``ProcessHealth`` record.

        Re-reads the roster when its files changed and forgets long-silent
        sources nobody expects. Sources first (exchange, then bots), then the
        expected processes never heard from.
        """
        self.roster.refresh()
        expected = self.roster.expected

        def keep(state: ProcessState) -> bool:
            if expected is not None and state.identity in expected:
                return True
            return now - state.received_at <= FORGET_AFTER_SEC

        self.sources_forgotten += len(self.table.forget(keep))

        now_wall = self._wall_clock()
        states = self.table.states()
        records = [
            state.health(
                now, now_wall, state.evaluate(now, self.rules, alive=self._alive)
            )
            for state in states
        ]
        if expected is not None and self._missing_is_judged(now):
            heard = {state.identity for state in states}
            records.extend(
                missing_health(process, instance)
                for process, instance in sorted(
                    expected, key=lambda e: (e[0], e[1] or "")
                )
                if (process, instance) not in heard
            )
        return records

    def _missing_is_judged(self, now: float) -> bool:
        cfg = self.config
        return (
            now - self._started_at > cfg.silent_after_beacons * cfg.beacon_interval_sec
        )

    def snapshot(self) -> dict[str, Any]:
        """The ``health.snapshot`` payload for now (unvalidated dict).

        Publishes a ``PROCESS_STATUS`` event for every state that changed
        since the previous snapshot.
        """
        now = self._clock()
        processes = self.processes(now)
        self._publish_transitions(processes)
        now_wall = self._wall_clock()
        return {
            "ts": iso_utc(now_wall),
            "seq": self._snapshot_seq,
            "exchange": {
                "status": exchange_status(processes, self.roster.expected),
                "session_state": "",
                "trading_date": trading_date(now_wall, self.session_tz),
                "session_timezone": timezone_name(self.session_tz),
            },
            "host": _placeholder_host(),
            "processes": processes,
            "trading": _placeholder_trading(),
            "participants": [],
            "books": [],
            "gateways": [],
            "thresholds": [],
        }

    # ------------------------------------------------------------------
    # events out
    # ------------------------------------------------------------------

    def _publish_transitions(self, processes: list[dict[str, Any]]) -> None:
        """A ``PROCESS_STATUS`` event per changed state.

        A process first heard from HEALTHY is not news; any other first state
        is. A MISSING process that starts beacons gets a new key (it now has a
        host), so its previous state is looked up under the hostless key.
        """
        last = self._last_states
        current: dict[str, str] = {}
        for record in processes:
            key, state = record["key"], record["state"]
            current[key] = state
            previous = last.get(key)
            if previous is None and record["host"]:
                previous = last.get(
                    process_key(record["process"], record["instance"], "")
                )
            if previous == state or (previous is None and state == "HEALTHY"):
                continue
            detail = (
                f"first seen {state}" if previous is None else f"{previous} -> {state}"
            )
            severity = STATE_SEVERITY[state]
            log.log(
                logging.INFO if severity == "INFO" else logging.WARNING,
                "%s: %s",
                key,
                detail,
            )
            self.publish_event("PROCESS_STATUS", severity, key, detail)
        self._last_states = current

    def publish_event(
        self, kind: str, severity: str, subject: str, detail: str
    ) -> bool:
        """Validate and publish one ``health.event``; False when it failed."""
        try:
            frames = make_health_event(
                seq=self._event_seq,
                ts=iso_utc(self._wall_clock()),
                kind=kind,
                severity=severity,
                subject=subject[:200],
                detail=detail[:512],
            )
        except MessageValidationError as exc:
            self._warn("event", "health event invalid, not published: %s", exc)
            return False
        self._pub.send_multipart(frames)
        self._event_seq += 1
        self.events_out += 1
        return True

    def publish_snapshot(self) -> bool:
        """Build, validate and publish one snapshot; False when it failed."""
        started = time.perf_counter()
        try:
            frames = make_health_snapshot(**self.snapshot())
        except MessageValidationError as exc:
            self.snapshot_errors += 1
            self._warn("snapshot", "health snapshot invalid, not published: %s", exc)
            return False
        self.snapshot_build_ms = (time.perf_counter() - started) * 1000.0
        self.snapshot_bytes = len(frames[1])
        self._pub.send_multipart(frames)  # PUB never blocks; drops at its HWM
        self._snapshot_seq += 1
        self.snapshots_out += 1
        return True

    # ------------------------------------------------------------------
    # own beacon
    # ------------------------------------------------------------------

    def metric_samples(self) -> list[MetricSample]:
        """pm-monitor's application metrics, for its own beacon."""
        return [
            counter("monitor.beacons_in", self.beacons_in),
            counter("monitor.beacons_invalid", self.beacons_invalid),
            counter("monitor.beacons_stale", self.beacons_stale),
            counter("monitor.sources_rejected", self.sources_rejected),
            counter("monitor.restarts_seen", self.restarts_seen),
            gauge("monitor.sources", len(self.table)),
            counter("monitor.snapshots_out", self.snapshots_out),
            counter("monitor.snapshot_errors", self.snapshot_errors),
            counter("monitor.events_out", self.events_out),
            counter("monitor.sources_forgotten", self.sources_forgotten),
            gauge("monitor.snapshot_bytes", self.snapshot_bytes),
            gauge("monitor.snapshot_build_ms", self.snapshot_build_ms),
        ]

    def _warn(self, kind: str, msg: str, *args: object) -> None:
        now = self._clock()
        if now - self._last_warning.get(kind, float("-inf")) >= WARN_EVERY_SEC:
            self._last_warning[kind] = now
            log.warning(msg, *args)
