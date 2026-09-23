"""
Shared session-schedule resolution: "which DaySchedule applies on date X".

Both pm-scheduler (deciding what to drive today) and the engine (publishing
a `today`/`today_is_holiday` convenience field alongside the full weekly
table in its wire replies) need to answer the same question: given a
resolved :class:`~edumatcher.engine.config_loader.ScheduleConfig` and a
calendar date, which `DaySchedule` (if any) applies?

This lives in one place so the two processes can never disagree about it --
exactly the kind of drift the compiled-config artifact already exists to
prevent for the rest of the config tree (see `config_artifact.py`).
"""

from __future__ import annotations

from datetime import date

import holidays

from edumatcher.engine.config_loader import DAY_KEYS, DaySchedule, ScheduleConfig


def is_bank_holiday(day: date, country: str) -> bool:
    """Return ``True`` if ``day`` is a bank holiday in ``country``.

    Weekends are NOT considered here -- a weekend day is resolved through
    :data:`DAY_KEYS` like any other day of the week (it may carry its own
    schedule now), not through the holiday calendar. Callers that also want
    "is this a non-trading day at all" combine this with the weekday lookup
    in :func:`resolve_day`.
    """
    return day in holidays.country_holidays(country)


def resolve_day(cfg: ScheduleConfig, day: date, country: str) -> DaySchedule | None:
    """Return the :class:`DaySchedule` in effect on ``day``, or ``None`` for
    CLOSED.

    A bank holiday for ``country`` takes priority over the weekday's own
    entry: ``cfg.holidays`` applies (and may itself be ``None``, meaning
    CLOSED on holidays) whenever ``day`` is a recognised holiday, regardless
    of what that weekday's ordinary schedule says.
    """
    if is_bank_holiday(day, country):
        return cfg.holidays
    return cfg.days[DAY_KEYS[day.weekday()]]
