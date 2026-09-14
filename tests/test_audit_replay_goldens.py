"""Golden-fixture tests for pm-audit-replay (tasks AR-1.5, AR-2.3, AR-2.4).

Each fixture is what ``pm-audit`` actually records, which is now more than it
was: the engine echoes every inbound command onto the PUB feed it subscribes
to, so the ``order.new`` that started an order is in the trail, carrying the
gateway's own envelope. Its ``msg_id`` is what every effect names, and the
line precedes its own ack in the file because the echo runs before dispatch.

Five scenarios. The first three cover the shapes the *resolver* has to handle;
the last two exist so that every episode kind in section 4 is exercised by a
fixture, which is what AR-3.1's verification asks for.

* ``01`` — healthy and enveloped. Nearly every link is RECORDED.
* ``02`` — a circuit-breaker halt, a rejection the market model has to
  explain, and a kill switch whose ack names one cancellation the trail does
  not contain.
* ``03`` — an archive from before the envelope existed. Every link is
  inferred, and two cancels in flight for one order have to degrade rather
  than guess.
* ``04`` — a market maker's structures: a two-sided quote whose bid leg is
  lifted, an OCO pair where one leg fills and the other is pulled, and a
  combo with two legs. Covers ``quote``, ``oco`` and ``combo``.
* ``05`` — the exchange's own day: a restart with one failed restore, the
  session spans, and an index corporate action. Covers ``recovery``,
  ``session`` and ``index``.

Every line of every fixture is validated against the message it claims to be
(:class:`TestTheFixturesAreRealMessages`). A fixture that has drifted from the
spec has quietly stopped testing what it says it tests — and one had: 01 and
02 carried a ``role`` field on ``system.gateway_auth`` that the engine has
never published.
"""

from __future__ import annotations

import importlib

import pytest

from edumatcher.audit.query import iter_entries, lookup_topic, parse_ts
from edumatcher.audit.replay.episodes import (
    KIND_COMBO,
    KIND_COMMAND,
    KIND_GATEWAY,
    KIND_INDEX,
    KIND_MARKET_PHASE,
    KIND_OCO,
    KIND_ORDER,
    KIND_ORPHAN,
    KIND_QUOTE,
    KIND_RECOVERY,
    KIND_SESSION,
    KIND_TRADE,
    OUTCOME_UNKNOWN,
)
from edumatcher.models.envelope import ulid_millis

from edumatcher.audit.replay.links import Confidence
from tests.replay_goldens import (
    LEVEL_CAUSALITY,
    LEVEL_EPISODES,
    LEVEL_ORDER,
    assert_golden,
    fixture_log,
    golden_path,
    PROSE_LEVELS,
    load_episodes,
    load_facts,
    load_steps,
    render_causality,
    render_episodes,
    render_prose,
    render_order,
)

SCENARIO = "01_simple_limit_partial_fill"
HALTED = "02_halted_reject_and_kill_switch"
ARCHIVE = "03_archived_no_envelope"
STRUCTURES = "04_quote_oco_combo"
EXCHANGE_DAY = "05_session_and_index"

ALL_SCENARIOS = (SCENARIO, HALTED, ARCHIVE, STRUCTURES, EXCHANGE_DAY)
#: Every kind the assembler can produce (design section 4, plus section 7.2's
#: catch-all). Listed rather than derived so adding a kind without a fixture
#: fails here.
ALL_KINDS = (
    KIND_ORDER,
    KIND_TRADE,
    KIND_QUOTE,
    KIND_OCO,
    KIND_COMBO,
    KIND_COMMAND,
    KIND_MARKET_PHASE,
    KIND_SESSION,
    KIND_GATEWAY,
    KIND_INDEX,
    KIND_RECOVERY,
    KIND_ORPHAN,
)


class TestSimpleLimitPartialFill:
    def test_the_canonical_order_matches_the_golden(self, update_goldens: bool) -> None:
        assert_golden(
            SCENARIO,
            LEVEL_ORDER,
            render_order(load_facts(SCENARIO)),
            update=update_goldens,
        )

    def test_every_line_is_parsed(self) -> None:
        """Nothing may vanish silently -- the strongest property the tool has."""
        raw = fixture_log(SCENARIO).read_text(encoding="utf-8").strip().splitlines()
        assert len(load_facts(SCENARIO)) == len(raw)

    def test_the_scenario_is_clean(self) -> None:
        """A healthy log produces no findings at all. This is what makes the
        anomaly report a meaningful regression signal."""
        findings = [a for f in load_facts(SCENARIO) for a in f.anomalies]
        assert findings == [], [str(a) for a in findings]

    def test_every_price_is_resolved(self) -> None:
        for fact in load_facts(SCENARIO):
            for price in fact.prices.values():
                assert price.resolved, f"{fact.kind}.{price.name} left unresolved"

    def test_the_tick_price_on_depth_is_converted(self) -> None:
        """The one tick-scaled field in the scenario, and the trap section 5.3.1
        is about: 7569 is 75.69, not seven and a half thousand."""
        depth = next(f for f in load_facts(SCENARIO) if f.kind == "depth")
        assert depth.prices["mid_price_ticks"].display == pytest.approx(75.69)
        assert depth.prices["mid_price_ticks"].raw == 7569

    def test_the_effects_share_one_causal_chain(self) -> None:
        """The ack, the trade and both fills all descend from the submission --
        which, since the engine echoes inbound commands, is in the trail."""
        facts = {f.kind: f for f in load_facts(SCENARIO)}
        chains = {
            facts[kind].correlation_id
            for kind in ("order.ack", "trade.executed", "order.fill")
        }
        assert len(chains) == 1
        root = chains.pop()
        assert root is not None
        assert facts["order.ack"].causation_id == root
        assert facts["order.new"].msg_id == root

    def test_the_submission_precedes_its_own_ack_in_the_file(self) -> None:
        """The echo runs before dispatch, so `grep` and `less` read causally
        too -- not only a tool that sorts by msg_id."""
        raw = fixture_log(SCENARIO).read_text(encoding="utf-8").splitlines()
        submitted = next(i for i, line in enumerate(raw) if "[order.new]" in line)
        acked = next(i for i, line in enumerate(raw) if "[order.ack." in line)
        assert submitted < acked

    def test_every_link_is_recorded_or_certain(self) -> None:
        """A healthy enveloped log should need no inference at all."""
        weak = [
            link
            for step in load_steps(SCENARIO)
            for link in step.resolution.links
            if link.confidence not in (Confidence.RECORDED, Confidence.CERTAIN)
        ]
        assert weak == []

    def test_a_snapshot_is_a_declared_origin(self) -> None:
        """Envelope present, no cause: the publisher stated nothing caused it,
        which is information rather than a gap."""
        book = next(f for f in load_facts(SCENARIO) if f.kind == "book")
        assert book.has_envelope is True
        assert book.causation_id is None


class TestTheHarnessItself:
    def test_update_goldens_regenerates_the_file(self, tmp_path, monkeypatch) -> None:
        import tests.replay_goldens as goldens

        monkeypatch.setattr(goldens, "FIXTURE_DIR", tmp_path)
        goldens.assert_golden("scratch", "order", "one\ntwo\n", update=True)
        assert (tmp_path / "scratch.expected.order.txt").read_text() == "one\ntwo\n"

    def test_a_corrupted_expectation_fails(self, tmp_path, monkeypatch) -> None:
        """The test that makes every other golden test worth having."""
        import tests.replay_goldens as goldens

        monkeypatch.setattr(goldens, "FIXTURE_DIR", tmp_path)
        (tmp_path / "scratch.expected.order.txt").write_text("one\nCORRUPTED\n")
        with pytest.raises(AssertionError) as exc:
            goldens.assert_golden("scratch", "order", "one\ntwo\n", update=False)
        assert "CORRUPTED" in str(exc.value)

    def test_a_missing_expectation_says_what_to_do(self, tmp_path, monkeypatch) -> None:
        import tests.replay_goldens as goldens

        monkeypatch.setattr(goldens, "FIXTURE_DIR", tmp_path)
        with pytest.raises(AssertionError) as exc:
            goldens.assert_golden("scratch", "order", "anything\n", update=False)
        assert "--update-goldens" in str(exc.value)

    def test_the_committed_golden_is_not_empty(self) -> None:
        """Guards against a --update-goldens run that froze nothing."""
        text = golden_path(SCENARIO, LEVEL_ORDER).read_text(encoding="utf-8")
        assert len(text.strip().splitlines()) == len(load_facts(SCENARIO))


@pytest.mark.parametrize("scenario", ALL_SCENARIOS)
class TestEveryScenario:
    def test_the_canonical_order_matches_the_golden(
        self, scenario: str, update_goldens: bool
    ) -> None:
        assert_golden(
            scenario,
            LEVEL_ORDER,
            render_order(load_facts(scenario)),
            update=update_goldens,
        )

    def test_the_causality_matches_the_golden(
        self, scenario: str, update_goldens: bool
    ) -> None:
        """Freezes the confidence as well as the link. A regression that
        promoted a guess to a certainty would change no other test."""
        assert_golden(
            scenario,
            LEVEL_CAUSALITY,
            render_causality(load_steps(scenario)),
            update=update_goldens,
        )

    def test_every_line_is_reconstructed(self, scenario: str) -> None:
        raw = fixture_log(scenario).read_text(encoding="utf-8").strip().splitlines()
        assert len(load_steps(scenario)) == len(raw)

    def test_the_episodes_match_the_golden(
        self, scenario: str, update_goldens: bool
    ) -> None:
        """Freezes the grouping, the outcome and the arithmetic together.

        Separating them would let a change move a fact from one episode to
        another while every per-episode number still added up.
        """
        assert_golden(
            scenario,
            LEVEL_EPISODES,
            render_episodes(load_episodes(scenario)),
            update=update_goldens,
        )

    @pytest.mark.parametrize("suffix,level", sorted(PROSE_LEVELS.items()))
    def test_the_prose_matches_the_golden(
        self, scenario: str, suffix: str, level: int, update_goldens: bool
    ) -> None:
        """The goldens a reviewer should actually read.

        Wording is cheap to change now and expensive once section 11's NDJSON
        contract freezes the ``text`` field, which is why CP-4 asks for these
        to be shown to someone who did not write them.
        """
        assert_golden(
            scenario,
            suffix,
            render_prose(scenario, level),
            update=update_goldens,
        )

    def test_every_fact_lands_in_exactly_one_episode(self, scenario: str) -> None:
        placed = [
            (event.fact.file, event.fact.line_no)
            for episode in load_episodes(scenario)
            for event in episode.events
        ]
        assert len(placed) == len(load_steps(scenario))
        assert len(set(placed)) == len(placed)

    def test_reconstruction_raises_nothing(self, scenario: str) -> None:
        """A malformed log must never crash the tool -- it is the thing you
        reach for *when* the system is misbehaving."""
        for step in load_steps(scenario):
            assert step.resolution.ref


class TestEveryEpisodeKindHasAFixture:
    """AR-3.1's verification: one fixture per kind, not one per code path.

    The assembler dispatches on eleven kinds plus the orphan catch-all. A kind
    nothing exercises is a kind whose claim rule, close rule and outcome have
    only ever been read, never run.
    """

    def test_all_twelve_kinds_appear(self) -> None:
        seen = {
            episode.kind
            for scenario in ALL_SCENARIOS
            for episode in load_episodes(scenario)
        }
        assert seen == set(ALL_KINDS), f"never exercised: {set(ALL_KINDS) - seen}"

    @pytest.mark.parametrize("kind", sorted(ALL_KINDS))
    def test_each_kind_reaches_an_outcome_that_is_not_unknown(self, kind: str) -> None:
        """UNKNOWN means the close rule never decided anything.

        ``orphan`` is the exception it is by definition: a fact nothing
        claimed has no outcome to reach, and saying so is the point of it.
        """
        outcomes = {
            episode.outcome
            for scenario in ALL_SCENARIOS
            for episode in load_episodes(scenario)
            if episode.kind == kind
        }
        expected = {OUTCOME_UNKNOWN} if kind == KIND_ORPHAN else set()
        assert outcomes - {OUTCOME_UNKNOWN} or outcomes == expected, outcomes


class TestTheFixturesAreRealMessages:
    """A fixture is a sample of the trail, so it has to be one.

    Nothing else in the suite would notice a fixture inventing a field: the
    tool reads payloads as mappings and ignores what it does not recognise. So
    a drifted fixture keeps passing while testing a message the system does
    not send -- which is how ``system.gateway_auth.role`` survived in two
    fixtures for a whole phase.
    """

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS)
    def test_every_line_validates_against_its_declared_message(
        self, scenario: str
    ) -> None:
        for entry in iter_entries([fixture_log(scenario)]):
            spec = lookup_topic(entry.topic)
            assert spec is not None, f"{entry.topic} is in no message family"
            module = importlib.import_module(
                f"edumatcher.models.generated.{spec['family']}"
            )
            name = "".join(part.title() for part in spec["message"].split("_"))
            getattr(module, name).from_dict(entry.payload).validate()

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS)
    def test_no_line_carries_a_field_the_spec_does_not_declare(
        self, scenario: str
    ) -> None:
        for entry in iter_entries([fixture_log(scenario)]):
            spec = lookup_topic(entry.topic)
            assert spec is not None
            undeclared = set(entry.payload) - {f["name"] for f in spec["fields"]}
            assert not undeclared, (
                f"{scenario}:{entry.line_no} {entry.topic} carries "
                f"{sorted(undeclared)}, which the spec does not declare"
            )

    @pytest.mark.parametrize("scenario", ALL_SCENARIOS)
    def test_no_message_is_recorded_before_it_was_minted(self, scenario: str) -> None:
        """The one thing the two clocks cannot do (design section 5.2).

        A ULID is minted at the publish site and the bracketed timestamp is
        ``pm-audit``'s receipt, so the gap between them is transit -- fixture
        01 has a realistic 5 ms on one line. Equality is *not* the invariant;
        a ULID minted after its own line was written is, and it would order
        the fixture in a way the real system never could.
        """
        for entry in iter_entries([fixture_log(scenario)]):
            if entry.msg_id is None:
                continue
            minted = ulid_millis(entry.msg_id)
            assert minted is not None, f"{scenario}:{entry.line_no}: unparseable ULID"
            received = int(parse_ts(entry.timestamp).timestamp() * 1000)
            assert minted <= received, (
                f"{scenario}:{entry.line_no} was recorded "
                f"{minted - received}ms before it was minted"
            )
