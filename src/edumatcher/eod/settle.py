"""End-of-day settlement arithmetic.

A trader's settlement for a trading day is the change in its mark-to-market
equity (cumulative realized + unrealized P&L) between two consecutive session
closes, summed over symbols and converted to display currency.  Equity is cash
plus positions at the mark, so for every symbol the changes of all gateways
cancel; what is left over is float noise from ``avg_cost`` and the rounding to
the minor unit.

Nothing in this module touches a database except :func:`settle_date`, which
only reads ``position_close_snapshot``.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from edumatcher.clearing.store import query_close_snapshots

#: The ledger account that absorbs the rounding residual.
EXCHANGE = "EXCHANGE"

#: Minor units per display-currency unit (2 decimals).
_MINOR = 100

#: A day whose exact total differs from zero by more than this per position is
#: an accounting error, not float noise.
_TOLERANCE_PER_KEY = Decimal("0.01")


class SettlementError(Exception):
    """The day cannot be settled; nothing should be written."""


@dataclass(frozen=True)
class Snapshot:
    """One ``position_close_snapshot`` row."""

    gateway_id: str
    symbol: str
    realized_pnl: float
    unrealized_pnl: float
    tick_decimals: int


@dataclass(frozen=True)
class Settlement:
    """A day's result: integer minor units per gateway plus the rounding line."""

    amounts_minor: dict[str, int]
    rounding_minor: int
    detail: dict[str, dict[str, Decimal]]


def _equity(snap: Snapshot) -> Decimal:
    """Cumulative P&L of one position in display currency."""
    ticks = Decimal(repr(snap.realized_pnl)) + Decimal(repr(snap.unrealized_pnl))
    return ticks / (Decimal(10) ** snap.tick_decimals)


def day_pnl(
    today: Iterable[Snapshot], previous: Iterable[Snapshot]
) -> dict[str, dict[str, Decimal]]:
    """Per gateway and symbol, the change in equity since the previous close.

    A position that is new today has no previous equity (0).  A position that
    is in the previous snapshot but not in today's is ignored: there is no
    information about it, and a made-up loss would break the zero sum.
    """
    before = {(s.gateway_id, s.symbol): _equity(s) for s in previous}
    result: dict[str, dict[str, Decimal]] = {}
    for snap in today:
        delta = _equity(snap) - before.get((snap.gateway_id, snap.symbol), Decimal(0))
        result.setdefault(snap.gateway_id, {})[snap.symbol] = delta
    return result


def to_minor_units(amounts: Mapping[str, Decimal]) -> tuple[dict[str, int], int]:
    """Round to whole minor units with the largest-remainder method.

    Returns ``(minor, total)`` where ``total`` is the exact sum rounded once.
    The rounded amounts add up to ``total`` exactly, so a day whose exact sum
    is zero stays at zero.  Ties are broken by account id.
    """
    scaled = {a: v * _MINOR for a, v in amounts.items()}
    floors = {a: math.floor(v) for a, v in scaled.items()}
    total = int(sum(scaled.values(), Decimal(0)).to_integral_value(ROUND_HALF_EVEN))
    extra = total - sum(floors.values())
    by_remainder = sorted(scaled, key=lambda a: (-(scaled[a] - floors[a]), a))
    minor = dict(floors)
    for account in by_remainder[:extra]:
        minor[account] += 1
    return minor, total


def compute_settlement(
    today: Iterable[Snapshot], previous: Iterable[Snapshot]
) -> Settlement:
    """Turn two close snapshots into a day's zero-sum settlement."""
    today = list(today)
    if any(s.gateway_id == EXCHANGE for s in today):
        raise SettlementError(f"a gateway may not be called {EXCHANGE}")
    detail = day_pnl(today, previous)
    exact = {
        gw: sum(per_symbol.values(), Decimal(0)) for gw, per_symbol in detail.items()
    }
    drift = sum(exact.values(), Decimal(0))
    if abs(drift) > _TOLERANCE_PER_KEY * len(today):
        raise SettlementError(
            f"the day does not sum to zero: exact total {drift} over "
            f"{len(today)} position(s)"
        )
    minor, total = to_minor_units(exact)
    return Settlement(minor, -total, detail)


def settle_date(clearing: sqlite3.Connection, trade_date: str) -> Settlement:
    """Settle ``trade_date`` from the snapshots in ``clearing.db``.

    The previous snapshot is the latest one before ``trade_date`` (a weekend or
    holiday is just a longer interval); none means everyone starts from zero.
    """
    today = _snapshots(clearing, trade_date)
    if not today:
        raise SettlementError(f"no close snapshot for {trade_date}")
    row = clearing.execute(
        "SELECT MAX(trade_date) FROM position_close_snapshot WHERE trade_date < ?",
        (trade_date,),
    ).fetchone()
    previous = _snapshots(clearing, row[0]) if row and row[0] else []
    return compute_settlement(today, previous)


def _snapshots(clearing: sqlite3.Connection, trade_date: str) -> list[Snapshot]:
    return [
        Snapshot(
            r["gateway_id"],
            r["symbol"],
            r["realized_pnl"],
            r["unrealized_pnl"],
            r["tick_decimals"],
        )
        for r in query_close_snapshots(clearing, date_value=trade_date, limit=1_000_000)
    ]
