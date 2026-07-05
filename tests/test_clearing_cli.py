"""Tests for pm-clearing-cli — all 10 verb handlers, formats, and error paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edumatcher.clearing.cli import main as cli_main
from edumatcher.clearing.store import (
    DailySummaryRow,
    PositionRow,
    TradeEventRow,
    flush_batch,
    open_writer_connection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_db(path: Path) -> None:
    """Create and seed a minimal clearing DB with two gateways and two symbols."""
    conn = open_writer_connection(path)

    trades = [
        TradeEventRow(
            id="T1",
            ts_ns=1_751_371_200_000_000_000,  # 2025-07-01 12:00 UTC
            trade_date="2025-07-01",
            symbol="AAPL",
            quantity=100,
            price=1500,
            buy_order_id="O_B1",
            sell_order_id="O_S1",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_B",
            aggressor_side="BUY",
            ingest_ts_ns=1_751_371_200_000_000_001,
        ),
        TradeEventRow(
            id="T2",
            ts_ns=1_751_371_300_000_000_000,
            trade_date="2025-07-01",
            symbol="MSFT",
            quantity=50,
            price=4000,
            buy_order_id=None,
            sell_order_id=None,
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_C",
            aggressor_side="SELL",
            ingest_ts_ns=1_751_371_300_000_000_001,
        ),
        TradeEventRow(
            id="T3",
            ts_ns=1_751_457_600_000_000_000,  # 2025-07-02
            trade_date="2025-07-02",
            symbol="AAPL",
            quantity=50,
            price=1600,
            buy_order_id="O_B3",
            sell_order_id="O_S3",
            buy_gateway_id="GW_B",
            sell_gateway_id="GW_A",
            aggressor_side="BUY",
            ingest_ts_ns=1_751_457_600_000_000_001,
        ),
    ]

    positions = [
        PositionRow(
            gateway_id="GW_A",
            symbol="AAPL",
            net_qty=50,
            avg_cost=1500.0,
            realized_pnl=5000.0,
            unrealized_pnl=2500.0,
            mark_price=1550,
            buy_qty=100,
            sell_qty=50,
            buy_notional=150_000,
            sell_notional=80_000,
            last_trade_ts_ns=1_751_457_600_000_000_000,
            updated_ts_ns=1_751_457_600_000_000_100,
        ),
        PositionRow(
            gateway_id="GW_A",
            symbol="MSFT",
            net_qty=50,
            avg_cost=4000.0,
            realized_pnl=0.0,
            unrealized_pnl=1000.0,
            mark_price=4020,
            buy_qty=50,
            sell_qty=0,
            buy_notional=200_000,
            sell_notional=0,
            last_trade_ts_ns=1_751_371_300_000_000_000,
            updated_ts_ns=1_751_371_300_000_000_100,
        ),
        PositionRow(
            gateway_id="GW_B",
            symbol="AAPL",
            net_qty=-50,
            avg_cost=1600.0,
            realized_pnl=-5000.0,
            unrealized_pnl=-2500.0,
            mark_price=1550,
            buy_qty=50,
            sell_qty=100,
            buy_notional=80_000,
            sell_notional=150_000,
            last_trade_ts_ns=1_751_457_600_000_000_000,
            updated_ts_ns=1_751_457_600_000_000_100,
        ),
        PositionRow(
            gateway_id="GW_C",
            symbol="MSFT",
            net_qty=-50,
            avg_cost=4000.0,
            realized_pnl=0.0,
            unrealized_pnl=-1000.0,
            mark_price=4020,
            buy_qty=0,
            sell_qty=50,
            buy_notional=0,
            sell_notional=200_000,
            last_trade_ts_ns=1_751_371_300_000_000_000,
            updated_ts_ns=1_751_371_300_000_000_100,
        ),
    ]

    daily = [
        DailySummaryRow(
            trade_date="2025-07-01",
            gateway_id="GW_A",
            symbol="AAPL",
            delta_traded_qty=100,
            delta_traded_notional=150_000,
            delta_buy_qty=100,
            delta_sell_qty=0,
            delta_buy_notional=150_000,
            delta_sell_notional=0,
            delta_net_amount=150_000,
            delta_realized_pnl=0.0,
            end_net_qty=100,
            end_avg_cost=1500.0,
            end_unrealized_pnl=0.0,
            last_trade_ts_ns=1_751_371_200_000_000_000,
            updated_ts_ns=1_751_371_200_000_000_100,
        ),
        DailySummaryRow(
            trade_date="2025-07-01",
            gateway_id="GW_B",
            symbol="AAPL",
            delta_traded_qty=100,
            delta_traded_notional=150_000,
            delta_buy_qty=0,
            delta_sell_qty=100,
            delta_buy_notional=0,
            delta_sell_notional=150_000,
            delta_net_amount=-150_000,
            delta_realized_pnl=0.0,
            end_net_qty=-100,
            end_avg_cost=1500.0,
            end_unrealized_pnl=0.0,
            last_trade_ts_ns=1_751_371_200_000_000_000,
            updated_ts_ns=1_751_371_200_000_000_100,
        ),
        DailySummaryRow(
            trade_date="2025-07-02",
            gateway_id="GW_A",
            symbol="AAPL",
            delta_traded_qty=50,
            delta_traded_notional=80_000,
            delta_buy_qty=0,
            delta_sell_qty=50,
            delta_buy_notional=0,
            delta_sell_notional=80_000,
            delta_net_amount=-80_000,
            delta_realized_pnl=5000.0,
            end_net_qty=50,
            end_avg_cost=1500.0,
            end_unrealized_pnl=2500.0,
            last_trade_ts_ns=1_751_457_600_000_000_000,
            updated_ts_ns=1_751_457_600_000_000_100,
        ),
    ]

    flush_batch(conn, trades, positions, daily)
    conn.close()


def _run(monkeypatch: pytest.MonkeyPatch, db_path: Path, args: list[str]) -> None:
    monkeypatch.setattr(
        "sys.argv", ["pm-clearing-cli", "--datapath", str(db_path), *args]
    )
    cli_main()


def _run_capture(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    db_path: Path,
    args: list[str],
) -> str:
    _run(monkeypatch, db_path, args)
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "clearing.db"
    _seed_db(path)
    return path


@pytest.fixture()
def empty_db(tmp_path: Path) -> Path:
    path = tmp_path / "empty.db"
    open_writer_connection(path).close()
    return path


# ---------------------------------------------------------------------------
# Global argument tests
# ---------------------------------------------------------------------------


class TestGlobalArgs:
    def test_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["pm-clearing-cli", "--version"])
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 0

    def test_missing_db_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["pm-clearing-cli", "--datapath", str(tmp_path / "no.db"), "health"],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 1

    def test_invalid_date_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, db_path: Path
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-clearing-cli",
                "--datapath",
                str(db_path),
                "daily",
                "--date",
                "31-07-2025",
            ],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 2

    def test_zero_limit_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, db_path: Path
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-clearing-cli",
                "--datapath",
                str(db_path),
                "trades",
                "--limit",
                "0",
            ],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# gateways verb
# ---------------------------------------------------------------------------


class TestGatewaysVerb:
    def test_returns_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["gateways"])
        assert "GW_A" in out

    def test_filter_gateway(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["gateways", "--gateway", "gw_a"]
        )
        assert "GW_A" in out
        assert "GW_B" not in out

    def test_json_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "json", "gateways"]
        )
        data = json.loads(out)
        assert isinstance(data, list)
        assert any(r["gateway_id"] == "GW_A" for r in data)

    def test_csv_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "csv", "gateways"]
        )
        assert "gateway_id" in out  # header
        assert "GW_A" in out

    def test_csv_no_header(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "csv", "--no-header", "gateways"]
        )
        assert "gateway_id" not in out

    def test_empty_db(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        empty_db: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, empty_db, ["gateways"])
        assert "No rows found" in out


# ---------------------------------------------------------------------------
# positions verb
# ---------------------------------------------------------------------------


class TestPositionsVerb:
    def test_returns_all(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["positions"])
        assert "GW_A" in out
        assert "AAPL" in out

    def test_filter_gateway(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["positions", "--gateway", "gw_c"]
        )
        assert "GW_C" in out
        assert "GW_A" not in out

    def test_filter_symbol(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["positions", "--symbol", "msft"]
        )
        assert "MSFT" in out
        assert "AAPL" not in out

    def test_json_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "json", "positions"]
        )
        data = json.loads(out)
        assert "net_qty" in data[0]
        assert "avg_cost" in data[0]

    def test_default_output_is_normalized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "positions", "--gateway", "GW_A", "--symbol", "AAPL"],
        )
        data = json.loads(out)
        row = data[0]
        assert row["tick_decimals"] == 2
        assert row["mark_price"] == pytest.approx(15.5)

    def test_raw_output_preserves_tick_units(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            [
                "--format",
                "json",
                "--raw-output",
                "positions",
                "--gateway",
                "GW_A",
                "--symbol",
                "AAPL",
            ],
        )
        data = json.loads(out)
        row = data[0]
        assert row["tick_decimals"] == 2
        assert row["mark_price"] == 1550


# ---------------------------------------------------------------------------
# pnl verb
# ---------------------------------------------------------------------------


class TestPnlVerb:
    def test_total_pnl_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "pnl"])
        data = json.loads(out)
        assert all("total_pnl" in r for r in data)

    def test_filter_gateway(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "pnl", "--gateway", "GW_A"],
        )
        data = json.loads(out)
        assert all(r["gateway_id"] == "GW_A" for r in data)


# ---------------------------------------------------------------------------
# daily verb
# ---------------------------------------------------------------------------


class TestDailyVerb:
    def test_returns_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["daily"])
        assert "2025-07-01" in out

    def test_filter_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "daily", "--date", "2025-07-02"],
        )
        data = json.loads(out)
        assert all(r["trade_date"] == "2025-07-02" for r in data)

    def test_from_to_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "daily", "--from", "2025-07-02", "--to", "2025-07-02"],
        )
        data = json.loads(out)
        assert all(r["trade_date"] == "2025-07-02" for r in data)

    def test_buy_sell_columns_present(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "daily"])
        data = json.loads(out)
        row = data[0]
        assert "buy_qty" in row
        assert "net_amount" in row


# ---------------------------------------------------------------------------
# trades verb
# ---------------------------------------------------------------------------


class TestTradesVerb:
    def test_returns_all_trades(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "trades"])
        data = json.loads(out)
        assert len(data) == 3

    def test_filter_symbol(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "trades", "--symbol", "MSFT"],
        )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["symbol"] == "MSFT"

    def test_filter_gateway_matches_both_sides(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "trades", "--gateway", "GW_A"],
        )
        data = json.loads(out)
        # GW_A is buyer in T1 and T2, seller in T3
        assert len(data) == 3

    def test_date_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "trades", "--date", "2025-07-02"],
        )
        data = json.loads(out)
        assert all(r["trade_date"] == "2025-07-02" for r in data)


# ---------------------------------------------------------------------------
# exposure verb
# ---------------------------------------------------------------------------


class TestExposureVerb:
    def test_returns_rows_with_notional(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "json", "exposure"]
        )
        data = json.loads(out)
        assert all("gross_notional" in r for r in data)

    def test_sort_by_total_pnl(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "exposure", "--sort", "total_pnl"],
        )
        data = json.loads(out)
        assert len(data) >= 1

    def test_invalid_sort_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, db_path: Path
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-clearing-cli",
                "--datapath",
                str(db_path),
                "exposure",
                "--sort",
                "bad_field",
            ],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# symbols verb
# ---------------------------------------------------------------------------


class TestSymbolsVerb:
    def test_returns_symbols(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "json", "symbols"]
        )
        data = json.loads(out)
        symbols = {r["symbol"] for r in data}
        assert "AAPL" in symbols

    def test_sort_by_traded_notional(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "symbols", "--sort", "traded_notional"],
        )
        data = json.loads(out)
        notionals = [r["traded_notional"] for r in data]
        assert notionals == sorted(notionals, reverse=True)


# ---------------------------------------------------------------------------
# dates verb
# ---------------------------------------------------------------------------


class TestDatesVerb:
    def test_default_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "dates"])
        data = json.loads(out)
        dates = {r["trade_date"] for r in data}
        assert "2025-07-01" in dates
        assert "2025-07-02" in dates

    def test_with_totals(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch, capsys, db_path, ["--format", "json", "dates", "--with-totals"]
        )
        data = json.loads(out)
        assert all("traded_qty_total" in r for r in data)
        assert all("net_amount_total" in r for r in data)

    def test_from_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(
            monkeypatch,
            capsys,
            db_path,
            ["--format", "json", "dates", "--from", "2025-07-02"],
        )
        data = json.loads(out)
        assert all(r["trade_date"] >= "2025-07-02" for r in data)


# ---------------------------------------------------------------------------
# health verb
# ---------------------------------------------------------------------------


class TestHealthVerb:
    def test_returns_single_row(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "health"])
        data = json.loads(out)
        assert len(data) == 1

    def test_row_has_expected_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        out = _run_capture(monkeypatch, capsys, db_path, ["--format", "json", "health"])
        row = json.loads(out)[0]
        assert row["trade_events_rows"] == 3
        assert row["gateway_symbol_positions_rows"] == 4
        assert "wal_mode" in row
        assert "db_path" in row


# ---------------------------------------------------------------------------
# reconcile verb
# ---------------------------------------------------------------------------


class TestReconcileVerb:
    def test_clean_data_prints_ok(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        # The test DB has matching aggregates, but reconcile only checks
        # buy-side consistency.  Create a clean DB to test the OK path.
        from edumatcher.clearing.store import flush_batch, open_writer_connection

        clean = db_path.parent / "clean.db"
        conn = open_writer_connection(clean)
        flush_batch(
            conn,
            [
                TradeEventRow(
                    id="X1",
                    ts_ns=1_751_371_200_000_000_000,
                    trade_date="2025-07-01",
                    symbol="AAPL",
                    quantity=10,
                    price=100,
                    buy_order_id=None,
                    sell_order_id=None,
                    buy_gateway_id="GW_X",
                    sell_gateway_id="GW_Y",
                    aggressor_side=None,
                    ingest_ts_ns=1,
                )
            ],
            [],
            [
                DailySummaryRow(
                    trade_date="2025-07-01",
                    gateway_id="GW_X",
                    symbol="AAPL",
                    delta_traded_qty=10,
                    delta_traded_notional=1000,
                    delta_buy_qty=10,
                    delta_sell_qty=0,
                    delta_buy_notional=1000,
                    delta_sell_notional=0,
                    delta_net_amount=1000,
                    delta_realized_pnl=0.0,
                    end_net_qty=10,
                    end_avg_cost=100.0,
                    end_unrealized_pnl=0.0,
                    last_trade_ts_ns=1_751_371_200_000_000_000,
                    updated_ts_ns=1,
                )
            ],
        )
        conn.close()

        out = _run_capture(monkeypatch, capsys, clean, ["reconcile"])
        assert "OK" in out

    def test_discrepancy_detected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        corrupt = tmp_path / "corrupt.db"
        conn = open_writer_connection(corrupt)
        flush_batch(
            conn,
            [
                TradeEventRow(
                    id="Z1",
                    ts_ns=1_751_371_200_000_000_000,
                    trade_date="2025-07-01",
                    symbol="AAPL",
                    quantity=10,
                    price=100,
                    buy_order_id=None,
                    sell_order_id=None,
                    buy_gateway_id="GW_X",
                    sell_gateway_id="GW_Y",
                    aggressor_side=None,
                    ingest_ts_ns=1,
                )
            ],
            [],
            [
                DailySummaryRow(
                    trade_date="2025-07-01",
                    gateway_id="GW_X",
                    symbol="AAPL",
                    delta_traded_qty=5,  # wrong: should be 10
                    delta_traded_notional=500,
                    delta_buy_qty=5,
                    delta_sell_qty=0,
                    delta_buy_notional=500,
                    delta_sell_notional=0,
                    delta_net_amount=500,
                    delta_realized_pnl=0.0,
                    end_net_qty=5,
                    end_avg_cost=100.0,
                    end_unrealized_pnl=0.0,
                    last_trade_ts_ns=1,
                    updated_ts_ns=1,
                )
            ],
        )
        conn.close()

        out = _run_capture(
            monkeypatch, capsys, corrupt, ["--format", "json", "reconcile"]
        )
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["qty_diff"] == 5


# ---------------------------------------------------------------------------
# prune verb tests
# ---------------------------------------------------------------------------


class TestPruneVerb:
    def test_prune_removes_old_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        # Insert an old row directly then prune.
        from edumatcher.clearing.store import flush_batch, open_writer_connection

        conn = open_writer_connection(db_path)
        flush_batch(
            conn,
            [
                TradeEventRow(
                    id="OLD",
                    ts_ns=1,
                    trade_date="2000-01-01",
                    symbol="AAPL",
                    quantity=1,
                    price=100,
                    buy_order_id=None,
                    sell_order_id=None,
                    buy_gateway_id="GW_A",
                    sell_gateway_id="GW_B",
                    aggressor_side=None,
                    ingest_ts_ns=1,
                )
            ],
            [],
            [],
        )
        conn.close()

        _run(monkeypatch, db_path, ["prune"])
        out = capsys.readouterr().out
        assert "Pruned" in out

    def test_dry_run_does_not_delete(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        from edumatcher.clearing.store import flush_batch, open_writer_connection

        conn = open_writer_connection(db_path)
        flush_batch(
            conn,
            [
                TradeEventRow(
                    id="ANCIENT",
                    ts_ns=1,
                    trade_date="1999-12-31",
                    symbol="AAPL",
                    quantity=1,
                    price=50,
                    buy_order_id=None,
                    sell_order_id=None,
                    buy_gateway_id="GW_A",
                    sell_gateway_id="GW_B",
                    aggressor_side=None,
                    ingest_ts_ns=1,
                )
            ],
            [],
            [],
        )
        conn.close()

        _run(monkeypatch, db_path, ["prune", "--dry-run"])
        out = capsys.readouterr().out
        assert "DRY RUN" in out

        # Row must still be there.
        from edumatcher.clearing.store import open_writer_connection

        conn = open_writer_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM trade_events WHERE id='ANCIENT'"
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ---------------------------------------------------------------------------
# Path resolution tests
# ---------------------------------------------------------------------------


class TestPathResolution:
    def test_explicit_db_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        # Pass the explicit .db file path rather than a directory.
        monkeypatch.setattr(
            "sys.argv", ["pm-clearing-cli", "--datapath", str(db_path), "health"]
        )
        cli_main()
        out = capsys.readouterr().out
        assert str(db_path) in out

    def test_db_name_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        db_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-clearing-cli",
                "--datapath",
                str(db_path.parent),
                "--db-name",
                db_path.name,
                "health",
            ],
        )
        cli_main()
        out = capsys.readouterr().out
        assert "wal_mode" in out or db_path.name in out
