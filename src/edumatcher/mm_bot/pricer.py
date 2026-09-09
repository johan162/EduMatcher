"""Pure pricing logic for the market-maker bot.

QuotePricer is stateless with respect to ZMQ — it only computes
bid/ask prices, tracks mid-price, and detects drift.
"""

from __future__ import annotations

import math
from collections.abc import Callable
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
}


def create_strategy(
    name: str,
    *,
    tick_size: float,
    gap: float,
    drift_ticks: int,
    max_position: int | None = None,
) -> PricingStrategy:
    """Construct the named pricing strategy.

    ``max_position`` is only meaningful for strategies that use it (today:
    ``inventory_skew``); strategies that don't accept it simply ignore it.

    Raises ValueError for an unknown strategy name or invalid parameters
    (the latter propagated from the strategy's own constructor).
    """
    try:
        factory = _STRATEGIES[name]
    except KeyError:
        allowed = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"Unknown strategy '{name}'. Allowed: {allowed}") from None
    return factory(tick_size, gap, drift_ticks, max_position=max_position)


def available_strategies() -> list[str]:
    return sorted(_STRATEGIES)
