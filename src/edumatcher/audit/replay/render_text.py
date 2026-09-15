"""Episodes to prose (design section 8).

Pass 2. A **pure function of the episode graph**: it may reformat and it may
omit, but it may not consult the raw log, and it may not state anything the
graph does not already record (section 8.3). Every sentence comes from
:mod:`~edumatcher.audit.replay.templates`; every enum word comes from
:mod:`~edumatcher.audit.replay.lexicon`; this module only decides which
template and fills its slots.

Three of section 8.3's prohibitions are structural here rather than a matter
of care:

* *No price without a resolved unit.* Prices are read through
  :func:`_money`, which renders an unresolved one as ticks, labelled.
* *No outcome for an episode that is still open.* The outcome phrase for
  ``OPEN`` and ``PARTIAL`` says so in words, and is the only thing a summary
  can print.
* *No unhedged cause for a guess.* ``--explain`` prints the confidence beside
  every link, and a HEURISTIC one is worded as a guess.

Where something is absent the output says so briefly and in line, including --
and this is the part that saves an hour -- that the antecedent may simply be
outside the requested window.
"""

from __future__ import annotations

import json

from dataclasses import dataclass, replace
from typing import Any, Iterable, Iterator, Mapping, Sequence

from edumatcher.audit.replay import lexicon, templates
from edumatcher.audit.replay.anomalies import (
    SEVERITY_WARN,
    UNKNOWN_ENUM,
    Anomaly,
)
from edumatcher.audit.replay.derived import derive
from edumatcher.audit.replay.episodes import (
    KIND_ORDER,
    KIND_ORPHAN,
    KIND_TRADE,
    OUTCOME_OPEN,
    Episode,
    EpisodeEvent,
)
from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.replay.links import REJECTED_BECAUSE, Confidence, Link
from edumatcher.audit.replay.state import StateModel

#: The indent a continuation line carries, matching section 10's examples.
CONTINUATION = " " * 14

#: Section 8.4's default id abbreviation.
DEFAULT_ID_LEN = 6

#: Payload fields that hold an entity id, in the order a line prefers them for
#: its own subject. One list, used both to pick a line's ``{ref}`` and to
#: build the collision pool -- a field in one and not the other is an id that
#: prints abbreviated without ever having been checked for ambiguity, which is
#: how two different recovery items both printed as ``dead00…``.
ID_FIELDS = (
    "id",
    "order_id",
    "quote_id",
    "oco_id",
    "combo_id",
    "entity_id",
)

#: Ids a line *refers* to rather than is about. They never become a ``{ref}``,
#: but they are printed, so they belong in the collision pool.
REFERENCE_ID_FIELDS = (
    "cancelled_order_id",
    "bid_order_id",
    "ask_order_id",
    "order_id_1",
    "order_id_2",
    "buy_order_id",
    "sell_order_id",
)

_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class Options:
    """The rendering switches of sections 8.1 and 8.4."""

    level: int = templates.LEVEL_DEFAULT
    id_len: int | None = DEFAULT_ID_LEN
    descriptive_actors: bool = False
    show_source: bool = False
    show_units: bool = False
    explain: bool = False


@dataclass(frozen=True, slots=True)
class Rendered:
    """One narrated line, with whatever the switches added beneath it.

    Kept apart from the joined text so the NDJSON renderer of section 11 can
    take the sentence without the annotations, and so a caller can indent
    continuations its own way.
    """

    receipt: str
    text: str
    continuations: tuple[str, ...] = ()
    anomalies: tuple[Anomaly, ...] = ()

    def lines(self) -> list[str]:
        head = f"{self.receipt}  {self.text}" if self.receipt else self.text
        return [head] + [CONTINUATION + line for line in self.continuations]


class Abbreviator:
    """Shortens ids, and lengthens them when two would collide (section 8.4).

    An ambiguous reference is worse than a long one: a reader who sees
    ``4f2c9a…`` twice and assumes one order has no way to find out otherwise.
    So the ids in scope are inspected up front and the length raised until
    every prefix is unique -- for *all* of them, not only the colliding pair,
    because two lengths in one report is its own kind of confusing.
    """

    def __init__(self, ids: Iterable[str], length: int | None = DEFAULT_ID_LEN):
        self._full = length is None
        self._length = length or 0
        if self._full:
            return
        pool = {i for i in ids if len(i) > self._length}
        while pool and self._length < max(len(i) for i in pool):
            if len({i[: self._length] for i in pool}) == len(pool):
                break
            self._length += 1

    def __call__(self, value: str | None) -> str:
        if not value:
            return "-"
        if self._full or len(value) <= self._length:
            return value
        return value[: self._length] + _ELLIPSIS


class Renderer:
    """Turns episodes into lines.

    The state model is read for one thing only -- a gateway's human
    description, for ``--actor-style=descriptive`` -- and never for anything
    the episode could have carried itself.
    """

    def __init__(
        self,
        episodes: Sequence[Episode],
        state: StateModel | None = None,
        options: Options | None = None,
    ) -> None:
        self.options = options or Options()
        self.state = state
        self._abbrev = Abbreviator(_identifiers(episodes), self.options.id_len)
        #: Who was on each side of an order, so a trade line can name both
        #: of them. Section 10.1's headline sentence needs the *other*
        #: episode, and this is the only cross-episode lookup the renderer
        #: does -- built from the graph it was handed, never from the log.
        self._order_owner: dict[str, tuple[str | None, str | None]] = {}
        for episode in episodes:
            if episode.kind != KIND_ORDER:
                continue
            side = next(
                (
                    s
                    for event in episode.events
                    if (s := _str(event.fact.payload, "side"))
                ),
                None,
            )
            self._order_owner[episode.anchor_key] = (episode.actor, side)
        #: The two orders behind each print. A fill names a trade, not a
        #: party, so this is how "took from TRADER02's sell 9ab1c4…" is
        #: reached from the fill's own line.
        self._trade_sides: dict[str, tuple[str | None, str | None]] = {
            episode.anchor_key: (
                _str(episode.opened.payload, "buy_order_id"),
                _str(episode.opened.payload, "sell_order_id"),
            )
            for episode in episodes
            if episode.kind == KIND_TRADE
        }
        #: The tick scale each episode trades at, for formatting only. A
        #: display price is correct without one; what it cannot do without one
        #: is print with the instrument's own precision, which is why
        #: ``order.fill.fill_price`` used to read 74.8 beside the trade's
        #: 74.80 for the very same number.
        #: Keyed by symbol, not by episode: the tick scale is a property of
        #: the instrument. An episode that opens with ``order.fill`` -- the
        #: resting side, whose submission is outside the window -- carries no
        #: scale of its own, and printing its price to a different precision
        #: from the print it belongs to helps nobody.
        self._scale: dict[str, int] = {}
        for episode in episodes:
            for event in episode.events:
                symbol = event.fact.symbol or episode.symbol
                decimals = _int(event.fact.payload, "tick_decimals")
                if symbol and decimals is not None:
                    self._scale.setdefault(symbol, decimals)

    # -- the two shapes -----------------------------------------------------

    def summaries(self, episodes: Iterable[Episode]) -> Iterator[Rendered]:
        """Level 0: one line per episode, outcome first.

        An episode whose opening fact level 1 would not narrate is skipped
        here too -- a page of "unattached book" is not a list of outcomes.
        :func:`suppressed` cannot be asked directly, because at level 0 it is
        true of everything: level 0 is a different shape, not a quieter
        level 1.
        """
        for episode in episodes:
            if suppressed(episode.opened, templates.LEVEL_DEFAULT):
                continue
            yield Rendered(receipt=_clock(episode.opened), text=self.summary(episode))

    def summary(self, episode: Episode) -> str:
        """The level-0 sentence for one episode.

        Public because section 11's ``episode`` object carries the same
        string: two renderers working it out separately is precisely the
        drift the machine-readable format exists to make impossible.
        """
        return _fill(
            templates.SUMMARIES.get(episode.kind, templates.SUMMARIES["orphan"]),
            self._summary_slots(episode),
        )

    def stream(
        self, events: Iterable[tuple[Episode, EpisodeEvent]]
    ) -> Iterator[Rendered]:
        """Levels 1 and up: one line per narrated fact, in the order given."""
        for episode, event in events:
            rendered = self.line(episode, event)
            if rendered is not None:
                yield rendered

    def line(self, episode: Episode, event: EpisodeEvent) -> Rendered | None:
        """One fact, or None when this level withholds it.

        Withheld, not dropped: :func:`suppressed` is public and AR-4.5's
        round-trip property asserts against it, so every event is narrated,
        explicitly suppressed, or an orphan -- and never simply absent.
        """
        fact = event.fact
        if suppressed(fact, self.options.level):
            return None
        slots, found = self._slots(episode, fact)
        template = _template_for(fact.kind, self.options.level)
        return Rendered(
            receipt=_clock(fact),
            text=_fill(template, slots),
            continuations=tuple(self._annotations(episode, event)),
            anomalies=tuple(found),
        )

    # -- slots --------------------------------------------------------------

    def _slots(
        self, episode: Episode, fact: Fact
    ) -> tuple[dict[str, str], list[Anomaly]]:
        found: list[Anomaly] = []

        def word(field: str, value: Any) -> str:
            if not isinstance(value, str) or not value:
                return ""
            if not lexicon.is_known(field, value):
                found.append(
                    Anomaly(
                        code=UNKNOWN_ENUM,
                        severity=SEVERITY_WARN,
                        detail=f"{fact.kind}.{field} = {value!r} has no lexicon entry",
                        receipt_ts=fact.receipt_raw,
                        file=fact.file,
                        line_no=fact.line_no,
                    )
                )
            return lexicon.phrase(field, value)

        payload = fact.payload
        ref = self._ref_for(fact)
        slots: dict[str, str] = {
            "kind": fact.kind,
            "ref": ref,
            "actor": self._actor(episode, fact),
            "actor_clause": _clause(" from ", self._actor(episode, fact), ""),
            "symbol": fact.symbol or episode.symbol or "-",
            "side": word("side", payload.get("side")),
            "order_type": word("order_type", payload.get("order_type")),
            "status": word("status", payload.get("status")),
            "qty": _number(payload.get("quantity") or payload.get("qty")),
            "at_price": _clause(" @ ", _money(fact, "price_ticks", "price"), ""),
            "tif_clause": _clause(" (", word("tif", payload.get("tif")), ")"),
            "origin_clause": _clause(" — ", word("origin", payload.get("origin")), ""),
            "verdict": _verdict(payload.get("accepted")),
            "reject_clause": _clause(
                " — ", word("reject_code", payload.get("reject_code")), ""
            ),
            "because_clause": self._because(fact, word),
            "fill_qty": _number(payload.get("fill_qty")),
            "fill_price": _money(
                fact, "fill_price", scale=self._scale_for(episode, fact)
            ),
            **self._fill_words(fact),
            "price": _money(fact, "price", "eq_price"),
            "progress_clause": self._progress(episode, fact),
            "counterparty": self._counterparty(fact),
            "explain_reject": "",
            "notional_clause": self._notional(episode, fact),
            "aggressor_clause": self._aggressor(fact, word),
            "sides_clause": self._sides(fact, word),
            "on_clause": _clause(" on ", _str(payload, "symbol"), ""),
            "note_clause": _clause(" — ", _str(payload, "note"), ""),
            "command_label": self._command_label(fact),
            "amend_clause": _clause(" to ", _number(payload.get("qty")), " remaining"),
            "bid_qty": _number(payload.get("bid_qty")),
            "ask_qty": _number(payload.get("ask_qty")),
            "bid_price": _money(fact, "bid_price_ticks"),
            "ask_price": _money(fact, "ask_price_ticks"),
            "legs_clause": self._legs(fact),
            "leg_ref": self._abbrev(_str(payload, "cancelled_order_id")),
            "combo_type": word("combo_type", payload.get("combo_type")),
            "combo_article": _article(word("combo_type", payload.get("combo_type"))),
            "halt_source": word("halt_source", payload.get("halt_source")),
            "corridor_clause": self._corridor(fact),
            "trigger_clause": self._trigger(fact),
            "imbalance_clause": self._imbalance(fact, word),
            "to_state": _str(payload, "to_state") or "-",
            "state": _str(payload, "state") or "-",
            "from_clause": _clause(", from ", _str(payload, "prev_state"), ""),
            "auth_clause": self._auth(fact),
            "restored": _plural(_int(payload, "restored_orders"), "order"),
            "recovery_failure_clause": self._recovery_failures(fact),
            "entity_kind": word("kind", payload.get("kind")).title() or "Entity",
            "outcome": word("outcome", payload.get("outcome")),
            "detail_clause": _clause(" — ", _str(payload, "detail"), ""),
            "action": word("action", payload.get("action")),
            "change_type": word("change_type", payload.get("change_type")),
            "index_id": _str(payload, "index_id") or "-",
            # -- level 3, the market ---------------------------------------
            "top_bid": _level(payload, "bids", self._scale_for(episode, fact)),
            "top_ask": _level(payload, "asks", self._scale_for(episode, fact)),
            "last_clause": _clause(" — last ", _money(fact, "last_price"), ""),
            "mid_price": _money(fact, "mid_price_ticks", "mid_price"),
            "bid_depth": _number(payload.get("bid_depth")),
            "ask_depth": _number(payload.get("ask_depth")),
            "skew_clause": self._skew(fact),
            "index_level": _decimal(payload.get("level")),
            "event_type": word("event_type", payload.get("event_type")),
        }
        return slots, found

    def _summary_slots(self, episode: Episode) -> dict[str, str]:
        facts = derive(episode)
        fact = episode.opened
        return {
            "kind": fact.kind,
            "ref": self._abbrev(episode.anchor_key),
            "symbol": episode.symbol or "-",
            "outcome_phrase": templates.OUTCOME_PHRASES.get(
                episode.outcome, episode.outcome
            ),
            "qty": _number(facts.quantity),
            "price": _money(fact, "price"),
            "fill_summary": _clause(
                " — ",
                (
                    f"{facts.filled_qty} of {facts.quantity} filled"
                    # Nothing filled is not a fill tally worth printing: "0 of
                    # 100 filled" beside "was rejected" says the same thing
                    # twice and the second time less clearly.
                    if facts.filled_qty and facts.quantity is not None
                    else ""
                ),
                "",
            ),
        }

    # -- clause builders ----------------------------------------------------

    def _ref_for(self, fact: Fact) -> str:
        for name in ID_FIELDS:
            value = _str(fact.payload, name)
            if value:
                return self._abbrev(value)
        return "-"

    def _actor(self, episode: Episode, fact: Fact) -> str:
        name = _str(fact.payload, "gateway_id") or episode.actor
        if not name:
            return ""
        if self.options.descriptive_actors and self.state is not None:
            gateway = self.state.gateways.get(name)
            if gateway is not None and gateway.description:
                return f"{name} ({gateway.description})"
        return name

    def _because(self, fact: Fact, word: Any) -> str:
        for field in ("cancel_reason", "reject_code"):
            value = _str(fact.payload, field)
            if value:
                return f" — {word(field, value)}"
        reason = _str(fact.payload, "reason")
        return f" — {reason}" if reason else ""

    def _progress(self, episode: Episode, fact: Fact) -> str:
        remaining = _int(fact.payload, "remaining_qty")
        quantity = _int(fact.payload, "qty") or derive(episode).quantity
        if remaining is None or quantity is None:
            return ""
        if remaining == 0:
            return f" — {quantity} of {quantity} done"
        return f" — {remaining} of {quantity} still working"

    def _scale_for(self, episode: Episode, fact: Fact) -> int | None:
        """This instrument's tick precision, for formatting only."""
        symbol = fact.symbol or episode.symbol
        return self._scale.get(symbol) if symbol else None

    def _fill_words(self, fact: Fact) -> dict[str, str]:
        """``verb`` and ``prep`` for a fill (section 8.2).

        ``crossed_in_uncross`` cannot be read off the fill: the engine flags
        both sides of an auction print MAKER, and only the trade carries
        ``aggressor_side``. Within one episode the fill is all there is, so a
        MAKER fill is narrated passively and the uncross reading comes from
        the trade's own line -- which is where ``aggressor_side`` lives.
        """
        verb, prep = lexicon.fill_verb(
            _str(fact.payload, "liquidity_flag"), _str(fact.payload, "side"), False
        )
        return {"verb": verb, "prep": prep}

    def _sides(self, fact: Fact, word: Any) -> str:
        """Who took and who rested, by name (section 10.1).

        An uncross is said to have crossed, never taken: ``aggressor_side`` is
        ``AUCTION`` exactly when the engine is stating that neither side was
        the aggressor.
        """
        aggressor = _str(fact.payload, "aggressor_side")
        buy, sell = (
            _str(fact.payload, "buy_order_id"),
            _str(fact.payload, "sell_order_id"),
        )
        if aggressor is None or buy is None or sell is None:
            return self._aggressor(fact, word)
        taker, maker = (buy, sell) if aggressor == "BUY" else (sell, buy)
        if aggressor == "AUCTION":
            return f"{self._owned(buy)} crossed with {self._owned(sell)}"
        return f"{self._owned(taker)} took from {self._owned(maker)}"

    def _owned(self, order_id: str) -> str:
        """``TRADER01's buy 4f2c9a…`` -- as much of it as the graph knows."""
        actor, side = self._order_owner.get(order_id, (None, None))
        parts = [f"{actor}'s"] if actor else []
        if side:
            parts.append(lexicon.phrase("side", side))
        parts.append(self._abbrev(order_id))
        return " ".join(parts)

    def _command_label(self, fact: Fact) -> str:
        """What an ack is an ack *of*, without naming a message type.

        The topic minus its ``_ack`` suffix, with dots and underscores opened
        out: ``risk.kill_switch_ack`` becomes "the kill switch". A reader of
        the prose should not have to know the topic tree.
        """
        kind = fact.kind
        if kind.endswith("_ack"):
            kind = kind[: -len("_ack")]
        _family, _, name = kind.rpartition(".")
        return "the " + name.replace("_", " ")

    def _counterparty(self, fact: Fact) -> str:
        """Who was on the other side, by name where the window knows.

        The fill itself names only a trade, so this hops fill -> trade ->
        the other order id. Both hops stay inside the episode graph. Where the
        trade is outside the window the answer is the trade id, which is at
        least something a reader can go and look up -- never an invented
        counterparty.
        """
        trades = fact.payload.get("trade_ids")
        if not (isinstance(trades, list) and trades):
            return "the book"
        trade_id = str(trades[0])
        mine = _str(fact.payload, "order_id")
        buy, sell = self._trade_sides.get(trade_id, (None, None))
        other = sell if mine == buy else buy
        if other:
            return self._owned(other)
        return f"trade {self._abbrev(trade_id)}"

    def _notional(self, episode: Episode, fact: Fact) -> str:
        facts = derive(episode)
        if facts.notional is None:
            return ""
        return f" — notional {facts.notional:,.2f}"

    def _aggressor(self, fact: Fact, word: Any) -> str:
        side = _str(fact.payload, "aggressor_side")
        if side is None:
            return "no recorded aggressor"
        return f"taken by {word('aggressor_side', side)}"

    def _legs(self, fact: Fact) -> str:
        legs = [
            self._abbrev(_str(fact.payload, name))
            for name in ("bid_order_id", "ask_order_id", "order_id_1", "order_id_2")
            if _str(fact.payload, name)
        ]
        return f" — legs {' and '.join(legs)}" if legs else ""

    def _corridor(self, fact: Fact) -> str:
        low, high = _price(fact, "corridor_low"), _price(fact, "corridor_high")
        if low is None or high is None:
            return ""
        return f", corridor {low:g}-{high:g}"

    def _trigger(self, fact: Fact) -> str:
        trigger, reference = _price(fact, "trigger_price"), _price(
            fact, "reference_price"
        )
        if trigger is None or reference is None or not reference:
            return ""
        move = (trigger - reference) / reference * 100
        return f", triggered at {trigger:g} against {reference:g} ({move:+.1f}%)"

    def _imbalance(self, fact: Fact, word: Any) -> str:
        qty = _int(fact.payload, "imbalance_qty")
        side = _str(fact.payload, "imbalance_side")
        if not qty or side is None:
            return ""
        return f", {qty} {word('imbalance_side', side)} unfilled"

    def _skew(self, fact: Fact) -> str:
        """``depth.imbalance`` as a side, not as a signed float.

        The field is a ratio and reads as one; a reader wants to know which
        way the book leans, which is what the sign means.
        """
        value = fact.payload.get("imbalance")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ""
        if value == 0:
            return ", balanced"
        return f", imbalance {abs(value):g} to the {'bid' if value > 0 else 'ask'}"

    def _auth(self, fact: Fact) -> str:
        if fact.payload.get("accepted") is False:
            reason = _str(fact.payload, "reason")
            return f" — refused{_clause(': ', reason, '')}"
        description = _str(fact.payload, "description")
        return f" ({description})" if description else ""

    def _recovery_failures(self, fact: Fact) -> str:
        failed = _int(fact.payload, "failed_orders")
        return f", {failed} failed" if failed else ""

    # -- the switches -------------------------------------------------------

    def _annotations(self, episode: Episode, event: EpisodeEvent) -> Iterator[str]:
        fact = event.fact
        if self.options.level >= templates.LEVEL_DETAIL:
            yield from self._why_rejected(event)
        if self.options.explain:
            yield from self._explain(episode, event)
        if self.options.show_units:
            for price in fact.prices.values():
                yield f"· {price.name}: {price.provenance()}"
        if self.options.show_source and fact.source:
            yield f"· {fact.source}"
        if self.options.level >= templates.LEVEL_MARKET:
            yield from self._mechanics(fact)
        if self.options.level >= templates.LEVEL_RAW:
            yield f"· payload: {json.dumps(fact.payload, sort_keys=True)}"

    def _mechanics(self, fact: Fact) -> Iterator[str]:
        """Section 8.1's level-3 additions beyond market data.

        ``arrival_seq`` is what the book actually used for priority, and the
        clock difference is the one number that says whether anything timed
        across the two clocks can be trusted. Both are on the line at level 3
        rather than in the anomaly report because at this level the reader is
        looking at mechanism, not hunting a bug.
        """
        arrival = _int(fact.payload, "arrival_seq")
        if arrival is not None:
            yield f"· arrival_seq {arrival}"
        stamped = fact.times.get("ts_ns")
        if stamped is not None:
            drift = (stamped.when - fact.receipt_ts).total_seconds()
            yield f"· {stamped.clock} clock {drift:+.3f}s from receipt"

    def _why_rejected(self, event: EpisodeEvent) -> Iterator[str]:
        """The market condition behind a rejection (section 10.3).

        This is the payoff of the market model, and the reason it exists: the
        reject code alone is a constant, while the halt that explains it is a
        minute and several thousand lines earlier. The clause is the state
        model's own description, carried on the ``rejected_because`` link --
        not re-derived here, so the prose cannot disagree with the link.
        """
        for link in event.step.resolution.links:
            if link.relation == REJECTED_BECAUSE:
                yield f"⤷ {link.evidence}"

    def _explain(self, episode: Episode, event: EpisodeEvent) -> Iterator[str]:
        """Link evidence and confidence, and what the tool could *not* find.

        A HEURISTIC link is worded as a guess, which section 8.3 requires: an
        unhedged cause the tool picked between two candidates reads exactly
        like one it read off the wire.
        """
        resolution = event.step.resolution
        for link in resolution.links:
            yield f"⤷ {_link_phrase(link)}"
        if resolution.origin:
            yield "⤷ the publisher recorded that nothing caused this"
        for anomaly in event.step.anomalies:
            if anomaly.code == "CAUSE_NOT_FOUND":
                yield (
                    "⤷ its stated cause is not in this window "
                    "(try an earlier --from)"
                )
        if resolution.orphan:
            yield "⤷ nothing in this window explains it"
        if episode.outcome == OUTCOME_OPEN and event is episode.events[-1]:
            yield "⤷ still open where the window ends"


# ---------------------------------------------------------------------------
# Suppression (section 8.1), public because AR-4.5 asserts against it
# ---------------------------------------------------------------------------


def suppressed(fact: Fact, level: int) -> bool:
    """Whether *level* withholds this fact.

    The round-trip property needs "withheld" to be a statement the tool can
    make, not an absence a reader has to notice. So this is a function rather
    than an ``if`` inside the renderer, and the test asserts over it.

    Two rules, and section 8.1 puts them at different levels. A kind in
    :data:`~templates.MIN_LEVEL` is market data or a query reply and arrives
    at level 3. A fact whose topic is in **no message family** is section
    8.1's "unclassified event" and arrives only at level 4: the tool cannot
    say what it is, so it has no business in a narrative of what the exchange
    did -- and it is not hidden either way, because ``UNKNOWN_TOPIC`` is
    raised on it at every level and the ``anomalies`` view reports it.

    Level 4 therefore withholds nothing at all, which is what makes the
    round-trip property strict equality there.
    """
    if not fact.known:
        return level < templates.LEVEL_RAW
    return level < templates.MIN_LEVEL.get(fact.kind, templates.LEVEL_DEFAULT)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _template_for(kind: str, level: int) -> str:
    by_level = templates.TEMPLATES.get(kind)
    if by_level is None:
        return templates.ACK_TEMPLATE if kind.endswith("_ack") else templates.GENERIC
    for candidate in range(level, templates.LEVEL_DEFAULT - 1, -1):
        if candidate in by_level:
            return by_level[candidate]
    return templates.GENERIC


class _Blanks(dict[str, str]):
    """A slot a template names and the renderer did not fill is empty.

    Not a KeyError: a template naming a slot that does not apply to one of its
    kinds is a wording bug, and crashing a replay over it would take the whole
    window with it.
    """

    def __missing__(self, key: str) -> str:
        return ""


def _fill(template: str, slots: Mapping[str, str]) -> str:
    return " ".join(template.format_map(_Blanks(slots)).split())


def _article(word: str) -> str:
    """``a`` or ``an``, by sound as far as a letter can tell.

    Crude on purpose. The alternative is a template that says "a(n)", which
    is the kind of detail that makes prose read as generated.
    """
    return "an" if word[:1].lower() in "aeiou" else "a"


def _clause(prefix: str, body: str | None, suffix: str) -> str:
    return f"{prefix}{body}{suffix}" if body else ""


def _clock(fact: Fact) -> str:
    return fact.receipt_ts.strftime("%H:%M:%S.%f")[:-3]


def _plural(count: int | None, noun: str) -> str:
    """``1 order`` / ``3 orders``. "order(s)" reads as generated, because it is."""
    if count is None:
        return ""
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def _number(value: Any) -> str:
    return (
        f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else ""
    )


def _money(fact: Fact, *names: str, scale: int | None = None) -> str:
    """A price, or ticks labelled as ticks -- never a bare unresolved number.

    *scale* is the episode's tick precision and is used only to format a price
    whose own message declares none. It cannot change the value: a display
    price is already display money, and an unresolved tick price stays in
    ticks whatever is passed here.
    """
    for name in names:
        price = fact.prices.get(name)
        if price is None:
            continue
        if price.tick_decimals is None and price.display is not None and scale:
            return f"{price.display:.{scale}f}"
        return price.render()
    return ""


def _level(payload: Mapping[str, Any], side: str, scale: int | None) -> str:
    """The top of one side of a book snapshot, as ``74.75 x 500``.

    Only the top: a level-3 line runs beside thousands of others and the
    whole ladder belongs in the raw payload at level 4, where it already is.
    """
    levels = payload.get(side)
    if not isinstance(levels, list) or not levels:
        return "-"
    top = levels[0]
    if not isinstance(top, dict):
        return "-"
    price, qty = top.get("price"), top.get("qty")
    if price is None or qty is None:
        return "-"
    # The ladder is a list of plain numbers rather than declared price fields,
    # so it never passes through Price -- but it is the same instrument, and
    # printing 74.8 beside a 74.80 elsewhere in the same line reads as two
    # different prices.
    shown = f"{price:.{scale}f}" if scale is not None else f"{price:g}"
    return f"{shown} x {_number(qty) or qty}"


def _decimal(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "-"
    return f"{value:,.2f}"


def _price(fact: Fact, name: str) -> float | None:
    price = fact.prices.get(name)
    return price.display if price is not None else None


def _link_phrase(link: Link) -> str:
    if link.confidence is Confidence.HEURISTIC:
        return (
            f"{link.relation.replace('_', ' ')} {link.source} — a guess: "
            f"{link.evidence}"
        )
    return (
        f"{link.relation.replace('_', ' ')} {link.source} "
        f"[{link.confidence.value.lower()}: {link.evidence}]"
    )


def _verdict(accepted: Any) -> str:
    if accepted is True:
        return "accepted"
    if accepted is False:
        return "rejected"
    return "answered"


def _identifiers(episodes: Iterable[Episode]) -> set[str]:
    """Every id the window will print, so none is abbreviated ambiguously."""
    found: set[str] = set()
    for episode in episodes:
        found.add(episode.anchor_key)
        for event in episode.events:
            for name in ID_FIELDS + REFERENCE_ID_FIELDS:
                value = _str(event.fact.payload, name)
                if value:
                    found.add(value)
    return found


def _str(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _int(payload: Mapping[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def narrate(
    episodes: Sequence[Episode],
    state: StateModel | None = None,
    options: Options | None = None,
) -> list[str]:
    """The whole window as text, in canonical order.

    Level 0 prints episode summaries in the order the episodes opened;
    everything else prints one line per fact in the order the facts happened,
    which is what makes ``stream`` read like a session rather than a list of
    objects.
    """
    options = options or Options()
    renderer = Renderer(episodes, state, options)
    if options.level <= templates.LEVEL_OUTCOMES:
        rendered = renderer.summaries(sorted(episodes, key=lambda e: e.opened_sort_key))
    else:
        events = sorted(
            ((episode, event) for episode in episodes for event in episode.events),
            key=lambda pair: pair[1].fact.ordinal,
        )
        rendered = renderer.stream(events)
    return [line for item in rendered for line in item.lines()]


__all__ = [
    "Abbreviator",
    "Options",
    "Rendered",
    "Renderer",
    "narrate",
    "suppressed",
    "replace",
    "KIND_ORDER",
    "KIND_ORPHAN",
    "KIND_TRADE",
]
