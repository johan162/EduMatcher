"""Pure pricing logic for the market-maker bot.

QuotePricer is stateless with respect to ZMQ — it only computes
bid/ask prices, tracks mid-price, and detects drift.
"""

from __future__ import annotations

import math


class QuotePricer:
    """Compute symmetric two-sided quote prices around a mid-price.

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
