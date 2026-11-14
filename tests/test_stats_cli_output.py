"""WP-STA05: pm-stats-cli shows exact numbers, never truncates silently, and
prints every recorded column (C3, C9, C10, D7, D8)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from edumatcher.stats.cli import build_parser, main as stats_cli_main
from edumatcher.stats.main import SCHEMA


def _run(monkeypatch: pytest.MonkeyPatch, db: Path, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-stats-cli", "--db", str(db), *argv])
    stats_cli_main()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "stats.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    with conn:
        conn.execute(
            "INSERT INTO daily_stats (date, symbol, open_price, high_price, "
            "low_price, close_price, volume, trade_count, turnover, vwap, "
            "tick_decimals) VALUES ('2026-06-14', 'AAPL', 1234567, 1234567, "
            "1234567, 1234567, 10, 1, 12345678950, 1234567.0, 2)"
        )
        conn.execute(
            "INSERT INTO trade_log (ts, trade_id, symbol, price, quantity, "
            "tick_decimals, buy_gateway_id, sell_gateway_id, aggressor_side, "
            "buy_order_id, sell_order_id, match_type, msg_id) VALUES "
            "('2026-06-14T09:00:01.000+00:00', '000001-000000001', 'AAPL', "
            "15025, 100, 2, 'GW01', 'GW02', 'BUY', 'B1', 'S1', 'CONTINUOUS', 'M1')"
        )
        conn.execute(
            "INSERT INTO order_events (ts, event_type, order_id, gateway_id, "
            "symbol, reason, reject_code, msg_id) VALUES "
            "('2026-06-14T09:00:00.100+00:00', 'REJECT', 'O1', 'GW01', 'AAPL', "
            "'no liquidity', 'INSUFFICIENT_LIQUIDITY', 'M2')"
        )
        for i in range(3):
            conn.execute(
                "INSERT INTO feed_gaps (ts, stream, source, expected_id, "
                "received_id, missing_count) "
                "VALUES (?, 'book.AAPL', 'publisher_seq', 1, 2, 1)",
                (f"2026-06-14T09:00:0{i}.000+00:00",),
            )
    conn.close()
    return path


def test_table_output_keeps_every_digit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: Path
) -> None:
    _run(monkeypatch, db, ["daily", "--wide"])
    out = capsys.readouterr().out
    assert "12345.67" in out
    assert "123456789.5" in out
    assert "e+" not in out


def test_a_whole_price_still_prints_without_a_fraction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: Path
) -> None:
    _run(monkeypatch, db, ["trades"])
    out = capsys.readouterr().out
    assert " 150.25 " in out


def test_gaps_say_when_they_are_truncated_and_page_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: Path
) -> None:
    _run(monkeypatch, db, ["--format", "json", "gaps", "--limit", "2"])
    captured = capsys.readouterr()
    assert len(json.loads(captured.out)) == 2
    assert "Output truncated" in captured.err
    cursor = captured.err.split("--after ")[1].split()[0]
    _run(monkeypatch, db, ["--format", "json", "gaps", "--after", cursor])
    (third,) = json.loads(capsys.readouterr().out)
    assert third["ts"] == "2026-06-14T09:00:02.000+00:00"


def test_order_events_show_the_reject_code_and_message_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: Path
) -> None:
    _run(monkeypatch, db, ["--format", "json", "order-events", "--gateway", "GW01"])
    (row,) = json.loads(capsys.readouterr().out)
    assert row["reject_code"] == "INSUFFICIENT_LIQUIDITY"
    assert row["msg_id"] == "M2"


def test_trades_show_how_the_trade_came_about(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db: Path
) -> None:
    _run(monkeypatch, db, ["--format", "json", "trades"])
    (row,) = json.loads(capsys.readouterr().out)
    assert row["match_type"] == "CONTINUOUS"
    assert (row["buy_order_id"], row["sell_order_id"]) == ("B1", "S1")
    assert row["msg_id"] == "M1"


def _help(command: str) -> str:
    parser = build_parser()
    subparsers = next(a for a in parser._actions if a.dest == "command")  # noqa: SLF001
    choices = getattr(subparsers, "choices")
    return str(choices[command].format_help())


def test_gaps_help_covers_every_stream() -> None:
    text = _help("gaps")
    assert "trades the recorder never received" not in text
    assert "every subscribed stream" in text


def test_time_bounds_say_what_they_accept() -> None:
    text = _help("trades")
    assert "inclusive" in text
    assert "session" in text
