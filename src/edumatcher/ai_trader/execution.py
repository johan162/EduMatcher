"""Execution styles: *how* an intent becomes orders.

``passive``     LIMIT behind the touch (``offset_ticks``; 0 joins the touch)
``marketable``  LIMIT through the touch (``cross_ticks`` past it); rests if not filled
``sweep``       MARKET, IOC or FOK (``sweep_type``) against the opposite side
``iceberg``     ICEBERG behind the touch showing ``visible_fraction``
``twap``        a parent order worked in ``slices`` child orders over ``horizon_sec``

Any style turns marketable when the intent's urgency reaches
``urgency_cross``. In call phases (pre-open and the auctions) every style
becomes an auction order straddling the reference price, with TIF ATO/ATC
in the auctions, so agents build crossing interest for the uncross.
Prices are clamped to the symbol's collar band and quantities to its order
limits, so agents do not send what the engine would refuse.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from edumatcher.ai_trader.actions import NewOrder
from edumatcher.ai_trader.market_state import SymbolState
from edumatcher.ai_trader.session_policy import (
    auction_tif,
    is_call_phase,
    order_allowed,
)
from edumatcher.ai_trader.strategies import Intent
from edumatcher.models.order import TIF, OrderType

STYLES = ("passive", "marketable", "sweep", "iceberg", "twap")
SWEEP_TYPES = {"MARKET": OrderType.MARKET, "IOC": OrderType.IOC, "FOK": OrderType.FOK}


@dataclass(frozen=True)
class ExecutionSpec:
    style: str = "passive"
    offset_ticks: int = 1
    cross_ticks: int = 0
    sweep_type: str = "MARKET"
    visible_fraction: float = 0.2
    slices: int = 5
    horizon_sec: float = 300.0
    #: Child style of a twap parent: passive or marketable.
    child_style: str = "passive"
    tif: str = "DAY"  # DAY | GTC for resting orders
    urgency_cross: float = 0.8
    #: Probability of taking part in a given call-phase decision.
    auction_participation: float = 0.5


@dataclass
class TwapParent:
    symbol: str
    side: str
    remaining: int
    slices_left: int
    interval: float
    next_at: float
    urgency: float


@dataclass
class Executor:
    spec: ExecutionSpec
    twaps: dict[str, TwapParent] = field(default_factory=dict)

    # --- public -----------------------------------------------------------
    def orders_for(
        self,
        intent: Intent,
        st: SymbolState,
        qty: int,
        phase: str,
        now: float,
        rng: random.Random,
        new_tag: "TagFactory",
    ) -> list[NewOrder]:
        if qty <= 0:
            return []
        if is_call_phase(phase):
            if rng.random() >= self.spec.auction_participation:
                return []
            order = self._auction_order(intent, st, qty, phase, rng, new_tag)
            return [order] if order else []
        if self.spec.style == "twap":
            if intent.symbol not in self.twaps:
                slices = max(1, min(self.spec.slices, qty))
                interval = self.spec.horizon_sec / slices
                self.twaps[intent.symbol] = TwapParent(
                    intent.symbol,
                    intent.side,
                    qty,
                    slices,
                    interval,
                    now,
                    intent.urgency,
                )
            return self.due_twap_slices(
                st_lookup={intent.symbol: st},
                phase=phase,
                now=now,
                rng=rng,
                new_tag=new_tag,
            )
        order = self._continuous_order(
            self.spec.style,
            intent.side,
            intent.urgency,
            st,
            qty,
            phase,
            new_tag,
            limit=intent.limit,
        )
        return [order] if order else []

    def due_twap_slices(
        self,
        st_lookup: dict[str, SymbolState],
        phase: str,
        now: float,
        rng: random.Random,
        new_tag: "TagFactory",
    ) -> list[NewOrder]:
        out: list[NewOrder] = []
        if phase != "CONTINUOUS":
            return out
        for sym, parent in list(self.twaps.items()):
            st = st_lookup.get(sym)
            if st is None or now < parent.next_at:
                continue
            child_qty = math.ceil(parent.remaining / parent.slices_left)
            order = self._continuous_order(
                self.spec.child_style,
                parent.side,
                parent.urgency,
                st,
                child_qty,
                phase,
                new_tag,
                limit=None,
            )
            parent.slices_left -= 1
            parent.remaining -= child_qty
            parent.next_at = now + parent.interval
            if parent.slices_left <= 0 or parent.remaining <= 0:
                del self.twaps[sym]
            if order:
                out.append(order)
        return out

    def cancel_twaps(self) -> None:
        self.twaps.clear()

    # --- internals ----------------------------------------------------------------
    def _continuous_order(
        self,
        style: str,
        side: str,
        urgency: float,
        st: SymbolState,
        qty: int,
        phase: str,
        new_tag: "TagFactory",
        limit: int | None,
    ) -> NewOrder | None:
        """One order for a continuous-trading decision. A crossing order is
        priced at ``limit`` when the strategy gave one, else ``cross_ticks``
        past the touch."""
        spec = self.spec
        tif = TIF(spec.tif)
        buy = side == "BUY"
        touch = st.best_bid if buy else st.best_ask
        far = st.best_ask if buy else st.best_bid
        if urgency >= spec.urgency_cross and style in ("passive", "iceberg"):
            style = "marketable"
        if style == "sweep":
            if far is None:
                style = "passive"  # nothing to take; rest instead
            else:
                otype = SWEEP_TYPES[spec.sweep_type]
                price = None
                if otype != OrderType.MARKET:
                    price = _crossing_price(far, spec.cross_ticks, buy, limit)
                return self._finish(
                    st, side, otype, TIF.DAY, qty, price, phase, new_tag
                )
        if style == "marketable":
            if far is None:
                style = "passive"
            else:
                price = _crossing_price(far, spec.cross_ticks, buy, limit)
                return self._finish(
                    st, side, OrderType.LIMIT, tif, qty, price, phase, new_tag
                )
        base = touch if touch is not None else st.reference()
        if base is None:
            return None
        price = base - spec.offset_ticks if buy else base + spec.offset_ticks
        if far is not None:  # never cross by accident when the book is one-sided
            price = min(price, far - 1) if buy else max(price, far + 1)
        if style == "iceberg" and qty >= 2:
            visible = max(1, min(qty - 1, int(qty * spec.visible_fraction)))
            return self._finish(
                st,
                side,
                OrderType.ICEBERG,
                tif,
                qty,
                price,
                phase,
                new_tag,
                visible=visible,
            )
        return self._finish(st, side, OrderType.LIMIT, tif, qty, price, phase, new_tag)

    def _auction_order(
        self,
        intent: Intent,
        st: SymbolState,
        qty: int,
        phase: str,
        rng: random.Random,
        new_tag: "TagFactory",
    ) -> NewOrder | None:
        ref = st.reference(auction=True)
        if ref is None:
            return None
        spread = max(1, self.spec.offset_ticks * 3)
        # Straddle the reference so buyers and sellers overlap at the uncross.
        jitter = rng.randint(-spread, spread)
        price = ref + jitter if intent.side == "BUY" else ref - jitter
        tif = auction_tif(phase) or TIF(self.spec.tif)
        return self._finish(
            st, intent.side, OrderType.LIMIT, tif, qty, price, phase, new_tag
        )

    def _finish(
        self,
        st: SymbolState,
        side: str,
        otype: OrderType,
        tif: TIF,
        qty: int,
        price: int | None,
        phase: str,
        new_tag: "TagFactory",
        visible: int | None = None,
    ) -> NewOrder | None:
        if price is not None:
            band = st.collar_band()
            if band is not None:
                price = min(max(price, band[0]), band[1])
            price = max(1, price)
        qty = clamp_qty(st, qty, price)
        if qty <= 0:
            return None
        if visible is not None:
            if qty < 2:
                otype, visible = OrderType.LIMIT, None
            else:
                visible = min(visible, qty - 1)
        if not order_allowed(phase, otype, tif, st.halted):
            return None
        return NewOrder(
            tag=new_tag(),
            symbol=st.symbol,
            side=side,
            order_type=otype,
            tif=tif,
            qty=qty,
            price_ticks=price,
            visible_qty=visible,
        )


def _crossing_price(far: int, cross_ticks: int, buy: bool, limit: int | None) -> int:
    if limit is not None:
        return limit
    return far + cross_ticks if buy else far - cross_ticks


def clamp_qty(st: SymbolState, qty: int, price_ticks: int | None) -> int:
    if st.max_order_qty is not None:
        qty = min(qty, st.max_order_qty)
    ref = price_ticks if price_ticks is not None else st.reference()
    if st.max_order_value is not None and ref:
        qty = min(qty, int(st.max_order_value // st.display(ref)))
    return max(0, qty)


class TagFactory:
    """Client tags: ``<GW>-<hex seq>``, within ALF's TAG charset (A-Z0-9-_.)."""

    def __init__(self, gateway_id: str) -> None:
        self._prefix = gateway_id.upper()
        self._seq = 0

    def __call__(self) -> str:
        self._seq += 1
        return f"{self._prefix}-{self._seq:X}"
