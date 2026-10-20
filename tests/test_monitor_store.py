"""metrics.db (WP-B4, design §9.5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from edumatcher.config import METRICS_DB_FILE
from edumatcher.emo import cli as emo_cli
from edumatcher.models.generated.health import HealthSnapshot
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.store import (
    IncompatibleStoreError,
    MetricsStore,
    StoreLockedError,
    initialize_schema,
)
from edumatcher.monitor.timefmt import iso_utc
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost, _beacon_frames

TZ = "Europe/Stockholm"
STOCKHOLM = ZoneInfo(TZ)
OPEN = datetime(2026, 10, 19, 9, 0, tzinfo=STOCKHOLM).timestamp()
STARTED = int((OPEN - 3600) * 1e9)  # every test process started this morning


def _store(path: Path, tz: str = TZ) -> MetricsStore:
    return MetricsStore(path, tz, raw_hours=6, minute_days=7)


def _rows(path: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# B4.1 open
# ---------------------------------------------------------------------------


class TestOpen:
    def test_schema_is_idempotent_and_wal(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.db"
        _store(path).close(OPEN)
        _store(path).close(OPEN)
        tables = {
            r[0]
            for r in _rows(path, "SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "series",
            "samples_raw",
            "samples_1m",
            "daily_totals",
            "counter_last",
            "events",
        } <= tables
        assert _rows(path, "PRAGMA journal_mode") == [("wal",)]
        assert _rows(path, "PRAGMA auto_vacuum") == [(2,)]  # INCREMENTAL

    def test_initialize_schema_twice(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            initialize_schema(conn)
            initialize_schema(conn)
        finally:
            conn.close()

    def test_schema_failure_closes_connection_and_releases_lock(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "metrics.db"
        conn = sqlite3.connect(str(path), isolation_level=None)
        with (
            patch("edumatcher.monitor.store.sqlite3.connect", return_value=conn),
            patch(
                "edumatcher.monitor.store.initialize_schema",
                side_effect=sqlite3.OperationalError("schema failed"),
            ),
        ):
            with pytest.raises(sqlite3.OperationalError, match="schema failed"):
                _store(path)
        try:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                conn.execute("SELECT 1")
        finally:
            conn.close()
        _store(path).close(OPEN)

    def test_connection_failure_releases_lock(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.db"
        with patch(
            "edumatcher.monitor.store.sqlite3.connect",
            side_effect=sqlite3.OperationalError("open failed"),
        ):
            with pytest.raises(sqlite3.OperationalError, match="open failed"):
                _store(path)
        _store(path).close(OPEN)

    def test_a_second_writer_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.db"
        first = _store(path)
        try:
            with pytest.raises(StoreLockedError, match="another pm-monitor"):
                _store(path)
        finally:
            first.close(OPEN)
        _store(path).close(OPEN)  # the lock went with the first writer

    def test_a_reader_reads_while_the_writer_writes(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.db"
        store = _store(path)
        try:
            store.record(("host", "host.cpu_pct", ""), 5.0, OPEN, counter=False)
            store.flush_raw(OPEN)
            assert _rows(path, "SELECT value FROM v_samples_raw") == [(5.0,)]
        finally:
            store.close(OPEN)

    def test_the_session_timezone_is_pinned(self, tmp_path: Path) -> None:
        path = tmp_path / "metrics.db"
        _store(path).close(OPEN)
        conn = sqlite3.connect(str(path), isolation_level=None)
        with patch("edumatcher.monitor.store.sqlite3.connect", return_value=conn):
            with pytest.raises(IncompatibleStoreError, match="'Europe/Stockholm'"):
                _store(path, "America/New_York")
        try:
            with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
                conn.execute("SELECT 1")
        finally:
            conn.close()
        _store(path).close(OPEN)  # a refused open released its lock


# ---------------------------------------------------------------------------
# a Monitor writing to a store, on fake clocks
# ---------------------------------------------------------------------------


class _Clocks:
    def __init__(self) -> None:
        self.mono = 1000.0
        self.wall = OPEN

    def advance(self, sec: float) -> None:
        self.mono += sec
        self.wall += sec


def _monitor(path: Path, clocks: _Clocks) -> Monitor:
    pull, pub = free_ports(2)
    return Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        STOCKHOLM,
        clock=lambda: clocks.mono,
        wall_clock=lambda: clocks.wall,
        host_sampler=QuietHost(),
        local_host="box",
        store=_store(path),
    )


@pytest.fixture
def clocks() -> _Clocks:
    return _Clocks()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "metrics.db"


@pytest.fixture
def mon(db: Path, clocks: _Clocks) -> Iterator[Monitor]:
    m = _monitor(db, clocks)
    try:
        yield m
    finally:
        m.close()


def _orders(
    seq: int, value: float, *, boot: str = "a" * 16, gauge: float = 0.0
) -> list[bytes]:
    return _beacon_frames(
        seq=seq,
        boot_id=boot,
        started_at_ns=STARTED,
        metrics=[
            {
                "name": "engine.orders_in",
                "kind": "COUNTER",
                "label": "GW1",
                "value": value,
            },
            {"name": "engine.busy_pct", "kind": "GAUGE", "value": gauge},
        ],
    )


def _beacons(
    mon: Monitor,
    clocks: _Clocks,
    values: list[float],
    *,
    start_seq: int = 0,
    boot: str = "a" * 16,
) -> None:
    """One beacon every 2 s, with a store tick after each (as the loop does)."""
    for i, v in enumerate(values):
        mon.receive(_orders(start_seq + i, v, boot=boot, gauge=float(i)), clocks.mono)
        mon.store_tick()
        clocks.advance(2.0)


# ---------------------------------------------------------------------------
# B4.2 raw
# ---------------------------------------------------------------------------


def test_60_s_of_2_s_beacons_are_6_raw_rows_per_series(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    _beacons(mon, clocks, [float(i) for i in range(30)])
    counts = dict(
        _rows(
            db,
            "SELECT name, COUNT(*) FROM v_samples_raw WHERE source = 'pm-engine@box' "
            "AND name IN ('engine.orders_in', 'engine.busy_pct', 'proc.rss_bytes') "
            "GROUP BY name",
        )
    )
    assert counts == {"engine.orders_in": 6, "engine.busy_pct": 6, "proc.rss_bytes": 6}


def test_host_series_are_stored(mon: Monitor, db: Path) -> None:
    mon.snapshot()
    mon.store_tick()
    names = {
        r[0] for r in _rows(db, "SELECT name FROM v_samples_raw WHERE source = 'host'")
    }
    assert {"host.cpu_pct", "host.mem_used_bytes", "host.disk_free_bytes"} <= names


# ---------------------------------------------------------------------------
# B4.3 minutes and daily totals
# ---------------------------------------------------------------------------


def test_a_minute_bucket_is_its_samples(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    # 30 beacons in the minute from 09:00:00: gauge 0..29, counter with a
    # process restart after 20 (value back to 3, then +1 per beacon)
    values = [10.0 * i for i in range(20)] + [3.0 + i for i in range(10)]
    _beacons(mon, clocks, values[:20])
    _beacons(mon, clocks, values[20:], boot="b" * 16)
    mon.store_tick()  # 09:01:00: the 09:00 minute is closed
    ((v_min, v_avg, v_max, v_last, n),) = _rows(
        db,
        "SELECT v_min, v_avg, v_max, v_last, n FROM v_samples_1m "
        "WHERE name = 'engine.busy_pct' AND ts = ?",
        iso_utc(OPEN),
    )
    gauges = [float(i) for i in range(20)] + [float(i) for i in range(10)]
    assert (v_min, v_max, v_last, n) == (0.0, 19.0, 9.0, 30)
    assert v_avg == pytest.approx(sum(gauges) / 30)
    ((delta, gauge_delta),) = _rows(
        db,
        "SELECT c.delta, g.delta FROM v_samples_1m c JOIN v_samples_1m g ON g.ts = c.ts "
        "AND g.name = 'engine.busy_pct' WHERE c.name = 'engine.orders_in' AND c.ts = ?",
        iso_utc(OPEN),
    )
    # first value 0 (started today), +10 x 19, then the restart counts 3,
    # then +1 x 9 -- reset-corrected
    assert delta == 190 + 3 + 9
    assert gauge_delta is None


def test_daily_totals_equal_today(mon: Monitor, clocks: _Clocks, db: Path) -> None:
    _beacons(mon, clocks, [0.0, 5.0, 12.0, 20.0, 31.0, 40.0])
    clocks.advance(10.0)
    mon.store_tick()
    assert _rows(db, "SELECT date, source, name, label, total FROM daily_totals") == [
        ("2026-10-19", "pm-engine@box", "engine.orders_in", "GW1", 40.0)
    ]
    assert mon.activity.orders.today == 40.0


def test_a_minute_split_by_a_restart_is_merged(db: Path, clocks: _Clocks) -> None:
    first = _monitor(db, clocks)
    _beacons(first, clocks, [0.0, 1.0, 2.0])  # 09:00:00 - 09:00:04
    first.close()  # writes the open minute
    second = _monitor(db, clocks)
    try:
        _beacons(second, clocks, [3.0, 4.0], start_seq=3)  # 09:00:06 - 09:00:08
        clocks.advance(60.0)
        second.store_tick()
    finally:
        second.close()
    ((n, v_min, v_max, delta),) = _rows(
        db,
        "SELECT n, v_min, v_max, delta FROM v_samples_1m "
        "WHERE name = 'engine.orders_in' AND ts = ?",
        iso_utc(OPEN),
    )
    assert (n, v_min, v_max, delta) == (5, 0.0, 4.0, 4.0)


def test_an_increment_to_another_day_is_not_growth_in_this_minute(db: Path) -> None:
    """I102: a backfill into an older trading date reaches its daily total
    only, not the delta of the minute that happens to be open."""
    store = _store(db)
    key = ("pm-engine@box", "engine.orders_in", "GW01")
    try:
        store.record(key, 10.0, OPEN, counter=True)
        store.record_increment("2026-10-19", key, 10.0, OPEN)
        store.record_increment("2026-10-17", key, 500.0, OPEN + 1)
        store.flush_minutes(OPEN + 1, force=True)
        store.flush_raw(OPEN + 1)
    finally:
        store.close(OPEN + 2)
    assert _rows(
        db, "SELECT delta FROM v_samples_1m WHERE name = 'engine.orders_in'"
    ) == [(10.0,)]
    assert _rows(db, "SELECT date, total FROM daily_totals ORDER BY date") == [
        ("2026-10-17", 500.0),
        ("2026-10-19", 10.0),
    ]


# ---------------------------------------------------------------------------
# a pm-monitor restart (I69)
# ---------------------------------------------------------------------------


def test_a_restart_neither_loses_nor_double_counts(db: Path, clocks: _Clocks) -> None:
    first = _monitor(db, clocks)
    _beacons(first, clocks, [0.0, 10.0, 20.0, 30.0])
    first.close()
    clocks.advance(30.0)  # down for a while; the engine took 25 more orders
    second = _monitor(db, clocks)
    try:
        assert second.activity.orders.today == 30.0  # restored
        _beacons(second, clocks, [55.0, 56.0], start_seq=4)
        snap = HealthSnapshot.from_dict(second.snapshot())
        assert snap.trading.orders.today == 56
        # the 25 from the gap count today but are no spike in the last minute
        assert snap.trading.orders.per_sec_now == pytest.approx(1 / 60.0)
        (gw1,) = [p for p in snap.participants if p.id == "GW1"]
        assert gw1.orders.today == 56
    finally:
        second.close()
    assert _rows(db, "SELECT total FROM daily_totals") == [(56.0,)]


def test_a_restart_across_an_engine_restart(db: Path, clocks: _Clocks) -> None:
    first = _monitor(db, clocks)
    _beacons(first, clocks, [0.0, 10.0])
    first.close()
    second = _monitor(db, clocks)
    try:
        _beacons(second, clocks, [4.0], boot="b" * 16)  # a new engine, 4 orders
        assert second.activity.orders.today == 14.0
    finally:
        second.close()


# ---------------------------------------------------------------------------
# events, retention, daily averages
# ---------------------------------------------------------------------------


def test_event_seq_is_the_stored_seq(mon: Monitor, db: Path) -> None:
    mon.publish_event("SESSION", "INFO", "session", "CLOSED -> PRE_OPEN")
    mon.publish_event("HALT", "WARN", "AAA", "L1 CB")
    assert _rows(db, "SELECT seq, kind, severity, subject FROM events") == [
        (1, "SESSION", "INFO", "session"),
        (2, "HALT", "WARN", "AAA"),
    ]
    assert mon._event_seq == 3


def test_a_failed_event_write_does_not_reuse_its_seq(mon: Monitor, db: Path) -> None:
    """The event is published as seq 2 although its write failed; the next
    stored event must be 3, or a reader would see two different seq 2s."""
    assert mon.store is not None
    mon.publish_event("SESSION", "INFO", "session", "CLOSED -> PRE_OPEN")
    real = mon.store.add_event
    with patch.object(
        mon.store, "add_event", side_effect=sqlite3.OperationalError("disk I/O error")
    ):
        assert mon.publish_event("HALT", "WARN", "AAA", "L1 CB")
    with patch.object(mon.store, "add_event", side_effect=real):
        mon.publish_event("RESUME", "INFO", "AAA", "timer")
    assert _rows(db, "SELECT seq, kind FROM events") == [(1, "SESSION"), (3, "RESUME")]
    assert mon.store_errors == 1


def test_event_seq_continues_past_events_retention_deleted(
    db: Path, clocks: _Clocks
) -> None:
    first = _monitor(db, clocks)
    for _ in range(3):
        first.publish_event("SESSION", "INFO", "session", "x")
    assert first.store is not None
    first.store.conn.execute("DELETE FROM events")
    first.close()
    second = _monitor(db, clocks)
    try:
        assert second._event_seq == 4
    finally:
        second.close()


def test_retention_keeps_the_windows(db: Path) -> None:
    store = _store(db)
    now = OPEN
    try:
        conn = store.conn
        sid = store._series_id(("host", "h", ""))
        for hours_ago in (1, 5, 7):
            ts = iso_utc(now - hours_ago * 3600)
            conn.execute("INSERT INTO samples_raw VALUES (?, ?, 1)", (sid, ts))
        for days_ago in (1, 6, 8):
            ts = iso_utc(now - days_ago * 86400)
            conn.execute(
                "INSERT INTO samples_1m VALUES (?, ?, 1, 1, 1, 1, 1, NULL)", (sid, ts)
            )
            conn.execute(
                "INSERT INTO events(ts, kind, severity, subject) "
                "VALUES (?, 'HALT', 'WARN', 'A')",
                (ts,),
            )
        conn.execute("INSERT INTO daily_totals VALUES ('2020-01-01', 's', 'n', '', 1)")
        assert store.apply_retention(now)
        assert not store.apply_retention(now + 60)  # hourly
    finally:
        store.close(now)
    assert len(_rows(db, "SELECT * FROM samples_raw")) == 2  # 1 h and 5 h of 6
    assert len(_rows(db, "SELECT * FROM samples_1m")) == 2  # 1 d and 6 d of 7
    assert len(_rows(db, "SELECT * FROM events")) == 2
    assert len(_rows(db, "SELECT * FROM daily_totals")) == 1  # kept for good


def test_avg_per_day_from_the_last_7_days_with_data(db: Path, clocks: _Clocks) -> None:
    store = _store(db)
    rows = [
        ("2026-10-10", "pm-engine@box", "engine.orders_in", "GW1", 999.0),  # too old
        *(
            (f"2026-10-{d}", "pm-engine@box", "engine.orders_in", gw, total)
            for d in (12, 13, 14, 15, 16, 17, 18)
            for gw, total in (("GW1", 100.0), ("MM01", 50.0))
        ),
        ("2026-10-19", "pm-engine@box", "engine.orders_in", "GW1", 1.0),  # today
    ]
    store.conn.executemany("INSERT INTO daily_totals VALUES (?, ?, ?, ?, ?)", rows)
    store.close(OPEN)
    m = _monitor(db, clocks)
    try:
        snap = HealthSnapshot.from_dict(m.snapshot())
        assert snap.trading.orders.avg_per_day == pytest.approx(150.0)
        assert snap.trading.trades.avg_per_day is None
        (gw1,) = [p for p in snap.participants if p.id == "GW1"]
        assert gw1.orders.avg_per_day == pytest.approx(100.0)
        assert gw1.orders.today == 1  # restored
    finally:
        m.close()


def test_a_failing_disk_costs_history_not_the_snapshot(
    mon: Monitor, clocks: _Clocks
) -> None:
    assert mon.store is not None
    mon.store.conn.execute("DROP TABLE samples_raw")
    _beacons(mon, clocks, [0.0, 1.0])
    assert mon.store_errors >= 1
    HealthSnapshot.from_dict(mon.snapshot()).validate()


# ---------------------------------------------------------------------------
# B4.6 pm-opctl-cli clear
# ---------------------------------------------------------------------------


def test_clear_all_removes_metrics_db() -> None:
    assert METRICS_DB_FILE in emo_cli.NON_STATE_PATHS
    assert METRICS_DB_FILE not in emo_cli.STATE_PATHS  # history, like the logs
