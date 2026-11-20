"""
Session Scheduler — drives the engine through daily trading phases.

Reads a schedule (from the deployed engine config, or default times) and sends
``session.transition`` messages to the engine at the configured wall-clock
times via a PUSH socket. It runs as a closed-loop driver:

  - On startup it queries the engine's current session state and only replays
    the transitions still needed to reach the correct current phase.
  - After each transition it listens to the engine's ``session.state``
    broadcast to confirm the change was actually applied.
  - It follows an engine restart: on the engine's ``system.startup``, or when
    a transition is not confirmed and the engine then reports a state it never
    announced, it brings the engine back to the scheduled phase. An
    operator's transition is announced, so it is left alone.

Schedule dates and times use ``locale.session_timezone`` from the deployed
configuration (default ``Europe/Stockholm``), not the host's timezone.

Usage:
  poetry run pm-scheduler                  # run today's schedule once, then exit
  poetry run pm-scheduler --daily          # run continuously, once per day
  poetry run pm-scheduler --now            # close the engine if needed, then
                                           # rapid-fire all transitions (testing)
  poetry run pm-scheduler --no-confirm     # do not query/confirm via the engine
  poetry run pm-scheduler -vv              # DEBUG-level diagnostics
  poetry run pm-scheduler --daily --on-close "pm-eod run --pending"
                                           # start a command 30 s after each
                                           # CLOSED (and once at start-up)
  poetry run pm-scheduler --daily --speed 600 --start 2026-11-02T08:55
                                           # compressed: 10 simulated minutes
                                           # per second, from that local time
  EDUMATCHER_SCHEDULER_SPEED=24 poetry run pm-scheduler --daily
                                           # the same through the environment
                                           # (EDUMATCHER_SCHEDULER_START too)

Logging:
  Operational messages go through the ``logging`` module (configured at the
  process entry point, mirroring pm-engine). The default level is WARNING;
  ``-v`` gives INFO (each transition and wait), ``-vv`` DEBUG (connection,
  schedule-table and state-query diagnostics), and ``--log-level`` sets it
  outright.

Same-day behavior:
  By default the scheduler drives *today's* timeline and then exits. If it is
  started after some scheduled times have already passed, it brings the engine
  to the correct current phase (engine session states are sequential and
  dependent). Use ``--daily`` to keep the process running and repeat the
  schedule every working day.

Typical daily sequence:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED

Working days:
  The scheduler drives whatever schedule resolves for *today*: each weekday
  (mon..sun) can carry its own independent schedule, and a bank holiday for
  the configured ``locale.country`` (default ``"Sweden"``) resolves to the ``holidays:`` entry instead,
  via the ``python-holidays`` package. A day that resolves to no schedule at
  all is CLOSED. ``--daily`` mode waits through CLOSED days and resumes on
  the next day that has a schedule; a single-shot run started on a CLOSED
  day does nothing.

Wall-clock re-checking:
  Long waits (until a scheduled time, or overnight between trading days) are
  never slept in one long ``time.sleep`` call. Instead the scheduler wakes
  every ``LIVENESS_CHUNK_SEC`` (0.5 s) and re-derives the remaining wait from
  the current wall-clock time, so a server time adjustment (NTP sync, manual
  change, DST) is picked up promptly instead of only after a single long
  sleep started under stale assumptions.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from datetime import UTC, date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

import holidays
import zmq

from edumatcher.config_artifact import exit_on_config_error
from edumatcher.health import HealthReporter, gauge
from edumatcher.models.generated.health import MetricSample
from edumatcher.config import (
    COMPILED_CONFIG_FILE,
    ENGINE_PUB_ADDR,
    ENGINE_PULL_ADDR,
)
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler
from edumatcher.messaging.bus import PushSocket, make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_session_next_msg,
    make_session_state_request_msg,
    make_session_transition_msg,
)
from edumatcher.engine.config_loader import (
    DAY_KEYS,
    DEFAULT_COUNTRY,
    DEFAULT_SESSION_TIMEZONE,
    DaySchedule,
    ScheduleConfig,
)
from edumatcher.engine.schedule_resolve import is_bank_holiday, resolve_day
from edumatcher.models.session import VALID_TRANSITIONS, SessionState
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.system import (
    TOPIC_STARTUP,
    topic_session_status,
)

_CLIENT_NAME = "pm-scheduler"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# Operational logging goes through the logging module; the process entry point
# (main()) configures the handler/level, the library installs no handlers
# (mirrors the engine's setup — review finding L3).
log = logging.getLogger(__name__)

# Default schedule — used when no config file provides one. Mon-Fri run the
# historical default times; weekends and holidays are CLOSED, matching this
# scheduler's behavior before per-day schedules existed.
_DEFAULT_DAY_SCHEDULE = DaySchedule(
    pre_open="09:00",
    opening_auction_start="09:25",
    continuous_start="09:30",
    closing_auction_start="16:00",
    closing_auction_end="16:05",
)
DEFAULT_SCHEDULE = ScheduleConfig(
    days={
        "mon": _DEFAULT_DAY_SCHEDULE,
        "tue": _DEFAULT_DAY_SCHEDULE,
        "wed": _DEFAULT_DAY_SCHEDULE,
        "thu": _DEFAULT_DAY_SCHEDULE,
        "fri": _DEFAULT_DAY_SCHEDULE,
        "sat": None,
        "sun": None,
    },
    holidays=None,
)

# Rapid-fire delays for --now mode (seconds between transitions)
NOW_MODE_DELAY = 3.0

# Bounded ZMQ send timeout and linger (milliseconds) so the scheduler can never
# block forever when the engine is not consuming (review finding H2). Without
# these, a PUSH ``send`` blocks until a peer appears and ``close`` waits
# forever on undelivered messages.
SEND_TIMEOUT_MS = 2000
LINGER_MS = 1000

# How long to wait for the engine to broadcast an applied session.state before
# warning that a transition could not be confirmed (review finding M3).
CONFIRM_TIMEOUT_MS = 2000

# How long to wait for the engine to answer a session-state query at startup
# (review finding A2).
QUERY_TIMEOUT_MS = 2000

# Brief settle so the confirmation SUB subscription takes effect before the
# startup state query — PUB/SUB is subject to the slow-joiner problem, so a
# request sent too early can miss its reply (review finding L5).
SUB_CONNECT_SETTLE_SEC = 0.1

# Identifier the scheduler uses when talking to the engine (request/reply
# replies come back on ``system.session_status.<ID>``).
SCHEDULER_GATEWAY_ID = "SCHEDULER"

# The engine boots CLOSED when the scheduler owns session state
# (sessions_enabled=true), so a schedule must be a valid transition path
# starting from CLOSED.
_ENGINE_START_STATE = SessionState.CLOSED

# The upper bound on one sleep in _sleep_until_wallclock, which re-derives a
# long wait from the wall clock at least this often so the scheduler picks up
# server time adjustments (NTP sync, manual change, DST). The scheduler's own
# waits pass the much shorter LIVENESS_CHUNK_SEC.
WALLCLOCK_RECHECK_SEC = 30.0

#: The chunk the scheduler actually sleeps in while waiting for a transition
#: or midnight. Every wake-up calls ``is_running()``, which ticks the health
#: beacon, so a scheduler idle for hours still reports a fresh main loop. At
#: the 30 s re-check bound it would read as HUNG between wake-ups (design
#: finding F8). It must also stay well under pm-monitor's DEGRADED line for
#: ``loop_lag_ms`` (1 s, the longest gap between ticks): at exactly 1 s every
#: gap measured a hair over it and an idle scheduler read DEGRADED forever
#: (I76). Re-deriving the remaining wait more often is harmless.
LIVENESS_CHUNK_SEC = 0.5

#: Seconds until the scheduler next acts, as last computed while waiting;
#: 0 when not waiting. Reported as ``sched.next_transition_in_s``.
_next_wait_sec = 0.0


class _Clock:
    """Session-local time the schedule runs on.

    By default the wall clock. Under ``--speed`` (compressed mode) a
    simulated local clock that starts at ``start`` and runs ``speed`` times
    faster than the wall clock: days, weekends and holidays pass in sim time,
    while waits and the countdown instants sent to the engine are wall time.
    """

    def __init__(
        self,
        speed: float = 1.0,
        start: datetime | None = None,
        *,
        session_timezone: str = DEFAULT_SESSION_TIMEZONE,
    ) -> None:
        self.timezone = ZoneInfo(session_timezone)
        self.speed = speed
        if start is not None and start.tzinfo is not None:
            start = start.astimezone(self.timezone).replace(tzinfo=None)
        self._start = start
        self._wall0 = time.time()

    def now(self) -> datetime:
        if self._start is None:
            return datetime.now(self.timezone).replace(tzinfo=None)
        elapsed = (time.time() - self._wall0) * self.speed
        return self._start + timedelta(seconds=elapsed)

    def seconds_until(self, target: datetime) -> float:
        """Wall seconds until the local schedule time ``target``."""
        if self._start is None:
            return _seconds_until_local(target, self.timezone)
        return (target - self.now()).total_seconds() / self.speed

    def wall_instant(self, target: datetime) -> datetime:
        """The (aware) wall-clock instant at which ``target`` falls."""
        if self._start is None:
            return _local_instant(target, self.timezone)
        return datetime.now(UTC) + timedelta(seconds=self.seconds_until(target))

    def is_past(self, target: datetime, now: datetime) -> bool:
        if self._start is None:
            return _local_instant(target, self.timezone) < now.replace(
                tzinfo=self.timezone
            ).astimezone(UTC)
        return target < now


_clock = _Clock()


def _hhmm_to_minutes(hhmm: str) -> int:
    """Return minutes-since-midnight for a normalized ``"HH:MM"`` string."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _transitions_for_day_schedule(ds: DaySchedule) -> list[tuple[str, str]]:
    """Map one resolved day's DaySchedule onto the engine's transition sequence.

    The times are already canonical ``HH:MM`` — ``load_engine_config`` runs
    them through ``normalize_hhmm`` — so there is nothing left to validate or
    recover here.
    """
    return [
        (ds.pre_open, SessionState.PRE_OPEN.value),
        (ds.opening_auction_start, SessionState.OPENING_AUCTION.value),
        (ds.continuous_start, SessionState.CONTINUOUS.value),
        (ds.closing_auction_start, SessionState.CLOSING_AUCTION.value),
        (ds.closing_auction_end, SessionState.CLOSED.value),
    ]


def _is_supported_country(country: str) -> bool:
    """Return ``True`` if ``python-holidays`` recognises ``country``.

    Accepts either a country name (``"Sweden"``) or an ISO 3166-1 alpha-2
    code (``"SE"``).
    """
    try:
        holidays.country_holidays(country)
        return True
    except NotImplementedError:
        return False


def _validate_schedule(schedule: list[tuple[str, str]]) -> list[str]:
    """Return a list of problems with the schedule (empty means valid).

    Engine session transitions are sequential and dependent, so a schedule is
    only usable if (a) its state sequence forms a legal path through
    ``VALID_TRANSITIONS`` starting from the engine's boot state (CLOSED), and
    (b) its times are strictly increasing. A partial or out-of-order schedule
    would otherwise be silently rejected by the engine at runtime (finding M1).
    """
    errors: list[str] = []

    # (a) transition-chain validity, starting from the engine's boot state.
    prev_state = _ENGINE_START_STATE
    for hhmm, state_value in schedule:
        try:
            state = SessionState(state_value)
        except ValueError:
            errors.append(f"unknown session state {state_value!r} at {hhmm}")
            continue
        if state not in VALID_TRANSITIONS.get(prev_state, set()):
            errors.append(
                f"illegal transition {prev_state.value} -> {state.value} at {hhmm} "
                "(schedule must be a valid path starting from CLOSED)"
            )
        prev_state = state

    # (b) strictly increasing times.
    last_minutes: int | None = None
    for hhmm, _state in schedule:
        minutes = _hhmm_to_minutes(hhmm)
        if last_minutes is not None and minutes <= last_minutes:
            errors.append(
                f"schedule time {hhmm} is not strictly after the previous entry"
            )
        last_minutes = minutes

    return errors


def _validate_schedule_config(cfg: ScheduleConfig) -> list[str]:
    """Validate every distinct DaySchedule in a resolved ScheduleConfig.

    Each present day (mon..sun) and the holidays entry must independently
    form a legal transition chain from CLOSED, in strictly increasing time
    order — see :func:`_validate_schedule`. Identical DaySchedule objects
    (e.g. every weekday sharing one ``weekdays:`` block) are validated once;
    an error is reported against every label that shares the bad entry
    rather than being repeated once per day.
    """
    labelled: list[tuple[str, DaySchedule]] = [
        (f"schedule.{key}", ds)
        for key, ds in ((k, cfg.days[k]) for k in DAY_KEYS)
        if ds is not None
    ]
    if cfg.holidays is not None:
        labelled.append(("schedule.holidays", cfg.holidays))

    by_schedule: dict[DaySchedule, list[str]] = {}
    for label, ds in labelled:
        by_schedule.setdefault(ds, []).append(label)

    errors: list[str] = []
    for ds, labels in by_schedule.items():
        transitions = _transitions_for_day_schedule(ds)
        for err in _validate_schedule(transitions):
            errors.append(f"{err} ({', '.join(labels)})")
    return errors


def _time_today(hhmm: str, day: date | None = None) -> datetime:
    """Parse a validated ``"HH:MM"`` string into a naive datetime on ``day``
    (default: the schedule clock's today).

    Classification, waits and countdowns resolve this local time through the
    same DST policy rather than comparing naive wall-clock readings.
    """
    h, m = hhmm.split(":")
    now = _clock.now()
    on = now.date() if day is None else day
    return now.replace(
        year=on.year,
        month=on.month,
        day=on.day,
        hour=int(h),
        minute=int(m),
        second=0,
        microsecond=0,
    )


def _local_instant(target: datetime, timezone: ZoneInfo) -> datetime:
    """Resolve a local schedule time to UTC using the later DST instant.

    A repeated time runs only on its second occurrence. A nonexistent time
    during the spring jump is shifted forward by the gap. For ordinary times
    both fold values resolve to the same instant.
    """
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone)
    return max(
        target.replace(fold=0).astimezone(UTC),
        target.replace(fold=1).astimezone(UTC),
    )


def _seconds_until_local(target: datetime, timezone: ZoneInfo | None = None) -> float:
    """Seconds from now until the local schedule time under the DST policy."""
    return _local_instant(target, timezone or _clock.timezone).timestamp() - time.time()


def _next_scheduled_day(cfg: ScheduleConfig, day: date, country: str) -> date:
    """Return the next date strictly after ``day`` that resolves to a
    schedule (not CLOSED) under ``cfg``/``country``.

    Uses the same day-resolution rule as everywhere else (see
    :func:`edumatcher.engine.schedule_resolve.resolve_day`), so a scheduler
    left running under ``--daily`` skips CLOSED days exactly the way a
    single-shot run would if started on one.
    """
    candidate = day + timedelta(days=1)
    # Bounded: a bank-holiday calendar can never plausibly cover an entire
    # year of consecutive CLOSED days, so this loop always terminates well
    # before the guard trips.
    for _ in range(366):
        if resolve_day(cfg, candidate, country) is not None:
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _next_open(cfg: ScheduleConfig, day: date, country: str) -> datetime | None:
    """The pre-open of the next scheduled day after ``day``, local time.

    None when no day within a year has a schedule (every day CLOSED): there
    is no open to count down to.
    """
    next_day = _next_scheduled_day(cfg, day, country)
    resolved = resolve_day(cfg, next_day, country)
    if resolved is None:
        return None
    h, m = resolved.pre_open.split(":")
    return datetime.combine(next_day, datetime.min.time()).replace(
        hour=int(h), minute=int(m)
    )


def _sleep_until_wallclock(
    remaining_seconds: Callable[[], float],
    is_running: Callable[[], bool],
    max_chunk: float = WALLCLOCK_RECHECK_SEC,
    watch: Callable[[float], bool] | None = None,
) -> bool:
    """Sleep until ``remaining_seconds()`` reaches zero, re-checking often.

    The remaining duration is *re-derived from the wall clock on every
    wake-up* (by calling ``remaining_seconds()`` again) rather than computed
    once and counted down against ``time.monotonic()``. That matters for
    waits pinned to an absolute local time: if the server's wall clock is
    stepped (NTP sync, manual change, DST) while the scheduler sleeps, a
    monotonic countdown started under the old assumption would fire at the
    wrong moment, whereas re-deriving the remaining time from
    ``datetime.now()`` at least every ``max_chunk`` seconds corrects for the
    jump within one wake-up cycle. ``max_chunk`` also bounds every individual
    ``time.sleep`` call (``WALLCLOCK_RECHECK_SEC``, 30 s, by default; the
    scheduler's waits pass ``LIVENESS_CHUNK_SEC``, 0.5 s).

    ``watch``, when given, spends each chunk instead of ``time.sleep`` and
    returns ``True`` to end the wait early; the function then returns
    ``True`` too. It returns ``False`` when the time ran out or the process
    is stopping.
    """
    global _next_wait_sec
    try:
        while is_running():
            remaining = remaining_seconds()
            if remaining <= 0:
                return False
            _next_wait_sec = remaining
            chunk = max(0.0, min(max_chunk, remaining))
            if watch is None:
                time.sleep(chunk)
            elif watch(chunk):
                return True
        return False
    finally:
        _next_wait_sec = 0.0


def _metric_samples() -> list[MetricSample]:
    """Design §8.5: how long until the scheduler next acts."""
    return [gauge("sched.next_transition_in_s", _next_wait_sec)]


def _no_wait() -> float:
    """A pre-send wait of zero (used for immediate/catch-up transitions)."""
    return 0.0


def _fixed_wait(seconds: float) -> Callable[[], float]:
    """Return a pre-send wait counting down from a fixed duration (used by --now).

    The returned callable computes remaining time against a monotonic
    deadline fixed on first call, so repeated calls (as done by
    ``_sleep_until_wallclock``) see a shrinking remainder rather than the
    same constant forever.
    """
    deadline: float | None = None

    def _remaining() -> float:
        nonlocal deadline
        if deadline is None:
            deadline = time.monotonic() + seconds
        return deadline - time.monotonic()

    return _remaining


def _to_utc_iso(target: datetime) -> str:
    """A local naive schedule time as UTC ISO-8601 with milliseconds.

    The schedule is written and reasoned about in local wall-clock time; CALF
    timestamps are UTC throughout, and a countdown rendered by a browser in
    another timezone has to be anchored to an absolute instant rather than to
    a wall-clock reading the client would interpret as its own.
    """
    aware = _clock.wall_instant(target) if target.tzinfo is None else target
    return (
        aware.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _wait_until(target: datetime) -> Callable[[], float]:
    """Return a pre-send wait that counts down to an absolute local time."""
    return lambda: _clock.seconds_until(target)


class _CloseHook:
    """Start the ``--on-close`` command after the day's CLOSED transition.

    The command runs ``delay_sec`` later so the services that react to the
    close (pm-clearing writing its close snapshot) have finished, and runs in a
    child process the scheduler does not wait for: a slow or failing command
    never delays the next transition.  One child at a time; a trigger that
    arrives while one is still running starts the command once more when it
    finishes (several such triggers make one more run), so no close is left
    unsettled when no later trigger comes (Scheduler review 2026-11, C6).
    """

    def __init__(self, command: str, delay_sec: float) -> None:
        self._argv = shlex.split(command)
        self._delay = delay_sec
        self._lock = threading.Lock()
        self._child: subprocess.Popen[bytes] | None = None
        self._again = False
        self._timers: list[threading.Timer] = []
        self._reapers: list[threading.Thread] = []

    def __call__(self) -> None:
        timer = threading.Timer(self._delay, self._spawn)
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()

    def _spawn(self) -> None:
        with self._lock:
            if self._child is not None and self._child.poll() is None:
                if not self._again:
                    log.info(
                        "--on-close command is still running; "
                        "it runs once more when it finishes"
                    )
                self._again = True
                return
            self._start_locked()

    def _start_locked(self) -> None:
        """Start the command and its reaper; the caller holds ``_lock``."""
        try:
            child = subprocess.Popen(self._argv)
        except OSError as exc:
            log.error("could not start --on-close command %r: %s", self._argv, exc)
            return
        self._child = child
        reaper = threading.Thread(target=self._reap, args=(child,), daemon=True)
        self._reapers.append(reaper)
        log.info("started --on-close command: %s", shlex.join(self._argv))
        reaper.start()

    def _reap(self, child: subprocess.Popen[bytes]) -> None:
        code = child.wait()
        if code != 0:
            log.warning("--on-close command exited %d", code)
        else:
            log.info("--on-close command finished")
        with self._lock:
            if self._again:
                self._again = False
                self._start_locked()

    def wait_timers(self) -> None:
        for timer in list(self._timers):
            timer.join()

    def wait(self) -> None:
        """Wait for pending triggers and the commands they started."""
        self.wait_timers()
        with self._lock:
            child = self._child
        if child is not None and child.poll() is None:
            log.info("waiting for the --on-close command (pid %d) to finish", child.pid)
        while True:
            with self._lock:
                alive = [r for r in self._reapers if r.is_alive()]
            if not alive:
                return
            for reaper in alive:
                reaper.join()

    def stop(self) -> None:
        """Cancel triggers that have not fired; a running command is left alone."""
        for timer in list(self._timers):
            timer.cancel()


def _send_transition(
    push_sock: PushSocket,
    state: str,
    next_state: str = "",
    next_at: str = "",
) -> bool:
    """Send one ``session.transition``; return ``False`` if not delivered.

    The PUSH socket carries a bounded send timeout (finding H2), so a send
    raises ``zmq.Again`` instead of blocking forever when the engine is not
    consuming. Any other ZMQ error (e.g. a terminated context) is caught too so
    a transport failure degrades gracefully instead of crashing the scheduler
    (review finding L7).
    """
    try:
        push_sock.send_multipart(
            make_session_transition_msg(state, next_state=next_state, next_at=next_at)
        )
        return True
    except zmq.Again:
        log.warning(
            "engine not reachable; transition to %s was not "
            "delivered (send timed out)",
            state,
        )
        return False
    except zmq.ZMQError as exc:
        log.error("failed to send transition to %s: %s", state, exc)
        return False


def _announce_next(push_sock: PushSocket, state: str, at: datetime) -> None:
    """Tell the engine the next transition without performing one.

    For a wait no transition has described: the day's first, or the next
    day's open while the exchange is closed. Best-effort, like every send.
    """
    try:
        push_sock.send_multipart(make_session_next_msg(state, _to_utc_iso(at)))
    except zmq.ZMQError as exc:
        log.warning("could not announce the next transition (%s): %s", state, exc)


def _poll_live(
    sock: zmq.Socket[bytes],
    timeout_ms: int,
    on_wake: Callable[[], object] | None,
) -> bool:
    """``sock.poll(timeout_ms)``, in LIVENESS_CHUNK_SEC slices calling
    ``on_wake`` between them.

    An engine round-trip waits up to 2 s for a reply; polled in one piece the
    health beacon saw a loop ~2 s late and read DEGRADED at start-up and at
    every session transition (A+B review, I93). ``on_wake`` is the same
    ``is_running`` closure every other wait calls, which ticks the reporter.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while True:
        remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000.0))
        chunk_ms = min(remaining_ms, int(LIVENESS_CHUNK_SEC * 1000))
        if sock.poll(timeout=chunk_ms):
            return True
        if on_wake is not None:
            on_wake()
        if remaining_ms <= chunk_ms:
            return False


def _drain(sock: zmq.Socket[bytes]) -> None:
    """Discard everything already queued on ``sock``.

    The SUB socket also queues other producers' ``session.state`` broadcasts
    and late replies to earlier queries, sometimes for hours. Drained right
    before a request, only what the engine publishes after it can answer it
    (Scheduler review 2026-11, C3).
    """
    while sock.poll(0):
        sock.recv_multipart()


def _confirm_transition(
    confirm_sock: zmq.Socket[bytes],
    expected_state: str,
    timeout_ms: int = CONFIRM_TIMEOUT_MS,
    on_wake: Callable[[], object] | None = None,
) -> bool:
    """Wait for the engine to broadcast ``session.state == expected_state``.

    Returns ``True`` once the applied-state broadcast is observed, or ``False``
    if it does not arrive within ``timeout_ms`` (engine rejected the transition
    or is unreachable). A broadcast carrying a ``command_id`` answers an
    operator's transition, not this one, and does not count. Best-effort:
    PUB/SUB gives no delivery guarantee.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000.0))
        if not _poll_live(confirm_sock, remaining_ms, on_wake):
            break
        try:
            topic, payload = decode(confirm_sock.recv_multipart())
        except Exception:
            continue
        if (
            topic == TOPIC_SESSION_STATE
            and str(payload.get("state", "")) == expected_state
            and not payload.get("command_id")
        ):
            return True
    return False


@dataclass(frozen=True)
class _EngineStatus:
    """The engine's session state and the UTC instant it entered it.

    ``since`` stays in its wire form, ``YYYY-MM-DDTHH:MM:SS.mmmZ``: one fixed
    width in UTC, so string order is time order.
    """

    state: SessionState
    since: str


def _query_engine_status(
    push_sock: PushSocket,
    sub_sock: zmq.Socket[bytes],
    gateway_id: str = SCHEDULER_GATEWAY_ID,
    timeout_ms: int = QUERY_TIMEOUT_MS,
    on_wake: Callable[[], object] | None = None,
) -> _EngineStatus | None:
    """Ask the engine for its current session state and wait for the reply.

    Sends ``system.session_state_request`` and reads the matching
    ``system.session_status.<ID>`` broadcast (review finding A2). Returns
    ``None`` if the engine does not answer within ``timeout_ms`` or the reply
    is unusable — the caller then falls back to assuming a CLOSED start.
    """
    reply_topic = topic_session_status(gateway_id.upper())
    _drain(sub_sock)
    try:
        push_sock.send_multipart(make_session_state_request_msg(gateway_id))
    except zmq.ZMQError as exc:
        log.debug("session-state request could not be sent: %s", exc)
        return None

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000.0))
        if not _poll_live(sub_sock, remaining_ms, on_wake):
            break
        try:
            topic, payload = decode(sub_sock.recv_multipart())
        except Exception:
            continue
        if topic == reply_topic:
            try:
                return _EngineStatus(
                    SessionState(str(payload.get("state", ""))),
                    str(payload.get("state_since", "")),
                )
            except ValueError:
                return None
    return None


def _query_engine_state(
    push_sock: PushSocket,
    sub_sock: zmq.Socket[bytes],
    gateway_id: str = SCHEDULER_GATEWAY_ID,
    timeout_ms: int = QUERY_TIMEOUT_MS,
    on_wake: Callable[[], object] | None = None,
) -> SessionState | None:
    """:func:`_query_engine_status`, the state alone."""
    status = _query_engine_status(
        push_sock, sub_sock, gateway_id, timeout_ms=timeout_ms, on_wake=on_wake
    )
    return None if status is None else status.state


def _left_over(status: _EngineStatus, day: date) -> bool:
    """Whether the engine is in a state of a day before ``day`` that never closed.

    CLOSED is every day's start, so only another state counts: one entered
    before ``day`` began on the schedule clock (L042). Without this test a
    CONTINUOUS left over from yesterday is on today's path and is taken as
    today's, and the close -- DAY expiry, archive, counter reset -- never
    happens.
    """
    day_start = _to_utc_iso(_time_today("00:00", day))
    return status.state != SessionState.CLOSED and status.since < day_start


def _catch_up_transitions(
    past: list[tuple[str, str]],
    engine_state: SessionState | None,
) -> list[tuple[str, str]]:
    """Return the past transitions still needed to reach the current phase.

    Skip the transitions the engine has already applied by realigning to the
    *last* occurrence of its state in the past sequence — this also
    disambiguates CLOSED, which is both the daily start and end state. An
    unknown state is taken as CLOSED, the state the engine boots in: before
    the open that replays the day so far, and after the close it replays
    nothing, where replaying every transition would run the whole day again
    in milliseconds (Scheduler review 2026-11, C2).
    """
    current = SessionState.CLOSED if engine_state is None else engine_state
    result: list[tuple[str, str]] = []
    for hhmm, state in past:
        if state == current.value:
            result = []  # engine already here; realign to what comes after
        else:
            result.append((hhmm, state))
    return result


def _route(start: SessionState, target: SessionState) -> list[SessionState]:
    """Shortest legal transition path from ``start`` to ``target``.

    Excludes ``start``, so it is empty when the two are equal. Ties are
    broken by state name, which keeps the route deterministic.
    """
    paths: dict[SessionState, list[SessionState]] = {start: []}
    frontier = [start]
    while frontier and target not in paths:
        reached: list[SessionState] = []
        for state in frontier:
            for nxt in sorted(VALID_TRANSITIONS.get(state, set()), key=str):
                if nxt not in paths:
                    paths[nxt] = [*paths[state], nxt]
                    reached.append(nxt)
        frontier = reached
    return paths.get(target, [])


_EARLY_STATES = (SessionState.PRE_OPEN, SessionState.OPENING_AUCTION)


def _plan_catch_up(
    past: list[tuple[str, str]],
    upcoming: list[tuple[str, str, datetime]],
    engine_state: SessionState | None,
    left_over: bool = False,
) -> tuple[list[_Step], list[tuple[str, str, datetime]]]:
    """Steps that bring the engine to the current phase, and what remains.

    A ``left_over`` state (see :func:`_left_over`) is first closed by the
    shortest legal route, as that day's close would have, and today is then
    planned from CLOSED.

    An engine that is CLOSED, or in a state today's schedule has already
    passed through, is on the day's path: :func:`_catch_up_transitions`
    replays what it still lacks. Any other state means the engine is ahead
    of the schedule or left over from a day that never closed, and replaying
    from PRE_OPEN would be rejected step after step while the engine sat in
    the wrong phase. Then:

    * a not-yet-matching early phase (PRE_OPEN, OPENING_AUCTION) the day
      still has ahead is kept, and the schedule resumes after it — routing
      it back to CLOSED would have to pass through CONTINUOUS and match;
    * any other state (CONTINUOUS, CLOSING_AUCTION) is driven along the
      shortest legal route to the phase the schedule says is current.
    """
    if left_over and engine_state is not None:
        route = _route(engine_state, SessionState.CLOSED)
        log.warning(
            "engine is still in %s from an earlier day; closing that day first "
            "via %s",
            engine_state.value,
            " -> ".join(s.value for s in route),
        )
        close = [
            _Step(s.value, _no_wait, label=f"{s.value} (close the earlier day)")
            for s in route
        ]
        steps, upcoming = _plan_catch_up(past, upcoming, SessionState.CLOSED)
        return close + steps, upcoming

    if (
        engine_state is None
        or engine_state == SessionState.CLOSED
        or any(state == engine_state.value for _, state in past)
    ):
        steps = [
            _Step(state, _no_wait, label=f"{state} (catch-up, was due {hhmm})")
            for hhmm, state in _catch_up_transitions(past, engine_state)
        ]
        return steps, upcoming

    ahead = [state for _, state, _ in upcoming]
    if engine_state in _EARLY_STATES and engine_state.value in ahead:
        log.warning(
            "engine is already in %s ahead of the schedule; resuming the "
            "schedule after it",
            engine_state.value,
        )
        return [], upcoming[ahead.index(engine_state.value) + 1 :]

    target = SessionState(past[-1][1]) if past else SessionState.CLOSED
    route = _route(engine_state, target)
    log.warning(
        "engine is in %s but the schedule says %s; reconciling via %s",
        engine_state.value,
        target.value,
        " -> ".join(s.value for s in route),
    )
    steps = [
        _Step(
            s.value, _no_wait, label=f"{s.value} (reconcile from {engine_state.value})"
        )
        for s in route
    ]
    return steps, upcoming


@dataclass(frozen=True)
class _Step:
    """One transition to drive: its target state, a live wait, and a log label.

    ``at`` is the absolute local time this step is due, where one is known.
    It exists so the *previous* step can tell the engine when the next
    transition lands, which is what lets a terminal show a countdown to it
    (T-M6). A catch-up step has no meaningful due time and leaves it None.
    """

    state: str
    wait: Callable[[], float]  # seconds to wait before sending (evaluated live)
    label: str = ""
    at: datetime | None = None


@dataclass(frozen=True)
class _Resync:
    """How :func:`_run_transitions` brings a restarted engine back on schedule.

    An engine restarted with sessions enabled boots CLOSED and the transitions
    still to come today are rejected from there; without this the market
    stayed closed until the next day (Scheduler review 2026-11, C1).
    ``known`` is the engine state the steps were planned from (None when
    unknown); ``query`` asks the engine for its state now; ``plan`` returns the
    steps that bring an engine in that state to the scheduled phase, followed
    by the rest of the day.
    """

    known: SessionState | None
    query: Callable[[], SessionState | None]
    plan: Callable[[SessionState | None], list[_Step]]


def _watch_engine(sock: zmq.Socket[bytes], seconds: float, seen: list[str]) -> bool:
    """Read the SUB socket for up to ``seconds``; ``True`` on an engine start.

    Every ``session.state`` read, whoever asked for it, becomes ``seen[0]``,
    the last state the scheduler saw the engine announce: an operator's move
    is announced, an engine restart is not (it boots CLOSED in silence), which
    is how an unconfirmed transition tells the two apart.
    """
    deadline = time.monotonic() + seconds
    while True:
        # Rounded up: a remainder under 1 ms would otherwise poll(0) and spin.
        remaining_ms = math.ceil(max(0.0, (deadline - time.monotonic()) * 1000.0))
        if not sock.poll(remaining_ms):
            return False
        try:
            topic, payload = decode(sock.recv_multipart())
        except Exception:
            continue
        if topic == TOPIC_STARTUP:
            return True
        if topic == TOPIC_SESSION_STATE:
            seen[0] = str(payload.get("state", ""))


def _run_transitions(
    push_sock: PushSocket,
    confirm_sock: zmq.Socket[bytes] | None,
    is_running: Callable[[], bool],
    steps: list[_Step],
    after: _Step | None = None,
    on_closed: Callable[[], None] | None = None,
    resync: _Resync | None = None,
) -> bool:
    """Drive a sequence of transition steps through one interruptible loop.

    Shared by every run mode so there is a single, tested execution path
    (review finding A1). Returns ``True`` if every step was applied (sent,
    and confirmed when there is a confirmation socket), ``False`` if the run
    was interrupted or a step was not applied.

    ``after`` is the transition that follows the last step -- not driven
    here, only advertised as its countdown target.  ``on_closed`` is called
    once the CLOSED transition has been dispatched.

    With ``resync`` (and a confirmation socket) the loop follows an engine
    restart: an engine start read during a wait, or an unconfirmed transition
    after which the engine reports a state it never announced, replaces the
    remaining steps with ``resync.plan`` from the engine's state now.
    """
    seen = [resync.known.value if resync and resync.known else ""]
    watch: Callable[[float], bool] | None = None
    if resync is not None and confirm_sock is not None:
        watch = partial(_watch_engine, confirm_sock, seen=seen)

    def replan(reason: str) -> list[_Step] | None:
        """The steps from the engine's state now, or None to carry on."""
        assert resync is not None
        state = resync.query()
        if reason == "unconfirmed" and (state is None or state.value == seen[0]):
            # Unreachable, or where it was last seen (an operator's move is
            # announced): not a restart, and replaying would undo a decision.
            return None
        now = state.value if state is not None else SessionState.CLOSED.value
        if reason == "started":
            log.warning("engine restarted; bringing it from %s to the schedule", now)
        else:
            log.warning(
                "engine is in %s, not %s as last announced; it restarted, "
                "bringing it back to the schedule",
                now,
                seen[0] or "unknown",
            )
        seen[0] = state.value if state is not None else ""
        return resync.plan(state)

    pending = list(steps)
    fresh = True  # a newly planned list: nothing sent has described its first step
    all_applied = True
    while pending:
        step = pending.pop(0)
        if not is_running():
            log.info("Interrupted")
            return False

        # Nothing sent this run has described the first step, so the engine
        # would have no countdown target for the whole wait.
        if fresh and step.at is not None:
            _announce_next(push_sock, step.state, step.at)
        fresh = False

        label = step.label or step.state
        wait = step.wait()
        if wait > 0:
            log.info("Waiting %.0fs for %s", wait, label)
            # Re-derive the remaining wait from ``step.wait()`` on every
            # wake-up (every LIVENESS_CHUNK_SEC) rather than
            # trusting the single duration captured above, so a wall-clock
            # adjustment during a long wait is picked up promptly instead of
            # only after sleeping out a now-stale duration.
            started = _sleep_until_wallclock(
                step.wait, is_running, max_chunk=LIVENESS_CHUNK_SEC, watch=watch
            )
            if not is_running():
                log.info("Interrupted")
                return False
            if started:
                replanned = replan("started")
                if replanned is not None:
                    pending, fresh = replanned, True
                    continue

        # The step after this one is what the engine will publish as the
        # countdown target. The last step of the day has a successor only
        # when ``after`` names one, and sends nothing rather than invent one.
        following = pending[0] if pending else after
        next_state = following.state if following and following.at else ""
        next_at = _to_utc_iso(following.at) if following and following.at else ""

        log.info("-> %s", label)
        applied = _dispatch_transition(
            push_sock,
            confirm_sock,
            step.state,
            next_state=next_state,
            next_at=next_at,
            on_wake=is_running,
        )
        if applied:
            seen[0] = step.state
        else:
            all_applied = False
        # The end-of-day command needs a closed day; a close that was not
        # delivered or not confirmed is left to the next trigger.
        if on_closed is not None and step.state == SessionState.CLOSED.value:
            if applied:
                on_closed()
            else:
                log.warning("CLOSED not confirmed; --on-close not triggered")
        if not applied and resync is not None and confirm_sock is not None:
            replanned = replan("unconfirmed")
            if replanned is not None:
                pending, fresh = replanned, True

    return all_applied


def _dispatch_transition(
    push_sock: PushSocket,
    confirm_sock: zmq.Socket[bytes] | None,
    state: str,
    next_state: str = "",
    next_at: str = "",
    on_wake: Callable[[], object] | None = None,
) -> bool:
    """Send a transition and, when possible, confirm the engine applied it.

    Returns ``False`` if the send failed or the confirmation did not arrive;
    without a confirmation socket a delivered send counts as applied.
    """
    if confirm_sock is not None:
        _drain(confirm_sock)
    if not _send_transition(push_sock, state, next_state=next_state, next_at=next_at):
        return False
    if confirm_sock is None:
        return True
    if _confirm_transition(confirm_sock, state, on_wake=on_wake):
        log.debug("confirmed: engine applied %s", state)
        return True
    log.warning(
        "no confirmation that the engine applied %s "
        "(it may have been rejected or the engine is unreachable)",
        state,
    )
    return False


def _run_scheduled(
    push_sock: PushSocket,
    schedule_cfg: ScheduleConfig,
    *,
    confirm_sock: zmq.Socket[bytes] | None = None,
    is_running: Callable[[], bool] | None = None,
    gateway_id: str = SCHEDULER_GATEWAY_ID,
    country: str = DEFAULT_COUNTRY,
    daily: bool = False,
    on_closed: Callable[[], None] | None = None,
) -> None:
    """Run one day's schedule: catch up to the current phase, then time the rest.

    Engine session transitions are sequential and dependent
    (``CLOSED → PRE_OPEN → … → CLOSED``), so a scheduler that starts after some
    scheduled times have already passed must bring the engine to the correct
    current phase before waiting on future transitions (review finding H1).
    When a confirmation socket is available the scheduler first asks the engine
    for its current state so it only replays what is actually missing (A2),
    and re-plans the rest of the day the same way if the engine restarts
    (Scheduler review 2026-11, C1).

    Does nothing (no transitions sent) if today resolves to no schedule at
    all under ``schedule_cfg`` (a CLOSED weekday entry, or a bank holiday for
    ``country`` with no ``holidays:`` entry) — the exchange does not open.

    ``daily`` says this scheduler will also drive the next scheduled day, so
    the close may name that day's open as its countdown target. A single-shot
    run will not be there to perform it, and names nothing.
    """
    running = is_running or (lambda: True)

    today = _clock.now().date()
    today_schedule = resolve_day(schedule_cfg, today, country)
    if today_schedule is None:
        if is_bank_holiday(today, country):
            reason = f"bank holiday in {country}"
        else:
            reason = f"no schedule entry for {today.strftime('%A').lower()}"
        log.info(
            "%s is CLOSED today (%s); skipping today's schedule",
            today.isoformat(),
            reason,
        )
        return
    schedule = _transitions_for_day_schedule(today_schedule)

    log.debug("Schedule for today:")
    for hhmm, state in schedule:
        log.debug("%s -> %s", hhmm, state)

    # A2: recover the engine's current state so catch-up only replays the
    # transitions it still needs, instead of blindly assuming a CLOSED start.
    engine_state: SessionState | None = None
    left_over = False
    if confirm_sock is not None:
        status = _query_engine_status(
            push_sock, confirm_sock, gateway_id, on_wake=running
        )
        if status is not None:
            engine_state = status.state
            left_over = _left_over(status, today)
            log.info(
                "Engine reports current state: %s (since %s)",
                engine_state.value,
                status.since,
            )
        else:
            log.warning("could not determine engine state; assuming a " "CLOSED start")

    def plan(engine_state: SessionState | None, left_over: bool = False) -> list[_Step]:
        """Catch-up steps from ``engine_state``, then the rest of the day.

        Only the first plan can meet a ``left_over`` state: a resync follows
        an engine restart, and a restarted engine is in a state of today.
        """
        # Partition the schedule against a single "now" snapshot.
        now = _clock.now()
        past: list[tuple[str, str]] = []
        upcoming: list[tuple[str, str, datetime]] = []
        for hhmm, state in schedule:
            # Anchored to the day resolved above: the clock may have crossed
            # midnight since (the state query alone can take seconds).
            target = _time_today(hhmm, today)
            if _clock.is_past(target, now):
                past.append((hhmm, state))
            else:
                upcoming.append((hhmm, state, target))

        steps, upcoming = _plan_catch_up(past, upcoming, engine_state, left_over)
        if past and not steps:
            log.info("Engine already at the current phase; no catch-up needed")
        elif steps:
            log.info(
                "Catching up %d transition(s) to reach the current phase",
                len(steps),
            )

        for hhmm, state, target in upcoming:
            steps.append(
                _Step(
                    state, _wait_until(target), label=f"{state} (at {hhmm})", at=target
                )
            )
        return steps

    resync: _Resync | None = None
    if confirm_sock is not None:
        sub = confirm_sock

        def query() -> SessionState | None:
            return _query_engine_state(push_sock, sub, gateway_id, on_wake=running)

        resync = _Resync(engine_state, query, plan)

    after = (
        _Step(
            SessionState.PRE_OPEN.value,
            _no_wait,
            at=_next_open(schedule_cfg, today, country),
        )
        if daily
        else None
    )  # an `after` with no `at` names nothing, like a single-shot close
    if _run_transitions(
        push_sock,
        confirm_sock,
        running,
        plan(engine_state, left_over),
        after,
        on_closed,
        resync,
    ):
        log.info("All transitions sent for today.")


def _run_forever(
    push_sock: PushSocket,
    schedule_cfg: ScheduleConfig,
    confirm_sock: zmq.Socket[bytes] | None,
    is_running: Callable[[], bool],
    country: str = DEFAULT_COUNTRY,
    on_closed: Callable[[], None] | None = None,
) -> None:
    """Run the daily schedule repeatedly, once per day that has one (``--daily``).

    A CLOSED day (a weekday/weekend with no entry, or a bank holiday for
    ``country`` with none) is skipped: ``_run_scheduled`` itself is a no-op
    on a CLOSED day, and the overnight wait is extended to land on the next
    day that resolves to a schedule instead of just the next calendar day.
    The overnight wait re-derives its remaining duration from the wall clock
    every ``LIVENESS_CHUNK_SEC`` (via
    ``_sleep_until_wallclock``) instead of trusting a single monotonic
    deadline computed once, so a server time adjustment during the (possibly
    many-hour) overnight wait is picked up promptly.
    """
    while is_running():
        _run_scheduled(
            push_sock,
            schedule_cfg,
            confirm_sock=confirm_sock,
            is_running=is_running,
            country=country,
            daily=True,
            on_closed=on_closed,
        )
        if not is_running():
            break

        target_day = _next_scheduled_day(schedule_cfg, _clock.now().date(), country)
        # Covers a start after the close or on a CLOSED day, when no close
        # was sent to carry it; after a normal close it repeats the target
        # the close already set, which the engine adopts unchanged.
        next_open = _next_open(schedule_cfg, _clock.now().date(), country)
        if next_open is not None:
            _announce_next(push_sock, SessionState.PRE_OPEN.value, next_open)
        target_midnight = datetime.combine(target_day, datetime.min.time())
        log.info(
            "Day complete; sleeping until the next scheduled day (%s)",
            target_day.isoformat(),
        )
        _sleep_until_wallclock(
            _wait_until(target_midnight), is_running, max_chunk=LIVENESS_CHUNK_SEC
        )
    log.info("Stopped.")


def _run_now(
    push_sock: PushSocket,
    delay: float = NOW_MODE_DELAY,
    *,
    confirm_sock: zmq.Socket[bytes] | None = None,
    is_running: Callable[[], bool] | None = None,
) -> None:
    """Rapid-fire all transitions with short delays (for testing).

    The day only runs from CLOSED. With a confirmation socket the engine is
    asked where it is first and closed by the shortest legal route, and each
    transition is confirmed; "Done." means the engine applied all of them
    (Scheduler review 2026-11, C4).
    """
    running = is_running or (lambda: True)
    transitions = [
        SessionState.PRE_OPEN,
        SessionState.OPENING_AUCTION,
        SessionState.CONTINUOUS,
        SessionState.CLOSING_AUCTION,
        SessionState.CLOSED,
    ]

    log.info("--now mode: sending all transitions with %ss delays", delay)

    steps: list[_Step] = []
    if confirm_sock is not None:
        state = _query_engine_state(push_sock, confirm_sock, on_wake=running)
        if state is None:
            log.warning("could not determine engine state; assuming a CLOSED start")
        else:
            route = _route(state, SessionState.CLOSED)
            if route:
                log.info(
                    "engine is in %s; closing it first via %s",
                    state.value,
                    " -> ".join(s.value for s in route),
                )
            steps = [
                _Step(s.value, _no_wait, label=f"{s.value} (close first)")
                for s in route
            ]

    # The day's first transition fires at once; the rest are spaced by ``delay``.
    steps += [
        _Step(state.value, _no_wait if i == 0 else _fixed_wait(delay))
        for i, state in enumerate(transitions)
    ]

    if _run_transitions(push_sock, confirm_sock, running, steps):
        log.info("Done.")


def _open_confirm_socket() -> zmq.Socket[bytes]:
    """SUB to the engine's session broadcasts, its reply topic and its starts.

    ``session.state`` confirms transitions (M3), the session-status reply
    gives the current state (A2), and ``system.startup`` tells of an engine
    restart (Scheduler review 2026-11, C1).
    """
    status_topic = topic_session_status(SCHEDULER_GATEWAY_ID)
    sock = make_subscriber(
        ENGINE_PUB_ADDR,
        TOPIC_SESSION_STATE,
        status_topic,
        TOPIC_STARTUP,
    )
    # Let the SUB subscription take effect before the state query
    # (slow-joiner — review finding L5).
    time.sleep(SUB_CONNECT_SETTLE_SEC)
    # Logs the topic actually subscribed rather than a second copy
    # of the string: design section 27.6, where `pm-dc-spy` could
    # report a subscription the process had not made.
    log.debug(
        "subscribed to %s, %s and %s",
        TOPIC_SESSION_STATE,
        status_topic,
        TOPIC_STARTUP,
    )
    return sock


def _speed(value: str) -> float:
    """``--speed``: a finite factor above 0 (nan passed ``<= 0``, C5)."""
    factor = float(value)
    if not math.isfinite(factor) or factor <= 0:
        raise argparse.ArgumentTypeError(f"must be a finite number > 0, not {value}")
    return factor


def _delay_sec(value: str) -> float:
    """``--on-close-delay``: finite seconds, not negative."""
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number >= 0, not {value}")
    return seconds


def _command(value: str) -> str:
    """``--on-close``: text that splits into a program and its arguments."""
    try:
        argv = shlex.split(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"cannot split {value!r}: {exc}") from None
    if not argv:
        raise argparse.ArgumentTypeError("needs a command, got nothing")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher session scheduler")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help=(
            "Close the engine first if it is not CLOSED, then rapid-fire all "
            "transitions (for testing)"
        ),
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help=(
            "Run continuously, repeating the schedule every working day "
            "(weekends and bank holidays for the configured country are "
            "skipped)"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help=(
            "Seconds between transitions in --now mode "
            f"(default: {NOW_MODE_DELAY}; ignored outside --now)"
        ),
    )
    parser.add_argument(
        "--speed",
        type=_speed,
        # argparse converts a string default with ``type``.
        default=os.environ.get("EDUMATCHER_SCHEDULER_SPEED") or None,
        metavar="F",
        help=(
            "Compressed mode (with --daily): simulated time runs F times "
            "faster than the wall clock (default: EDUMATCHER_SCHEDULER_SPEED)"
        ),
    )
    parser.add_argument(
        "--start",
        type=datetime.fromisoformat,
        default=os.environ.get("EDUMATCHER_SCHEDULER_START") or None,
        metavar="YYYY-MM-DDTHH:MM",
        help=(
            "Compressed mode: session-local time the simulated clock starts at "
            "(default: EDUMATCHER_SCHEDULER_START, else now)"
        ),
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help=(
            "Do not query/confirm session state via the engine (nor follow an "
            "engine restart)"
        ),
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Explicit WARNING log level (the default)",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--on-close",
        type=_command,
        default=None,
        metavar="COMMAND",
        help=(
            "Command started after each day's CLOSED transition (and once at "
            "start-up), e.g. 'pm-eod run --pending'; runs detached, one at a time"
        ),
    )
    parser.add_argument(
        "--on-close-delay",
        type=_delay_sec,
        default=30.0,
        metavar="SECONDS",
        help="Wait this long after CLOSED before starting --on-close (default: 30)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    if getattr(args, "log_level", None):
        level_name = str(args.log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif int(getattr(args, "verbose", 0)) >= 2:
        level = logging.DEBUG
    elif int(getattr(args, "verbose", 0)) == 1:
        level = logging.INFO
    elif bool(getattr(args, "quiet", False)):
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


@exit_on_config_error
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    log_level = _configure_logging(args)
    log.info(
        "starting pm-scheduler with log level %s",
        logging.getLevelName(log_level),
    )

    # --delay only applies to --now mode; warn rather than silently ignore it
    # (review finding L4).
    if args.delay is not None and not args.now:
        log.warning("--delay is ignored outside --now mode")
    now_mode_delay = args.delay if args.delay is not None else NOW_MODE_DELAY

    speed = 1.0 if args.speed is None else args.speed
    if args.speed is not None or args.start is not None:
        if not args.daily:
            parser.error("--speed and --start need --daily")
    if args.now and args.daily:
        parser.error("--now cannot be combined with --daily, --speed or --start")

    if args.on_close is not None and args.now:
        log.warning("--on-close is ignored in --now mode")
    close_hook = (
        _CloseHook(args.on_close, args.on_close_delay)
        if args.on_close is not None and not args.now
        else None
    )

    running = True

    def _stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Health beacon (operator dashboard §8.5). Every wait in this process
    # calls _is_running() on each wake-up, so that is where the main loop
    # ticks; no wait sleeps longer than LIVENESS_CHUNK_SEC between calls.
    reporter = HealthReporter.start_from_compiled_config(_CLIENT_NAME)

    def _is_running() -> bool:
        if reporter is not None:
            reporter.tick_and_publish(_metric_samples)
        return running

    push_sock = make_pusher(ENGINE_PULL_ADDR)
    # Bound the send timeout and linger so the scheduler can never block forever
    # when the engine is not consuming (review finding H2).
    push_sock.setsockopt(zmq.SNDTIMEO, SEND_TIMEOUT_MS)
    push_sock.setsockopt(zmq.LINGER, LINGER_MS)
    log.debug(
        "PUSH -> engine at %s (send timeout %dms, linger %dms)",
        ENGINE_PULL_ADDR,
        SEND_TIMEOUT_MS,
        LINGER_MS,
    )
    # No connect sleep for the PUSH socket: PUSH/PULL queues messages until the
    # peer connects and SNDTIMEO bounds the wait, so a sleep here is unnecessary
    # (review finding L5).

    try:
        if args.now:
            now_confirm = None if args.no_confirm else _open_confirm_socket()
            try:
                _run_now(
                    push_sock,
                    now_mode_delay,
                    confirm_sock=now_confirm,
                    is_running=_is_running,
                )
            finally:
                if now_confirm is not None:
                    now_confirm.close()
        else:
            # Schedule and country both come from the compiled artifact, so
            # pm-scheduler and pm-engine can no longer disagree about the
            # trading day. `country` in particular was invisible to the engine
            # loader until now, which meant nothing but this process had ever
            # read a documented, generated field.
            from edumatcher.config_artifact import load_compiled_config

            compiled = load_compiled_config()
            if compiled is None:
                # Nothing deployed. Running a timetable the engine has never
                # seen is worse than not starting, so this is fatal here even
                # though absence is tolerable for processes that only need
                # their logging settings.
                log.critical(
                    "FATAL: no compiled configuration at %s — "
                    "run pm-config-deploy to install one",
                    COMPILED_CONFIG_FILE,
                )
                sys.exit(1)

            engine_cfg = compiled.engine
            if not engine_cfg.sessions_enabled:
                # The engine refuses every transition when sessions are off,
                # so a schedule would only log unconfirmed transitions. The
                # bundled examples run this way under profiles that start
                # pm-scheduler, so idle (still beaconing) instead of exiting.
                log.info(
                    "sessions are disabled in the deployed configuration "
                    "(sessions_enabled: false); no transitions will be sent"
                )
                while _is_running():
                    time.sleep(LIVENESS_CHUNK_SEC)
                return
            global _clock
            _clock = _Clock(session_timezone=engine_cfg.locale.session_timezone)
            if args.speed is not None or args.start is not None:
                _clock = _Clock(
                    speed,
                    args.start or _clock.now(),
                    session_timezone=engine_cfg.locale.session_timezone,
                )
                log.info(
                    "compressed mode: x%g from simulated %s",
                    speed,
                    _clock.now().isoformat(),
                )
            log.info("Using session timezone %s", _clock.timezone)
            schedule_cfg = (
                DEFAULT_SCHEDULE if engine_cfg.schedule is None else engine_cfg.schedule
            )
            country = engine_cfg.locale.country
            if not _is_supported_country(country):
                log.warning(
                    "unrecognised country %r for holiday calendar; using default %r",
                    country,
                    DEFAULT_COUNTRY,
                )
                country = DEFAULT_COUNTRY
            log.info("Using country %r for working-day/holiday calendar", country)

            # Refuse to start on a schedule the engine could never follow (M1).
            errors = _validate_schedule_config(schedule_cfg)
            if errors:
                for err in errors:
                    log.critical("FATAL: invalid schedule: %s", err)
                sys.exit(1)

            # Subscribe to the engine's session.state broadcasts (to confirm
            # transitions, M3), to our session-status reply topic (to recover
            # the current state on startup, A2) and to its starts (C1).
            confirm_sock = None if args.no_confirm else _open_confirm_socket()

            try:
                if close_hook is not None:
                    close_hook()  # settle any day that closed while we were down
                if args.daily:
                    _run_forever(
                        push_sock,
                        schedule_cfg,
                        confirm_sock,
                        _is_running,
                        country=country,
                        on_closed=close_hook,
                    )
                else:
                    _run_scheduled(
                        push_sock,
                        schedule_cfg,
                        confirm_sock=confirm_sock,
                        is_running=_is_running,
                        country=country,
                        on_closed=close_hook,
                    )
            finally:
                if close_hook is not None:
                    # A single-shot run exits right after the close: let the
                    # command finish.  A daily run is being stopped: do not hold
                    # the shutdown for it.
                    if args.daily:
                        close_hook.stop()
                    else:
                        close_hook.wait()
                if confirm_sock is not None:
                    confirm_sock.close()
    finally:
        push_sock.close()
        if reporter is not None:
            reporter.stop()


if __name__ == "__main__":
    main()
