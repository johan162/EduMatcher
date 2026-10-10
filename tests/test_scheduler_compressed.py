"""pm-scheduler --speed: a simulated local clock for compressed soak runs."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import edumatcher.scheduler.main as sched
from edumatcher.scheduler.main import DEFAULT_SCHEDULE, _Clock, _next_scheduled_day


class _Wall:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def time(self) -> float:
        return self.t


@pytest.fixture()
def wall(monkeypatch: pytest.MonkeyPatch) -> _Wall:
    w = _Wall()
    monkeypatch.setattr("edumatcher.scheduler.main.time.time", w.time)
    return w


def test_sim_time_runs_speed_times_faster(wall: _Wall) -> None:
    start = datetime(2026, 11, 6, 15, 0)  # a Friday
    clock = _Clock(600.0, start)
    wall.t += 6.0
    assert clock.now() == start + timedelta(hours=1)
    # 16:05 is 5 simulated minutes away: half a wall second
    assert clock.seconds_until(datetime(2026, 11, 6, 16, 5)) == pytest.approx(0.5)


def test_weekend_passes_in_sim_time(wall: _Wall) -> None:
    clock = _Clock(3600.0, datetime(2026, 11, 6, 17, 0))  # Friday evening
    monday = _next_scheduled_day(DEFAULT_SCHEDULE, clock.now().date(), "Sweden")
    assert monday.isoformat() == "2026-11-09"
    target = datetime.combine(monday, datetime.min.time())
    # 55 simulated hours to Monday 00:00 = 55 wall seconds
    assert clock.seconds_until(target) == pytest.approx(55.0)


def test_countdown_instant_is_wall_time(wall: _Wall) -> None:
    clock = _Clock(60.0, datetime(2026, 11, 9, 9, 0))
    target = datetime(2026, 11, 9, 9, 30)  # 30 sim minutes = 30 wall seconds
    instant = clock.wall_instant(target)
    assert instant.tzinfo is not None
    delta = instant - datetime.now().astimezone()
    assert abs(delta.total_seconds() - 30.0) < 2.0


def test_default_clock_is_the_wall_clock() -> None:
    clock = _Clock()
    assert abs((clock.now() - datetime.now()).total_seconds()) < 1.0


@pytest.mark.parametrize(
    "argv",
    [["--speed", "10"], ["--start", "2026-11-02T08:55"], ["--daily", "--speed", "0"]],
)
def test_speed_needs_daily_and_a_positive_factor(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["pm-scheduler", *argv])
    monkeypatch.setattr(sched, "_configure_logging", lambda _a: 20)
    with pytest.raises(SystemExit) as exc:
        sched.main()
    assert exc.value.code == 2
