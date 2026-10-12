"""One AI trading agent: a participant id driven by a preset.

An agent never touches a socket. The worker feeds it events and asks it to
``step``; it answers with actions (new orders, cancels, OCOs) for the
transport to send. That keeps every decision reproducible from a seed and
an event sequence, and lets one worker host hundreds of agents.

Each step does, in order: housekeeping (cancel stale orders, give up on
unanswered cancels), due TWAP slices, position protection, and -- when the
Poisson clock says so -- one new decision.
"""

from __future__ import annotations

import logging
import math
import random
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from edumatcher.ai_trader.actions import (
    Action,
    CancelOco,
    CancelOrder,
    NewOco,
    NewOrder,
    OcoLegSpec,
)
from edumatcher.ai_trader.execution import Executor, TagFactory
from edumatcher.ai_trader.market_state import MarketState, SymbolState
from edumatcher.ai_trader.orders import LiveOrder, OrderManager, OrderState, Purpose
from edumatcher.ai_trader.preset import Preset
from edumatcher.ai_trader.risk import RejectBreaker, allowed_qty
from edumatcher.ai_trader.session_policy import order_allowed
from edumatcher.ai_trader.strategies import DecisionContext
from edumatcher.models.order import TIF, OrderType

log = logging.getLogger(__name__)

HOUSEKEEPING_INTERVAL = 1.0
#: A cancel the engine never answered (lost message) is forgotten after this.
CANCEL_TIMEOUT = 15.0
#: Minimum seconds between two protection re-placements on one symbol.
PROTECTION_INTERVAL = 5.0
#: Hard ceiling on one agent's decision rate, far below ALF's 100 commands/s.
MAX_DECISIONS_PER_SEC = 10.0
#: Reject codes that end an order normally: a FOK, IOC or MARKET order that
#: could not fill. Counted as kills, not rejects.
KILL_CODES = frozenset({"INSUFFICIENT_LIQUIDITY"})


def intraday_multiplier(market: MarketState, wall: float) -> float:
    """U-shaped activity over continuous trading, mean 1 over the session.

    ``0.6 + 1.6 * (2x - 1)^2`` for ``x`` the elapsed fraction of the phase,
    divided by its mean 17/15: 1.94 at the open and the close, 0.53 midday.
    1.0 whenever the phase boundaries are unknown.
    """
    if (
        market.phase != "CONTINUOUS"
        or market.phase_since is None
        or market.next_at is None
    ):
        return 1.0
    span = market.next_at - market.phase_since
    if span <= 0:
        return 1.0
    x = min(1.0, max(0.0, (wall - market.phase_since) / span))
    return (0.6 + 1.6 * (2 * x - 1) ** 2) / (17.0 / 15.0)


@dataclass
class AgentStats:
    decisions: int = 0
    submitted: int = 0
    cancels: int = 0
    acked: int = 0
    rejected: Counter[str] = field(default_factory=Counter)
    order_types: Counter[str] = field(default_factory=Counter)
    breaker_trips: int = 0
    killed: int = 0


class Agent:
    def __init__(
        self,
        gateway_id: str,
        preset: Preset,
        universe: list[str],
        seed: int,
        now: float,
    ) -> None:
        self.gateway_id = gateway_id.upper()
        self.preset = preset
        self.universe = list(universe)
        self.rng = random.Random(seed)
        self.strategy = preset.make_strategy()
        self.executor = Executor(preset.execution)
        self.orders = OrderManager()
        self.breaker = RejectBreaker()
        self.new_tag = TagFactory(self.gateway_id)
        self.stats = AgentStats()
        #: Set by the worker to share an aggregate rate budget.
        self.rate_scale = 1.0
        self.next_decision_at = now + self._interval(1.0)
        self._next_housekeeping = now
        self._protect_after: dict[str, float] = {}
        #: Earliest time ``step`` has anything to do; the worker skips the
        #: agent until then.
        self.next_due = now
        #: Counters at the previous close, for per-day figures.
        self._day_base: dict[str, int] = {}

    # --- scheduling -----------------------------------------------------------
    def _interval(self, multiplier: float) -> float:
        rate = self.preset.tempo.decisions_per_min / 60.0 * self.rate_scale * multiplier
        rate = min(max(rate, 1e-6), MAX_DECISIONS_PER_SEC)
        return self.rng.expovariate(rate)

    # --- main entry --------------------------------------------------------------
    def step(self, now: float, wall: float, market: MarketState) -> list[Action]:
        actions: list[Action] = []
        if not market.can_trade():
            self.next_due = now + HOUSEKEEPING_INTERVAL
            return actions
        phase = market.phase
        if now >= self._next_housekeeping:
            self._next_housekeeping = now + HOUSEKEEPING_INTERVAL
            actions += self._housekeeping(now, market)
            actions += self._protect(now, market)
        actions += self._twap(now, market)
        if now >= self.next_decision_at:
            self.next_decision_at = now + self._interval(
                intraday_multiplier(market, wall)
            )
            if not self.breaker.paused(now):
                actions += self._decide(now, phase, market)
        self.next_due = min(
            self.next_decision_at,
            self._next_housekeeping,
            *(t.next_at for t in self.executor.twaps.values()),
        )
        return actions

    # --- decisions -----------------------------------------------------------------
    def _decide(self, now: float, phase: str, market: MarketState) -> list[Action]:
        self.stats.decisions += 1
        ctx = DecisionContext(
            rng=self.rng,
            market=market,
            universe=self.universe,
            position=lambda s: self.orders.position(s).qty,
            now=now,
        )
        intent = self.strategy.decide(ctx)
        if intent is None:
            return []
        st = market.symbols[intent.symbol]
        if (
            len(self.orders.live(intent.symbol))
            >= self.preset.risk.max_live_orders_per_symbol
        ):
            return []
        size = max(1, round(self.preset.tempo.sample_qty(self.rng) * intent.size))
        qty = self._risk_qty(intent.symbol, intent.side, size)
        orders = self.executor.orders_for(
            intent, st, qty, phase, now, self.rng, self.new_tag
        )
        return self._send_trade_orders(orders, now)

    def _twap(self, now: float, market: MarketState) -> list[Action]:
        if not self.executor.twaps:
            return []
        lookup = {
            s: market.symbols[s] for s in self.executor.twaps if s in market.symbols
        }
        orders = self.executor.due_twap_slices(
            lookup, market.phase, now, self.rng, self.new_tag
        )
        clamped = []
        for o in orders:
            qty = self._risk_qty(o.symbol, o.side, o.qty)
            if qty > 0:
                clamped.append(o if qty == o.qty else _with_qty(o, qty))
        return self._send_trade_orders(clamped, now)

    def _risk_qty(self, symbol: str, side: str, qty: int) -> int:
        pos = self.orders.position(symbol).qty
        open_same = self.orders.open_qty(symbol, side)
        return min(
            qty, allowed_qty(side, pos, open_same, self.preset.risk.max_position)
        )

    def _send_trade_orders(self, orders: list[NewOrder], now: float) -> list[Action]:
        out: list[Action] = []
        for o in orders:
            if o.qty <= 0:
                continue
            self.orders.track(
                LiveOrder(
                    tag=o.tag,
                    symbol=o.symbol,
                    side=o.side,
                    order_type=o.order_type,
                    tif=o.tif,
                    qty=o.qty,
                    remaining=o.qty,
                    price_ticks=o.price_ticks,
                    submitted_at=now,
                )
            )
            self.stats.submitted += 1
            self.stats.order_types[f"{o.order_type.value}/{o.tif.value}"] += 1
            out.append(o)
        return out

    # --- housekeeping ----------------------------------------------------------------
    def _housekeeping(self, now: float, market: MarketState) -> list[Action]:
        risk = self.preset.risk
        touch = {
            sym: (market.symbols[sym].best_bid, market.symbols[sym].best_ask)
            for sym in {o.symbol for o in self.orders.orders.values()}
            if sym in market.symbols
        }
        out: list[Action] = []
        for o in self.orders.stale(
            now,
            max_age=risk.max_order_age_sec,
            drift_ticks=risk.stale_price_ticks,
            touch=touch,
        ):
            out += self._cancel(o, now)
        for o in self.orders.unanswered_cancels(now, CANCEL_TIMEOUT):
            log.warning(
                "[%s] cancel of %s never answered; forgetting it",
                self.gateway_id,
                o.tag,
            )
            self.orders.on_done(o.order_id, o.tag)
        return out

    def _cancel(self, o: LiveOrder, now: float) -> list[Action]:
        if o.state == OrderState.CANCEL_PENDING:
            return []
        if o.oco_tag is not None:
            for leg in [
                x for x in self.orders.orders.values() if x.oco_tag == o.oco_tag
            ]:
                self.orders.mark_cancel(leg, now)
            self.stats.cancels += 1
            return [CancelOco(tag=o.oco_tag, symbol=o.symbol)]
        if o.order_id is None:
            return []  # not acknowledged yet; nothing to cancel by id
        self.orders.mark_cancel(o, now)
        self.stats.cancels += 1
        return [CancelOrder(order_id=o.order_id, tag=o.tag, symbol=o.symbol)]

    # --- protection ------------------------------------------------------------------
    def _protect(self, now: float, market: MarketState) -> list[Action]:
        kind = self.preset.risk.protection
        if kind == "none" or market.phase != "CONTINUOUS":
            return []
        out: list[Action] = []
        symbols = set(self.orders.positions) | {
            o.symbol
            for o in self.orders.orders.values()
            if o.purpose == Purpose.PROTECT
        }
        for sym in sorted(symbols):
            pos = self.orders.position(sym)
            existing = self.orders.live(sym, Purpose.PROTECT)
            want_side = "SELL" if pos.qty > 0 else "BUY"
            if existing:
                ok = pos.qty != 0 and all(
                    o.side == want_side and o.qty == abs(pos.qty) for o in existing
                )
                if not ok:
                    seen: set[str] = set()
                    for o in existing:
                        if o.oco_tag is not None and o.oco_tag in seen:
                            continue
                        if o.oco_tag is not None:
                            seen.add(o.oco_tag)
                        out += self._cancel(o, now)
                continue
            if pos.qty == 0 or now < self._protect_after.get(sym, 0.0):
                continue
            st = market.symbols.get(sym)
            if st is None or st.last_trade is None or st.halted:
                continue
            placed = self._place_protection(kind, st, pos.qty, pos.avg_cost, now)
            if placed:
                self._protect_after[sym] = now + PROTECTION_INTERVAL
                out += placed
        return out

    def _place_protection(
        self, kind: str, st: SymbolState, qty: int, avg_cost: float, now: float
    ) -> list[Action]:
        pct = self.preset.risk.protection_pct
        last = st.last_trade
        assert last is not None
        long = qty > 0
        side = "SELL" if long else "BUY"
        size = abs(qty)
        cost = avg_cost if avg_cost > 0 else float(last)
        if long:
            stop = min(math.floor(cost * (1 - pct)), last - 1)
        else:
            stop = max(math.ceil(cost * (1 + pct)), last + 1)
        if stop <= 0:
            return []
        band = st.collar_band()

        def clamp(price: int) -> int:
            if band is not None:
                price = min(max(price, band[0]), band[1])
            return max(1, price)

        if kind == "bracket":
            target = (
                math.ceil(cost * (1 + pct)) if long else math.floor(cost * (1 - pct))
            )
            target = max(target, last + 1) if long else min(target, last - 1)
            if target <= 0:
                return []
            tag = self.new_tag()
            oco = NewOco(
                tag=tag,
                symbol=st.symbol,
                qty=size,
                tif=TIF.DAY,
                leg1=OcoLegSpec(
                    side=side, order_type=OrderType.LIMIT, price_ticks=clamp(target)
                ),
                leg2=OcoLegSpec(
                    side=side, order_type=OrderType.STOP, stop_price_ticks=stop
                ),
            )
            for i, leg in enumerate((oco.leg1, oco.leg2), 1):
                self.orders.track(
                    LiveOrder(
                        tag=f"{tag}-{i}",
                        symbol=st.symbol,
                        side=side,
                        order_type=leg.order_type,
                        tif=TIF.DAY,
                        qty=size,
                        remaining=size,
                        price_ticks=leg.price_ticks,
                        submitted_at=now,
                        purpose=Purpose.PROTECT,
                        oco_tag=tag,
                    )
                )
            self.stats.submitted += 1
            self.stats.order_types["OCO/DAY"] += 1
            return [oco]

        if kind == "trailing":
            order = NewOrder(
                tag=self.new_tag(),
                symbol=st.symbol,
                side=side,
                order_type=OrderType.TRAILING_STOP,
                tif=TIF.DAY,
                qty=size,
                trail_offset_ticks=max(1, round(last * pct)),
            )
        elif kind == "stop_limit":
            gap = max(1, round(stop * pct / 2))
            order = NewOrder(
                tag=self.new_tag(),
                symbol=st.symbol,
                side=side,
                order_type=OrderType.STOP_LIMIT,
                tif=TIF.DAY,
                qty=size,
                stop_price_ticks=stop,
                price_ticks=clamp(stop - gap if long else stop + gap),
            )
        else:
            order = NewOrder(
                tag=self.new_tag(),
                symbol=st.symbol,
                side=side,
                order_type=OrderType.STOP,
                tif=TIF.DAY,
                qty=size,
                stop_price_ticks=stop,
            )
        if not order_allowed("CONTINUOUS", order.order_type, order.tif, st.halted):
            return []
        self.orders.track(
            LiveOrder(
                tag=order.tag,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                tif=order.tif,
                qty=order.qty,
                remaining=order.qty,
                price_ticks=order.price_ticks,
                submitted_at=now,
                purpose=Purpose.PROTECT,
            )
        )
        self.stats.submitted += 1
        self.stats.order_types[f"{order.order_type.value}/{order.tif.value}"] += 1
        return [order]

    # --- inbound events ------------------------------------------------------------------
    def on_ack(
        self,
        now: float,
        *,
        order_id: str | None,
        tag: str | None,
        accepted: bool,
        code: str | None,
        reason: str,
        request_tag: str | None,
    ) -> None:
        if accepted:
            if self.orders.on_ack(order_id, tag) is not None:
                self.stats.acked += 1
            return
        if request_tag is not None:
            # A refused cancel. ORDER_NOT_FOUND: the order already ended.
            if code == "ORDER_NOT_FOUND":
                self.orders.on_cancel_reject(order_id)
            else:
                log.debug("[%s] cancel refused (%s): %s", self.gateway_id, code, reason)
            return
        self.orders.on_reject(order_id, tag)
        if code in KILL_CODES:
            # A FOK or MARKET order that found no liquidity: an outcome, not
            # an error, and never a reason to pause the agent.
            self.stats.killed += 1
            return
        self.stats.rejected[code or reason or "UNKNOWN"] += 1
        log.debug("[%s] order %s rejected (%s): %s", self.gateway_id, tag, code, reason)
        if self.breaker.record(now, code):
            self.stats.breaker_trips += 1
            log.warning(
                "[%s] reject breaker tripped; pausing %.0fs",
                self.gateway_id,
                self.breaker.cooldown,
            )

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
    ) -> None:
        self.orders.on_fill(
            order_id=order_id,
            tag=tag,
            symbol=symbol,
            side=side,
            fill_qty=fill_qty,
            fill_price_ticks=fill_price_ticks,
            remaining=remaining,
        )

    def on_done(self, *, order_id: str | None, tag: str | None) -> None:
        self.orders.on_done(order_id, tag)

    def on_oco_ack(
        self, oco_tag: str, accepted: bool, leg_ids: tuple[str, str], reason: str
    ) -> None:
        self.orders.on_oco_ack(oco_tag, accepted, leg_ids)
        if not accepted:
            self.stats.rejected[f"OCO: {reason}"] += 1

    def on_positions(self, positions: dict[str, tuple[int, float]]) -> None:
        self.orders.reset_positions(positions)

    def on_reconnected(self) -> None:
        """The order-entry session was lost and is back.

        Whatever the participant's disconnect behaviour did to its orders
        (CANCEL_ALL cancels them) happened while no events could reach the
        agent, so tracked orders are stale; positions are re-read by the
        worker.
        """
        self.orders.forget_all()
        self.executor.cancel_twaps()

    def on_session_closed(self) -> None:
        """DAY orders expire at the close; TWAP parents die with the day."""
        self.executor.cancel_twaps()

    def end_of_day(self, market: MarketState) -> dict[str, Any]:
        """Close the day and report it.

        Orders the close expired (DAY, ATO, ATC) are dropped even when their
        expiry never reached the agent, so the next day starts from what the
        engine holds: GTC orders only. P&L is the position ledger's (since the
        agent started or last re-read its positions), marked at the last trade.
        """
        unseen = [o for o in self.orders.orders.values() if o.tif != TIF.GTC]
        for o in unseen:
            self.orders.on_done(o.order_id, o.tag)
        s = self.stats
        counts = {
            "submitted": s.submitted,
            "fills": self.orders.fills,
            "filled_qty": self.orders.filled_qty,
            "cancels": s.cancels,
            "rejected": sum(s.rejected.values()),
            "killed": s.killed,
        }
        day = {k: v - self._day_base.get(k, 0) for k, v in counts.items()}
        self._day_base = counts
        realized = unrealized = 0.0
        gross = 0
        for sym, p in self.orders.positions.items():
            st = market.symbols.get(sym)
            if st is None:
                continue
            realized += p.realized / st.scale
            mark = st.last_trade if st.last_trade is not None else st.reference()
            if p.qty and mark is not None:
                unrealized += p.qty * (mark - p.avg_cost) / st.scale
            gross += abs(p.qty)
        return {
            "agent": self.gateway_id,
            "preset": self.preset.name,
            **day,
            "unseen_expiries": len(unseen),
            "gtc_orders": len(self.orders.orders),
            "gross_position": gross,
            "pnl_realized": round(realized, 2),
            "pnl_mtm": round(realized + unrealized, 2),
        }

    def summary(self) -> str:
        s = self.stats
        rejects = ", ".join(f"{k}={v}" for k, v in s.rejected.most_common(5))
        pos = sum(abs(p.qty) for p in self.orders.positions.values())
        return (
            f"preset={self.preset.name} decisions={s.decisions} submitted={s.submitted} "
            f"acked={s.acked} cancels={s.cancels} fills={self.orders.fills} "
            f"killed={s.killed} "
            f"rejected={sum(s.rejected.values())}{f' ({rejects})' if rejects else ''} "
            f"live={len(self.orders.orders)} gross_pos={pos} "
            f"types={','.join(f'{k}:{v}' for k, v in sorted(s.order_types.items()))}"
        )


def _with_qty(o: NewOrder, qty: int) -> NewOrder:
    """A TWAP child cut down by the position limit (TWAP children are LIMIT)."""
    return replace(o, qty=qty)
