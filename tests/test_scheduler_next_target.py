"""The scheduler gives the engine a countdown target while the exchange is closed.

A ``session.transition`` can only describe the transition after itself, so the
close named nothing, and a scheduler started before the day's first transition
or after its last had no transition to carry a target on at all. Every closed
hour then showed a bare CLOSED badge.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import edumatcher.scheduler.main as sched
from edumatcher.engine.config_loader import DAY_KEYS, ScheduleConfig
from edumatcher.models.message import decode
from edumatcher.models.session import SessionState

STOCKHOLM = ZoneInfo("Europe/Stockholm")
# Monday 2026-11-09 09:00 Stockholm (UTC+1): the open after Friday's close.
MONDAY_OPEN = "2026-11-09T08:00:00.000Z"

WEEKDAYS_ONLY = ScheduleConfig(
    days={
        key: None if key in ("sat", "sun") else sched._DEFAULT_DAY_SCHEDULE
        for key in DAY_KEYS
    },
    holidays=None,
)

Event = tuple[str, str, str, float]  # (kind, state, next_at, epoch)


@pytest.fixture()
def run_at(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str], list[Event]]:
    """Freeze the clock at a Stockholm time; record transitions and announcements.

    Sleeping advances the frozen clock instead of waiting, so a whole day runs
    instantly and each event records when it was sent.
    """
    events: list[Event] = []
    epoch = 0.0

    class LocalDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> LocalDatetime:
            return cls.fromtimestamp(epoch, STOCKHOLM)

    def sleep(seconds: float) -> None:
        nonlocal epoch
        epoch += seconds

    def dispatch(
        push: object,
        confirm: object,
        state: str,
        next_state: str = "",
        next_at: str = "",
        on_wake: object = None,
    ) -> None:
        events.append(("transition", state, next_at, epoch))

    def announce(push: object, state: str, at: datetime) -> None:
        events.append(("announce", state, sched._to_utc_iso(at), epoch))

    monkeypatch.setattr(sched, "datetime", LocalDatetime)
    monkeypatch.setattr(time, "time", lambda: epoch)
    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(sched, "LIVENESS_CHUNK_SEC", 3600.0)
    monkeypatch.setattr(sched, "_dispatch_transition", dispatch)
    monkeypatch.setattr(sched, "_announce_next", announce)

    def start(local: str) -> list[Event]:
        nonlocal epoch
        epoch = datetime.fromisoformat(local).replace(tzinfo=STOCKHOLM).timestamp()
        monkeypatch.setattr(sched, "_clock", sched._Clock())
        return events

    return start


def _until(events: list[Event], count: int) -> Callable[[], bool]:
    """``is_running`` for ``_run_forever``: stop once ``count`` events are in."""
    return lambda: len(events) < count


def test_the_daily_close_names_the_next_open_skipping_the_weekend(
    run_at: Callable[[str], list[Event]],
) -> None:
    events = run_at("2026-11-06T08:00")

    sched._run_forever(MagicMock(), WEEKDAYS_ONLY, None, _until(events, 6))

    transitions = [e for e in events if e[0] == "transition"]
    assert transitions[-1][:3] == ("transition", "CLOSED", MONDAY_OPEN)


def test_a_single_shot_close_names_nothing(
    run_at: Callable[[str], list[Event]],
) -> None:
    """No scheduler will be running to perform tomorrow's open."""
    events = run_at("2026-11-06T08:00")

    sched._run_scheduled(MagicMock(), WEEKDAYS_ONLY)

    assert events[-1][:3] == ("transition", "CLOSED", "")


def test_a_start_before_the_open_announces_it_before_waiting(
    run_at: Callable[[str], list[Event]],
) -> None:
    events = run_at("2026-11-06T08:00")
    started = time.time()

    sched._run_scheduled(MagicMock(), WEEKDAYS_ONLY)

    assert events[0] == ("announce", "PRE_OPEN", "2026-11-06T08:00:00.000Z", started)
    assert events[1][:2] == ("transition", "PRE_OPEN")
    assert [e[0] for e in events[2:]] == ["transition"] * 4


def test_a_mid_day_start_announces_the_next_step_it_waits_for(
    run_at: Callable[[str], list[Event]],
) -> None:
    """Engine already CONTINUOUS (it says so): nothing to catch up, one wait."""
    events = run_at("2026-11-06T12:00")
    started = time.time()
    confirm = MagicMock()
    query = MagicMock(return_value=SessionState.CONTINUOUS)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sched, "_query_engine_state", query)
        sched._run_scheduled(MagicMock(), WEEKDAYS_ONLY, confirm_sock=confirm)

    assert events[0] == (
        "announce",
        "CLOSING_AUCTION",
        "2026-11-06T15:00:00.000Z",
        started,
    )


def test_a_daily_start_after_the_close_announces_the_next_open(
    run_at: Callable[[str], list[Event]],
) -> None:
    events = run_at("2026-11-06T18:00")
    started = time.time()
    query = MagicMock(return_value=SessionState.CLOSED)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sched, "_query_engine_state", query)
        sched._run_forever(MagicMock(), WEEKDAYS_ONLY, MagicMock(), _until(events, 1))

    assert events == [("announce", "PRE_OPEN", MONDAY_OPEN, started)]


def test_a_daily_start_on_a_closed_day_announces_the_next_open(
    run_at: Callable[[str], list[Event]],
) -> None:
    events = run_at("2026-11-07T10:00")  # Saturday
    started = time.time()

    sched._run_forever(MagicMock(), WEEKDAYS_ONLY, None, _until(events, 1))

    assert events == [("announce", "PRE_OPEN", MONDAY_OPEN, started)]


def test_catch_up_carries_the_target_instead_of_an_announcement(
    run_at: Callable[[str], list[Event]],
) -> None:
    """The last catch-up transition already names the step being waited for."""
    events = run_at("2026-11-06T09:27")

    sched._run_scheduled(MagicMock(), WEEKDAYS_ONLY)

    assert [e[0] for e in events[:2]] == ["transition", "transition"]
    assert events[1][1:3] == ("OPENING_AUCTION", "2026-11-06T08:30:00.000Z")
    assert "announce" not in [e[0] for e in events]


def test_the_announcement_is_a_session_next_message() -> None:
    push = MagicMock()

    sched._announce_next(push, "PRE_OPEN", datetime(2026, 11, 9, 9, 0))

    topic, payload = decode(push.send_multipart.call_args.args[0])
    assert topic == "session.next"
    assert payload == {"next": {"state": "PRE_OPEN", "at": MONDAY_OPEN}}


def test_a_schedule_that_never_opens_names_no_open() -> None:
    never = ScheduleConfig(days={key: None for key in DAY_KEYS}, holidays=None)

    assert sched._next_open(never, date(2026, 11, 6), "Sweden") is None
