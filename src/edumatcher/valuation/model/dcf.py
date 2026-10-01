"""Two-stage DCF with a value-driver terminal value (design §8)."""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.valuation.model.forecast import YearRow


@dataclass(frozen=True)
class DcfRow:
    t: int
    stage: int
    rate: float
    discount_factor: float
    fcff: float
    pv: float


@dataclass(frozen=True)
class Dcf:
    rows: tuple[DcfRow, ...]
    pv_explicit: float
    ebit_terminal: float  # EBIT in year N+1
    nopat_terminal: float
    ronic: float
    reinvestment_rate: float
    fcff_terminal: float
    terminal_value: float  # at year N
    pv_terminal: float
    enterprise_value: float
    tv_share: float


def dcf(
    years: tuple[YearRow, ...],
    r1: float,
    r2: float,
    stage1_years: int,
    terminal_growth: float,
    ronic_spread: float,
    tax_rate: float,
    mid_year: bool = False,
) -> Dcf:
    """Discount years 1..N and a terminal value at N.

    *years* holds N+1 rows; the last only feeds the terminal value. The
    discount factor is a product of each year's own rate (§8.1), so year 6 is
    discounted five years at r1 and one at r2, never six at r2.

    With *mid_year*, each flow, and the terminal value with it, arrives half a
    year earlier than the end of its year (§8.4).
    """
    if r2 <= terminal_growth:
        raise ValueError(
            f"the stage-2 rate ({r2:.2%}) must exceed terminal growth "
            f"({terminal_growth:.2%})"
        )
    horizon = len(years) - 1
    rows: list[DcfRow] = []
    discount = 1.0
    for year in years[:horizon]:
        stage = 1 if year.t <= stage1_years else 2
        rate = r1 if stage == 1 else r2
        discount /= 1 + rate
        factor = discount * ((1 + rate) ** 0.5 if mid_year else 1.0)
        rows.append(DcfRow(year.t, stage, rate, factor, year.fcff, year.fcff * factor))

    # §8.3: in perpetuity the company is fully taxed and reinvests exactly what
    # growth at g requires, g / RONIC of its NOPAT.
    ebit_terminal = years[horizon].ebit
    nopat = ebit_terminal * (1 - tax_rate)
    ronic = r2 + ronic_spread
    reinvestment_rate = terminal_growth / ronic
    fcff_terminal = nopat * (1 - reinvestment_rate)
    terminal_value = fcff_terminal / (r2 - terminal_growth)
    terminal_factor = discount * ((1 + r2) ** 0.5 if mid_year else 1.0)
    pv_terminal = terminal_value * terminal_factor

    pv_explicit = sum(row.pv for row in rows)
    enterprise_value = pv_explicit + pv_terminal
    return Dcf(
        rows=tuple(rows),
        pv_explicit=pv_explicit,
        ebit_terminal=ebit_terminal,
        nopat_terminal=nopat,
        ronic=ronic,
        reinvestment_rate=reinvestment_rate,
        fcff_terminal=fcff_terminal,
        terminal_value=terminal_value,
        pv_terminal=pv_terminal,
        enterprise_value=enterprise_value,
        tv_share=pv_terminal / enterprise_value,
    )
