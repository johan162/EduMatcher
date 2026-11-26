"""Replay one gateway's position in one symbol through one trading day (CG28).

For teaching: how the position was built, fill by fill, by pm-clearing's own
rules. Each of the gateway's fills that day is applied with the ledger's
``_apply_fill_to_position`` to a scratch position, converted between
precisions with ``_rescale_position`` exactly as ``ClearingLedger._apply_leg``
does, so the replay cannot teach a rule the ledger does not follow.

- **Start:** the pair's last daily row before the day (its ``end_net_qty``
  and ``end_avg_cost``), or flat when there is none. Realized P&L starts at 0:
  the replay reports the day's.
- **Order:** the raw trades in the order clearing stored them (``rowid``),
  which is the order it applied them; a trade on which the gateway is both
  buyer and seller is applied buy leg first, as the ledger does.
- **Check:** whether the end state equals the day's stored daily row and, on
  the pair's latest day, the stored position (net quantity and average cost;
  the day's realized P&L against the daily row). A mismatch is reported with
  the stored values, never corrected. There is no check when there is
  nothing to compare with, or when the replay is cut at ``MAX_STEPS``.

The unrealized P&L of a step is at that fill's price: the ledger also
re-marks a position on other gateways' trades, which are not steps here.
Raw trades older than the retention window are pruned while the daily rows
stay, so a pruned day has ``trades_retained: false`` and no steps.
"""

from __future__ import annotations

# The replay applies fills with the ledger's own private helpers on purpose:
# using them, not a copy, is what keeps it from teaching another rule.
# pyright: reportPrivateUsage=false

import math
import sqlite3
from typing import Any

from edumatcher.clearing.ledger import (
    _apply_fill_to_position,
    _Position,
    _rescale_position,
)
from edumatcher.clearing.store import query_retained_from

#: The most steps one reply carries; a longer day says ``has_more``.
MAX_STEPS = 5000


def _kind(before: int, after: int) -> str:
    """What a fill did to the position, in the words the GUI teaches."""
    if before == 0:
        return "open"
    if after == 0:
        return "close"
    if (before > 0) != (after > 0):
        return "flip"
    return "add" if abs(after) > abs(before) else "reduce"


def _display(ticks: float, tick_decimals: int) -> float:
    return ticks / 10.0**tick_decimals


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def _ends_on(pos: _Position, net_qty: int, avg_cost: float, tick_decimals: int) -> bool:
    """*pos* equals a stored net quantity and average cost (in its own precision)."""
    return pos.net_qty == net_qty and _same(
        _display(pos.avg_cost, pos.tick_decimals), _display(avg_cost, tick_decimals)
    )


def _empty(gateway: str, symbol: str) -> dict[str, Any]:
    return {
        "gateway_id": gateway,
        "symbol": symbol,
        "trade_date": None,
        "trades_retained": True,
        "has_more": False,
        "start": {
            "net_qty": 0,
            "avg_cost": 0.0,
            "avg_cost_ticks": 0.0,
            "tick_decimals": 2,
        },
        "steps": [],
        "matches_daily_row": None,
        "matches_position": None,
        "daily_row": None,
    }


def replay_position(
    conn: sqlite3.Connection, *, gateway: str, symbol: str, trade_date: str | None
) -> dict[str, Any]:
    """The day's replay for *gateway* / *symbol*; the latest day it traded
    when *trade_date* is ``None``."""
    pair = {"gateway": gateway, "symbol": symbol}
    if trade_date is None:
        trade_date = conn.execute(
            "SELECT MAX(trade_date) FROM gateway_daily_summary"
            " WHERE gateway_id = :gateway AND symbol = :symbol",
            pair,
        ).fetchone()[0]
        if trade_date is None:
            return _empty(gateway, symbol)
    day = {**pair, "day": trade_date}

    previous = conn.execute(
        "SELECT end_net_qty, end_avg_cost, tick_decimals FROM gateway_daily_summary"
        " WHERE gateway_id = :gateway AND symbol = :symbol AND trade_date < :day"
        " ORDER BY trade_date DESC LIMIT 1",
        day,
    ).fetchone()
    pos = _Position(gateway_id=gateway, symbol=symbol)
    if previous is not None:
        pos.net_qty = int(previous["end_net_qty"])
        pos.avg_cost = float(previous["end_avg_cost"])
        pos.tick_decimals = int(previous["tick_decimals"])
    start = {
        "net_qty": pos.net_qty,
        "avg_cost": _display(pos.avg_cost, pos.tick_decimals),
        "avg_cost_ticks": pos.avg_cost,
        "tick_decimals": pos.tick_decimals,
    }

    daily = conn.execute(
        "SELECT end_net_qty, end_avg_cost, realized_pnl, tick_decimals"
        " FROM gateway_daily_summary"
        " WHERE gateway_id = :gateway AND symbol = :symbol AND trade_date = :day",
        day,
    ).fetchone()
    retained_from = query_retained_from(conn)
    retained = daily is None or (
        retained_from is not None and trade_date >= retained_from
    )

    trades = (
        conn.execute(
            "SELECT id, ts_ns, quantity, price, tick_decimals,"
            " buy_gateway_id, sell_gateway_id FROM trade_events"
            " WHERE trade_date = :day AND symbol = :symbol"
            " AND (buy_gateway_id = :gateway OR sell_gateway_id = :gateway)"
            " ORDER BY rowid",
            day,
        ).fetchall()
        if retained
        else []
    )

    steps: list[dict[str, Any]] = []
    realized_day = 0.0
    has_more = False
    for t in trades:
        legs = [
            is_buy
            for owner, is_buy in (
                (t["buy_gateway_id"], True),
                (t["sell_gateway_id"], False),
            )
            if owner == gateway
        ]
        for is_buy in legs:
            if len(steps) == MAX_STEPS:
                has_more = True
                break
            tick_decimals = int(t["tick_decimals"])
            realized_day *= 10.0 ** (tick_decimals - pos.tick_decimals)
            _rescale_position(pos, tick_decimals)
            before = pos.net_qty
            price = int(t["price"])
            delta = _apply_fill_to_position(
                pos, int(t["quantity"]), price, is_buy, int(t["ts_ns"])
            )
            realized_day += delta
            money = {
                "price": price,
                "avg_cost": pos.avg_cost,
                "realized_delta": delta,
                "realized_day": realized_day,
                "unrealized": pos.unrealized_pnl,
            }
            step: dict[str, Any] = {
                "trade_id": t["id"],
                "ts_ns": int(t["ts_ns"]),
                "side": "BUY" if is_buy else "SELL",
                "quantity": int(t["quantity"]),
                "kind": _kind(before, pos.net_qty),
                "net_qty": pos.net_qty,
                "tick_decimals": tick_decimals,
            }
            for name, ticks in money.items():
                step[f"{name}_ticks"] = ticks
                step[name] = _display(ticks, tick_decimals)
            steps.append(step)
        if has_more:
            break

    checked = bool(steps) and not has_more
    matches_daily_row = None
    if checked and daily is not None:
        td = int(daily["tick_decimals"])
        matches_daily_row = _ends_on(
            pos, int(daily["end_net_qty"]), float(daily["end_avg_cost"]), td
        ) and _same(
            _display(realized_day, pos.tick_decimals),
            _display(float(daily["realized_pnl"]), td),
        )
    matches_position = None
    latest = conn.execute(
        "SELECT MAX(trade_date) FROM gateway_daily_summary"
        " WHERE gateway_id = :gateway AND symbol = :symbol",
        pair,
    ).fetchone()[0]
    if checked and latest == trade_date:
        stored = conn.execute(
            "SELECT net_qty, avg_cost, tick_decimals FROM gateway_symbol_positions"
            " WHERE gateway_id = :gateway AND symbol = :symbol",
            pair,
        ).fetchone()
        if stored is not None:
            matches_position = _ends_on(
                pos,
                int(stored["net_qty"]),
                float(stored["avg_cost"]),
                int(stored["tick_decimals"]),
            )

    daily_row = None
    if daily is not None:
        td = int(daily["tick_decimals"])
        daily_row = {
            "end_net_qty": int(daily["end_net_qty"]),
            "end_avg_cost": _display(float(daily["end_avg_cost"]), td),
            "end_avg_cost_ticks": float(daily["end_avg_cost"]),
            "realized_pnl": _display(float(daily["realized_pnl"]), td),
            "realized_pnl_ticks": float(daily["realized_pnl"]),
            "tick_decimals": td,
        }
    return {
        "gateway_id": gateway,
        "symbol": symbol,
        "trade_date": trade_date,
        "trades_retained": retained,
        "has_more": has_more,
        "start": start,
        "steps": steps,
        "matches_daily_row": matches_daily_row,
        "matches_position": matches_position,
        "daily_row": daily_row,
    }
