"""Index eligibility under the tool's fictive rulebook (design §17).

pm-index itself has no eligibility rules: constituents are configured or
added by an operator. This rulebook is a teaching device, and the question it
answers is how soon index funds will have to buy the stock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

#: Free float the exchange accepts when it relaxes the float rule.
RELAXED_FREE_FLOAT = 0.10
#: Trading day of inclusion when seasoning is waived: the next review.
WAIVED_SEASONING_DAY = 10


class Path(Enum):
    FAST_ENTRY = "fast entry"
    SEASONING = "after seasoning"
    WAIVER = "only with a waiver"
    NOT_ELIGIBLE = "not eligible"


#: P(inclusion within six months) for each path (§17.3).
_PROBABILITY = {
    Path.FAST_ENTRY: 1.0,
    Path.SEASONING: 0.8,
    Path.WAIVER: 0.5,
    Path.NOT_ELIGIBLE: 0.0,
}


@dataclass(frozen=True)
class IndexRules:
    min_cap: float
    min_free_float: float
    min_ff_cap: float
    seasoning_days: int
    fast_entry_cap: float
    fast_entry_days: int
    allow_multi_class: bool
    relax: str  # none, seasoning, float, multi_class or all


def index_rules(v: Mapping[str, Any], relax: str | None = None) -> IndexRules:
    """The rulebook from resolved values; *relax* overrides the exchange's choice."""
    return IndexRules(
        min_cap=v["index.min_cap"],
        min_free_float=v["index.min_free_float"],
        min_ff_cap=v["index.min_ff_cap"],
        seasoning_days=int(v["index.seasoning_days"]),
        fast_entry_cap=v["index.fast_entry_cap"],
        fast_entry_days=int(v["index.fast_entry_days"]),
        allow_multi_class=v["index.allow_multi_class"],
        relax=v["index.relax"] if relax is None else relax,
    )


@dataclass(frozen=True)
class IndexVerdict:
    path: Path
    day: int | None  # trading day of inclusion; None when not eligible
    waivers: tuple[str, ...]  # the relaxations the verdict relies on
    failures: tuple[str, ...]  # the rules that fail, when not eligible
    probability: float  # P(inclusion within six months)


def index_verdict(
    rules: IndexRules,
    market_cap: float,
    free_float: float,
    free_float_cap: float,
    dual_class: bool,
) -> IndexVerdict:
    """Apply the rulebook to a listing at one price.

    Size rules are never relaxed. The float and multi-class rules can be,
    and a company that passes only thanks to one of them depends on a
    waiver. Waiving seasoning never makes a company eligible; it only brings
    the inclusion day forward.
    """

    def relaxed(rule: str) -> bool:
        return rules.relax in (rule, "all")

    failures: list[str] = []
    waivers: list[str] = []
    if market_cap < rules.min_cap:
        failures.append("minimum market cap")
    if free_float_cap < rules.min_ff_cap:
        failures.append("minimum free-float market cap")
    if free_float < rules.min_free_float:
        if relaxed("float") and free_float >= RELAXED_FREE_FLOAT:
            waivers.append("float")
        else:
            failures.append("minimum free float")
    if dual_class and not rules.allow_multi_class:
        if relaxed("multi_class"):
            waivers.append("multi_class")
        else:
            failures.append("single share class")
    if failures:
        return IndexVerdict(Path.NOT_ELIGIBLE, None, (), tuple(failures), 0.0)

    if market_cap >= rules.fast_entry_cap:
        path, day = Path.FAST_ENTRY, rules.fast_entry_days
    else:
        path, day = Path.SEASONING, rules.seasoning_days
        if relaxed("seasoning"):
            waivers.append("seasoning")
            day = min(day, WAIVED_SEASONING_DAY)
    if {"float", "multi_class"} & set(waivers):
        path = Path.WAIVER
    return IndexVerdict(path, day, tuple(waivers), (), _PROBABILITY[path])


def passive_buying(
    free_float_cap: float, index_ff_cap: float | None, passive_aum: float | None
) -> float | None:
    """Forced buying by index funds at inclusion: weight × passive assets."""
    if index_ff_cap is None or passive_aum is None:
        return None
    weight = free_float_cap / (index_ff_cap + free_float_cap)
    return weight * passive_aum
