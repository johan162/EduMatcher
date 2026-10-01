"""F4: the live preview explained, with the numbers it shows (design §19.2).

Each entry is (heading, text): the preview line with its current value, and
what it means and how it was reached, in the words of the user guide.
"""

from __future__ import annotations

from edumatcher.valuation.model.offering import Outcome
from edumatcher.valuation.tui.interview import Evaluation

_VERDICT = {
    Outcome.PRICED: (
        "PROCEED",
        "The book is covered at least {target:g} times at some price in the "
        "band, so the IPO can go ahead at the offer price above.",
    ),
    Outcome.THIN_BOOK: (
        "THIN BOOK",
        "No price in the band reaches the {target:g}× target, but the book is "
        "covered at least once at its bottom, so the deal prices there. With "
        "few unfilled orders the stock may trade below its offer price.",
    ),
    Outcome.POSTPONED: (
        "POSTPONE",
        "The IPO cannot be sold: {reason}.",
    ),
}


def explain_preview(ev: Evaluation) -> list[tuple[str, str]]:
    """The preview's lines explained, or why there is no preview."""
    if ev.preview is None:
        count = len(ev.problems)
        return [
            (
                f"{count} problem{'s' * (count != 1)} to fix",
                "The preview needs every answer to be valid. A field with a "
                "problem is red, and its description says what is wrong; "
                "Ctrl-D puts it back to its automatic value. A problem with the"
                " company as a whole, such as a stage-2 rate too close to "
                "terminal growth, is listed under the count.",
            )
        ]
    v = ev.preview.resolved.values
    val, pr = ev.preview.valuation, ev.preview.pricing
    weight = v["investors.dcf_weight"]
    ntm = val.years[0].revenue / 1e6
    low, high = pr.price_range
    target = v["investors.target_coverage"]
    above = v["offering.max_above_range"]
    out = [
        (
            f"Fair value  {val.fair_value:.2f}",
            "The model's estimate of what one share is worth once the IPO has "
            "settled, in the company's currency. It blends the two methods "
            f"below: {weight:.0%} × DCF {val.dcf_price:.2f} + {1 - weight:.0%}"
            f" × comparables {val.comps_price:.2f} (DCF weight, page 9).",
        ),
        (
            f"DCF  {val.dcf_price:.2f}",
            "Discounted cash flow: the free cash flows of the forecast and the "
            "terminal value after it, each turned into today's money at the "
            f"stage-1 rate {val.stage1.rate:.2%} (years 1-5) and the stage-2 "
            f"rate {val.stage2.rate:.2%}, plus cash, minus debt, per share. "
            f"{val.dcf.tv_share:.0%} of it lies beyond the forecast horizon.",
        ),
        (
            f"Comps  {val.comps_price:.2f}",
            "Comparables: what the stock market pays for similar companies. "
            f"Next year's revenue of {ntm:,.1f} m × the comparable multiple "
            f"{v['investors.comps_multiple']:g}× gives the enterprise value; "
            "plus cash, minus debt, per share. It moves with market mood; the "
            "DCF does not.",
        ),
        (
            f"Range  {low:.2f}–{high:.2f}",
            "The price range published before investors order: fair value less"
            f" the IPO discount of {v['offering.ipo_discount']:.0%} (page 8), "
            "±5%, rounded to 'nice' prices. The discount rewards investors for "
            "buying an untested stock."
            + (
                f" Management's minimum market cap moved it up from "
                f"{pr.first_range[0]:.2f}–{pr.first_range[1]:.2f} (page 11)."
                if pr.range_moved
                else ""
            ),
        ),
    ]
    if pr.listing is not None and pr.coverage is not None:
        limit = (
            "the top of the range, the maximum price"
            if above == 0
            else f"{above:.0%} above the range"
        )
        out.append(
            (
                f"Offer {pr.listing.price:.2f} at {pr.coverage:.1f}×",
                "The price IPO investors pay, chosen from the book of orders: "
                f"the highest price that is still covered {target:g} times "
                f"(target coverage, page 9), no higher than {limit}. "
                f"{pr.coverage:.1f}× means orders for {pr.coverage:.1f} times "
                "the shares on offer; the unfilled buyers support the price on "
                "the first day.",
            )
        )
    word, text = _VERDICT[pr.outcome]
    out.append((word, text.format(target=target, reason=pr.reason)))
    notes = len(ev.preview.findings)
    if notes:
        out.append(
            (
                f"⚠ {notes} note{'s' * (notes != 1)}",
                "Warnings from the model's plausibility checks, such as a "
                "margin outside the sector's range. F2 lists them under the "
                "values; the report explains each one.",
            )
        )
    return out
