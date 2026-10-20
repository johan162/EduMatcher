"""Build the metrics.db the bridge tests read, with pm-monitor's own writer.

Written through ``edumatcher.monitor.store.MetricsStore`` -- never by hand --
so the fixture can never drift from the real schema (design WP-C2.3).

Usage::

    poetry run python make_metrics_db.py OUT.db

Timeline (UTC), one sample every 2 s from T0 = 2026-10-19T08:00:00Z for two
hours, as pm-monitor records beacons:

* ``host.cpu_pct`` (source ``host``, gauge): 10 + the minute index mod 10, so
  every sample of minute m is 10 + m % 10.
* ``engine.orders_in`` (source ``pm-engine@h1``, counter), label ``GW01``: one
  per sample (30 a minute); label ``GW02``: two per sample (60 a minute).
* ``proc.rss_bytes`` from ``pm-engine@h1`` and ``pm-engine@h2`` (gauges):
  the same name from two sources, for the ambiguity rule.

Daily totals: the two hours' increments into 2026-10-19, plus 1000 (GW01)
and 2000 (GW02) on each of 2026-10-17 and 2026-10-18.

Events: seq 1-5 at T0 + 10 min, + 20 min, ... with kinds CONNECT,
DISCONNECT, PROCESS_STATUS, THRESHOLD, SESSION.

Retention is never applied, so every raw row survives.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from edumatcher.monitor.store import MetricsStore
from edumatcher.monitor.timefmt import iso_utc

T0 = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc).timestamp()
STEP = 2.0
SAMPLES = 3600  # two hours
GW01 = ("pm-engine@h1", "engine.orders_in", "GW01")
GW02 = ("pm-engine@h1", "engine.orders_in", "GW02")
CPU = ("host", "host.cpu_pct", "")
RSS1 = ("pm-engine@h1", "proc.rss_bytes", "")
RSS2 = ("pm-engine@h2", "proc.rss_bytes", "")
EVENTS = [
    ("CONNECT", "INFO", "GW01", ""),
    ("DISCONNECT", "WARN", "GW02", "heartbeat_timeout"),
    ("PROCESS_STATUS", "CRIT", "pm-engine@h1", "HEALTHY -> HUNG"),
    ("THRESHOLD", "WARN", "host_cpu_pct", "WARN 85.0 > 80.0"),
    ("SESSION", "INFO", "exchange", "PRE_OPEN -> CONTINUOUS"),
]


def main(out: Path) -> None:
    out.unlink(missing_ok=True)
    store = MetricsStore(out, "Europe/Stockholm", raw_hours=6, minute_days=7)
    gw01 = gw02 = 0.0
    now = T0
    for i in range(SAMPLES):
        now = T0 + i * STEP
        minute = int((now - T0) // 60)
        store.record(CPU, 10.0 + minute % 10, now, counter=False)
        store.record(RSS1, 1_000_000.0, now, counter=False)
        store.record(RSS2, 2_000_000.0, now, counter=False)
        gw01 += 1
        gw02 += 2
        store.record(GW01, gw01, now, counter=True)
        store.record_increment("2026-10-19", GW01, 1.0, now)
        store.record(GW02, gw02, now, counter=True)
        store.record_increment("2026-10-19", GW02, 2.0, now)
        if store.due_raw(now):
            store.flush_raw(now)
        store.flush_minutes(now)
    for date in ("2026-10-17", "2026-10-18"):
        store.record_increment(date, GW01, 1000.0, now)
        store.record_increment(date, GW02, 2000.0, now)
    for n, (kind, severity, subject, detail) in enumerate(EVENTS, start=1):
        store.add_event(n, iso_utc(T0 + n * 600), kind, severity, subject, detail)
    store.close(now + STEP)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
