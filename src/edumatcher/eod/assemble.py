"""Build a trading day's :class:`~edumatcher.eod.report.DayReport` from the databases.

Reads the settled day from ``eod.db``, positions and trades from
``clearing.db`` and, when available, market figures from ``stats.db``.  Writes
nothing.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from edumatcher.clearing.store import query_close_snapshots, query_day_trades
from edumatcher.eod.ledger import LedgerError, balances, day_amounts, day_detail
from edumatcher.eod.report import (
    DayReport,
    PositionLine,
    Statement,
    Summary,
    SymbolStats,
    TradeLine,
)
from edumatcher.eod.roster import Trader
from edumatcher.eod.settle import EXCHANGE
from edumatcher.stats.query import query_daily

_ALL = 1_000_000


def _price(ticks: int, tick_decimals: int) -> Decimal:
    """Ticks as a price with the symbol's own number of decimals (10.20, not 10.2)."""
    return Decimal(ticks).scaleb(-tick_decimals)


def build_day(
    clearing: sqlite3.Connection,
    ledger: sqlite3.Connection,
    trade_date: str,
    roster: Mapping[str, Trader],
    stats: sqlite3.Connection | None = None,
) -> DayReport:
    amounts = day_amounts(ledger, trade_date)
    if not amounts:
        raise LedgerError(f"{trade_date} is not settled")
    rounding = amounts.pop(EXCHANGE, 0)
    detail = day_detail(ledger, trade_date)
    running = balances(
        ledger,
        as_of=trade_date,
        openings={g: t.opening_minor for g, t in roster.items()},
    )

    held: dict[str, list[PositionLine]] = {}
    for r in query_close_snapshots(clearing, date_value=trade_date, limit=_ALL):
        if r["net_qty"] != 0:
            mark = r["mark_price"]
            held.setdefault(r["gateway_id"], []).append(
                PositionLine(
                    r["symbol"],
                    r["net_qty"],
                    (None if mark is None else _price(mark, r["tick_decimals"])),
                )
            )

    trades = _trades(clearing, trade_date)
    statements = []
    for gateway in sorted(set(amounts) | set(roster)):
        person = roster.get(gateway)
        # Flat positions stay in the snapshot for good, so a symbol closed out
        # weeks ago would print 0.00 on every statement; show what the trader
        # holds, traded today or gained/lost on today.
        relevant = {p.symbol for p in held.get(gateway, ())} | {
            t.symbol for t in trades.get(gateway, ())
        }
        symbol_pnl = {
            sym: pnl
            for sym, pnl in detail.get(gateway, {}).items()
            if pnl != 0 or sym in relevant
        }
        statements.append(
            Statement(
                gateway=gateway,
                name=person.name if person else gateway,
                email=person.email if person else None,
                listed=person is not None,
                trade_date=trade_date,
                amount_minor=amounts.get(gateway, 0),
                balance_minor=running.get(gateway, 0),
                symbol_pnl=symbol_pnl,
                positions=tuple(held.get(gateway, ())),
                trades=tuple(trades.get(gateway, ())),
            )
        )

    warnings: tuple[str, ...]
    if not roster:
        warnings = ("no roster: statements are keyed by gateway id",)
    else:
        warnings = tuple(
            f"gateway {s.gateway} is not in the roster"
            for s in statements
            if not s.listed
        )
    summary = Summary(
        trade_date,
        rounding,
        sum(amounts.values()) + rounding,
        None if stats is None else _market(stats, trade_date),
    )
    return DayReport(trade_date, tuple(statements), summary, warnings)


def _trades(
    clearing: sqlite3.Connection, trade_date: str
) -> dict[str, list[TradeLine]]:
    """The day's trades per gateway, oldest first, from one query for the day."""
    lines: dict[str, list[TradeLine]] = {}
    for r in query_day_trades(clearing, trade_date):
        buyer, seller = r["buy_gateway_id"], r["sell_gateway_id"]
        sides = {buyer: "SELF"} if buyer == seller else {buyer: "BUY", seller: "SELL"}
        time_utc = datetime.fromtimestamp(r["ts_ns"] / 1e9, UTC).strftime("%H:%M:%S")
        price = _price(r["price"], r["tick_decimals"])
        for gateway, side in sides.items():
            lines.setdefault(gateway, []).append(
                TradeLine(time_utc, r["symbol"], side, r["quantity"], price)
            )
    return lines


def _market(stats: sqlite3.Connection, trade_date: str) -> tuple[SymbolStats, ...]:
    rows, _ = query_daily(stats, date_value=trade_date, symbol=None, limit=10_000)
    return tuple(
        SymbolStats(
            r["symbol"],
            r["volume"],
            r["trade_count"],
            (
                None
                if r["close_price"] is None
                else _price(r["close_price"], r["tick_decimals"])
            ),
        )
        for r in rows
    )
