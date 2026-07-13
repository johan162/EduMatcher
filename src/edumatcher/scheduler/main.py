"""
Session Scheduler — drives the engine through daily trading phases.

Reads a schedule (either from --config YAML or default times) and sends
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
  poetry run pm-scheduler --config my.yaml # custom config file
  poetry run pm-scheduler --no-confirm     # do not query/confirm via the engine

Same-day behavior:
  By default the scheduler drives *today's* timeline and then exits. If it is
  started after some scheduled times have already passed, it brings the engine
  to the correct current phase (engine session states are sequential and
  dependent). Use ``--daily`` to keep the process running and repeat the
  schedule every calendar day.

Typical daily sequence:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import zmq

from edumatcher.config import ENGINE_CONFIG_FILE, ENGINE_PUB_ADDR, ENGINE_PULL_ADDR
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import (
    decode,
    make_session_state_request_msg,
    make_session_transition_msg,
)
from edumatcher.models.session import VALID_TRANSITIONS, SessionState

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

# Identifier the scheduler uses when talking to the engine (request/reply
# replies come back on ``system.session_status.<ID>``).
SCHEDULER_GATEWAY_ID = "SCHEDULER"

# The engine boots CLOSED when the scheduler owns session state
# (sessions_enabled=true), so a schedule must be a valid transition path
# starting from CLOSED.
_ENGINE_START_STATE = SessionState.CLOSED


def _normalize_hhmm(raw: object) -> str | None:
    """Normalize a schedule time to canonical ``"HH:MM"``, or ``None`` if invalid.

    Accepts:
      - ``"HH:MM"`` strings (quoted in YAML), validated as a real 24-hour time.
      - integers, which PyYAML produces for *unquoted* sexagesimal values such
        as ``9:30`` (parsed as ``9 * 60 + 30 == 570`` minutes past midnight).
        These are interpreted as minutes-since-midnight and recovered so the
        documented — but unquoted — config form does not crash the scheduler
        (review finding H3).

    Out-of-range or malformed values return ``None`` so the caller can skip
    them with a warning instead of crashing later in ``_time_today``.
    """
    # bool is a subclass of int — reject it explicitly.
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        if 0 <= raw < 24 * 60:
            return f"{raw // 60:02d}:{raw % 60:02d}"
        return None
    if isinstance(raw, str):
        parts = raw.strip().split(":")
        if len(parts) != 2:
            return None
        hh, mm = parts
        if not (hh.isdigit() and mm.isdigit()):
            return None
        hours, minutes = int(hh), int(mm)
        if 0 <= hours < 24 and 0 <= minutes < 60:
            return f"{hours:02d}:{minutes:02d}"
        return None
    return None


def _hhmm_to_minutes(hhmm: str) -> int:
    """Return minutes-since-midnight for a normalized ``"HH:MM"`` string."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _load_schedule(config_path: Path | None) -> list[tuple[str, str]]:
    """Load schedule from YAML config or fall back to defaults."""
    if config_path and config_path.exists():
        try:
            import yaml

            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            sched = data.get("schedule")
            if sched:
                mapping = [
                    ("pre_open", SessionState.PRE_OPEN.value),
                    ("opening_auction_start", SessionState.OPENING_AUCTION.value),
                    ("continuous_start", SessionState.CONTINUOUS.value),
                    ("closing_auction_start", SessionState.CLOSING_AUCTION.value),
                    ("closing_auction_end", SessionState.CLOSED.value),
                ]
                result: list[tuple[str, str]] = []
                for key, state in mapping:
                    raw_time = sched.get(key)
                    if raw_time is None:
                        continue
                    # Validate/normalize so malformed or unquoted (sexagesimal)
                    # times never crash scheduling downstream (finding H3).
                    normalized = _normalize_hhmm(raw_time)
                    if normalized is None:
                        print(
                            "[SCHEDULER] Warning: ignoring invalid schedule time "
                            f"for {key!r}: {raw_time!r} "
                            "(times must be quoted, e.g. '09:30')",
                            file=sys.stderr,
                        )
                        continue
                    result.append((normalized, state))
                if result:
                    print(f"[SCHEDULER] Loaded schedule from {config_path}")
                    return result
        except Exception as exc:
            print(
                f"[SCHEDULER] Warning: could not load schedule from {config_path}: {exc}",
                file=sys.stderr,
            )
    return DEFAULT_SCHEDULE


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
    """Parse a validated ``"HH:MM"`` string into a datetime for today.

    Callers must pass a normalized value (see :func:`_normalize_hhmm`); the
    schedule loader guarantees this, so this helper stays deliberately simple.
    """
    h, m = hhmm.split(":")
    now = datetime.now()
    return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def _seconds_until_next_day() -> float:
    """Seconds from now until 00:00 tomorrow (local time)."""
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow - now).total_seconds()


def _interruptible_sleep(seconds: float, is_running: Callable[[], bool]) -> None:
    """Sleep up to ``seconds`` in small increments, stopping early if requested."""
    deadline = time.monotonic() + seconds
    while is_running() and time.monotonic() < deadline:
        time.sleep(max(0.0, min(1.0, deadline - time.monotonic())))


def _no_wait() -> float:
    """A pre-send wait of zero (used for immediate/catch-up transitions)."""
    return 0.0


def _fixed_wait(seconds: float) -> Callable[[], float]:
    """Return a pre-send wait of a fixed number of seconds (used by --now)."""
    return lambda: seconds


def _wait_until(target: datetime) -> Callable[[], float]:
    """Return a pre-send wait that counts down to an absolute time."""
    return lambda: (target - datetime.now()).total_seconds()


def _send_transition(push_sock: zmq.Socket[bytes], state: str) -> bool:
    """Send one ``session.transition``; return ``False`` if not delivered.

    The PUSH socket carries a bounded send timeout (finding H2), so a send
    raises ``zmq.Again`` instead of blocking forever when the engine is not
    consuming. We log and continue rather than hang or crash.
    """
    try:
        push_sock.send_multipart(make_session_transition_msg(state))
        return True
    except zmq.Again:
        print(
            "[SCHEDULER] Warning: engine not reachable; "
            f"transition to {state} was not delivered",
            file=sys.stderr,
        )
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
    except zmq.Again:
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
            print("[SCHEDULER] Interrupted")
            return False

        label = step.label or step.state
        wait = step.wait()
        if wait > 0:
            print(f"[SCHEDULER] Waiting {wait:.0f}s for {label}")
            _interruptible_sleep(wait, is_running)
            if not is_running():
                print("[SCHEDULER] Interrupted")
                return False

        print(f"[SCHEDULER] → {label}")
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
        print(f"[SCHEDULER]   confirmed: engine applied {state}")
    else:
        print(
            f"[SCHEDULER]   WARNING: no confirmation that the engine applied {state} "
            "(it may have been rejected or the engine is unreachable)",
            file=sys.stderr,
        )


def _run_scheduled(
    push_sock: zmq.Socket[bytes],
    schedule: list[tuple[str, str]],
    *,
    confirm_sock: zmq.Socket[bytes] | None = None,
    is_running: Callable[[], bool] | None = None,
    gateway_id: str = SCHEDULER_GATEWAY_ID,
) -> None:
    """Run one day's schedule: catch up to the current phase, then time the rest.

    Engine session transitions are sequential and dependent
    (``CLOSED → PRE_OPEN → … → CLOSED``), so a scheduler that starts after some
    scheduled times have already passed must bring the engine to the correct
    current phase before waiting on future transitions (review finding H1).
    When a confirmation socket is available the scheduler first asks the engine
    for its current state so it only replays what is actually missing (A2).
    """
    running = is_running or (lambda: True)

    print("[SCHEDULER] Schedule for today:")
    for hhmm, state in schedule:
        print(f"  {hhmm}  → {state}")
    print()

    # A2: recover the engine's current state so catch-up only replays the
    # transitions it still needs, instead of blindly assuming a CLOSED start.
    engine_state: SessionState | None = None
    if confirm_sock is not None:
        engine_state = _query_engine_state(push_sock, confirm_sock, gateway_id)
        if engine_state is not None:
            print(f"[SCHEDULER] Engine reports current state: {engine_state.value}")
        else:
            print(
                "[SCHEDULER] Warning: could not determine engine state; "
                "assuming a CLOSED start",
                file=sys.stderr,
            )

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
        print("[SCHEDULER] Engine already at the current phase; no catch-up needed")
    elif catch_up:
        print(
            f"[SCHEDULER] Catching up {len(catch_up)} transition(s) "
            "to reach the current phase"
        )

    steps: list[_Step] = []
    for hhmm, state in catch_up:
        steps.append(
            _Step(state, _no_wait, label=f"{state} (catch-up, was due {hhmm})")
        )
    for hhmm, state, target in upcoming:
        steps.append(_Step(state, _wait_until(target), label=f"{state} (at {hhmm})"))

    if _run_transitions(push_sock, confirm_sock, running, steps):
        print("[SCHEDULER] All transitions sent for today.")


def _run_forever(
    push_sock: zmq.Socket[bytes],
    schedule: list[tuple[str, str]],
    confirm_sock: zmq.Socket[bytes] | None,
    is_running: Callable[[], bool],
) -> None:
    """Run the daily schedule repeatedly, once per calendar day (``--daily``)."""
    while is_running():
        _run_scheduled(
            push_sock, schedule, confirm_sock=confirm_sock, is_running=is_running
        )
        if not is_running():
            break
        secs = _seconds_until_next_day()
        print(
            f"[SCHEDULER] Day complete; sleeping {secs / 3600.0:.1f}h "
            "until the next trading day"
        )
        _interruptible_sleep(secs, is_running)
    print("[SCHEDULER] Stopped.")


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

    print(f"[SCHEDULER] --now mode: sending all transitions with {delay}s delays\n")

    # First transition fires immediately; the rest are spaced by ``delay``.
    steps = [
        _Step(state.value, _no_wait if i == 0 else _fixed_wait(delay))
        for i, state in enumerate(transitions)
    ]

    if _run_transitions(push_sock, None, running, steps):
        print("[SCHEDULER] Done.")


def main() -> None:
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
        help="Run continuously, repeating the schedule every calendar day",
    )
    parser.add_argument(
        "--config",
        "-c",
        metavar="FILE",
        help="Config YAML with schedule section (default: engine_config.yaml)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=NOW_MODE_DELAY,
        help=f"Seconds between transitions in --now mode (default: {NOW_MODE_DELAY})",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Do not query/confirm session state via the engine",
    )
    args = parser.parse_args()
    now_mode_delay = args.delay

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
    time.sleep(0.1)  # let socket connect

    try:
        if args.now:
            _run_now(push_sock, now_mode_delay, is_running=_is_running)
        else:
            config_path = Path(args.config) if args.config else ENGINE_CONFIG_FILE
            if args.config and not config_path.exists():
                print(
                    f"[SCHEDULER] FATAL: Config file not found: {config_path}",
                    file=sys.stderr,
                )
                sys.exit(1)

            schedule = _load_schedule(config_path)

            # Refuse to start on a schedule the engine could never follow (M1).
            errors = _validate_schedule(schedule)
            if errors:
                for err in errors:
                    print(
                        f"[SCHEDULER] FATAL: invalid schedule: {err}",
                        file=sys.stderr,
                    )
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
                time.sleep(0.05)  # let the SUB connect before the first send

            try:
                if args.daily:
                    _run_forever(push_sock, schedule, confirm_sock, _is_running)
                else:
                    _run_scheduled(
                        push_sock,
                        schedule,
                        confirm_sock=confirm_sock,
                        is_running=_is_running,
                    )
            finally:
                if confirm_sock is not None:
                    confirm_sock.close()
    finally:
        push_sock.close()


if __name__ == "__main__":
    main()
