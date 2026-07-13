"""Regression tests for the three HIGH-severity scheduler defects.

These encode the *correct* expected behaviour described in
``docs-design/EduMatcher-scheduler-review.md`` and are expected to FAIL against
the current implementation until each defect is fixed:

- H1: skipping past-due transitions silently desyncs the engine. Because engine
      session transitions are sequential and dependent
      (``CLOSED → PRE_OPEN → … → CLOSED``), a scheduler that starts after some
      transition times have passed must still bring the engine to the correct
      current state, not skip every past entry and leave the engine stuck.
- H2: the PUSH socket is created with a default (infinite) LINGER and no send
      timeout, so ``send``/``close`` can hang forever when the engine is not
      consuming. The scheduler must configure a bounded send timeout and a
      finite linger.
- H3: unquoted ``HH:MM`` schedule values are parsed by PyYAML as base-60
      integers (``9:30`` → ``570``), and out-of-range/malformed times reach
      ``_time_today`` unguarded, crashing the scheduler with an unhandled
      exception. Schedule loading must validate/normalise times so scheduling
      never crashes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import zmq

from edumatcher.models.message import decode
from edumatcher.scheduler.main import _load_schedule, _run_scheduled, _time_today

# Full, valid, in-order daily schedule (a legal CLOSED→…→CLOSED chain).
_FULL_SCHEDULE = [
    ("09:00", "PRE_OPEN"),
    ("09:25", "OPENING_AUCTION"),
    ("09:30", "CONTINUOUS"),
    ("16:00", "CLOSING_AUCTION"),
    ("16:05", "CLOSED"),
]


def _sent_states(sock: MagicMock) -> list[str]:
    """Decode every ``to_state`` the scheduler PUSHed on the mock socket."""
    states: list[str] = []
    for call in sock.send_multipart.call_args_list:
        frames = call.args[0]
        _topic, payload = decode(frames)
        states.append(payload["to_state"])
    return states


# ---------------------------------------------------------------------------
# H1 — skipping past-due transitions must still catch the engine up
# ---------------------------------------------------------------------------


class TestH1PastTransitionsDesync:
    def test_late_start_catches_engine_up_to_current_state(self) -> None:
        """Starting after all scheduled times must not leave the engine stuck.

        With every schedule time in the past, the engine (which boots CLOSED)
        should be driven to the most-recent-past state — the final entry,
        CLOSED — rather than having every transition silently skipped.
        """
        fake_sock = MagicMock()
        # Pin "now" to 23:59 so all five schedule entries are in the past.
        fixed_now = datetime(2000, 1, 1, 23, 59, 0)

        with (
            patch("edumatcher.scheduler.main.time.sleep"),
            patch("edumatcher.scheduler.main.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fixed_now
            _run_scheduled(fake_sock, _FULL_SCHEDULE)

        # DEFECT (H1): current code prints "already past, skipping" for every
        # entry and sends nothing, so the engine never leaves CLOSED.
        assert fake_sock.send_multipart.called, (
            "scheduler skipped all past transitions and sent nothing — "
            "engine would be stuck in its startup state"
        )
        # The engine must end up in the correct current phase.
        assert _sent_states(fake_sock)[-1] == "CLOSED"

    def test_partial_late_start_reaches_most_recent_past_state(self) -> None:
        """Mid-morning start must catch up to CONTINUOUS before waiting.

        At 10:00 the first three entries (PRE_OPEN, OPENING_AUCTION,
        CONTINUOUS) are past; the engine should be brought to CONTINUOUS.
        """
        fake_sock = MagicMock()
        fixed_now = datetime(2000, 1, 1, 10, 0, 0)

        # Only the already-past portion of the day, to avoid waiting on future
        # entries (the point here is the catch-up, not the timed waits).
        past_only = _FULL_SCHEDULE[:3]  # through CONTINUOUS

        with (
            patch("edumatcher.scheduler.main.time.sleep"),
            patch("edumatcher.scheduler.main.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = fixed_now
            _run_scheduled(fake_sock, past_only)

        assert fake_sock.send_multipart.called, (
            "scheduler skipped past transitions on a late start — "
            "engine never reaches CONTINUOUS"
        )
        assert _sent_states(fake_sock)[-1] == "CONTINUOUS"


# ---------------------------------------------------------------------------
# H2 — bounded send timeout + finite linger so the process cannot hang
# ---------------------------------------------------------------------------


class TestH2BlockingSendAndLinger:
    @patch("edumatcher.scheduler.main._run_now")
    @patch("edumatcher.scheduler.main.time.sleep")
    def test_push_socket_has_finite_send_timeout_and_linger(
        self, _mock_sleep: MagicMock, _mock_run_now: MagicMock
    ) -> None:
        """The scheduler's PUSH socket must not be able to block forever.

        A ``zmq.PUSH`` with the default ``LINGER=-1`` and no ``SNDTIMEO`` blocks
        indefinitely on ``send`` when no peer is consuming and hangs on
        ``close`` when messages are undelivered. The scheduler must set a
        bounded send timeout and a finite linger.
        """
        fake_sock = MagicMock()
        with (
            patch("edumatcher.scheduler.main.make_pusher", return_value=fake_sock),
            patch("sys.argv", ["pm-scheduler", "--now"]),
        ):
            from edumatcher.scheduler.main import main

            main()

        opts = {
            call.args[0]: call.args[1]
            for call in fake_sock.setsockopt.call_args_list
            if len(call.args) >= 2
        }

        # DEFECT (H2): current code never calls setsockopt, so neither option
        # is present and the socket can hang.
        assert (
            zmq.SNDTIMEO in opts
        ), "push socket has no bounded send timeout (SNDTIMEO)"
        assert opts[zmq.SNDTIMEO] > 0, "SNDTIMEO must be a positive, finite timeout"

        assert zmq.LINGER in opts, "push socket has no finite LINGER"
        assert opts[zmq.LINGER] >= 0, "LINGER must be finite (>= 0), not the default -1"


# ---------------------------------------------------------------------------
# H3 — malformed / unquoted schedule times must not crash the scheduler
# ---------------------------------------------------------------------------


class TestH3MalformedScheduleTimesCrash:
    def test_unquoted_yaml_times_do_not_crash_scheduler(self, tmp_path: Path) -> None:
        """Unquoted HH:MM (parsed by PyYAML as base-60 ints) must be handled.

        ``continuous_start: 9:30`` is loaded by PyYAML as the integer ``570``;
        stringified to ``"570"`` it crashes ``_time_today`` on the tuple unpack.
        The project's own sample config documents this unquoted form, so it is
        a realistic input.
        """
        config = tmp_path / "unquoted.yaml"
        config.write_text(
            "schedule:\n"
            "  pre_open: 9:00\n"
            "  opening_auction_start: 9:25\n"
            "  continuous_start: 9:30\n"
            "  closing_auction_start: 16:00\n"
            "  closing_auction_end: 16:05\n"
        )

        # Loading must not raise ...
        schedule = _load_schedule(config)

        # ... and every time it hands downstream must be parseable without an
        # unhandled exception (DEFECT H3: values like "570" blow up here).
        for hhmm, _state in schedule:
            try:
                _time_today(hhmm)
            except Exception as exc:  # noqa: BLE001 - the point is "must not raise"
                pytest.fail(
                    f"scheduler crashed on unquoted schedule time {hhmm!r}: {exc!r}"
                )

    def test_out_of_range_and_malformed_times_do_not_crash(
        self, tmp_path: Path
    ) -> None:
        """Quoted-but-invalid times must be rejected/normalised, not fatal."""
        config = tmp_path / "malformed.yaml"
        config.write_text(
            "schedule:\n"
            '  pre_open: "25:00"\n'  # hour out of range
            '  continuous_start: "16:5:00"\n'  # too many components
        )

        schedule = _load_schedule(config)

        for hhmm, _state in schedule:
            try:
                _time_today(hhmm)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    f"scheduler crashed on malformed schedule time {hhmm!r}: {exc!r}"
                )
