"""A trading day's statements and exchange summary, as files.

Everything here is pure data in, text out; :mod:`edumatcher.eod.assemble`
builds the :class:`DayReport` from the databases.  The wording of the
statements lives in this module only.

Layout of ``<data>/settlement/<date>/`` (not ``<data>/eod/``, which is the
engine's)::

    statements/<gateway>.md|.json|.csv
    summary.md|.json
    instructions.csv      mail-merge input: who pays or receives what
    leaderboard.csv       balance ranking (informational)
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

_TOP = 3


@dataclass(frozen=True)
class PositionLine:
    symbol: str
    net_qty: int
    mark: Decimal | None


@dataclass(frozen=True)
class TradeLine:
    time_utc: str
    symbol: str
    side: str
    quantity: int
    price: Decimal


@dataclass(frozen=True)
class Statement:
    gateway: str
    name: str
    email: str | None
    listed: bool
    trade_date: str
    amount_minor: int
    balance_minor: int
    symbol_pnl: dict[str, Decimal]
    positions: tuple[PositionLine, ...]
    trades: tuple[TradeLine, ...]
    #: The last settled date before ``trade_date`` when the result covers more
    #: than one closed day (a closed day in between was never settled); the
    #: trade list is ``trade_date``'s only.  ``None`` for a one-day result.
    since: str | None = None


@dataclass(frozen=True)
class SymbolStats:
    symbol: str
    volume: int
    trade_count: int
    close: Decimal | None


@dataclass(frozen=True)
class Summary:
    trade_date: str
    #: The residual booked to the EXCHANGE account.
    rounding_minor: int
    #: Sum of every account including EXCHANGE; the proof that the day nets out.
    total_minor: int
    #: ``None`` when the statistics database was not available.
    symbols: tuple[SymbolStats, ...] | None


@dataclass(frozen=True)
class DayReport:
    trade_date: str
    statements: tuple[Statement, ...]
    summary: Summary
    warnings: tuple[str, ...]


def fmt_minor(minor: int) -> str:
    """Minor units as a signed decimal string: ``-1234`` -> ``-12.34``."""
    sign = "-" if minor < 0 else ""
    whole, cents = divmod(abs(minor), 100)
    return f"{sign}{whole}.{cents:02d}"


def _verdict(amount_minor: int) -> str:
    if amount_minor > 0:
        return f"The exchange owes you {fmt_minor(amount_minor)}."
    if amount_minor < 0:
        return f"You owe the exchange {fmt_minor(-amount_minor)}."
    return "Nothing to pay or receive today."


def render_statement_md(s: Statement) -> str:
    who = f"{s.name} ({s.gateway})"
    if s.email:
        who += f" <{s.email}>"
    lines = [f"# Statement for {s.trade_date}", "", who]
    if not s.listed:
        lines += ["", "*This gateway is not in the roster.*"]
    lines += [
        "",
        f"**{_verdict(s.amount_minor)}**",
        "",
        (
            f"- Result since the close of {s.since}: {fmt_minor(s.amount_minor)}"
            f" (no day in between was settled; the trades below are {s.trade_date}'s)"
            if s.since
            else f"- Today's result: {fmt_minor(s.amount_minor)}"
        ),
        f"- Balance after today: {fmt_minor(s.balance_minor)}",
        "",
        "## Result by symbol",
        "",
    ]
    if s.symbol_pnl:
        lines += ["| Symbol | Result |", "|---|---:|"]
        lines += [f"| {sym} | {pnl:.2f} |" for sym, pnl in sorted(s.symbol_pnl.items())]
    else:
        lines.append("Nothing held, traded or changed today.")
    lines += ["", "## Open positions at the close", ""]
    if s.positions:
        lines += ["| Symbol | Quantity | Closing price |", "|---|---:|---:|"]
        lines += [
            f"| {p.symbol} | {p.net_qty} | {p.mark if p.mark is not None else '-'} |"
            for p in s.positions
        ]
    else:
        lines.append("No open positions.")
    lines += ["", "## Trades", ""]
    if s.trades:
        lines += [
            "| Time (UTC) | Symbol | Side | Quantity | Price |",
            "|---|---|---|---:|---:|",
        ]
        lines += [
            f"| {t.time_utc} | {t.symbol} | {t.side} | {t.quantity} | {t.price} |"
            for t in s.trades
        ]
    else:
        lines.append("No trades today.")
    return "\n".join(lines) + "\n"


def _statement_dict(s: Statement) -> dict[str, Any]:
    return {
        "trade_date": s.trade_date,
        "gateway": s.gateway,
        "name": s.name,
        "email": s.email,
        "listed": s.listed,
        "amount_minor": s.amount_minor,
        "amount": fmt_minor(s.amount_minor),
        "since": s.since,
        "balance_minor": s.balance_minor,
        "balance": fmt_minor(s.balance_minor),
        "symbol_pnl": {k: f"{v:.2f}" for k, v in sorted(s.symbol_pnl.items())},
        "positions": [
            {
                "symbol": p.symbol,
                "net_qty": p.net_qty,
                "mark": None if p.mark is None else str(p.mark),
            }
            for p in s.positions
        ],
        "trades": [
            {
                "time_utc": t.time_utc,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": str(t.price),
            }
            for t in s.trades
        ],
    }


def _write_statement_csv(path: Path, s: Statement) -> None:
    qty = {p.symbol: p for p in s.positions}
    with path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["symbol", "day_pnl", "net_qty", "mark"])
        for sym, pnl in sorted(s.symbol_pnl.items()):
            pos = qty.get(sym)
            out.writerow(
                [
                    sym,
                    f"{pnl:.2f}",
                    pos.net_qty if pos else 0,
                    "" if pos is None or pos.mark is None else pos.mark,
                ]
            )


def _write_instructions(path: Path, statements: tuple[Statement, ...]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["gateway", "name", "email", "amount", "direction", "balance"])
        for s in statements:
            direction = (
                "receive"
                if s.amount_minor > 0
                else "pay" if s.amount_minor < 0 else "none"
            )
            out.writerow(
                [
                    s.gateway,
                    s.name,
                    s.email or "",
                    fmt_minor(s.amount_minor),
                    direction,
                    fmt_minor(s.balance_minor),
                ]
            )


def _write_leaderboard(path: Path, statements: tuple[Statement, ...]) -> None:
    ranked = sorted(statements, key=lambda s: (-s.balance_minor, s.gateway))
    with path.open("w", newline="", encoding="utf-8") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["rank", "gateway", "name", "balance"])
        rank = 0
        previous: int | None = None
        for position, s in enumerate(ranked, start=1):
            if s.balance_minor != previous:
                rank, previous = position, s.balance_minor
            out.writerow([rank, s.gateway, s.name, fmt_minor(s.balance_minor)])


def _movers(
    statements: tuple[Statement, ...],
) -> tuple[list[Statement], list[Statement]]:
    winners = sorted(
        (s for s in statements if s.amount_minor > 0),
        key=lambda s: (-s.amount_minor, s.gateway),
    )
    losers = sorted(
        (s for s in statements if s.amount_minor < 0),
        key=lambda s: (s.amount_minor, s.gateway),
    )
    return winners[:_TOP], losers[:_TOP]


def _summary_dict(rep: DayReport) -> dict[str, Any]:
    winners, losers = _movers(rep.statements)
    sm = rep.summary
    return {
        "trade_date": rep.trade_date,
        "accounts": len(rep.statements),
        "total": fmt_minor(sm.total_minor),
        "rounding": fmt_minor(sm.rounding_minor),
        "top_winners": [
            {"gateway": s.gateway, "amount": fmt_minor(s.amount_minor)} for s in winners
        ],
        "top_losers": [
            {"gateway": s.gateway, "amount": fmt_minor(s.amount_minor)} for s in losers
        ],
        "symbols": (
            None
            if sm.symbols is None
            else [
                {
                    "symbol": x.symbol,
                    "volume": x.volume,
                    "trade_count": x.trade_count,
                    "close": None if x.close is None else str(x.close),
                }
                for x in sm.symbols
            ]
        ),
        "warnings": list(rep.warnings),
    }


def _render_summary_md(rep: DayReport) -> str:
    data = _summary_dict(rep)
    lines = [
        f"# Exchange summary for {rep.trade_date}",
        "",
        f"- Accounts settled: {data['accounts']}",
        f"- Sum of all accounts: {data['total']}",
        f"- Rounding booked to the exchange: {data['rounding']}",
        "",
        "## Biggest winners",
        "",
    ]
    lines += [f"- {w['gateway']}: {w['amount']}" for w in data["top_winners"]] or [
        "None."
    ]
    lines += ["", "## Biggest losers", ""]
    lines += [f"- {w['gateway']}: {w['amount']}" for w in data["top_losers"]] or [
        "None."
    ]
    lines += ["", "## Market", ""]
    if data["symbols"] is None:
        lines.append("Market statistics unavailable.")
    else:
        lines += ["| Symbol | Volume | Trades | Close |", "|---|---:|---:|---:|"]
        lines += [
            f"| {x['symbol']} | {x['volume']} | {x['trade_count']} | {x['close'] or '-'} |"
            for x in data["symbols"]
        ]
    if rep.warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in rep.warnings]
    return "\n".join(lines) + "\n"


def _write_files(root: Path, rep: DayReport) -> None:
    (root / "statements").mkdir(parents=True)
    for s in rep.statements:
        # Not with_suffix(): it would cut "GW.A" to "GW" and let "GW.B"
        # overwrite it.
        folder = root / "statements"
        (folder / f"{s.gateway}.md").write_text(
            render_statement_md(s), encoding="utf-8"
        )
        (folder / f"{s.gateway}.json").write_text(
            json.dumps(_statement_dict(s), indent=2) + "\n", encoding="utf-8"
        )
        _write_statement_csv(folder / f"{s.gateway}.csv", s)
    (root / "summary.md").write_text(_render_summary_md(rep), encoding="utf-8")
    (root / "summary.json").write_text(
        json.dumps(_summary_dict(rep), indent=2) + "\n", encoding="utf-8"
    )
    _write_instructions(root / "instructions.csv", rep.statements)
    _write_leaderboard(root / "leaderboard.csv", rep.statements)


def write_day(base: Path, rep: DayReport) -> Path:
    """Write the day under ``base/<date>``, replacing any earlier version.

    Files go to a sibling work directory that is renamed into place at the end,
    so a reader never sees a half-written day.  A failed write leaves the
    previous version in place; if the final rename fails after the previous
    version was moved aside, it is moved back.
    """
    final = base / rep.trade_date
    work = base / f".{rep.trade_date}.partial"
    old = base / f".{rep.trade_date}.old"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        _write_files(work, rep)
        if final.exists():
            shutil.rmtree(old, ignore_errors=True)
            final.rename(old)
            work.rename(final)
            shutil.rmtree(old, ignore_errors=True)
        else:
            work.rename(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        if old.exists() and not final.exists():
            old.rename(final)  # the swap failed halfway: put the old day back
        raise
    return final
