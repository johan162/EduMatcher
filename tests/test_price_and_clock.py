from __future__ import annotations

from edumatcher.models.clock import now_ns, reset_clock_for_tests
from edumatcher.models.price import (
    clear_tick_registry,
    format_price_ticks,
    from_ticks,
    from_ticks_or_none,
    get_tick_decimals,
    register_tick_decimals,
    to_ticks,
    to_ticks_or_none,
)


def setup_function() -> None:
    clear_tick_registry()
    reset_clock_for_tests()


def test_tick_registry_defaults_to_two_decimals() -> None:
    assert get_tick_decimals("AAPL") == 2


def test_tick_conversion_roundtrip_default_precision() -> None:
    ticks = to_ticks(150.30, "AAPL")
    assert ticks == 15030
    assert from_ticks(ticks, "AAPL") == 150.30


def test_tick_conversion_roundtrip_custom_precision() -> None:
    register_tick_decimals("EURUSD", 4)
    ticks = to_ticks(1.2345, "EURUSD")
    assert ticks == 12345
    assert from_ticks(ticks, "EURUSD") == 1.2345


def test_optional_tick_helpers() -> None:
    assert to_ticks_or_none(None, "AAPL") is None
    assert from_ticks_or_none(None, "AAPL") is None
    assert to_ticks_or_none(100.25, "AAPL") == 10025
    assert from_ticks_or_none(10025, "AAPL") == 100.25


def test_format_price_ticks_uses_symbol_precision() -> None:
    register_tick_decimals("BTCUSD", 3)
    assert format_price_ticks(123456, "BTCUSD") == "123.456"


def test_now_ns_is_strictly_increasing() -> None:
    first = now_ns()
    second = now_ns()
    third = now_ns()
    assert first < second < third


def test_register_tick_decimals_validates_bounds() -> None:
    try:
        register_tick_decimals("X", -1)
        assert False, "Expected ValueError"
    except ValueError:
        pass

    try:
        register_tick_decimals("X", 9)
        assert False, "Expected ValueError"
    except ValueError:
        pass
