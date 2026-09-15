"""The link resolver (tasks AR-2.3, AR-2.4).

The confidence assertions matter more than the link assertions, and every test
below makes both. A regression that silently promoted a guess to RECORDED or
CERTAIN would make the tool assert something it inferred, in prose, with no
hedge -- and nothing else in the suite would catch it.

One trap gets a section of its own: a **declared origin** -- envelope present,
``causation_id`` null -- must not fall through to the inference tiers. If it
does, the tool invents a cause for every scheduler tick and circuit-breaker
trip, and those inventions read exactly like facts.
"""

from __future__ import annotations

from typing import Any, Iterable

import pytest

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.anomalies import (
    CAUSE_NOT_FOUND,
    CHAIN_BROKEN,
    EFFECT_COUNT_MISMATCH,
    ENVELOPE_MISSING,
    MSG_ID_DUPLICATE,
    ORPHAN_EVENT,
)
from edumatcher.audit.replay.facts import to_fact
from edumatcher.audit.replay.links import (
    CANCELLED_BY,
    CAUSED,
    CONDITION_PREFIX,
    LEG_OF,
    MATCHED_WITH,
    REJECTED_BECAUSE,
    Confidence,
    Link,
    LinkResolver,
    Resolution,
    ref,
)
from edumatcher.audit.replay.state import StateModel

_TS = "2026-09-08T09:31:02.118+00:00"
ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"
OTHER = "9ab1c47f2e5d48a1b3c6f9078e2d15b4"
TRADE = "000042-000001873"


class Feeder:
    """Drives a resolver, and a state model beside it, over a script of lines.

    The two are driven together because they are not independent: only the
    market model can explain a rejection, and a resolver built without one
    silently cannot.
    """

    def __init__(self) -> None:
        self.state = StateModel()
        self.resolver = LinkResolver(self.state)
        self._ordinal = 0

    def feed(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        msg: str | None = None,
        cause: str | None = None,
        chain: str | None = None,
    ) -> Resolution:
        meta: dict[str, str] = {}
        if msg:
            meta["msg"] = msg
            meta["chain"] = chain or cause or msg
        if cause:
            meta["cause"] = cause
        entry = AuditEntry(
            _TS, topic, payload, meta, file="audit.log", line_no=self._ordinal + 1
        )
        fact = to_fact(entry, self._ordinal)
        self._ordinal += 1
        self.state.apply(fact)
        return self.resolver.feed(fact)


def codes(resolution: Resolution) -> list[str]:
    return [a.code for a in resolution.anomalies]


def only(links: Iterable[Link], relation: str) -> Link:
    matching = [link for link in links if link.relation == relation]
    assert len(matching) == 1, f"expected one {relation}, got {matching}"
    return matching[0]


# ---------------------------------------------------------------------------
# Tier 0 — the envelope
# ---------------------------------------------------------------------------


class TestTheEnvelopeTier:
    def test_a_causation_id_is_read_not_inferred(self) -> None:
        feeder = Feeder()
        feeder.feed("order.new", {"id": ORDER}, msg="M1")
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
            msg="M2",
            cause="M1",
            chain="M1",
        )
        link = only(resolution.links, CAUSED)
        assert link.source == "M1"
        assert link.confidence is Confidence.RECORDED
        assert link.evidence == "causation_id"

    def test_the_envelope_wins_over_every_fallback(self) -> None:
        """Both rules would fire; the recorded one is the only one that does."""
        feeder = Feeder()
        feeder.feed("order.new", {"id": ORDER}, msg="M1")
        feeder.feed("session.transition", {"to_state": "CONTINUOUS"}, msg="M9")
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
            msg="M2",
            cause="M9",
            chain="M9",
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == ("M9", Confidence.RECORDED)

    def test_a_cause_outside_the_window_is_reported_not_invented(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
            msg="M2",
            cause="GONE",
            chain="GONE",
        )
        assert CAUSE_NOT_FOUND in codes(resolution)
        assert [link for link in resolution.links if link.relation == CAUSED] == []

    def test_a_cause_outside_the_window_is_not_also_an_orphan(self) -> None:
        """One gap, reported once. The publisher said what caused it; the
        window is what is short, and CAUSE_NOT_FOUND is the finding for that."""
        feeder = Feeder()
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
            msg="M2",
            cause="GONE",
            chain="GONE",
        )
        assert resolution.orphan is False
        assert ORPHAN_EVENT not in codes(resolution)

    def test_a_broken_chain_is_an_error(self) -> None:
        """correlation_id is propagated by Envelope.caused(), so a break means
        something built an envelope by hand."""
        feeder = Feeder()
        feeder.feed("order.new", {"id": ORDER}, msg="M1", chain="M1")
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
            msg="M2",
            cause="M1",
            chain="SOMETHING-ELSE",
        )
        assert CHAIN_BROKEN in codes(resolution)
        # Still linked: the chain is broken, the causation is not.
        assert only(resolution.links, CAUSED).confidence is Confidence.RECORDED

    def test_a_repeated_msg_id_is_an_error(self) -> None:
        feeder = Feeder()
        feeder.feed("order.new", {"id": ORDER}, msg="M1")
        assert MSG_ID_DUPLICATE in codes(
            feeder.feed("order.new", {"id": OTHER}, msg="M1")
        )


class TestADeclaredOrigin:
    """Envelope present, ``causation_id`` null. The publisher stated that
    nothing on the bus caused this."""

    def test_it_is_an_origin_rather_than_a_gap(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "circuit_breaker.halt.AAPL",
            {"symbol": "AAPL", "halt_source": "CB"},
            msg="H1",
        )
        assert resolution.origin is True
        assert resolution.orphan is False
        assert ORPHAN_EVENT not in codes(resolution)

    def test_it_does_not_fall_through_to_the_inference_tiers(self) -> None:
        """The trap AR-2.3 names. A cancel request is sitting right there and
        must not be picked up."""
        feeder = Feeder()
        feeder.feed("order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"})
        resolution = feeder.feed(
            "order.cancelled.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "symbol": "AAPL"},
            msg="C1",
        )
        assert resolution.origin is True
        assert [link for link in resolution.links if link.relation == CAUSED] == []

    def test_a_command_the_engine_echoed_is_an_origin(self) -> None:
        """The echo republishes the gateway's own envelope, which names no
        cause -- so a submission is an origin, not an orphan."""
        feeder = Feeder()
        resolution = feeder.feed("order.new", {"id": ORDER}, msg="M1")
        assert (resolution.origin, resolution.orphan) == (True, False)


# ---------------------------------------------------------------------------
# Tier 1 — the CERTAIN rows of section 5.1.1, for envelope-less facts
# ---------------------------------------------------------------------------


class TestTheDirectKeyTier:
    def test_order_new_to_order_ack_on_order_id(self) -> None:
        feeder = Feeder()
        origin = feeder.feed("order.new", {"id": ORDER})
        resolution = feeder.feed(
            "order.ack.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "accepted": True},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence, link.evidence) == (
            origin.ref,
            Confidence.CERTAIN,
            "order_id",
        )

    def test_order_new_to_order_fill_on_order_id(self) -> None:
        feeder = Feeder()
        origin = feeder.feed("order.new", {"id": ORDER})
        resolution = feeder.feed(
            "order.fill.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "fill_qty": 10},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (origin.ref, Confidence.CERTAIN)

    def test_trade_executed_to_order_fill_on_trade_ids(self) -> None:
        """The strongest link in the system: trade_ids is an explicit
        back-reference, carried by the fill itself."""
        feeder = Feeder()
        trade = feeder.feed(
            "trade.executed", {"id": TRADE, "symbol": "AAPL", "run_seq": 42}
        )
        resolution = feeder.feed(
            "order.fill.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "trade_ids": [TRADE]},
        )
        link = only(resolution.links, MATCHED_WITH)
        assert (link.source, link.confidence) == (trade.ref, Confidence.CERTAIN)
        assert TRADE in link.evidence

    def test_trade_executed_to_both_order_episodes(self) -> None:
        feeder = Feeder()
        buy = feeder.feed("order.new", {"id": ORDER})
        sell = feeder.feed("order.new", {"id": OTHER})
        resolution = feeder.feed(
            "trade.executed",
            {
                "id": TRADE,
                "symbol": "AAPL",
                "run_seq": 42,
                "buy_order_id": ORDER,
                "sell_order_id": OTHER,
            },
        )
        matched = [link for link in resolution.links if link.relation == MATCHED_WITH]
        assert {link.source for link in matched} == {buy.ref, sell.ref}
        assert {link.confidence for link in matched} == {Confidence.CERTAIN}

    def test_order_cancel_to_order_cancelled_on_request_tag(self) -> None:
        feeder = Feeder()
        feeder.feed(
            "order.cancel",
            {"order_id": ORDER, "gateway_id": "TRADER01", "request_tag": "OTHER"},
        )
        wanted = feeder.feed(
            "order.cancel",
            {"order_id": ORDER, "gateway_id": "TRADER01", "request_tag": "T-1"},
        )
        resolution = feeder.feed(
            "order.cancelled.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "request_tag": "T-1"},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (wanted.ref, Confidence.CERTAIN)
        assert "request_tag" in link.evidence

    def test_order_amend_to_order_amended_on_request_tag(self) -> None:
        feeder = Feeder()
        amend = feeder.feed(
            "order.amend",
            {"order_id": ORDER, "gateway_id": "TRADER01", "request_tag": "A-1"},
        )
        resolution = feeder.feed(
            "order.amended.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "request_tag": "A-1"},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (amend.ref, Confidence.CERTAIN)

    def test_a_risk_command_to_its_ack_on_command_id(self) -> None:
        feeder = Feeder()
        command = feeder.feed(
            "risk.kill_switch",
            {"gateway_id": "TRADER07", "command_id": "8812", "note": "fat finger"},
        )
        resolution = feeder.feed(
            "risk.kill_switch_ack.RISKDESK",
            {"gateway_id": "RISKDESK", "accepted": True, "command_id": "8812"},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence, link.evidence) == (
            command.ref,
            Confidence.CERTAIN,
            "command_id",
        )

    def test_a_risk_command_to_the_cancels_it_caused_on_command_id(self) -> None:
        """Section 5.1.2's correction: this is a join, not a guess."""
        feeder = Feeder()
        command = feeder.feed(
            "risk.kill_switch", {"gateway_id": "TRADER07", "command_id": "8812"}
        )
        resolution = feeder.feed(
            "order.cancelled.TRADER07",
            {
                "gateway_id": "TRADER07",
                "order_id": ORDER,
                "cancel_reason": "KILL_SWITCH",
                "command_id": "8812",
            },
        )
        # Two cancelled_by edges, answering different questions: which message
        # ordered it, and which named condition it was. The source namespace
        # is what tells them apart.
        by_source = {
            link.source: link
            for link in resolution.links
            if link.relation == CANCELLED_BY
        }
        assert by_source[command.ref].confidence is Confidence.CERTAIN
        assert "8812" in by_source[command.ref].evidence
        assert f"{CONDITION_PREFIX}KILL_SWITCH" in by_source

    def test_quote_new_to_quote_ack_on_quote_id(self) -> None:
        feeder = Feeder()
        quote = feeder.feed(
            "quote.new", {"gateway_id": "MM01", "symbol": "AAPL", "quote_id": "Q-77"}
        )
        resolution = feeder.feed(
            "quote.ack.MM01",
            {"gateway_id": "MM01", "quote_id": "Q-77", "accepted": True},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (quote.ref, Confidence.CERTAIN)

    def test_order_oco_to_its_ack_on_oco_id(self) -> None:
        feeder = Feeder()
        oco = feeder.feed(
            "order.oco", {"oco_id": "O-1", "gateway_id": "TRADER01", "symbol": "AAPL"}
        )
        resolution = feeder.feed(
            "oco.ack.TRADER01",
            {"gateway_id": "TRADER01", "oco_id": "O-1", "accepted": True},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (oco.ref, Confidence.CERTAIN)

    def test_oco_cancelled_to_its_parent_on_oco_id(self) -> None:
        feeder = Feeder()
        oco = feeder.feed(
            "order.oco", {"oco_id": "O-1", "gateway_id": "TRADER01", "symbol": "AAPL"}
        )
        resolution = feeder.feed(
            "oco.cancelled.TRADER01",
            {"gateway_id": "TRADER01", "oco_id": "O-1", "cancelled_order_id": ORDER},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (oco.ref, Confidence.CERTAIN)


class TestParentage:
    """A leg to its parent. Not a cause, so the envelope never settles it --
    these run on every fact, enveloped or not."""

    @pytest.mark.parametrize(
        ("parent_topic", "parent_payload", "leg_field", "leg_value"),
        [
            (
                "quote.new",
                {"quote_id": "Q-77", "gateway_id": "MM01"},
                "quote_id",
                "Q-77",
            ),
            (
                "order.oco",
                {"oco_id": "O-1", "gateway_id": "TRADER01"},
                "oco_group_id",
                "O-1",
            ),
            (
                "order.combo",
                {"combo_id": "C-1", "gateway_id": "TRADER01"},
                "combo_parent_id",
                "C-1",
            ),
        ],
    )
    def test_a_leg_names_its_parent(
        self,
        parent_topic: str,
        parent_payload: dict[str, Any],
        leg_field: str,
        leg_value: str,
    ) -> None:
        feeder = Feeder()
        parent = feeder.feed(parent_topic, dict(parent_payload, symbol="AAPL"))
        resolution = feeder.feed(
            "order.new", {"id": ORDER, "symbol": "AAPL", leg_field: leg_value}
        )
        link = only(resolution.links, LEG_OF)
        assert (link.source, link.confidence, link.evidence) == (
            parent.ref,
            Confidence.CERTAIN,
            leg_field,
        )

    def test_parentage_is_resolved_even_on_an_enveloped_leg(self) -> None:
        feeder = Feeder()
        quote = feeder.feed(
            "quote.new",
            {"quote_id": "Q-77", "gateway_id": "MM01", "symbol": "AAPL"},
            msg="Q1",
        )
        resolution = feeder.feed(
            "order.new",
            {"id": ORDER, "symbol": "AAPL", "quote_id": "Q-77", "origin": "QUOTE"},
            msg="M1",
            cause="Q1",
            chain="Q1",
        )
        assert only(resolution.links, CAUSED).confidence is Confidence.RECORDED
        assert only(resolution.links, LEG_OF).source == quote.ref


class TestTheCancelReason:
    """``cancel_reason`` names the cause directly. No search, and no message
    to point at -- SELF_MATCH_PREVENTED is a thing that happened."""

    @pytest.mark.parametrize(
        "reason",
        [
            "SELF_MATCH_PREVENTED",
            "INSUFFICIENT_LIQUIDITY",
            "QUOTE_REPLACED",
            "QUOTE_LEG_FILLED",
        ],
    )
    def test_the_reason_is_the_cause(self, reason: str) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.cancelled.MM01",
            {"gateway_id": "MM01", "order_id": ORDER, "cancel_reason": reason},
        )
        link = only(resolution.links, CANCELLED_BY)
        assert link.source == f"{CONDITION_PREFIX}{reason}"
        assert link.confidence is Confidence.CERTAIN

    def test_a_condition_reference_is_not_mistaken_for_a_message(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.cancelled.MM01",
            {
                "gateway_id": "MM01",
                "order_id": ORDER,
                "cancel_reason": "QUOTE_REPLACED",
            },
        )
        source = only(resolution.links, CANCELLED_BY).source
        assert source.startswith(CONDITION_PREFIX)
        assert not source.startswith("@")


# ---------------------------------------------------------------------------
# Tier 2 — constrained search, and where it has to degrade
# ---------------------------------------------------------------------------


class TestTheConstrainedTier:
    def test_one_cancel_in_flight_is_strong(self) -> None:
        feeder = Feeder()
        cancel = feeder.feed(
            "order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"}
        )
        resolution = feeder.feed(
            "order.cancelled.TRADER01", {"gateway_id": "TRADER01", "order_id": ORDER}
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (cancel.ref, Confidence.STRONG)

    def test_two_cancels_in_flight_degrade_to_heuristic(self) -> None:
        """AR-2.4's named case. A confident wrong answer is worse than a
        hedged right one."""
        feeder = Feeder()
        first = feeder.feed(
            "order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"}
        )
        feeder.feed("order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"})
        resolution = feeder.feed(
            "order.cancelled.TRADER01", {"gateway_id": "TRADER01", "order_id": ORDER}
        )
        link = only(resolution.links, CAUSED)
        assert link.confidence is Confidence.HEURISTIC
        assert link.source == first.ref
        assert "in flight" in link.evidence

    def test_the_second_cancellation_of_a_pair_is_no_longer_ambiguous(self) -> None:
        feeder = Feeder()
        feeder.feed("order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"})
        second = feeder.feed(
            "order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"}
        )
        feeder.feed(
            "order.cancelled.TRADER01", {"gateway_id": "TRADER01", "order_id": ORDER}
        )
        resolution = feeder.feed(
            "order.cancelled.TRADER01", {"gateway_id": "TRADER01", "order_id": ORDER}
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (second.ref, Confidence.STRONG)

    def test_a_request_tag_beats_the_ordering_even_when_it_arrives_second(self) -> None:
        feeder = Feeder()
        feeder.feed("order.cancel", {"order_id": ORDER, "gateway_id": "TRADER01"})
        tagged = feeder.feed(
            "order.cancel",
            {"order_id": ORDER, "gateway_id": "TRADER01", "request_tag": "T-9"},
        )
        resolution = feeder.feed(
            "order.cancelled.TRADER01",
            {"gateway_id": "TRADER01", "order_id": ORDER, "request_tag": "T-9"},
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (tagged.ref, Confidence.CERTAIN)

    def test_a_session_transition_links_to_the_state_it_asked_for(self) -> None:
        feeder = Feeder()
        transition = feeder.feed("session.transition", {"to_state": "CONTINUOUS"})
        resolution = feeder.feed(
            "session.state", {"state": "CONTINUOUS", "prev_state": "OPEN"}
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (transition.ref, Confidence.STRONG)

    def test_a_state_nobody_asked_for_is_left_unlinked(self) -> None:
        feeder = Feeder()
        feeder.feed("session.transition", {"to_state": "CLOSED"})
        resolution = feeder.feed("session.state", {"state": "CONTINUOUS"})
        assert [link for link in resolution.links if link.relation == CAUSED] == []

    def test_a_resume_links_to_the_open_halt_for_that_symbol(self) -> None:
        feeder = Feeder()
        halt = feeder.feed(
            "circuit_breaker.halt.AAPL", {"symbol": "AAPL", "halt_source": "CB"}
        )
        resolution = feeder.feed(
            "circuit_breaker.resume.AAPL", {"symbol": "AAPL", "halt_source": "CB"}
        )
        link = only(resolution.links, CAUSED)
        assert (link.source, link.confidence) == (halt.ref, Confidence.STRONG)

    def test_a_resume_does_not_reach_another_symbols_halt(self) -> None:
        feeder = Feeder()
        feeder.feed(
            "circuit_breaker.halt.MSFT", {"symbol": "MSFT", "halt_source": "CB"}
        )
        resolution = feeder.feed(
            "circuit_breaker.resume.AAPL", {"symbol": "AAPL", "halt_source": "CB"}
        )
        assert [link for link in resolution.links if link.relation == CAUSED] == []


# ---------------------------------------------------------------------------
# Tier 3 — reason codes and reconciliation
# ---------------------------------------------------------------------------


class TestExplainingARejection:
    def test_a_halted_rejection_points_at_the_halt(self) -> None:
        feeder = Feeder()
        halt = feeder.feed(
            "circuit_breaker.halt.AAPL",
            {
                "symbol": "AAPL",
                "halt_source": "CB",
                "level": "L1",
                "corridor_low": 71.25,
                "corridor_high": 78.75,
            },
            msg="H1",
        )
        resolution = feeder.feed(
            "order.ack.TRADER07",
            {
                "gateway_id": "TRADER07",
                "order_id": ORDER,
                "accepted": False,
                "reject_code": "CIRCUIT_BREAKER_ACTIVE",
                "symbol": "AAPL",
            },
            msg="A1",
        )
        link = only(resolution.links, REJECTED_BECAUSE)
        assert (link.source, link.confidence) == (halt.ref, Confidence.STRONG)
        assert "71.25" in link.evidence and "L1" in link.evidence

    def test_an_unrelated_reject_code_is_not_blamed_on_the_halt(self) -> None:
        feeder = Feeder()
        feeder.feed(
            "circuit_breaker.halt.AAPL", {"symbol": "AAPL", "halt_source": "CB"}
        )
        resolution = feeder.feed(
            "order.ack.TRADER07",
            {
                "gateway_id": "TRADER07",
                "order_id": ORDER,
                "accepted": False,
                "reject_code": "TICK_VIOLATION",
                "symbol": "AAPL",
            },
        )
        assert [
            link for link in resolution.links if link.relation == REJECTED_BECAUSE
        ] == []

    def test_a_rejection_with_no_halt_on_record_is_not_explained(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.ack.TRADER07",
            {
                "gateway_id": "TRADER07",
                "order_id": ORDER,
                "accepted": False,
                "reject_code": "INSTRUMENT_HALTED",
                "symbol": "AAPL",
            },
        )
        assert [
            link for link in resolution.links if link.relation == REJECTED_BECAUSE
        ] == []

    def test_a_resolver_with_no_state_model_still_works(self) -> None:
        resolver = LinkResolver()
        entry = AuditEntry(
            _TS,
            "order.ack.TRADER07",
            {"order_id": ORDER, "accepted": False, "reject_code": "INSTRUMENT_HALTED"},
            {},
        )
        assert resolver.feed(to_fact(entry, 0)).ref == "@0"


class TestReconciliation:
    def test_an_ack_matching_what_was_observed_is_silent(self) -> None:
        feeder = Feeder()
        feeder.feed(
            "risk.kill_switch", {"gateway_id": "TRADER07", "command_id": "8812"}
        )
        for order_id in (ORDER, OTHER):
            feeder.feed(
                "order.cancelled.TRADER07",
                {
                    "gateway_id": "TRADER07",
                    "order_id": order_id,
                    "cancel_reason": "KILL_SWITCH",
                    "command_id": "8812",
                },
            )
        resolution = feeder.feed(
            "risk.kill_switch_ack.RISKDESK",
            {
                "gateway_id": "RISKDESK",
                "accepted": True,
                "cancelled_orders": 2,
                "cancelled_order_ids": [ORDER, OTHER],
                "command_id": "8812",
            },
        )
        assert EFFECT_COUNT_MISMATCH not in codes(resolution)

    def test_a_missing_cancellation_is_named(self) -> None:
        """Since AR-0.5 the ack lists the ids, so the finding says *which*
        order is missing rather than only that one is."""
        feeder = Feeder()
        feeder.feed(
            "risk.kill_switch", {"gateway_id": "TRADER07", "command_id": "8812"}
        )
        feeder.feed(
            "order.cancelled.TRADER07",
            {
                "gateway_id": "TRADER07",
                "order_id": ORDER,
                "cancel_reason": "KILL_SWITCH",
                "command_id": "8812",
            },
        )
        resolution = feeder.feed(
            "risk.kill_switch_ack.RISKDESK",
            {
                "gateway_id": "RISKDESK",
                "accepted": True,
                "cancelled_orders": 2,
                "cancelled_order_ids": [ORDER, OTHER],
                "command_id": "8812",
            },
        )
        assert EFFECT_COUNT_MISMATCH in codes(resolution)
        detail = next(
            a.detail for a in resolution.anomalies if a.code == EFFECT_COUNT_MISMATCH
        )
        assert OTHER in detail
        assert ORDER not in detail

    def test_quote_legs_count_towards_the_same_command(self) -> None:
        feeder = Feeder()
        feeder.feed("risk.kill_switch", {"gateway_id": "MM01", "command_id": "9001"})
        feeder.feed(
            "order.cancelled.MM01",
            {
                "gateway_id": "MM01",
                "order_id": ORDER,
                "cancel_reason": "KILL_SWITCH",
                "command_id": "9001",
            },
        )
        resolution = feeder.feed(
            "risk.kill_switch_ack.RISKDESK",
            {
                "gateway_id": "RISKDESK",
                "accepted": True,
                "cancelled_quotes": 1,
                "cancelled_quote_order_ids": [ORDER],
                "command_id": "9001",
            },
        )
        assert EFFECT_COUNT_MISMATCH not in codes(resolution)

    def test_an_ack_naming_nothing_is_not_reconciled(self) -> None:
        feeder = Feeder()
        feeder.feed("risk.symbol_halt", {"gateway_id": "OPS01", "command_id": "7"})
        resolution = feeder.feed(
            "risk.symbol_halt_ack.OPS01",
            {
                "gateway_id": "OPS01",
                "accepted": True,
                "symbol": "AAPL",
                "command_id": "7",
            },
        )
        assert EFFECT_COUNT_MISMATCH not in codes(resolution)


# ---------------------------------------------------------------------------
# Envelope-less facts, and what the tool admits it cannot explain
# ---------------------------------------------------------------------------


class TestHonesty:
    def test_an_engine_message_with_no_envelope_is_reported(self) -> None:
        feeder = Feeder()
        assert ENVELOPE_MISSING in codes(feeder.feed("book.AAPL", {"symbol": "AAPL"}))

    def test_an_enveloped_message_is_not(self) -> None:
        feeder = Feeder()
        assert ENVELOPE_MISSING not in codes(
            feeder.feed("book.AAPL", {"symbol": "AAPL"}, msg="B1")
        )

    def test_an_unexplained_fact_is_counted_rather_than_swallowed(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.cancel", {"order_id": ORDER, "gateway_id": "T1"}
        )
        assert resolution.orphan is True
        assert ORPHAN_EVENT in codes(resolution)

    def test_an_attached_fact_is_not_an_orphan_even_with_no_cause(self) -> None:
        """A fill joined to its trade has been explained; calling it an orphan
        would overstate what the tool failed to do."""
        feeder = Feeder()
        feeder.feed("trade.executed", {"id": TRADE, "symbol": "AAPL", "run_seq": 42})
        resolution = feeder.feed(
            "order.fill.MM01", {"gateway_id": "MM01", "trade_ids": [TRADE]}
        )
        assert resolution.orphan is False
        assert ORPHAN_EVENT not in codes(resolution)

    def test_a_fact_with_no_msg_id_gets_a_reference_that_cannot_collide(self) -> None:
        entry = AuditEntry(_TS, "book.AAPL", {"symbol": "AAPL"}, {})
        assert ref(to_fact(entry, 41)) == "@41"


class TestAMessageIsNeverItsOwnCause:
    """``_register`` runs before ``_resolve_cause`` so the two halves need not
    be ordered at every call site — which means an envelope-less ack or fill
    has already registered *itself* as its order's anchor by the time the
    direct-key tier looks that anchor up.

    It got its own ref back, at CERTAIN. On a window opening after the
    ``order.new`` that read "the ack was caused by the ack"; with two
    envelope-less fills, "the first fill caused the second". Both also
    suppressed the ``ORPHAN_EVENT`` that should have been reported, because
    any incoming link counts as having explained a fact.
    """

    def test_an_ack_that_is_its_own_anchor_has_no_cause(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.ack.TRADER01", {"order_id": ORDER, "accepted": True}
        )

        assert [link for link in resolution.links if link.relation == CAUSED] == []

    def test_and_is_then_reported_as_the_orphan_it_is(self) -> None:
        feeder = Feeder()
        resolution = feeder.feed(
            "order.ack.TRADER01", {"order_id": ORDER, "accepted": True}
        )

        assert resolution.orphan

    def test_one_fill_does_not_cause_the_next(self) -> None:
        feeder = Feeder()
        feeder.feed(
            "order.fill.TRADER01",
            {"order_id": ORDER, "fill_qty": 50, "remaining_qty": 50},
        )
        second = feeder.feed(
            "order.fill.TRADER01",
            {"order_id": ORDER, "fill_qty": 50, "remaining_qty": 0},
        )

        assert [link for link in second.links if link.relation == CAUSED] == []
        assert second.orphan

    def test_a_real_anchor_still_causes_its_ack(self) -> None:
        """The tier is not disabled — only the self-reference is refused."""
        feeder = Feeder()
        feeder.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 100})
        resolution = feeder.feed(
            "order.ack.TRADER01", {"order_id": ORDER, "accepted": True}
        )

        link = only(resolution.links, CAUSED)
        assert link.confidence is Confidence.CERTAIN
        assert not resolution.orphan
