"""Regression tests for the pre-ship statistics fixes.

Each test here pins one defect that produced *wrong numbers* rather than an
error, so a regression would otherwise be invisible.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from edumatcher.stats.main import (
    SCHEMA,
    SCHEMA_VERSION,
    DatabaseInUseError,
    IncompatibleDatabaseError,
    StatsProcess,
    main as stats_main,
)
from edumatcher.stats.query import (
    open_readonly_connection,
    query_trades,
    read_meta,
    resolve_session_timezone,
    validate_date,
)
from edumatcher.stats.trading_day import (
    canonical_ts,
    normalise_ts_bound,
    resolve_timezone,
    trading_date,
    trading_day_bounds,
)

STOCKHOLM = ZoneInfo("Europe/Stockholm")


@pytest.fixture
def sp(tmp_path: Path):
    """StatsProcess with fake ZMQ sockets; fully closed after each test."""
    fake_sock = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        proc = StatsProcess(tmp_path / "test.db", session_tz=STOCKHOLM)
    yield proc
    proc.close()


# ---------------------------------------------------------------------------
# trading_day helpers
# ---------------------------------------------------------------------------


def test_resolve_timezone_known_and_unknown() -> None:
    assert resolve_timezone("UTC") is timezone.utc
    assert resolve_timezone("Europe/Stockholm") == STOCKHOLM
    assert resolve_timezone("Mars/Olympus_Mons") is None


def test_canonical_ts_omits_a_zero_fraction() -> None:
    """A whole-second bound must render without ``.000``.

    ``price_snapshots.ts`` is second-precision while every other ``ts`` is
    millisecond-precision. Because ``'+'`` sorts before ``'.'``, a bound
    written as ``09:00:00.000+00:00`` would sort *after* a stored
    ``09:00:00+00:00`` and silently exclude it.
    """
    whole = datetime(2026, 6, 14, 9, 0, 0, tzinfo=timezone.utc)
    assert canonical_ts(whole) == "2026-06-14T09:00:00+00:00"

    fractional = datetime(2026, 6, 14, 9, 0, 0, 500_000, tzinfo=timezone.utc)
    assert canonical_ts(fractional) == "2026-06-14T09:00:00.500+00:00"


def test_canonical_ts_sorts_correctly_against_both_stored_precisions() -> None:
    bound = canonical_ts(datetime(2026, 6, 14, 9, 0, 0, tzinfo=timezone.utc))
    assert bound <= "2026-06-14T09:00:00+00:00"  # second-precision row
    assert bound <= "2026-06-14T09:00:00.000+00:00"  # millisecond-precision row


def test_normalise_ts_bound_accepts_z_suffix_and_offsets() -> None:
    """All three spellings of the same instant must produce the same bound."""
    expected = "2026-06-14T09:00:00+00:00"
    assert normalise_ts_bound("2026-06-14T09:00:00Z", timezone.utc) == expected
    assert normalise_ts_bound("2026-06-14T09:00:00+00:00", timezone.utc) == expected
    assert normalise_ts_bound("2026-06-14T11:00:00+02:00", timezone.utc) == expected


def test_normalise_ts_bound_reads_naive_input_as_session_local() -> None:
    """A bound with no offset follows the same clock as ``--date``."""
    # 11:00 in Stockholm (CEST, UTC+2) in June is 09:00 UTC.
    assert (
        normalise_ts_bound("2026-06-14T11:00:00", STOCKHOLM)
        == "2026-06-14T09:00:00+00:00"
    )


def test_normalise_ts_bound_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        normalise_ts_bound("not-a-timestamp", timezone.utc)


def test_trading_day_bounds_span_local_midnight_to_local_midnight() -> None:
    start, end = trading_day_bounds("2026-06-14", STOCKHOLM)
    assert start == "2026-06-13T22:00:00+00:00"
    assert end == "2026-06-14T22:00:00+00:00"


def test_trading_day_bounds_handle_a_dst_transition() -> None:
    """The EU clocks go forward on 2026-03-29, making that day 23 hours long."""
    start, end = trading_day_bounds("2026-03-29", STOCKHOLM)
    assert start == "2026-03-28T23:00:00+00:00"
    assert end == "2026-03-29T22:00:00+00:00"


def test_trading_date_uses_session_clock_not_utc() -> None:
    """23:30 UTC is already the next trading day in Stockholm."""
    late = datetime(2026, 6, 14, 23, 30, tzinfo=timezone.utc).timestamp()
    assert trading_date(late, timezone.utc) == "2026-06-14"
    assert trading_date(late, STOCKHOLM) == "2026-06-15"


def test_validate_date_rejects_unpadded_dates() -> None:
    """``2026-6-4`` parses but never equals the zero-padded stored text."""
    validate_date("2026-06-04")
    with pytest.raises(ValueError):
        validate_date("2026-6-4")


# ---------------------------------------------------------------------------
# P0-2 — bounds must select rows by instant, not by byte order
# ---------------------------------------------------------------------------


def _seed_trades(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO trade_log "
        "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("2026-06-14T09:00:00.000+00:00", "T1", "AAPL", 150.0, 10, "A", "B"),
            ("2026-06-14T16:30:00.500+00:00", "T2", "AAPL", 151.0, 10, "A", "B"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "from_ts",
    [
        "2026-06-14T09:00:00Z",
        "2026-06-14T09:00:00+00:00",
        "2026-06-14T11:00:00+02:00",
    ],
)
def test_from_bound_selects_the_same_rows_for_equivalent_spellings(
    tmp_path: Path, from_ts: str
) -> None:
    """Before the fix, ``Z`` and ``+02:00`` each dropped the 09:00 trade.

    The bounds were compared as raw text, where ``'Z'`` > ``'+'`` and
    ``"11…"`` > ``"09…"``, so two spellings of one instant gave two different
    answers and neither reported an error.
    """
    db = tmp_path / "stats.db"
    _seed_trades(db)
    conn = open_readonly_connection(db)
    rows, _ = query_trades(
        conn,
        symbol="AAPL",
        date_value=None,
        from_ts=from_ts,
        to_ts=None,
        limit=10,
        tz=timezone.utc,
    )
    conn.close()
    assert [row["trade_id"] for row in rows] == ["T1", "T2"]


def test_date_filter_follows_the_session_timezone(tmp_path: Path) -> None:
    """In Stockholm both trades belong to the 2026-06-14 trading day.

    The 09:00 UTC trade is 11:00 local and the 16:30 UTC trade is 18:30
    local, so a Stockholm-session query for 2026-06-14 must return both —
    which the old ``substr(ts, 1, 10)`` UTC-date filter could not express.
    """
    db = tmp_path / "stats.db"
    _seed_trades(db)
    conn = open_readonly_connection(db)
    rows, _ = query_trades(
        conn,
        symbol="AAPL",
        date_value="2026-06-14",
        from_ts=None,
        to_ts=None,
        limit=10,
        tz=STOCKHOLM,
    )
    conn.close()
    assert [row["trade_id"] for row in rows] == ["T1", "T2"]


# ---------------------------------------------------------------------------
# P0-5 — the day bucket comes from the event, in the session timezone
# ---------------------------------------------------------------------------


def test_trade_is_booked_to_the_session_trading_date(sp: StatsProcess) -> None:
    """A 23:30 UTC trade is 01:30 the next day in Stockholm."""
    late = datetime(2026, 6, 14, 23, 30, tzinfo=timezone.utc).timestamp()
    sp._on_trade(
        {"symbol": "AAPL", "price": 100.0, "quantity": 5, "id": "T1", "timestamp": late}
    )
    rows = sp._conn.execute("SELECT date FROM daily_stats").fetchall()
    assert rows == [("2026-06-15",)]


def test_late_processed_trade_keeps_its_own_trading_date(sp: StatsProcess) -> None:
    """Two trades either side of local midnight land in different days.

    Both are handled in the same processing instant, so a wall-clock bucket
    would put them both in whichever day the recorder happened to be in.
    """
    before = datetime(2026, 6, 14, 21, 0, tzinfo=timezone.utc).timestamp()
    after = datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc).timestamp()
    sp._on_trade(
        {
            "symbol": "AAPL",
            "price": 100.0,
            "quantity": 5,
            "id": "T1",
            "timestamp": before,
        }
    )
    sp._on_trade(
        {
            "symbol": "AAPL",
            "price": 200.0,
            "quantity": 7,
            "id": "T2",
            "timestamp": after,
        }
    )
    rows = dict(
        sp._conn.execute(
            "SELECT date, volume FROM daily_stats ORDER BY date"
        ).fetchall()
    )
    assert rows == {"2026-06-14": 5, "2026-06-15": 7}


# ---------------------------------------------------------------------------
# P0-1 — a restart must not overwrite the day already recorded
# ---------------------------------------------------------------------------


def test_restart_preserves_the_days_ohlcv(tmp_path: Path) -> None:
    """The defect this pins: after a mid-session restart the next trade
    rewrote open/high/low/volume/VWAP from post-restart data alone, so the
    recorded volume went *down* and the open price changed retroactively.
    """
    db = tmp_path / "stats.db"
    fake_sock = MagicMock()
    patches = (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    )

    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    with patches[0], patches[1]:
        first = StatsProcess(db, session_tz=timezone.utc)
    for i, (price, qty) in enumerate([(100.0, 10), (120.0, 30), (90.0, 20)]):
        first._on_trade(
            {
                "symbol": "AAPL",
                "price": price,
                "quantity": qty,
                "id": f"T{i}",
                "timestamp": base + i,
            }
        )
    first.close()

    # Restart against the same database, then record one more trade.
    with patches[0], patches[1]:
        second = StatsProcess(db, session_tz=timezone.utc)
    second._on_trade(
        {
            "symbol": "AAPL",
            "price": 110.0,
            "quantity": 40,
            "id": "T3",
            "timestamp": base + 10,
        }
    )
    row = second._conn.execute(
        "SELECT open_price, high_price, low_price, close_price, volume, "
        "trade_count, vwap, largest_trade_qty FROM daily_stats"
    ).fetchone()
    second.close()

    open_price, high, low, close, volume, count, vwap, largest = row
    # Prices are integer ticks: 100.00 -> 10000 at two tick decimals.
    assert open_price == 10000  # not 11000 — the morning survived
    assert high == 12000
    assert low == 9000
    assert close == 11000
    assert volume == 100  # 10 + 30 + 20 + 40, not 40
    assert count == 4
    assert largest == 40
    expected_vwap = (10000 * 10 + 12000 * 30 + 9000 * 20 + 11000 * 40) / 100
    assert vwap == pytest.approx(expected_vwap)


def test_restart_preserves_opening_quotes(tmp_path: Path) -> None:
    """``open_bid``/``open_ask`` have no per-event table, so they are carried
    over from the existing ``daily_stats`` row rather than recomputed."""
    db = tmp_path / "stats.db"
    fake_sock = MagicMock()
    book = {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]}

    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        first = StatsProcess(db, session_tz=timezone.utc)
    first._on_book("AAPL", book)
    first.close()

    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        second = StatsProcess(db, session_tz=timezone.utc)
    second._on_book("AAPL", {"bids": [{"price": 95.0}], "asks": [{"price": 96.0}]})
    row = second._conn.execute("SELECT open_bid, open_ask FROM daily_stats").fetchone()
    second.close()

    assert row == (9900, 10100)  # ticks


def test_index_restart_preserves_the_days_ohlc(tmp_path: Path) -> None:
    db = tmp_path / "stats.db"
    fake_sock = MagicMock()
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()

    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        first = StatsProcess(db, session_tz=timezone.utc)
    for i, level in enumerate([1000.0, 1050.0, 990.0]):
        first._on_index_update(
            {"index_id": "EDU100", "level": level, "timestamp": base + i}
        )
    first.close()

    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        second = StatsProcess(db, session_tz=timezone.utc)
    second._on_index_update(
        {"index_id": "EDU100", "level": 1010.0, "timestamp": base + 10}
    )
    row = second._conn.execute(
        "SELECT open_level, high_level, low_level, close_level, update_count "
        "FROM index_daily_stats"
    ).fetchone()
    second.close()

    assert row == (1000.0, 1050.0, 990.0, 1010.0, 4)


# ---------------------------------------------------------------------------
# P0-6 — the writer must run in WAL
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P1-5 — the opening snapshot must not depend on host uptime
# ---------------------------------------------------------------------------


def test_first_snapshot_is_written_on_a_freshly_booted_host(
    sp: StatsProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``time.monotonic()`` is seconds since boot on Linux and macOS.

    The old code compared it against a ``defaultdict(float)`` zero, so the
    first snapshot required the *host* to have been up for a whole snapshot
    interval. On a fresh VM, container or demo laptop that silently skipped
    the opening snapshot — the very row the startup book request exists to
    capture.
    """
    # Host up for 12 seconds, well under the 900 s default interval.
    monkeypatch.setattr(
        "edumatcher.stats.main.time.monotonic", lambda: 12.0, raising=True
    )
    sp._on_book("AAPL", {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]})

    rows = sp._conn.execute("SELECT symbol, mid_price FROM price_snapshots").fetchall()
    assert rows == [("AAPL", 10000.0)]  # mid in ticks


def test_subsequent_snapshots_still_respect_the_interval(
    sp: StatsProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixing the first snapshot must not turn every book update into a row.

    Both clocks have to advance together: the throttle is driven by
    ``time.monotonic()``, but the row's key is a wall-clock ``ts`` at second
    precision, so leaving the wall clock still would make ``INSERT OR IGNORE``
    swallow the second row and hide a broken throttle.
    """
    clock = {"now": 12.0}
    epoch = datetime(2026, 6, 14, 9, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return epoch + timedelta(seconds=clock["now"])

        @staticmethod
        def fromtimestamp(value, tz=None):
            return datetime.fromtimestamp(value, tz)

    monkeypatch.setattr(
        "edumatcher.stats.main.time.monotonic", lambda: clock["now"], raising=True
    )
    monkeypatch.setattr("edumatcher.stats.main.datetime", _FakeDatetime)
    book = {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]}

    sp._on_book("AAPL", book)  # first — always written
    clock["now"] += 10.0
    sp._on_book("AAPL", book)  # inside the interval — skipped
    count = sp._conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    assert count == 1

    clock["now"] += sp._snapshot_interval_sec
    sp._on_book("AAPL", book)  # interval elapsed — written
    count = sp._conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------------------
# P1-10 — dropped trades must be detectable
# ---------------------------------------------------------------------------


def _trade(tid: str, epoch: float, qty: int = 1) -> dict:
    return {
        "symbol": "AAPL",
        "price": 100.0,
        "quantity": qty,
        "id": tid,
        "timestamp": epoch,
    }


def test_gap_in_trade_ids_is_recorded(sp: StatsProcess) -> None:
    """ZMQ PUB/SUB drops silently past the high-water mark.

    The engine numbers trades monotonically, so a jump in the id is the only
    evidence a subscriber has that anything went missing.
    """
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, tid in enumerate(["1", "2", "6"]):
        sp._on_trade(_trade(tid, base + i))

    rows = sp._conn.execute(
        "SELECT stream, expected_id, received_id, missing_count FROM feed_gaps"
    ).fetchall()
    assert rows == [("trade.executed", 3, 6, 3)]


def test_contiguous_trade_ids_record_no_gap(sp: StatsProcess) -> None:
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, tid in enumerate(["1", "2", "3"]):
        sp._on_trade(_trade(tid, base + i))
    assert sp._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0


def test_engine_restart_is_not_reported_as_a_gap(sp: StatsProcess) -> None:
    """Trade ids restart at 1 each engine run, so a decrease is a restart."""
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, tid in enumerate(["1", "2", "3", "1", "2"]):
        sp._on_trade(_trade(tid, base + i))
    assert sp._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0


def test_post_restart_trades_are_not_silently_discarded(sp: StatsProcess) -> None:
    """Trade ids repeat after an engine restart.

    Keyed on ``trade_id`` alone, a run-2 trade "1" collided with the run-1
    trade "1" and vanished into ``INSERT OR IGNORE``, understating volume for
    the rest of the day. The same defect clearing records as CL-C1.
    """
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, tid in enumerate(["1", "2", "1", "2"]):
        sp._on_trade(_trade(tid, base + i, qty=10))

    assert sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] == 4
    assert sp._conn.execute("SELECT volume FROM daily_stats").fetchone()[0] == 40


def test_genuine_duplicate_delivery_is_still_deduplicated(sp: StatsProcess) -> None:
    """Widening the key must not turn dedup off — same id *and* same ts."""
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    sp._on_trade(_trade("1", base, qty=10))
    sp._on_trade(_trade("1", base, qty=10))

    assert sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] == 1


def test_non_numeric_trade_id_disables_detection_once(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    """A synthetic id is not the engine counter; warn once, not per trade."""
    import logging

    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    with caplog.at_level(logging.WARNING):
        for i, tid in enumerate(["T-A", "T-B", "T-C"]):
            sp._on_trade(_trade(tid, base + i))

    assert caplog.text.count("trade-gap detection disabled") == 1
    assert sp._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0
    assert sp._conn.execute("SELECT COUNT(*) FROM trade_log").fetchone()[0] == 3


def test_counters_are_recorded_without_debug_logging(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    """Counting used to be skipped entirely unless DEBUG was enabled.

    That left a production run with no record of how much it handled — the
    first number you want when asking whether a session is complete.
    """
    import logging

    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    with caplog.at_level(logging.INFO):
        sp._on_trade(_trade("1", base))
    assert sp._debug_counts["trades_persisted"] == 1


# ---------------------------------------------------------------------------
# P1-11 — one recorder per database
# ---------------------------------------------------------------------------


def test_second_recorder_on_the_same_db_is_refused(tmp_path: Path) -> None:
    """Two recorders each keep their own rollup and overwrite the other's."""
    db = tmp_path / "stats.db"
    first = _make_process(db, session_tz=timezone.utc)
    try:
        with pytest.raises(DatabaseInUseError, match="already recording"):
            _make_process(db, session_tz=timezone.utc)
    finally:
        first.close()


def test_lock_is_released_when_the_recorder_closes(tmp_path: Path) -> None:
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=timezone.utc).close()
    second = _make_process(db, session_tz=timezone.utc)
    second.close()


def test_a_refused_database_does_not_leave_the_lock_held(tmp_path: Path) -> None:
    """Otherwise a corrected restart reports the file as in use by nobody."""
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=STOCKHOLM).close()

    with pytest.raises(IncompatibleDatabaseError):
        _make_process(db, session_tz=timezone.utc)

    # The lock must be free, so the correct timezone can start normally.
    _make_process(db, session_tz=STOCKHOLM).close()


def test_recorder_creates_a_missing_db_directory(tmp_path: Path) -> None:
    """The lock is taken before the database is opened, so it owns the mkdir."""
    db = tmp_path / "does" / "not" / "exist" / "stats.db"
    _make_process(db, session_tz=timezone.utc).close()
    assert db.exists()


# ---------------------------------------------------------------------------
# P1-7 / P1-8 / P1-9 — smaller correctness fixes
# ---------------------------------------------------------------------------


def test_zero_quantity_order_event_is_preserved(sp: StatsProcess) -> None:
    """``payload.get("quantity") or payload.get("qty")`` treated 0 as absent."""
    sp._on_order_event(
        "order.ack.GW01",
        {"order_id": "O1", "symbol": "AAPL", "accepted": True, "quantity": 0},
    )
    stored = sp._conn.execute("SELECT quantity FROM order_events").fetchone()[0]
    assert stored == 0


def test_quantity_falls_back_to_qty_when_absent(sp: StatsProcess) -> None:
    sp._on_order_event(
        "order.ack.GW01",
        {"order_id": "O1", "symbol": "AAPL", "accepted": True, "qty": 25},
    )
    stored = sp._conn.execute("SELECT quantity FROM order_events").fetchone()[0]
    assert stored == 25


def test_index_update_without_timestamp_warns(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    """Receipt time is a different clock; substituting it must not be silent."""
    import logging

    with caplog.at_level(logging.WARNING):
        sp._on_index_update({"index_id": "EDU100", "level": 1000.0})
    assert "no timestamp" in caplog.text


def test_pct_change_is_reproducible_from_consecutive_rows(
    sp: StatsProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A NULL-mid row becomes the baseline instead of being skipped over.

    Previously the baseline only advanced on a usable mid, so the row after a
    gap reported a multi-interval move as though it were a single step — a
    number no reader could reproduce from the table.
    """
    clock = {"now": 12.0}
    epoch = datetime(2026, 6, 14, 9, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return epoch + timedelta(seconds=clock["now"])

        @staticmethod
        def fromtimestamp(value, tz=None):
            return datetime.fromtimestamp(value, tz)

    monkeypatch.setattr(
        "edumatcher.stats.main.time.monotonic", lambda: clock["now"], raising=True
    )
    monkeypatch.setattr("edumatcher.stats.main.datetime", _FakeDatetime)

    def advance() -> None:
        clock["now"] += sp._snapshot_interval_sec

    sp._on_book("AAPL", {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]})
    advance()
    # Empty book and no last price — this row has no usable mid.
    sp._on_book("AAPL", {"bids": [], "asks": []})
    advance()
    sp._on_book("AAPL", {"bids": [{"price": 109.0}], "asks": [{"price": 111.0}]})

    rows = sp._conn.execute(
        "SELECT mid_price, pct_change FROM price_snapshots ORDER BY ts"
    ).fetchall()
    assert [row[0] for row in rows] == [10000.0, None, 11000.0]  # ticks
    # The third row's predecessor has no mid, so the move is undefined — not
    # silently measured against the 100.0 two intervals earlier.
    assert [row[1] for row in rows] == [None, None, None]


def test_pct_change_is_computed_between_adjacent_rows(
    sp: StatsProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 12.0}
    epoch = datetime(2026, 6, 14, 9, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        @staticmethod
        def now(tz=None):
            return epoch + timedelta(seconds=clock["now"])

        @staticmethod
        def fromtimestamp(value, tz=None):
            return datetime.fromtimestamp(value, tz)

    monkeypatch.setattr(
        "edumatcher.stats.main.time.monotonic", lambda: clock["now"], raising=True
    )
    monkeypatch.setattr("edumatcher.stats.main.datetime", _FakeDatetime)

    sp._on_book("AAPL", {"bids": [{"price": 99.0}], "asks": [{"price": 101.0}]})
    clock["now"] += sp._snapshot_interval_sec
    sp._on_book("AAPL", {"bids": [{"price": 109.0}], "asks": [{"price": 111.0}]})

    rows = sp._conn.execute(
        "SELECT mid_price, pct_change FROM price_snapshots ORDER BY ts"
    ).fetchall()
    assert rows[1][1] == pytest.approx(10.0)  # 100 → 110


@pytest.mark.parametrize("interval", ["0", "0.5", "0.999", "-1"])
def test_sub_second_snapshot_interval_is_rejected(
    monkeypatch: pytest.MonkeyPatch, interval: str
) -> None:
    """price_snapshots cannot hold more than one row per second per symbol.

    A shorter interval is a setting the schema physically cannot honour: the
    extra rows collide on ``(ts, symbol)`` and INSERT OR IGNORE discards them
    without a word. Refusing at startup beats accepting a value that silently
    does not work.
    """
    monkeypatch.setattr(
        "sys.argv", ["pm-stats", "--snapshot-interval", interval, "--db", "/tmp/x.db"]
    )
    with pytest.raises(SystemExit) as excinfo:
        stats_main()
    assert excinfo.value.code == 2  # argparse usage error


def test_one_second_snapshot_interval_is_accepted(tmp_path: Path) -> None:
    """The boundary must remain usable — one second is representable."""
    proc = _make_process(
        tmp_path / "stats.db", session_tz=timezone.utc, snapshot_interval_sec=1.0
    )
    assert proc._snapshot_interval_sec == 1.0
    proc.close()


# ---------------------------------------------------------------------------
# GAP-6 — publisher sequence covers every stream, not just trades
# ---------------------------------------------------------------------------


def test_a_filtering_subscriber_sees_a_contiguous_sequence() -> None:
    """The counter must be per topic, not per socket.

    A SUB socket filters by topic prefix. Against a socket-wide counter a
    subscriber taking only ``trade.executed`` would see it jump on every
    message it filtered out and report continuous phantom gaps — a detector
    that cries wolf is worse than none.
    """
    import zmq

    from edumatcher.messaging.bus import SequencedPublisher
    from edumatcher.models.message import decode_sequence

    ctx: zmq.Context = zmq.Context.instance()
    raw = ctx.socket(zmq.PUB)
    raw.bind("inproc://gap6test")
    pub = SequencedPublisher(raw)
    sub = ctx.socket(zmq.SUB)
    sub.connect("inproc://gap6test")
    sub.setsockopt(zmq.SUBSCRIBE, b"trade.executed")
    time.sleep(0.2)

    try:
        for _ in range(5):
            pub.send_multipart([b"trade.executed", b"{}"])
            pub.send_multipart([b"depth.AAPL", b"{}"])  # not subscribed
        time.sleep(0.2)

        seen = []
        while True:
            try:
                seen.append(decode_sequence(sub.recv_multipart(zmq.NOBLOCK)))
            except zmq.Again:
                break
        assert seen == [1, 2, 3, 4, 5]
    finally:
        sub.close()
        raw.close()


def test_sequence_frame_does_not_disturb_existing_subscribers() -> None:
    """decode() reads two frames, so every current consumer is unaffected."""
    from edumatcher.models.message import decode, decode_sequence, encode

    frames = encode("trade.executed", {"symbol": "AAPL"})
    assert decode(frames) == ("trade.executed", {"symbol": "AAPL"})
    assert decode_sequence(frames) is None  # unsequenced publisher

    stamped = [*frames, b"7"]
    assert decode(stamped) == ("trade.executed", {"symbol": "AAPL"})
    assert decode_sequence(stamped) == 7


def test_gap_on_a_non_trade_stream_is_recorded(sp: StatsProcess) -> None:
    """The whole point of GAP-6: loss on book/order streams was invisible."""
    for seq in (1, 2, 8):
        sp._check_topic_sequence("book.AAPL", seq)

    rows = sp._conn.execute(
        "SELECT stream, expected_id, received_id, missing_count FROM feed_gaps"
    ).fetchall()
    assert rows == [("book.AAPL", 3, 8, 5)]


def test_publisher_restart_is_not_reported_as_a_gap(sp: StatsProcess) -> None:
    """Sequences begin again at 1, so a decrease is a restart."""
    for seq in (1, 2, 3, 1, 2):
        sp._check_topic_sequence("index.update", seq)
    assert sp._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0


def test_unsequenced_topic_warns_once(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    """A silent stream must not masquerade as a clean one."""
    import logging

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            sp._check_topic_sequence("session.state", None)
    assert caplog.text.count("carries no sequence frame") == 1
    assert sp._conn.execute("SELECT COUNT(*) FROM feed_gaps").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# Topic drift — a `book.` subscription must not invent a symbol
# ---------------------------------------------------------------------------


def test_book_subtopic_does_not_create_a_phantom_symbol(
    sp: StatsProcess, caplog: pytest.LogCaptureFixture
) -> None:
    """`book.` matches sub-topics too, and the naive split invented a symbol.

    `make_depth_msg` published `book.depth.AAPL` while every subscriber
    listened for `depth.`, so nothing received it. Had anything used the
    factory, pm-stats would have recorded an instrument literally named
    "depth.AAPL" into daily_stats — verified before the fix. This pins the
    recorder against any future `book.<something>.<symbol>` topic.
    """
    import logging

    book = {"bids": [{"price": 100.0}], "asks": [{"price": 101.0}], "tick_decimals": 2}
    with caplog.at_level(logging.WARNING):
        sp._dispatch("book.depth.AAPL", book)

    assert "not a book snapshot" in caplog.text
    assert sp._conn.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0] == 0

    # A genuine single-symbol book snapshot still routes normally.
    sp._dispatch("book.AAPL", book)
    rows = sp._conn.execute("SELECT symbol FROM daily_stats").fetchall()
    assert rows == [("AAPL",)]


def test_depth_topic_does_not_match_a_book_subscription() -> None:
    """The fix, stated as the property that matters."""
    from edumatcher.models.message import decode, make_depth_msg

    topic, _ = decode(make_depth_msg("AAPL", {}))
    assert topic == "depth.AAPL"
    assert not topic.startswith("book.")


def test_writer_opens_in_wal_mode(sp: StatsProcess) -> None:
    """Without WAL a concurrent pm-stats-cli read makes the writer fail, and
    the receive loop's catch-all would swallow the dropped record."""
    mode = sp._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


# ---------------------------------------------------------------------------
# Schema version and recorded metadata
# ---------------------------------------------------------------------------


def _make_process(db: Path, **kwargs) -> StatsProcess:
    fake_sock = MagicMock()
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.stats.main.make_pusher", return_value=fake_sock),
    ):
        return StatsProcess(db, **kwargs)


def test_new_database_is_stamped_with_the_schema_version(tmp_path: Path) -> None:
    proc = _make_process(tmp_path / "stats.db", session_tz=timezone.utc)
    version = proc._conn.execute("PRAGMA user_version").fetchone()[0]
    proc.close()
    assert version == SCHEMA_VERSION


def test_mismatched_schema_version_is_refused(tmp_path: Path) -> None:
    """Writing new-format rows into an old-format file must not be attempted.

    That failure mode leaves a database that opens cleanly and reports wrong
    numbers, which is worse than refusing to start.
    """
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=timezone.utc).close()

    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(IncompatibleDatabaseError, match="schema version"):
        _make_process(db, session_tz=timezone.utc)


@pytest.mark.parametrize("failure", ["version", "timezone"])
def test_refused_open_does_not_leak_the_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A rejected database must be closed before the exception escapes.

    The caller only ever sees the exception, so it has no handle to close —
    the connection would linger until garbage collection, which on Python
    3.13+ also raises a ``ResourceWarning: unclosed database`` attributed to
    whatever unrelated test happens to be running at the time.

    Asserted by checking the connection is unusable rather than by catching
    the warning, so this holds on every Python version.
    """
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=STOCKHOLM).close()

    if failure == "version":
        conn = sqlite3.connect(db)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        session_tz = STOCKHOLM
    else:
        session_tz = timezone.utc

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", _tracking_connect)
    with pytest.raises(IncompatibleDatabaseError):
        _make_process(db, session_tz=session_tz)

    assert opened, "expected the refused open to have created a connection"
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


@pytest.mark.parametrize("failing_socket", [0, 1, 2])
def test_failed_socket_setup_closes_the_database(
    tmp_path: Path, failing_socket: int
) -> None:
    """A socket failure must not strand the already-open database connection.

    Parametrised over which socket fails because each one after the first
    also leaves the earlier sockets dangling, so the cleanup has to cope with
    a partially-built instance.
    """

    class _FakeSocket:
        """Tracks ``closed`` like a real ZMQ socket.

        close() may be invoked twice — once by the constructor's cleanup and
        again via __del__ on the discarded instance — and the guard in
        StatsProcess.close() relies on this attribute to make the second a
        no-op. A MagicMock would report a truthy ``closed`` from the start and
        hide that.
        """

        def __init__(self) -> None:
            self.closed = False
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            self.closed = True

    made: list[_FakeSocket] = []

    def _make(*_args, **_kwargs):
        if len(made) == failing_socket:
            raise RuntimeError("socket setup failed")
        sock = _FakeSocket()
        made.append(sock)
        return sock

    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    partial = None
    with (
        patch("edumatcher.stats.main.sqlite3.connect", _tracking_connect),
        patch("edumatcher.stats.main.make_subscriber", _make),
        patch("edumatcher.stats.main.make_pusher", _make),
    ):
        try:
            StatsProcess(tmp_path / "stats.db", session_tz=timezone.utc)
        except RuntimeError as exc:
            # Recover the half-built instance from the traceback and hold a
            # strong reference to it. Cleanup must not depend on __del__:
            # the traceback keeps the object alive for as long as the caller
            # holds the exception, so a __del__-only cleanup would leave the
            # database open for that whole time.
            frame = exc.__traceback__
            while frame is not None:
                if frame.tb_frame.f_code.co_name == "__init__":
                    partial = frame.tb_frame.f_locals.get("self")
                frame = frame.tb_next
        else:  # pragma: no cover - the constructor must raise
            pytest.fail("expected socket setup to fail")

    assert partial is not None, "could not retain the partially-built instance"
    assert opened, "expected the database to have been opened first"
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
    # Every socket created before the failure must have been closed too,
    # exactly once — the guard in close() makes any later pass a no-op.
    for sock in made:
        assert sock.closed
        assert sock.close_calls == 1


def test_session_timezone_is_recorded(tmp_path: Path) -> None:
    proc = _make_process(tmp_path / "stats.db", session_tz=STOCKHOLM)
    recorded = read_meta(proc._conn, "session_timezone")
    proc.close()
    assert recorded == "Europe/Stockholm"


def test_changing_session_timezone_on_an_existing_db_is_refused(
    tmp_path: Path,
) -> None:
    """The date column would otherwise mean two different things in one file."""
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=STOCKHOLM).close()

    with pytest.raises(IncompatibleDatabaseError, match="session timezone"):
        _make_process(db, session_tz=timezone.utc)


def test_reader_resolves_timezone_from_the_database(tmp_path: Path) -> None:
    """A reader that passes nothing must still agree with the recorder."""
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=STOCKHOLM).close()

    conn = open_readonly_connection(db)
    tz, warning = resolve_session_timezone(conn)
    conn.close()
    assert tz == STOCKHOLM
    assert warning is None


def test_reader_override_that_contradicts_the_database_warns(tmp_path: Path) -> None:
    db = tmp_path / "stats.db"
    _make_process(db, session_tz=STOCKHOLM).close()

    conn = open_readonly_connection(db)
    tz, warning = resolve_session_timezone(conn, "UTC")
    conn.close()
    assert tz is timezone.utc
    assert warning is not None and "Europe/Stockholm" in warning


# ---------------------------------------------------------------------------
# Fields that were previously on the wire but discarded
# ---------------------------------------------------------------------------


def test_aggressor_side_is_persisted(sp: StatsProcess) -> None:
    """Includes AUCTION, which is how an uncross print is distinguished."""
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, side in enumerate(["BUY", "SELL", "AUCTION"]):
        sp._on_trade(
            {
                "symbol": "AAPL",
                "price": 100.0,
                "quantity": 5,
                "id": f"T{i}",
                "timestamp": base + i,
                "aggressor_side": side,
            }
        )
    rows = sp._conn.execute(
        "SELECT aggressor_side FROM trade_log ORDER BY ts"
    ).fetchall()
    assert [row[0] for row in rows] == ["BUY", "SELL", "AUCTION"]


def test_turnover_is_persisted_and_reproduces_vwap(sp: StatsProcess) -> None:
    base = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc).timestamp()
    for i, (price, qty) in enumerate([(100.0, 10), (120.0, 30)]):
        sp._on_trade(
            {
                "symbol": "AAPL",
                "price": price,
                "quantity": qty,
                "id": f"T{i}",
                "timestamp": base + i,
            }
        )
    turnover, volume, vwap = sp._conn.execute(
        "SELECT turnover, volume, vwap FROM daily_stats"
    ).fetchone()
    assert turnover == 10000 * 10 + 12000 * 30  # exact integer, ticks x qty
    assert turnover / volume == pytest.approx(vwap)
