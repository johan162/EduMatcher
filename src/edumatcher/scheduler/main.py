"""
Session Scheduler — drives the engine through daily trading phases.

Reads a schedule (either from --config YAML or default times) and sends
``session.transition`` messages to the engine at the configured wall-clock
times via a PUSH socket.

Usage:
  poetry run pm-scheduler                  # use times from engine_config.yaml
  poetry run pm-scheduler --now            # rapid-fire all transitions (for testing)
  poetry run pm-scheduler --config my.yaml # custom config file

Typical daily sequence:
  PRE_OPEN → OPENING_AUCTION → CONTINUOUS → CLOSING_AUCTION → CLOSED
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import zmq

from edumatcher.config import ENGINE_PULL_ADDR, ENGINE_CONFIG_FILE
from edumatcher.messaging.bus import make_pusher
from edumatcher.models.message import make_session_transition_msg
from edumatcher.models.session import SessionState

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


def _time_today(hhmm: str) -> datetime:
    """Parse a validated ``"HH:MM"`` string into a datetime for today.

    Callers must pass a normalized value (see :func:`_normalize_hhmm`); the
    schedule loader guarantees this, so this helper stays deliberately simple.
    """
    h, m = hhmm.split(":")
    now = datetime.now()
    return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


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


def _run_scheduled(
    push_sock: zmq.Socket[bytes], schedule: list[tuple[str, str]]
) -> None:
    """Wait for each scheduled time and send transitions.

    Engine session transitions are sequential and dependent
    (``CLOSED → PRE_OPEN → … → CLOSED``), so a scheduler that starts after some
    scheduled times have already passed must *replay* those past transitions in
    order to bring the engine to the correct current phase. Silently skipping
    them (the previous behavior) left the engine stuck in whatever state it
    started in — see review finding H1.
    """
    print("[SCHEDULER] Schedule for today:")
    for hhmm, state in schedule:
        print(f"  {hhmm}  → {state}")
    print()

    running = True

    def _stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

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
            if not running:
                break
            print(f"[SCHEDULER] → Catch-up transition to {state} (was due {hhmm})")
            _send_transition(push_sock, state)

    for hhmm, state, target in upcoming:
        if not running:
            break

        wait_secs = (target - datetime.now()).total_seconds()
        if wait_secs > 0:
            print(f"[SCHEDULER] Waiting {wait_secs:.0f}s until {hhmm} for {state}")
            # Sleep in small increments so SIGINT can interrupt promptly.
            deadline = time.monotonic() + wait_secs
            while running and time.monotonic() < deadline:
                time.sleep(max(0.0, min(1.0, deadline - time.monotonic())))

        if not running:
            print("[SCHEDULER] Interrupted")
            break

        print(f"[SCHEDULER] → Sending transition to {state}")
        _send_transition(push_sock, state)

    if running:
        print("[SCHEDULER] All transitions sent. Done.")


def _run_now(push_sock: zmq.Socket[bytes], delay: float = NOW_MODE_DELAY) -> None:
    """Rapid-fire all transitions with short delays (for testing)."""
    transitions = [
        SessionState.PRE_OPEN,
        SessionState.OPENING_AUCTION,
        SessionState.CONTINUOUS,
        SessionState.CLOSING_AUCTION,
        SessionState.CLOSED,
    ]

    print(f"[SCHEDULER] --now mode: sending all transitions with {delay}s delays\n")

    running = True

    def _stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    for state in transitions:
        if not running:
            print("[SCHEDULER] Interrupted")
            break
        print(f"[SCHEDULER] → {state.value}")
        _send_transition(push_sock, state.value)
        deadline = time.monotonic() + delay
        while running and time.monotonic() < deadline:
            time.sleep(max(0.0, min(1.0, deadline - time.monotonic())))

    if running:
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
    args = parser.parse_args()
    now_mode_delay = args.delay

    push_sock = make_pusher(ENGINE_PULL_ADDR)
    # Bound the send timeout and linger so the scheduler can never block forever
    # when the engine is not consuming (review finding H2).
    push_sock.setsockopt(zmq.SNDTIMEO, SEND_TIMEOUT_MS)
    push_sock.setsockopt(zmq.LINGER, LINGER_MS)
    time.sleep(0.1)  # let socket connect

    try:
        if args.now:
            _run_now(push_sock, now_mode_delay)
        else:
            config_path = Path(args.config) if args.config else ENGINE_CONFIG_FILE
            if args.config and not config_path.exists():
                print(
                    f"[SCHEDULER] FATAL: Config file not found: {config_path}",
                    file=sys.stderr,
                )
                sys.exit(1)
            schedule = _load_schedule(config_path)
            _run_scheduled(push_sock, schedule)
    finally:
        push_sock.close()


if __name__ == "__main__":
    main()
