"""From enterprise value to value per share, including the IPO (design §9)."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Offering:
    """The primary offering's economics; the raise R is gross."""

    raise_gross: float
    gross_spread: float
    other_expenses: float
    shares_pre: float  # fully diluted, before the IPO

    def primary_shares(self, price: float) -> int:
        """New shares sold at *price*, rounded down to whole shares."""
        return math.floor(self.raise_gross / price)

    def net_proceeds(self, price: float) -> float:
        raised = self.primary_shares(price) * price
        return raised * (1 - self.gross_spread) - self.other_expenses


def fair_price(equity_pre: float, offering: Offering) -> float:
    """The price at which IPO buyers pay exactly what their shares are worth.

    Solving P = (E + R − fR − X) / (S + R/P) for P gives
    P = (E − fR − X) / S: the raise cancels out, its costs do not (§9.2).
    """
    costs = offering.gross_spread * offering.raise_gross + offering.other_expenses
    return (equity_pre - costs) / offering.shares_pre


def value_after_ipo(price: float, equity_pre: float, offering: Offering) -> float:
    """Intrinsic value per share once the IPO at *price* has settled."""
    shares = offering.shares_pre + offering.primary_shares(price)
    return (equity_pre + offering.net_proceeds(price)) / shares


@dataclass(frozen=True)
class Dilution:
    """The S-1 dilution section (§9.4)."""

    ntbv_pre: float
    ntbv_pre_per_share: float
    ntbv_post: float
    ntbv_post_per_share: float
    increase_per_share: float  # to existing holders
    dilution_per_share: float  # to new investors
    dilution_pct: float


def dilution(
    price: float,
    offering: Offering,
    cash: float,
    ppe_0: float,
    nwc_0: float,
    debt: float,
) -> Dilution:
    ntbv_pre = cash + ppe_0 + nwc_0 - debt
    ntbv_post = ntbv_pre + offering.net_proceeds(price)
    pre_per_share = ntbv_pre / offering.shares_pre
    post_per_share = ntbv_post / (offering.shares_pre + offering.primary_shares(price))
    return Dilution(
        ntbv_pre=ntbv_pre,
        ntbv_pre_per_share=pre_per_share,
        ntbv_post=ntbv_post,
        ntbv_post_per_share=post_per_share,
        increase_per_share=post_per_share - pre_per_share,
        dilution_per_share=price - post_per_share,
        dilution_pct=(price - post_per_share) / price,
    )
