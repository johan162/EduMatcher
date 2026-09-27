"""Pure pricing logic for the market-maker bot.

QuotePricer is stateless with respect to ZMQ — it only computes
bid/ask prices, tracks mid-price, and detects drift.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class PricingStrategy(Protocol):
    """The surface ``MMBot`` needs from a pricing strategy.

    Any class implementing these six members can stand in for
    ``QuotePricer`` in ``MMBot._pricer`` — the state machine, ZMQ handling,
    and reissue/heartbeat logic never depend on which concrete strategy is
    active. ``QuotePricer`` (below) is today's only implementation.
    """

    @property
    def mid_price(self) -> float | None: ...

    @property
    def price_decimals(self) -> int: ...

    def update_mid(self, best_bid: float | None, best_ask: float | None) -> None: ...

    def set_mid(self, price: float) -> None: ...

    def compute_prices(self) -> tuple[float, float]: ...

    def has_drifted(self, quoted_at_mid: float) -> bool: ...


class QuotePricer:
    """Compute symmetric two-sided quote prices around a mid-price.

    This is the ``"symmetric"`` strategy referenced by ``--strategy`` /
    ``mm_bot/config.py`` — it satisfies :class:`PricingStrategy` structurally.

    Parameters
    ----------
    tick_size : float
        Minimum price increment (e.g. 0.01).
    gap : float
        Total spread between bid and ask in price units.
    drift_ticks : int
        Number of ticks the mid must move before drift is signalled.
    """

    def __init__(self, tick_size: float, gap: float, drift_ticks: int) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if gap < 2 * tick_size:
            raise ValueError(
                f"gap ({gap}) must be at least 2 × tick_size ({2 * tick_size})"
            )
        if drift_ticks < 1:
            raise ValueError("drift_ticks must be >= 1")

        self._tick_size = tick_size
        self._gap = gap
        self._drift_ticks = drift_ticks
        self._price_decimals = self._decimals_from_tick(tick_size)
        self._mid_price: float | None = None

    @staticmethod
    def _decimals_from_tick(tick_size: float) -> int:
        """Derive the number of decimal places from tick_size."""
        s = f"{tick_size:.10f}".rstrip("0")
        # f"{x:.10f}" always produces a '.' for float values, so the fallback
        # branch (return 0) is never reached in practice.  Use the length of
        # the fractional part directly.
        return len(s.split(".")[1]) if "." in s else 0

    @property
    def mid_price(self) -> float | None:
        """Current mid-price or None if not yet set."""
        return self._mid_price

    @property
    def price_decimals(self) -> int:
        """Number of decimal places derived from tick_size."""
        return self._price_decimals

    def update_mid(self, best_bid: float | None, best_ask: float | None) -> None:
        """Update internal mid-price from book data.

        Priority: both sides → ask only → bid only → keep previous.
        """
        if best_bid is not None and best_ask is not None:
            self._mid_price = (best_bid + best_ask) / 2.0
        elif best_ask is not None:
            self._mid_price = best_ask
        elif best_bid is not None:
            self._mid_price = best_bid
        # else: no update — keep previous mid

    def set_mid(self, price: float) -> None:
        """Set mid-price directly (e.g. from bootstrap or trade)."""
        self._mid_price = price

    def compute_prices(self) -> tuple[float, float]:
        """Return (bid_price, ask_price) rounded to the nearest tick.

        Raises RuntimeError if no mid-price is available.
        """
        if self._mid_price is None:
            raise RuntimeError("No mid-price available for quote computation")

        half_gap = self._gap / 2.0
        raw_bid = self._mid_price - half_gap
        raw_ask = self._mid_price + half_gap

        bid = math.floor(raw_bid / self._tick_size + 0.5) * self._tick_size
        ask = math.ceil(raw_ask / self._tick_size - 0.5) * self._tick_size

        # Guarantee minimum spread of 2 ticks even after rounding
        if ask - bid < 2 * self._tick_size:
            ask = bid + 2 * self._tick_size

        return round(bid, self._price_decimals), round(ask, self._price_decimals)

    def has_drifted(self, quoted_at_mid: float) -> bool:
        """Return True if current mid has moved beyond drift threshold."""
        if self._mid_price is None:
            return False
        drift = abs(self._mid_price - quoted_at_mid)
        return drift > self._drift_ticks * self._tick_size

    @staticmethod
    def validate_bootstrap_range(
        initial_min: float | None, initial_max: float | None
    ) -> None:
        """Validate that bootstrap range params are consistent.

        Raises ValueError if only one is provided or min >= max.
        """
        has_min = initial_min is not None
        has_max = initial_max is not None
        if has_min != has_max:
            raise ValueError(
                "Both --initial_min and --initial_max must be provided together"
            )
        if has_min and has_max:
            assert initial_min is not None  # for type narrowing
            assert initial_max is not None
            if initial_min >= initial_max:
                raise ValueError(
                    f"--initial_min ({initial_min}) must be less than "
                    f"--initial_max ({initial_max})"
                )


class InventorySkewPricer:
    """Skew the quote toward flattening inventory instead of quoting
    symmetrically around mid.

    This is the ``"inventory_skew"`` strategy referenced by ``--strategy``
    (design doc §14.1). It wraps a plain ``QuotePricer`` for mid-tracking,
    drift detection, and the tick-rounding / minimum-2-tick-spread rules —
    those do not change — and only overrides how the bid/ask are placed
    relative to mid.

    A long position (``net_position > 0``) shifts the effective mid *down*:
    the ask comes down too, making it more attractive to lift (sell to),
    and the bid comes down, making it less attractive to hit (buy from) —
    both push the bot toward flattening the long. A short position shifts
    the effective mid *up*, symmetrically. The shift scales linearly with
    ``net_position / max_position`` and is clamped at 1.0 in magnitude, so
    beyond ``max_position`` the skew simply stays pinned at its maximum —
    the bot keeps quoting, at the most defensive spread this strategy ever
    offers, rather than stopping.

    Parameters
    ----------
    tick_size, gap, drift_ticks : see ``QuotePricer``.
    max_position : int
        Net position (either direction) at which the skew saturates. Must
        be positive — required because the skew fraction is normalized by
        it; there is no meaningful "unbounded" skew.
    """

    def __init__(
        self,
        tick_size: float,
        gap: float,
        drift_ticks: int,
        *,
        max_position: int | None,
    ) -> None:
        if max_position is None:
            raise ValueError("inventory_skew strategy requires max_position (> 0)")
        if max_position <= 0:
            raise ValueError(f"max_position ({max_position}) must be positive")
        self._inner = QuotePricer(tick_size=tick_size, gap=gap, drift_ticks=drift_ticks)
        self._gap = gap
        self._max_position = max_position
        self._net_position = 0

    @property
    def mid_price(self) -> float | None:
        return self._inner.mid_price

    @property
    def price_decimals(self) -> int:
        return self._inner.price_decimals

    def update_mid(self, best_bid: float | None, best_ask: float | None) -> None:
        self._inner.update_mid(best_bid, best_ask)

    def set_mid(self, price: float) -> None:
        self._inner.set_mid(price)

    def has_drifted(self, quoted_at_mid: float) -> bool:
        return self._inner.has_drifted(quoted_at_mid)

    def update_position(self, net_position: int) -> None:
        """Record the bot's current net position for this symbol.

        Not part of the ``PricingStrategy`` Protocol — ``MMBot`` calls this
        only on strategies that expose it (see the ``hasattr`` guard in
        ``bot.py::_handle_order_fill``), keeping the state machine and ZMQ
        handling agnostic to which strategy is active.
        """
        self._net_position = net_position

    def compute_prices(self) -> tuple[float, float]:
        """Return (bid_price, ask_price) skewed by the tracked position.

        Raises RuntimeError if no mid-price is available (propagated from
        the inner ``QuotePricer``, whose rounding and minimum-2-tick-spread
        guard this delegates to after shifting the mid).
        """
        if self._inner.mid_price is None:
            raise RuntimeError("No mid-price available for quote computation")

        # Fraction in [-1, 1]: how far toward (or past) max_position the
        # bot's inventory sits. Clamped so the skew saturates instead of
        # growing without bound past the cap.
        fraction = self._net_position / self._max_position
        fraction = max(-1.0, min(1.0, fraction))

        half_gap = self._gap / 2.0
        skew = -fraction * half_gap
        skewed_mid = self._inner.mid_price + skew

        # Delegate to QuotePricer's tick-rounding / minimum-spread logic at
        # the skewed mid, then restore the true mid so drift detection
        # keeps comparing against the real market, not the skewed price.
        true_mid = self._inner.mid_price
        self._inner.set_mid(skewed_mid)
        try:
            return self._inner.compute_prices()
        finally:
            self._inner.set_mid(true_mid)


@dataclass(frozen=True)
class PassiveParams:
    """The ``passive`` strategy's control knobs (see ``PassivePricer``).

    Defaults live in ``mm_bot/params.py::TIER2_DEFAULTS``; this class only
    groups the resolved values so ``create_strategy`` can pass them as one.
    """

    retreat_ticks: int
    behind_ticks: int
    min_cover_qty: int
    fade_ticks: int
    fade_sec: float


@dataclass(frozen=True)
class _PassivePlan:
    """One computed quote, in integer ticks, plus why each side sits there."""

    bid: int
    ask: int
    bid_covered: bool
    ask_covered: bool
    bid_faded: bool
    ask_faded: bool


class PassivePricer:
    """Quote as a backstop: yield the top of the book to other traders.

    This is the ``"passive"`` strategy referenced by ``--strategy``. It
    combines two behaviours (docs/user-guide/100-mm-bot.md, "The passive
    strategy"):

    * **Step behind others.** Every side has a *home* price (where the
      ``symmetric`` strategy would quote, ``mid ± gap/2``) and a *band* that
      reaches ``retreat_ticks`` further out. When other traders already show
      at least ``min_cover_qty`` inside that band, the side is *covered* and
      the bot quotes ``behind_ticks`` behind their best price — never
      tighter than home, never outside the band. An uncovered side quotes at
      home, so the bot still makes the market when nobody else does.
    * **Fade after a fill.** When a leg is hit, that side is pushed
      ``fade_ticks`` further out (still inside the band) for ``fade_sec``.

    The mid is taken from *other traders'* book only — ``MMBot`` removes the
    bot's own legs before calling ``update_book`` — so the bot never chases
    its own quote. With no other liquidity the previous mid is kept.

    If the symbol has an MM spread obligation (``max_spread_ticks``), the
    band is narrowed so the widest possible quote still satisfies it.
    """

    def __init__(
        self,
        tick_size: float,
        gap: float,
        drift_ticks: int,
        *,
        params: PassiveParams | None,
        max_spread_ticks: int | None,
    ) -> None:
        if params is None:
            raise ValueError("passive strategy requires its PassiveParams")
        if params.retreat_ticks < 0:
            raise ValueError(f"retreat_ticks ({params.retreat_ticks}) must be >= 0")
        if params.behind_ticks < 1:
            raise ValueError(f"behind_ticks ({params.behind_ticks}) must be >= 1")
        if params.min_cover_qty < 1:
            raise ValueError(f"min_cover_qty ({params.min_cover_qty}) must be >= 1")
        if params.fade_ticks < 0:
            raise ValueError(f"fade_ticks ({params.fade_ticks}) must be >= 0")
        if params.fade_sec < 0:
            raise ValueError(f"fade_sec ({params.fade_sec}) must be >= 0")
        self._inner = QuotePricer(tick_size=tick_size, gap=gap, drift_ticks=drift_ticks)
        self._tick_size = tick_size
        self._drift_ticks = drift_ticks
        self._params = params
        self._max_spread_ticks = max_spread_ticks
        # Other traders' levels, best first, as (price_ticks, qty).
        self._bids: list[tuple[int, int]] = []
        self._asks: list[tuple[int, int]] = []
        self._fade_until: dict[str, float] = {"BID": 0.0, "ASK": 0.0}
        self._last: _PassivePlan | None = None

    @property
    def mid_price(self) -> float | None:
        return self._inner.mid_price

    @property
    def price_decimals(self) -> int:
        return self._inner.price_decimals

    def update_mid(self, best_bid: float | None, best_ask: float | None) -> None:
        self._inner.update_mid(best_bid, best_ask)

    def set_mid(self, price: float) -> None:
        self._inner.set_mid(price)

    def _to_ticks(self, price: float) -> int:
        return round(price / self._tick_size)

    def update_book(
        self, bids: list[tuple[float, int]], asks: list[tuple[float, int]]
    ) -> None:
        """Record other traders' levels (best first) and re-derive the mid.

        Not part of the ``PricingStrategy`` Protocol — ``MMBot`` calls it
        instead of ``update_mid`` on strategies that expose it, after
        removing the bot's own legs from the book.
        """
        self._bids = [(self._to_ticks(p), q) for p, q in bids if q > 0]
        self._asks = [(self._to_ticks(p), q) for p, q in asks if q > 0]
        self._inner.update_mid(
            self._bids[0][0] * self._tick_size if self._bids else None,
            self._asks[0][0] * self._tick_size if self._asks else None,
        )

    def on_fill(self, side: str, now: float) -> None:
        """Start (or restart) the fade on the side that was hit.

        ``side`` is ``"BID"`` or ``"ASK"``; ``now`` is ``time.monotonic()``.
        """
        if self._params.fade_ticks > 0 and self._params.fade_sec > 0:
            self._fade_until[side] = now + self._params.fade_sec

    def _plan(self, now: float) -> _PassivePlan:
        home_bid, home_ask = self._inner.compute_prices()
        hb, ha = self._to_ticks(home_bid), self._to_ticks(home_ask)
        retreat = self._params.retreat_ticks
        if self._max_spread_ticks is not None:
            # Both sides fully retreated must still meet the obligation.
            retreat = min(retreat, max(0, (self._max_spread_ticks - (ha - hb)) // 2))
        floor_bid, ceil_ask = hb - retreat, ha + retreat
        p = self._params

        in_band_bid = sum(q for price, q in self._bids if price >= floor_bid)
        bid_covered = in_band_bid >= p.min_cover_qty
        bid = hb
        if bid_covered:
            bid = min(hb, max(floor_bid, self._bids[0][0] - p.behind_ticks))
        bid_faded = now < self._fade_until["BID"]
        if bid_faded:
            bid = max(floor_bid, bid - p.fade_ticks)

        in_band_ask = sum(q for price, q in self._asks if price <= ceil_ask)
        ask_covered = in_band_ask >= p.min_cover_qty
        ask = ha
        if ask_covered:
            ask = max(ha, min(ceil_ask, self._asks[0][0] + p.behind_ticks))
        ask_faded = now < self._fade_until["ASK"]
        if ask_faded:
            ask = min(ceil_ask, ask + p.fade_ticks)

        return _PassivePlan(bid, ask, bid_covered, ask_covered, bid_faded, ask_faded)

    def compute_prices(self) -> tuple[float, float]:
        """Return (bid_price, ask_price) and remember them as the live quote.

        Raises RuntimeError if no mid-price is available.
        """
        if self._inner.mid_price is None:
            raise RuntimeError("No mid-price available for quote computation")
        plan = self._plan(time.monotonic())
        self._last = plan
        decimals = self._inner.price_decimals
        return (
            round(plan.bid * self._tick_size, decimals),
            round(plan.ask * self._tick_size, decimals),
        )

    def requote_due(self, now: float) -> bool:
        """True when the live quote no longer matches what should be quoted.

        Per side: a change of covered/faded state, a covered side that must
        step further back (any amount — the bot never stays in front of the
        traders it yields to), or any other move of more than
        ``drift_ticks``.
        """
        last = self._last
        if last is None or self._inner.mid_price is None:
            return False
        plan = self._plan(now)
        if (plan.bid_covered, plan.ask_covered, plan.bid_faded, plan.ask_faded) != (
            last.bid_covered,
            last.ask_covered,
            last.bid_faded,
            last.ask_faded,
        ):
            return True
        if plan.bid_covered and plan.bid < last.bid:
            return True
        if plan.ask_covered and plan.ask > last.ask:
            return True
        return (
            abs(plan.bid - last.bid) > self._drift_ticks
            or abs(plan.ask - last.ask) > self._drift_ticks
        )

    def has_drifted(self, quoted_at_mid: float) -> bool:
        """Drift for this strategy is ``requote_due`` — see there.

        Before the first quote this strategy computed itself (an adopted
        quote at startup), fall back to the plain mid-drift rule.
        """
        if self._last is None:
            return self._inner.has_drifted(quoted_at_mid)
        return self.requote_due(time.monotonic())


# Registered strategy names -> constructor function. Each strategy takes
# tick_size/gap/drift_ticks plus whatever else it needs as keyword-only
# extras; a strategy that ignores an extra simply doesn't declare it. A
# Callable, not `type[PricingStrategy]`, because Protocol does not model
# constructor signatures — this keeps each strategy free to take whatever
# __init__ arguments it needs behind a common factory signature.
_StrategyFactory = Callable[..., PricingStrategy]
_STRATEGIES: dict[str, _StrategyFactory] = {
    "symmetric": lambda tick_size, gap, drift_ticks, **_ignored: QuotePricer(
        tick_size=tick_size, gap=gap, drift_ticks=drift_ticks
    ),
    "inventory_skew": lambda tick_size, gap, drift_ticks, **kwargs: InventorySkewPricer(
        tick_size=tick_size,
        gap=gap,
        drift_ticks=drift_ticks,
        max_position=kwargs.get("max_position"),
    ),
    "passive": lambda tick_size, gap, drift_ticks, **kwargs: PassivePricer(
        tick_size=tick_size,
        gap=gap,
        drift_ticks=drift_ticks,
        params=kwargs.get("passive"),
        max_spread_ticks=kwargs.get("max_spread_ticks"),
    ),
}


def create_strategy(
    name: str,
    *,
    tick_size: float,
    gap: float,
    drift_ticks: int,
    max_position: int | None = None,
    passive: PassiveParams | None = None,
    max_spread_ticks: int | None = None,
) -> PricingStrategy:
    """Construct the named pricing strategy.

    ``max_position`` is only meaningful for ``inventory_skew``; ``passive``
    and ``max_spread_ticks`` (the symbol's MM spread obligation) only for
    ``passive``. Strategies that don't use an argument simply ignore it.

    Raises ValueError for an unknown strategy name or invalid parameters
    (the latter propagated from the strategy's own constructor).
    """
    try:
        factory = _STRATEGIES[name]
    except KeyError:
        allowed = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"Unknown strategy '{name}'. Allowed: {allowed}") from None
    return factory(
        tick_size,
        gap,
        drift_ticks,
        max_position=max_position,
        passive=passive,
        max_spread_ticks=max_spread_ticks,
    )


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)
