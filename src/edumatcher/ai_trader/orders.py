"""Order lifecycle manager (OLM) and position book for one agent.

Correlation is by ``tag`` (the order's ``client_tag``): the engine assigns
order ids, and an ALF client never chooses one, so the agent only learns an
order's id from the first event that carries both. Positions move **only** on
fills (``fill_qty`` is the increment matched in that event), never on an
optimistic cancel, so a cancel/fill race cannot double count.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edumatcher.models.order import TIF, OrderType


class OrderState(str, Enum):
    PENDING = "PENDING"  # sent, not yet acknowledged
    LIVE = "LIVE"
    CANCEL_PENDING = "CANCEL_PENDING"


class Purpose(str, Enum):
    TRADE = "TRADE"
    PROTECT = "PROTECT"  # stop / trailing stop / bracket leg on a position


@dataclass
class LiveOrder:
    tag: str
    symbol: str
    side: str
    order_type: OrderType
    tif: TIF
    qty: int
    remaining: int
    price_ticks: int | None
    submitted_at: float
    purpose: Purpose = Purpose.TRADE
    order_id: str | None = None
    state: OrderState = OrderState.PENDING
    cancel_sent_at: float | None = None
    oco_tag: str | None = None


@dataclass
class Position:
    qty: int = 0
    avg_cost: float = 0.0  # ticks
    realized: float = 0.0  # ticks x shares

    def apply(self, side: str, qty: int, price_ticks: int) -> None:
        signed = qty if side == "BUY" else -qty
        if self.qty == 0 or (self.qty > 0) == (signed > 0):
            total = self.qty + signed
            self.avg_cost = (
                (self.avg_cost * abs(self.qty) + price_ticks * qty) / abs(total)
                if total
                else 0.0
            )
            self.qty = total
            return
        # reducing, possibly flipping
        closing = min(abs(signed), abs(self.qty))
        direction = 1 if self.qty > 0 else -1
        self.realized += closing * (price_ticks - self.avg_cost) * direction
        self.qty += signed
        if self.qty == 0:
            self.avg_cost = 0.0
        elif (self.qty > 0) != (direction > 0):
            self.avg_cost = float(price_ticks)  # flipped: new position at fill


class OrderManager:
    def __init__(self) -> None:
        self.orders: dict[str, LiveOrder] = {}  # by tag
        self._by_id: dict[str, str] = {}  # engine order id -> tag
        self.positions: dict[str, Position] = {}
        self.fills = 0
        self.filled_qty = 0

    # --- lookup ---------------------------------------------------------------
    def _resolve(self, order_id: str | None, tag: str | None) -> LiveOrder | None:
        if tag and tag in self.orders:
            order = self.orders[tag]
            if order_id and order.order_id is None:
                order.order_id = order_id
                self._by_id[order_id] = tag
            return order
        if order_id:
            known = self._by_id.get(order_id)
            if known is not None:
                return self.orders.get(known)
        return None

    def _drop(self, order: LiveOrder) -> None:
        self.orders.pop(order.tag, None)
        if order.order_id:
            self._by_id.pop(order.order_id, None)

    def position(self, symbol: str) -> Position:
        pos = self.positions.get(symbol)
        if pos is None:
            pos = self.positions[symbol] = Position()
        return pos

    # --- outbound ---------------------------------------------------------------
    def track(self, order: LiveOrder) -> None:
        self.orders[order.tag] = order

    def mark_cancel(self, order: LiveOrder, now: float) -> None:
        order.state = OrderState.CANCEL_PENDING
        order.cancel_sent_at = now

    # --- inbound events -------------------------------------------------------------
    def on_ack(self, order_id: str | None, tag: str | None) -> LiveOrder | None:
        order = self._resolve(order_id, tag)
        if order is not None and order.state == OrderState.PENDING:
            order.state = OrderState.LIVE
        return order

    def on_reject(self, order_id: str | None, tag: str | None) -> LiveOrder | None:
        """A new order refused (or, for MARKET/IOC/FOK, killed after its ack)."""
        order = self._resolve(order_id, tag)
        if order is not None:
            self._drop(order)
        return order

    def on_cancel_reject(self, order_id: str | None) -> LiveOrder | None:
        """Cancel refused with ORDER_NOT_FOUND: the order had already ended.

        The engine publishes the fill or expiry before it handles the cancel,
        on the same socket, so its terminal event has already been applied.
        Anything still tracked under that id is stale.
        """
        order = self._resolve(order_id, None)
        if order is not None:
            self._drop(order)
        return order

    def on_fill(
        self,
        *,
        order_id: str | None,
        tag: str | None,
        symbol: str,
        side: str,
        fill_qty: int,
        fill_price_ticks: int,
        remaining: int | None,
    ) -> LiveOrder | None:
        if fill_qty <= 0:
            return None
        # The position is the truth whether or not the order is still tracked
        # (an OCO leg before its ack, an order from before a restart).
        self.position(symbol).apply(side, fill_qty, fill_price_ticks)
        self.fills += 1
        self.filled_qty += fill_qty
        order = self._resolve(order_id, tag)
        if order is None:
            return None
        if order.state == OrderState.PENDING:
            order.state = OrderState.LIVE
        order.remaining = (
            max(0, remaining) if remaining is not None else order.remaining - fill_qty
        )
        if order.remaining <= 0:
            self._drop(order)
        return order

    def on_done(self, order_id: str | None, tag: str | None) -> LiveOrder | None:
        """Cancelled or expired."""
        order = self._resolve(order_id, tag)
        if order is not None:
            self._drop(order)
        return order

    def on_oco_ack(
        self, oco_tag: str, accepted: bool, leg_ids: tuple[str, str]
    ) -> list[LiveOrder]:
        legs = [o for o in self.orders.values() if o.oco_tag == oco_tag]
        if not accepted:
            for leg in legs:
                self._drop(leg)
            return legs
        for leg, order_id in zip(sorted(legs, key=lambda o: o.tag), leg_ids):
            if order_id:
                leg.order_id = order_id
                leg.state = OrderState.LIVE
                self._by_id[order_id] = leg.tag
        return legs

    def reset_positions(self, positions: dict[str, tuple[int, float]]) -> None:
        """Adopt the engine's position ledger (net qty, avg cost in ticks)."""
        self.positions = {
            sym: Position(qty=qty, avg_cost=cost)
            for sym, (qty, cost) in positions.items()
        }

    def forget_all(self) -> None:
        """Drop every tracked order (the session they lived in is gone)."""
        self.orders.clear()
        self._by_id.clear()

    # --- queries ------------------------------------------------------------------
    def live(
        self, symbol: str, purpose: Purpose | None = Purpose.TRADE
    ) -> list[LiveOrder]:
        return [
            o
            for o in self.orders.values()
            if o.symbol == symbol and (purpose is None or o.purpose == purpose)
        ]

    def open_qty(self, symbol: str, side: str) -> int:
        """Unfilled quantity of TRADE orders on one side (cancels still count)."""
        return sum(
            o.remaining
            for o in self.orders.values()
            if o.symbol == symbol and o.side == side and o.purpose == Purpose.TRADE
        )

    def stale(
        self,
        now: float,
        *,
        max_age: float,
        drift_ticks: int | None,
        touch: dict[str, tuple[int | None, int | None]],
    ) -> list[LiveOrder]:
        """LIVE trade orders to cancel: too old, or left behind by the market.

        "Left behind" is measured against the order's own side of the book:
        a buy more than ``drift_ticks`` below the best bid, a sell more than
        that above the best ask. (Measuring against the mid, as first
        designed, made every passive order in a wide spread stale on arrival.)
        ``touch`` maps symbol -> (best bid, best ask) in ticks.
        """
        out: list[LiveOrder] = []
        for o in self.orders.values():
            if o.state != OrderState.LIVE or o.purpose != Purpose.TRADE:
                continue
            if o.order_type not in (OrderType.LIMIT, OrderType.ICEBERG):
                continue
            if o.tif in (TIF.ATO, TIF.ATC):
                continue  # the auction ends them
            if now - o.submitted_at >= max_age:
                out.append(o)
                continue
            if drift_ticks is None or o.price_ticks is None:
                continue
            bid, ask = touch.get(o.symbol, (None, None))
            if (
                o.side == "BUY"
                and bid is not None
                and o.price_ticks < bid - drift_ticks
            ):
                out.append(o)
            elif (
                o.side == "SELL"
                and ask is not None
                and o.price_ticks > ask + drift_ticks
            ):
                out.append(o)
        return out

    def unanswered_cancels(self, now: float, timeout: float) -> list[LiveOrder]:
        return [
            o
            for o in self.orders.values()
            if o.state == OrderState.CANCEL_PENDING
            and o.cancel_sent_at is not None
            and now - o.cancel_sent_at >= timeout
        ]
