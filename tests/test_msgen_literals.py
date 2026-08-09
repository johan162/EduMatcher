"""Phase 5's acceptance check: a family is migrated when its literal count is zero.

Design section 7.4. Section 1.2 measured 108 topic literals across 25 files and
called them the reason a publisher-side rename is silent: the subscriber keeps
compiling, keeps running, and simply stops receiving.

``pm-msgen grep-literals`` is how that migration is measured, and this file is
what turns the report into a gate. Once a family reaches zero here, a new
literal for one of its topics fails the suite instead of merging quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.msgen import literals as lit
from edumatcher.msgen.cli import main as msgen_main
from edumatcher.msgen.spec import load_all

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"
SRC = REPO_ROOT / "src"

#: Families whose topics must no longer appear as literals anywhere in src/.
#: Add a family here the moment `grep-literals` reports it at zero — that is
#: what makes the migration stick.
#:
#: ``order`` counts only the topics specified so far: 5.1a covers the five
#: engine→gateway events and 5.1b the three inbound commands. The scanner only
#: knows about declared topics, so "zero" here means "zero for what is
#: specified"; the combo/OCO topics join the count when 5.1c specifies them.
MIGRATED = ("trade", "order")


@pytest.fixture(scope="module")
def hits() -> list[lit.Hit]:
    _registry, families = load_all(SPEC_ROOT)
    return lit.scan([SRC], families)


class TestMigratedFamiliesHaveNoLiterals:
    @pytest.mark.parametrize("family", MIGRATED)
    def test_zero_literals(self, family: str, hits: list[lit.Hit]) -> None:
        offenders = [h for h in hits if h.family == family]
        assert not offenders, "\n".join(
            f"{h.path.relative_to(REPO_ROOT)}:{h.line}: {h.text}" for h in offenders
        )

    def test_trade_executed_appears_nowhere_as_a_literal(self) -> None:
        """The specific string this migration removed, stated plainly."""
        generated = SRC / "edumatcher" / "models" / "generated"
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{number}"
            for path in SRC.rglob("*.py")
            if generated not in path.parents and "msgen" not in path.parts
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            )
            if '"trade.executed"' in line and not line.strip().startswith("#")
        ]
        assert offenders == []

    def test_the_constant_is_what_they_use_instead(self) -> None:
        """Not merely absent — replaced by the generated constant."""
        from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED

        assert TOPIC_TRADE_EXECUTED == "trade.executed"
        users = [
            path.relative_to(SRC)
            for path in SRC.rglob("*.py")
            if "TOPIC_TRADE_EXECUTED" in path.read_text(encoding="utf-8")
            and "generated" not in path.parts
        ]
        # 14 subscribers plus the engine, message.py and pm-stats.
        assert len(users) >= 15, users


class TestTheScannerItself:
    """A gate is only as good as the thing doing the looking."""

    def test_it_finds_a_literal_that_is_reintroduced(self, tmp_path: Path) -> None:
        _registry, families = load_all(SPEC_ROOT)
        offender = tmp_path / "regression.py"
        offender.write_text('TOPIC = "trade.executed"\n', encoding="utf-8")
        found = lit.scan([tmp_path], families)
        assert [(h.family, h.line) for h in found] == [("trade", 1)]

    def test_it_finds_a_parameterised_topic_by_prefix(self, tmp_path: Path) -> None:
        """A subscriber hard-codes ``"order.ack."``, not the whole pattern."""
        from edumatcher.msgen.spec import Family, Message

        family = Family(
            family="fake",
            version=1,
            messages=(
                Message(
                    name="order_ack",
                    topic="order.ack.{gateway_id}",
                    transport=("engine_pub",),
                    fields=(),
                ),
            ),
        )
        offender = tmp_path / "subscriber.py"
        offender.write_text('sock.subscribe("order.ack.")\n', encoding="utf-8")
        assert len(lit.scan([tmp_path], [family])) == 1

    def test_it_ignores_commented_out_literals(self, tmp_path: Path) -> None:
        _registry, families = load_all(SPEC_ROOT)
        (tmp_path / "commented.py").write_text(
            '# was: TOPIC = "trade.executed"\n', encoding="utf-8"
        )
        assert lit.scan([tmp_path], families) == []

    def test_it_ignores_the_generated_bindings(self, tmp_path: Path) -> None:
        """They define the constant, so of course they contain the string."""
        _registry, families = load_all(SPEC_ROOT)
        generated = tmp_path / "generated"
        generated.mkdir()
        (generated / "trade.py").write_text(
            'TOPIC_TRADE_EXECUTED = "trade.executed"\n', encoding="utf-8"
        )
        assert lit.scan([tmp_path], families) == []


class TestTheCliReport:
    def test_it_runs_and_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The report names what is left, and every migrated family is at zero.

        This asserted ``no topic literals remain`` until Phase 5.2e, which
        holds only while *every* specified family is also adopted. ``index``
        broke that: its spec and binding are committed and its 23 literals are
        still literals, because the ``day`` record is a wire change whose
        adoption is its own phase (design section 20.6). The boundary moved
        from "nothing is left" to "nothing is left in a family that claims to
        be migrated", which is what MIGRATED above states and what
        TestMigratedFamiliesHaveNoLiterals enforces.
        """
        code = msgen_main(
            ["grep-literals", "--spec", str(SPEC_ROOT), "--src", str(SRC)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "trade: 0 literals - migrated" in out
        for family in MIGRATED:
            assert f"{family}: 0 literals - migrated" in out
