"""Scheduler deadlines, countdowns and catch-up across Stockholm DST changes."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import edumatcher.scheduler.main as sched
from edumatcher.engine.config_loader import DAY_KEYS, DaySchedule, ScheduleConfig
from edumatcher.config_deploy import deploy
from edumatcher.health import HealthReporter


@pytest.fixture(params=["UTC", "America/New_York"])
def stockholm(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[None]:
    if not hasattr(time, "tzset"):
        pytest.skip("Requires POSIX local timezone support")
    original = os.environ.get("TZ")
    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    monkeypatch.setattr(sched, "_clock", sched._Clock())
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()


@pytest.mark.parametrize(
    ("start", "target", "hours", "utc"),
    [
        ("2026-10-24T23:00:00+02:00", "2026-10-25T09:00", 11, "08:00"),
        ("2026-10-25T02:00:00+01:00", "2026-10-25T09:00", 7, "08:00"),
        ("2026-03-28T23:00:00+01:00", "2026-03-29T09:00", 9, "07:00"),
    ],
)
def test_daytime_deadlines_across_dst(
    stockholm: None,
    monkeypatch: pytest.MonkeyPatch,
    start: str,
    target: str,
    hours: int,
    utc: str,
) -> None:
    monkeypatch.setattr(time, "time", lambda: datetime.fromisoformat(start).timestamp())
    monkeypatch.setattr(sched, "_clock", sched._Clock())
    local = datetime.fromisoformat(target)
    assert sched._clock.seconds_until(local) == hours * 3600
    assert sched._to_utc_iso(local) == f"{local.date()}T{utc}:00.000Z"


@pytest.mark.parametrize("fold", [0, 1])
def test_repeated_hour_always_uses_second_occurrence(
    stockholm: None, monkeypatch: pytest.MonkeyPatch, fold: int
) -> None:
    now = datetime(2026, 10, 25, 0, tzinfo=UTC).timestamp()
    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setattr(sched, "_clock", sched._Clock())
    target = datetime(2026, 10, 25, 2, 30, fold=fold)
    assert sched._seconds_until_local(target) == 90 * 60
    assert sched._to_utc_iso(target) == "2026-10-25T01:30:00.000Z"


def test_spring_gap_wait_and_countdown_agree(
    stockholm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 3, 29, 0, tzinfo=UTC).timestamp()
    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setattr(sched, "_clock", sched._Clock())
    target = datetime(2026, 3, 29, 2, 30)
    assert sched._seconds_until_local(target) == 90 * 60
    assert sched._to_utc_iso(target) == "2026-03-29T01:30:00.000Z"


@pytest.mark.parametrize(
    ("start", "opening"),
    [
        ("2026-10-25T00:00:00+02:00", "2026-10-25T01:10:00+00:00"),
        ("2026-10-25T02:45:00+02:00", "2026-10-25T01:10:00+00:00"),
        ("2026-10-25T02:20:00+01:00", "2026-10-25T01:20:00+00:00"),
    ],
)
def test_repeated_hour_schedule_and_restart(
    stockholm: None, monkeypatch: pytest.MonkeyPatch, start: str, opening: str
) -> None:
    epoch = datetime.fromisoformat(start).timestamp()

    class LocalDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> LocalDatetime:
            return cls.fromtimestamp(epoch, ZoneInfo("Europe/Stockholm"))

    monkeypatch.setattr(sched, "datetime", LocalDatetime)
    monkeypatch.setattr(time, "time", lambda: epoch)
    monkeypatch.setattr(sched, "_clock", sched._Clock())

    # Advance directly to each resolved deadline without real sleeps.
    def sleep(seconds: float) -> None:
        nonlocal epoch
        epoch += seconds

    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(sched, "LIVENESS_CHUNK_SEC", 3600.0)
    day = DaySchedule("01:50", "02:10", "02:30", "03:10", "03:15")
    cfg = ScheduleConfig(days={key: day for key in DAY_KEYS}, holidays=None)
    observed: list[tuple[str, float, str]] = []

    def dispatch(
        push: object,
        confirm: object,
        state: str,
        next_state: str = "",
        next_at: str = "",
        on_wake: object = None,
    ) -> None:
        observed.append((state, epoch, next_at))

    monkeypatch.setattr(sched, "_dispatch_transition", dispatch)
    sched._run_scheduled(MagicMock(), cfg)
    assert [state for state, _, _ in observed] == [
        "PRE_OPEN",
        "OPENING_AUCTION",
        "CONTINUOUS",
        "CLOSING_AUCTION",
        "CLOSED",
    ]
    assert observed[1][1] == datetime.fromisoformat(opening).timestamp()
    assert observed[2][1] == datetime(2026, 10, 25, 1, 30, tzinfo=UTC).timestamp()
    assert observed[1][2] == "2026-10-25T01:30:00.000Z"


def test_stockholm_rollback_instant(stockholm: None) -> None:
    tz = ZoneInfo("Europe/Stockholm")
    before = datetime(2026, 10, 25, 0, 59, 59, tzinfo=UTC).astimezone(tz)
    after = datetime(2026, 10, 25, 1, tzinfo=UTC).astimezone(tz)
    assert (before.hour, before.minute, before.fold) == (2, 59, 0)
    assert (after.hour, after.minute, after.fold) == (2, 0, 1)


def test_clock_date_and_catch_up_use_session_timezone(
    stockholm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    epoch = datetime(2026, 10, 24, 22, 30, tzinfo=UTC).timestamp()

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> FixedDatetime:
            assert isinstance(tz, ZoneInfo)
            return cls.fromtimestamp(epoch, tz)

    monkeypatch.setattr(sched, "datetime", FixedDatetime)
    clock = sched._Clock()
    now = clock.now()
    assert now.isoformat() == "2026-10-25T00:30:00"
    assert clock.is_past(datetime(2026, 10, 25, 0, 15), now)
    assert not clock.is_past(datetime(2026, 10, 25, 0, 45), now)


@pytest.mark.parametrize(
    "mode", ["wall", "naive-start", "offset-start", "current-start"]
)
@pytest.mark.parametrize("timezone", ["Europe/Stockholm", "Asia/Tokyo"])
def test_main_loads_session_timezone(
    stockholm: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    timezone: str,
) -> None:
    source = tmp_path / "engine_config.yaml"
    source.write_text(
        f"locale:\n  session_timezone: {timezone}\n"
        "symbols:\n  AAPL: {tick_decimals: 2, last_buy_price: 150.0}\n"
        "participants: [{id: TRADER01, role: TRADER}]\n"
    )
    artifact = tmp_path / "engine_config.json"
    deploy(source, artifact)
    monkeypatch.setattr("edumatcher.config_artifact.COMPILED_CONFIG_FILE", artifact)
    monkeypatch.setattr(sched, "_configure_logging", lambda args: 20)
    monkeypatch.setattr(sched, "make_pusher", lambda addr: MagicMock())
    monkeypatch.setattr(HealthReporter, "start_from_compiled_config", lambda name: None)
    monkeypatch.delenv("EDUMATCHER_SCHEDULER_SPEED", raising=False)
    monkeypatch.delenv("EDUMATCHER_SCHEDULER_START", raising=False)
    argv = ["pm-scheduler", "--no-confirm"]
    if mode != "wall":
        argv += ["--daily", "--speed", "60"]
    if mode == "naive-start":
        argv += ["--start", "2026-10-25T00:30"]
    elif mode == "offset-start":
        argv += ["--start", "2026-10-25T00:30+00:00"]
    monkeypatch.setattr("sys.argv", argv)
    captured: list[sched._Clock] = []
    monkeypatch.setattr(
        sched, "_run_scheduled", lambda *a, **kw: captured.append(sched._clock)
    )
    monkeypatch.setattr(
        sched, "_run_forever", lambda *a, **kw: captured.append(sched._clock)
    )
    before = datetime.now(ZoneInfo(timezone)).replace(tzinfo=None)
    sched.main()
    assert len(captured) == 1
    clock = captured[0]
    assert str(clock.timezone) == timezone
    # The start point, not clock.now(): at --speed 60 every wall millisecond
    # main() spends after building the clock (the first holiday-calendar load
    # alone is ~70 ms) moves now() 60 ms, which made a tolerance on now() flaky.
    if mode != "wall":
        assert clock.speed == 60
    if mode == "offset-start":
        expected = (
            datetime.fromisoformat("2026-10-25T00:30+00:00")
            .astimezone(ZoneInfo(timezone))
            .replace(tzinfo=None)
        )
        assert clock._start == expected
    elif mode == "naive-start":
        assert clock._start == datetime(2026, 10, 25, 0, 30)
    elif mode == "current-start":
        assert clock._start is not None
        assert abs((clock._start - before).total_seconds()) < 5
    else:
        target = datetime(2026, 10, 25, 9)
        expected_utc = target.replace(tzinfo=ZoneInfo(timezone)).astimezone(UTC)
        assert clock.wall_instant(target) == expected_utc


@pytest.mark.parametrize(
    ("start", "opening_utc", "hours"),
    [
        ("2026-10-24T23:00:00+02:00", "2026-10-25T08:00:00+00:00", 11),
        ("2026-03-28T23:00:00+01:00", "2026-03-29T07:00:00+00:00", 9),
    ],
)
def test_daily_rollover_runs_each_session_once(
    stockholm: None,
    monkeypatch: pytest.MonkeyPatch,
    start: str,
    opening_utc: str,
    hours: int,
) -> None:
    epoch = datetime.fromisoformat(start).timestamp()
    started = epoch

    class LocalDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> LocalDatetime:
            return cls.fromtimestamp(epoch, ZoneInfo("Europe/Stockholm"))

    def sleep(seconds: float) -> None:
        nonlocal epoch
        epoch += seconds

    monkeypatch.setattr(sched, "datetime", LocalDatetime)
    monkeypatch.setattr(time, "time", lambda: epoch)
    monkeypatch.setattr(time, "sleep", sleep)
    monkeypatch.setattr(sched, "_clock", sched._Clock())
    monkeypatch.setattr(sched, "LIVENESS_CHUNK_SEC", 3600.0)
    cfg = ScheduleConfig(
        days={
            key: None if key == "sat" else sched._DEFAULT_DAY_SCHEDULE
            for key in DAY_KEYS
        },
        holidays=None,
    )
    observed: list[tuple[str, float]] = []

    def dispatch(
        push: object,
        confirm: object,
        state: str,
        next_state: str = "",
        next_at: str = "",
        on_wake: object = None,
    ) -> None:
        observed.append((state, epoch))

    monkeypatch.setattr(sched, "_dispatch_transition", dispatch)
    sched._run_forever(MagicMock(), cfg, None, lambda: len(observed) < 10)
    states = [
        state
        for _, state in sched._transitions_for_day_schedule(sched._DEFAULT_DAY_SCHEDULE)
    ]
    assert [state for state, _ in observed] == states * 2
    assert observed[0][1] == datetime.fromisoformat(opening_utc).timestamp()
    assert observed[0][1] - started == hours * 3600
    assert observed[5][1] - observed[0][1] == 24 * 3600
