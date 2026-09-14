"""Fact -> Episode: the unit of narration (design sections 4, 7.3).

An episode is one business happening -- an order's life, a halt and the resume
that ended it, a command and its ack -- assembled from the Facts that make it
up. It is the abstraction everything downstream reads: the narrator renders
episodes, the index stores them, ``story`` retrieves one.

**One Fact belongs to exactly one episode.** Section 6.2 makes the
chronological stream "a single ordered scan of ``episode_events``", and a fill
filed under both its order and its trade would be narrated twice by that scan.
So a fill belongs to its order, and the trade reaches it through a ``links``
row instead. Section 4's "typical Facts" column lists what an episode is
*about*, not what it contains.

**The most specific kind wins.** Section 4's ``command`` row claims "any
``risk.*`` / ``admin.action`` / ``session.transition`` / ``index.*`` request
with its ack", and the same table gives ``session`` and ``index`` rows of their
own. Both cannot own the same message. ``session`` keeps the session family,
``index`` keeps the index commands, and ``command`` is left with ``risk.*`` and
``admin.action`` -- which leaves all eleven kinds disjoint and each of them
meaning something a reader would ask for by name.

**Nothing is dropped.** A Fact no rule claims becomes a single-event episode of
kind ``orphan`` (section 7.2). That is deliberately noisy on a log full of
market data: the count is the coverage finding of section 12.5, and a tool that
quietly discarded what it could not classify would be hiding exactly the thing
its reader needs to know.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Iterator, Mapping, TypeVar

from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.replay.links import LinkResolver
from edumatcher.audit.replay.ordering import (
    DEFAULT_MAX_FACTS,
    DEFAULT_MAX_SECONDS,
    SortKey,
    sort_key,
)
from edumatcher.audit.replay.pipeline import Step
from edumatcher.audit.replay.state import StateModel

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

#: The eleven kinds of section 4, plus the catch-all of section 7.2.
KIND_ORDER = "order"
KIND_TRADE = "trade"
KIND_QUOTE = "quote"
KIND_OCO = "oco"
KIND_COMBO = "combo"
KIND_COMMAND = "command"
KIND_MARKET_PHASE = "market_phase"
KIND_SESSION = "session"
KIND_GATEWAY = "gateway"
KIND_INDEX = "index"
KIND_RECOVERY = "recovery"
KIND_ORPHAN = "orphan"

#: ``episodes.outcome`` in section 6.2's schema.
OUTCOME_FILLED = "FILLED"
OUTCOME_PARTIAL = "PARTIAL"
OUTCOME_CANCELLED = "CANCELLED"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_EXPIRED = "EXPIRED"
OUTCOME_ACCEPTED = "ACCEPTED"
OUTCOME_DENIED = "DENIED"
OUTCOME_OPEN = "OPEN"
OUTCOME_UNKNOWN = "UNKNOWN"

#: ``episode_events.role``. What this fact did to the episode. The first event
#: is always ``open``; a later one that ends the episode is ``close``.
ROLE_OPEN = "open"
ROLE_PROGRESS = "progress"
ROLE_CLOSE = "close"

#: ``quote.status`` and ``combo.status`` values that end their episode, mapped
#: to the outcome each one means. Spelled out rather than imported because the
#: generated ``_VALUES`` tuples are private; the fixture tests are what catch a
#: value being added to the spec and not to this table.
_TERMINAL_STATUS: Mapping[str, str] = {
    "CANCELLED": OUTCOME_CANCELLED,
    "REJECTED": OUTCOME_REJECTED,
    "FAILED": OUTCOME_DENIED,
    "MATCHED": OUTCOME_ACCEPTED,
    "INACTIVE_BID_FILLED": OUTCOME_FILLED,
    "INACTIVE_ASK_FILLED": OUTCOME_FILLED,
}

_ACK_SUFFIX = "_ack"

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# The episode
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EpisodeEvent:
    """One Fact's membership of one episode.

    Holds the whole :class:`~edumatcher.audit.replay.pipeline.Step`, not just
    the Fact: the resolution is what phase 3's index turns into ``links`` rows,
    and the anomalies are what it anchors to an ``episode_id``. Splitting them
    off here would mean joining them back on later by line number.
    """

    step: Step
    seq_in_ep: int
    role: str

    @property
    def fact(self) -> Fact:
        return self.step.fact


@dataclass(slots=True)
class Episode:
    """A set of causally connected Facts with one business meaning.

    ``episode_id`` is assigned when the episode opens rather than when it is
    emitted, so a link recorded between two episodes stays valid however the
    retirement order shuffles them.
    """

    episode_id: int
    kind: str
    anchor_key: str
    events: list[EpisodeEvent] = field(default_factory=list)
    outcome: str = OUTCOME_OPEN
    closed: bool = False
    #: When the episode ended. Usually its last event's receipt time -- but a
    #: session span is ended by the fact that opens the *next* one, which
    #: belongs to that episode and not to this one.
    closed_ts: datetime | None = None
    closed_sort_key: SortKey | None = None

    @property
    def opened(self) -> Fact:
        return self.events[0].fact

    @property
    def opened_ts(self) -> datetime:
        return self.opened.receipt_ts

    @property
    def opened_sort_key(self) -> SortKey:
        return sort_key(self.opened)

    @property
    def correlation_id(self) -> str | None:
        return _first(event.fact.correlation_id for event in self.events)

    @property
    def root_msg_id(self) -> str | None:
        return self.opened.msg_id

    @property
    def symbol(self) -> str | None:
        return _first(event.fact.symbol for event in self.events)

    @property
    def actor(self) -> str | None:
        """The gateway that originated this, when one did.

        The payload's ``gateway_id`` before the topic's wildcard, because the
        wildcard on an outbound message names the *recipient*: ``order.fill``
        is addressed to the filled gateway, which for a quote leg is not who
        submitted it.

        Not every wildcard is a gateway. ``book.AAPL`` and
        ``circuit_breaker.halt.AAPL`` are parameterised by symbol, and the
        Fact layer records that by setting ``symbol`` to the same value -- so
        a wildcard equal to the fact's own symbol is a symbol, and this
        episode has no actor rather than an instrument for one.
        """
        return _first(
            _str(event.fact.payload, "gateway_id") or _gateway_wildcard(event.fact)
            for event in self.events
        )

    @property
    def run_seq(self) -> int | None:
        return _first(_int(event.fact.payload, "run_seq") for event in self.events)


def _gateway_wildcard(fact: Fact) -> str | None:
    """The topic's wildcard, unless it is a symbol."""
    return None if fact.actor == fact.symbol else fact.actor


def _first(values: Iterable[_T | None]) -> _T | None:
    """The first value an episode's events agree on, in the order they arrived.

    An episode's symbol, actor and run are properties of the happening, not of
    any one line: ``order.new`` names the gateway, ``order.fill`` names the
    symbol, and either may be the one that opened the episode.
    """
    for value in values:
        if value is not None:
            return value
    return None


def _str(payload: Mapping[str, object], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _int(payload: Mapping[str, object], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


# ---------------------------------------------------------------------------
# Which episode a Fact belongs to
# ---------------------------------------------------------------------------


def claim(fact: Fact) -> tuple[str, str] | None:
    """``(episode kind, anchor key)`` for this Fact, or None for an orphan.

    Ordered most specific first, so the overlaps in section 4's table resolve
    the way the module docstring describes. A rule that finds its kind but not
    its anchor returns None rather than inventing one: an ack with no
    ``command_id`` cannot be joined to anything, and saying so is the honest
    answer.
    """
    kind = fact.kind
    payload = fact.payload

    if kind == kinds.ORDER_NEW:
        return _anchored(KIND_ORDER, _str(payload, "id"))
    if kind in _ORDER_KINDS:
        return _anchored(KIND_ORDER, _str(payload, "order_id"))
    if kind == kinds.TRADE_EXECUTED:
        return _anchored(KIND_TRADE, _str(payload, "id"))
    if kind in _QUOTE_KINDS:
        return _anchored(KIND_QUOTE, _str(payload, "quote_id"))
    if kind in _OCO_KINDS:
        return _anchored(KIND_OCO, _str(payload, "oco_id"))
    if kind in _COMBO_KINDS:
        return _anchored(KIND_COMBO, _str(payload, "combo_id"))
    if kind in _INDEX_KINDS:
        return _anchored(KIND_INDEX, _str(payload, "command_id"))
    if kind in _SESSION_KINDS:
        # Anchored on the state being entered, which is what the span *is*.
        return _anchored(
            KIND_SESSION, _str(payload, "to_state") or _str(payload, "state")
        )
    if kind == kinds.SYSTEM_EOD:
        return (KIND_SESSION, CURRENT)
    if fact.family in (kinds.FAMILY_CIRCUIT_BREAKER, kinds.FAMILY_AUCTION):
        return _anchored(KIND_MARKET_PHASE, fact.symbol)
    if kind in _GATEWAY_KINDS:
        return _anchored(KIND_GATEWAY, _str(payload, "gateway_id") or fact.actor)
    if kind in (kinds.STARTUP_RECOVERY, kinds.RECOVERY_ITEM):
        run_seq = _int(payload, "run_seq")
        return (KIND_RECOVERY, str(run_seq) if run_seq is not None else CURRENT)
    if fact.family in (kinds.FAMILY_RISK, kinds.FAMILY_ADMIN):
        return _anchored(KIND_COMMAND, _str(payload, "command_id"))
    return None


#: ``system.eod`` and an un-numbered recovery line name no span of their own.
#: :func:`claim` is a pure function of one fact and cannot know which span is
#: open, so it returns this and the assembler substitutes the open episode's
#: anchor -- or leaves it standing, when there is no open span to join.
CURRENT = "current"

_ORDER_KINDS = frozenset(
    {
        kinds.ORDER_ACK,
        kinds.ORDER_FILL,
        kinds.ORDER_CANCEL,
        kinds.ORDER_CANCELLED,
        kinds.ORDER_AMEND,
        kinds.ORDER_AMENDED,
        kinds.ORDER_EXPIRED,
    }
)
_QUOTE_KINDS = frozenset(
    {kinds.QUOTE_NEW, kinds.QUOTE_CANCEL, kinds.QUOTE_ACK, kinds.QUOTE_STATUS}
)
_OCO_KINDS = frozenset(
    {
        kinds.ORDER_OCO,
        kinds.ORDER_OCO_CANCEL,
        kinds.OCO_ACK,
        kinds.OCO_CANCELLED,
    }
)
_COMBO_KINDS = frozenset(
    {
        kinds.ORDER_COMBO,
        kinds.ORDER_COMBO_CANCEL,
        kinds.COMBO_ACK,
        kinds.COMBO_STATUS,
    }
)
_INDEX_KINDS = frozenset(
    {
        kinds.INDEX_CORP_ACTION,
        kinds.INDEX_CONSTITUENT_CHANGE,
        kinds.INDEX_REBALANCE,
        kinds.INDEX_CORP_ACTION_ACK,
        kinds.INDEX_CONSTITUENT_CHANGE_ACK,
        kinds.INDEX_REBALANCE_ACK,
    }
)
_SESSION_KINDS = frozenset(
    {kinds.SESSION_TRANSITION, kinds.SESSION_TRANSITION_ACK, kinds.SESSION_STATE}
)
_GATEWAY_KINDS = frozenset(
    {
        kinds.GATEWAY_CONNECT,
        kinds.GATEWAY_AUTH,
        kinds.GATEWAY_DISCONNECT,
        kinds.GATEWAY_BYE,
    }
)


def _anchored(kind: str, anchor: str | None) -> tuple[str, str] | None:
    return (kind, anchor) if anchor else None


# ---------------------------------------------------------------------------
# The assembler
# ---------------------------------------------------------------------------


class EpisodeAssembler:
    """Facts in, episodes out, bounded (design sections 7.1, 7.3).

    :meth:`feed` yields the episodes that have *retired* -- closed, and far
    enough behind that nothing can still join them. Section 7.1's rule, and
    the reason the tool can read a log larger than memory: an episode is only
    held while a later fact might still belong to it.

    The reorder window sets "far enough": the same two bounds the ordering
    pass uses, because they measure the same thing. A fact that arrives after
    its window has closed is tagged ``late`` and emitted where it landed, so
    an episode that has fallen out of the window cannot legitimately grow.

    :meth:`drain` ends the window. Everything still open comes out with
    ``outcome = OPEN`` rather than being truncated -- section 7.3 calls
    silently truncating them the single most misleading thing a replay tool
    can do.
    """

    def __init__(
        self,
        state: StateModel,
        links: LinkResolver | None = None,
        *,
        max_facts: int = DEFAULT_MAX_FACTS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
    ) -> None:
        self.state = state
        #: Optional only so a test can assemble without one. The pipeline
        #: always passes it: without it the resolver's message index keeps an
        #: entry per line and the tool cannot read a log larger than memory.
        self.links = links
        self.max_facts = max_facts
        self.max_seconds = max_seconds
        self._next_id = 1
        self._facts_seen = 0
        #: The one open episode per ``(kind, anchor)``. Closing removes the
        #: entry, so a second halt on one symbol opens a second episode rather
        #: than reviving the first.
        self._open: dict[tuple[str, str], Episode] = {}
        #: Closed but still reachable, oldest first: ``(facts_seen, ts, ep)``.
        self._closing: list[tuple[int, datetime, Episode]] = []

    # -- feeding ------------------------------------------------------------

    def feed(self, step: Step) -> Iterator[Episode]:
        fact = step.fact
        self._facts_seen += 1
        claimed = claim(fact)
        if claimed is None:
            self._single(KIND_ORPHAN, _orphan_key(fact), step)
            yield from self._retire(fact.receipt_ts)
            return

        kind, anchor = claimed
        if anchor == CURRENT:
            anchor = self._current(kind)
        if kind == KIND_TRADE:
            self._single(KIND_TRADE, anchor, step, OUTCOME_ACCEPTED)
            yield from self._retire(fact.receipt_ts)
            return

        if kind == KIND_SESSION:
            self._close_superseded_session(anchor, fact)
        elif kind == KIND_OCO and fact.kind == kinds.OCO_CANCELLED:
            self._close_oco_sibling(fact)

        episode = self._open.get((kind, anchor))
        if episode is None:
            episode = Episode(episode_id=self._take_id(), kind=kind, anchor_key=anchor)
            self._open[(kind, anchor)] = episode
            role = ROLE_OPEN
        else:
            role = ROLE_PROGRESS

        outcome = self._closing_outcome(kind, fact)
        if outcome is not None and role != ROLE_OPEN:
            # An episode's first event is always ``open``, even when it also
            # ends it: ``events[0].role == ROLE_OPEN`` is an invariant the
            # narrator and the index both lean on, and one line that both
            # opened and closed a happening is better described by
            # ``closed=True`` than by losing the opening.
            role = ROLE_CLOSE
        episode.events.append(
            EpisodeEvent(step=step, seq_in_ep=len(episode.events), role=role)
        )
        if outcome is not None:
            self._close(episode, outcome, fact.receipt_ts, sort_key(fact))
        yield from self._retire(fact.receipt_ts)

    def drain(self) -> Iterator[Episode]:
        """End the window: everything still held, open episodes marked OPEN."""
        for _seen, _ts, episode in self._closing:
            yield episode
        self._closing.clear()
        for episode in self._open.values():
            episode.outcome = self._open_outcome(episode)
            yield episode
        self._open.clear()

    # -- closing ------------------------------------------------------------

    def _closing_outcome(self, kind: str, fact: Fact) -> str | None:
        """The outcome this fact ends its episode with, or None if it does not."""
        if kind == KIND_ORDER:
            order_id = _str(fact.payload, "order_id") or _str(fact.payload, "id")
            order = self.state.orders.get(order_id) if order_id else None
            # Read off the state model rather than re-derived: the model has
            # already applied this fact and already owns what "terminal" means.
            return order.status if order is not None and order.terminal else None

        if fact.payload.get("accepted") is False:
            return OUTCOME_DENIED

        if kind in (KIND_QUOTE, KIND_COMBO):
            return _TERMINAL_STATUS.get(_str(fact.payload, "status") or "")
        if kind == KIND_OCO:
            return OUTCOME_CANCELLED if fact.kind == kinds.OCO_CANCELLED else None
        if kind in (KIND_COMMAND, KIND_INDEX, KIND_SESSION):
            return OUTCOME_ACCEPTED if fact.kind.endswith(_ACK_SUFFIX) else None
        if kind == KIND_MARKET_PHASE:
            return self._phase_outcome(fact)
        if kind == KIND_GATEWAY:
            return (
                OUTCOME_ACCEPTED
                if fact.kind in (kinds.GATEWAY_DISCONNECT, kinds.GATEWAY_BYE)
                else None
            )
        if kind == KIND_RECOVERY:
            # The items come first and the summary last (engine/main.py), so
            # the summary is what concludes the restore.
            return OUTCOME_ACCEPTED if fact.kind == kinds.STARTUP_RECOVERY else None
        return None

    def _phase_outcome(self, fact: Fact) -> str | None:
        """A halt ends on its resume; an auction ends on its result.

        An auction held *inside* a halt is part of that halt's span -- it is
        how a halted symbol reopens -- so its result does not end the episode
        while the symbol is still halted. The state model has already applied
        this fact, so ``halted`` is the truth at this moment.
        """
        if fact.kind == kinds.CIRCUIT_BREAKER_RESUME:
            return OUTCOME_ACCEPTED
        if fact.kind == kinds.AUCTION_RESULT and fact.symbol:
            symbol = self.state.symbols.get(fact.symbol)
            if symbol is None or not symbol.halted:
                return OUTCOME_ACCEPTED
        return None

    def _current(self, kind: str) -> str:
        """The open span of *kind* for a fact that names none of its own.

        ``system.eod`` belongs to the session it ends, not to a session of its
        own; a recovery line with no ``run_seq`` belongs to the restore it is
        part of. Falls back to :data:`CURRENT` when nothing of that kind is
        open, which is a one-fact episode saying exactly that -- better than
        attaching it to a span the window never saw.
        """
        for open_kind, open_anchor in self._open:
            if open_kind == kind:
                return open_anchor
        return CURRENT

    def _close_oco_sibling(self, fact: Fact) -> None:
        """End the leg episode that ``oco.cancelled`` names.

        The second place a fact ends an episode it does not belong to. The
        engine publishes no ``order.cancelled`` for an OCO sibling, so without
        this the leg's episode would report OPEN for an order the trail plainly
        says was cancelled -- the failure section 7.3 calls the most misleading
        thing this tool could do.
        """
        order_id = _str(fact.payload, "cancelled_order_id")
        episode = self._open.get((KIND_ORDER, order_id)) if order_id else None
        if episode is not None:
            self._close(episode, OUTCOME_CANCELLED, fact.receipt_ts, sort_key(fact))

    def _close_superseded_session(self, anchor: str, fact: Fact) -> None:
        """A session span ends when the market enters a different state.

        The fact that ends it belongs to the *next* span -- it is what opens
        it -- so this episode closes with no ``close``-role event of its own
        and takes its ``closed_ts`` from that fact. Every other kind is ended
        by a fact it contains; this one is not, and pretending otherwise would
        put one line in two episodes.
        """
        if anchor == CURRENT:
            return
        for key, episode in list(self._open.items()):
            if key[0] == KIND_SESSION and key[1] != anchor:
                self._close(episode, OUTCOME_ACCEPTED, fact.receipt_ts, sort_key(fact))

    def _close(
        self, episode: Episode, outcome: str, when: datetime, key: SortKey
    ) -> None:
        episode.closed = True
        episode.outcome = outcome
        episode.closed_ts = when
        episode.closed_sort_key = key
        self._open.pop((episode.kind, episode.anchor_key), None)
        self._closing.append((self._facts_seen, when, episode))

    def _open_outcome(self, episode: Episode) -> str:
        """What to call an episode the window ended on top of.

        PARTIAL rather than OPEN for an order that filled some: "still
        working, 50 of 200 remaining at end of window" is the sentence section
        7.3 asks for, and OPEN alone does not carry it.
        """
        if episode.kind == KIND_ORDER:
            order = self.state.orders.get(episode.anchor_key)
            if order is not None and order.filled_qty > 0:
                return OUTCOME_PARTIAL
        return OUTCOME_OPEN

    # -- retirement (section 7.1) -------------------------------------------

    def _retire(self, now: datetime) -> Iterator[Episode]:
        """Release every closed episode the reorder window has moved past.

        Retiring the episode retires everything held on its behalf -- the order
        state, and the resolver's index of its messages. That is the half of
        section 7.1 phase 2 deferred, and it is what makes the memory flat on
        a log of any length.
        """
        while self._closing:
            seen, closed_ts, episode = self._closing[0]
            behind = self._facts_seen - seen
            elapsed = (now - closed_ts).total_seconds()
            if behind <= self.max_facts and elapsed <= self.max_seconds:
                return
            self._closing.pop(0)
            if episode.kind == KIND_ORDER:
                self.state.retire_order(episode.anchor_key)
            if self.links is not None:
                for event in episode.events:
                    self.links.forget(event.fact)
            yield episode

    def _take_id(self) -> int:
        episode_id = self._next_id
        self._next_id += 1
        return episode_id

    def _single(
        self, kind: str, anchor: str, step: Step, outcome: str = OUTCOME_UNKNOWN
    ) -> None:
        """An episode that is one fact and is over the moment it opens.

        Closed on arrival, but aged out through :meth:`_retire` like every
        other episode rather than released on the spot. Retiring frees the
        resolver's record of the fact, and a trade's ``msg_id`` is what the
        fills it caused name as their ``causation_id`` -- releasing the trade
        immediately would make the fill arriving a line later cite a cause the
        tool had just thrown away.
        """
        fact = step.fact
        episode = Episode(
            episode_id=self._take_id(),
            kind=kind,
            anchor_key=anchor,
            events=[EpisodeEvent(step=step, seq_in_ep=0, role=ROLE_OPEN)],
            outcome=outcome,
            closed=True,
            closed_ts=fact.receipt_ts,
            closed_sort_key=sort_key(fact),
        )
        self._closing.append((self._facts_seen, fact.receipt_ts, episode))


def _orphan_key(fact: Fact) -> str:
    """An orphan is anchored on the line it is, because it joins nothing."""
    return fact.msg_id or f"@{fact.ordinal}"


def assemble(
    steps: Iterable[Step],
    state: StateModel,
    links: LinkResolver | None = None,
    *,
    max_facts: int = DEFAULT_MAX_FACTS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> Iterator[Episode]:
    """Drive an :class:`EpisodeAssembler` over a whole stream.

    Episodes come out as they retire, which is *not* the order they opened in
    -- a long-running order outlives the trades that happened during it. The
    index sorts on ``opened_sort_key``; a caller that needs chronological
    order in memory has to sort.
    """
    assembler = EpisodeAssembler(
        state, links, max_facts=max_facts, max_seconds=max_seconds
    )
    for step in steps:
        yield from assembler.feed(step)
    yield from assembler.drain()
