"""
engine/collar.py — Price collar band validation.

Collar bands are a fat-finger and manipulation protection mechanism.
Two independent bands must both pass before a limit order is accepted:

Static band
~~~~~~~~~~~
  ±static_band_pct from the *reference price* (prior close or config seed).

  Catches absolute fat-finger errors: "sell 1,000 shares at $1.00" when
  the stock trades near $150 is caught regardless of what happened today.

Dynamic band
~~~~~~~~~~~~
  ±dynamic_band_pct from the *last trade price* (most recent fill).

  Prevents incremental price walking: submitting 50 orders each moving
  price 1.9% to avoid any single 2% collar trigger. Each order is checked
  against wherever the last trade occurred, so the first step outside the
  dynamic band is caught.

Both bands are checked on every LIMIT and ICEBERG order. MARKET/FOK/IOC
orders bypass collar checks — they are not price-limited and will execute
against whatever is available.

Integer arithmetic
~~~~~~~~~~~~~~~~~~
All prices are integer ticks. Band boundaries are computed with ``int()``
truncation toward zero:

  static_upper = int(ref * (1 + static_band_pct))   → slightly tighter than exact
  static_lower = int(ref * (1 - static_band_pct))   → slightly tighter than exact

Truncating *toward zero* makes upper bounds slightly lower and lower bounds
slightly higher than the mathematically exact values — the allowed range is
slightly tighter than specified. For a price-protection mechanism, erring
toward restrictiveness is the correct behaviour. No ``Decimal`` or rounding
is needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CollarConfig:
    """Per-symbol collar configuration.

    Attributes
    ----------
    symbol          : The trading symbol this config applies to.
    reference_price : Reference price in *int ticks* — resolved from the
                      symbol's last-buy/last-sell price (buy side preferred),
                      preferring a persisted ``book_stats.json`` value over the
                      ``last_buy_price`` / ``last_sell_price`` seed in
                      ``engine_config.yaml`` when both are present. Populated
                      by ``Engine._load_config()`` after tick-decimals are
                      registered.
    static_band_pct : Fraction of ``reference_price`` that defines the static
                      half-band (default: 0.20 = ±20%).
    dynamic_band_pct: Fraction of ``last_trade_price`` that defines the dynamic
                      half-band (default: 0.02 = ±2%).
    """

    symbol: str
    reference_price: int = 0  # ticks — populated in _load_config()
    static_band_pct: float = 0.20
    dynamic_band_pct: float = 0.02


@dataclass
class CollarResult:
    """Result of a collar check.

    Attributes
    ----------
    rejected : ``True`` if the order price failed a collar band.
    reason   : Human-readable reason string (empty when ``rejected=False``).
    """

    rejected: bool
    reason: str = field(default="")


def validate_collar(
    price: int,
    collar: CollarConfig,
    last_trade_price: Optional[int],
) -> CollarResult:
    """
    Check *price* (int ticks) against both collar bands.

    Parameters
    ----------
    price            : The order price in int ticks.
    collar           : Configuration for this symbol.
    last_trade_price : The most recent fill price in int ticks, or ``None``
                       if no trades have occurred today.  When ``None``,
                       only the static band is checked.

    Returns
    -------
    ``CollarResult(rejected=False)``  — price passed all applicable bands.
    ``CollarResult(rejected=True, reason=…)`` — price failed a band; the
    *reason* string names the band and includes the boundary values so
    operators can diagnose fat-finger errors immediately.
    """
    ref = collar.reference_price

    # Static band check (always applied)
    static_upper = int(ref * (1 + collar.static_band_pct))
    static_lower = int(ref * (1 - collar.static_band_pct))
    if not (static_lower <= price <= static_upper):
        return CollarResult(
            rejected=True,
            reason=(
                f"STATIC_COLLAR_BREACH: price {price} ticks is outside "
                f"[{static_lower}, {static_upper}] ticks "
                f"(\u00b1{collar.static_band_pct * 100:.0f}% from reference {ref})"
            ),
        )

    # Dynamic band check — only when at least one trade has occurred
    if last_trade_price is not None:
        dyn_upper = int(last_trade_price * (1 + collar.dynamic_band_pct))
        dyn_lower = int(last_trade_price * (1 - collar.dynamic_band_pct))
        if not (dyn_lower <= price <= dyn_upper):
            return CollarResult(
                rejected=True,
                reason=(
                    f"DYNAMIC_COLLAR_BREACH: price {price} ticks is outside "
                    f"[{dyn_lower}, {dyn_upper}] ticks "
                    f"(\u00b1{collar.dynamic_band_pct * 100:.0f}% from last trade "
                    f"{last_trade_price})"
                ),
            )

    return CollarResult(rejected=False)
