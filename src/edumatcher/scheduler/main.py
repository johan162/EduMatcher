"""
Session Scheduler — drives the engine through daily trading phases.

Reads a schedule (from the deployed engine config, or default times) and sends
``session.transition`` messages to the engine at the configured wall-clock
times via a PUSH socket. It runs as a closed-loop driver:

  - On startup it queries the engine's current session state and only replays
    the transitions still needed to reach the correct current phase.
  - After each transition it listens to the engine's ``session.state``
    broadcast to confirm the change was actually applied.

Usage:
  poetry run pm-scheduler                  # run today's schedule once, then exit
  poetry run pm-scheduler --daily          # run continuously, once per day
  poetry run pm-scheduler --now            # rapid-fire all transitions (for testing)
  poetry run pm-scheduler --no-confirm     # do not query/confirm via the engine
  poetry run pm-scheduler --verbose        # DEBUG-level diagnostics

Logging:
  Operational messages go through the ``logging`` module (configured at the
  process entry point, mirroring pm-engine). The default level is INFO; pass
  ``--verbose`` / ``-v`` to drop to DEBUG for connection, schedule-table and
  state-query diagnostics.

Same-day behavior:
  By default the scheduler drives *today's* timeline and then exits. If it is
  started after some scheduled times have already passed, it brings the engine
  to the correct current phase (engine session states are sequential and
  dependent). Use ``--daily`` to keep the process running and repeat the
  schedule every working day.

Typical daily sequence:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED

Working days:
  The scheduler only drives the daily schedule on working days — weekends and
  bank holidays for the configured ``country`` (top-level ``country:`` field in
  the config YAML, default ``"Sweden"``) are skipped entirely via the
  ``python-holidays`` package. ``--daily`` mode waits through non-working days
  and resumes on the next one; a single-shot run started on a non-working day
  does nothing.

Wall-clock re-checking:
  Long waits (until a scheduled time, or overnight between trading days) are
  never slept in one long ``time.sleep`` call. Instead the scheduler wakes at
  least every ``WALLCLOCK_RECHECK_SEC`` seconds and re-derives the remaining
  wait from the current wall-clock time, so a server time adjustment (NTP
  sync, manual change, DST) is picked up promptly instead of only after a
  single long sleep started under stale assumptions.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import holidays
import zmq

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
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_session_state_request_msg,
    make_session_transition_msg,
)
from edumatcher.engine.config_loader import DEFAULT_COUNTRY, ScheduleConfig
from edumatcher.models.session import VALID_TRANSITIONS, SessionState

_CLIENT_NAME = "pm-scheduler"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# Operational logging goes through the logging module; the process entry point
# (main()) configures the handler/level, the library installs no handlers
# (mirrors the engine's setup — review finding L3).
log = logging.getLogger(__name__)

# Default schedule (HH:MM) — used when no config file provides one
DEFAULT_SCHEDULE: list[tuple[str, str]] = [
    ("09:00", SessionState.PRE_OPEN.value),
    ("09:25", SessionState.OPENING_AUCTION.value),
    ("09:30", SessionState.CONTINUOUS.value),
    ("16:00", SessionState.CLOSING_AUCTION.value),
    ("16:05", SessionState.CLOSED.value),
]

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

# Long waits (until a scheduled time, or overnight between trading days) are
# re-derived from the wall clock at least this often, so the scheduler picks
# up server time adjustments (NTP sync, manual change, DST) promptly instead
# of trusting a single duration computed once at the start of a long sleep.
WALLCLOCK_RECHECK_SEC = 30.0


def _hhmm_to_minutes(hhmm: str) -> int:
    """Return minutes-since-midnight for a normalized ``"HH:MM"`` string."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _schedule_from_config(cfg: ScheduleConfig) -> list[tuple[str, str]]:
    """Map a compiled ScheduleConfig onto the engine's transition sequence.

    The times are already canonical ``HH:MM`` — ``load_engine_config`` runs
    them through ``normalize_hhmm`` — so there is nothing left to validate or
    recover here.
    """
    return [
        (cfg.pre_open, SessionState.PRE_OPEN.value),
        (cfg.opening_auction_start, SessionState.OPENING_AUCTION.value),
        (cfg.continuous_start, SessionState.CONTINUOUS.value),
        (cfg.closing_auction_start, SessionState.CLOSING_AUCTION.value),
        (cfg.closing_auction_end, SessionState.CLOSED.value),
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


def _time_today(hhmm: str) -> datetime:
    """Parse a validated ``"HH:MM"`` string into a naive datetime for today.

    Used for classifying past/upcoming entries and for log labels. Wall-clock
    wait *durations* are computed by :func:`_seconds_until_local`, which is
    DST-aware; a naive subtraction here would only ever misclassify an entry by
    an hour right at a DST boundary.
    """
    h, m = hhmm.split(":")
    now = datetime.now()
    return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def _seconds_until_local(target: datetime) -> float:
    """Seconds from now until the local wall-clock ``target`` (DST-aware).

    Resolves the target's wall-clock components to epoch seconds via the OS
    timezone database (``time.mktime`` with ``tm_isdst=-1``), so the wait is
    correct even across a daylight-saving transition. A plain naive subtraction
    can be off by an hour on those days (review finding L1).
    """
    tm = (
        target.year,
        target.month,
        target.day,
        target.hour,
        target.minute,
        target.second,
        0,  # tm_wday (ignored by mktime)
        0,  # tm_yday (ignored by mktime)
        -1,  # tm_isdst = -1 → let the OS resolve DST
    )
    return time.mktime(tm) - time.time()


def _holiday_calendar(country: str) -> holidays.HolidayBase:
    """Return the ``python-holidays`` calendar for ``country``.

    Callers should pass a country already validated by
    :func:`_is_supported_country` (``main`` guarantees this) —
    unrecognised countries raise ``NotImplementedError`` here.
    """
    return holidays.country_holidays(country)


def _is_working_day(day: date, country: str) -> bool:
    """Return ``True`` if ``day`` is neither a weekend nor a bank holiday.

    Weekends (Saturday/Sunday) are always excluded regardless of whether the
    country's calendar also lists them as observances. Bank holidays are
    looked up in the ``python-holidays`` calendar for ``country``.
    """
    if day.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return day not in _holiday_calendar(country)


def _next_working_day(day: date, country: str) -> date:
    """Return the next working day strictly after ``day`` for ``country``."""
    candidate = day + timedelta(days=1)
    # Bounded: a bank-holiday calendar can never plausibly cover an entire
    # year of consecutive non-working days, so this loop always terminates
    # well before the guard trips.
    for _ in range(366):
        if _is_working_day(candidate, country):
            return candidate
        candidate += timedelta(days=1)
    return candidate


def _sleep_until_wallclock(
    remaining_seconds: Callable[[], float],
    is_running: Callable[[], bool],
    max_chunk: float = WALLCLOCK_RECHECK_SEC,
) -> None:
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
    ``time.sleep`` call, so the scheduler never sleeps more than
    ``WALLCLOCK_RECHECK_SEC`` (30s) at a stretch.
    """
    while is_running():
        remaining = remaining_seconds()
        if remaining <= 0:
            return
        time.sleep(max(0.0, min(max_chunk, remaining)))


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


def _wait_until(target: datetime) -> Callable[[], float]:
    """Return a pre-send wait that counts down to an absolute local time."""
    return lambda: _seconds_until_local(target)


def _send_transition(push_sock: zmq.Socket[bytes], state: str) -> bool:
    """Send one ``session.transition``; return ``False`` if not delivered.

    The PUSH socket carries a bounded send timeout (finding H2), so a send
    raises ``zmq.Again`` instead of blocking forever when the engine is not
    consuming. Any other ZMQ error (e.g. a terminated context) is caught too so
    a transport failure degrades gracefully instead of crashing the scheduler
    (review finding L7).
    """
    try:
        push_sock.send_multipart(make_session_transition_msg(state))
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


def _confirm_transition(
    confirm_sock: zmq.Socket[bytes],
    expected_state: str,
    timeout_ms: int = CONFIRM_TIMEOUT_MS,
) -> bool:
    """Wait for the engine to broadcast ``session.state == expected_state``.

    Returns ``True`` once the applied-state broadcast is observed, or ``False``
    if it does not arrive within ``timeout_ms`` (engine rejected the transition
    or is unreachable). Best-effort: PUB/SUB gives no delivery guarantee.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000.0))
        if not confirm_sock.poll(timeout=remaining_ms):
            break
        try:
            topic, payload = decode(confirm_sock.recv_multipart())
        except Exception:
            continue
        if topic == "session.state" and str(payload.get("state", "")) == expected_state:
            return True
    return False


def _query_engine_state(
    push_sock: zmq.Socket[bytes],
    sub_sock: zmq.Socket[bytes],
    gateway_id: str = SCHEDULER_GATEWAY_ID,
    timeout_ms: int = QUERY_TIMEOUT_MS,
) -> SessionState | None:
    """Ask the engine for its current session state and wait for the reply.

    Sends ``system.session_state_request`` and reads the matching
    ``system.session_status.<ID>`` broadcast (review finding A2). Returns
    ``None`` if the engine does not answer within ``timeout_ms`` or the reply
    is unusable — the caller then falls back to assuming a CLOSED start.
    """
    reply_topic = f"system.session_status.{gateway_id.upper()}"
    try:
        push_sock.send_multipart(make_session_state_request_msg(gateway_id))
    except zmq.ZMQError as exc:
        log.debug("session-state request could not be sent: %s", exc)
        return None

    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        remaining_ms = int(max(0.0, (deadline - time.monotonic()) * 1000.0))
        if not sub_sock.poll(timeout=remaining_ms):
            break
        try:
            topic, payload = decode(sub_sock.recv_multipart())
        except Exception:
            continue
        if topic == reply_topic:
            try:
                return SessionState(str(payload.get("state", "")))
            except ValueError:
                return None
    return None


def _catch_up_transitions(
    past: list[tuple[str, str]],
    engine_state: SessionState | None,
) -> list[tuple[str, str]]:
    """Return the past transitions still needed to reach the current phase.

    When the engine's current state is known (finding A2), skip the transitions
    it has already applied by realigning to the *last* occurrence of that state
    in the past sequence — this also disambiguates CLOSED, which is both the
    daily start and end state. When unknown, replay every past transition
    (assumes the engine booted CLOSED — the H1 fallback).
    """
    if engine_state is None:
        return list(past)
    result: list[tuple[str, str]] = []
    for hhmm, state in past:
        if state == engine_state.value:
            result = []  # engine already here; realign to what comes after
        else:
            result.append((hhmm, state))
    return result


@dataclass(frozen=True)
class _Step:
    """One transition to drive: its target state, a live wait, and a log label."""

    state: str
    wait: Callable[[], float]  # seconds to wait before sending (evaluated live)
    label: str = ""


def _run_transitions(
    push_sock: zmq.Socket[bytes],
    confirm_sock: zmq.Socket[bytes] | None,
    is_running: Callable[[], bool],
    steps: list[_Step],
) -> bool:
    """Drive a sequence of transition steps through one interruptible loop.

    Shared by every run mode so there is a single, tested execution path
    (review finding A1). Returns ``True`` if all steps completed, or ``False``
    if the run was interrupted.
    """
    for step in steps:
        if not is_running():
            log.info("Interrupted")
            return False

        label = step.label or step.state
        wait = step.wait()
        if wait > 0:
            log.info("Waiting %.0fs for %s", wait, label)
            # Re-derive the remaining wait from ``step.wait()`` on every
            # wake-up (at least every WALLCLOCK_RECHECK_SEC) rather than
            # trusting the single duration captured above, so a wall-clock
            # adjustment during a long wait is picked up promptly instead of
            # only after sleeping out a now-stale duration.
            _sleep_until_wallclock(step.wait, is_running)
            if not is_running():
                log.info("Interrupted")
                return False

        log.info("-> %s", label)
        _dispatch_transition(push_sock, confirm_sock, step.state)

    return True


def _dispatch_transition(
    push_sock: zmq.Socket[bytes],
    confirm_sock: zmq.Socket[bytes] | None,
    state: str,
) -> None:
    """Send a transition and, when possible, confirm the engine applied it."""
    if not _send_transition(push_sock, state):
        return
    if confirm_sock is None:
        return
    if _confirm_transition(confirm_sock, state):
        log.debug("confirmed: engine applied %s", state)
    else:
        log.warning(
            "no confirmation that the engine applied %s "
            "(it may have been rejected or the engine is unreachable)",
            state,
        )


def _run_scheduled(
    push_sock: zmq.Socket[bytes],
    schedule: list[tuple[str, str]],
    *,
    confirm_sock: zmq.Socket[bytes] | None = None,
    is_running: Callable[[], bool] | None = None,
    gateway_id: str = SCHEDULER_GATEWAY_ID,
    country: str = DEFAULT_COUNTRY,
) -> None:
    """Run one day's schedule: catch up to the current phase, then time the rest.

    Engine session transitions are sequential and dependent
    (``CLOSED → PRE_OPEN → … → CLOSED``), so a scheduler that starts after some
    scheduled times have already passed must bring the engine to the correct
    current phase before waiting on future transitions (review finding H1).
    When a confirmation socket is available the scheduler first asks the engine
    for its current state so it only replays what is actually missing (A2).

    Does nothing (no transitions sent) if today is a weekend or a bank
    holiday for ``country`` — the exchange does not open on non-working days.
    """
    running = is_running or (lambda: True)

    today = datetime.now().date()
    if not _is_working_day(today, country):
        log.info(
            "%s is not a working day for %s (weekend or bank holiday); "
            "skipping today's schedule",
            today.isoformat(),
            country,
        )
        return

    log.debug("Schedule for today:")
    for hhmm, state in schedule:
        log.debug("%s -> %s", hhmm, state)

    # A2: recover the engine's current state so catch-up only replays the
    # transitions it still needs, instead of blindly assuming a CLOSED start.
    engine_state: SessionState | None = None
    if confirm_sock is not None:
        engine_state = _query_engine_state(push_sock, confirm_sock, gateway_id)
        if engine_state is not None:
            log.info("Engine reports current state: %s", engine_state.value)
        else:
            log.warning("could not determine engine state; assuming a " "CLOSED start")

    # Partition the schedule against a single "now" snapshot.
    now = datetime.now()
    past: list[tuple[str, str]] = []
    upcoming: list[tuple[str, str, datetime]] = []
    for hhmm, state in schedule:
        target = _time_today(hhmm)
        if target < now:
            past.append((hhmm, state))
        else:
            upcoming.append((hhmm, state, target))

    catch_up = _catch_up_transitions(past, engine_state)
    if past and not catch_up:
        log.info("Engine already at the current phase; no catch-up needed")
    elif catch_up:
        log.info(
            "Catching up %d transition(s) to reach the current phase",
            len(catch_up),
        )

    steps: list[_Step] = []
    for hhmm, state in catch_up:
        steps.append(
            _Step(state, _no_wait, label=f"{state} (catch-up, was due {hhmm})")
        )
    for hhmm, state, target in upcoming:
        steps.append(_Step(state, _wait_until(target), label=f"{state} (at {hhmm})"))

    if _run_transitions(push_sock, confirm_sock, running, steps):
        log.info("All transitions sent for today.")


def _run_forever(
    push_sock: zmq.Socket[bytes],
    schedule: list[tuple[str, str]],
    confirm_sock: zmq.Socket[bytes] | None,
    is_running: Callable[[], bool],
    country: str = DEFAULT_COUNTRY,
) -> None:
    """Run the daily schedule repeatedly, once per working day (``--daily``).

    Weekends and bank holidays for ``country`` are skipped: ``_run_scheduled``
    itself is a no-op on a non-working day, and the overnight wait is
    extended to land on the next working day instead of just the next
    calendar day. The overnight wait re-derives its remaining duration from
    the wall clock at least every ``WALLCLOCK_RECHECK_SEC`` seconds (via
    ``_sleep_until_wallclock``) instead of trusting a single monotonic
    deadline computed once, so a server time adjustment during the (possibly
    many-hour) overnight wait is picked up promptly.
    """
    while is_running():
        _run_scheduled(
            push_sock,
            schedule,
            confirm_sock=confirm_sock,
            is_running=is_running,
            country=country,
        )
        if not is_running():
            break

        target_day = _next_working_day(datetime.now().date(), country)
        target_midnight = datetime.combine(target_day, datetime.min.time())
        log.info(
            "Day complete; sleeping until the next working day (%s)",
            target_day.isoformat(),
        )
        _sleep_until_wallclock(_wait_until(target_midnight), is_running)
    log.info("Stopped.")


def _run_now(
    push_sock: zmq.Socket[bytes],
    delay: float = NOW_MODE_DELAY,
    *,
    is_running: Callable[[], bool] | None = None,
) -> None:
    """Rapid-fire all transitions with short delays (for testing)."""
    running = is_running or (lambda: True)
    transitions = [
        SessionState.PRE_OPEN,
        SessionState.OPENING_AUCTION,
        SessionState.CONTINUOUS,
        SessionState.CLOSING_AUCTION,
        SessionState.CLOSED,
    ]

    log.info("--now mode: sending all transitions with %ss delays", delay)

    # First transition fires immediately; the rest are spaced by ``delay``.
    steps = [
        _Step(state.value, _no_wait if i == 0 else _fixed_wait(delay))
        for i, state in enumerate(transitions)
    ]

    if _run_transitions(push_sock, None, running, steps):
        log.info("Done.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher session scheduler")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-scheduler")
    parser.add_argument(
        "--now",
        action="store_true",
        help="Rapid-fire all transitions immediately (for testing)",
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
        "--no-confirm",
        action="store_true",
        help="Do not query/confirm session state via the engine",
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
        help="Reduce log output to warnings/errors",
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


def main() -> None:
    parser = _build_parser()
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

    running = True

    def _stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    def _is_running() -> bool:
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
            _run_now(push_sock, now_mode_delay, is_running=_is_running)
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
                log.error(
                    "FATAL: no compiled configuration at %s — "
                    "run pm-config-deploy to install one",
                    COMPILED_CONFIG_FILE,
                )
                sys.exit(1)

            engine_cfg = compiled.engine
            schedule = (
                DEFAULT_SCHEDULE
                if engine_cfg.schedule is None
                else _schedule_from_config(engine_cfg.schedule)
            )
            country = engine_cfg.country
            if not _is_supported_country(country):
                log.warning(
                    "unrecognised country %r for holiday calendar; using default %r",
                    country,
                    DEFAULT_COUNTRY,
                )
                country = DEFAULT_COUNTRY
            log.info("Using country %r for working-day/holiday calendar", country)

            # Refuse to start on a schedule the engine could never follow (M1).
            errors = _validate_schedule(schedule)
            if errors:
                for err in errors:
                    log.error("FATAL: invalid schedule: %s", err)
                sys.exit(1)

            # Subscribe to the engine's session.state broadcasts (to confirm
            # transitions, M3) and to our session-status reply topic (to recover
            # the current state on startup, A2).
            confirm_sock: zmq.Socket[bytes] | None = None
            if not args.no_confirm:
                confirm_sock = make_subscriber(
                    ENGINE_PUB_ADDR,
                    "session.state",
                    f"system.session_status.{SCHEDULER_GATEWAY_ID}",
                )
                # Let the SUB subscription take effect before the state query
                # (slow-joiner — review finding L5).
                time.sleep(SUB_CONNECT_SETTLE_SEC)
                log.debug(
                    "subscribed to session.state and " "system.session_status.%s",
                    SCHEDULER_GATEWAY_ID,
                )

            try:
                if args.daily:
                    _run_forever(
                        push_sock,
                        schedule,
                        confirm_sock,
                        _is_running,
                        country=country,
                    )
                else:
                    _run_scheduled(
                        push_sock,
                        schedule,
                        confirm_sock=confirm_sock,
                        is_running=_is_running,
                        country=country,
                    )
            finally:
                if confirm_sock is not None:
                    confirm_sock.close()
    finally:
        push_sock.close()


if __name__ == "__main__":
    main()
