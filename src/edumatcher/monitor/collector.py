"""The ``pm-monitor`` collector loop: receive beacons, publish snapshots.

See docs-design/EduMatcher-Operator-Dashboard.md §9.1. One thread, one
``zmq.Poller`` with a 200 ms timeout -- the EduMatcher norm:

1. Drain the ``PULL`` (beacons from every process) into the
   :class:`~edumatcher.monitor.state.ProcessTable`, and each accepted beacon's
   metrics into :class:`~edumatcher.monitor.activity.Activity` (rates, §9.4).
2. Drain the ``SUB`` on the engine bus (a few lifecycle topics, §9.2) into
   ``health.event``.
3. Once a second, drain the ``PULL`` again (so a burst that has just arrived
   is judged by its newest beacon, never by a stale one), re-read the
   expected roster if the active ``emo`` profile changed, sample the host
   (§8.1), evaluate the thresholds (§9.6), judge every process (§10),
   ``PUB`` a ``health.event`` for each change and then the
   ``health.snapshot``.

Thresholds are evaluated before the processes are judged, because a breach
on a process makes it DEGRADED. A breach that belongs to no process (the
host, the exchange reject ratio, a book) makes the exchange DEGRADED.

MISSING waits for one silence period after pm-monitor starts: every process
of a running exchange needs a beacon interval to be heard from, and judging
earlier would announce each of them MISSING and then back.
"""

from __future__ import annotations

import errno
import logging
import socket
import sqlite3
import time
from collections.abc import Callable
from datetime import tzinfo
from typing import Any

import zmq

from edumatcher.config import resolve_gateway_bind_host
from edumatcher.health import HealthReporter, counter, gauge
from edumatcher.messaging.bus import get_context, make_subscriber
from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated.health import (
    TOPIC_HEALTH_BEACON,
    MetricSample,
    make_health_event,
    make_health_snapshot,
    parse_health_beacon,
)
from edumatcher.monitor.activity import Activity
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.events import SUBSCRIPTIONS, translate
from edumatcher.monitor.host import (
    HostSampler,
    HostSource,
    disk_free_pct,
    mem_used_pct,
)
from edumatcher.monitor.roster import ExpectedRoster, Roster
from edumatcher.monitor.store import MetricsStore
from edumatcher.monitor.thresholds import (
    LOOP_AGE_RULE,
    LOOP_AGE_WARN_MS,
    MIN_HEAP_ENTRIES,
    MIN_REQUESTS_5M,
    Change,
    Reading,
    ThresholdBook,
    band_reading,
    increase_reading,
)
from edumatcher.monitor.timefmt import iso_utc
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
from edumatcher.stats.trading_day import timezone_name

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
#: Engine bus messages read per drain at most.
ENGINE_DRAIN_BUDGET = 1024
#: The engine bus carries a few events a second at most on our topics; a
#: modest buffer rides out a burst of connects at the open.
ENGINE_SUB_RCVHWM = 10_000
#: The log level of a threshold change, by its new level.
THRESHOLD_LOG_LEVEL = {
    "OK": logging.INFO,
    "WARN": logging.WARNING,
    "CRIT": logging.ERROR,
}
#: How often the dashboard's daily averages are re-read from metrics.db.
AVERAGES_EVERY_SEC = 60.0
#: Process vitals stored as series (``proc.<field>``) next to the metrics.
VITALS = ("rss_bytes", "cpu_pct", "threads", "fds", "loop_age_ms", "loop_lag_ms")
#: Host figures stored as series of source ``host``.
HOST_SERIES = (
    "load1",
    "load5",
    "load15",
    "mem_used_bytes",
    "mem_available_bytes",
    "swap_used_bytes",
    "disk_free_bytes",
)
#: How long pm-monitor keeps collecting after a stop request. ``pm-opctl-cli
#: stop`` (and ``docker stop``) signal every process at once, so the final
#: beacons of the rest arrive just after pm-monitor's own SIGTERM; without
#: this grace it exited first and the stop was never seen -- no STOPPED, no
#: events, nothing in metrics.db (review R9). Longer than a reporter's 0.5 s
#: final linger (``health.reporter.FINAL_LINGER_MS``).
FINAL_GRACE_SEC = 1.5
#: States in which a process is gone: its last gauges describe the past.
GONE_STATES = frozenset({"STOPPED", "DEAD", "MISSING"})
#: pm-engine's labelled samples -- one per participant or symbol, thousands
#: at 300 symbols -- are left out of its snapshot record: the trading,
#: participants and books blocks carry them derived, and metrics.db keeps
#: them. Kept: its unlabelled samples, and these (I123).
SNAPSHOT_ENGINE_LABELLED = frozenset({"engine.diagnostics"})
#: Of pm-engine's labelled series (one per participant or symbol), the ones
#: metrics.db keeps: what the dashboard charts and its rates and reject ratio
#: count (web-apps/dash-gui lib/metrics.ts, pinned by
#: tests/test_dash_metrics_mirror.py), plus diagnostics and reject reasons.
#: At 300 symbols and 112 participants every labelled series came to some
#: 2.5 GB at the default retention (I123). Daily totals and counter state
#: keep every series, so restarts and averages are unaffected.
STORED_ENGINE_LABELLED = frozenset(
    {
        "engine.orders_in",
        "engine.rejects",
        "engine.fills",
        "engine.cancels_in",
        "engine.amends_in",
        "engine.quotes_in",
        "engine.trades",
        "engine.traded_value",
        "engine.rejects_by_code",
        "engine.diagnostics",
        "engine.resting_orders",
        "engine.book_resting_orders",
        "engine.book_est_bytes",
        "engine.book_heap_garbage_pct",
    }
)
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


def slim(record: dict[str, Any]) -> dict[str, Any]:
    """A ``ProcessHealth`` record as the snapshot carries it: pm-engine's
    per-participant and per-symbol samples left out (see
    :data:`SNAPSHOT_ENGINE_LABELLED`)."""
    if record["process"] == "pm-engine":
        record["metrics"] = [
            m
            for m in record["metrics"]
            if not m.get("label") or m["name"] in SNAPSHOT_ENGINE_LABELLED
        ]
    return record


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
        engine_pub_addr: str | None = None,
        roles: dict[str, str] | None = None,
        host_sampler: HostSource | None = None,
        store: MetricsStore | None = None,
        history_unavailable: bool = False,
    ) -> None:
        """``engine_pub_addr`` is the engine bus to subscribe to (``main()``
        passes ``ENGINE_PUB_ADDR``; ``None`` runs without it, so a test never
        joins a developer's live engine). ``roles`` maps each configured
        gateway id to its participant role. ``store`` is ``metrics.db``
        (``None`` keeps no history: tests, or a read-only data directory).
        ``history_unavailable``: metrics.db was wanted but could not be
        opened; every store tick then counts a store error, so the
        ``metrics_store_errors`` rule keeps pm-monitor DEGRADED (I123)."""
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

        self._engine_sub: zmq.Socket[bytes] | None = None
        if engine_pub_addr is not None:
            self._engine_sub = make_subscriber(
                engine_pub_addr, *SUBSCRIPTIONS, rcvhwm=ENGINE_SUB_RCVHWM
            )
            self._engine_sub.setsockopt(zmq.LINGER, 0)

        self.table = ProcessTable()
        self.activity = Activity(session_tz, roles)
        self.thresholds = ThresholdBook()
        self.host_sampler: HostSource = (
            HostSampler() if host_sampler is None else host_sampler
        )
        self._stop_requested_at: float | None = None
        #: Seconds of collecting after a stop request (tests may shorten it).
        self.final_grace_sec = FINAL_GRACE_SEC
        self._reporter: HealthReporter | None = None
        self._snapshot_seq = 0
        #: The next event's seq; continues metrics.db's (``_resume_from``).
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
        self.engine_events_in = 0
        self.engine_events_invalid = 0
        self.threshold_changes = 0
        self.store_errors = 0
        self.loop_errors = 0

        self.store = store
        self.history_unavailable = history_unavailable
        self._next_averages = 0.0
        if store is not None:
            self._resume_from(store)

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
        if self._engine_sub is not None:
            poller.register(self._engine_sub, zmq.POLLIN)
        reporter = self._reporter
        next_snapshot = self._clock()
        while True:
            requested = self._stop_requested_at
            if (
                requested is not None
                and self._clock() - requested >= self.final_grace_sec
            ):
                break
            if reporter is not None:
                reporter.tick_and_publish(self.metric_samples)
            wait_ms = (next_snapshot - self._clock()) * 1000.0
            try:
                events = dict(poller.poll(timeout=max(0, min(POLL_MS, int(wait_ms)))))
            except zmq.ZMQError as exc:
                if exc.errno != errno.EINTR:
                    raise
                continue  # a signal; stop() has recorded the request
            if self._pull in events:
                self._guarded("drain", self.drain)
            if self._engine_sub is not None and self._engine_sub in events:
                self._guarded("engine", self.drain_engine)
            now = self._clock()
            if now >= next_snapshot:
                self._guarded("drain", self.drain)
                self._guarded("snapshot", self.publish_snapshot)
                self._guarded("store", self.store_tick)
                # Fixed cadence; after a stall resume from now, never burst.
                next_snapshot += SNAPSHOT_INTERVAL_SEC
                if next_snapshot <= now:
                    next_snapshot = now + SNAPSHOT_INTERVAL_SEC
        # The final picture: what stopped with us is recorded, published and
        # stored before pm-monitor goes.
        self._guarded("drain", self.drain)
        self._guarded("snapshot", self.publish_snapshot)
        self._guarded("store", self.store_tick)

    def _guarded(self, step: str, fn: Callable[[], object]) -> None:
        """Run one step of the loop; a bug in it costs that step, not the
        process. The watcher must outlive whatever it is watching report
        (review R1): counted in ``monitor.loop_errors``, logged with its
        traceback at most once a minute per step."""
        try:
            fn()
        except Exception:
            self.loop_errors += 1
            now = self._clock()
            key = f"loop:{step}"
            if now - self._last_warning.get(key, float("-inf")) >= WARN_EVERY_SEC:
                self._last_warning[key] = now
                log.exception("pm-monitor %s step failed; continuing", step)

    def stop(self) -> None:
        """Ask the loop to exit after ``final_grace_sec`` of collecting the
        other processes' final beacons; then one last snapshot."""
        if self._stop_requested_at is None:
            log.info(
                "stop requested; collecting final beacons for %.1f s",
                self.final_grace_sec,
            )
            self._stop_requested_at = self._clock()

    def close(self) -> None:
        if self._reporter is not None:
            self._reporter.stop()
            self._reporter = None
        if self.store is not None:
            try:
                self.store.close(self._wall_clock(), self.activity.tracker.state)
            except sqlite3.Error as exc:
                log.error("metrics.db not closed cleanly: %s", exc)
            self.store = None
        self._pull.close()
        self._pub.close()
        if self._engine_sub is not None:
            self._engine_sub.close()

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
        outcome = self.table.ingest(beacon, now, self.rules.silent_after_beacons)
        if outcome in (Ingest.NEW, Ingest.UPDATED, Ingest.RESTARTED):
            key = process_key(beacon.process, beacon.instance, beacon.host)
            now_wall = self._wall_clock()
            state = self.table.get(beacon.process, beacon.instance, beacon.host)
            if self.store is not None and state is not None:
                self._record_beacon(self.store, key, state, now_wall)
            self.activity.observe(key, beacon, now, now_wall)
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

    def drain_engine(self) -> int:
        """Read queued engine bus messages into events; return the count."""
        sub = self._engine_sub
        if sub is None:
            return 0
        n = 0
        while n < ENGINE_DRAIN_BUDGET:
            try:
                frames = sub.recv_multipart(flags=zmq.NOBLOCK)
            except zmq.Again:
                break
            n += 1
            self.receive_engine(frames)
        return n

    def receive_engine(self, frames: list[bytes]) -> None:
        """One engine bus message: update activity, publish its event."""
        self.engine_events_in += 1
        try:
            event = translate(frames, self.activity, self._wall_clock())
        except Exception as exc:  # a malformed message must not stop us
            self.engine_events_invalid += 1
            self._warn("engine", "engine bus message not understood: %s", exc)
            return
        if event is not None:
            self.publish_event(event.kind, event.severity, event.subject, event.detail)

    # ------------------------------------------------------------------
    # snapshot out
    # ------------------------------------------------------------------

    def refresh_sources(self, now: float) -> None:
        """Re-read the roster when its files changed; forget long-silent
        sources nobody expects."""
        self.roster.refresh()
        expected = self.roster.expected

        def keep(state: ProcessState) -> bool:
            if expected is not None and state.identity in expected:
                return True
            return now - state.received_at <= FORGET_AFTER_SEC

        for state in self.table.forget(keep):
            self.sources_forgotten += 1
            self.activity.forget_source(state.key)

    def processes(
        self,
        now: float,
        breached: set[str] | frozenset[str] = frozenset(),
        *,
        refresh: bool = True,
    ) -> list[dict[str, Any]]:
        """Every process as a judged ``ProcessHealth`` record.

        ``breached``: process keys with a threshold in breach (DEGRADED).
        ``refresh``: re-read the roster and forget old sources first (the
        snapshot has just done so). Sources first (exchange, then bots), then
        the expected processes never heard from.
        """
        if refresh:
            self.refresh_sources(now)
        expected = self.roster.expected
        now_wall = self._wall_clock()
        states = self.table.states()
        records = [
            slim(
                state.health(
                    now,
                    now_wall,
                    state.evaluate(
                        now,
                        self.rules,
                        breached=state.key in breached,
                        alive=self._alive,
                    ),
                )
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

    def readings(self, now: float, host: dict[str, Any]) -> list[Reading]:
        """Everything the §9.6 rules judge, measured now."""
        t = self.config.thresholds
        out = [
            band_reading(t, "host_cpu_pct", "host", host["cpu_pct"]),
            band_reading(t, "host_mem_pct", "host", mem_used_pct(host)),
        ]
        if self.activity.requests_5m(now) >= MIN_REQUESTS_5M:
            out.append(
                band_reading(
                    t, "reject_pct_5m", "exchange", self.activity.reject_pct_5m(now)
                )
            )
        free = disk_free_pct(host)
        if free is not None:
            out.append(band_reading(t, "disk_free_pct", "host", free))
        for state in self.table.states():
            if not state.is_live(now, self.rules):
                continue
            b = state.beacon
            if not b.starting:
                out.append(
                    Reading(
                        LOOP_AGE_RULE,
                        state.key,
                        state.loop_age_ms,
                        warn=LOOP_AGE_WARN_MS,
                    )
                )
            growth = state.rss_growth_pct(now)
            if growth is not None:
                out.append(band_reading(t, "rss_growth_pct_1h", state.key, growth))
            if b.process == "pm-engine":
                for sample in b.metrics:
                    if sample.name == "engine.handle_us_p99" and not sample.label:
                        out.append(
                            band_reading(
                                t, "engine_handle_p99_us", state.key, sample.value
                            )
                        )
        for symbol, book in self.activity.books.items():
            garbage = book.gauges.get("engine.book_heap_garbage_pct")
            entries = book.gauges.get("engine.book_heap_entries", 0.0)
            if garbage is not None and entries >= MIN_HEAP_ENTRIES:
                out.append(band_reading(t, "heap_garbage_pct", symbol, garbage))
        for (rule, key), rate in self.activity.increases.items():
            out.append(increase_reading(rule, key, rate.last_5m(now)))
        return out

    def snapshot(self) -> dict[str, Any]:
        """The ``health.snapshot`` payload for now (unvalidated dict).

        Publishes a ``THRESHOLD`` event for every threshold change and a
        ``PROCESS_STATUS`` event for every state that changed since the
        previous snapshot.
        """
        now = self._clock()
        now_wall = self._wall_clock()
        self.activity.roll_day(now_wall)
        self.refresh_sources(now)
        host = self.host_sampler.sample()
        if self.store is not None:
            self._record_host(self.store, host, now_wall)
            self._refresh_averages(self.store, now_wall)
        for change in self.thresholds.evaluate(
            self.readings(now, host), iso_utc(now_wall)
        ):
            self._publish_threshold(change)
        breached = self.thresholds.breached_subjects()
        processes = self.processes(now, breached, refresh=False)
        self._publish_transitions(processes)
        process_keys = {p["key"] for p in processes}
        gone = {p["key"] for p in processes if p["state"] in GONE_STATES}
        engine_live = any(
            p["process"] == "pm-engine" and p["key"] not in gone and p["host"]
            for p in processes
        )
        a = self.activity
        return {
            "ts": iso_utc(now_wall),
            "seq": self._snapshot_seq,
            "exchange": {
                "status": exchange_status(
                    processes,
                    self.roster.expected,
                    degraded=bool(breached - process_keys),
                ),
                "session_state": a.session_state[:32],
                "trading_date": a.date,
                "session_timezone": timezone_name(self.session_tz),
            },
            "host": host,
            "processes": processes,
            "trading": a.trading(now, now_wall, engine_live=engine_live),
            "participants": a.participant_records(
                now, now_wall, engine_live=engine_live
            ),
            "books": a.book_records(),
            "gateways": a.gateway_records(now, process_keys, gone),
            "thresholds": self.thresholds.active(),
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

    def _publish_threshold(self, change: Change) -> None:
        self.threshold_changes += 1
        log.log(
            THRESHOLD_LOG_LEVEL[change.level],
            "threshold %s on %s",
            change.detail,
            change.subject,
        )
        self.publish_event("THRESHOLD", change.severity, change.subject, change.detail)

    def publish_event(
        self, kind: str, severity: str, subject: str, detail: str
    ) -> bool:
        """Store and publish one ``health.event``; False when it failed.

        With ``metrics.db`` the event's ``seq`` is its ``events.seq``, so the
        bridge can fetch what it missed by sequence. The number continues
        from metrics.db (``_resume_from``) and is never reused: an event
        whose write failed is published under its number all the same, and
        the next one takes the following number.
        """
        ts = iso_utc(self._wall_clock())
        subject, detail = subject[:200], detail[:512]
        seq = self._event_seq
        if self.store is not None:
            try:
                self.store.add_event(seq, ts, kind, severity, subject, detail)
            except sqlite3.Error as exc:
                self._store_failed(exc)
        try:
            frames = make_health_event(
                seq=seq,
                ts=ts,
                kind=kind,
                severity=severity,
                subject=subject,
                detail=detail,
            )
        except MessageValidationError as exc:
            self._warn("event", "health event invalid, not published: %s", exc)
            return False
        self._pub.send_multipart(frames)
        self._event_seq = seq + 1
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
    # metrics.db
    # ------------------------------------------------------------------

    def _resume_from(self, store: MetricsStore) -> None:
        """Continue the day metrics.db recorded (a pm-monitor restart, I69)."""
        now, now_wall = self._clock(), self._wall_clock()
        a = self.activity
        a.tracker.prime(store.counter_state())
        a.roll_day(now_wall)
        restored = store.totals_for(a.date)
        for source, name, label, total in restored:
            a.restore(source, name, label, total, now, now_wall)
        if restored:
            log.info(
                "resumed %d series of %s from %s", len(restored), a.date, store.path
            )
        a.sink = self._store_increment
        self._refresh_averages(store, now_wall, force=True)
        self._event_seq = store.next_event_seq()

    def _store_increment(
        self,
        date: str,
        source: str,
        name: str,
        label: str,
        delta: float,
        now_wall: float,
    ) -> None:
        if self.store is not None:
            self.store.record_increment(date, (source, name, label), delta, now_wall)

    @staticmethod
    def _record_beacon(
        store: MetricsStore, key: str, state: ProcessState, now_wall: float
    ) -> None:
        """Vitals as judged -- loop figures less credited silence (I108) --
        and the beacon's application metrics as sent. A labelled series is
        kept at minute resolution only, and of pm-engine's only those in
        :data:`STORED_ENGINE_LABELLED` (I123): its 10 s rows and its
        unused series were most of metrics.db."""
        beacon = state.beacon
        engine = beacon.process == "pm-engine"
        for name in VITALS:
            value = getattr(state if name.startswith("loop_") else beacon, name)
            if value is not None:
                store.record(
                    (key, f"proc.{name}", ""), float(value), now_wall, counter=False
                )
        for sample in beacon.metrics:
            labelled = sample.label != ""
            if labelled and engine and sample.name not in STORED_ENGINE_LABELLED:
                continue
            store.record(
                (key, sample.name, sample.label),
                sample.value,
                now_wall,
                counter=sample.kind == "COUNTER",
                raw=not labelled,
            )

    @staticmethod
    def _record_host(
        store: MetricsStore, host: dict[str, Any], now_wall: float
    ) -> None:
        def put(name: str, value: float, label: str = "") -> None:
            store.record(
                ("host", name, label),
                float(value),
                now_wall,
                counter=False,
                raw=label == "",
            )

        put("host.cpu_pct", host["cpu_pct"])
        for i, pct in enumerate(host["cpu_per_core"]):
            put("host.cpu_pct", pct, f"cpu{i}")
        for field_name in HOST_SERIES:
            put(f"host.{field_name}", host[field_name])
        for f in host["files"]:
            put("files.size_bytes", f["size_bytes"], f["name"])

    def _refresh_averages(
        self, store: MetricsStore, now_wall: float, *, force: bool = False
    ) -> None:
        """Re-read the 7-day daily averages the snapshot shows (once a minute)."""
        if not force and now_wall < self._next_averages:
            return
        self._next_averages = now_wall + AVERAGES_EVERY_SEC
        a = self.activity
        wanted: list[tuple[str, str | None]] = [
            ("engine.orders_in", None),
            ("engine.trades", None),
            *(("engine.orders_in", gw) for gw in a.participants),
        ]
        try:
            a.daily_averages = {
                (name, label): store.avg_per_day(name, label, before=a.date)
                for name, label in wanted
            }
        except sqlite3.Error as exc:
            self._store_failed(exc)

    def store_tick(self) -> None:
        """Write what is due: raw rows every 10 s, closed minutes, retention.

        A failing disk costs history, never the live snapshot. Without the
        metrics.db that was wanted, every tick's history is lost, and counted
        as such (``history_unavailable``)."""
        store = self.store
        if store is None:
            if self.history_unavailable:
                self.store_errors += 1
            return
        now_wall = self._wall_clock()
        try:
            if store.due_raw(now_wall):
                store.flush_raw(now_wall, self.activity.tracker.state)
            store.flush_minutes(now_wall)
            store.apply_retention(now_wall)
        except sqlite3.Error as exc:
            self._store_failed(exc)

    def _store_failed(self, exc: Exception) -> None:
        self.store_errors += 1
        self._warn("store", "metrics.db write failed: %s", exc)

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
            counter("monitor.engine_events_in", self.engine_events_in),
            counter("monitor.engine_events_invalid", self.engine_events_invalid),
            counter("monitor.threshold_changes", self.threshold_changes),
            counter("monitor.store_errors", self.store_errors),
            counter("monitor.loop_errors", self.loop_errors),
            gauge("monitor.series_tracked", len(self.activity.tracker)),
            gauge("monitor.snapshot_bytes", self.snapshot_bytes),
            gauge("monitor.snapshot_build_ms", self.snapshot_build_ms),
        ]

    def _warn(self, kind: str, msg: str, *args: object) -> None:
        now = self._clock()
        if now - self._last_warning.get(kind, float("-inf")) >= WARN_EVERY_SEC:
            self._last_warning[kind] = now
            log.warning(msg, *args)
