"""The narrator (task AR-4.2).

The goldens in ``test_audit_replay_goldens.py`` freeze *what* it says. This
file pins the rules it must not break while saying it -- section 8.3's
no-invention list, which is the difference between a tool that is trusted and
one that is believed.

Four of those rules are testable directly and each gets a class: a price is
never printed without a resolved unit, an open episode is never described as
finished, a guess is never worded as a certainty, and an abbreviated id is
never ambiguous. The fifth -- no inferred intent -- is a property of the
template file, so it is checked there: no template contains a verb of
intention.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import REPLAY_FIXTURES

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.replay import episodes as episodes_module
from edumatcher.audit.replay import templates
from edumatcher.audit.replay.anomalies import UNKNOWN_TOPIC
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.facts import Fact, Price, to_fact
from edumatcher.audit.replay.pipeline import Reconstruction, reconstruct
from edumatcher.audit.replay.render_text import (
    Abbreviator,
    Options,
    Renderer,
    narrate,
    suppressed,
)

FIXTURES = REPLAY_FIXTURES
SIMPLE = "01_simple_limit_partial_fill"
HALTED = "02_halted_reject_and_kill_switch"
ARCHIVE = "03_archived_no_envelope"
STRUCTURES = "04_quote_oco_combo"
DAY = "05_session_and_index"
ALL = (SIMPLE, HALTED, ARCHIVE, STRUCTURES, DAY)


def run(name: str) -> tuple[list[Episode], Reconstruction]:
    reconstruction, steps = reconstruct(iter_entries([FIXTURES / f"{name}.log"]))
    return (
        list(assemble(steps, reconstruction.state, reconstruction.links)),
        reconstruction,
    )


def fact_of(name: str, kind: str) -> Fact:
    """The first fact of *kind* in a fixture.

    ``suppressed`` takes a Fact rather than a kind, because section 8.1's
    "unclassified event" is a property of the fact -- whether its topic is in
    any message family at all -- and not of the string it is named by.
    """
    episodes, _reconstruction = run(name)
    return next(
        event.fact
        for episode in episodes
        for event in episode.events
        if event.fact.kind == kind
    )


def text(name: str, **options: Any) -> str:
    episodes, reconstruction = run(name)
    return "\n".join(narrate(episodes, reconstruction.state, Options(**options)))


# ---------------------------------------------------------------------------
# Section 8.3 — the no-invention rule
# ---------------------------------------------------------------------------


class TestNoPriceWithoutAResolvedUnit:
    def test_an_unresolved_price_is_labelled_as_ticks(self) -> None:
        price = Price(
            name="price_ticks", raw=7569, display=None, tick_decimals=None, source=""
        )
        assert price.render() == "7569 ticks"

    def test_a_display_price_is_never_rounded_to_make_it_fit(self) -> None:
        """Regression: ``or 0`` turned 74.80 into "75".

        ``order.fill.fill_price`` is display money and its message declares no
        ``tick_decimals``, so every fill price the tool printed was rounded to
        the nearest whole unit. Rounding is not formatting -- it changes the
        number, which is the one thing section 5.3.1 exists to prevent.
        """
        price = Price(
            name="fill_price",
            raw=74.8,
            display=74.8,
            tick_decimals=None,
            source="already display money",
        )
        assert price.render() == "74.8"

    def test_a_fill_prints_at_its_instrument_scale(self) -> None:
        """Formatting may use the symbol's scale; it may not invent a value."""
        assert "150 @ 74.80" in text(SIMPLE, level=1)

    def test_no_narrated_price_is_bare_ticks_when_the_scale_is_known(self) -> None:
        for name in ALL:
            assert "ticks" not in text(name, level=2), name


class TestNoOutcomeForAnOpenEpisode:
    def test_an_unfinished_order_says_so(self) -> None:
        assert "is still working at the end of the window" in text(SIMPLE, level=0)

    def test_an_untouched_order_says_so(self) -> None:
        assert "was still open at the end of the window" in text(STRUCTURES, level=0)

    def test_every_summary_carries_its_own_episode_s_outcome(self) -> None:
        for name in ALL:
            episodes, reconstruction = run(name)
            shown = sorted(
                (e for e in episodes if not suppressed(e.opened, 1)),
                key=lambda e: e.opened_sort_key,
            )
            lines = narrate(episodes, reconstruction.state, Options(level=0))
            assert len(lines) == len(shown), name
            for episode, line in zip(shown, lines):
                template = templates.SUMMARIES[episode.kind]
                if "{outcome_phrase}" not in template:
                    # A trade has no outcome worth stating: it happened, and
                    # "trade 000042 ran to completion" says nothing the line
                    # does not already.
                    continue
                assert templates.OUTCOME_PHRASES[episode.outcome] in line, line

    def test_every_outcome_the_assembler_can_produce_has_a_phrase(self) -> None:
        """Totality is what makes the lookup safe.

        The renderer reads ``OUTCOME_PHRASES[outcome]`` with no branch, so an
        open episode cannot be described as finished *unless* its phrase says
        so or is missing. This asserts neither happens.
        """
        produced = {
            value
            for name, value in vars(episodes_module).items()
            if name.startswith("OUTCOME_") and isinstance(value, str)
        }
        assert produced <= set(templates.OUTCOME_PHRASES)

    @pytest.mark.parametrize("outcome", ["OPEN", "PARTIAL"])
    def test_an_unfinished_outcome_announces_itself(self, outcome: str) -> None:
        """The two that must never read as finished say "still" in words."""
        assert "still" in templates.OUTCOME_PHRASES[outcome]

    def test_a_rejected_order_is_not_given_a_fill_tally(self) -> None:
        """ "0 of 100 filled" beside "was rejected" says it twice, worse."""
        rejected = [
            line for line in text(HALTED, level=0).splitlines() if "rejected" in line
        ]
        assert rejected and all("filled" not in line for line in rejected)


class TestAGuessIsWordedAsAGuess:
    def test_a_heuristic_link_is_hedged(self) -> None:
        """Fixture 03 has two cancels in flight for one order."""
        rendered = text(ARCHIVE, level=2, explain=True)
        assert "a guess:" in rendered

    def test_a_recorded_link_is_not_hedged(self) -> None:
        rendered = text(SIMPLE, level=2, explain=True)
        assert "[recorded:" in rendered
        assert "a guess:" not in rendered

    def test_a_declared_origin_is_not_reported_as_a_missing_cause(self) -> None:
        rendered = text(SIMPLE, level=2, explain=True)
        assert "the publisher recorded that nothing caused this" in rendered

    def test_a_cause_outside_the_window_says_where_to_look(self) -> None:
        """Section 8.3: most missing antecedents are just outside the range,
        and saying so saves a wasted debugging hour.

        The window has to be narrowed *before* reconstruction: filtering
        episodes afterwards would leave the resolver's answers untouched, and
        it is the resolver that reports a cause it could not find.
        """
        entries = list(iter_entries([FIXTURES / f"{SIMPLE}.log"]))
        reconstruction, steps = reconstruct(iter(entries[4:]))
        episodes = list(assemble(steps, reconstruction.state, reconstruction.links))
        lines = narrate(episodes, reconstruction.state, Options(level=2, explain=True))
        assert any("try an earlier --from" in line for line in lines), lines


class TestNoAmbiguousReference:
    def test_two_ids_sharing_a_prefix_are_both_lengthened(self) -> None:
        short = Abbreviator(["abcdef1111", "abcdef2222"], 6)
        assert short("abcdef1111") != short("abcdef2222")

    def test_an_id_referred_to_but_never_the_subject_is_still_checked(self) -> None:
        """Regression: ``entity_id`` was absent from the collision pool, so
        two different recovery items both printed as ``dead00…``."""
        lines = [line for line in text(DAY, level=1).splitlines() if "Order" in line]
        assert len(lines) == 2
        assert lines[0].split()[2] != lines[1].split()[2]

    def test_full_keeps_the_whole_id(self) -> None:
        assert Abbreviator(["abcdef1111"], None)("abcdef1111") == "abcdef1111"

    def test_a_missing_id_is_a_dash_not_an_empty_gap(self) -> None:
        assert Abbreviator([], 6)(None) == "-"


class TestTheTemplatesInferNoIntent:
    """Section 8.3 forbids "the trader was trying to…" and its relatives."""

    @pytest.mark.parametrize(
        "verb", ["trying", "intended", "wanted", "attempted", "hoped", "meant to"]
    )
    def test_no_template_speculates(self, verb: str) -> None:
        every = list(templates.SUMMARIES.values()) + [
            sentence
            for by_level in templates.TEMPLATES.values()
            for sentence in by_level.values()
        ]
        assert not [s for s in every if verb in s.lower()]


# ---------------------------------------------------------------------------
# Detail levels (section 8.1)
# ---------------------------------------------------------------------------


class TestDetailLevels:
    def test_level_zero_is_one_line_per_episode(self) -> None:
        episodes, reconstruction = run(SIMPLE)
        narrated = narrate(episodes, reconstruction.state, Options(level=0))
        shown = [e for e in episodes if not suppressed(e.opened, 1)]
        assert len(narrated) == len(shown)

    def test_level_one_is_one_line_per_narrated_fact(self) -> None:
        episodes, reconstruction = run(SIMPLE)
        narrated = narrate(episodes, reconstruction.state, Options(level=1))
        shown = [
            event
            for episode in episodes
            for event in episode.events
            if not suppressed(event.fact, 1)
        ]
        assert len(narrated) == len(shown)

    def test_market_data_waits_for_level_three(self) -> None:
        book = fact_of(SIMPLE, "book")
        depth = fact_of(SIMPLE, "depth")

        assert suppressed(book, 1) and suppressed(depth, 2)
        assert not suppressed(book, 3)
        assert not suppressed(fact_of(SIMPLE, "order.fill"), 1)

    def test_level_two_adds_without_removing(self) -> None:
        """Raising the level may say more; it may not say less."""
        for name in ALL:
            one = text(name, level=1).splitlines()
            two = text(name, level=2).splitlines()
            assert len(two) >= len(one), name

    def test_the_switches_annotate_rather_than_replace(self) -> None:
        plain = text(SIMPLE, level=1)
        annotated = text(SIMPLE, level=1, show_source=True)
        for line in plain.splitlines():
            assert line in annotated


class TestActorNaming:
    def test_ids_by_default(self) -> None:
        assert "TRADER01 submitted" in text(SIMPLE, level=1)

    def test_descriptive_appends_the_recorded_description(self) -> None:
        rendered = text(SIMPLE, level=1, descriptive_actors=True)
        assert "TRADER01 (Nordic Equities desk) submitted" in rendered

    def test_descriptive_invents_nothing_for_a_gateway_that_named_none(self) -> None:
        rendered = text(SIMPLE, level=1, descriptive_actors=True)
        assert "TRADER02 (" not in rendered


class TestNothingCrashes:
    @pytest.mark.parametrize("name", ALL)
    @pytest.mark.parametrize("level", [0, 1, 2])
    def test_every_fixture_narrates_at_every_level(self, name: str, level: int) -> None:
        lines = text(name, level=level).splitlines()
        assert lines
        assert all(line.strip() for line in lines)

    def test_a_template_naming_a_slot_that_does_not_apply_is_not_fatal(self) -> None:
        """A wording bug must not take the whole window with it."""
        entry = AuditEntry(
            "2026-09-08T09:31:02.118+00:00",
            "order.new",
            {"id": "x" * 32},
            {},
            file="a.log",
            line_no=1,
        )
        fact = to_fact(entry, 0)
        episodes, reconstruction = run(SIMPLE)
        renderer = Renderer(episodes, reconstruction.state, Options(level=1))
        slots, _found = renderer._slots(episodes[0], fact)
        assert slots["symbol"]


class TestLevelThree:
    """Section 8.1: market data, drop copy, clock skew and ``arrival_seq``."""

    def test_market_data_gets_a_sentence_rather_than_its_topic(self) -> None:
        """Level 3 without templates would reveal the lines and still say
        nothing -- ``book from -`` is a topic, not market data."""
        out = text(SIMPLE, level=3)

        assert "AAPL book: 74.75 x 500 bid / 74.80 x 150 ask" in out
        assert "AAPL depth: mid 75.69, 550 bid / 0 ask" in out
        assert "book from" not in out

    def test_a_book_price_is_printed_at_the_instrument_s_precision(self) -> None:
        """74.8 beside a 74.80 elsewhere in the same report reads as two
        different prices. The ladder is plain numbers rather than declared
        price fields, so nothing else would have done it."""
        assert "74.80 x 150" in text(SIMPLE, level=3)

    def test_arrival_seq_is_shown(self) -> None:
        """What the book actually used for priority -- never the client
        clock beside it."""
        assert "· arrival_seq 8814" in text(SIMPLE, level=3)

    def test_the_two_clocks_are_shown_against_receipt(self) -> None:
        out = text(SIMPLE, level=3)

        assert "· client clock -0.005s from receipt" in out
        assert "· engine clock +0.000s from receipt" in out

    def test_none_of_it_appears_at_level_two(self) -> None:
        out = text(SIMPLE, level=2)

        assert "arrival_seq" not in out
        assert "from receipt" not in out
        assert "book:" not in out


class TestLevelFour:
    """Section 8.1: every unclassified event, and the raw payload."""

    def test_the_payload_is_shown_under_every_line(self) -> None:
        episodes, reconstruction = run(SIMPLE)
        narrated = narrate(episodes, reconstruction.state, Options(level=4))
        payloads = [line for line in narrated if "· payload: " in line]
        events = sum(len(episode.events) for episode in episodes)

        assert len(payloads) == events

    def test_it_does_not_appear_at_level_three(self) -> None:
        assert "· payload: " not in text(SIMPLE, level=3)

    def test_an_unclassified_event_waits_for_level_four(self) -> None:
        """A topic in no message family is section 8.1's "unclassified
        event". The tool cannot say what it is, so it stays out of a
        narrative of what the exchange did -- but it is never hidden:
        UNKNOWN_TOPIC is raised on it at every level."""
        stray = to_fact(
            AuditEntry(
                "2026-09-08T09:31:02.110+00:00",
                "not.a.real.family",
                {"whatever": 1},
                {},
                file="audit.log",
                line_no=1,
            ),
            0,
        )

        assert stray.known is False
        assert suppressed(stray, 3) is True
        assert suppressed(stray, 4) is False
        assert [a.code for a in stray.anomalies] == [UNKNOWN_TOPIC]
