"""WP-MOD02: every price on a 0–8 decimal grid is accepted, and a
non-finite or overflowing price is a tick violation (Models review 2026-11,
C1 and C2).

The exact check used an absolute tolerance of 1e-6 ticks, below the float
rounding of ``price * 10**d`` once that passes about 4.5e9: at 8 decimals
11-16 % of correctly typed prices from 100 up were refused.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side
from edumatcher.models.price import (
    TickViolation,
    clear_tick_registry,
    format_price_ticks,
    register_tick_decimals,
    to_ticks_exact_at,
)
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from tests.engine_harness import connect, make_engine, msgs, order_payload


def _sample(decimals: int) -> list[int]:
    """Seeded tick counts, 300 per decade from 1 to 10**7 display units."""
    rng = random.Random(decimals)
    out: list[int] = []
    for lo in (1, 10, 100, 1_000, 10_000, 100_000, 1_000_000):
        out += [
            rng.randint(lo * 10**decimals, 10 * lo * 10**decimals) for _ in range(300)
        ]
    return out


def _typed(ticks: int, decimals: int) -> float:
    """The float a client sends after typing the price to its decimals."""
    return float(f"{ticks / 10**decimals:.{decimals}f}")


@pytest.mark.parametrize("decimals", range(9))
def test_every_typed_on_grid_price_converts_exactly(decimals: int) -> None:
    wrong = [
        t for t in _sample(decimals) if _converts(_typed(t, decimals), decimals) != t
    ]
    assert wrong == [], f"{len(wrong)} refused or misconverted, e.g. {wrong[:3]}"


def _converts(price: float, decimals: int) -> int | None:
    try:
        return to_ticks_exact_at(price, decimals, "X")
    except TickViolation:
        return None


@pytest.mark.parametrize("decimals", range(9))
def test_half_a_tick_off_the_grid_is_refused(decimals: int) -> None:
    accepted = []
    for t in _sample(decimals):
        off = float(f"{(t + 0.5) / 10**decimals:.{decimals + 1}f}")
        if _converts(off, decimals) is not None:
            accepted.append(off)
    assert accepted == []


def test_float_arithmetic_noise_is_still_accepted() -> None:
    assert to_ticks_exact_at(100.00 - 3 * 0.01, 2, "X") == 9997


def test_an_off_grid_price_is_still_refused() -> None:
    with pytest.raises(TickViolation):
        to_ticks_exact_at(100.005, 2, "X")


def test_the_review_example_converts() -> None:
    assert to_ticks_exact_at(1234.56789012, 8, "X") == 123456789012


@pytest.mark.parametrize("price", [float("inf"), float("-inf"), float("nan"), 1e308])
def test_a_non_finite_or_overflowing_price_is_a_tick_violation(price: float) -> None:
    with pytest.raises(TickViolation):
        to_ticks_exact_at(price, 2, "X")


def test_an_amend_to_an_overflowing_price_is_a_client_reject(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path)
    connect(engine)
    order = order_payload(Side.BUY, OrderType.LIMIT, 10, "GW02", price=99.00)
    engine._handle_new_order(order)
    engine._handle_amend(
        {"order_id": order["id"], "gateway_id": "GW02", "price": 1e308}
    )
    ack = msgs(pub, "order.ack.GW02")[-1]
    assert (ack["accepted"], ack["request"], ack["reject_code"]) == (
        False,
        "AMEND",
        "TICK_VIOLATION",
    )


# --- WP-MOD03 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "ticks, decimals, text",
    [
        (123456789012345678, 8, "1234567890.12345678"),
        (9_999_999_999_999_999, 8, "99999999.99999999"),
        (-150, 2, "-1.50"),
        (-5, 2, "-0.05"),
        (0, 2, "0.00"),
        (150, 0, "150"),
        (12345, 4, "1.2345"),
    ],
)
def test_format_price_ticks_is_exact(ticks: int, decimals: int, text: str) -> None:
    clear_tick_registry()
    register_tick_decimals("X", decimals)
    try:
        assert format_price_ticks(ticks, "X") == text
    finally:
        clear_tick_registry()


def test_an_engine_trade_carries_its_symbols_scale() -> None:
    clear_tick_registry()
    register_tick_decimals("EURUSD", 4)
    reset_trade_ids_for_tests()
    set_run_seq(1)
    try:
        book = OrderBook("EURUSD")
        trades = []
        for side, gw in ((Side.SELL, "GW01"), (Side.BUY, "GW02")):
            order = Order.create(
                "EURUSD", side, OrderType.LIMIT, 10, gw, price_ticks=12345
            )
            trades += book.process(order)[0]
        (trade,) = trades
        assert trade.tick_decimals == 4
        assert trade.to_wire()["tick_decimals"] == 4
    finally:
        clear_tick_registry()
        reset_trade_ids_for_tests()
