"""Golden-fixture tests for pm-audit-replay (tasks AR-1.5, AR-2.3, AR-2.4).

Each fixture is what ``pm-audit`` actually records, which is now more than it
was: the engine echoes every inbound command onto the PUB feed it subscribes
to, so the ``order.new`` that started an order is in the trail, carrying the
gateway's own envelope. Its ``msg_id`` is what every effect names, and the
line precedes its own ack in the file because the echo runs before dispatch.

Three scenarios, covering the three shapes the resolver has to handle:

* ``01`` — healthy and enveloped. Nearly every link is RECORDED.
* ``02`` — a circuit-breaker halt, a rejection the market model has to
  explain, and a kill switch whose ack names one cancellation the trail does
  not contain.
* ``03`` — an archive from before the envelope existed. Every link is
  inferred, and two cancels in flight for one order have to degrade rather
  than guess.
"""

from __future__ import annotations

import pytest

from edumatcher.audit.replay.links import Confidence
from tests.replay_goldens import (
    LEVEL_CAUSALITY,
    LEVEL_ORDER,
    assert_golden,
    fixture_log,
    golden_path,
    load_facts,
    load_steps,
    render_causality,
    render_order,
)

SCENARIO = "01_simple_limit_partial_fill"
HALTED = "02_halted_reject_and_kill_switch"
ARCHIVE = "03_archived_no_envelope"

ALL_SCENARIOS = (SCENARIO, HALTED, ARCHIVE)


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

    def test_reconstruction_raises_nothing(self, scenario: str) -> None:
        """A malformed log must never crash the tool -- it is the thing you
        reach for *when* the system is misbehaving."""
        for step in load_steps(scenario):
            assert step.resolution.ref
