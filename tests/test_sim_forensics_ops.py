"""tools/sim_forensics checks H1-H3 (ops signals and statistics).

These checks report INFO: a count of pointers, never a failed run. Each
test builds just the stores its check reads, with the recorders' schemas,
and plants the one pointer it expects to see.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from edumatcher.market_sim.news_history import initialize_schema as news_schema
from edumatcher.monitor.store import initialize_schema as metrics_schema
from edumatcher.stats.main import SCHEMA as STATS_SCHEMA
from tests.sim_forensics_world import SEC, OpenDataset, build, iso, ns, opener, sql
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.__main__ import main  # noqa: E402
from sim_forensics.checks.ops import spearman, ulid_ns  # noqa: E402
from sim_forensics.registry import (  # noqa: E402
    REGISTRY,
    Check,
    Outcome,
    Sample,
    run_checks,
)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: An order_events row: event type, quantity, fill_qty.
Row = tuple[str, int | None, int | None]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def ulid(at_ns: int) -> str:
    ms, chars = at_ns // 1_000_000, []
    for _ in range(10):
        ms, r = divmod(ms, 32)
        chars.append(_CROCKFORD[r])
    return "".join(reversed(chars)) + "0" * 16


def test_ulid_time_is_decoded() -> None:
    assert ulid_ns(ulid(ns("08:00:10.250"))) == ns("08:00:10.250")
    # A real one from the 2026-10-24 run's audit.
    assert ulid_ns("01M5Q31H3M2VWXVTHN7BH7HH01") // 1_000_000 == 1792850052212


def test_spearman() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 25, 90]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 3], [5, 5, 5]) is None


# --- H1 ----------------------------------------------------------------------


def event(data: Path, at: int, kind: str, detail: str) -> None:
    sql(
        data / "metrics.db",
        "INSERT INTO events (ts, kind, severity, subject, detail) "
        "VALUES (?, ?, 'CRIT', 'pm-engine@h', ?)",
        iso(at).replace("+00:00", "Z"),
        kind,
        detail,
    )


def test_h1_lists_ops_events_near_a_failed_checks_samples(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Samples are placed in time by their chain (a ULID), trade id or order
    id; only the chain's is within 30 s of an ops event."""
    data = build(tmp_path / "data")
    event(data, ns("08:00:00"), "THRESHOLD", "engine_handle_p99_us CRIT")
    event(data, ns("12:00:00"), "PROCESS_STATUS", "HEALTHY -> DEGRADED")
    samples: list[Sample] = [
        {"chain": ulid(ns("08:00:10"))},
        {"trade_id": "000001-000000003"},
        {"order_id": "O7"},
        {"date": "2026-06-15"},
    ]
    failing = Check("X1", "cross-store", "fails", (), lambda ds: Outcome(4, samples))
    passing = Check("X2", "cross-store", "passes", (), lambda ds: Outcome(0, []))
    *_, h1 = run_checks(open_ds(data), [failing, passing, REGISTRY["H1"]], 10)
    assert (h1.status, h1.violations) == ("INFO", 1)
    assert h1.samples == [
        {
            "check": "X1",
            "sample": samples[0],
            "events": ["-10.0s THRESHOLD CRIT pm-engine@h: engine_handle_p99_us CRIT"],
        }
    ]
    assert "X1: 1 of 3 timed samples" in h1.note
    assert "X2" not in h1.note


def test_h1_counts_clearing_disconnects_and_log_warnings(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = build(tmp_path / "data")
    sql(
        data / "clearing.db",
        "INSERT INTO gateway_sessions VALUES ('GW2', 0, ?, 'heartbeat_timeout')",
        ns("09:00:05"),
    )
    failing = Check(
        "X1", "cross-store", "fails", (), lambda ds: Outcome(1, [{"trade_id": "000001-000000003"}])  # fmt: skip
    )
    _, h1 = run_checks(open_ds(data), [failing, REGISTRY["H1"]], 10)
    assert h1.samples[0]["events"] == ["+5.0s disconnect GW2: heartbeat_timeout"]


def test_h1_skips_without_ops_events(tmp_path: Path, open_ds: OpenDataset) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (result,) = run_checks(open_ds(data), [REGISTRY["H1"]], 10)
    assert result.status == "SKIPPED"


# --- H2 ----------------------------------------------------------------------


def stats_db(data: Path) -> sqlite3.Connection:
    data.mkdir(exist_ok=True)
    conn = sqlite3.connect(data / "stats.db")
    conn.executescript(STATS_SCHEMA)
    conn.execute(
        "INSERT INTO stats_meta VALUES ('session_timezone', 'Europe/Stockholm')"
    )
    return conn


def h2_world(data: Path) -> None:
    conn = stats_db(data)
    # Six AI gateways with 20 ACKs each; AI006 is rejected far more often.
    for i, rejects in enumerate((1, 1, 2, 1, 2, 9), 1):
        gw = f"AI{i:03d}"
        ack: Row = ("ACK", 100, None)
        reject: Row = ("REJECT", None, None)
        fill: Row = ("FILL", None, 10)
        rows = [ack] * 20 + [reject] * rejects + [fill] * 5
        conn.executemany(
            "INSERT INTO order_events (ts, event_type, order_id, gateway_id, "
            "symbol, quantity, fill_qty) "
            "VALUES ('2026-06-15T08:00:00Z', ?, 'O', ?, 'AAPL', ?, ?)",
            [(et, gw, q, f) for et, q, f in rows],
        )
    # AAPL wanders by a tick, then trades 10 % up and stays there (one
    # excursion); MSFT does the same just after news on MSFT; TSLA prints
    # 10 % up once and goes straight back.
    wander = [10000, 10001, 10000, 10002, 10001] * 5
    for symbol, news_at, after in (
        ("AAPL", None, [11000] * 20),
        ("MSFT", ns("08:20:00"), [11000] * 20),
        ("TSLA", None, [11000] + [10001] * 19),
    ):
        conn.executemany(
            "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, "
            "aggressor_side) VALUES (?, ?, ?, ?, 1, 'BUY')",
            [
                (iso(ns("08:00:00") + k * 60 * SEC), f"{symbol}-{k:09d}", symbol, p)
                for k, p in enumerate(wander + after)
            ],
        )
        if news_at is not None:
            news = sqlite3.connect(data / "market_sim_news.db")
            news_schema(news)
            news.execute(
                "INSERT INTO news_events (id, ts_ns, scope, targets, kind, status, "
                "headline, sentiment, related_id) VALUES "
                "('N1', ?, 'SYMBOL', '[\"MSFT\"]', 'EARNINGS', 'CONFIRMED', 'x', 1, '')",
                (news_at,),
            )
            news.commit()
            news.close()
    # Six symbols' spreads around 10 ticks at 100.00; ZS's is 2 %.
    for symbol, spread in zip(("A", "B", "C", "D", "E", "ZS"), (10, 11, 12, 10, 11, 200)):  # fmt: skip
        conn.execute(
            "INSERT INTO price_snapshots VALUES ('2026-06-15T08:00:00+00:00', ?, "
            "NULL, ?, ?, NULL, 2)",
            (symbol, 10000 - spread // 2, 10000 + spread - spread // 2),
        )
    conn.commit()
    conn.close()


def test_h2_reports_outliers_as_info(tmp_path: Path, open_ds: OpenDataset) -> None:
    data = tmp_path / "data"
    h2_world(data)
    (result,) = run_checks(open_ds(data), [REGISTRY["H2"]], 10)
    assert result.status == "INFO"
    kinds = [
        (s["kind"], s.get("gateway_id") or s.get("symbol")) for s in result.samples
    ]
    assert kinds == [("gateway", "AI006"), ("jump", "AAPL"), ("spread", "ZS")]
    assert result.samples[0]["figure"] == "reject_rate"
    assert result.samples[1]["lasting_pct"] == 9.99  # off the median 100.01
    assert "1 unexplained lasting jumps (> 5 % off the prevailing price over 20 prints; 1 more after news, 1 reverted)" in result.note  # fmt: skip


def test_h2_cannot_confirm_a_jump_at_the_end_of_the_day(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = tmp_path / "data"
    conn = stats_db(data)
    prices = [10000, 10001, 10000, 10002, 10001] * 4 + [11000] * 19
    conn.executemany(
        "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, "
        "aggressor_side) VALUES (?, ?, 'AAPL', ?, 1, 'BUY')",
        [
            (iso(ns("08:00:00") + k * 60 * SEC), f"AAPL-{k:09d}", p)
            for k, p in enumerate(prices)
        ],
    )
    conn.commit()
    conn.close()
    (result,) = run_checks(open_ds(data), [REGISTRY["H2"]], 10)
    assert "0 unexplained lasting jumps" in result.note
    assert "0 reverted" in result.note


def test_h2_does_not_fail_the_run(tmp_path: Path) -> None:
    data = tmp_path / "data"
    h2_world(data)
    assert main(["--data", str(data), "--out", str(tmp_path / "out"), "--check", "H2"]) == 0  # fmt: skip


# --- H3 ----------------------------------------------------------------------


def test_h3_finds_latency_spikes_and_their_correlates(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "metrics.db")
    metrics_schema(conn)
    conn.executemany(
        "INSERT INTO series (id, source, name, label) VALUES (?, 'pm-engine@h', ?, '')",
        [(1, "engine.handle_us_p99"), (2, "engine.msgs_in")],
    )
    p99 = [100, 101, 102, 103, 104, 105, 106, 107, 108, 5000]
    for minute, v in enumerate(p99):
        ts = f"2026-06-15T08:{minute:02d}:00.000Z"
        conn.execute(
            "INSERT INTO samples_1m (series, ts, v_min, v_avg, v_max, v_last, n, delta) "
            "VALUES (1, ?, 0, 0, ?, 0, 1, NULL), (2, ?, 0, 0, 0, 0, 1, ?)",
            (ts, v, ts, 1000 + minute * 100),
        )
    conn.commit()
    conn.close()
    (result,) = run_checks(open_ds(data), [REGISTRY["H3"]], 10)
    assert (result.status, result.violations) == ("INFO", 1)
    assert result.samples[0]["p99_us"] == 5000
    assert result.samples[0]["engine.msgs_in"] == 1900
    assert "engine.msgs_in +1.00" in result.note
    assert "engine.busy_pct n/a" in result.note
