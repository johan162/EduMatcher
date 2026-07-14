"""
In-memory position ledger for pm-clearing v2.

Responsibilities
----------------
- Track per-(gateway_id, symbol) running positions in memory.
- Compute realized P&L correctly for all position transitions:
  flat → long, flat → short, adding to a position, partial close,
  full close, cross-zero (long → short, short → long).
- Accumulate per-flush incremental deltas for the daily summary UPSERT.
- Produce ready-to-write PositionRow and DailySummaryRow objects on flush.

Design notes
------------
``Ledger`` has two kinds of state:

1. **Persistent** — ``_positions``: survives across flushes; represents the
   true current position state for every (gateway_id, symbol) seen so far.

2. **Batch** — ``_batch_deltas``: accumulated increments since the last flush;
   reset by ``clear_batch()`` after a successful DB write.

Prices are integers throughout (matching the engine representation).
``avg_cost``, ``realized_pnl``, and ``unrealized_pnl`` are floats because
they involve division and subtraction that can produce non-integer results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any

from edumatcher.clearing.store import DailySummaryRow, PositionRow

# ---------------------------------------------------------------------------
# Internal position state (one per gateway_id + symbol key)
# ---------------------------------------------------------------------------


@dataclass
class _Position:
    """Mutable position state for one (gateway_id, symbol) key."""

    gateway_id: str
    symbol: str
    net_qty: int = 0
    avg_cost: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    mark_price: int | None = None
    buy_qty: int = 0
    sell_qty: int = 0
    buy_notional: int = 0
    sell_notional: int = 0
    last_trade_ts_ns: int | None = None
    tick_decimals: int = 2


# ---------------------------------------------------------------------------
# Internal daily-batch accumulator (one per trade_date + gateway_id + symbol)
# ---------------------------------------------------------------------------


@dataclass
class _BatchDelta:
    """Accumulated increments for one (date, gateway_id, symbol) within the current flush batch."""

    traded_qty: int = 0
    traded_notional: int = 0
    buy_qty: int = 0
    sell_qty: int = 0
    buy_notional: int = 0
    sell_notional: int = 0
    realized_pnl: float = 0.0
    last_trade_ts_ns: int = 0
    tick_decimals: int = 2


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def trade_date(ts_ns: int, tz: tzinfo = timezone.utc) -> str:
    """
    Return the trade-date string (YYYY-MM-DD) for a nanosecond timestamp in the
    exchange's session timezone.

    The trading day should align to the exchange's wall-clock calendar day, not
    UTC (finding CL-M3): bucketing on UTC splits a single evening session — or
    any session that straddles 00:00 UTC — across two ``trade_date`` values, so
    daily summaries no longer match the session the participants actually traded.
    ``tz`` defaults to UTC to preserve the historical behaviour when no session
    timezone is configured.
    """
    ts_sec = ts_ns / 1_000_000_000
    return datetime.fromtimestamp(ts_sec, tz=tz).strftime("%Y-%m-%d")


def trade_date_utc(ts_ns: int) -> str:
    """Return the UTC trade-date string (YYYY-MM-DD) for a nanosecond timestamp."""
    return trade_date(ts_ns, timezone.utc)


def _apply_fill_to_position(
    pos: _Position,
    qty: int,
    price: int,
    is_buy: bool,
    ts_ns: int,
) -> float:
    """
    Apply one fill leg to ``pos``.  Returns the realized P&L delta for this fill.

    ``qty`` is always a positive integer.  ``is_buy`` sets direction.

    Position transitions handled:
    - Flat → Long / Short (opening)
    - Adding to existing same-side position (VWAP avg_cost update)
    - Partial or full close (realize P&L on closed quantity, avg_cost unchanged)
    - Cross-zero (realize P&L on full close, set new avg_cost = fill price)
    """
    signed_qty = qty if is_buy else -qty
    realized_delta = 0.0

    if pos.net_qty == 0:
        # Opening a brand-new position.
        pos.avg_cost = float(price)
        pos.net_qty = signed_qty

    elif (pos.net_qty > 0 and is_buy) or (pos.net_qty < 0 and not is_buy):
        # Adding to an existing same-side position — update VWAP avg_cost.
        existing_notional = pos.avg_cost * abs(pos.net_qty)
        incoming_notional = float(price) * qty
        pos.net_qty += signed_qty
        pos.avg_cost = (existing_notional + incoming_notional) / abs(pos.net_qty)

    else:
        # Reducing or crossing zero.
        open_qty = abs(pos.net_qty)
        close_qty = min(qty, open_qty)

        # Realize P&L on the closed portion.
        if pos.net_qty > 0:
            realized_delta = (float(price) - pos.avg_cost) * close_qty
        else:
            realized_delta = (pos.avg_cost - float(price)) * close_qty

        pos.net_qty += signed_qty

        if pos.net_qty == 0:
            # Full close — flat position.
            pos.avg_cost = 0.0
        elif (is_buy and pos.net_qty > 0) or (not is_buy and pos.net_qty < 0):
            # Cross-zero: the fill exceeded the open position and opened a new
            # position on the opposite side.  The condition checks the
            # *post-update* net_qty intentionally: entering this else-branch
            # already guarantees the original side opposed the fill direction.
            # After adding signed_qty, a net_qty that still matches the fill
            # direction means the excess quantity is now a fresh position, so
            # avg_cost resets to the fill price.
            pos.avg_cost = float(price)

    pos.realized_pnl += realized_delta
    pos.mark_price = price
    pos.unrealized_pnl = pos.net_qty * (float(price) - pos.avg_cost)
    pos.last_trade_ts_ns = ts_ns

    return realized_delta


# ---------------------------------------------------------------------------
# Public Ledger class
# ---------------------------------------------------------------------------


class Ledger:
    """
    In-memory position and P&L ledger.

    Typical call sequence:
    1. Call ``apply_trade`` for every trade in the current buffer.
    2. Call ``get_flush_rows`` to obtain DB-ready objects.
    3. Write them to SQLite via ``store.flush_batch``.
    4. Call ``clear_batch`` to reset the incremental delta accumulators.
    """

    def __init__(self, tz: tzinfo = timezone.utc) -> None:
        # Persistent position state — never cleared.
        self._positions: dict[tuple[str, str], _Position] = {}
        # Batch incremental deltas — cleared after each successful flush.
        self._batch_deltas: dict[tuple[str, str, str], _BatchDelta] = {}
        # Exchange session timezone used to bucket trades into a trading day
        # (finding CL-M3).  Defaults to UTC.
        self._tz = tz

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def restore(self, rows: list[dict[str, Any]]) -> None:
        """
        Warm-start the persistent position state from stored rows (CL-C4).

        Rebuilds ``_positions`` so that after a clearing restart the next trade
        for a (gateway, symbol) key accumulates onto its true cumulative state
        instead of starting from flat and overwriting it.  Only persistent state
        is restored; batch deltas stay empty (the next flush emits fresh deltas
        for post-restart trades only).  Accepts the dicts from
        ``store.fetch_all_positions``.
        """
        for r in rows:
            key = (r["gateway_id"], r["symbol"])
            self._positions[key] = _Position(
                gateway_id=r["gateway_id"],
                symbol=r["symbol"],
                net_qty=int(r["net_qty"]),
                avg_cost=float(r["avg_cost"]),
                realized_pnl=float(r["realized_pnl"]),
                unrealized_pnl=float(r["unrealized_pnl"]),
                mark_price=(None if r["mark_price"] is None else int(r["mark_price"])),
                buy_qty=int(r["buy_qty"]),
                sell_qty=int(r["sell_qty"]),
                buy_notional=int(r["buy_notional"]),
                sell_notional=int(r["sell_notional"]),
                last_trade_ts_ns=(
                    None
                    if r["last_trade_ts_ns"] is None
                    else int(r["last_trade_ts_ns"])
                ),
                tick_decimals=int(r["tick_decimals"]),
            )

    def apply_trade(
        self,
        *,
        symbol: str,
        buy_gateway_id: str,
        sell_gateway_id: str,
        price: int,
        tick_decimals: int = 2,
        quantity: int,
        ts_ns: int,
        ingest_ts_ns: int,
    ) -> None:
        """
        Process one trade event — applies the buy leg and the sell leg.

        ``ingest_ts_ns`` is not used for P&L math but is stored for the
        ``last_trade_ts_ns`` column in daily accumulators.
        """
        bucket_date = trade_date(ts_ns, self._tz)

        for gateway_id, is_buy in (
            (buy_gateway_id, True),
            (sell_gateway_id, False),
        ):
            self._apply_leg(
                gateway_id=gateway_id,
                symbol=symbol,
                price=price,
                tick_decimals=tick_decimals,
                quantity=quantity,
                is_buy=is_buy,
                ts_ns=ts_ns,
                trade_date=bucket_date,
            )

    def get_flush_rows(
        self,
        updated_ts_ns: int,
        position_keys: set[tuple[str, str]] | None = None,
    ) -> tuple[list[PositionRow], list[DailySummaryRow]]:
        """
        Return DB-ready rows for the current batch.

        ``updated_ts_ns`` is written as the flush timestamp on every row.

        Only the positions that actually changed this batch are emitted
        (finding CL-M9): re-writing every position ever seen on every 5-second
        flush rewrites the whole table to touch a handful of rows.  ``position_keys``
        overrides which ``(gateway_id, symbol)`` positions to emit — passed by the
        EOD mark pass, which mutates positions outside the delta accumulator.
        When ``None``, the keys are derived from the current batch deltas.
        """
        if position_keys is None:
            position_keys = {(gw, sym) for (_date, gw, sym) in self._batch_deltas}
        position_rows = [
            _position_to_row(self._positions[key], updated_ts_ns)
            for key in position_keys
            if key in self._positions
        ]
        daily_rows = [
            _delta_to_daily_row(key, delta, self._positions, updated_ts_ns)
            for key, delta in self._batch_deltas.items()
        ]
        return position_rows, daily_rows

    def clear_batch(self) -> None:
        """Reset batch delta accumulators after a successful flush."""
        self._batch_deltas.clear()

    def position(self, gateway_id: str, symbol: str) -> _Position | None:
        """Return the current position state, or None if never seen."""
        return self._positions.get((gateway_id, symbol))

    def all_positions(self) -> list[_Position]:
        """Return all current positions (snapshot — do not mutate)."""
        return list(self._positions.values())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_leg(
        self,
        *,
        gateway_id: str,
        symbol: str,
        price: int,
        tick_decimals: int,
        quantity: int,
        is_buy: bool,
        ts_ns: int,
        trade_date: str,
    ) -> None:
        pos_key = (gateway_id, symbol)
        if pos_key not in self._positions:
            self._positions[pos_key] = _Position(gateway_id=gateway_id, symbol=symbol)
        pos = self._positions[pos_key]
        pos.tick_decimals = tick_decimals

        realized_delta = _apply_fill_to_position(pos, quantity, price, is_buy, ts_ns)

        # Update side-specific cumulative totals.
        if is_buy:
            pos.buy_qty += quantity
            pos.buy_notional += quantity * price
        else:
            pos.sell_qty += quantity
            pos.sell_notional += quantity * price

        # Accumulate daily delta for the UPSERT.
        delta_key = (trade_date, gateway_id, symbol)
        if delta_key not in self._batch_deltas:
            self._batch_deltas[delta_key] = _BatchDelta()
        delta = self._batch_deltas[delta_key]
        delta.tick_decimals = tick_decimals
        delta.traded_qty += quantity
        delta.traded_notional += quantity * price
        if is_buy:
            delta.buy_qty += quantity
            delta.buy_notional += quantity * price
        else:
            delta.sell_qty += quantity
            delta.sell_notional += quantity * price
        delta.realized_pnl += realized_delta
        delta.last_trade_ts_ns = max(delta.last_trade_ts_ns, ts_ns)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _position_to_row(pos: _Position, updated_ts_ns: int) -> PositionRow:
    return PositionRow(
        gateway_id=pos.gateway_id,
        symbol=pos.symbol,
        net_qty=pos.net_qty,
        avg_cost=pos.avg_cost,
        realized_pnl=pos.realized_pnl,
        unrealized_pnl=pos.unrealized_pnl,
        mark_price=pos.mark_price,
        buy_qty=pos.buy_qty,
        sell_qty=pos.sell_qty,
        buy_notional=pos.buy_notional,
        sell_notional=pos.sell_notional,
        last_trade_ts_ns=pos.last_trade_ts_ns,
        updated_ts_ns=updated_ts_ns,
        tick_decimals=pos.tick_decimals,
    )


def _delta_to_daily_row(
    key: tuple[str, str, str],
    delta: _BatchDelta,
    positions: dict[tuple[str, str], _Position],
    updated_ts_ns: int,
) -> DailySummaryRow:
    trade_date, gateway_id, symbol = key
    pos = positions.get((gateway_id, symbol))

    end_net_qty = pos.net_qty if pos else 0
    end_avg_cost = pos.avg_cost if pos else 0.0
    end_unrealized_pnl = pos.unrealized_pnl if pos else 0.0

    return DailySummaryRow(
        trade_date=trade_date,
        gateway_id=gateway_id,
        symbol=symbol,
        delta_traded_qty=delta.traded_qty,
        delta_traded_notional=delta.traded_notional,
        delta_buy_qty=delta.buy_qty,
        delta_sell_qty=delta.sell_qty,
        delta_buy_notional=delta.buy_notional,
        delta_sell_notional=delta.sell_notional,
        delta_net_amount=delta.buy_notional - delta.sell_notional,
        delta_realized_pnl=delta.realized_pnl,
        end_net_qty=end_net_qty,
        end_avg_cost=end_avg_cost,
        end_unrealized_pnl=end_unrealized_pnl,
        last_trade_ts_ns=delta.last_trade_ts_ns if delta.last_trade_ts_ns else None,
        updated_ts_ns=updated_ts_ns,
        tick_decimals=delta.tick_decimals,
    )
