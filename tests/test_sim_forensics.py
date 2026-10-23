"""tools/sim_forensics: the framework, and each check proven to fail when it should.

Fixture data dirs are built with the recorders' real schemas (pm-stats's
SCHEMA, pm-clearing's apply_schema), so a schema change that breaks a check's
SQL fails here rather than on the next simulation run.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from sim_forensics.__main__ import main  # noqa: E402
from sim_forensics.dataset import Dataset  # noqa: E402
from sim_forensics.registry import (  # noqa: E402
    REGISTRY,
    Check,
    Outcome,
    run_checks,
)

from edumatcher.clearing.store import apply_schema  # noqa: E402
from edumatcher.stats.main import SCHEMA as STATS_SCHEMA  # noqa: E402
from tests.sim_forensics_world import OpenDataset, opener  # noqa: E402

#: (trade_id, ts UTC, symbol, price ticks, qty). 22:30 UTC on 06-14 is
#: 00:30 on 06-15 in Stockholm (CEST): it belongs to the next trading day.
TRADES = [
    ("000001-000000001", "2026-06-14T07:30:00.000+00:00", "AAPL", 15000, 10),
    ("000001-000000002", "2026-06-14T08:00:00.000+00:00", "AAPL", 15100, 30),
    ("000001-000000003", "2026-06-14T09:00:00.000+00:00", "AAPL", 14900, 30),
    ("000001-000000004", "2026-06-14T22:30:00.000+00:00", "AAPL", 15200, 5),
]


def _daily_rows() -> list[tuple[object, ...]]:
    """daily_stats as a correct pm-stats would have written it for TRADES."""
    return [
        # date, symbol, open, high, low, close, volume, count, turnover, vwap,
        # largest qty, largest price
        (
            "2026-06-14",
            "AAPL",
            15000,
            15100,
            14900,
            14900,
            70,
            3,
            1050000,
            1050000 / 70,
            30,
            15100,
        ),
        (
            "2026-06-15",
            "AAPL",
            15200,
            15200,
            15200,
            15200,
            5,
            1,
            76000,
            15200.0,
            5,
            15200,
        ),
        # A listed symbol that did not trade.
        ("2026-06-14", "MSFT", None, None, None, None, 0, 0, 0, None, 0, None),
    ]


def _make_stats(data: Path, daily: list[tuple[object, ...]]) -> None:
    conn = sqlite3.connect(data / "stats.db")
    conn.executescript(STATS_SCHEMA)
    conn.execute(
        "INSERT INTO stats_meta VALUES ('session_timezone', 'Europe/Stockholm')"
    )
    conn.executemany(
        "INSERT INTO trade_log (trade_id, ts, symbol, price, quantity) "
        "VALUES (?, ?, ?, ?, ?)",
        TRADES,
    )
    conn.executemany(
        "INSERT INTO daily_stats (date, symbol, open_price, high_price, low_price, "
        "close_price, volume, trade_count, turnover, vwap, largest_trade_qty, "
        "largest_trade_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        daily,
    )
    conn.commit()
    conn.close()


def _make_clearing(data: Path, trade_ids: list[str]) -> None:
    conn = sqlite3.connect(data / "clearing.db")
    apply_schema(conn)
    conn.executemany(
        "INSERT INTO trade_events (id, ts_ns, trade_date, symbol, quantity, price, "
        "buy_gateway_id, sell_gateway_id, ingest_ts_ns) "
        "VALUES (?, 0, '2026-06-14', 'AAPL', 1, 1, 'B', 'S', 0)",
        [(t,) for t in trade_ids],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def data(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    _make_stats(d, _daily_rows())
    return d


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def _f1(open_ds: OpenDataset, data: Path) -> Outcome:
    return REGISTRY["F1"].fn(open_ds(data))


# --- Dataset ---------------------------------------------------------------


def test_dataset_attaches_present_stores_only(data: Path, open_ds: OpenDataset) -> None:
    ds = open_ds(data)
    assert ds.stores == {"stats"}
    assert ds.session_tz.key == "Europe/Stockholm"


def test_dataset_opens_stores_read_only(data: Path, open_ds: OpenDataset) -> None:
    ds = open_ds(data)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ds.conn.execute("DELETE FROM stats.trade_log")


def test_cut_is_the_lowest_high_water_mark_of_the_trade_stores(
    data: Path, open_ds: OpenDataset
) -> None:
    # Clearing stopped one trade earlier than stats.
    _make_clearing(data, [t[0] for t in TRADES[:3]])
    assert open_ds(data).cut_trade_id == "000001-000000003"


def test_session_date_uses_the_session_timezone(
    data: Path, open_ds: OpenDataset
) -> None:
    ds = open_ds(data)
    (date,) = ds.conn.execute(
        "SELECT session_date('2026-06-14T22:30:00.000+00:00')"
    ).fetchone()
    assert date == "2026-06-15"


# --- registry ----------------------------------------------------------------


def _raises(ds: Dataset) -> Outcome:
    raise RuntimeError("boom")


def test_check_missing_its_store_is_skipped_not_passed(
    data: Path, open_ds: OpenDataset
) -> None:
    c = Check("X1", "cross-store", "needs clearing", ("clearing",), _raises)
    (result,) = run_checks(open_ds(data), [c], max_samples=10)
    assert result.status == "SKIPPED"
    assert "clearing" in result.note


def test_check_that_raises_is_an_error_and_does_not_stop_the_run(
    data: Path, open_ds: OpenDataset
) -> None:
    broken = Check("X1", "cross-store", "broken", ("stats",), _raises)
    results = run_checks(open_ds(data), [broken, REGISTRY["F1"]], 10)
    assert [r.status for r in results] == ["ERROR", "PASS"]
    assert "boom" in results[0].note


def test_samples_are_capped_but_violations_counted_in_full(
    data: Path, open_ds: OpenDataset
) -> None:
    many = Check(
        "X1",
        "cross-store",
        "many",
        ("stats",),
        lambda ds: Outcome(50, [{"n": i} for i in range(50)]),
    )
    (result,) = run_checks(open_ds(data), [many], max_samples=3)
    assert (result.status, result.violations, len(result.samples)) == ("FAIL", 50, 3)


# --- F1 ----------------------------------------------------------------------


def test_f1_passes_on_consistent_daily_stats(data: Path, open_ds: OpenDataset) -> None:
    out = _f1(open_ds, data)
    assert out.violations == 0, out.samples


@pytest.mark.parametrize(
    "column, index, value",
    [
        ("close_price", 5, 15100),
        ("volume", 6, 69),
        ("turnover", 8, 1),
        ("largest_trade_price", 11, 14900),
    ],
)
def test_f1_fails_on_a_wrong_column(
    tmp_path: Path, open_ds: OpenDataset, column: str, index: int, value: object
) -> None:
    daily = _daily_rows()
    row = list(daily[0])
    row[index] = value
    daily[0] = tuple(row)
    _make_stats(tmp_path, daily)

    out = _f1(open_ds, tmp_path)

    assert out.violations == 1
    assert out.samples[0]["date"] == "2026-06-14"
    assert column in out.samples[0]["diffs"]  # type: ignore[operator]


def test_f1_fails_when_a_traded_day_has_no_row(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    # Bucketing by UTC date would put trade 4 on 06-14 and miss this.
    _make_stats(tmp_path, _daily_rows()[:1] + _daily_rows()[2:])
    out = _f1(open_ds, tmp_path)
    assert out.samples == [
        {"date": "2026-06-15", "symbol": "AAPL", "diffs": "no daily_stats row"}
    ]


def test_f1_fails_when_a_row_claims_trades_that_are_not_in_the_tape(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    daily = _daily_rows()
    daily[2] = ("2026-06-14", "MSFT", 100, 100, 100, 100, 1, 1, 100, 100.0, 1, 100)
    _make_stats(tmp_path, daily)
    out = _f1(open_ds, tmp_path)
    assert [s["symbol"] for s in out.samples] == ["MSFT"]


# --- command line ------------------------------------------------------------


def test_cli_writes_report_and_findings_and_exit_code_reflects_failures(
    tmp_path: Path, data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out)]) == 0

    findings = json.loads((out / "findings.json").read_text())
    assert [c["id"] for c in findings["checks"]] == sorted(REGISTRY)
    assert "| F1 |" in (out / "report.md").read_text()

    bad = tmp_path / "bad"
    bad.mkdir()
    daily = _daily_rows()
    daily[1] = daily[1][:6] + (6,) + daily[1][7:]
    _make_stats(bad, daily)
    assert main(["--data", str(bad), "--out", str(out), "--check", "F1"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_rejects_unknown_check_ids(data: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--data", str(data), "--out", str(tmp_path), "--check", "Z9"])
