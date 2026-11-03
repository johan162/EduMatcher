"""K10 (S2, S3): book snapshots use event time; the snapshot baseline survives restart.

S2: ``_on_book`` stamped everything with receipt time on the claim that a book
    message "carries no timestamp of its own". ``book.{symbol}`` has carried
    ``ts_ns`` since AR-0.4 (spec/messages/book.yaml), so a snapshot handled
    just after midnight was filed under the wrong trading day.
S3: ``_last_snap_mid`` was never restored, so the first ``pct_change`` after a
    restart was NULL. (No test may seed ``_last_snap_mid`` by hand: that is
    exactly the step production was missing.)
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K10.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from edumatcher.stats.main import StatsProcess


def _open(db: Path) -> StatsProcess:
    fake = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake),
        patch("edumatcher.stats.main.make_pusher", return_value=fake),
        patch("edumatcher.stats.main.make_replier", return_value=fake),
    ):
        return StatsProcess(db, session_tz=timezone.utc)


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text).timestamp()


def _book(bid: float | None, ask: float | None, at: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": "AAPL",
        "tick_decimals": 2,
        "bids": [] if bid is None else [{"price": bid, "qty": 1, "count": 1}],
        "asks": [] if ask is None else [{"price": ask, "qty": 1, "count": 1}],
        "last_price": None,
    }
    if at is not None:
        payload["ts_ns"] = int(_epoch(at) * 1_000_000_000)
    return payload


# --- S2 ---------------------------------------------------------------------


def test_a_book_is_filed_under_the_day_of_its_own_timestamp(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    # Produced long before it is handled now: event day and receipt day differ.
    proc._on_book("AAPL", _book(99.0, 101.0, "2026-06-13T23:59:59+00:00"))

    (date,) = proc._conn.execute("SELECT date FROM daily_stats").fetchone()
    (snap_ts,) = proc._conn.execute("SELECT ts FROM price_snapshots").fetchone()
    proc.close()

    assert date == "2026-06-13"
    assert snap_ts == "2026-06-13T23:59:59+00:00"


def test_books_either_side_of_midnight_land_on_their_own_days(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    proc._on_book("AAPL", _book(99.0, 101.0, "2026-06-13T23:59:59+00:00"))
    proc._on_book("AAPL", _book(98.0, 102.0, "2026-06-14T00:00:01+00:00"))

    dates = [
        r[0] for r in proc._conn.execute("SELECT date FROM daily_stats ORDER BY 1")
    ]
    proc.close()

    assert dates == ["2026-06-13", "2026-06-14"]


def test_a_book_without_ts_ns_falls_back_to_receipt_time(tmp_path: Path) -> None:
    proc = _open(tmp_path / "s.db")
    proc._on_book("AAPL", _book(99.0, 101.0, None))

    (date,) = proc._conn.execute("SELECT date FROM daily_stats").fetchone()
    proc.close()

    assert date == datetime.now(tz=timezone.utc).date().isoformat()


# --- S3 ---------------------------------------------------------------------


def test_pct_change_after_a_restart_is_measured_from_the_persisted_snapshot(
    tmp_path: Path,
) -> None:
    db = tmp_path / "s.db"
    first = _open(db)
    first._on_book("AAPL", _book(99.0, 101.0, "2026-06-14T09:00:00+00:00"))  # mid 100
    first.close()

    second = _open(db)
    second._on_book("AAPL", _book(109.0, 111.0, "2026-06-14T09:15:00+00:00"))  # mid 110
    rows = second._conn.execute(
        "SELECT mid_price, pct_change FROM price_snapshots ORDER BY ts"
    ).fetchall()
    second.close()

    assert rows == [(10000.0, None), (11000.0, 10.0)]


def test_a_null_mid_row_is_the_baseline_after_a_restart(tmp_path: Path) -> None:
    db = tmp_path / "s.db"
    first = _open(db)
    first._on_book("AAPL", _book(None, None, "2026-06-14T09:00:00+00:00"))  # no mid
    first.close()

    second = _open(db)
    second._on_book("AAPL", _book(99.0, 101.0, "2026-06-14T09:15:00+00:00"))
    pct = second._conn.execute(
        "SELECT pct_change FROM price_snapshots ORDER BY ts DESC LIMIT 1"
    ).fetchone()[0]
    second.close()

    assert pct is None
