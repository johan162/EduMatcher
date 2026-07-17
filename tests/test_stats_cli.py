from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edumatcher.stats.cli import main as stats_cli_main
from edumatcher.stats.main import SCHEMA


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)

        conn.execute(
            "INSERT INTO daily_stats "
            "(date, symbol, open_price, high_price, low_price, close_price, volume, trade_count, vwap) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-14", "AAPL", 150.0, 153.25, 149.5, 152.75, 5000, 12, 151.82),
        )
        conn.execute(
            "INSERT INTO daily_stats "
            "(date, symbol, open_price, high_price, low_price, close_price, volume, trade_count, vwap) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2026-06-15", "MSFT", 414.0, 418.5, 413.0, 417.0, 3200, 8, 415.63),
        )

        conn.execute(
            "INSERT INTO price_snapshots (ts, symbol, mid_price, best_bid, best_ask, pct_change) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("2026-06-14T09:00:00+00:00", "AAPL", 150.5, 150.0, 151.0, None),
        )

        conn.execute(
            "INSERT INTO trade_log "
            "(ts, trade_id, symbol, price, quantity, buy_gateway_id, sell_gateway_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:01.000+00:00",
                "T-AAPL-1",
                "AAPL",
                150.0,
                100,
                "GW01",
                "GW02",
            ),
        )

        conn.execute(
            "INSERT INTO order_events "
            "(ts, event_type, order_id, gateway_id, symbol, side, order_type, tif, "
            "price, quantity, remaining_qty, status, client_order_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.100+00:00",
                "ACK",
                "O-AAPL-1",
                "GW01",
                "AAPL",
                "BUY",
                "LIMIT",
                "DAY",
                150.0,
                100,
                100,
                "ACCEPTED",
                "client-1",
            ),
        )
        conn.execute(
            "INSERT INTO order_events "
            "(ts, event_type, order_id, gateway_id, symbol, side, fill_price, fill_qty, "
            "trade_id, remaining_qty, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:01.000+00:00",
                "FILL",
                "O-AAPL-1",
                "GW01",
                "AAPL",
                "BUY",
                150.0,
                100,
                "T-AAPL-1",
                0,
                "FILLED",
            ),
        )
        conn.execute(
            "INSERT INTO order_events "
            "(ts, event_type, order_id, gateway_id, symbol, side, order_type, tif, "
            "price, quantity, remaining_qty, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:02.000+00:00",
                "ACK",
                "O-MSFT-1",
                "GW02",
                "MSFT",
                "SELL",
                "LIMIT",
                "DAY",
                415.0,
                50,
                50,
                "ACCEPTED",
            ),
        )

        conn.execute(
            "INSERT INTO index_daily_stats "
            "(date, index_id, open_level, high_level, low_level, close_level, "
            " open_aggregate_cap, close_aggregate_cap, update_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14",
                "EDU100",
                1042.10,
                1056.30,
                1040.05,
                1048.73,
                7.3e12,
                7.35e12,
                512,
            ),
        )
        conn.execute(
            "INSERT INTO index_level_snapshots "
            "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:00:00.000+00:00",
                "EDU100",
                1042.10,
                7.3e12,
                1.25,
                "OPENING_AUCTION",
                None,
                None,
                None,
            ),
        )
        conn.execute(
            "INSERT INTO index_level_snapshots "
            "(ts, index_id, level, aggregate_cap, divisor, session_state, day_open, day_high, day_low) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-06-14T09:30:00.000+00:00",
                "EDU100",
                1048.73,
                7.35e12,
                1.25,
                "CONTINUOUS",
                1042.10,
                1048.73,
                1042.10,
            ),
        )

        conn.commit()
    finally:
        conn.close()


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-stats-cli", *argv])
    stats_cli_main()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "stats.db"
    _seed_db(db_path)
    return db_path


def test_snapshots_requires_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["snapshots"])
    assert exc_info.value.code == 2


def test_invalid_date_fails(monkeypatch: pytest.MonkeyPatch, seeded_db: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(
            monkeypatch,
            ["--db", str(seeded_db), "daily", "--date", "2026/06/14"],
        )
    assert exc_info.value.code == 2


def test_invalid_timestamp_fails(
    monkeypatch: pytest.MonkeyPatch, seeded_db: Path
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(
            monkeypatch,
            [
                "--db",
                str(seeded_db),
                "trades",
                "--from",
                "not-a-timestamp",
            ],
        )
    assert exc_info.value.code == 2


def test_missing_db_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["--db", str(missing), "daily"])
    assert exc_info.value.code == 1


def test_daily_defaults_to_latest_date_table_output(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(monkeypatch, ["--db", str(seeded_db), "daily"])
    out = capsys.readouterr().out

    assert "MSFT" in out
    assert "2026-06-15" in out
    assert "AAPL" not in out


def test_daily_wide_json_contains_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch, ["--db", str(seeded_db), "--format", "json", "daily", "--wide"]
    )
    out = capsys.readouterr().out

    assert '"open_bid"' in out
    assert '"largest_trade_qty"' in out


def test_snapshots_csv_output_with_header(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "csv",
            "snapshots",
            "--symbol",
            "AAPL",
        ],
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert out[0] == "ts,symbol,mid_price,best_bid,best_ask,pct_change"
    assert "AAPL" in out[1]


def test_csv_no_rows_still_prints_header(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "csv",
            "trades",
            "--symbol",
            "MSFT",
        ],
    )
    out = capsys.readouterr().out.strip()

    assert out == "ts,trade_id,symbol,price,quantity,buy_gateway_id,sell_gateway_id"


def test_csv_no_header_suppresses_header(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "csv",
            "--no-header",
            "trades",
            "--symbol",
            "AAPL",
        ],
    )
    out = capsys.readouterr().out.strip().splitlines()

    assert len(out) == 1
    assert out[0].startswith("2026-06-14T09:00:01.000+00:00,T-AAPL-1")


def test_json_no_rows_is_empty_array(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "json",
            "trades",
            "--symbol",
            "MSFT",
        ],
    )
    out = capsys.readouterr().out.strip()

    assert out == "[]"


def test_table_no_rows_message(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        ["--db", str(seeded_db), "trades", "--symbol", "MSFT"],
    )
    out = capsys.readouterr().out.strip()

    assert out == "No rows found."


def test_symbols_and_dates_commands(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(monkeypatch, ["--db", str(seeded_db), "symbols"])
    sym_out = capsys.readouterr().out
    assert "AAPL" in sym_out
    assert "MSFT" in sym_out

    _run_cli(monkeypatch, ["--db", str(seeded_db), "dates"])
    date_out = capsys.readouterr().out
    assert "2026-06-15" in date_out
    assert "2026-06-14" in date_out


def test_order_events_filters_by_gateway_symbol_and_type(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "json",
            "order-events",
            "--gateway",
            "gw01",
            "--symbol",
            "aapl",
            "--event-type",
            "fill",
        ],
    )
    out = capsys.readouterr().out

    assert '"event_type": "FILL"' in out
    assert '"order_id": "O-AAPL-1"' in out
    assert '"gateway_id": "GW01"' in out
    assert "O-MSFT-1" not in out


def test_order_lifecycle_outputs_all_events_for_order(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "csv",
            "order-lifecycle",
            "--gateway",
            "GW01",
            "--order-id",
            "O-AAPL-1",
        ],
    )
    lines = capsys.readouterr().out.strip().splitlines()

    assert lines[0].startswith("seq,ts,event_type,order_id,gateway_id")
    assert len(lines) == 3
    assert "ACK,O-AAPL-1,GW01,AAPL" in lines[1]
    assert "FILL,O-AAPL-1,GW01,AAPL" in lines[2]


# ---------------------------------------------------------------------------
# index-daily / index-snapshots / index-ids — end-to-end through main()
# ---------------------------------------------------------------------------


def test_index_daily_defaults_to_latest_date_table_output(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(monkeypatch, ["--db", str(seeded_db), "index-daily"])
    out = capsys.readouterr().out

    assert "EDU100" in out
    assert "2026-06-14" in out
    # Default (non-wide) view omits aggregate cap columns
    assert "aggregate_cap" not in out


def test_index_daily_wide_includes_aggregate_cap_columns(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        ["--db", str(seeded_db), "--format", "json", "index-daily", "--wide"],
    )
    out = capsys.readouterr().out

    assert '"open_aggregate_cap"' in out
    assert '"close_aggregate_cap"' in out


def test_index_daily_index_id_filter(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Lowercase input must be normalized the same way --symbol is elsewhere
    # in this CLI (case-insensitive convenience for interactive use).
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "index-daily",
            "--date",
            "2026-06-14",
            "--index-id",
            "edu100",
        ],
    )
    out = capsys.readouterr().out
    assert "EDU100" in out


def test_index_snapshots_requires_index_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["index-snapshots"])
    assert exc_info.value.code == 2


def test_index_snapshots_csv_output_with_header(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "--format",
            "csv",
            "index-snapshots",
            "--index-id",
            "EDU100",
        ],
    )
    lines = capsys.readouterr().out.strip().splitlines()

    assert (
        lines[0]
        == "ts,index_id,level,aggregate_cap,divisor,session_state,day_open,day_high,day_low"
    )
    # Two EDU100 rows were seeded (OPENING_AUCTION and CONTINUOUS)
    assert len(lines) == 3
    assert "OPENING_AUCTION" in lines[1]
    assert "CONTINUOUS" in lines[2]


def test_index_snapshots_time_window_narrows_results(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(
        monkeypatch,
        [
            "--db",
            str(seeded_db),
            "index-snapshots",
            "--index-id",
            "EDU100",
            "--from",
            "2026-06-14T09:20:00+00:00",
            "--to",
            "2026-06-14T09:40:00+00:00",
        ],
    )
    out = capsys.readouterr().out

    assert "CONTINUOUS" in out
    assert "OPENING_AUCTION" not in out


def test_index_ids_lists_configured_indexes(
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_cli(monkeypatch, ["--db", str(seeded_db), "index-ids"])
    out = capsys.readouterr().out
    assert "EDU100" in out


def test_index_ids_no_configured_index_returns_no_rows_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A symbol-only exchange (no index configured) must not error on
    index-ids — it should just report no rows, matching the documented
    'empty is expected, not an error' behavior.
    """
    db_path = tmp_path / "no_index_stats.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO daily_stats (date, symbol, open_price, close_price, volume, trade_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-06-14", "AAPL", 150.0, 152.0, 1000, 5),
    )
    conn.commit()
    conn.close()

    _run_cli(monkeypatch, ["--db", str(db_path), "index-ids"])
    out = capsys.readouterr().out
    assert "No rows found" in out
