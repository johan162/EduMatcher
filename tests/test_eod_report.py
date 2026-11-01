"""Rendering and writing a day's statements and summary."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest

from edumatcher.eod.report import (
    DayReport,
    PositionLine,
    Statement,
    Summary,
    SymbolStats,
    TradeLine,
    fmt_minor,
    render_statement_md,
    write_day,
)


def statement(amount: int = 1234, balance: int = 5000, **kw: object) -> Statement:
    base: dict[str, object] = dict(
        gateway="GW_A",
        name="Alice",
        email="alice@example.org",
        listed=True,
        trade_date="2026-07-01",
        amount_minor=amount,
        balance_minor=balance,
        symbol_pnl={"AAPL": Decimal("12.34")},
        positions=(PositionLine("AAPL", 100, Decimal("10.50")),),
        trades=(TradeLine("09:30:01", "AAPL", "BUY", 100, Decimal("10.00")),),
    )
    base.update(kw)
    return Statement(**base)  # type: ignore[arg-type]


def report(*statements: Statement) -> DayReport:
    return DayReport(
        trade_date="2026-07-01",
        statements=tuple(statements),
        summary=Summary(
            trade_date="2026-07-01",
            rounding_minor=0,
            total_minor=0,
            symbols=(SymbolStats("AAPL", 300, 3, Decimal("10.50")),),
        ),
        warnings=(),
    )


@pytest.mark.parametrize(
    ("minor", "text"),
    [(0, "0.00"), (5, "0.05"), (-5, "-0.05"), (123456, "1234.56"), (-100, "-1.00")],
)
def test_fmt_minor(minor: int, text: str) -> None:
    assert fmt_minor(minor) == text


class TestStatementText:
    def test_credit(self) -> None:
        assert "The exchange owes you 12.34." in render_statement_md(statement(1234))

    def test_debit(self) -> None:
        assert "You owe the exchange 12.34." in render_statement_md(statement(-1234))

    def test_zero(self) -> None:
        assert "Nothing to pay or receive today." in render_statement_md(statement(0))

    def test_balance_and_identity(self) -> None:
        text = render_statement_md(statement())
        assert "Alice (GW_A)" in text and "alice@example.org" in text
        assert "50.00" in text  # balance

    def test_unlisted_gateway_is_flagged(self) -> None:
        text = render_statement_md(statement(listed=False, name="GW_A", email=None))
        assert "not in the roster" in text

    def test_no_trades_and_no_positions(self) -> None:
        text = render_statement_md(statement(trades=(), positions=()))
        assert "No trades today." in text and "No open positions." in text


class TestWriteDay:
    def test_writes_every_file(self, tmp_path: Path) -> None:
        out = write_day(
            tmp_path, report(statement(1234), statement(-1234, gateway="GW_B"))
        )
        assert out == tmp_path / "2026-07-01"
        names = sorted(p.name for p in (out / "statements").iterdir())
        assert names == [
            "GW_A.csv",
            "GW_A.json",
            "GW_A.md",
            "GW_B.csv",
            "GW_B.json",
            "GW_B.md",
        ]
        for name in (
            "summary.md",
            "summary.json",
            "instructions.csv",
            "leaderboard.csv",
        ):
            assert (out / name).is_file()

    def test_statement_json(self, tmp_path: Path) -> None:
        out = write_day(tmp_path, report(statement()))
        data = json.loads((out / "statements" / "GW_A.json").read_text())
        assert data["gateway"] == "GW_A"
        assert data["amount_minor"] == 1234 and data["amount"] == "12.34"
        assert data["balance"] == "50.00"
        assert data["trades"][0]["quantity"] == 100

    def test_statement_csv(self, tmp_path: Path) -> None:
        out = write_day(tmp_path, report(statement()))
        rows = list(csv.DictReader((out / "statements" / "GW_A.csv").open()))
        assert rows == [
            {"symbol": "AAPL", "day_pnl": "12.34", "net_qty": "100", "mark": "10.50"}
        ]

    def test_instructions_and_leaderboard(self, tmp_path: Path) -> None:
        out = write_day(
            tmp_path,
            report(
                statement(100, 100, gateway="GW_A"),
                statement(-100, 900, gateway="GW_B", name="Bob", email=None),
                statement(0, 900, gateway="GW_C", name="Cy", email=None),
            ),
        )
        ins = list(csv.DictReader((out / "instructions.csv").open()))
        assert [(r["gateway"], r["amount"], r["direction"]) for r in ins] == [
            ("GW_A", "1.00", "receive"),
            ("GW_B", "-1.00", "pay"),
            ("GW_C", "0.00", "none"),
        ]
        board = list(csv.DictReader((out / "leaderboard.csv").open()))
        assert [(r["rank"], r["gateway"]) for r in board] == [
            ("1", "GW_B"),
            ("1", "GW_C"),
            ("3", "GW_A"),
        ]

    def test_summary(self, tmp_path: Path) -> None:
        out = write_day(
            tmp_path, report(statement(1234), statement(-1234, gateway="GW_B"))
        )
        data = json.loads((out / "summary.json").read_text())
        assert data["total"] == "0.00" and data["accounts"] == 2
        assert data["top_winners"][0] == {"gateway": "GW_A", "amount": "12.34"}
        assert data["top_losers"][0] == {"gateway": "GW_B", "amount": "-12.34"}
        assert data["symbols"][0]["volume"] == 300
        assert "Sum of all accounts: 0.00" in (out / "summary.md").read_text()

    def test_summary_without_market_stats(self, tmp_path: Path) -> None:
        rep = report(statement())
        rep = DayReport(
            rep.trade_date, rep.statements, Summary("2026-07-01", 0, 0, None), ()
        )
        out = write_day(tmp_path, rep)
        assert "unavailable" in (out / "summary.md").read_text()

    def test_rewriting_a_day_replaces_it_without_leftovers(
        self, tmp_path: Path
    ) -> None:
        write_day(tmp_path, report(statement(1234), statement(-1234, gateway="GW_B")))
        out = write_day(tmp_path, report(statement(0)))
        assert sorted(p.name for p in (out / "statements").iterdir()) == [
            "GW_A.csv",
            "GW_A.json",
            "GW_A.md",
        ]
        assert [p.name for p in tmp_path.iterdir()] == ["2026-07-01"]

    def test_a_failed_write_leaves_the_old_day_and_no_partial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = write_day(tmp_path, report(statement(1234)))
        before = (out / "summary.md").read_text()

        def boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("edumatcher.eod.report._write_instructions", boom)
        with pytest.raises(OSError):
            write_day(tmp_path, report(statement(0)))
        assert (out / "summary.md").read_text() == before
        assert [p.name for p in tmp_path.iterdir()] == ["2026-07-01"]
