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
from edumatcher.msgen.spec import Family, Message, load_all

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"
SRC = REPO_ROOT / "src"

#: Families whose topics must no longer appear as literals anywhere in src/.
#: Add a family here the moment `grep-literals` reports it at zero — that is
#: what makes the migration stick.
#:
#: "Zero" means zero for what is *specified* — the scanner only knows declared
#: topics. Every family here is now fully specified, so it also means zero
#: outright. Until 5.3b that distinction hid a second one: the scanner could
#: not see f-string topics at all, so a family could read as migrated with
#: parameterised topics still hard-coded. See TestTheDetectorSeesFStrings.
MIGRATED = (
    "trade",
    "order",
    "session",
    "book",
    "log",
    "index",
    "risk",
    "structure",
    "quote",
)


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
        """Every specified family is at zero, and the report says so.

        This assertion was relaxed for exactly one phase. 5.2e committed
        ``index``'s spec and binding without adopting them — the ``day``
        record is a wire change reaching three consumers, and half-adopting it
        would have left ``pm-msgen check`` passing while those three read a
        key the producer no longer sent. 5.2f finished the job, so the
        stronger claim holds again.
        """
        code = msgen_main(
            ["grep-literals", "--spec", str(SPEC_ROOT), "--src", str(SRC)]
        )
        out = capsys.readouterr().out
        assert code == 0
        for family in MIGRATED:
            assert f"{family}: 0 literals - migrated" in out
        assert "no topic literals remain" in out


class TestTheDetectorSeesFStrings:
    """The hole 5.3b closed, and the reason it went unnoticed for six phases.

    ``_patterns`` built ``re.compile(f'"{needle}"')`` — a closing quote
    immediately after the prefix. An f-string never has one:
    ``f"order.fill.{gateway_id}"`` continues with ``{``. So the report said
    ``order: 0 literals - migrated`` while forty hard-coded parameterised
    topics sat in eight modules, and had said so since 5.1e.

    Every family migrated before this was migrated correctly *anyway*, because
    each phase grepped by hand as well — which is exactly why nobody noticed
    the tool was not the thing finding them. A gate that cannot see the most
    common way of writing what it gates is worse than no gate, because it is
    believed.
    """

    def _family(self, topic: str) -> list[Family]:
        return [
            Family(
                family="fake",
                version=1,
                messages=(
                    Message(
                        name="m",
                        topic=topic,
                        transport=("engine_pub",),
                        fields=(),
                    ),
                ),
            )
        ]

    def test_an_f_string_parameterised_topic_is_found(self, tmp_path: Path) -> None:
        (tmp_path / "sub.py").write_text(
            'sock.subscribe(f"order.ack.{gateway_id}")\n', encoding="utf-8"
        )
        assert len(lit.scan([tmp_path], self._family("order.ack.{gateway_id}"))) == 1

    def test_a_plain_prefix_is_still_found(self, tmp_path: Path) -> None:
        """The behaviour that already worked must not regress."""
        (tmp_path / "sub.py").write_text('sock.subscribe("order.ack.")\n', "utf-8")
        assert len(lit.scan([tmp_path], self._family("order.ack.{gateway_id}"))) == 1

    def test_a_fully_hard_coded_instance_is_found(self, tmp_path: Path) -> None:
        (tmp_path / "sub.py").write_text('if topic == "order.ack.GW1":\n', "utf-8")
        assert len(lit.scan([tmp_path], self._family("order.ack.{gateway_id}"))) == 1

    def test_a_longer_sibling_topic_is_not_a_false_positive(
        self, tmp_path: Path
    ) -> None:
        """Dropping the closing quote must not make prefixes swallow each other.

        Safe because a parameterised needle ends in ``.``: the quote has to sit
        immediately before it, so ``risk.kill_switch_gateway_ack.`` cannot
        match a ``risk.kill_switch_ack.`` needle.
        """
        (tmp_path / "sub.py").write_text(
            'topic = f"risk.kill_switch_gateway_ack.{gw}"\n', "utf-8"
        )
        found = lit.scan([tmp_path], self._family("risk.kill_switch_ack.{gateway_id}"))
        assert found == []

    def test_a_non_parameterised_topic_keeps_its_closing_quote(
        self, tmp_path: Path
    ) -> None:
        """Without the anchor ``"risk.kill_switch"`` would match its siblings."""
        (tmp_path / "sub.py").write_text('topic = "risk.kill_switch_global"\n', "utf-8")
        assert lit.scan([tmp_path], self._family("risk.kill_switch")) == []
