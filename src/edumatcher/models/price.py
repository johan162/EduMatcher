"""Shared price conversion helpers for tick-based pricing.

Internal engine logic should use integer ticks. Conversion between human-readable
price values and ticks happens only at boundaries.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_TICK_DECIMALS = 2
_MIN_TICK_DECIMALS = 0
_MAX_TICK_DECIMALS = 8

# Symbol -> tick decimals registry. Populated at startup.
_tick_decimals_by_symbol: dict[str, int] = {}

# Per-symbol scale caches — populated by register_tick_decimals so that
# from_ticks / to_ticks skip the 10**N computation on every call.
_from_scale_cache: dict[str, float] = {}
_to_scale_cache: dict[str, int] = {}


def register_tick_decimals(symbol: str, tick_decimals: int) -> None:
    """Register tick precision for a symbol.

    Raises:
        ValueError: If tick_decimals is outside supported bounds.
    """
    if not (_MIN_TICK_DECIMALS <= tick_decimals <= _MAX_TICK_DECIMALS):
        raise ValueError(
            f"tick_decimals must be between {_MIN_TICK_DECIMALS} and {_MAX_TICK_DECIMALS}"
        )
    sym_upper = symbol.upper()
    _tick_decimals_by_symbol[sym_upper] = tick_decimals
    _from_scale_cache[sym_upper] = float(10**tick_decimals)
    _to_scale_cache[sym_upper] = 10**tick_decimals


def get_tick_decimals(symbol: str) -> int:
    """Return tick decimals for a symbol, defaulting to 2."""
    return _tick_decimals_by_symbol.get(symbol.upper(), DEFAULT_TICK_DECIMALS)


def has_tick_decimals(symbol: str) -> bool:
    """Whether *symbol*'s tick precision has actually been registered.

    ``get_tick_decimals`` answers 2 for an unknown symbol, which is a
    reasonable default for display and a dangerous one for conversion: a
    4-decimal price scaled by 100 is a different price, not a rounded one.
    Callers that convert a client's money need to know the difference.
    """
    return symbol.upper() in _tick_decimals_by_symbol


def clear_tick_registry() -> None:
    """Clear the in-memory tick registry (used by tests)."""
    _tick_decimals_by_symbol.clear()
    _from_scale_cache.clear()
    _to_scale_cache.clear()


def to_ticks(price: float, symbol: str) -> int:
    """Convert a display price to integer ticks with nearest-tick rounding.

    ``price`` is always display money. This function used to return an ``int``
    argument unchanged, on the convention that "an integer is already ticks" -
    which made the *unit* of a price depend on its *runtime type*, and made a
    display price of exactly 150 indistinguishable from 150 ticks.

    Engine-inbound messages now carry ticks and only ticks; converting is the
    submitting gateway's job. Nothing calls this with a tick value any more, so
    the passthrough is gone and the function is total.
    """
    scale = _to_scale_cache.get(symbol)
    if scale is None:
        scale = 10 ** get_tick_decimals(symbol)
        _to_scale_cache[symbol.upper()] = scale
    return int(round(price * scale))


class TickViolation(ValueError):
    """A display price does not sit on the symbol's tick grid.

    Carries the offending price and the symbol so a caller can build its own
    message; every order-entry edge words the rejection differently and none
    of them should have to re-derive the tick size.
    """

    def __init__(self, price: float, symbol: str) -> None:
        self.price = price
        self.symbol = symbol
        self.tick_decimals = get_tick_decimals(symbol)
        self.tick_size = 10**-self.tick_decimals
        super().__init__(
            f"{price} is not a multiple of {symbol}'s tick size "
            f"{self.tick_size:.{self.tick_decimals}f}"
        )


# Half a tick would accept anything; a millionth of a tick rejects nothing a
# client could have meant. The gap between them is where float arithmetic
# lands: a bot computing `100.00 - 3 * 0.01` produces 99.97000000000001, which
# is the same price a human typed as "99.97" and must not be rejected.
_TICK_EPSILON = 1e-6


def to_ticks_exact(price: float, symbol: str) -> int:
    """Convert a display price to ticks, rejecting one that is off the grid.

    ``to_ticks`` rounds to the nearest tick, which is right for an engine-side
    value already known to be well-formed and wrong for a client submission:
    a client asking for 100.005 on a 2-decimal symbol gets a resting order at
    100.00 or 100.01 and is never told. This is the checking variant that the
    order-entry edges use.

    The check cannot be ``price % tick == 0``. Prices arrive as binary floats,
    where a value a client both meant and typed exactly is routinely off by
    an ulp or two, so an exact test rejects almost everything. Compare the
    scaled value against its own rounding instead, within `_TICK_EPSILON`.

    The grid it checks against is whatever ``get_tick_decimals`` reports, so
    for an unregistered symbol that is the two-decimal default. Deciding
    whether a symbol is ready to be priced at all is a separate question and
    a separate check - ``has_tick_decimals`` - because it belongs at the
    connection edge, where there is a client to tell and a retry to suggest,
    not in a pure conversion.

    Raises:
        TickViolation: if *price* is not on the symbol's tick grid.
    """
    scale = _to_scale_cache.get(symbol)
    if scale is None:
        scale = 10 ** get_tick_decimals(symbol)
        _to_scale_cache[symbol.upper()] = scale
    scaled = price * scale
    ticks = round(scaled)
    if abs(scaled - ticks) > _TICK_EPSILON:
        raise TickViolation(price, symbol)
    return int(ticks)


def to_ticks_exact_or_none(price: Optional[float], symbol: str) -> Optional[int]:
    """Optional-tolerant :func:`to_ticks_exact`."""
    if price is None:
        return None
    return to_ticks_exact(price, symbol)


def from_ticks(ticks: int | float, symbol: str) -> float:
    """Convert integer ticks to display price.

    If a float is passed, it is assumed to already be in display units and is
    returned unchanged. This keeps staged migration behavior stable.
    """
    if isinstance(ticks, float):
        return ticks
    scale = _from_scale_cache.get(symbol)
    if scale is None:
        scale = float(10 ** get_tick_decimals(symbol))
        _from_scale_cache[symbol.upper()] = scale
    return float(ticks) / scale


def to_ticks_or_none(price: Optional[float], symbol: str) -> Optional[int]:
    """Convert optional display price to optional ticks."""
    if price is None:
        return None
    return to_ticks(price, symbol)


def from_ticks_or_none(ticks: Optional[int], symbol: str) -> Optional[float]:
    """Convert optional ticks to optional display price."""
    if ticks is None:
        return None
    return from_ticks(ticks, symbol)


def format_price_ticks(ticks: int, symbol: str) -> str:
    """Format ticks as a decimal string using symbol tick precision."""
    decimals = get_tick_decimals(symbol)
    return f"{from_ticks(ticks, symbol):.{decimals}f}"
