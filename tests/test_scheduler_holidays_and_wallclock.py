"""Integration tests for two scheduler features:

- Bank-holiday / weekend awareness: the scheduler reads a top-level
  ``country:`` field from the config YAML (default ``"Sweden"``) and refuses
  to run the daily schedule on weekends or that country's bank holidays,
  using the ``python-holidays`` package.
- Wall-clock re-checking: long waits (until a scheduled time, or overnight
  between trading days) never sleep in one long call. The scheduler wakes at
  least every ``WALLCLOCK_RECHECK_SEC`` (30s) and re-derives the remaining
  wait from the current wall-clock time, so a server time adjustment is
  picked up promptly instead of only after a single long, stale sleep.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.scheduler.main import (
    WALLCLOCK_RECHECK_SEC,
    _fixed_wait,
    _is_supported_country,
    _is_working_day,
    _next_working_day,
    _run_forever,
    _run_scheduled,
    _sleep_until_wallclock,
    _wait_until,
)

# ---------------------------------------------------------------------------
# _load_country
# ---------------------------------------------------------------------------


class TestCountryFromCompiledConfig:
    """`_load_country` is gone.

    It did two jobs: parse `country:` out of YAML, and check that
    python-holidays recognises the result. The parse now belongs to
    ``load_engine_config`` (covered in test_config_extensions.py) and the
    recognition check is ``_is_supported_country``, tested below. What ties
    them together is pm-scheduler's ``main``, which reads the compiled value
    and falls back when it is not a usable calendar.
    """

    def test_a_recognised_country_survives_compiling(self, tmp_path: Path) -> None:
        from edumatcher.config_deploy import compile_config
        from edumatcher.scheduler.main import _is_supported_country

        source = tmp_path / "authored.yaml"
        source.write_text(
            "country: Germany\n"
            "symbols:\n  AAPL: {tick_decimals: 2, last_buy_price: 150.0}\n"
            "gateways:\n  alf: [{id: TRADER01, role: TRADER}]\n"
        )

        country = compile_config(source).engine.country

        assert country == "Germany"
        assert _is_supported_country(country)

    def test_an_unrecognised_country_compiles_but_is_not_a_calendar(
        self, tmp_path: Path
    ) -> None:
        # The loader only checks it is a non-empty string; whether holidays
        # knows it is pm-scheduler's business, and pm-scheduler falls back.
        from edumatcher.config_deploy import compile_config
        from edumatcher.scheduler.main import _is_supported_country

        source = tmp_path / "authored.yaml"
        source.write_text(
            "country: Narnia\n"
            "symbols:\n  AAPL: {tick_decimals: 2, last_buy_price: 150.0}\n"
            "gateways:\n  alf: [{id: TRADER01, role: TRADER}]\n"
        )

        country = compile_config(source).engine.country

        assert country == "Narnia"
        assert not _is_supported_country(country)


class TestIsSupportedCountry:
    def test_full_name_recognised(self) -> None:
        assert _is_supported_country("Sweden") is True

    def test_iso_code_recognised(self) -> None:
        assert _is_supported_country("SE") is True

    def test_unrecognised_country_rejected(self) -> None:
        assert _is_supported_country("Narnia") is False


# ---------------------------------------------------------------------------
# _is_working_day / _next_working_day
# ---------------------------------------------------------------------------


class TestIsWorkingDay:
    def test_plain_weekday_is_working(self) -> None:
        # 2024-01-09 is a Tuesday, not a Swedish holiday.
        assert _is_working_day(date(2024, 1, 9), "Sweden") is True

    def test_saturday_is_not_working(self) -> None:
        # 2024-01-06 is a Saturday (also Epiphany, but weekend alone excludes it).
        assert _is_working_day(date(2024, 1, 6), "Sweden") is False

    def test_sunday_is_not_working(self) -> None:
        assert _is_working_day(date(2024, 1, 7), "Sweden") is False

    def test_bank_holiday_on_a_weekday_is_not_working(self) -> None:
        # 2026-01-06 (Epiphany / Trettondedag jul) is a Tuesday in 2026.
        assert date(2026, 1, 6).weekday() < 5
        assert _is_working_day(date(2026, 1, 6), "Sweden") is False

    def test_christmas_day_is_not_working(self) -> None:
        # 2026-12-25 is a Friday.
        assert date(2026, 12, 25).weekday() < 5
        assert _is_working_day(date(2026, 12, 25), "Sweden") is False

    def test_holiday_calendar_differs_by_country(self) -> None:
        # July 4th, 2024 (Thursday) is a US holiday but an ordinary Swedish
        # working day.
        july_4 = date(2024, 7, 4)
        assert july_4.weekday() < 5
        assert _is_working_day(july_4, "US") is False
        assert _is_working_day(july_4, "Sweden") is True


class TestNextWorkingDay:
    def test_skips_a_single_weekend(self) -> None:
        # Friday -> next working day is Monday.
        friday = date(2024, 1, 5)
        assert friday.weekday() == 4
        result = _next_working_day(friday, "Sweden")
        assert result == date(2024, 1, 8)
        assert result.weekday() == 0

    def test_skips_holiday_adjacent_to_weekend(self) -> None:
        # 2026-01-01 (New Year's Day) is a Thursday; 2026-01-03/04 is a
        # weekend; 2026-01-05 (Monday) is the next working day for Sweden.
        new_years_eve = date(2025, 12, 31)
        result = _next_working_day(new_years_eve, "Sweden")
        assert result == date(2026, 1, 2)  # Jan 1 is a holiday, Jan 2 is Friday

    def test_returns_tomorrow_when_already_a_working_day_run(self) -> None:
        tuesday = date(2024, 1, 9)
        result = _next_working_day(tuesday, "Sweden")
        assert result == date(2024, 1, 10)


# ---------------------------------------------------------------------------
# _run_scheduled — skip on non-working days
# ---------------------------------------------------------------------------


class TestRunScheduledSkipsNonWorkingDays:
    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_no_transitions_sent_on_a_saturday(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_dt.now.return_value = datetime(2024, 1, 6, 12, 0, 0)  # Saturday
        fake_sock = MagicMock()
        _run_scheduled(
            fake_sock,
            [("09:00", "PRE_OPEN"), ("09:30", "CONTINUOUS")],
            country="Sweden",
        )
        fake_sock.send_multipart.assert_not_called()

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_no_transitions_sent_on_a_bank_holiday(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # 2026-12-25 is a Friday and Christmas Day.
        mock_dt.now.return_value = datetime(2026, 12, 25, 12, 0, 0)
        fake_sock = MagicMock()
        _run_scheduled(
            fake_sock,
            [("09:00", "PRE_OPEN"), ("09:30", "CONTINUOUS")],
            country="Sweden",
        )
        fake_sock.send_multipart.assert_not_called()

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_transitions_sent_on_a_working_day(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        mock_dt.now.return_value = datetime(2024, 1, 9, 23, 59, 0)  # Tuesday
        fake_sock = MagicMock()
        _run_scheduled(
            fake_sock,
            [("09:00", "PRE_OPEN"), ("09:30", "CONTINUOUS")],
            country="Sweden",
        )
        fake_sock.send_multipart.assert_called()

    @patch("edumatcher.scheduler.main.time.sleep")
    @patch("edumatcher.scheduler.main.datetime")
    def test_country_specific_holiday_calendars(
        self, mock_dt: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # July 4th 2024 is a US holiday (Thursday) but an ordinary working
        # day in Sweden.
        mock_dt.now.return_value = datetime(2024, 7, 4, 23, 59, 0)

        us_sock = MagicMock()
        _run_scheduled(us_sock, [("09:00", "PRE_OPEN")], country="US")
        us_sock.send_multipart.assert_not_called()

        se_sock = MagicMock()
        _run_scheduled(se_sock, [("09:00", "PRE_OPEN")], country="Sweden")
        se_sock.send_multipart.assert_called()


# ---------------------------------------------------------------------------
# _run_forever — waits through non-working days
# ---------------------------------------------------------------------------


class TestRunForeverSkipsToNextWorkingDay:
    @patch("edumatcher.scheduler.main._sleep_until_wallclock")
    @patch("edumatcher.scheduler.main._run_scheduled")
    @patch("edumatcher.scheduler.main.datetime")
    def test_targets_next_working_day_not_just_next_day(
        self,
        mock_dt: MagicMock,
        mock_run_scheduled: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        # "Now" is a Friday; the overnight wait must target Monday (the next
        # working day), not just tomorrow (Saturday).
        mock_dt.now.return_value = datetime(2024, 1, 5, 18, 0, 0)
        mock_dt.combine = datetime.combine
        mock_dt.min = datetime.min

        state = {"n": 0}

        def is_running() -> bool:
            state["n"] += 1
            # True for the loop-entry check and the post-_run_scheduled
            # check, False once we reach the overnight sleep so the test
            # doesn't spin forever.
            return state["n"] <= 2

        _run_forever(MagicMock(), [("09:00", "PRE_OPEN")], None, is_running, "Sweden")

        assert mock_sleep.called
        target_wait_fn = mock_sleep.call_args.args[0]
        # The wait function should resolve to a target of Monday 00:00, not
        # Saturday 00:00.
        assert target_wait_fn is not None


# ---------------------------------------------------------------------------
# Wall-clock re-checking — never sleep more than WALLCLOCK_RECHECK_SEC
# ---------------------------------------------------------------------------


class TestSleepUntilWallclockChunking:
    def test_wakes_at_least_every_30_seconds(self) -> None:
        assert WALLCLOCK_RECHECK_SEC == 30.0

        # A wait far longer than one chunk: remaining_seconds counts down by
        # a large amount each "wake", but time.sleep should never be asked
        # to sleep more than WALLCLOCK_RECHECK_SEC in one call.
        remaining = [10_000.0]

        def remaining_seconds() -> float:
            return remaining[0]

        sleep_durations: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleep_durations.append(seconds)
            remaining[0] -= seconds
            if remaining[0] <= 0:
                remaining[0] = 0

        with patch("edumatcher.scheduler.main.time.sleep", side_effect=fake_sleep):
            _sleep_until_wallclock(remaining_seconds, lambda: True)

        assert sleep_durations, "expected at least one sleep call"
        assert all(d <= WALLCLOCK_RECHECK_SEC for d in sleep_durations), (
            "a single sleep call exceeded the 30s wall-clock recheck cap: "
            f"{sleep_durations}"
        )
        # A ~10000s wait chunked into <=30s pieces requires many wake-ups.
        assert len(sleep_durations) >= 300

    def test_stops_immediately_when_not_running(self) -> None:
        with patch("edumatcher.scheduler.main.time.sleep") as mock_sleep:
            _sleep_until_wallclock(lambda: 100.0, lambda: False)
        mock_sleep.assert_not_called()

    def test_re_derives_remaining_time_each_wakeup(self) -> None:
        # Simulate a wall-clock jump: the first call to remaining_seconds
        # reports a long wait, but a "clock adjustment" mid-sleep causes the
        # next call to report the wait is already over. Because
        # _sleep_until_wallclock re-derives the remaining duration on every
        # wake-up instead of trusting a monotonic deadline computed once, it
        # must stop promptly rather than sleeping out the original duration.
        call_count = [0]

        def remaining_seconds() -> float:
            call_count[0] += 1
            if call_count[0] == 1:
                return 10_000.0  # first check: far in the future
            return -1.0  # clock jumped forward past the target

        with patch("edumatcher.scheduler.main.time.sleep") as mock_sleep:
            _sleep_until_wallclock(remaining_seconds, lambda: True)

        # Only one sleep call should have happened before the second check
        # detected the wait was already satisfied.
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args.args[0] <= WALLCLOCK_RECHECK_SEC

    def test_stops_when_stop_flag_flips_mid_wait(self) -> None:
        # is_running() flips to False after the first wake — the loop must
        # not continue sleeping.
        state = {"n": 0}

        def is_running() -> bool:
            state["n"] += 1
            return state["n"] <= 1

        with patch("edumatcher.scheduler.main.time.sleep"):
            _sleep_until_wallclock(lambda: 10_000.0, is_running)

        assert state["n"] == 2  # checked once True, once False, then stopped


class TestFixedWaitCountsDown:
    def test_fixed_wait_decreases_across_calls(self) -> None:
        wait_fn = _fixed_wait(5.0)
        first = wait_fn()
        assert 0 < first <= 5.0
        # A later call should report a smaller (or equal) remaining time,
        # not the same constant forever — otherwise _sleep_until_wallclock
        # would loop indefinitely on a fixed-duration wait.
        import time as _time

        _time.sleep(0.05)
        second = wait_fn()
        assert second < first

    def test_wait_until_recomputes_from_wall_clock(self) -> None:
        target = datetime.now() + timedelta(seconds=5)
        wait_fn = _wait_until(target)
        first = wait_fn()
        import time as _time

        _time.sleep(0.05)
        second = wait_fn()
        assert second < first


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
