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
                result = []
                for key, state in mapping:
                    t = sched.get(key)
                    if t:
                        result.append((str(t), state))
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
    """Parse 'HH:MM' into a datetime for today."""
    h, m = hhmm.split(":")
    now = datetime.now()
    return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


def _run_scheduled(
    push_sock: zmq.Socket[bytes], schedule: list[tuple[str, str]]
) -> None:
    """Wait for each scheduled time and send transitions."""
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

    for hhmm, state in schedule:
        target = _time_today(hhmm)
        now = datetime.now()

        if target < now:
            print(f"[SCHEDULER] {hhmm} {state} — already past, skipping")
            continue

        wait_secs = (target - now).total_seconds()
        print(f"[SCHEDULER] Waiting {wait_secs:.0f}s until {hhmm} for {state}")

        # Sleep in small increments so SIGINT can interrupt
        deadline = time.monotonic() + wait_secs
        while running and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

        if not running:
            print("[SCHEDULER] Interrupted")
            break

        print(f"[SCHEDULER] → Sending transition to {state}")
        push_sock.send_multipart(make_session_transition_msg(state))

    if running:
        print("[SCHEDULER] All transitions sent. Done.")


def _run_now(push_sock: zmq.Socket[bytes]) -> None:
    """Rapid-fire all transitions with short delays (for testing)."""
    transitions = [
        SessionState.PRE_OPEN,
        SessionState.OPENING_AUCTION,
        SessionState.CONTINUOUS,
        SessionState.CLOSING_AUCTION,
        SessionState.CLOSED,
    ]

    print(
        f"[SCHEDULER] --now mode: sending all transitions with {NOW_MODE_DELAY}s delays\n"
    )

    for state in transitions:
        print(f"[SCHEDULER] → {state.value}")
        push_sock.send_multipart(make_session_transition_msg(state.value))
        time.sleep(NOW_MODE_DELAY)

    print("[SCHEDULER] Done.")


def main() -> None:
    global NOW_MODE_DELAY

    parser = argparse.ArgumentParser(description="EduMatcher session scheduler")
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

    NOW_MODE_DELAY = args.delay

    push_sock = make_pusher(ENGINE_PULL_ADDR)
    time.sleep(0.1)  # let socket connect

    if args.now:
        _run_now(push_sock)
    else:
        config_path = Path(args.config) if args.config else ENGINE_CONFIG_FILE
        if args.config and not config_path.exists():
            print(
                f"[SCHEDULER] FATAL: Config file not found: {config_path}",
                file=sys.stderr,
            )
            push_sock.close()
            sys.exit(1)
        schedule = _load_schedule(config_path)
        _run_scheduled(push_sock, schedule)

    push_sock.close()


if __name__ == "__main__":
    main()
