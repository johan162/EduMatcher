"""The offering: range, management floor, book-building, allocation, pop.

Design §13–§16. The demand multipliers and the first-day pop are heuristics
(D9): they make causes visible and directions right, not predictions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from edumatcher.valuation.model.bridge import value_after_ipo
from edumatcher.valuation.model.index_rules import (
    IndexVerdict,
    index_rules,
    index_verdict,
)
from edumatcher.valuation.model.valuation import Valuation, offering

#: Multiplier for each interest level, institutional and retail alike (§15.2).
INTEREST = {"very_low": 0.3, "low": 0.6, "medium": 1.0, "high": 1.5, "very_high": 2.2}
#: The book is tabulated, and may be priced, from 80% of the low end of the
#: range to 120% of the high end (the Rule 430A analogue, §15.5).
BAND_LOW, BAND_HIGH = 0.8, 1.2


class Outcome(Enum):
    PRICED = "priced"
    THIN_BOOK = "priced on a thin book"
    POSTPONED = "postponed"


@dataclass(frozen=True)
class BookLine:
    price: float
    institutional: float  # demand in money
    retail: float
    cornerstone: float
    offer_value: float
    coverage: float


@dataclass(frozen=True)
class Listing:
    """The company once the IPO has settled at one price (§9, §13.3, §17)."""

    price: float
    primary_shares: int
    post_shares: float
    market_cap: float
    dilution: float  # new shares / post-money shares
    net_proceeds: float
    value_after_ipo: float  # intrinsic value per share
    free_float_shares: float
    free_float: float
    free_float_cap: float
    locked_shares: float  # pre-IPO shares released at lock-up expiry
    overhang: float  # locked shares / free-float shares
    index: IndexVerdict  # under the relaxations the exchange allows
    index_unrelaxed: IndexVerdict


@dataclass(frozen=True)
class Allocation:
    cornerstone: float
    retail: float
    institutional: float
    retail_fill: float
    institutional_fill: float


@dataclass(frozen=True)
class Pricing:
    fair_value: float
    step: float
    mid: float  # fair value × (1 − IPO discount)
    first_range: tuple[float, float]
    price_range: tuple[float, float]  # after any move by the management floor
    floor_price: float | None
    range_moved: bool
    index_prospects: IndexVerdict  # at the range midpoint, as the book sees it
    book: tuple[BookLine, ...]
    outcome: Outcome
    reason: str
    listing: Listing | None  # None when postponed
    allocation: Allocation | None
    coverage: float | None
    position: str | None  # below, within or above the range
    pop: float | None
    first_day_close: float | None
    money_left: float | None


def price_step(mid: float) -> float:
    """ "Nice" price increments: 14.00-16.00, not 14.37-15.89 (§14.1).

    0.01 below 2, 0.10 below 10, then 0.50 per decade of price (0.50 below
    100, 5 below 1,000, ...), so the book never runs to more than about 90
    lines.
    """
    if mid < 2:
        return 0.01
    if mid < 10:
        return 0.10
    return 0.50 * 10.0 ** math.floor(math.log10(mid / 10))


def _down(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 2)


def _up(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 2)


def listing_at(price: float, v: Mapping[str, Any], valuation: Valuation) -> Listing:
    offer = offering(v)
    primary = offer.primary_shares(price)
    post = offer.shares_pre + primary
    secondary = v["offering.secondary_shares"]
    offer_value = offer.raise_gross + secondary * price
    cornerstone_shares = min(v["offering.cornerstone"], offer_value) / price
    lockup = v["offering.lockup_coverage"]
    free_shares = (
        primary + secondary - cornerstone_shares + (1 - lockup) * offer.shares_pre
    )
    locked = max(0.0, lockup * offer.shares_pre - secondary)
    free_float, free_cap, cap = free_shares / post, free_shares * price, price * post
    rules = index_rules(v)
    dual_class = v["company.dual_class"]
    return Listing(
        price=price,
        primary_shares=primary,
        post_shares=post,
        market_cap=cap,
        dilution=primary / post,
        net_proceeds=offer.net_proceeds(price),
        value_after_ipo=value_after_ipo(price, valuation.equity_pre, offer),
        free_float_shares=free_shares,
        free_float=free_float,
        free_float_cap=free_cap,
        locked_shares=locked,
        overhang=locked / free_shares if free_shares else math.inf,
        index=index_verdict(rules, cap, free_float, free_cap, dual_class),
        index_unrelaxed=index_verdict(
            index_rules(v, relax="none"), cap, free_float, free_cap, dual_class
        ),
    )


def book_line(
    price: float, v: Mapping[str, Any], fair_value: float, index: IndexVerdict
) -> BookLine:
    """Demand from each investor class at one price (§15.1-15.4)."""
    hype = v["investors.hype"]
    lockup = 1 + 0.10 * max(-1.0, min(1.0, (v["offering.lockup_days"] - 180) / 180))
    governance = 0.95 if v["company.dual_class"] else 1.0
    institutional = (
        v["investors.n_institutions"]
        * v["investors.avg_ticket"]
        * INTEREST[v["investors.inst_interest"]]
        * lockup
        * (1 + 0.10 * index.probability)
        * governance
        * (1 + 0.03 * hype)
        * (fair_value / price) ** v["investors.inst_elasticity"]
    )
    retail = (
        v["investors.n_retail"]
        * v["investors.retail_application"]
        * INTEREST[v["investors.retail_interest"]]
        * (1 + 0.25 * hype)
        * (fair_value / price) ** (1.5 / (1 + 0.3 * hype))
    )
    offer_value = v["offering.raise"] + v["offering.secondary_shares"] * price
    cornerstone = min(v["offering.cornerstone"], offer_value)
    coverage = (institutional + retail + cornerstone) / offer_value
    return BookLine(price, institutional, retail, cornerstone, offer_value, coverage)


def allocate(line: BookLine, retail_tranche: float) -> Allocation:
    """Cornerstones first, retail up to its tranche, institutions the rest (§15.6)."""
    left = line.offer_value - line.cornerstone
    retail = min(line.retail, retail_tranche * line.offer_value, left)
    institutional = min(line.institutional, left - retail)
    retail += min(line.retail - retail, left - retail - institutional)
    return Allocation(
        cornerstone=line.cornerstone,
        retail=retail,
        institutional=institutional,
        retail_fill=retail / line.retail if line.retail else 0.0,
        institutional_fill=(
            institutional / line.institutional if line.institutional else 0.0
        ),
    )


def price_ipo(v: Mapping[str, Any], valuation: Valuation) -> Pricing:
    """From fair value to an offer price, or to a postponed deal (§14-§16)."""
    fair_value = valuation.fair_value
    mid = fair_value * (1 - v["offering.ipo_discount"])
    step = price_step(mid)
    # No price is below one step: a range must not start at zero.
    low, high = max(step, _down(mid * 0.95, step)), _up(mid * 1.05, step)
    first_range = (low, high)
    shares_pre, raise_gross = v["offering.shares_pre"], v["offering.raise"]
    minimum = v["management.min_market_cap"]
    floor = None if minimum is None else (minimum - raise_gross) / shares_pre

    def postponed(reason: str, book: tuple[BookLine, ...] = ()) -> Pricing:
        return Pricing(
            fair_value, step, mid, first_range, (low, high), floor, moved,
            prospects, book, Outcome.POSTPONED, reason,
            None, None, None, None, None, None, None,
        )  # fmt: skip

    moved = False
    prospects = (
        listing_at(mid, v, valuation).index
        if mid > 0
        else index_verdict(index_rules(v), 0.0, 0.0, 0.0, False)
    )
    if fair_value <= 0:
        return postponed("the fair value is not positive")
    if floor is not None and low < floor:
        width = high - low
        low = _up(floor, step)
        high = round(low + width, 2)
        moved = True
        discount = 1 - (low + high) / 2 / fair_value
        if discount < v["offering.min_discount"]:
            return postponed(
                f"the management floor moves the range midpoint to "
                f"{(low + high) / 2:.2f}, a {discount:.1%} discount to fair value "
                f"{fair_value:.2f}; the bankers need at least "
                f"{v['offering.min_discount']:.0%}"
            )

    bottom = max(step, _down(low * BAND_LOW, step))
    if floor is not None:
        bottom = max(bottom, _up(floor, step))
    top = _down(high * BAND_HIGH, step)
    count = int(round((top - bottom) / step)) + 1
    book = tuple(
        book_line(round(bottom + i * step, 2), v, fair_value, prospects)
        for i in range(max(count, 0))
    )
    target = v["investors.target_coverage"]
    covered = [line for line in book if line.coverage >= target]
    if covered:
        line, outcome = covered[-1], Outcome.PRICED
        reason = f"the highest price with at least {target:g}× coverage"
    elif book and book[0].coverage >= 1:
        line, outcome = book[0], Outcome.THIN_BOOK
        reason = (
            f"no price reaches {target:g}× coverage; priced where demand is greatest"
        )
    else:
        return postponed("demand falls short of the offer at every price", book)

    price = line.price
    pop = max(
        -0.20,
        min(
            1.00, 0.08 * math.log(max(line.coverage, 0.5)) + 0.02 * v["investors.hype"]
        ),
    )
    listing = listing_at(price, v, valuation)
    sold = listing.primary_shares + v["offering.secondary_shares"]
    position = "below" if price < low else "above" if price > high else "within"
    return Pricing(
        fair_value, step, mid, first_range, (low, high), floor, moved, prospects,
        book, outcome, reason, listing,
        allocate(line, v["offering.retail_tranche"]),
        line.coverage, position, pop, price * (1 + pop), pop * price * sold,
    )  # fmt: skip
