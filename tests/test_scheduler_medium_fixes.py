"""Tests for the three MEDIUM scheduler fixes (M1, M2, M3).

- M1: the schedule is validated at load time — an out-of-order or transition-
      illegal schedule is rejected and the scheduler refuses to start.
- M2: ``--daily`` runs the schedule repeatedly, once per calendar day, instead
      of the process being a single-shot that exits after one day.
- M3: each transition is confirmed against the engine's ``session.state``
      broadcast instead of being reported as sent unconditionally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from edumatcher.models.message import make_session_state_msg
from edumatcher.scheduler.main import (
    DEFAULT_SCHEDULE,
    _confirm_transition,
    _dispatch_transition,
    _run_forever,
    _seconds_until_next_day,
    _validate_schedule,
)

# ---------------------------------------------------------------------------
# M1 — schedule validation
# ---------------------------------------------------------------------------


class TestM1ValidateSchedule:
    def test_default_schedule_is_valid(self) -> None:
        assert _validate_schedule(DEFAULT_SCHEDULE) == []

    def test_out_of_order_times_are_rejected(self) -> None:
        schedule = [("09:30", "PRE_OPEN"), ("09:00", "OPENING_AUCTION")]
        errors = _validate_schedule(schedule)
        assert any("strictly after" in e for e in errors)

    def test_illegal_transition_chain_is_rejected(self) -> None:
        # CONTINUOUS is not reachable directly from CLOSED (the engine boot
        # state), so a schedule that starts there is illegal.
        schedule = [("09:30", "CONTINUOUS")]
        errors = _validate_schedule(schedule)
        assert any("illegal transition" in e for e in errors)

    def test_valid_partial_chain_is_accepted(self) -> None:
        # PRE_OPEN -> CONTINUOUS (skipping the opening auction) is legal.
        schedule = [("09:00", "PRE_OPEN"), ("09:30", "CONTINUOUS")]
        assert _validate_schedule(schedule) == []

    @patch("edumatcher.scheduler.main.make_pusher", return_value=MagicMock())
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch(
        "edumatcher.scheduler.main._load_schedule",
        return_value=[("09:30", "CONTINUOUS")],
    )
    def test_main_refuses_to_start_on_invalid_schedule(
        self,
        mock_load: MagicMock,
        mock_sleep: MagicMock,
        mock_pusher: MagicMock,
    ) -> None:
        from edumatcher.scheduler.main import main

        with patch("sys.argv", ["pm-scheduler"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 1
        # We should bail out before ever running the schedule.
        mock_pusher.return_value.send_multipart.assert_not_called()


# ---------------------------------------------------------------------------
# M2 — daily rollover / long-running mode
# ---------------------------------------------------------------------------


class TestM2DailyRollover:
    def test_seconds_until_next_day_is_bounded(self) -> None:
        secs = _seconds_until_next_day()
        # Upper bound allows for a 25-hour day on a DST "fall back" boundary,
        # since the wait is now computed DST-aware (review finding L1).
        assert 0 < secs <= 25 * 60 * 60

    @patch("edumatcher.scheduler.main._seconds_until_next_day", return_value=10.0)
    @patch("edumatcher.scheduler.main._interruptible_sleep")
    @patch("edumatcher.scheduler.main._run_scheduled")
    def test_run_forever_repeats_until_stopped(
        self,
        mock_run_scheduled: MagicMock,
        mock_sleep: MagicMock,
        mock_secs: MagicMock,
    ) -> None:
        # is_running(): True, True, True, then False -> exactly two day-runs
        # with one inter-day sleep between them.
        state = {"n": 0}

        def is_running() -> bool:
            state["n"] += 1
            return state["n"] <= 3

        _run_forever(MagicMock(), DEFAULT_SCHEDULE, None, is_running)

        assert mock_run_scheduled.call_count == 2
        assert mock_sleep.called  # slept between the two days


# ---------------------------------------------------------------------------
# M3 — transition confirmation
# ---------------------------------------------------------------------------


class TestM3ConfirmTransition:
    def test_confirm_returns_true_on_matching_broadcast(self) -> None:
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 1  # data ready
        fake_sub.recv_multipart.return_value = make_session_state_msg(
            "PRE_OPEN", prev_state="CLOSED"
        )
        assert _confirm_transition(fake_sub, "PRE_OPEN", timeout_ms=200) is True

    def test_confirm_returns_false_on_timeout(self) -> None:
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 0  # nothing arrives
        assert _confirm_transition(fake_sub, "PRE_OPEN", timeout_ms=50) is False

    def test_confirm_ignores_non_matching_state(self) -> None:
        fake_sub = MagicMock()
        # First a mismatching broadcast, then the timeout path (poll -> 0).
        fake_sub.poll.side_effect = [1, 0]
        fake_sub.recv_multipart.return_value = make_session_state_msg(
            "OPENING_AUCTION", prev_state="PRE_OPEN"
        )
        assert _confirm_transition(fake_sub, "PRE_OPEN", timeout_ms=200) is False


class TestM3DispatchTransition:
    def test_dispatch_without_confirm_socket_just_sends(self) -> None:
        fake_push = MagicMock()
        _dispatch_transition(fake_push, None, "PRE_OPEN")
        fake_push.send_multipart.assert_called_once()

    def test_dispatch_with_confirm_socket_sends_and_confirms(self) -> None:
        fake_push = MagicMock()
        fake_confirm = MagicMock()
        fake_confirm.poll.return_value = 1
        fake_confirm.recv_multipart.return_value = make_session_state_msg(
            "PRE_OPEN", prev_state="CLOSED"
        )
        _dispatch_transition(fake_push, fake_confirm, "PRE_OPEN")
        fake_push.send_multipart.assert_called_once()
        assert fake_confirm.poll.called
