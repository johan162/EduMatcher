"""pm-viewer's session statistics and trade tape.

Regression coverage for four defects in how pm-viewer built its header and
TRADES panel:

* the TRADES panel showed at most 5 rows, because it rendered the book
  snapshot's ``recent_trades``, which the engine truncates to 5;
* the seeded volume double-counted the first snapshot's ``recent_trades``,
  which the stats database had already counted;
* high/low were sampled from the throttled snapshot's ``last_price``, so a
  print between two snapshots never reached them;
* prices were always shown with 4 decimals, whatever the symbol's tick size.

It also pins the stats-database seed reading integer *ticks*, not display
prices, and "today", the clock and trade times following the exchange's
session timezone recorded in the stats database rather than the host's.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console

from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.stats.main import SCHEMA
from edumatcher.viewer import main as viewer_main
from edumatcher.viewer.main import (
    _MAX_RECENT_TRADES,
    _build_display,
    _load_stats_from_db,
    _SessionStats,
)
from tests.test_viewer_symbol_picker import _run_viewer


def _tid(n: int, run: int = 1) -> str:
    return f"{run:06d}-{n:09d}"


def _trade(
    n: int, price: float, qty: int = 100, symbol: str = "AAPL"
) -> dict[str, Any]:
    return {
        "id": _tid(n),
        "symbol": symbol,
        "price": price,
        "quantity": qty,
        "ts_ns": 1_790_000_000_000_000_000 + n * 1_000_000,
        "tick_decimals": 2,
    }


def _capture(renderable: Any, *, width: int = 200, height: int = 60) -> str:
    console = Console(width=width, height=height, force_terminal=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _snapshot(**extra: Any) -> dict[str, Any]:
    return {"bids": [], "asks": [], "recent_trades": [], "tick_decimals": 2, **extra}


# ========================================================================
# Trade tape
# ========================================================================


def test_the_trades_panel_shows_more_than_the_five_a_snapshot_carries() -> None:
    stats = _SessionStats()
    for n in range(1, 21):
        stats.add_trade(_trade(n, 100 + n / 100))

    out = _capture(_build_display(_snapshot(), "AAPL", stats=stats, size=(200, 60)))

    for n in range(1, 21):
        assert f"{100 + n / 100:.2f}" in out


def test_the_tape_keeps_only_the_newest_trades() -> None:
    stats = _SessionStats()
    for n in range(1, _MAX_RECENT_TRADES + 11):
        stats.add_trade(_trade(n, 100.0))

    assert len(stats.tape) == _MAX_RECENT_TRADES
    assert stats.tape[0]["id"] == _tid(11)
    assert stats.tape[-1]["id"] == _tid(_MAX_RECENT_TRADES + 10)


def test_a_late_older_trade_is_placed_by_id_not_by_arrival() -> None:
    stats = _SessionStats()
    stats.add_trade(_trade(2, 11.0))
    stats.add_trade(_trade(1, 10.0))

    assert [t["id"] for t in stats.tape] == [_tid(1), _tid(2)]
    assert stats.open == 10.0
    assert stats.close == 11.0


# ========================================================================
# Volume
# ========================================================================


def test_snapshot_repeats_and_the_live_print_count_once() -> None:
    stats = _SessionStats()
    trades = [_trade(1, 10.0, 100), _trade(2, 10.5, 50)]
    stats.update(_snapshot(recent_trades=trades))
    stats.update(_snapshot(recent_trades=trades))
    stats.add_trade(trades[1])

    assert stats.volume == 150


# 2026-06-14T12:00:00Z is already 2026-06-15 02:00 in the session timezone
# (UTC+14), so a reader using the UTC or host date picks the wrong trading day.
_SESSION_TZ = "Pacific/Kiritimati"
_NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def _stats_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        viewer_main, "time", SimpleNamespace(time=lambda: _NOW.timestamp())
    )
    db = tmp_path / "stats.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO stats_meta (key, value) VALUES ('session_timezone', ?)",
        (_SESSION_TZ,),
    )
    # Prices are integer ticks at 2 decimals: 16723 is 167.23.
    conn.execute(
        "INSERT INTO daily_stats (date, symbol, open_price, high_price, low_price, "
        "close_price, volume, trade_count, tick_decimals) "
        "VALUES ('2026-06-15', 'AAPL', ?, ?, ?, ?, ?, ?, 2)",
        (16700, 16750, 16690, 16723, 300, 3),
    )
    # The UTC date's row: yesterday's session, so only the previous close.
    conn.execute(
        "INSERT INTO daily_stats (date, symbol, open_price, high_price, low_price, "
        "close_price, volume, trade_count, tick_decimals) "
        "VALUES ('2026-06-14', 'AAPL', 16500, 16650, 16400, 16600, 900, 9, 2)"
    )
    rows = [
        # 23:30 session time on 2026-06-14: yesterday, though the same UTC date.
        (_NOW - timedelta(hours=2, minutes=30), _tid(1), 16600),
        (_NOW - timedelta(seconds=3), _tid(2), 16700),
        (_NOW - timedelta(seconds=2), _tid(3), 16750),
        (_NOW - timedelta(seconds=1), _tid(4), 16723),
    ]
    for ts, tid, px in rows:
        conn.execute(
            "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, tick_decimals) "
            "VALUES (?, ?, 'AAPL', ?, 100, 2)",
            (ts.isoformat(timespec="milliseconds"), tid, px),
        )
    conn.commit()
    conn.close()
    return db


def test_the_database_seed_is_read_in_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stats = _load_stats_from_db(_stats_db(tmp_path, monkeypatch), "aapl")

    assert (stats.open, stats.high, stats.low, stats.close) == (
        167.0,
        167.5,
        166.9,
        167.23,
    )
    assert stats.volume == 300
    assert stats.tick_decimals == 2
    assert [t["price"] for t in stats.tape] == [167.0, 167.5, 167.23]
    assert stats.counted_through == _tid(4)


def test_today_is_the_trading_date_in_the_session_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stats = _load_stats_from_db(_stats_db(tmp_path, monkeypatch), "AAPL")

    assert stats.tz == ZoneInfo(_SESSION_TZ)
    # 2026-06-15 is today, so 2026-06-14 supplies the previous close ...
    assert stats.volume == 300
    assert stats.prev_close == 166.0
    # ... and a print at 23:30 session time on the 14th is not on today's tape.
    assert [t["id"] for t in stats.tape] == [_tid(2), _tid(3), _tid(4)]


def test_without_a_recorded_timezone_the_session_is_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _stats_db(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM stats_meta WHERE key = 'session_timezone'")
    conn.commit()
    conn.close()

    stats = _load_stats_from_db(db, "AAPL")

    assert stats.tz == timezone.utc
    assert stats.volume == 900
    assert stats.close == 166.0


def test_seeded_volume_is_not_double_counted_by_the_first_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stats = _load_stats_from_db(_stats_db(tmp_path, monkeypatch), "AAPL")
    already_counted = [_trade(n, 167.0) for n in (2, 3, 4)]

    stats.update(_snapshot(recent_trades=already_counted))
    assert stats.volume == 300
    assert len(stats.tape) == 3

    stats.add_trade(_trade(5, 167.8, 50))
    assert stats.volume == 350
    assert stats.high == 167.8
    assert stats.close == 167.8
    assert stats.open == 167.0


# ========================================================================
# High / low
# ========================================================================


def test_high_and_low_come_from_every_trade_not_from_sampled_snapshots() -> None:
    stats = _SessionStats()
    stats.add_trade(_trade(1, 10.0))
    stats.add_trade(_trade(2, 12.0))
    stats.add_trade(_trade(3, 11.0))
    # The throttled snapshot only ever saw the last price.
    stats.update(_snapshot(last_price=11.0))

    assert (stats.open, stats.high, stats.low, stats.close) == (10.0, 12.0, 10.0, 11.0)


def test_a_snapshot_last_price_alone_does_not_move_ohlc() -> None:
    stats = _SessionStats()
    stats.update(_snapshot(last_price=99.0))

    assert (stats.open, stats.high, stats.low, stats.close) == (None, None, None, None)


# ========================================================================
# Decimals
# ========================================================================


@pytest.mark.parametrize(
    "decimals, shown, not_shown",
    [(2, "99.50", "99.5000"), (4, "99.5000", "99.50000"), (0, "100", "100.0")],
)
def test_prices_are_shown_at_the_symbols_tick_decimals(
    decimals: int, shown: str, not_shown: str
) -> None:
    price = 100.0 if decimals == 0 else 99.5
    snap = _snapshot(
        tick_decimals=decimals,
        bids=[{"price": price, "qty": 10, "count": 1}],
        last_price=price,
    )
    out = _capture(_build_display(snap, "AAPL", size=(200, 20)))

    assert shown in out
    assert not_shown not in out


def test_the_change_is_shown_at_the_symbols_tick_decimals() -> None:
    stats = _SessionStats(prev_close=99.0)
    stats.update(_snapshot(last_price=99.5))

    out = _capture(_build_display(_snapshot(last_price=99.5), "AAPL", stats=stats))

    assert "+0.50" in out
    assert "+0.5000" not in out


# ========================================================================
# Session timezone on screen
# ========================================================================


@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "Etc/GMT+12"])
def test_the_header_date_is_the_session_date(zone: str) -> None:
    # UTC+14 and UTC-12 are 26 hours apart: their dates never agree, so each
    # rendering can only contain its own.
    tz = ZoneInfo(zone)
    other = ZoneInfo(
        "Etc/GMT+12" if zone == "Pacific/Kiritimati" else "Pacific/Kiritimati"
    )
    out = _capture(_build_display(_snapshot(), "AAPL", stats=_SessionStats(tz=tz)))

    assert datetime.now(tz).strftime("%Y-%m-%d") in out
    assert datetime.now(other).strftime("%Y-%m-%d") not in out


def test_trade_times_are_shown_in_the_session_timezone() -> None:
    stats = _SessionStats(tz=ZoneInfo(_SESSION_TZ))
    trade = _trade(1, 10.0)
    trade["ts_ns"] = int(_NOW.timestamp()) * 1_000_000_000 + 123_000_000
    stats.add_trade(trade)

    out = _capture(_build_display(_snapshot(), "AAPL", stats=stats))

    assert "02:00:00.123" in out
    assert "12:00:00.123" not in out


# ========================================================================
# Main loop
# ========================================================================


def test_live_prints_for_the_symbol_reach_the_trades_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(viewer_main, "_load_stats_from_db", lambda *_a: _SessionStats())
    _sub, _pushed, rendered = _run_viewer(
        monkeypatch,
        steps=[
            ([], (TOPIC_TRADE_EXECUTED, _trade(1, 42.17))),
            ([], (TOPIC_TRADE_EXECUTED, _trade(2, 55.55, symbol="MSFT"))),
        ],
    )
    out = _capture(rendered[-1])

    assert "42.17" in out
    assert "55.55" not in out
