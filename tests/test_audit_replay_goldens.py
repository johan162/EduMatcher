"""Golden-fixture tests for pm-audit-replay (task AR-1.5).

The fixture is deliberately what ``pm-audit`` actually records: it subscribes
to the engine's PUB feed, so the inbound ``order.new`` that started this order
is *not* in the trail -- only the id it left behind as every effect's
``causation_id``. A fixture containing lines that can never appear would freeze
fiction.
"""

from __future__ import annotations

import pytest

from tests.replay_goldens import (
    LEVEL_ORDER,
    assert_golden,
    fixture_log,
    golden_path,
    load_facts,
    render_order,
)

SCENARIO = "01_simple_limit_partial_fill"


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
        """The ack, the trade and both fills all descend from a submission that
        is not itself in the trail."""
        facts = {f.kind: f for f in load_facts(SCENARIO)}
        chains = {
            facts[kind].correlation_id
            for kind in ("order.ack", "trade.executed", "order.fill")
        }
        assert len(chains) == 1
        root = chains.pop()
        assert root is not None
        assert facts["order.ack"].causation_id == root
        assert root not in {f.msg_id for f in load_facts(SCENARIO)}

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
