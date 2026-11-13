"""One business date: the session timezone's, wherever the host is (WP-ENG05).

C9 (engine review 2026-11): the end-of-day archive and the schedule's
``today`` used the host's local date, the DAY-order restore the session
timezone's. C6: ``GET /reference`` cached ``today`` at load time, so from the
second day of a run it reported yesterday, and its ``config_version`` hashed
the date. Here the host runs on UTC and the exchange in Auckland, where
Christmas Day starts eleven hours before it does on the host.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.engine.config_loader import DAY_KEYS, DaySchedule, ScheduleConfig
from edumatcher.engine.main import Engine
from edumatcher.models.order import Order, OrderType, Side, TIF
from tests.engine_harness import SYMBOL, FakeSock, make_engine, msgs

#: 12:30 on 25 December in Auckland (NZDT, UTC+13); still the 24th on the host.
XMAS_IN_AUCKLAND = datetime(2026, 12, 24, 23, 30, tzinfo=UTC)


class _Clock(datetime):
    """``datetime`` frozen at ``at``, on a host whose local zone is UTC."""

    at = XMAS_IN_AUCKLAND

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Any:
        return cls.at.astimezone(tz) if tz else cls.at.replace(tzinfo=None)


def _engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kw: Any
) -> tuple[Engine, FakeSock]:
    monkeypatch.setattr(_Clock, "at", XMAS_IN_AUCKLAND)
    monkeypatch.setattr(engine_main, "datetime", _Clock)
    monkeypatch.setattr(engine_main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(engine_main, "GTC_COMBOS_FILE", tmp_path / "no_combos.json")
    engine, pub = make_engine(monkeypatch, tmp_path, **kw)
    assert engine._engine_config is not None
    engine._engine_config.locale.country = "NZ"
    engine._engine_config.locale.session_timezone = "Pacific/Auckland"
    day = DaySchedule("08:00", "09:50", "10:00", "16:50", "17:00")
    engine._engine_config.schedule = ScheduleConfig(
        days={key: day for key in DAY_KEYS}, holidays=None
    )
    engine._rebuild_reference_cache()
    return engine, pub


def _day_order(placed: datetime) -> Order:
    order = Order.create(
        symbol=SYMBOL,
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=5,
        gateway_id="GW01",
        tif=TIF.DAY,
        price_ticks=9900,
    )
    order.ts_ns = int(placed.timestamp() * 1e9)
    return order


def _reference_schedule(engine: Engine, pub: FakeSock) -> dict[str, Any]:
    engine._handle_reference_request({"gateway_id": "GW01"})
    return msgs(pub, "system.reference.GW01")[-1]


def test_the_archive_restore_and_schedule_share_the_session_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    this_morning = _day_order(datetime(2026, 12, 24, 12, 0, tzinfo=UTC))  # 01:00 25th
    last_night = _day_order(datetime(2026, 12, 24, 10, 0, tzinfo=UTC))  # 23:00 24th
    engine, pub = _engine(monkeypatch, tmp_path, gtc_orders=[this_morning, last_night])

    engine._restore_gtc()
    engine._archive_eod()
    engine._handle_session_schedule_request({"gateway_id": "GW01"})

    assert [o.id for o in engine.books[SYMBOL].resting_orders()] == [this_morning.id]
    assert [p.name for p in (tmp_path / "eod").iterdir()] == ["2026-12-25"]
    schedule = msgs(pub, "system.session_schedule.GW01")[-1]["schedule"]
    assert schedule["today_is_holiday"] is True
    assert schedule["today"] is None  # holidays: CLOSED


def test_the_reference_schedule_follows_the_day_without_a_reload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    monkeypatch.setattr(_Clock, "at", XMAS_IN_AUCKLAND - timedelta(days=1))
    christmas_eve = _reference_schedule(engine, pub)

    monkeypatch.setattr(_Clock, "at", XMAS_IN_AUCKLAND)
    christmas = _reference_schedule(engine, pub)

    assert christmas_eve["schedule"]["schedule"]["today_is_holiday"] is False
    assert christmas_eve["schedule"]["schedule"]["today"] is not None
    assert christmas["schedule"]["schedule"]["today_is_holiday"] is True
    assert christmas["schedule"]["schedule"]["today"] is None
    upcoming = christmas["schedule"]["schedule"]["upcoming_holidays"]
    assert upcoming[0]["date"] == date(2026, 12, 25).isoformat()
    assert christmas["config_version"] == christmas_eve["config_version"]


def test_both_schedule_replies_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    monkeypatch.setattr(_Clock, "at", XMAS_IN_AUCKLAND + timedelta(days=3))

    reference = _reference_schedule(engine, pub)["schedule"]["schedule"]
    engine._handle_session_schedule_request({"gateway_id": "GW01"})
    session = msgs(pub, "system.session_schedule.GW01")[-1]["schedule"]

    assert reference == session
