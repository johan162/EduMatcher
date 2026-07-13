"""
Session Scheduler — drives the engine through daily trading phases.

Reads a schedule (either from --config YAML or default times) and sends
``session.transition`` messages to the engine at the configured wall-clock
times via a PUSH socket. When a confirmation subscriber is available it also
listens to the engine's ``session.state`` broadcasts to verify each transition
was actually applied (rather than blindly reporting success).

Usage:
  poetry run pm-scheduler                  # run today's schedule once, then exit
  poetry run pm-scheduler --daily          # run continuously, once per day
  poetry run pm-scheduler --now            # rapid-fire all transitions (for testing)
  poetry run pm-scheduler --config my.yaml # custom config file
  poetry run pm-scheduler --no-confirm     # do not wait for engine confirmation

Same-day behavior:
  By default the scheduler drives *today's* timeline and then exits. If it is
  started after some scheduled times have already passed, it first replays those
  past transitions in order to bring the engine to the correct current phase
  (engine session states are sequential and dependent). Use ``--daily`` to keep
  the process running and repeat the schedule every calendar day.

Typical daily sequence:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import zmq

from edumatcher.config import ENGINE_CONFIG_FILE, ENGINE_PUB_ADDR, ENGINE_PULL_ADDR
from edumatcher.messaging.bus import make_pusher, make_subscriber
from edumatcher.models.message import decode, make_session_transition_msg
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
) -> None:
    """Run one day's schedule: catch up on past transitions, then time the rest.

    Engine session transitions are sequential and dependent
    (``CLOSED → PRE_OPEN → … → CLOSED``), so a scheduler that starts after some
    scheduled times have already passed must *replay* those past transitions in
    order to bring the engine to the correct current phase. Silently skipping
    them (the previous behavior) left the engine stuck — see review finding H1.
    """
    running = is_running or (lambda: True)

    print("[SCHEDULER] Schedule for today:")
    for hhmm, state in schedule:
        print(f"  {hhmm}  → {state}")
    print()

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

    # Catch-up: replay every already-past transition in order so the engine
    # reaches the correct current phase instead of being left behind (H1).
    if past:
        print(
            f"[SCHEDULER] Catching up {len(past)} past transition(s) "
            "to reach the current phase"
        )
        for hhmm, state in past:
            if not running():
                break
            print(f"[SCHEDULER] → Catch-up transition to {state} (was due {hhmm})")
            _dispatch_transition(push_sock, confirm_sock, state)

    for hhmm, state, target in upcoming:
        if not running():
            break

        wait_secs = (target - datetime.now()).total_seconds()
        if wait_secs > 0:
            print(f"[SCHEDULER] Waiting {wait_secs:.0f}s until {hhmm} for {state}")
            _interruptible_sleep(wait_secs, running)

        if not running():
            print("[SCHEDULER] Interrupted")
            break

        print(f"[SCHEDULER] → Sending transition to {state}")
        _dispatch_transition(push_sock, confirm_sock, state)

    if running():
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

    for state in transitions:
        if not running():
            print("[SCHEDULER] Interrupted")
            break
        print(f"[SCHEDULER] → {state.value}")
        _send_transition(push_sock, state.value)
        _interruptible_sleep(delay, running)

    if running():
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
        help="Do not subscribe for engine session.state confirmations",
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

            # Subscribe to engine session.state broadcasts so we can confirm
            # each transition actually applied instead of blindly reporting
            # success (review finding M3).
            confirm_sock: zmq.Socket[bytes] | None = None
            if not args.no_confirm:
                confirm_sock = make_subscriber(ENGINE_PUB_ADDR, "session.state")
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
