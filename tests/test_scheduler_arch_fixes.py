"""Tests for the two architecture fixes (A1, A2).

- A1: both run modes drive transitions through a single ``_run_transitions``
      loop that honors the stop flag and reports completion.
- A2: on startup the scheduler recovers the engine's current session state and
      only replays the catch-up transitions that are actually missing, turning
      the blind emitter into a closed-loop driver.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import zmq

from edumatcher.models.message import (
    decode,
    make_session_status_msg,
)
from edumatcher.models.session import SessionState
from edumatcher.scheduler.main import (
    _Step,
    _catch_up_transitions,
    _query_engine_state,
    _run_scheduled,
    _run_transitions,
)

_FULL = [
    ("09:00", "PRE_OPEN"),
    ("09:25", "OPENING_AUCTION"),
    ("09:30", "CONTINUOUS"),
    ("16:00", "CLOSING_AUCTION"),
    ("16:05", "CLOSED"),
]


def _sent(sock: MagicMock) -> list[tuple[str, dict[str, object]]]:
    return [decode(call.args[0]) for call in sock.send_multipart.call_args_list]


# ---------------------------------------------------------------------------
# A1 — single shared run loop
# ---------------------------------------------------------------------------


class TestA1RunTransitions:
    def test_dispatches_all_steps_and_reports_complete(self) -> None:
        fake_push = MagicMock()
        steps = [
            _Step("PRE_OPEN", lambda: 0.0),
            _Step("OPENING_AUCTION", lambda: 0.0),
        ]
        assert _run_transitions(fake_push, None, lambda: True, steps) is True
        assert fake_push.send_multipart.call_count == 2

    def test_stops_before_first_step_when_not_running(self) -> None:
        fake_push = MagicMock()
        steps = [_Step("PRE_OPEN", lambda: 0.0)]
        assert _run_transitions(fake_push, None, lambda: False, steps) is False
        fake_push.send_multipart.assert_not_called()

    def test_stops_midway_and_reports_incomplete(self) -> None:
        state = {"n": 0}

        def is_running() -> bool:
            state["n"] += 1
            return state["n"] <= 1  # allow only the first step

        fake_push = MagicMock()
        steps = [_Step("PRE_OPEN", lambda: 0.0), _Step("CONTINUOUS", lambda: 0.0)]
        assert _run_transitions(fake_push, None, is_running, steps) is False
        assert fake_push.send_multipart.call_count == 1


# ---------------------------------------------------------------------------
# A2 — engine-state recovery + minimal catch-up
# ---------------------------------------------------------------------------


class TestA2CatchUpTransitions:
    def test_unknown_state_replays_all(self) -> None:
        assert _catch_up_transitions(_FULL[:3], None) == _FULL[:3]

    def test_engine_already_at_target_replays_nothing(self) -> None:
        # Past runs through CONTINUOUS and the engine is already CONTINUOUS.
        assert _catch_up_transitions(_FULL[:3], SessionState.CONTINUOUS) == []

    def test_engine_behind_replays_only_remaining(self) -> None:
        # Engine is at PRE_OPEN; it still needs OPENING_AUCTION then CONTINUOUS.
        result = _catch_up_transitions(_FULL[:3], SessionState.PRE_OPEN)
        assert [state for _hhmm, state in result] == ["OPENING_AUCTION", "CONTINUOUS"]

    def test_closed_boot_midday_replays_all(self) -> None:
        # Freshly booted (CLOSED) mid-day: no CLOSED in the past window, so the
        # full day so far must be replayed.
        assert _catch_up_transitions(_FULL[:3], SessionState.CLOSED) == _FULL[:3]

    def test_closed_end_of_day_replays_nothing(self) -> None:
        # After the close: past ends in CLOSED and the engine is CLOSED.
        assert _catch_up_transitions(_FULL, SessionState.CLOSED) == []


class TestA2QueryEngineState:
    def test_returns_state_from_reply(self) -> None:
        fake_push = MagicMock()
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 1
        fake_sub.recv_multipart.return_value = make_session_status_msg(
            "SCHEDULER", "CONTINUOUS", True
        )
        result = _query_engine_state(fake_push, fake_sub, "SCHEDULER", timeout_ms=200)
        assert result is SessionState.CONTINUOUS
        # a state request was actually sent
        request_topics = [topic for topic, _payload in _sent(fake_push)]
        assert "system.session_state_request" in request_topics

    def test_returns_none_on_timeout(self) -> None:
        fake_push = MagicMock()
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 0
        assert (
            _query_engine_state(fake_push, fake_sub, "SCHEDULER", timeout_ms=50) is None
        )

    def test_returns_none_when_send_blocks(self) -> None:
        fake_push = MagicMock()
        fake_push.send_multipart.side_effect = zmq.Again
        fake_sub = MagicMock()
        assert _query_engine_state(fake_push, fake_sub, "SCHEDULER") is None
        fake_sub.poll.assert_not_called()


class TestA2ClosedLoopCatchUp:
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_skips_transitions_engine_already_applied(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # After 09:30, the engine reports it is already CONTINUOUS -> no
        # catch-up transitions should be sent, only the state query.
        mock_dt.now.return_value = datetime(2000, 1, 1, 12, 0, 0)
        fake_push = MagicMock()
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 1
        fake_sub.recv_multipart.return_value = make_session_status_msg(
            "SCHEDULER", "CONTINUOUS", True
        )

        _run_scheduled(
            fake_push, _FULL[:3], confirm_sock=fake_sub, is_running=lambda: True
        )

        topics = [topic for topic, _payload in _sent(fake_push)]
        assert "system.session_state_request" in topics
        assert "session.transition" not in topics

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_replays_only_missing_transitions(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # Engine restarted and is only at PRE_OPEN at 12:00 -> it should be
        # driven forward through OPENING_AUCTION and CONTINUOUS.
        mock_dt.now.return_value = datetime(2000, 1, 1, 12, 0, 0)
        fake_push = MagicMock()
        fake_sub = MagicMock()
        fake_sub.poll.return_value = 1
        fake_sub.recv_multipart.return_value = make_session_status_msg(
            "SCHEDULER", "PRE_OPEN", True
        )

        _run_scheduled(
            fake_push, _FULL[:3], confirm_sock=fake_sub, is_running=lambda: True
        )

        transition_states = [
            payload["to_state"]
            for topic, payload in _sent(fake_push)
            if topic == "session.transition"
        ]
        assert transition_states == ["OPENING_AUCTION", "CONTINUOUS"]
