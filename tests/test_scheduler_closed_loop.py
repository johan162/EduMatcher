"""The scheduler's closed loop with a real engine (Scheduler review 2026-11).

Every test drives the real scheduler functions against a real Engine through
``tests/scheduler_harness.py``: the engine decides what it applies and what
it broadcasts, and the assertions read the engine's state and the
transitions it applied.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import pytest

from edumatcher.engine import main as engine_main
from edumatcher.engine.config_loader import DaySchedule, ScheduleConfig
from edumatcher.models.session import SessionState
from edumatcher.scheduler import main as sched
from tests.scheduler_harness import EngineBridge, EngineRef, EngineSub, fast_timeouts

DAY = ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED")
_HOURS = DaySchedule(
    pre_open="09:00",
    opening_auction_start="09:25",
    continuous_start="09:30",
    closing_auction_start="16:00",
    closing_auction_end="16:05",
)
CFG = ScheduleConfig(
    days={k: _HOURS for k in ("mon", "tue", "wed", "thu", "fri")}
    | {"sat": None, "sun": None},
    holidays=None,
)


@pytest.fixture
def ref(monkeypatch, tmp_path) -> EngineRef:
    fast_timeouts(monkeypatch)
    return EngineRef(monkeypatch, tmp_path)


def _steps(*states: str) -> list[sched._Step]:
    return [sched._Step(s, sched._no_wait) for s in states]


# --- WP-SCH01: only the engine's answer to this request confirms it --------


def test_queued_operator_broadcasts_do_not_confirm_rejected_transitions(
    ref: EngineRef, caplog: pytest.LogCaptureFixture
) -> None:
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
    sub = EngineSub(ref)
    while sub.poll(0):  # the scheduler read the morning's confirmations
        sub.recv_multipart()
    ref.drive("CLOSING_AUCTION", "CLOSED", command_id="OPS-1")  # early close
    bridge = EngineBridge(ref)
    closes: list[int] = []

    with caplog.at_level(logging.WARNING, logger=sched.log.name):
        sched._run_transitions(
            bridge,  # type: ignore[arg-type]
            sub,  # type: ignore[arg-type]
            lambda: True,
            _steps("CLOSING_AUCTION", "CLOSED"),
            None,
            lambda: closes.append(1),
        )

    assert bridge.transitions() == []  # both rejected by the CLOSED engine
    unconfirmed = [r for r in caplog.records if "no confirmation" in r.getMessage()]
    assert len(unconfirmed) == 2
    assert closes == []


def test_a_late_state_reply_does_not_answer_the_next_query(ref: EngineRef) -> None:
    sub = EngineSub(ref)
    # The reply to an earlier query that timed out, while the engine was CLOSED.
    ref.engine._handle_session_state_request({"gateway_id": "SCHEDULER"})
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", command_id="OPS-1")

    got = sched._query_engine_state(EngineBridge(ref), sub)  # type: ignore[arg-type]

    assert got is not None and got.value == "CONTINUOUS"


def test_an_operator_broadcast_after_the_send_does_not_confirm(ref: EngineRef) -> None:
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
    sub = EngineSub(ref)

    def lost_then_operator(to_state: str) -> bool:
        # The scheduler's message is lost; an operator makes the same move.
        ref.drive(to_state, command_id="OPS-2")
        return False

    applied = sched._dispatch_transition(
        EngineBridge(ref, lost_then_operator),  # type: ignore[arg-type]
        sub,  # type: ignore[arg-type]
        "CLOSING_AUCTION",
    )

    assert ref.state == "CLOSING_AUCTION"
    assert applied is False


def test_a_scheduled_day_is_confirmed_step_by_step(ref: EngineRef) -> None:
    bridge = EngineBridge(ref)
    closes: list[int] = []

    done = sched._run_transitions(
        bridge,  # type: ignore[arg-type]
        EngineSub(ref),  # type: ignore[arg-type]
        lambda: True,
        _steps(*DAY),
        None,
        lambda: closes.append(1),
    )

    assert done is True
    assert bridge.transitions() == list(DAY)
    assert ref.state == "CLOSED"
    assert closes == [1]


# --- WP-SCH02: an unknown engine state never replays a closed day ----------


def _at(monkeypatch: pytest.MonkeyPatch, start: str) -> None:
    """Run the schedule clock from ``start`` (session-local) at wall speed."""
    monkeypatch.setattr(
        sched, "_clock", sched._Clock(1.0, datetime.fromisoformat(start))
    )


def test_no_confirm_start_after_the_close_sends_nothing(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref.drive(*DAY)
    _at(monkeypatch, "2026-11-17T17:00")  # a Tuesday
    bridge = EngineBridge(ref)
    closes: list[int] = []

    sched._run_scheduled(
        bridge, CFG, confirm_sock=None, on_closed=lambda: closes.append(1)  # type: ignore[arg-type]
    )

    assert bridge.applied == []
    assert closes == []


def test_unanswered_state_query_after_the_close_sends_nothing(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref.drive(*DAY)
    monkeypatch.setattr(ref.engine, "_handle_session_state_request", lambda _p: None)
    _at(monkeypatch, "2026-11-17T17:00")
    bridge = EngineBridge(ref)

    sched._run_scheduled(bridge, CFG, confirm_sock=EngineSub(ref))  # type: ignore[arg-type]

    assert bridge.applied == []
    assert ref.state == "CLOSED"


def test_no_confirm_mid_day_start_still_catches_up(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, "2026-11-17T10:00")
    bridge = EngineBridge(ref)

    sched._run_scheduled(
        bridge,  # type: ignore[arg-type]
        CFG,
        confirm_sock=None,
        is_running=lambda: len(bridge.applied) < 3,  # stop before 16:00
    )

    assert bridge.transitions() == ["PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"]


# --- L042: a state left over from an earlier day is closed first ----------


def test_the_engine_reports_when_it_entered_its_state(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    def status() -> sched._EngineStatus | None:
        return sched._query_engine_status(EngineBridge(ref), EngineSub(ref))  # type: ignore[arg-type]

    booted = status()
    assert booted is not None and booted.state == SessionState.CLOSED
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", booted.since)

    monkeypatch.setattr(engine_main, "_utc_now_iso", lambda: "2026-11-17T08:00:00.000Z")
    ref.drive("PRE_OPEN")
    monkeypatch.setattr(engine_main, "_utc_now_iso", lambda: "2026-11-17T09:00:00.000Z")
    ref.drive("CLOSING_AUCTION")  # rejected: the engine stays where it was

    assert status() == sched._EngineStatus(
        SessionState.PRE_OPEN, "2026-11-17T08:00:00.000Z"
    )


@pytest.mark.parametrize(
    ("entered", "expected"),
    [
        # CONTINUOUS since Monday: Monday is closed, then Tuesday replayed.
        ("2026-11-16T09:30", ["CLOSED", "PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"]),
        # CONTINUOUS since 09:30 today: already where the schedule says.
        ("2026-11-17T09:30", []),
    ],
)
def test_a_continuous_left_over_from_yesterday_is_closed_first(
    ref: EngineRef,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    entered: str,
    expected: list[str],
) -> None:
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
    _at(monkeypatch, "2026-11-17T11:00")  # a Tuesday
    # The engine stamps wall time: the instant the schedule clock maps
    # ``entered`` to.
    since = sched._to_utc_iso(datetime.fromisoformat(entered))
    ref.engine._session_state_since = since
    bridge = EngineBridge(ref)

    with caplog.at_level(logging.INFO, logger=sched.log.name):
        sched._run_scheduled(
            bridge,  # type: ignore[arg-type]
            CFG,
            confirm_sock=EngineSub(ref),  # type: ignore[arg-type]
            is_running=lambda: len(bridge.applied) < len(expected),  # before 16:00
        )

    messages = [r.getMessage() for r in caplog.records]
    assert f"Engine reports current state: CONTINUOUS (since {since})" in messages
    assert any("from an earlier day" in m for m in messages) is bool(expected)
    assert bridge.transitions() == expected
    assert ref.state == "CONTINUOUS"


@pytest.mark.parametrize("n_past", range(len(DAY) + 1))
def test_unknown_state_catches_up_as_a_closed_engine(n_past: int) -> None:
    past = [(f"{9 + i:02d}:00", s) for i, s in enumerate(DAY[:n_past])]
    assert sched._catch_up_transitions(past, None) == sched._catch_up_transitions(
        past, SessionState.CLOSED
    )


# --- WP-SCH03: an engine restart is followed by the schedule ---------------


def _late_afternoon(ref: EngineRef, monkeypatch: pytest.MonkeyPatch) -> EngineBridge:
    """The engine trading as scheduled; the scheduler (re)started at 15:50.

    The clock runs 2000x: 15:50 -> 16:05 takes under half a second, and the
    100 ms confirmation timeout is about three simulated minutes.
    """
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
    monkeypatch.setattr(
        sched, "_clock", sched._Clock(2000.0, datetime(2026, 11, 17, 15, 50))
    )
    return EngineBridge(ref)


def _once_after(hhmm: str, action) -> object:  # noqa: ANN001
    """An ``is_running`` that runs ``action`` once the clock passes ``hhmm``."""
    done: list[int] = []

    def is_running() -> bool:
        if not done and sched._clock.now().strftime("%H:%M") >= hhmm:
            done.append(1)
            action()
        return True

    return is_running


def test_an_announced_engine_restart_is_brought_back_at_once(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _late_afternoon(ref, monkeypatch)
    closes: list[int] = []

    sched._run_scheduled(
        bridge,  # type: ignore[arg-type]
        CFG,
        confirm_sock=EngineSub(ref),  # type: ignore[arg-type]
        is_running=_once_after("15:55", ref.restart),  # type: ignore[arg-type]
        on_closed=lambda: closes.append(1),
    )

    assert bridge.applied == [
        ("PRE_OPEN", "CLOSED", "PRE_OPEN"),
        ("OPENING_AUCTION", "PRE_OPEN", "OPENING_AUCTION"),
        ("CONTINUOUS", "OPENING_AUCTION", "CONTINUOUS"),
        ("CLOSING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION"),
        ("CLOSED", "CLOSING_AUCTION", "CLOSED"),
    ]
    assert closes == [1]


def test_a_silent_engine_restart_is_caught_at_the_next_transition(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _late_afternoon(ref, monkeypatch)
    closes: list[int] = []

    sched._run_scheduled(
        bridge,  # type: ignore[arg-type]
        CFG,
        confirm_sock=EngineSub(ref),  # type: ignore[arg-type]
        is_running=_once_after(  # type: ignore[arg-type]
            "15:55", lambda: ref.restart(announce=False)
        ),
        on_closed=lambda: closes.append(1),
    )

    assert bridge.transitions() == [
        "PRE_OPEN",
        "OPENING_AUCTION",
        "CONTINUOUS",
        "CLOSING_AUCTION",
        "CLOSED",
    ]
    assert ref.state == "CLOSED"
    assert closes == [1]


def test_an_operator_early_close_is_left_alone(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = _late_afternoon(ref, monkeypatch)

    sched._run_scheduled(
        bridge,  # type: ignore[arg-type]
        CFG,
        confirm_sock=EngineSub(ref),  # type: ignore[arg-type]
        is_running=_once_after(  # type: ignore[arg-type]
            "15:55",
            lambda: ref.drive("CLOSING_AUCTION", "CLOSED", command_id="OPS-1"),
        ),
    )

    assert bridge.transitions() == []
    assert ref.state == "CLOSED"


def test_an_engine_restart_after_the_close_sends_nothing(
    ref: EngineRef, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref.drive(*DAY)
    ref.restart()  # its system.startup is queued for the scheduler
    _at(monkeypatch, "2026-11-17T17:00")
    bridge = EngineBridge(ref)

    sched._run_scheduled(bridge, CFG, confirm_sock=EngineSub(ref))  # type: ignore[arg-type]

    assert bridge.applied == []
    assert ref.state == "CLOSED"


# --- WP-SCH04: --now starts from CLOSED and reports what was applied ------


def test_now_closes_an_open_engine_first_and_runs_the_whole_day(
    ref: EngineRef, caplog: pytest.LogCaptureFixture
) -> None:
    ref.drive("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS")
    bridge = EngineBridge(ref)

    with caplog.at_level(logging.INFO, logger=sched.log.name):
        sched._run_now(bridge, 0.0, confirm_sock=EngineSub(ref))  # type: ignore[arg-type]

    assert bridge.transitions() == ["CLOSED", *DAY]
    assert ref.state == "CLOSED"
    messages = [r.getMessage() for r in caplog.records]
    assert any("closing it first" in m for m in messages)
    assert messages[-1] == "Done."


def test_now_reports_a_transition_the_engine_did_not_apply(
    ref: EngineRef, caplog: pytest.LogCaptureFixture
) -> None:
    # OPENING_AUCTION is lost on the way; PRE_OPEN -> CONTINUOUS is legal.
    bridge = EngineBridge(ref, lambda s: s != "OPENING_AUCTION")

    with caplog.at_level(logging.INFO, logger=sched.log.name):
        sched._run_now(bridge, 0.0, confirm_sock=EngineSub(ref))  # type: ignore[arg-type]

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        r.levelno == logging.WARNING and "OPENING_AUCTION" in r.getMessage()
        for r in caplog.records
    )
    assert "Done." not in messages


def test_now_without_confirmation_sends_the_day_blind(
    ref: EngineRef, caplog: pytest.LogCaptureFixture
) -> None:
    bridge = EngineBridge(ref)

    with caplog.at_level(logging.INFO, logger=sched.log.name):
        sched._run_now(bridge, 0.0)  # type: ignore[arg-type]

    assert bridge.transitions() == list(DAY)
    assert caplog.records[-1].getMessage() == "Done."
