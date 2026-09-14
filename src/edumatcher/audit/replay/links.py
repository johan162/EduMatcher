"""Who caused what, and how sure the tool is (sections 5.1, 7.2).

Since the envelope landed, most links are **read** rather than inferred: an
effect's ``causation_id`` names its cause's ``msg_id``, and that is one lookup.
Since the command echo landed, the inbound commands are in the trail too, so
the causes those ids name are usually present. What keeps the inference
machinery below alive is the rest of the world: archived lines recorded before
the envelope existed, and publishers outside the engine -- ``pm-index``,
``pm-stats``, the gateways' own emissions -- which are not behind a
``CausalPublisher`` and carry none.

So the resolver reads the envelope when it is there and falls back when it is
not, and attaches an explicit :class:`Confidence` either way. That label is
the load-bearing part. A link the tool guessed and a link the publisher stated
render as different sentences, and a regression that silently promoted one to
the other would make the tool lie with a straight face -- which is why the
tests assert confidence at least as hard as they assert the link.

**The two kinds of "no cause" are kept apart.** A message whose envelope says
``causation_id`` is null was *declared* uncaused -- a scheduler tick, a
circuit-breaker trip, an end-of-day sweep -- and is an origin. A message with
no envelope at all has an *unknown* cause. Collapsing them would be the same
error twice over: inventing causes for scheduler ticks, and presenting
unknowns as origins.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping

from edumatcher.audit.replay.anomalies import (
    CAUSE_NOT_FOUND,
    CHAIN_BROKEN,
    ENVELOPE_MISSING,
    MSG_ID_DUPLICATE,
    ORPHAN_EVENT,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EFFECT_COUNT_MISMATCH,
    Anomaly,
)
from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.replay.state import StateModel


class Confidence(str, Enum):
    """How the link was arrived at (section 5.1), worst case last.

    Ordered so a report can sort by it and a threshold can be a comparison.
    ``RECORDED`` is not an inference at all -- the publisher stated it -- and
    is the only level ``--strict-causality`` accepts.
    """

    RECORDED = "RECORDED"
    CERTAIN = "CERTAIN"
    STRONG = "STRONG"
    HEURISTIC = "HEURISTIC"
    NONE = "NONE"


#: Report order, strongest first. An Enum is not ordered and giving it a
#: comparison operator to serve one report would be the wrong kind of clever.
CONFIDENCE_ORDER: tuple[Confidence, ...] = (
    Confidence.RECORDED,
    Confidence.CERTAIN,
    Confidence.STRONG,
    Confidence.HEURISTIC,
    Confidence.NONE,
)

#: Relations, as section 6.2's ``links`` table names them.
CAUSED = "caused"
MATCHED_WITH = "matched_with"
LEG_OF = "leg_of"
CANCELLED_BY = "cancelled_by"
REJECTED_BECAUSE = "rejected_because"

#: A reference to something that is not a fact: a named condition rather than a
#: message. ``order.cancelled.cancel_reason`` names its cause directly --
#: SELF_MATCH_PREVENTED is a thing that happened, not a thing that was
#: published -- so the link points at the condition, namespaced so a reader and
#: phase 3 can tell the two apart at a glance.
CONDITION_PREFIX = "condition:"


@dataclass(frozen=True, slots=True)
class Link:
    """One directed edge: *target* happened because of *source*.

    Both ends are :func:`ref` strings rather than Facts, so a Link can be
    stored, compared and counted without dragging a payload along, and so a
    source that is a condition rather than a message can be expressed at all.
    """

    source: str
    target: str
    relation: str
    confidence: Confidence
    evidence: str


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the resolver made of one Fact."""

    ref: str
    #: The publisher stated that nothing on the bus caused this. Not the same
    #: as "no cause was found", and never rendered as one.
    origin: bool
    #: Whether the fact carried an envelope at all. The third state, between
    #: an origin and an orphan: a fact that *names* its cause, where the cause
    #: is simply outside the window.
    enveloped: bool
    links: tuple[Link, ...]
    anomalies: tuple[Anomaly, ...]

    @property
    def orphan(self) -> bool:
        """No envelope, nothing attached, and nothing declared it unattached.

        Any incoming link counts, not only a cause: a fill joined to its trade
        has been explained even if no rule found what caused it, and calling
        that an orphan would overstate what the tool failed to do.

        An enveloped fact whose stated cause is outside the window is **not**
        an orphan. It is not unexplained -- the publisher said what caused it,
        and the window is what is short. ``CAUSE_NOT_FOUND`` reports that, once;
        counting it here as well would report one gap twice and under two
        different names.
        """
        return (
            not self.origin
            and not self.enveloped
            and not any(link.target == self.ref for link in self.links)
        )


def ref(fact: Fact) -> str:
    """A stable handle for one fact.

    The ``msg_id`` when there is one, because that is what every other message
    refers to it by. Otherwise the stream ordinal, which is unique within a
    run and prefixed so it can never be mistaken for a ULID.
    """
    return fact.msg_id or f"@{fact.ordinal}"


def _str(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _str_list(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------

#: Kinds whose ``command_id`` identifies a request the engine will ack. Read
#: off the registry rather than listed, so a new risk command is covered the
#: day it is specified.
_ACK_SUFFIX = "_ack"


class LinkResolver:
    """Four tiers, cheapest and most certain first (section 7.2).

    Fed Facts in canonical order, one at a time, and looking only backwards:
    a cause always precedes its effect, because both orders agree. The
    envelope's ULID is minted before the effects it triggers, and the engine
    echoes an inbound command *before* dispatching it -- so the command's line
    is earlier in the file as well as earlier by id. A single forward pass is
    therefore enough, and a ``causation_id`` with nothing behind it is a real
    finding rather than an artefact of reading order.

    The tiers resolve the **cause** of a fact. Structural links -- a leg to its
    parent, a fill to its trade, a rejection to the market condition behind it
    -- are not causes and are resolved separately, on every fact, envelope or
    not. Section 5.1.2 makes the same distinction for the acks: their counts
    are a completeness cross-check, not the link.
    """

    def __init__(self, state: StateModel | None = None) -> None:
        #: The model is optional because most rules do not need it; only the
        #: reject-code explanation does, and a caller that does not keep one
        #: gets everything else.
        self.state = state
        self._by_msg: dict[str, str] = {}
        self._chain_of: dict[str, str | None] = {}
        self._order_origin: dict[str, str] = {}
        self._trade: dict[str, str] = {}
        self._command: dict[str, str] = {}
        self._quote: dict[str, str] = {}
        self._oco: dict[str, str] = {}
        self._combo: dict[str, str] = {}
        #: Requests awaiting their effect, newest last. A list rather than a
        #: single entry because two cancels for one order can be in flight,
        #: which is precisely the case that must not resolve confidently.
        self._cancel_requests: dict[str, list[tuple[str, str | None]]] = {}
        self._amend_requests: dict[str, list[tuple[str, str | None]]] = {}
        self._transitions: list[tuple[str, str]] = []
        self._halt_open: dict[str, str] = {}
        #: command_id -> the order ids observed cancelled under it, for the
        #: reconciliation in section 5.1.2.
        self._command_effects: dict[str, set[str]] = {}

    # -- entry point --------------------------------------------------------

    def feed(self, fact: Fact) -> Resolution:
        this = ref(fact)
        found: list[Anomaly] = []
        links: list[Link] = []

        self._register(fact, this, found)
        cause = self._resolve_cause(fact, this, found)
        if cause is not None:
            links.append(cause)
        links.extend(self._structural(fact, this, found))
        self._retire(fact)

        resolution = Resolution(
            ref=this,
            origin=fact.has_envelope and fact.causation_id is None,
            enveloped=fact.has_envelope,
            links=tuple(links),
            anomalies=tuple(found),
        )
        if not resolution.orphan:
            return resolution
        # Reported through the same predicate the report counts, so the two
        # can never disagree about what the tool failed to explain.
        return replace(
            resolution,
            anomalies=resolution.anomalies
            + (
                _anomaly(
                    ORPHAN_EVENT,
                    SEVERITY_INFO,
                    f"{fact.kind} carries no envelope and nothing attached to it",
                    fact,
                ),
            ),
        )

    # -- tier 0: the envelope -----------------------------------------------

    def _resolve_cause(
        self, fact: Fact, this: str, found: list[Anomaly]
    ) -> Link | None:
        if fact.causation_id is not None:
            source = self._by_msg.get(fact.causation_id)
            if source is None:
                found.append(
                    _anomaly(
                        CAUSE_NOT_FOUND,
                        SEVERITY_WARN,
                        f"{fact.kind} cites cause {fact.causation_id}, "
                        f"which is not in the window",
                        fact,
                    )
                )
                return None
            expected = self._chain_of.get(fact.causation_id)
            if expected is not None and fact.correlation_id != expected:
                found.append(
                    _anomaly(
                        CHAIN_BROKEN,
                        SEVERITY_ERROR,
                        f"{fact.kind} is in chain {fact.correlation_id} but its "
                        f"cause is in {expected}",
                        fact,
                    )
                )
            return Link(
                source=source,
                target=this,
                relation=CAUSED,
                confidence=Confidence.RECORDED,
                evidence="causation_id",
            )
        if fact.has_envelope:
            # Declared origin. Section 7.2: stop here. Falling through would
            # invent a cause for every scheduler tick and breaker trip, and
            # those inventions would read exactly like facts.
            return None
        return self._fallback(fact, this, found)

    # -- tiers 1-3: for facts with no envelope at all ------------------------

    def _fallback(self, fact: Fact, this: str, found: list[Anomaly]) -> Link | None:
        payload = fact.payload
        kind = fact.kind

        if kind in (kinds.ORDER_ACK, kinds.ORDER_FILL):
            order_id = _str(payload, "order_id")
            source = self._order_origin.get(order_id) if order_id else None
            if source:
                return _link(source, this, CAUSED, Confidence.CERTAIN, "order_id")
            return None

        if kind == kinds.ORDER_CANCELLED:
            return self._cancel_cause(fact, this)

        if kind == kinds.ORDER_AMENDED:
            return self._request_cause(
                fact, this, self._amend_requests, kinds.ORDER_AMEND
            )

        if kind == kinds.QUOTE_ACK:
            quote_id = _str(payload, "quote_id")
            source = self._quote.get(quote_id) if quote_id else None
            if source:
                return _link(source, this, CAUSED, Confidence.CERTAIN, "quote_id")
            return None

        if kind in (kinds.OCO_ACK, kinds.OCO_CANCELLED):
            oco_id = _str(payload, "oco_id")
            source = self._oco.get(oco_id) if oco_id else None
            if source:
                return _link(source, this, CAUSED, Confidence.CERTAIN, "oco_id")
            return None

        if kind.endswith(_ACK_SUFFIX):
            command_id = _str(payload, "command_id")
            source = self._command.get(command_id) if command_id else None
            if source:
                return _link(source, this, CAUSED, Confidence.CERTAIN, "command_id")
            return None

        # -- tier 2: a constrained candidate search --------------------------

        if kind == kinds.SESSION_STATE:
            return self._session_cause(fact, this)

        if kind == kinds.CIRCUIT_BREAKER_RESUME and fact.symbol:
            source = self._halt_open.get(fact.symbol)
            if source:
                return _link(
                    source, this, CAUSED, Confidence.STRONG, "open halt for symbol"
                )
            return None

        return None

    def _cancel_cause(self, fact: Fact, this: str) -> Link | None:
        """``order.cancelled`` has three ladders, in decreasing certainty.

        A ``command_id`` names the admin or risk command that ordered it --
        exact, and the reason the kill-switch join is not a guess. A
        ``request_tag`` names the client's own cancel. The third rung, the
        ``cancel_reason``, is in :meth:`_structural` instead: the condition it
        names is not a message, so the envelope never covers it and it is
        worth recording on an enveloped cancel too.
        """
        command_id = _str(fact.payload, "command_id")
        if command_id:
            source = self._command.get(command_id)
            if source:
                return _link(
                    source,
                    this,
                    CANCELLED_BY,
                    Confidence.CERTAIN,
                    f"command_id={command_id}",
                )
        return self._request_cause(
            fact, this, self._cancel_requests, kinds.ORDER_CANCEL
        )

    def _request_cause(
        self,
        fact: Fact,
        this: str,
        pending: dict[str, list[tuple[str, str | None]]],
        request_kind: str,
    ) -> Link | None:
        """Match an effect to the request that asked for it.

        ``request_tag`` is the client's own correlation and is exact. Without
        one there is only the order id and the ordering, which is enough when
        a single request is in flight and is **not** enough when two are: two
        cancels for one order with no tag is the ambiguous case, and it has to
        degrade to HEURISTIC rather than pick the earlier one and sound sure.
        """
        order_id = _str(fact.payload, "order_id")
        if not order_id:
            return None
        waiting = pending.get(order_id)
        if not waiting:
            return None
        tag = _str(fact.payload, "request_tag")
        if tag:
            for index, (source, request_tag) in enumerate(waiting):
                if request_tag == tag:
                    waiting.pop(index)
                    return _link(
                        source, this, CAUSED, Confidence.CERTAIN, f"request_tag={tag}"
                    )
        source, _tag = waiting.pop(0)
        if len(waiting) > 0:
            return _link(
                source,
                this,
                CAUSED,
                Confidence.HEURISTIC,
                f"{len(waiting) + 1} {request_kind} in flight for one order, "
                f"earliest chosen",
            )
        return _link(
            source,
            this,
            CAUSED,
            Confidence.STRONG,
            f"order_id + earliest {request_kind}",
        )

    def _session_cause(self, fact: Fact, this: str) -> Link | None:
        state_name = _str(fact.payload, "state")
        if not state_name:
            return None
        for index in range(len(self._transitions) - 1, -1, -1):
            to_state, source = self._transitions[index]
            if to_state == state_name:
                del self._transitions[index]
                return _link(
                    source,
                    this,
                    CAUSED,
                    Confidence.STRONG,
                    f"first session.state matching to_state={state_name}",
                )
        return None

    # -- structural links, resolved on every fact ---------------------------

    def _structural(self, fact: Fact, this: str, found: list[Anomaly]) -> list[Link]:
        """Relations that are not causes, so the envelope does not settle them.

        Parentage (a quote leg, an OCO leg, a combo leg), the join from a fill
        to its trade, and the market condition a rejection names. All three are
        carried explicitly by the messages, so all three are CERTAIN or
        STRONG -- and none of them is what ``causation_id`` records, which
        answers *which message* triggered this one, not *what this one is part
        of*.
        """
        links: list[Link] = []
        payload = fact.payload
        kind = fact.kind

        if kind == kinds.ORDER_FILL:
            for trade_id in _str_list(payload, "trade_ids"):
                source = self._trade.get(trade_id)
                if source:
                    links.append(
                        _link(
                            source,
                            this,
                            MATCHED_WITH,
                            Confidence.CERTAIN,
                            f"trade_ids contains {trade_id}",
                        )
                    )

        if kind == kinds.TRADE_EXECUTED:
            for field_name in ("buy_order_id", "sell_order_id"):
                order_id = _str(payload, field_name)
                source = self._order_origin.get(order_id) if order_id else None
                if source:
                    links.append(
                        _link(
                            source, this, MATCHED_WITH, Confidence.CERTAIN, field_name
                        )
                    )

        if kind == kinds.ORDER_NEW:
            links.extend(self._parentage(fact, this))

        if kind == kinds.ORDER_CANCELLED:
            reason = _str(payload, "cancel_reason")
            if reason:
                links.append(
                    _link(
                        f"{CONDITION_PREFIX}{reason}",
                        this,
                        CANCELLED_BY,
                        Confidence.CERTAIN,
                        "cancel_reason",
                    )
                )

        if kind == kinds.ORDER_ACK and payload.get("accepted") is False:
            explanation = self._explain_rejection(fact, this)
            if explanation is not None:
                links.append(explanation)

        if kind.endswith(_ACK_SUFFIX):
            found.extend(self._reconcile(fact))

        return links

    def _parentage(self, fact: Fact, this: str) -> list[Link]:
        links: list[Link] = []
        for field_name, index in (
            ("quote_id", self._quote),
            ("oco_group_id", self._oco),
            ("combo_parent_id", self._combo),
        ):
            value = _str(fact.payload, field_name)
            source = index.get(value) if value else None
            if source:
                links.append(
                    _link(source, this, LEG_OF, Confidence.CERTAIN, field_name)
                )
        return links

    def _explain_rejection(self, fact: Fact, this: str) -> Link | None:
        """Point a market-condition rejection at the event that made it true.

        This is the whole reason the market model exists. ``reject_code`` on
        its own says an order was refused; with the halt that is in force for
        that symbol beside it, the tool can say since when, by whom, and
        through which corridor -- and can quote the original
        ``circuit_breaker.halt`` rather than paraphrasing it.
        """
        if self.state is None or not fact.symbol:
            return None
        code = _str(fact.payload, "reject_code")
        if code not in ("CIRCUIT_BREAKER_ACTIVE", "INSTRUMENT_HALTED"):
            return None
        source = self._halt_open.get(fact.symbol)
        if source is None:
            return None
        symbol_state = self.state.symbols.get(fact.symbol)
        detail = symbol_state.describe_halt() if symbol_state else "halted"
        return _link(source, this, REJECTED_BECAUSE, Confidence.STRONG, detail)

    def _reconcile(self, fact: Fact) -> list[Anomaly]:
        """Check an ack's list of effects against the effects observed.

        Section 5.1.2 described this as a count comparison, because a count was
        all the ack carried. AR-0.5 changed that: the acks now name the ids, so
        the check can say *which* cancellation is missing rather than only that
        one is. Disagreement means a dropped message, and naming the order is
        the difference between a finding a reader can chase and a number they
        cannot.
        """
        command_id = _str(fact.payload, "command_id")
        if not command_id:
            return []
        claimed = set(_str_list(fact.payload, "cancelled_order_ids")) | set(
            _str_list(fact.payload, "cancelled_quote_order_ids")
        )
        if not claimed:
            return []
        observed = self._command_effects.get(command_id, set())
        missing = sorted(claimed - observed)
        if not missing:
            return []
        shown = ", ".join(missing[:5])
        if len(missing) > 5:
            shown += f", and {len(missing) - 5} more"
        return [
            _anomaly(
                EFFECT_COUNT_MISMATCH,
                SEVERITY_WARN,
                f"{fact.kind} for command {command_id} names {len(claimed)} "
                f"cancelled order(s); {len(missing)} were not observed: {shown}",
                fact,
            )
        ]

    # -- the indexes --------------------------------------------------------

    def _register(self, fact: Fact, this: str, found: list[Anomaly]) -> None:
        """Record what later facts will look this one up by.

        Runs before resolution, not after: a message is never its own cause,
        and registering first keeps the two halves from having to be ordered
        against each other at every call site.
        """
        if fact.msg_id is not None:
            if fact.msg_id in self._by_msg:
                found.append(
                    _anomaly(
                        MSG_ID_DUPLICATE,
                        SEVERITY_ERROR,
                        f"msg_id {fact.msg_id} was already seen in this window",
                        fact,
                    )
                )
            self._by_msg[fact.msg_id] = this
            self._chain_of[fact.msg_id] = fact.correlation_id
        elif fact.known and "engine_pub" in _transport(fact):
            found.append(
                _anomaly(
                    ENVELOPE_MISSING,
                    SEVERITY_INFO,
                    f"{fact.kind} was published by the engine with no envelope",
                    fact,
                )
            )

        payload = fact.payload
        kind = fact.kind

        if kind == kinds.ORDER_NEW:
            order_id = _str(payload, "id")
            if order_id:
                self._order_origin.setdefault(order_id, this)
        elif kind in (kinds.ORDER_ACK, kinds.ORDER_FILL):
            order_id = _str(payload, "order_id")
            if order_id:
                # An archived log may have no order.new; the ack is then the
                # earliest thing that names the order, and is a better anchor
                # than nothing.
                self._order_origin.setdefault(order_id, this)
        elif kind == kinds.TRADE_EXECUTED:
            trade_id = _str(payload, "id")
            if trade_id:
                self._trade[trade_id] = this
        elif kind == kinds.QUOTE_NEW:
            quote_id = _str(payload, "quote_id")
            if quote_id:
                self._quote[quote_id] = this
        elif kind == kinds.ORDER_OCO:
            oco_id = _str(payload, "oco_id")
            if oco_id:
                self._oco[oco_id] = this
        elif kind == kinds.ORDER_COMBO:
            combo_id = _str(payload, "combo_id")
            if combo_id:
                self._combo[combo_id] = this
        elif kind == kinds.ORDER_CANCEL:
            order_id = _str(payload, "order_id")
            if order_id:
                self._cancel_requests.setdefault(order_id, []).append(
                    (this, _str(payload, "request_tag"))
                )
        elif kind == kinds.ORDER_AMEND:
            order_id = _str(payload, "order_id")
            if order_id:
                self._amend_requests.setdefault(order_id, []).append(
                    (this, _str(payload, "request_tag"))
                )
        elif kind == kinds.SESSION_TRANSITION:
            to_state = _str(payload, "to_state")
            if to_state:
                self._transitions.append((to_state, this))
        elif kind == kinds.CIRCUIT_BREAKER_HALT and fact.symbol:
            self._halt_open[fact.symbol] = this
        elif kind == kinds.ORDER_CANCELLED:
            command_id = _str(payload, "command_id")
            order_id = _str(payload, "order_id")
            if command_id and order_id:
                self._command_effects.setdefault(command_id, set()).add(order_id)

        command_id = _str(payload, "command_id")
        if (
            command_id
            and not kind.endswith(_ACK_SUFFIX)
            and kind != kinds.ORDER_CANCELLED
        ):
            self._command.setdefault(command_id, this)

    def _retire(self, fact: Fact) -> None:
        """Close out what this fact ends, *after* it has been resolved.

        Registration only ever adds. A resume closes the halt it names, and
        clearing that while registering would take the halt away before the
        resume had a chance to link to it -- the bug this split exists to
        prevent.
        """
        if fact.kind == kinds.CIRCUIT_BREAKER_RESUME and fact.symbol:
            self._halt_open.pop(fact.symbol, None)


def _transport(fact: Fact) -> tuple[str, ...]:
    from edumatcher.audit.query import lookup_topic

    spec = lookup_topic(fact.topic)
    return tuple(spec["transport"]) if spec else ()


def _link(
    source: str, target: str, relation: str, confidence: Confidence, evidence: str
) -> Link:
    return Link(
        source=source,
        target=target,
        relation=relation,
        confidence=confidence,
        evidence=evidence,
    )


def _anomaly(code: str, severity: str, detail: str, fact: Fact) -> Anomaly:
    return Anomaly(
        code=code,
        severity=severity,
        detail=detail,
        receipt_ts=fact.receipt_raw,
        file=fact.file,
        line_no=fact.line_no,
    )
