"""WP3: range, management floor, book-building, allocation and index (§13–§17).

Golden values are the worked example, docs-design/EduMatcher-valuation.md
§18.11–18.13, asserted to the precision the document prints.
"""

import pytest

from edumatcher.valuation.model.index_rules import (
    Path,
    index_rules,
    index_verdict,
    passive_buying,
)
from edumatcher.valuation.model.offering import (
    Outcome,
    allocate,
    book_line,
    listing_at,
    price_ipo,
    price_step,
)
from edumatcher.valuation.model.valuation import value
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.resolve import resolve
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
M = 1e6


def _values(**changes: object) -> dict:
    return dict(resolve({**AURORA, **changes}, PRESETS).values)


@pytest.fixture(scope="module")
def aurora() -> dict:
    return _values()


def _price(v: dict):
    return price_ipo(v, value(v))


# -- golden: the worked example -------------------------------------------------


def test_range_moved_by_the_management_floor(aurora: dict) -> None:  # §18.11
    pricing = _price(aurora)
    assert pricing.mid == pytest.approx(14.32, abs=0.005)
    assert pricing.first_range == (13.5, 15.5)
    assert pricing.floor_price == pytest.approx(13.75)
    assert pricing.range_moved
    assert pricing.price_range == (14.0, 16.0)


def test_book(aurora: dict) -> None:  # §18.11
    book = _price(aurora).book
    assert [line.price for line in book] == [
        14.0, 14.5, 15.0, 15.5, 16.0, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0,
    ]  # fmt: skip
    assert [line.coverage for line in book] == pytest.approx(
        [3.60, 3.24, 2.93, 2.65, 2.41, 2.20, 2.01, 1.85, 1.70, 1.57, 1.45], abs=0.005
    )
    assert book[1].institutional / M == pytest.approx(1108.2, abs=0.051)
    assert book[1].retail / M == pytest.approx(98.5, abs=0.051)
    assert book[1].offer_value / M == pytest.approx(372.5)


def test_offer_price_and_listing(aurora: dict) -> None:  # §18.11-18.13
    pricing = _price(aurora)
    assert pricing.outcome is Outcome.PRICED
    assert pricing.position == "within"
    listing = pricing.listing
    assert listing is not None and listing.price == 14.5
    assert listing.primary_shares == 20_689_655
    assert listing.market_cap / M == pytest.approx(1460.0, abs=0.05)
    assert listing.dilution == pytest.approx(0.205, abs=0.0005)
    assert listing.value_after_ipo == pytest.approx(15.93, abs=0.005)
    assert listing.free_float == pytest.approx(0.255, abs=0.0005)
    assert listing.free_float_cap / M == pytest.approx(372.5, abs=0.05)
    assert listing.overhang == pytest.approx(2.9, abs=0.05)
    assert pricing.coverage == pytest.approx(3.24, abs=0.005)
    assert pricing.pop == pytest.approx(0.154, abs=0.0005)
    assert pricing.money_left is not None
    assert pricing.money_left / M == pytest.approx(57.4, abs=0.051)


def test_allocation(aurora: dict) -> None:  # §18.11
    allocation = _price(aurora).allocation
    assert allocation is not None
    assert allocation.retail / M == pytest.approx(37.25)
    assert allocation.institutional / M == pytest.approx(335.25)
    assert allocation.retail_fill == pytest.approx(0.378, abs=0.0005)
    assert allocation.institutional_fill == pytest.approx(0.303, abs=0.0005)


def test_index_verdict(aurora: dict) -> None:  # §18.13
    pricing = _price(aurora)
    assert pricing.index_prospects.path is Path.SEASONING
    assert pricing.listing is not None
    assert pricing.listing.index.path is Path.SEASONING
    assert pricing.listing.index.day == 63
    waived = _price({**aurora, "index.relax": "seasoning"}).listing
    assert waived is not None
    assert (waived.index.day, waived.index.probability) == (10, 0.8)
    assert waived.index_unrelaxed.day == 63


def test_a_higher_floor_postpones(aurora: dict) -> None:  # §18.11 what-if
    pricing = _price({**aurora, "management.min_market_cap": 1.6e9})
    assert pricing.outcome is Outcome.POSTPONED
    assert pricing.price_range == (16.5, 18.5)
    assert pricing.listing is None and pricing.book == ()


# -- the pricing rule ---------------------------------------------------------------


def test_thin_book_prices_where_demand_is_greatest(aurora: dict) -> None:
    pricing = _price({**aurora, "investors.target_coverage": 10.0})
    assert pricing.outcome is Outcome.THIN_BOOK
    assert pricing.listing is not None and pricing.listing.price == 14.0


def test_no_demand_postpones(aurora: dict) -> None:
    pricing = _price({**aurora, "investors.n_institutions": 1, "investors.n_retail": 0})
    assert pricing.outcome is Outcome.POSTPONED
    assert pricing.book and all(line.coverage < 1 for line in pricing.book)


def test_no_floor_keeps_the_first_range(aurora: dict) -> None:
    pricing = _price({**aurora, "management.min_market_cap": None})
    assert not pricing.range_moved
    assert pricing.price_range == pricing.first_range == (13.5, 15.5)
    assert pricing.book[0].price == 10.5  # 80% of the low end, rounded down


def test_coverage_falls_with_price(aurora: dict) -> None:
    coverage = [line.coverage for line in _price(aurora).book]
    assert coverage == sorted(coverage, reverse=True)


@pytest.mark.parametrize(
    ("mid", "step"),
    [(25.0, 0.5), (10.0, 0.5), (5.0, 0.1), (1.5, 0.01), (250.0, 5.0), (4000.0, 50.0)],
)
def test_price_step(mid: float, step: float) -> None:
    assert price_step(mid) == step


def test_lockup_and_dual_class_move_institutional_demand(aurora: dict) -> None:
    prospects = _price(aurora).index_prospects
    base = book_line(15.0, aurora, 16.85, prospects).institutional
    longer = book_line(15.0, {**aurora, "offering.lockup_days": 360}, 16.85, prospects)
    dual = book_line(15.0, {**aurora, "company.dual_class": True}, 16.85, prospects)
    assert longer.institutional == pytest.approx(base * 1.10)
    assert dual.institutional == pytest.approx(base * 0.95)


def test_cornerstones_are_filled_first_and_locked(aurora: dict) -> None:
    with_anchor = _values(**{"offering.cornerstone": 50e6})
    allocation = _price(with_anchor).allocation
    assert allocation is not None and allocation.cornerstone == 50e6
    # At the same price, the cornerstone's shares leave the free float.
    anchored = listing_at(14.5, with_anchor, value(with_anchor))
    plain = listing_at(14.5, aurora, value(aurora))
    assert anchored.free_float_shares == pytest.approx(
        plain.free_float_shares - 50e6 / 14.5
    )


def test_retail_takes_what_institutions_leave(aurora: dict) -> None:
    line = book_line(14.5, aurora, 16.85, _price(aurora).index_prospects)
    thin = type(line)(14.5, 100e6, 500e6, 0.0, 372.5e6, 600e6 / 372.5e6)
    allocation = allocate(thin, 0.10)
    assert allocation.institutional == 100e6
    assert allocation.retail == pytest.approx(272.5e6)


# -- the index rulebook -----------------------------------------------------------


def _verdict(v: dict, cap=1.46e9, free_float=0.255, ff_cap=372.5e6, dual=False):
    return index_verdict(index_rules(v), cap, free_float, ff_cap, dual)


def test_fast_entry(aurora: dict) -> None:
    verdict = _verdict(aurora, cap=6e9, ff_cap=1.5e9)
    assert (verdict.path, verdict.day, verdict.probability) == (Path.FAST_ENTRY, 5, 1.0)


def test_size_rules_are_never_relaxed(aurora: dict) -> None:
    verdict = _verdict({**aurora, "index.relax": "all"}, cap=400e6, ff_cap=100e6)
    assert verdict.path is Path.NOT_ELIGIBLE
    assert verdict.failures == ("minimum market cap", "minimum free-float market cap")


@pytest.mark.parametrize(
    ("relax", "free_float", "dual", "path"),
    [
        ("none", 0.12, False, Path.NOT_ELIGIBLE),
        ("float", 0.12, False, Path.WAIVER),
        ("float", 0.08, False, Path.NOT_ELIGIBLE),
        ("none", 0.25, True, Path.NOT_ELIGIBLE),
        ("multi_class", 0.25, True, Path.WAIVER),
        ("all", 0.12, True, Path.WAIVER),
    ],
)
def test_waivers(
    aurora: dict, relax: str, free_float: float, dual: bool, path: Path
) -> None:
    verdict = _verdict(
        {**aurora, "index.relax": relax}, free_float=free_float, dual=dual
    )
    assert verdict.path is path
    assert verdict.probability == {Path.WAIVER: 0.5, Path.NOT_ELIGIBLE: 0.0}[path]


def test_passive_buying() -> None:
    assert passive_buying(100e6, None, 1e9) is None
    assert passive_buying(100e6, 900e6, 1e9) == pytest.approx(100e6)
