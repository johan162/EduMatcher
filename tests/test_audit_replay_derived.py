"""Derived facts (task AR-3.2).

Every expectation below is worked out by hand in the test that asserts it, and
the arithmetic is written out in the comment beside it. A test that recomputed
the number the same way the code does would pass on a sign error, a
double-count and an off-by-one alike, which for a tool whose whole claim is
"it only says what the log says" is worse than no test.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.derived import (
    AGGRESSOR_AUCTION,
    ROLE_MAKER,
    ROLE_TAKER,
    derive,
)
from edumatcher.audit.replay.episodes import Episode, EpisodeAssembler
from edumatcher.audit.replay.facts import to_fact
from edumatcher.audit.replay.links import LinkResolver
from edumatcher.audit.replay.pipeline import Step
from edumatcher.audit.replay.state import StateModel

ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"


class Driver:
    """Assembles one episode from a script of lines, one second apart."""

    def __init__(self) -> None:
        self.state = StateModel()
        self.resolver = LinkResolver(self.state)
        self.assembler = EpisodeAssembler(self.state, self.resolver)
        self.retired: list[Episode] = []
        self._ordinal = 0
        self._finished: list[Episode] | None = None

    def feed(
        self, topic: str, payload: dict[str, Any], *, second: int | None = None
    ) -> None:
        at = self._ordinal if second is None else second
        entry = AuditEntry(
            f"2026-09-08T09:31:{at:02d}.000+00:00",
            topic,
            payload,
            {},
            file="audit.log",
            line_no=self._ordinal + 1,
        )
        fact = to_fact(entry, self._ordinal)
        self._ordinal += 1
        anomalies = self.state.apply(fact)
        resolution = self.resolver.feed(fact)
        self.retired.extend(
            self.assembler.feed(
                Step(
                    fact=fact,
                    resolution=resolution,
                    anomalies=anomalies + resolution.anomalies,
                )
            )
        )

    def one(self, kind: str) -> Episode:
        if self._finished is None:
            self._finished = self.retired + list(self.assembler.drain())
        matching = [e for e in self._finished if e.kind == kind]
        assert len(matching) == 1, f"expected one {kind}, got {matching}"
        return matching[0]


def buy_100_at_75_69(driver: Driver) -> None:
    """A resting buy limit: 100 shares, limit 75.69, tick scale 2."""
    driver.feed(
        "order.new",
        {
            "id": ORDER,
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "remaining_qty": 100,
            "gateway_id": "TRADER01",
            "tick_decimals": 2,
            "price_ticks": 7569,
        },
        second=0,
    )


def fill(
    qty: int, price: float, remaining: int, *, flag: str = ROLE_MAKER
) -> dict[str, Any]:
    return {
        "gateway_id": "TRADER01",
        "order_id": ORDER,
        "symbol": "AAPL",
        "side": "BUY",
        "fill_qty": qty,
        "fill_price": price,
        "remaining_qty": remaining,
        "status": "PARTIAL" if remaining else "FILLED",
        "liquidity_flag": flag,
        "trade_ids": [],
    }


# ---------------------------------------------------------------------------
# Fill progress and money
# ---------------------------------------------------------------------------


class TestFillProgressAndMoney:
    def test_two_fills_of_one_order(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed("order.fill.TRADER01", fill(40, 75.60, 60), second=2)
        driver.feed("order.fill.TRADER01", fill(60, 75.50, 0), second=5)
        d = derive(driver.one("order"))

        # 40 x 75.60 = 3024.00; 60 x 75.50 = 4530.00; total 7554.00 over 100
        # shares, so VWAP is 75.54 exactly.
        assert d.notional == pytest.approx(7554.0)
        assert d.vwap == pytest.approx(75.54)
        assert (d.quantity, d.remaining_qty) == (100, 0)
        assert (d.filled_qty, d.fills_total_qty, d.fills) == (100, 100, 2)

    def test_both_tallies_are_kept_so_a_mismatch_is_visible(self) -> None:
        """The engine says 70 left; the fills add to 40. Both numbers survive."""
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed("order.fill.TRADER01", fill(40, 75.60, 70), second=2)
        d = derive(driver.one("order"))
        assert d.filled_qty == 30  # 100 - 70, what the message claims
        assert d.fills_total_qty == 40  # what the fills actually carried

    def test_an_order_with_no_fills_has_no_vwap(self) -> None:
        """Not zero. Zero is a price, and no fill happened at it."""
        driver = Driver()
        buy_100_at_75_69(driver)
        d = derive(driver.one("order"))
        assert (d.vwap, d.notional, d.fills) == (None, None, None)
        assert (d.quantity, d.filled_qty) == (100, 0)

    def test_an_amend_moves_the_quantity_the_tally_is_read_against(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed(
            "order.amended.TRADER01",
            {
                "order_id": ORDER,
                "gateway_id": "TRADER01",
                "qty": 60,
                "remaining_qty": 60,
            },
            second=1,
        )
        d = derive(driver.one("order"))
        assert (d.quantity, d.remaining_qty, d.filled_qty) == (60, 60, 0)


# ---------------------------------------------------------------------------
# Price improvement
# ---------------------------------------------------------------------------


class TestPriceImprovement:
    def test_a_buy_filled_under_its_limit_improved(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed("order.fill.TRADER01", fill(100, 75.60, 0), second=2)
        d = derive(driver.one("order"))
        # Limit 75.69 from price_ticks=7569 at tick_decimals=2; filled at
        # 75.60, so 9 cents a share in the buyer's favour.
        assert d.limit_price == pytest.approx(75.69)
        assert d.price_improvement == pytest.approx(0.09)

    def test_a_sell_filled_over_its_limit_improved(self) -> None:
        """The sign flips with the side, so positive is always the gain."""
        driver = Driver()
        driver.feed(
            "order.new",
            {
                "id": ORDER,
                "symbol": "AAPL",
                "side": "SELL",
                "order_type": "LIMIT",
                "quantity": 50,
                "remaining_qty": 50,
                "tick_decimals": 2,
                "price_ticks": 7500,
            },
            second=0,
        )
        driver.feed(
            "order.fill.TRADER01",
            {
                "order_id": ORDER,
                "side": "SELL",
                "fill_qty": 50,
                "fill_price": 75.25,
                "remaining_qty": 0,
                "status": "FILLED",
            },
            second=1,
        )
        d = derive(driver.one("order"))
        # Limit 75.00, filled at 75.25: 25 cents a share better for a seller.
        assert d.price_improvement == pytest.approx(0.25)

    def test_improvement_is_measured_against_the_average_not_each_fill(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed("order.fill.TRADER01", fill(25, 75.69, 75), second=1)
        driver.feed("order.fill.TRADER01", fill(75, 75.49, 0), second=2)
        d = derive(driver.one("order"))
        # 25 x 75.69 = 1892.25, 75 x 75.49 = 5661.75, total 7554.00 / 100 =
        # 75.54 average, which is 15 cents under the 75.69 limit.
        assert d.vwap == pytest.approx(75.54)
        assert d.price_improvement == pytest.approx(0.15)

    def test_a_market_order_has_no_limit_and_so_no_improvement(self) -> None:
        driver = Driver()
        driver.feed(
            "order.new",
            {
                "id": ORDER,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "MARKET",
                "quantity": 10,
                "remaining_qty": 10,
                "tick_decimals": 2,
            },
            second=0,
        )
        driver.feed("order.fill.TRADER01", fill(10, 75.60, 0), second=1)
        d = derive(driver.one("order"))
        assert (d.limit_price, d.price_improvement) == (None, None)
        assert d.vwap == pytest.approx(75.60)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class TestRoles:
    def test_an_aggressing_order_is_the_taker(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed(
            "order.fill.TRADER01", fill(100, 75.60, 0, flag=ROLE_TAKER), second=1
        )
        assert derive(driver.one("order")).role == ROLE_TAKER

    def test_an_uncross_print_says_nobody_took(self) -> None:
        driver = Driver()
        driver.feed(
            "trade.executed",
            {
                "id": "000042-000001873",
                "symbol": "AAPL",
                "price": 75.55,
                "quantity": 500,
                "aggressor_side": AGGRESSOR_AUCTION,
                "tick_decimals": 2,
            },
        )
        d = derive(driver.one("trade"))
        assert d.crossed_in_uncross is True
        assert d.aggressor_side == AGGRESSOR_AUCTION
        # 500 x 75.55 = 37 775.00
        assert d.notional == pytest.approx(37775.0)

    def test_a_normal_print_names_the_side_that_took(self) -> None:
        driver = Driver()
        driver.feed(
            "trade.executed",
            {
                "id": "000042-000001874",
                "symbol": "AAPL",
                "price": 75.55,
                "quantity": 100,
                "aggressor_side": "BUY",
                "tick_decimals": 2,
            },
        )
        d = derive(driver.one("trade"))
        assert (d.aggressor_side, d.crossed_in_uncross) == ("BUY", False)


# ---------------------------------------------------------------------------
# Timings
# ---------------------------------------------------------------------------


class TestTimings:
    def test_the_three_timings_are_measured_from_the_opening_fact(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)  # second 0
        driver.feed(
            "order.ack.TRADER01",
            {"order_id": ORDER, "gateway_id": "TRADER01", "accepted": True},
            second=1,
        )
        driver.feed("order.fill.TRADER01", fill(40, 75.60, 60), second=4)
        driver.feed("order.fill.TRADER01", fill(60, 75.60, 0), second=9)
        d = derive(driver.one("order"))
        assert (d.time_to_ack, d.time_to_first_fill, d.time_to_completion) == (
            1.0,
            4.0,
            9.0,
        )

    def test_an_unfinished_order_has_no_completion_time(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        driver.feed("order.fill.TRADER01", fill(40, 75.60, 60), second=4)
        d = derive(driver.one("order"))
        assert d.time_to_first_fill == 4.0
        assert d.time_to_completion is None


class TestTheJsonPayload:
    def test_only_what_was_worked_out_is_stored(self) -> None:
        driver = Driver()
        buy_100_at_75_69(driver)
        payload = derive(driver.one("order")).as_dict()
        assert "vwap" not in payload and "role" not in payload
        assert payload["quantity"] == 100

    def test_a_kind_with_no_arithmetic_stores_nothing(self) -> None:
        driver = Driver()
        driver.feed("system.gateway_connect", {"gateway_id": "TRADER01"})
        assert derive(driver.one("gateway")).as_dict() == {}
