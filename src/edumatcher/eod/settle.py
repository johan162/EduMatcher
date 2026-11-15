"""End-of-day settlement arithmetic.

A trader's settlement for a trading day is the change in its mark-to-market
equity (cumulative realized + unrealized P&L) since the close of the previous
settled day, summed over symbols and converted to display currency.  Equity is cash
plus positions at the mark, so for every symbol the changes of all gateways
cancel.  What is left over should be float noise from ``avg_cost``: a day is
refused when it exceeds 0.01 per position whose equity changed, and anything
below that, plus the rounding to the minor unit, is booked to ``EXCHANGE``
(``Settlement.rounding_minor`` is the negated exact total, rounded once).

Nothing in this module touches a database except :func:`settle_date`, which
only reads ``position_close_snapshot`` and ``clearing_meta``.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Decimal

from edumatcher.clearing.store import clearing_instance, query_close_snapshots

#: The ledger account that absorbs the rounding residual.
EXCHANGE = "EXCHANGE"

#: A position: ``(gateway_id, symbol)``.
Key = tuple[str, str]

#: Minor units per display-currency unit (2 decimals).
_MINOR = 100

#: A day whose exact total differs from zero by more than this per position
#: whose equity changed is an accounting error, not float noise.  Unchanged
#: positions (the snapshot keeps every flat position for good) add no noise,
#: so they must not widen the tolerance.
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
class Baseline:
    """The equity a date was settled at, and the ``clearing.db`` it came from."""

    equity: dict[Key, Decimal]
    #: ``clearing_meta.instance_id`` at settlement; ``None`` if it had none.
    clearing_instance: str | None


@dataclass(frozen=True)
class Settlement:
    """A day's result: integer minor units per gateway plus the rounding line."""

    amounts_minor: dict[str, int]
    rounding_minor: int
    detail: dict[str, dict[str, Decimal]]
    #: Each position's cumulative equity at this close: the next day's baseline.
    equity: dict[Key, Decimal] = field(default_factory=dict)
    #: The exact (unrounded) total of the day; ``rounding_minor`` is its
    #: negation rounded to minor units, booked to ``EXCHANGE``.
    drift: Decimal = Decimal(0)
    #: The previous settled date's snapshot in ``clearing.db`` no longer matches
    #: the equity recorded when it was settled (it closed again since).
    baseline_changed: bool = False
    #: ``clearing.db`` was replaced after the previous date was settled, and
    #: that date traded again in the new one: the day starts from zero.
    baseline_reset: bool = False
    #: The ``clearing.db`` this day was settled from (see :class:`Baseline`).
    clearing_instance: str | None = None


def _equity(snap: Snapshot) -> Decimal:
    """Cumulative P&L of one position in display currency."""
    ticks = Decimal(repr(snap.realized_pnl)) + Decimal(repr(snap.unrealized_pnl))
    return ticks / (Decimal(10) ** snap.tick_decimals)


def equities(snapshots: Iterable[Snapshot]) -> dict[Key, Decimal]:
    """Cumulative equity per position, in display currency."""
    return {(s.gateway_id, s.symbol): _equity(s) for s in snapshots}


def day_pnl(
    today: Iterable[Snapshot], before: Mapping[Key, Decimal]
) -> dict[str, dict[str, Decimal]]:
    """Per gateway and symbol, the change in equity since the previous close.

    A position that is new today has no previous equity (0).  A position that
    is in the baseline but not in today's snapshot is ignored: there is no
    information about it, and a made-up loss would break the zero sum.
    """
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
    today: Iterable[Snapshot], baseline: Mapping[Key, Decimal]
) -> Settlement:
    """Turn a close snapshot and the previous close's equity into a settlement."""
    today = list(today)
    if any(s.gateway_id == EXCHANGE for s in today):
        raise SettlementError(f"a gateway may not be called {EXCHANGE}")
    detail = day_pnl(today, baseline)
    exact = {
        gw: sum(per_symbol.values(), Decimal(0)) for gw, per_symbol in detail.items()
    }
    drift = sum(exact.values(), Decimal(0))
    changed = sum(1 for per in detail.values() for v in per.values() if v != 0)
    if abs(drift) > _TOLERANCE_PER_KEY * max(changed, 1):
        raise SettlementError(
            f"the day does not sum to zero: exact total {drift} over "
            f"{changed} changed position(s)"
        )
    minor, total = to_minor_units(exact)
    return Settlement(minor, -total, detail, equities(today), drift)


def settle_date(
    clearing: sqlite3.Connection,
    trade_date: str,
    previous: str | None,
    settled: Baseline | None = None,
) -> Settlement:
    """Settle ``trade_date`` from its snapshot in ``clearing.db``.

    ``previous`` is the latest *settled* date before ``trade_date``, and the
    equity at its close is the baseline.  Measuring from the latest snapshot
    instead would silently drop the equity change of any snapshot date in
    between that was never settled.  Every unsettled day since ``previous`` (a
    weekend, a skipped day) is part of this one interval.

    ``settled`` is what ``eod.db`` recorded when ``previous`` was settled, and
    its equity wins over ``previous``'s snapshot: pm-clearing rewrites a
    date's snapshot when that date closes again (a reopen, another shutdown
    without a scheduler), and measuring from the rewritten one would drop
    everything traded in between.  With the recorded baseline that change
    falls into this day, and ``baseline_changed`` says so.  ``previous``
    without a recorded baseline uses its snapshot.

    Everyone starts from zero when there is no ``previous``, when
    ``clearing.db`` has no snapshot for it (it was reset), and when it is a
    different ``clearing.db`` than ``previous`` was settled from (reset, and
    ``previous``'s date traded again): equity restarted at zero with it
    (``baseline_reset``).  Unknown instances count as the same file.
    """
    today = _snapshots(clearing, trade_date)
    if not today:
        raise SettlementError(f"no close snapshot for {trade_date}")
    instance = clearing_instance(clearing)
    snapshot = equities(_snapshots(clearing, previous)) if previous else {}
    if not snapshot or settled is None:
        result = compute_settlement(today, snapshot)
    elif settled.clearing_instance not in (None, instance) and instance is not None:
        result = replace(compute_settlement(today, {}), baseline_reset=True)
    else:
        result = replace(
            compute_settlement(today, settled.equity),
            baseline_changed=snapshot != settled.equity,
        )
    return replace(result, clearing_instance=instance)


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
