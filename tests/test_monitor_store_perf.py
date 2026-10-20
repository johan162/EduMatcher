"""metrics.db size for design question Q3 (WP-B4.5).

Simulates one hour of beacons for an exchange shaped like the ``s30-complex``
example (30 symbols, its 8 gateways) and like the design's §9.5 estimate (30
symbols, 30 participants), writes them through ``MetricsStore`` exactly as
pm-monitor does (raw every 10 s, minutes as they close), and prints MB per
hour of each table and the steady-state file size under the default retention
(6 h raw, 7 days of minutes).

Run with ``poetry run pytest -m perf -s tests/test_monitor_store_perf.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from edumatcher.engine.metrics import GATEWAY_COUNTERS
from edumatcher.monitor.config import DEFAULT_MINUTE_DAYS, DEFAULT_RAW_HOURS
from edumatcher.monitor.store import MetricsStore, SeriesKey

pytestmark = pytest.mark.perf

#: Other beaconing processes, each with about this many metrics.
OTHER_PROCESSES = 14
OTHER_METRICS = 8
#: Every beacon's health.* counters and the proc.* vitals.
PER_PROCESS = 3 + 6
HOST_SERIES = 22  # cpu total + 8 cores, 7 host figures, 6 files
BEACON_SEC = 2.0
HOURS = 1.0


def _series(gateways: int, symbols: int) -> list[tuple[SeriesKey, bool]]:
    """Every series pm-monitor stores, with whether it is a counter."""
    out: list[tuple[SeriesKey, bool]] = []
    eng = "pm-engine@box"
    for name in GATEWAY_COUNTERS:
        out += [((eng, f"engine.{name}", f"GW{g}"), True) for g in range(gateways)]
    for name in ("participant_connected", "resting_orders"):
        out += [((eng, f"engine.{name}", f"GW{g}"), False) for g in range(gateways)]
    for name, counter in (
        ("trades", True),
        ("traded_qty", True),
        ("traded_value", True),
        ("book_halted", False),
        ("book_resting_orders", False),
        ("book_stop_orders", False),
        ("book_bid_levels", False),
        ("book_ask_levels", False),
        ("book_heap_entries", False),
        ("book_heap_garbage_pct", False),
        ("book_est_bytes", False),
    ):
        out += [((eng, f"engine.{name}", f"S{s}"), counter) for s in range(symbols)]
    out += [((eng, f"engine.misc{i}", ""), False) for i in range(20)]
    out += [((eng, f"proc.v{i}", ""), False) for i in range(PER_PROCESS)]
    for p in range(OTHER_PROCESSES):
        src = f"pm-p{p}@box"
        out += [
            ((src, f"p.m{i}", ""), i % 2 == 0)
            for i in range(OTHER_METRICS + PER_PROCESS)
        ]
    out += [(("host", f"host.h{i}", ""), False) for i in range(HOST_SERIES)]
    return out


def _simulate(path: Path, gateways: int, symbols: int) -> dict[str, float]:
    series = _series(gateways, symbols)
    store = MetricsStore(
        path,
        "Europe/Stockholm",
        raw_hours=DEFAULT_RAW_HOURS,
        minute_days=DEFAULT_MINUTE_DAYS,
    )
    counters: dict[SeriesKey, tuple[str, float]] = {}
    wall = 1_760_000_000.0
    ticks = int(HOURS * 3600 / BEACON_SEC)
    started = time.perf_counter()
    for tick in range(ticks):
        for key, counter in series:
            value = float(tick)
            store.record(key, value, wall, counter=counter)
            if counter:
                store.record_increment("2025-10-09", key, 1.0, wall)
                counters[key] = ("boot", value)
        if store.due_raw(wall):
            store.flush_raw(wall, counters)
        store.flush_minutes(wall)
        wall += BEACON_SEC
    store.close(wall, counters)
    elapsed = time.perf_counter() - started

    import sqlite3

    conn = sqlite3.connect(path)
    sizes = dict(
        conn.execute("SELECT name, SUM(pgsize) FROM dbstat GROUP BY name").fetchall()
    )
    conn.close()
    mb = 1024 * 1024

    def table(*names: str) -> float:
        return sum(sizes.get(n, 0) for n in names) / mb / HOURS

    raw = table("samples_raw", "idx_raw", "idx_raw_ts")
    minute = table("samples_1m", "sqlite_autoindex_samples_1m_1", "idx_1m_ts")
    return {
        "series": len(series),
        "raw_mb_per_h": raw,
        "minute_mb_per_h": minute,
        "steady_mb": raw * DEFAULT_RAW_HOURS + minute * 24 * DEFAULT_MINUTE_DAYS,
        "sim_sec": elapsed,
    }


@pytest.mark.parametrize(
    ("shape", "gateways", "symbols"),
    [("s30-complex", 8, 30), ("design 9.5 (30 participants)", 30, 30)],
)
def test_metrics_db_size(
    tmp_path: Path, shape: str, gateways: int, symbols: int
) -> None:
    r = _simulate(tmp_path / "metrics.db", gateways, symbols)
    print(
        f"\n{shape}: {r['series']:.0f} series, raw {r['raw_mb_per_h']:.1f} MB/h, "
        f"1-minute {r['minute_mb_per_h']:.2f} MB/h -> steady state "
        f"{r['steady_mb']:.0f} MB ({DEFAULT_RAW_HOURS} h raw + "
        f"{DEFAULT_MINUTE_DAYS} d minutes); simulated 1 h in {r['sim_sec']:.1f} s"
    )
    assert r["raw_mb_per_h"] > 0 and r["minute_mb_per_h"] > 0
