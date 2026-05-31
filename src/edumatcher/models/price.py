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


def clear_tick_registry() -> None:
    """Clear the in-memory tick registry (used by tests)."""
    _tick_decimals_by_symbol.clear()
    _from_scale_cache.clear()
    _to_scale_cache.clear()


def to_ticks(price: float | int, symbol: str) -> int:
    """Convert a display price to integer ticks with nearest-tick rounding.

    If an integer is passed, it is assumed to already be in ticks.
    """
    if isinstance(price, int):
        return price
    scale = _to_scale_cache.get(symbol)
    if scale is None:
        scale = 10 ** get_tick_decimals(symbol)
        _to_scale_cache[symbol.upper()] = scale
    return int(round(price * scale))


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
