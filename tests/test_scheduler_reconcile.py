"""Reconciling an engine that is off today's schedule path, and the
CLOSED-gated --on-close trigger.

An engine left in CONTINUOUS by a day that never closed, or moved ahead of
the schedule by an operator, used to receive a replay starting at PRE_OPEN
that it rejected step after step — trading on through the night and the
opening auction until the 16:00 closing auction happened to be legal again.
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.engine.config_loader import DaySchedule, ScheduleConfig
from edumatcher.models.message import (
    decode,
    make_session_state_msg,
    make_session_status_msg,
)
from edumatcher.models.session import SessionState
from edumatcher.scheduler import main as sched
from edumatcher.scheduler.main import (
    _plan_catch_up,
    _route,
    _run_scheduled,
    _run_transitions,
    _Step,
    _time_today,
)

S = SessionState
_DAY = [
    ("09:00", "PRE_OPEN"),
    ("09:25", "OPENING_AUCTION"),
    ("09:30", "CONTINUOUS"),
    ("16:00", "CLOSING_AUCTION"),
    ("16:05", "CLOSED"),
]
_AT = datetime(2024, 1, 9, 0, 0)  # placeholder due time for upcoming entries
_FULL_DAY = DaySchedule(
    pre_open="09:00",
    opening_auction_start="09:25",
    continuous_start="09:30",
    closing_auction_start="16:00",
    closing_auction_end="16:05",
)
_CFG = ScheduleConfig(
    days={k: _FULL_DAY for k in ("mon", "tue", "wed", "thu", "fri")}
    | {"sat": None, "sun": None},
    holidays=None,
)


def _split(
    n_past: int,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, datetime]]]:
    return _DAY[:n_past], [(h, s, _AT) for h, s in _DAY[n_past:]]


@pytest.mark.parametrize(
    ("start", "target", "route"),
    [
        (S.CONTINUOUS, S.CLOSED, [S.CLOSED]),
        (S.CLOSING_AUCTION, S.CLOSED, [S.CLOSED]),
        (S.CONTINUOUS, S.PRE_OPEN, [S.CLOSED, S.PRE_OPEN]),
        (S.CLOSED, S.CLOSED, []),
    ],
)
def test_route_is_the_shortest_legal_path(
    start: SessionState, target: SessionState, route: list[SessionState]
) -> None:
    assert _route(start, target) == route


def test_on_path_states_use_the_ordinary_catch_up() -> None:
    past, upcoming = _split(3)
    steps, rest = _plan_catch_up(past, upcoming, S.PRE_OPEN)
    assert [s.state for s in steps] == ["OPENING_AUCTION", "CONTINUOUS"]
    assert rest == upcoming


def test_a_stale_continuous_engine_is_closed_before_the_day_starts() -> None:
    past, upcoming = _split(0)  # 08:00: nothing due yet
    steps, rest = _plan_catch_up(past, upcoming, S.CONTINUOUS)
    assert [s.state for s in steps] == ["CLOSED"]
    assert rest == upcoming  # the day then runs normally from PRE_OPEN


def test_an_early_continuous_engine_is_brought_back_to_the_scheduled_phase() -> None:
    past, upcoming = _split(1)  # 09:10: schedule says PRE_OPEN
    steps, rest = _plan_catch_up(past, upcoming, S.CONTINUOUS)
    assert [s.state for s in steps] == ["CLOSED", "PRE_OPEN"]
    assert rest == upcoming


@pytest.mark.parametrize(
    ("n_past", "engine", "resume_with"),
    [
        (0, S.PRE_OPEN, "OPENING_AUCTION"),
        (0, S.OPENING_AUCTION, "CONTINUOUS"),
        (1, S.OPENING_AUCTION, "CONTINUOUS"),
    ],
)
def test_an_early_non_matching_phase_is_kept_and_the_schedule_resumes_after_it(
    n_past: int, engine: SessionState, resume_with: str
) -> None:
    # Routing these back to CLOSED would have to pass through CONTINUOUS.
    past, upcoming = _split(n_past)
    steps, rest = _plan_catch_up(past, upcoming, engine)
    assert steps == []
    assert rest[0][1] == resume_with


@patch("edumatcher.scheduler.main.time.sleep")
@patch("edumatcher.scheduler.main.datetime")
def test_run_scheduled_closes_a_stale_engine_first(
    mock_dt: MagicMock, _sleep: MagicMock
) -> None:
    mock_dt.now.return_value = datetime(2024, 1, 9, 8, 0)  # a Tuesday
    push = MagicMock()
    sub = MagicMock()
    sub.poll.return_value = 1
    sub.recv_multipart.side_effect = [
        make_session_status_msg("SCHEDULER", "CONTINUOUS", True),
        make_session_state_msg("CLOSED", prev_state="CONTINUOUS"),
    ]
    calls = {"n": 0}

    def is_running() -> bool:
        calls["n"] += 1
        return calls["n"] <= 1  # stop after the reconcile step

    _run_scheduled(push, _CFG, confirm_sock=sub, is_running=is_running)

    sent = [decode(c.args[0]) for c in push.send_multipart.call_args_list]
    assert [p["to_state"] for t, p in sent if t == "session.transition"] == ["CLOSED"]


def test_time_today_is_anchored_to_the_given_day() -> None:
    assert _time_today("09:30", date(2024, 1, 9)) == datetime(2024, 1, 9, 9, 30)


def test_on_close_waits_for_a_confirmed_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sched, "_dispatch_transition", lambda *_a, **_k: False)
    calls: list[str] = []
    assert _run_transitions(
        MagicMock(),
        MagicMock(),
        lambda: True,
        [_Step("CLOSED", lambda: 0.0)],
        on_closed=lambda: calls.append("hook"),
    )
    assert calls == []
