"""Episode assembly (task AR-3.1).

Three properties carry most of the weight, and each has a section below.

**Every fact lands in exactly one episode.** Section 6.2 renders the
chronological stream as a single ordered scan of ``episode_events``, so a fact
filed twice is narrated twice and a fact filed nowhere is silently lost. The
whole-log test asserts the count both ways.

**An episode still open at the end of the window says so.** Section 7.3 calls
truncating it the single most misleading thing a replay tool can do.

**A closed episode is released.** Section 7.1's retirement is what bounds the
memory, and it takes the order state with it.
"""

from __future__ import annotations

from typing import Any

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.episodes import (
    KIND_COMMAND,
    KIND_GATEWAY,
    KIND_INDEX,
    KIND_MARKET_PHASE,
    KIND_ORDER,
    KIND_ORPHAN,
    KIND_QUOTE,
    KIND_SESSION,
    KIND_TRADE,
    OUTCOME_ACCEPTED,
    OUTCOME_CANCELLED,
    OUTCOME_DENIED,
    OUTCOME_FILLED,
    OUTCOME_OPEN,
    OUTCOME_PARTIAL,
    OUTCOME_REJECTED,
    ROLE_CLOSE,
    ROLE_OPEN,
    Episode,
    EpisodeAssembler,
    assemble,
    claim,
)
from edumatcher.audit.replay.facts import to_fact
from edumatcher.audit.replay.links import LinkResolver
from edumatcher.audit.replay.pipeline import Step
from edumatcher.audit.replay.state import StateModel

ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"
OTHER = "9ab1c47f2e5d48a1b3c6f9078e2d15b4"


class Driver:
    """Feeds an assembler the way the pipeline does: state first, then claim.

    The order is not incidental. ``_closing_outcome`` asks the state model
    whether an order is terminal and whether a symbol is still halted, so a
    driver that assembled before applying would see the previous moment.
    """

    def __init__(self, **bounds: Any) -> None:
        self.state = StateModel()
        self.resolver = LinkResolver(self.state)
        self.assembler = EpisodeAssembler(self.state, **bounds)
        self.retired: list[Episode] = []
        self._ordinal = 0
        self._finished: list[Episode] | None = None

    def feed(self, topic: str, payload: dict[str, Any], *, ts: str = "") -> None:
        entry = AuditEntry(
            ts or f"2026-09-08T09:31:{self._ordinal:02d}.000+00:00",
            topic,
            payload,
            {},
            file="audit.log",
            line_no=self._ordinal + 1,
        )
        fact = to_fact(entry, self._ordinal)
        self._ordinal += 1
        anomalies = self.state.apply(fact)
        resolution = self.resolver.feed(fact)
        step = Step(
            fact=fact,
            resolution=resolution,
            anomalies=anomalies + resolution.anomalies,
        )
        self.retired.extend(self.assembler.feed(step))

    def finish(self) -> list[Episode]:
        # Cached: ``drain`` ends the window, and ending it twice would report
        # the second time as an empty log.
        if self._finished is None:
            self._finished = self.retired + list(self.assembler.drain())
        return self._finished

    def one(self, kind: str, anchor: str) -> Episode:
        matching = [
            e for e in self.finish() if e.kind == kind and e.anchor_key == anchor
        ]
        assert len(matching) == 1, f"expected one {kind}/{anchor}, got {matching}"
        return matching[0]


def kinds_of(episode: Episode) -> list[str]:
    return [event.fact.kind for event in episode.events]


# ---------------------------------------------------------------------------
# Who claims what
# ---------------------------------------------------------------------------


class TestTheKindsAreDisjoint:
    """Section 4's table overlaps; the resolution is most-specific-wins."""

    def test_an_index_command_is_an_index_episode_not_a_command_one(self) -> None:
        driver = Driver()
        driver.feed(
            "index.corp_action",
            {"action": "SPLIT", "index_id": "EDU100", "command_id": "cmd-1"},
        )
        episode = driver.one(KIND_INDEX, "cmd-1")
        assert episode.kind == KIND_INDEX

    def test_a_session_transition_is_a_session_episode_not_a_command_one(
        self,
    ) -> None:
        driver = Driver()
        driver.feed("session.transition", {"to_state": "CONTINUOUS"})
        assert driver.one(KIND_SESSION, "CONTINUOUS").kind == KIND_SESSION

    def test_a_risk_command_is_what_is_left_for_the_command_kind(self) -> None:
        driver = Driver()
        driver.feed(
            "risk.kill_switch", {"command_id": "8812", "target_gateway_id": "MM01"}
        )
        assert driver.one(KIND_COMMAND, "8812").kind == KIND_COMMAND

    def test_a_new_risk_command_needs_no_edit_here(self) -> None:
        """The rule is the spec family, not a list of message names."""
        assert claim(
            _fact("risk.force_uncross", {"command_id": "c9", "symbol": "AAPL"})
        ) == (KIND_COMMAND, "c9")

    def test_a_fact_no_rule_claims_becomes_an_orphan(self) -> None:
        driver = Driver()
        driver.feed("book.AAPL", {"symbol": "AAPL", "bids": [], "asks": []})
        assert [e.kind for e in driver.finish()] == [KIND_ORPHAN]

    def test_an_ack_with_no_command_id_cannot_be_joined(self) -> None:
        """Returning None is the honest answer, not an invented anchor."""
        assert claim(_fact("risk.kill_switch_ack.ADMIN", {"accepted": True})) is None


class TestOneFactBelongsToOneEpisode:
    def test_a_fill_belongs_to_its_order_not_to_its_trade(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 100})
        driver.feed("trade.executed", {"id": "T1", "symbol": "AAPL", "qty": 40})
        driver.feed(
            "order.fill.TRADER01",
            {
                "order_id": ORDER,
                "symbol": "AAPL",
                "fill_qty": 40,
                "remaining_qty": 60,
                "status": "PARTIAL",
                "trade_ids": ["T1"],
            },
        )
        assert kinds_of(driver.one(KIND_TRADE, "T1")) == ["trade.executed"]
        assert kinds_of(driver.one(KIND_ORDER, ORDER)) == ["order.new", "order.fill"]


# ---------------------------------------------------------------------------
# Opening, closing and the outcome
# ---------------------------------------------------------------------------


class TestClosing:
    def test_an_order_closes_when_the_state_model_says_it_is_terminal(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 100})
        driver.feed(
            "order.fill.TRADER01",
            {
                "order_id": ORDER,
                "fill_qty": 100,
                "remaining_qty": 0,
                "status": "FILLED",
            },
        )
        episode = driver.one(KIND_ORDER, ORDER)
        assert episode.closed and episode.outcome == OUTCOME_FILLED
        assert [e.role for e in episode.events] == [ROLE_OPEN, ROLE_CLOSE]

    def test_a_rejected_order_closes_on_its_ack(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 100})
        driver.feed(
            "order.ack.TRADER01",
            {"order_id": ORDER, "accepted": False, "reject_code": "INSTRUMENT_HALTED"},
        )
        assert driver.one(KIND_ORDER, ORDER).outcome == OUTCOME_REJECTED

    def test_a_command_closes_on_its_ack(self) -> None:
        driver = Driver()
        driver.feed("risk.kill_switch", {"command_id": "8812"})
        driver.feed(
            "risk.kill_switch_ack.ADMIN", {"command_id": "8812", "accepted": True}
        )
        episode = driver.one(KIND_COMMAND, "8812")
        assert (episode.outcome, len(episode.events)) == (OUTCOME_ACCEPTED, 2)

    def test_a_refused_command_closes_denied(self) -> None:
        driver = Driver()
        driver.feed("index.rebalance", {"command_id": "cmd-2", "index_id": "EDU100"})
        driver.feed(
            "index.rebalance_ack.ADMIN",
            {"command_id": "cmd-2", "accepted": False, "reason": "unknown symbol"},
        )
        assert driver.one(KIND_INDEX, "cmd-2").outcome == OUTCOME_DENIED

    def test_a_quote_closes_on_a_terminal_status(self) -> None:
        driver = Driver()
        driver.feed("quote.new", {"quote_id": "Q1", "symbol": "AAPL"})
        driver.feed(
            "quote.status.MM01",
            {"quote_id": "Q1", "status": "INACTIVE_BID_FILLED"},
        )
        assert driver.one(KIND_QUOTE, "Q1").outcome == OUTCOME_FILLED

    def test_a_quote_stays_open_on_a_non_terminal_status(self) -> None:
        driver = Driver()
        driver.feed("quote.new", {"quote_id": "Q1", "symbol": "AAPL"})
        driver.feed("quote.status.MM01", {"quote_id": "Q1", "status": "ACTIVE"})
        assert driver.one(KIND_QUOTE, "Q1").outcome == OUTCOME_OPEN

    def test_a_gateway_closes_when_it_goes_away(self) -> None:
        driver = Driver()
        driver.feed("system.gateway_connect", {"gateway_id": "TRADER01"})
        driver.feed("system.gateway_bye.TRADER01", {"gateway_id": "TRADER01"})
        assert driver.one(KIND_GATEWAY, "TRADER01").outcome == OUTCOME_ACCEPTED

    def test_two_halts_on_one_symbol_are_two_episodes(self) -> None:
        """Closing frees the anchor, so a span cannot be revived by a later one."""
        driver = Driver()
        for _ in range(2):
            driver.feed("circuit_breaker.halt.AAPL", {"symbol": "AAPL"})
            driver.feed("circuit_breaker.resume.AAPL", {"symbol": "AAPL"})
        phases = [e for e in driver.finish() if e.kind == KIND_MARKET_PHASE]
        assert len(phases) == 2
        assert all(len(e.events) == 2 for e in phases)

    def test_an_auction_inside_a_halt_does_not_end_the_halt(self) -> None:
        driver = Driver()
        driver.feed("circuit_breaker.halt.AAPL", {"symbol": "AAPL"})
        driver.feed("auction.result.AAPL", {"symbol": "AAPL", "eq_qty": 10})
        driver.feed("circuit_breaker.resume.AAPL", {"symbol": "AAPL"})
        episode = driver.one(KIND_MARKET_PHASE, "AAPL")
        assert kinds_of(episode) == [
            "circuit_breaker.halt",
            "auction.result",
            "circuit_breaker.resume",
        ]

    def test_a_standalone_auction_closes_on_its_result(self) -> None:
        driver = Driver()
        driver.feed("auction.indicative.MSFT", {"symbol": "MSFT"})
        driver.feed("auction.result.MSFT", {"symbol": "MSFT", "eq_qty": 10})
        assert driver.one(KIND_MARKET_PHASE, "MSFT").outcome == OUTCOME_ACCEPTED

    def test_a_session_span_ends_when_a_different_state_is_entered(self) -> None:
        """The fact that ends a span opens the next one, and belongs to it."""
        driver = Driver()
        driver.feed("session.transition", {"to_state": "CONTINUOUS"})
        driver.feed("session.state", {"state": "CONTINUOUS", "prev_state": "OPENING"})
        driver.feed("session.transition", {"to_state": "CLOSED"})
        first = driver.one(KIND_SESSION, "CONTINUOUS")
        assert first.closed and kinds_of(first) == [
            "session.transition",
            "session.state",
        ]
        assert kinds_of(driver.one(KIND_SESSION, "CLOSED")) == ["session.transition"]

    def test_the_first_event_is_always_the_opening_one(self) -> None:
        """Even when it also ends the episode: ``events[0].role`` is invariant."""
        driver = Driver()
        driver.feed(
            "order.cancelled.TRADER01",
            {"order_id": OTHER, "symbol": "AAPL", "cancel_reason": "KILL_SWITCH"},
        )
        episode = driver.one(KIND_ORDER, OTHER)
        assert episode.events[0].role == ROLE_OPEN
        assert (episode.closed, episode.outcome) == (True, OUTCOME_CANCELLED)


class TestTheWindowEnd:
    def test_an_unfinished_order_that_filled_some_is_partial(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 200})
        driver.feed(
            "order.fill.TRADER01",
            {
                "order_id": ORDER,
                "fill_qty": 150,
                "remaining_qty": 50,
                "status": "PARTIAL",
            },
        )
        episode = driver.one(KIND_ORDER, ORDER)
        assert (episode.closed, episode.outcome) == (False, OUTCOME_PARTIAL)

    def test_an_untouched_order_is_open(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 200})
        assert driver.one(KIND_ORDER, ORDER).outcome == OUTCOME_OPEN

    def test_nothing_held_is_dropped(self) -> None:
        driver = Driver()
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 1})
        driver.feed("risk.kill_switch", {"command_id": "8812"})
        driver.feed("system.gateway_connect", {"gateway_id": "TRADER01"})
        assert len(driver.finish()) == 3


class TestRetirement:
    """Section 7.1: closed, and out of the reorder window."""

    def test_a_closed_episode_is_released_once_the_window_moves_past_it(self) -> None:
        driver = Driver(max_facts=2, max_seconds=3600)
        driver.feed(
            "order.cancelled.TRADER01", {"order_id": ORDER, "cancel_reason": "X"}
        )
        # Held: a later fact for this order could still join it.
        assert [e.anchor_key for e in driver.retired] == []
        for _ in range(4):
            driver.feed("book.AAPL", {"symbol": "AAPL"})
        assert ORDER in [e.anchor_key for e in driver.retired]

    def test_a_single_fact_episode_ages_out_like_any_other(self) -> None:
        """A trade is the cause its fills name; it cannot be freed on arrival."""
        driver = Driver(max_facts=2, max_seconds=3600)
        driver.feed("trade.executed", {"id": "T1", "symbol": "AAPL", "qty": 1})
        assert driver.retired == []
        for _ in range(4):
            driver.feed("book.AAPL", {"symbol": "AAPL"})
        assert [e.kind for e in driver.retired][0] == KIND_TRADE

    def test_retiring_a_fact_stops_its_message_id_resolving_causes(self) -> None:
        """The bargain section 7.1 makes, asserted rather than assumed."""
        driver = Driver(max_facts=1, max_seconds=0)
        driver.feed("trade.executed", {"id": "T1", "symbol": "AAPL", "qty": 1})
        for _ in range(3):
            driver.feed("book.AAPL", {"symbol": "AAPL"})
        assert driver.resolver._by_msg == {}

    def test_an_open_episode_is_never_released_early(self) -> None:
        driver = Driver(max_facts=1, max_seconds=0)
        driver.feed("order.new", {"id": ORDER, "symbol": "AAPL", "quantity": 100})
        for _ in range(5):
            driver.feed("book.AAPL", {"symbol": "AAPL"})
        assert ORDER not in [e.anchor_key for e in driver.retired]

    def test_retiring_an_order_episode_retires_its_order_state(self) -> None:
        """The half of section 7.1 phase 2 deferred: the model is bounded now."""
        driver = Driver(max_facts=1, max_seconds=0)
        driver.feed(
            "order.cancelled.TRADER01", {"order_id": ORDER, "cancel_reason": "X"}
        )
        assert ORDER in driver.state.orders
        for _ in range(3):
            driver.feed("book.AAPL", {"symbol": "AAPL"})
        assert ORDER not in driver.state.orders


class TestTheWholeLog:
    def test_every_fact_lands_in_exactly_one_episode(self) -> None:
        from pathlib import Path

        from edumatcher.audit.query import iter_entries
        from edumatcher.audit.replay.pipeline import reconstruct

        for log in sorted(Path("tests/fixtures/replay").glob("*.log")):
            run, steps = reconstruct(iter_entries([log]))
            episodes = list(assemble(steps, run.state))
            placed = [
                (event.fact.file, event.fact.line_no)
                for episode in episodes
                for event in episode.events
            ]
            lines = [
                line
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            assert len(placed) == len(lines), log.name
            assert len(set(placed)) == len(placed), f"{log.name}: a fact filed twice"


def _fact(topic: str, payload: dict[str, Any]) -> Any:
    entry = AuditEntry(
        "2026-09-08T09:31:02.118+00:00", topic, payload, {}, file="a.log", line_no=1
    )
    return to_fact(entry, 0)
