"""Tests for the weekdays/weekend/individual-day/holidays schedule shortcuts.

Covers the resolution rules end to end, from raw YAML (``config_loader``)
through to the shared per-date resolution helper
(``schedule_resolve.resolve_day``) that pm-scheduler and pm-engine both use.
Cross-cutting concerns owned by other modules -- console/config_show
rendering, cverifier's own checks, the wire shape -- have their own test
coverage and are not duplicated here.
"""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest

from edumatcher.engine.config_loader import (
    DAY_KEYS,
    DaySchedule,
    ScheduleConfig,
    load_engine_config,
)
from edumatcher.engine.schedule_resolve import is_bank_holiday, resolve_day

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


_BASE = """
symbols:
  AAPL: {}
gateways:
  alf:
    - id: TRADER01
"""


def _load(tmp_path: Path, schedule_yaml: str) -> ScheduleConfig | None:
    return load_engine_config(
        _write_yaml(tmp_path, _BASE + textwrap.dedent(schedule_yaml))
    ).schedule


_WEEKDAYS = """
schedule:
  weekdays:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"
"""

_WEEKEND = """
  weekend:
    pre_open: "10:00"
    opening_auction_start: "10:25"
    continuous_start: "10:30"
    closing_auction_start: "14:00"
    closing_auction_end: "14:05"
"""

_HOLIDAYS = """
  holidays:
    pre_open: "10:00"
    opening_auction_start: "10:25"
    continuous_start: "10:30"
    closing_auction_start: "13:00"
    closing_auction_end: "13:05"
"""


# ---------------------------------------------------------------------------
# Valid configurations
# ---------------------------------------------------------------------------


class TestValidSchedules:
    def test_weekdays_only_leaves_weekend_and_holidays_closed(
        self, tmp_path: Path
    ) -> None:
        cfg = _load(tmp_path, _WEEKDAYS)
        assert cfg is not None
        for key in ("mon", "tue", "wed", "thu", "fri"):
            day = cfg.days[key]
            assert day is not None
            assert day.pre_open == "09:00"
        assert cfg.days["sat"] is None
        assert cfg.days["sun"] is None
        assert cfg.holidays is None

    def test_weekdays_plus_weekend_shortcut(self, tmp_path: Path) -> None:
        cfg = _load(tmp_path, _WEEKDAYS + _WEEKEND)
        assert cfg is not None
        sat = cfg.days["sat"]
        assert sat is not None
        assert sat == cfg.days["sun"]
        assert sat.pre_open == "10:00"
        # weekend: doesn't touch the weekday entries.
        mon = cfg.days["mon"]
        assert mon is not None
        assert mon.pre_open == "09:00"

    def test_individual_day_overrides_weekdays_shortcut(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            _WEEKDAYS + """
  fri:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "13:00"
    closing_auction_end: "13:05"
""",
        )
        assert cfg is not None
        fri = cfg.days["fri"]
        assert fri is not None
        assert fri.closing_auction_end == "13:05"
        # Mon-Thu still get the weekdays: block unchanged.
        for key in ("mon", "tue", "wed", "thu"):
            day = cfg.days[key]
            assert day is not None
            assert day.closing_auction_end == "16:05"

    def test_weekdays_weekend_and_holidays_all_distinct(self, tmp_path: Path) -> None:
        cfg = _load(tmp_path, _WEEKDAYS + _WEEKEND + _HOLIDAYS)
        assert cfg is not None
        mon = cfg.days["mon"]
        sat = cfg.days["sat"]
        assert mon is not None
        assert sat is not None
        assert mon.pre_open == "09:00"
        assert sat.pre_open == "10:00"
        assert cfg.holidays is not None
        assert cfg.holidays.closing_auction_start == "13:00"
        # All three are genuinely distinct DaySchedule values.
        assert len({mon, sat, cfg.holidays}) == 3

    def test_weekend_only_exchange_leaves_weekdays_closed(self, tmp_path: Path) -> None:
        cfg = _load(tmp_path, "schedule:" + _WEEKEND)
        assert cfg is not None
        for key in ("mon", "tue", "wed", "thu", "fri"):
            assert cfg.days[key] is None
        assert cfg.days["sat"] is not None
        assert cfg.days["sat"] == cfg.days["sun"]

    def test_fully_explicit_individual_days_no_shortcuts(self, tmp_path: Path) -> None:
        block = """
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"
"""
        yaml = "schedule:\n" + "\n".join(f"  {key}:{block}" for key in DAY_KEYS)
        cfg = _load(tmp_path, yaml)
        assert cfg is not None
        for key in DAY_KEYS:
            day = cfg.days[key]
            assert day is not None
            assert day.pre_open == "09:00"

    def test_individual_sat_sun_without_weekend_shortcut(self, tmp_path: Path) -> None:
        # sat/sun specified individually (not via weekend:) is legal even
        # when they happen to be identical -- weekend: is a convenience, not
        # a requirement.
        cfg = _load(
            tmp_path,
            """
schedule:
  sat:
    pre_open: "10:00"
    opening_auction_start: "10:25"
    continuous_start: "10:30"
    closing_auction_start: "14:00"
    closing_auction_end: "14:05"
  sun:
    pre_open: "10:00"
    opening_auction_start: "10:25"
    continuous_start: "10:30"
    closing_auction_start: "14:00"
    closing_auction_end: "14:05"
""",
        )
        assert cfg is not None
        assert cfg.days["sat"] == cfg.days["sun"]
        assert cfg.days["mon"] is None

    def test_holidays_alone_without_any_day_configured(self, tmp_path: Path) -> None:
        cfg = _load(tmp_path, "schedule:" + _HOLIDAYS)
        assert cfg is not None
        assert all(cfg.days[key] is None for key in DAY_KEYS)
        assert cfg.holidays is not None

    def test_no_schedule_section_at_all(self, tmp_path: Path) -> None:
        assert _load(tmp_path, "") is None


# ---------------------------------------------------------------------------
# Invalid configurations
# ---------------------------------------------------------------------------


class TestInvalidSchedules:
    def test_weekend_and_sat_combined_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="weekend.*sat"):
            _load(
                tmp_path,
                "schedule:" + _WEEKEND + """
  sat:
    pre_open: "11:00"
    opening_auction_start: "11:25"
    continuous_start: "11:30"
    closing_auction_start: "13:00"
    closing_auction_end: "13:05"
""",
            )

    def test_weekend_and_sun_combined_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="weekend.*sat"):
            _load(
                tmp_path,
                "schedule:" + _WEEKEND + """
  sun:
    pre_open: "11:00"
    opening_auction_start: "11:25"
    continuous_start: "11:30"
    closing_auction_start: "13:00"
    closing_auction_end: "13:05"
""",
            )

    def test_incomplete_day_block_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="missing required field"):
            _load(
                tmp_path,
                """
schedule:
  weekdays:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    # closing_auction_end omitted
""",
            )

    def test_unknown_schedule_key_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unknown field"):
            _load(
                tmp_path,
                """
schedule:
  weekdys:
    pre_open: "09:00"
    opening_auction_start: "09:25"
    continuous_start: "09:30"
    closing_auction_start: "16:00"
    closing_auction_end: "16:05"
""",
            )

    def test_non_mapping_day_block_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="mapping"):
            _load(tmp_path, "schedule:\n  weekdays: not-a-mapping\n")


# ---------------------------------------------------------------------------
# resolve_day / is_bank_holiday -- the shared per-date lookup
# ---------------------------------------------------------------------------


class TestResolveDay:
    _WEEKDAY = DaySchedule(
        pre_open="09:00",
        opening_auction_start="09:25",
        continuous_start="09:30",
        closing_auction_start="16:00",
        closing_auction_end="16:05",
    )
    _HOLIDAY = DaySchedule(
        pre_open="10:00",
        opening_auction_start="10:25",
        continuous_start="10:30",
        closing_auction_start="13:00",
        closing_auction_end="13:05",
    )

    def _cfg(self, *, holidays: DaySchedule | None) -> ScheduleConfig:
        return ScheduleConfig(
            days={
                "mon": self._WEEKDAY,
                "tue": self._WEEKDAY,
                "wed": self._WEEKDAY,
                "thu": self._WEEKDAY,
                "fri": self._WEEKDAY,
                "sat": None,
                "sun": None,
            },
            holidays=holidays,
        )

    def test_ordinary_weekday_resolves_to_its_own_entry(self) -> None:
        # 2024-01-09 is a plain Tuesday, not a Swedish holiday.
        cfg = self._cfg(holidays=None)
        assert resolve_day(cfg, date(2024, 1, 9), "Sweden") == self._WEEKDAY

    def test_weekend_with_no_entry_is_closed(self) -> None:
        cfg = self._cfg(holidays=None)
        assert resolve_day(cfg, date(2024, 1, 6), "Sweden") is None  # Saturday

    def test_bank_holiday_uses_the_holidays_entry_not_the_weekday_one(
        self,
    ) -> None:
        # 2026-01-06 (Epiphany) is a Tuesday in 2026.
        cfg = self._cfg(holidays=self._HOLIDAY)
        holiday_day = date(2026, 1, 6)
        assert is_bank_holiday(holiday_day, "Sweden") is True
        assert resolve_day(cfg, holiday_day, "Sweden") == self._HOLIDAY

    def test_bank_holiday_with_no_holidays_entry_is_closed(self) -> None:
        cfg = self._cfg(holidays=None)
        holiday_day = date(2026, 1, 6)
        assert resolve_day(cfg, holiday_day, "Sweden") is None

    def test_holiday_override_takes_priority_over_the_weekday_entry(
        self,
    ) -> None:
        # 2026-12-25 (Christmas) is a Friday, which would otherwise resolve
        # to _WEEKDAY -- the holiday entry must win.
        cfg = self._cfg(holidays=self._HOLIDAY)
        christmas = date(2026, 12, 25)
        assert christmas.weekday() == 4
        assert resolve_day(cfg, christmas, "Sweden") == self._HOLIDAY
