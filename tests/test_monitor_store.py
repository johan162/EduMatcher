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
from edumatcher.models.generated.session import make_session_state
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.store import (
    BACKLOG_SEC,
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

    def test_one_raw_write_stamps_every_series_alike(self, tmp_path: Path) -> None:
        """Beacons arrive at their own moments; a raw write records each
        series' latest value at the write's time, so the series of one write
        share a 10 s bucket on any chart (a stacked chart would otherwise dip
        where one is missing)."""
        path = tmp_path / "metrics.db"
        store = _store(path)
        try:
            store.record(("a@h", "proc.rss_bytes", ""), 1.0, OPEN + 0.1, counter=False)
            store.record(("b@h", "proc.rss_bytes", ""), 2.0, OPEN + 1.9, counter=False)
            store.record(("a@h", "proc.rss_bytes", ""), 3.0, OPEN + 2.1, counter=False)
            store.flush_raw(OPEN + 2.2)
            rows = _rows(
                path, "SELECT source, ts, value FROM v_samples_raw ORDER BY source"
            )
            assert rows == [
                ("a@h", iso_utc(OPEN + 2.2), 3.0),
                ("b@h", iso_utc(OPEN + 2.2), 2.0),
            ]
            # Nothing new from b: the next write has a's row only.
            store.record(("a@h", "proc.rss_bytes", ""), 4.0, OPEN + 5.0, counter=False)
            store.flush_raw(OPEN + 12.2)
            assert _rows(
                path, "SELECT COUNT(*) FROM v_samples_raw WHERE source = 'b@h'"
            ) == [(1,)]
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


def test_60_s_of_2_s_beacons_are_6_raw_rows_per_unlabelled_series(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    """Unlabelled series and vitals keep their 10 s rows; a labelled series
    (one per participant or symbol) is kept at minute resolution only (I123)."""
    _beacons(mon, clocks, [float(i) for i in range(30)])
    counts = dict(
        _rows(
            db,
            "SELECT name, COUNT(*) FROM v_samples_raw WHERE source = 'pm-engine@box' "
            "AND name IN ('engine.orders_in', 'engine.busy_pct', 'proc.rss_bytes') "
            "GROUP BY name",
        )
    )
    assert counts == {"engine.busy_pct": 6, "proc.rss_bytes": 6}
    clocks.advance(60.0)  # the minute closes
    mon.store_tick()
    minutes = _rows(
        db,
        "SELECT COUNT(*) FROM v_samples_1m WHERE source = 'pm-engine@box' "
        "AND name = 'engine.orders_in' AND label = 'GW1'",
    )
    assert minutes[0][0] >= 1


def test_only_the_engines_listed_labelled_series_are_stored(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    """Of pm-engine's per-participant and per-symbol series, metrics.db keeps
    what the dashboard reads; daily totals keep every counter (I123)."""
    metrics = [
        {"name": "engine.orders_in", "kind": "COUNTER", "label": "GW1", "value": 5.0},
        {"name": "engine.traded_qty", "kind": "COUNTER", "label": "AAA", "value": 7.0},
        {
            "name": "engine.book_bid_levels",
            "kind": "GAUGE",
            "label": "AAA",
            "value": 3.0,
        },
        {
            "name": "engine.book_est_bytes",
            "kind": "GAUGE",
            "label": "AAA",
            "value": 9.0,
        },
    ]
    for i in range(32):
        mon.receive(
            _beacon_frames(
                seq=i, boot_id="a" * 16, started_at_ns=STARTED, metrics=metrics
            ),
            clocks.mono,
        )
        mon.store_tick()
        clocks.advance(2.0)
    stored = {
        r[0]
        for r in _rows(
            db, "SELECT DISTINCT name FROM v_samples_1m WHERE source = 'pm-engine@box'"
        )
    }
    assert {"engine.orders_in", "engine.book_est_bytes"} <= stored
    assert not stored & {"engine.traded_qty", "engine.book_bid_levels"}


def test_the_snapshot_leaves_out_the_engines_labelled_samples(
    mon: Monitor, clocks: _Clocks
) -> None:
    """The trading, participants and books blocks carry them derived; at 300
    symbols they were 83 % of every snapshot (I123)."""
    metrics = [
        {"name": "engine.orders_in", "kind": "COUNTER", "label": "GW1", "value": 5.0},
        {"name": "engine.busy_pct", "kind": "GAUGE", "value": 1.0},
        {
            "name": "engine.diagnostics",
            "kind": "COUNTER",
            "label": "DISPATCH_ERROR",
            "value": 0.0,
        },
    ]
    mon.receive(
        _beacon_frames(seq=0, boot_id="a" * 16, started_at_ns=STARTED, metrics=metrics),
        clocks.mono,
    )
    (engine,) = [p for p in mon.snapshot()["processes"] if p["process"] == "pm-engine"]
    assert {(m["name"], m.get("label", "")) for m in engine["metrics"]} == {
        ("engine.busy_pct", ""),
        ("engine.diagnostics", "DISPATCH_ERROR"),
    }


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


def _engine(
    seq: int,
    orders: float,
    trades: float,
    *,
    boot: str = "a" * 16,
    started: int = STARTED,
) -> list[bytes]:
    """An engine beacon with a cumulative counter and a PRE_OPEN-reset one."""
    return _beacon_frames(
        seq=seq,
        boot_id=boot,
        started_at_ns=started,
        metrics=[
            {
                "name": "engine.orders_in",
                "kind": "COUNTER",
                "label": "GW1",
                "value": orders,
            },
            {
                "name": "engine.trades",
                "kind": "COUNTER",
                "label": "AAA",
                "value": trades,
            },
        ],
    )


def _day_totals(db: Path, date: str) -> dict[str, float]:
    return dict(
        _rows(
            db,
            "SELECT name, SUM(total) FROM daily_totals WHERE date = ? GROUP BY name",
            date,
        )
    )


class TestRestartAcrossDays:
    """C2 (Monitor review): a counter value recorded on an earlier trading
    date is no resume point -- the step follows the first-value rule."""

    def _day_one(self, db: Path, clocks: _Clocks) -> None:
        """09:00-15:00 on 2026-10-19, then pm-monitor stops."""
        first = _monitor(db, clocks)
        try:
            first.receive(_engine(0, 0.0, 0.0), clocks.mono)
            clocks.advance(6 * 3600.0)
            first.receive(_engine(1, 6000.0, 3000.0), clocks.mono)
            first.store_tick()
        finally:
            first.close()
        assert _day_totals(db, "2026-10-19") == {
            "engine.orders_in": 6000.0,
            "engine.trades": 3000.0,
        }

    def test_an_engine_running_on_counts_nothing_from_before_today(
        self, db: Path, clocks: _Clocks
    ) -> None:
        """The engine kept running overnight: what it counted since 15:00
        yesterday is partly yesterday's, so none of it is today's."""
        self._day_one(db, clocks)
        clocks.advance(20 * 3600.0)  # 2026-10-20 11:00
        second = _monitor(db, clocks)
        try:
            second.receive(_engine(2, 15000.0, 4000.0), clocks.mono)
            second.store_tick()
            assert second.activity.orders.today == 0.0  # not 9000
            assert second.activity.trades.today == 0.0  # not 1000
            second.receive(_engine(3, 15010.0, 4002.0), clocks.mono + 2.0)
            assert second.activity.orders.today == 10.0
            assert second.activity.trades.today == 2.0
        finally:
            second.close()
        assert _day_totals(db, "2026-10-20") == {
            "engine.orders_in": 10.0,
            "engine.trades": 2.0,
        }
        assert _day_totals(db, "2026-10-19")["engine.orders_in"] == 6000.0

    def test_an_engine_started_today_counts_its_whole_value(
        self, db: Path, clocks: _Clocks
    ) -> None:
        self._day_one(db, clocks)
        clocks.advance(20 * 3600.0)
        today = int((clocks.wall - 2 * 3600.0) * 1e9)  # 09:00 on 2026-10-20
        second = _monitor(db, clocks)
        try:
            second.receive(
                _engine(0, 800.0, 40.0, boot="b" * 16, started=today), clocks.mono
            )
            assert second.activity.orders.today == 800.0
            assert second.activity.trades.today == 40.0
        finally:
            second.close()

    def test_increments_after_midnight_go_to_the_new_date(
        self, db: Path, clocks: _Clocks
    ) -> None:
        """pm-monitor running through midnight: unchanged."""
        mon = _monitor(db, clocks)
        try:
            mon.receive(_engine(0, 0.0, 0.0), clocks.mono)
            clocks.advance(14 * 3600.0)  # 23:00
            mon.receive(_engine(1, 100.0, 10.0), clocks.mono)
            clocks.advance(2 * 3600.0)  # 01:00 on 2026-10-20
            mon.receive(_engine(2, 130.0, 10.0), clocks.mono)
            mon.store_tick()
        finally:
            mon.close()
        assert _day_totals(db, "2026-10-19")["engine.orders_in"] == 100.0
        assert _day_totals(db, "2026-10-20") == {"engine.orders_in": 30.0}


class TestSessionOpenedAfterRestart:
    """C4 (Monitor review): "avg / hour" counts from today's open after a
    restart, which metrics.db's SESSION events record."""

    def _open_then_restart(
        self, db: Path, clocks: _Clocks, *, opens: bool
    ) -> HealthSnapshot:
        first = _monitor(db, clocks)
        try:
            if opens:  # 09:00, as the engine bus says it
                first.receive_engine(
                    make_session_state(state="PRE_OPEN", prev_state="CLOSED")
                )
            first.receive(_engine(0, 0.0, 0.0), clocks.mono)
            clocks.advance(2 * 3600.0)  # 11:00
            first.receive(_engine(1, 12000.0, 0.0), clocks.mono)
        finally:
            first.close()
        clocks.advance(5.0)
        second = _monitor(db, clocks)
        try:
            second.receive(_engine(2, 12000.0, 0.0), clocks.mono)
            return HealthSnapshot.from_dict(second.snapshot())
        finally:
            second.close()

    def test_avg_per_hour_counts_from_the_open(self, db: Path, clocks: _Clocks) -> None:
        snap = self._open_then_restart(db, clocks, opens=True)
        hours = (2 * 3600.0 + 5.0) / 3600.0
        assert snap.trading.orders.avg_per_hour == pytest.approx(12000.0 / hours)

    def test_before_any_open_today_it_counts_from_midnight(
        self, db: Path, clocks: _Clocks
    ) -> None:
        snap = self._open_then_restart(db, clocks, opens=False)
        hours = (11 * 3600.0 + 5.0) / 3600.0
        assert snap.trading.orders.avg_per_hour == pytest.approx(12000.0 / hours)

    def test_an_open_on_an_earlier_date_does_not_count(
        self, db: Path, clocks: _Clocks
    ) -> None:
        first = _monitor(db, clocks)
        try:
            first.receive_engine(
                make_session_state(state="PRE_OPEN", prev_state="CLOSED")
            )
        finally:
            first.close()
        clocks.advance(24 * 3600.0)  # 2026-10-20 09:00, not opened yet
        second = _monitor(db, clocks)
        try:
            assert second.activity.session_opened_at is None
        finally:
            second.close()


class TestCounterState:
    """C1/P2 (Monitor review): ``counter_last`` holds what was last heard,
    so the state of a source that never returns expires with retention."""

    BOT = "pm-mm-bot/MM07@box"

    def _bot(self, seq: int, value: float) -> list[bytes]:
        return _beacon_frames(
            process="pm-mm-bot",
            instance="MM07",
            seq=seq,
            boot_id="c" * 16,
            started_at_ns=STARTED,
            metrics=[
                {"name": "bot.orders", "kind": "COUNTER", "label": "", "value": value}
            ],
        )

    def _last(self, db: Path, source: str) -> list[tuple[Any, ...]]:
        return _rows(
            db, "SELECT name, value, ts FROM counter_last WHERE source = ?", source
        )

    def test_a_source_that_never_returns_expires(
        self, db: Path, clocks: _Clocks
    ) -> None:
        first = _monitor(db, clocks)
        try:
            first.receive(self._bot(0, 5.0), clocks.mono)
            first.store_tick()
        finally:
            first.close()
        assert len(self._last(db, self.BOT)) == 1
        clocks.advance(300.0)  # same day: MM07's state is primed
        second = _monitor(db, clocks)
        try:
            assert len(second.activity.tracker) == 1
            for _ in range(8 * 24):  # eight days, MM07 never heard again
                clocks.advance(3600.0)
                second.store_tick()
            assert len(second.activity.tracker) == 0
        finally:
            second.close()
        assert self._last(db, self.BOT) == []

    def test_an_unchanged_counter_is_not_rewritten(
        self, mon: Monitor, clocks: _Clocks, db: Path
    ) -> None:
        mon.receive(self._bot(0, 5.0), clocks.mono)
        mon.store_tick()
        before = self._last(db, self.BOT)
        for seq in range(1, 10):  # 18 s of beacons, value unchanged
            clocks.advance(2.0)
            mon.receive(self._bot(seq, 5.0), clocks.mono)
            mon.store_tick()
        assert self._last(db, self.BOT) == before
        clocks.advance(2.0)
        mon.receive(self._bot(10, 6.0), clocks.mono)
        clocks.advance(10.0)
        mon.store_tick()
        assert self._last(db, self.BOT)[0][1] == 6.0

    def test_a_quiet_counter_heard_today_resumes_today(
        self, db: Path, clocks: _Clocks
    ) -> None:
        """An unchanged value is written again once on a new trading date,
        so a restart that day still resumes it exactly."""
        first = _monitor(db, clocks)
        try:
            first.receive(self._bot(0, 5.0), clocks.mono)
            first.store_tick()
            clocks.advance(24 * 3600.0)  # 2026-10-20 09:00, still 5
            first.receive(self._bot(1, 5.0), clocks.mono)
            first.store_tick()
        finally:
            first.close()
        assert self._last(db, self.BOT)[0][2] == iso_utc(clocks.wall)
        clocks.advance(300.0)  # down 5 min; MM07 sent 7 orders meanwhile
        second = _monitor(db, clocks)
        try:
            second.receive(self._bot(2, 12.0), clocks.mono)
            second.store_tick()
        finally:
            second.close()
        assert _day_totals(db, "2026-10-20") == {"bot.orders": 7.0}


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


@pytest.mark.parametrize("label", [None, "GW1"])
def test_avg_per_day_reads_only_the_last_dates(db: Path, label: str | None) -> None:
    """P1 (Monitor review): kept for good, so a plan that groups every date
    of a name grows with history (65 ms at a year for engine.trades)."""
    store = _store(db)
    try:
        store.conn.executemany(
            "INSERT INTO daily_totals VALUES (?, ?, ?, ?, ?)",
            [
                (f"2026-10-{d:02d}", "pm-engine@box", "engine.orders_in", gw, 1.0)
                for d in range(1, 19)
                for gw in ("GW1", "GW2")
            ],
        )
        executed: list[str] = []
        store.conn.set_trace_callback(executed.append)
        store.avg_per_day("engine.orders_in", label, before="2026-10-19")
        store.conn.set_trace_callback(None)
        (sql,) = [q for q in executed if "daily_totals" in q]
        plan = [r[3] for r in store.conn.execute("EXPLAIN QUERY PLAN " + sql)]
    finally:
        store.close(OPEN)
    assert not any("TEMP B-TREE" in step or step.startswith("SCAN") for step in plan)


def test_avg_per_day_with_gaps_and_few_dates(db: Path) -> None:
    store = _store(db)
    try:
        assert store.avg_per_day("engine.trades", None, before="2026-10-19") is None
        store.conn.executemany(
            "INSERT INTO daily_totals VALUES (?, ?, ?, ?, ?)",
            [
                ("2026-10-01", "pm-engine@box", "engine.trades", "AAA", 10.0),
                ("2026-10-01", "pm-engine@box", "engine.trades", "BBB", 20.0),
                ("2026-10-09", "pm-engine@box", "engine.trades", "AAA", 60.0),
                ("2026-10-19", "pm-engine@box", "engine.trades", "AAA", 999.0),
            ],
        )
        assert store.avg_per_day("engine.trades", None, before="2026-10-19") == 45.0
        assert store.avg_per_day("engine.trades", "AAA", before="2026-10-19") == 35.0
        assert store.avg_per_day("engine.trades", "BBB", before="2026-10-19") == 20.0
        assert store.avg_per_day("engine.trades", "CCC", before="2026-10-19") is None
    finally:
        store.close(OPEN)


def test_a_failing_disk_costs_history_not_the_snapshot(
    mon: Monitor, clocks: _Clocks
) -> None:
    assert mon.store is not None
    mon.store.conn.execute("DROP TABLE samples_raw")
    _beacons(mon, clocks, [0.0, 1.0])
    assert mon.store_errors >= 1
    HealthSnapshot.from_dict(mon.snapshot()).validate()


class TestFailingWrites:
    """C3 (Monitor review): while every write fails, what waits for the next
    write is bounded, and what is dropped is counted."""

    SERIES = [("pm-engine@box", "engine.book_est_bytes", f"S{i}") for i in range(40)]

    def _run(self, store: MetricsStore, start: float, seconds: int) -> int:
        """One sample per series every 2 s and a minute flush per sample;
        the number of flushes that failed."""
        failed = 0
        for t in range(0, seconds, 2):
            for key in self.SERIES:
                store.record(key, float(t), start + t, counter=False, raw=False)
            try:
                store.flush_minutes(start + t)
            except sqlite3.Error:
                failed += 1
        return failed

    def test_the_backlog_is_bounded_and_written_when_the_disk_returns(
        self, db: Path
    ) -> None:
        store = _store(db)
        try:
            store.conn.execute("PRAGMA query_only = 1")  # every write fails
            assert self._run(store, OPEN, 2 * 3600) > 0
            kept_minutes = int(BACKLOG_SEC // 60) + 1
            assert len(store._closed) <= len(self.SERIES) * kept_minutes
            closed = len(self.SERIES) * 119  # minutes closed in two hours
            assert store.dropped_rows == closed - len(store._closed)
            store.conn.execute("PRAGMA query_only = 0")
            store.flush_minutes(OPEN + 2 * 3600)
        finally:
            store.close(OPEN + 2 * 3600)
        starts = sorted({r[0] for r in _rows(db, "SELECT DISTINCT ts FROM samples_1m")})
        # The newest minutes, with no gap, for every series.
        assert starts == [iso_utc(OPEN + 60 * m) for m in range(120 - len(starts), 120)]
        assert _rows(db, "SELECT COUNT(DISTINCT series) FROM samples_1m") == [
            (len(self.SERIES),)
        ]

    def test_one_failed_write_loses_nothing(self, db: Path) -> None:
        store = _store(db)
        try:
            self._run(store, OPEN, 120)
            store.conn.execute("PRAGMA query_only = 1")
            assert self._run(store, OPEN + 120, 60) > 0
            store.conn.execute("PRAGMA query_only = 0")
            self._run(store, OPEN + 180, 62)
        finally:
            store.close(OPEN + 242)
        assert _rows(db, "SELECT COUNT(DISTINCT ts) FROM samples_1m") == [(5,)]
        assert store.dropped_rows == 0

    def test_dropped_rows_are_store_errors(self, mon: Monitor, clocks: _Clocks) -> None:
        assert mon.store is not None
        mon.store.conn.execute("PRAGMA query_only = 1")
        failures: list[Exception] = []
        real = mon._store_failed

        def failed(exc: Exception) -> None:
            failures.append(exc)
            real(exc)

        with patch.object(mon, "_store_failed", side_effect=failed):
            _beacons(mon, clocks, [float(i) for i in range(900)])  # 30 minutes
        # Every failed write counts one, and every dropped minute one more.
        assert mon.store_errors > len(failures) > 0
        assert mon.store.dropped_rows == 0  # taken by the collector


# ---------------------------------------------------------------------------
# B4.6 pm-opctl-cli clear
# ---------------------------------------------------------------------------


def test_clear_all_removes_metrics_db() -> None:
    assert METRICS_DB_FILE in emo_cli.NON_STATE_PATHS
    assert METRICS_DB_FILE not in emo_cli.STATE_PATHS  # history, like the logs


# ---------------------------------------------------------------------------
# opening metrics.db at start (I123)
# ---------------------------------------------------------------------------


def test_another_writer_or_another_timezone_stops_pm_monitor(tmp_path: Path) -> None:
    from edumatcher.monitor.main import open_store

    path = tmp_path / "metrics.db"
    config = MonitorConfig()
    first = open_store(path, TZ, config)
    assert first is not None
    try:
        with pytest.raises(SystemExit):
            open_store(path, TZ, config)  # another pm-monitor holds it
    finally:
        first.close(OPEN)
    with pytest.raises(SystemExit):
        open_store(path, "America/New_York", config)


def test_a_metrics_db_that_cannot_be_opened_costs_history_not_monitoring(
    tmp_path: Path,
) -> None:
    from edumatcher.monitor.main import open_store

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    assert open_store(blocker / "metrics.db", TZ, MonitorConfig()) is None


def test_a_counter_that_did_not_move_has_no_minute_row(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    """A rate needs only the minutes it moved in -- a missing minute is 0 --
    so a quiet counter writes nothing; a gauge writes every minute, or its
    chart's line would break (I123)."""
    _beacons(mon, clocks, [5.0] * 35)  # orders_in never moves; busy_pct does
    clocks.advance(60.0)
    mon.store_tick()
    counts = dict(
        _rows(
            db,
            "SELECT name, COUNT(*) FROM v_samples_1m WHERE source = 'pm-engine@box' "
            "GROUP BY name",
        )
    )
    # Its first minute holds today's first value (the process started
    # today); the minutes after that, when it did not move, hold nothing.
    assert counts["engine.orders_in"] == 1
    assert counts["engine.busy_pct"] >= 2


def test_every_series_is_known_within_one_raw_write(
    mon: Monitor, clocks: _Clocks, db: Path
) -> None:
    """A labelled series writes no raw rows and a quiet counter no minute
    rows, but the history API knows a metric by its series row: every series
    is registered at the next raw write, or a never-amended exchange would
    answer its reject-ratio query "unknown metric" (I123)."""
    metrics = [
        {"name": "engine.amends_in", "kind": "COUNTER", "label": "GW1", "value": 0.0},
        {
            "name": "engine.book_est_bytes",
            "kind": "GAUGE",
            "label": "AAA",
            "value": 9.0,
        },
    ]
    for i in range(6):  # 12 s: one raw write, no closed minute
        mon.receive(
            _beacon_frames(
                seq=i, boot_id="a" * 16, started_at_ns=STARTED, metrics=metrics
            ),
            clocks.mono,
        )
        mon.store_tick()
        clocks.advance(2.0)
    known = {
        (r[0], r[1])
        for r in _rows(
            db, "SELECT name, label FROM series WHERE source = 'pm-engine@box'"
        )
    }
    assert {("engine.amends_in", "GW1"), ("engine.book_est_bytes", "AAA")} <= known
