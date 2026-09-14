"""Arithmetic over what an episode recorded (design section 7.4).

Section 7.3 groups the facts; this works out what they add up to. Kept apart
because the two answer different questions, and because the rule governing
this one is a single sentence: **nothing beyond arithmetic over recorded
fields**. The tool does not model the book to guess what *should* have
matched, and it does not fill a gap with a plausible number.

Two consequences of that rule are visible below.

*Both quantity tallies are kept.* ``filled_qty`` is what the messages say
(``quantity - remaining_qty``) and ``fills_total_qty`` is the sum of the
``fill_qty`` values this episode actually carried. They are the same number on
a healthy log, and section 12.2's ``QTY_MISMATCH`` is the case where they are
not -- which the state model already reports. Keeping both here means a reader
who sees that finding can see the two numbers that disagree.

*Notional is a share notional.* Section 7.4 warns against assuming a contract
multiplier of 1. There is none to assume: every quantity in the spec is
declared ``unit: shares``, and no message, no reference-data reply and no
symbol config carries a multiplier or an instrument type (checked against the
generated registry). ``notional`` is therefore price times shares, which is
what the field means here, rather than a guess at what it would mean in a
system that traded contracts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.episodes import (
    KIND_ORDER,
    KIND_TRADE,
    Episode,
)
from edumatcher.audit.replay.facts import Fact

#: ``trade.executed.aggressor_side`` when both sides rested. Not a side.
AGGRESSOR_AUCTION = "AUCTION"

#: ``order.fill.liquidity_flag``. MAKER and TAKER are the only two values the
#: spec declares; an uncross has no aggressor, so the engine flags *both*
#: sides MAKER -- see :attr:`Derived.role`.
ROLE_MAKER = "MAKER"
ROLE_TAKER = "TAKER"

_BUY = "BUY"


@dataclass(frozen=True, slots=True)
class Derived:
    """What an episode's facts work out to. Every field is optional.

    A field is None when the episode did not carry what it needs -- never a
    zero standing in for an unknown, and never a default. ``--explain`` shows
    the working, so a number that is here has to be one the log supports.
    """

    #: Fill progress (section 7.4). Two tallies, deliberately.
    quantity: int | None = None
    remaining_qty: int | None = None
    filled_qty: int | None = None
    fills_total_qty: int | None = None
    fills: int | None = None

    #: Money. ``vwap`` over this episode's fills; ``notional`` their total.
    vwap: float | None = None
    notional: float | None = None

    #: Price improvement: how much better than the limit the fills came in,
    #: per share, signed so that positive is always in the trader's favour.
    limit_price: float | None = None
    price_improvement: float | None = None

    #: MAKER or TAKER, off ``liquidity_flag``. MAKER covers two different
    #: things -- an order that rested and was hit, and one that crossed in an
    #: uncross -- because an auction print has no aggressor and the engine
    #: flags both of its sides MAKER. The trade episode's
    #: :attr:`crossed_in_uncross` is what separates them.
    role: str | None = None

    #: On a ``trade`` episode only.
    aggressor_side: str | None = None
    crossed_in_uncross: bool | None = None

    #: Seconds on the receipt clock -- the only clock on every line, and the
    #: one the reader can grep for. Not the client's, which section 5.3.2
    #: keeps separate for good reason.
    time_to_ack: float | None = None
    time_to_first_fill: float | None = None
    time_to_completion: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """The ``episodes.facts_json`` payload: only what was worked out."""
        return {k: v for k, v in asdict(self).items() if v is not None}


def derive(episode: Episode) -> Derived:
    """Work out what *episode* adds up to.

    Only ``order`` and ``trade`` have arithmetic worth doing. The other kinds
    get an empty :class:`Derived` rather than a made-up one; their timings are
    the open and close columns the index already stores.
    """
    if episode.kind == KIND_ORDER:
        return _order(episode)
    if episode.kind == KIND_TRADE:
        return _trade(episode)
    return Derived()


def _order(episode: Episode) -> Derived:
    facts = [event.fact for event in episode.events]
    fills = [f for f in facts if f.kind == kinds.ORDER_FILL]

    # One field, two spellings: `order.new` calls the order's size `quantity`
    # and every engine event restates it as `qty`. Scanned together and in
    # event order, because an amend restates the size and it is the *latest*
    # statement the fill tally has to be reconciled against -- taking all the
    # `quantity` values first would make an amend invisible here.
    quantity = _last(facts, "quantity", "qty")
    remaining = _last(facts, "remaining_qty")
    total_qty = sum(q for f in fills if (q := _int(f.payload, "fill_qty")) is not None)
    notional = sum(
        q * p
        for f in fills
        if (q := _int(f.payload, "fill_qty")) is not None
        and (p := _price(f, "fill_price")) is not None
    )

    limit = _first_price(facts)
    side = _first_str(facts, "side")
    return Derived(
        quantity=quantity,
        remaining_qty=remaining,
        filled_qty=(
            quantity - remaining
            if quantity is not None and remaining is not None
            else None
        ),
        fills_total_qty=total_qty if fills else None,
        fills=len(fills) if fills else None,
        vwap=notional / total_qty if total_qty else None,
        notional=notional if fills else None,
        limit_price=limit,
        price_improvement=_improvement(limit, side, notional, total_qty),
        role=_first_str(fills, "liquidity_flag"),
        time_to_ack=_elapsed(episode, _find(facts, kinds.ORDER_ACK)),
        time_to_first_fill=_elapsed(episode, fills[0] if fills else None),
        time_to_completion=(
            (episode.closed_ts - episode.opened_ts).total_seconds()
            if episode.closed_ts is not None
            else None
        ),
    )


def _trade(episode: Episode) -> Derived:
    fact = episode.opened
    quantity = _int(fact.payload, "quantity")
    price = _price(fact, "price")
    aggressor = _str(fact.payload, "aggressor_side")
    return Derived(
        quantity=quantity,
        notional=(
            quantity * price if quantity is not None and price is not None else None
        ),
        aggressor_side=aggressor,
        crossed_in_uncross=(
            aggressor == AGGRESSOR_AUCTION if aggressor is not None else None
        ),
    )


def _improvement(
    limit: float | None, side: str | None, notional: float, total_qty: int
) -> float | None:
    """How much better than the limit the fills came in, per share.

    Signed so positive is always the trader's gain: a buy filled below its
    limit and a sell filled above it. Section 7.4's example of something
    invisible in raw JSON and obvious in prose -- and meaningless without a
    limit, which a market order does not have.
    """
    if limit is None or side is None or not total_qty:
        return None
    average = notional / total_qty
    return limit - average if side == _BUY else average - limit


def _elapsed(episode: Episode, fact: Fact | None) -> float | None:
    if fact is None:
        return None
    return (fact.receipt_ts - episode.opened_ts).total_seconds()


def _find(facts: list[Fact], kind: str) -> Fact | None:
    return next((f for f in facts if f.kind == kind), None)


def _first_price(facts: list[Fact]) -> float | None:
    """The order's limit price, from the earliest fact that states one.

    ``order.new`` carries it as ``price_ticks`` and the engine's own events
    restate it as ``price`` in display money; the Fact layer has already put
    both on the same scale, so this only has to take whichever arrived first.
    """
    for fact in facts:
        for name in ("price_ticks", "price"):
            value = _price(fact, name)
            if value is not None:
                return value
    return None


def _first_str(facts: list[Fact], name: str) -> str | None:
    for fact in facts:
        value = _str(fact.payload, name)
        if value is not None:
            return value
    return None


def _last(facts: list[Fact], *names: str) -> int | None:
    """The most recent statement of a field, under any of its spellings."""
    found: int | None = None
    for fact in facts:
        for name in names:
            value = _int(fact.payload, name)
            if value is not None:
                found = value
    return found


def _price(fact: Fact, name: str) -> float | None:
    price = fact.prices.get(name)
    return price.display if price is not None else None


def _str(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _int(payload: Mapping[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
