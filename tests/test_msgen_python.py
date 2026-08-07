"""Generator tests: determinism, drift detection, and the emitted helpers.

Determinism is not a nicety. ``pm-msgen check`` is the guarantee the whole
design rests on (section 7.2), and a generator that occasionally reorders its
own output turns that check into a source of flaky CI failures — which is
worse than not having it (risk R9).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from edumatcher.msgen import generate as gen
from edumatcher.msgen.cli import main as msgen_main

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_ROOT = REPO_ROOT / "spec"
OUT_PYTHON = REPO_ROOT / "src" / "edumatcher" / "models" / "generated"

_PARAM_FAMILY = """\
family: paramfam
version: 3

messages:
  - name: order_ack
    topic: "order.ack.{gateway_id}"
    transport: [engine_pub]
    doc:
      motivation: "Acknowledge acceptance or rejection of a new order."
      example_note: "reason is empty on ACCEPTED."
    fields:
      - { name: gateway_id, type: string, validate: { max_len: 32 } }
      - { name: order_id, type: string, validate: { max_len: 64, pattern: '^[0-9]+$' } }
      - name: status
        type: enum
        values: [ACCEPTED, REJECTED]
      - { name: qty, type: int, unit: shares, validate: { gt: 0, le: 1000 } }
      - { name: reason, type: string, required: false, default: "",
          validate: { max_len: 128, min_len: 0 } }
"""


@pytest.fixture
def param_spec(tmp_path: Path) -> Path:
    """A spec root exercising a parameterised topic and every validate rule."""
    root = tmp_path / "spec"
    (root / "messages").mkdir(parents=True)
    (root / "transports.yaml").write_text(
        (SPEC_ROOT / "transports.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "messages" / "paramfam.yaml").write_text(_PARAM_FAMILY, encoding="utf-8")
    return root


def _import_generated(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestDeterminism:
    def test_generation_is_byte_identical_when_repeated(self) -> None:
        first = gen.build_artifacts(SPEC_ROOT, OUT_PYTHON)
        second = gen.build_artifacts(SPEC_ROOT, OUT_PYTHON)
        assert [a.content for a in first] == [b.content for b in second]

    def test_generation_is_identical_across_processes(self) -> None:
        """Catches hash-seed-dependent ordering, which a single process cannot."""
        code = (
            "from pathlib import Path\n"
            "from edumatcher.msgen import generate as gen\n"
            f"arts = gen.build_artifacts(Path({str(SPEC_ROOT)!r}), "
            f"Path({str(OUT_PYTHON)!r}))\n"
            "print(''.join(a.content for a in arts), end='')\n"
        )
        outputs = set()
        for seed in ("0", "1", "12345"):
            # Inherit the environment and override only what the test controls:
            # a hand-built env drops interpreter-critical variables on some
            # platforms and would fail for reasons unrelated to determinism.
            env = {**os.environ, "PYTHONHASHSEED": seed}
            env["PYTHONPATH"] = os.pathsep.join(
                [str(REPO_ROOT / "src"), env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
            outputs.add(proc.stdout)
        assert len(outputs) == 1

    def test_no_absolute_path_leaks_into_the_banner(self) -> None:
        for art in gen.build_artifacts(SPEC_ROOT, OUT_PYTHON):
            assert str(REPO_ROOT) not in art.content
            assert art.content.startswith("# GENERATED FROM spec/messages/")


class TestCommittedOutputMatchesSpec:
    """This is `pm-msgen check` — the guarantee (design section 7.2)."""

    def test_check_reports_no_drift(self) -> None:
        assert gen.diff(gen.build_artifacts(SPEC_ROOT, OUT_PYTHON)) == []

    def test_check_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = msgen_main(
            ["check", "--spec", str(SPEC_ROOT), "--out-python", str(OUT_PYTHON)]
        )
        capsys.readouterr()
        assert code == 0

    def test_a_hand_edit_to_a_generated_file_is_caught(self, tmp_path: Path) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(SPEC_ROOT, out))
        target = out / "trade.py"
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                "tick_decimals: int = 2", "tick_decimals: int = 4"
            ),
            encoding="utf-8",
        )
        diffs = gen.diff(gen.build_artifacts(SPEC_ROOT, out))
        assert diffs and "tick_decimals" in diffs[0]

    def test_a_spec_edit_without_regeneration_is_caught(
        self, tmp_path: Path, param_spec: Path
    ) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(param_spec, out))
        assert gen.diff(gen.build_artifacts(param_spec, out)) == []

        spec_file = param_spec / "messages" / "paramfam.yaml"
        spec_file.write_text(
            spec_file.read_text(encoding="utf-8").replace("le: 1000", "le: 5000"),
            encoding="utf-8",
        )
        diffs = gen.diff(gen.build_artifacts(param_spec, out))
        assert diffs and "5000" in diffs[0]

    def test_a_missing_generated_file_is_caught(self, tmp_path: Path) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        diffs = gen.diff(gen.build_artifacts(SPEC_ROOT, out))
        assert diffs and "missing" in diffs[0]

    def test_check_exits_nonzero_on_drift(self, tmp_path: Path) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        assert (
            msgen_main(["check", "--spec", str(SPEC_ROOT), "--out-python", str(out)])
            == 1
        )

    def test_generate_is_idempotent(self, tmp_path: Path) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        assert gen.write(gen.build_artifacts(SPEC_ROOT, out)) != []
        assert gen.write(gen.build_artifacts(SPEC_ROOT, out)) == []


class TestGeneratedModuleIsUsable:
    """The generated file must import, type-check by eye, and behave."""

    def test_committed_trade_module_imports(self) -> None:
        from edumatcher.models.generated import trade

        assert trade.FAMILY == "trade"
        assert trade.FAMILY_VERSION == 1
        assert trade.FAMILY_TOPICS == ("trade.executed",)

    def test_describe_lists_exactly_the_spec_fields(self) -> None:
        """Capstone assertion 7, at Phase 1 scale."""
        from edumatcher.msgen.spec import load_all
        from edumatcher.models.generated import trade

        _registry, families = load_all(SPEC_ROOT)
        (msg,) = families[0].messages
        described = trade.describe_trade_executed()
        assert [d["name"] for d in described] == [f.name for f in msg.fields]
        assert [d["unit"] for d in described] == [f.unit for f in msg.fields]
        assert [d["required"] for d in described] == [f.required for f in msg.fields]

    def test_is_topic_helper(self) -> None:
        from edumatcher.models.generated import trade

        assert trade.is_trade_executed("trade.executed")
        assert not trade.is_trade_executed("trade.executed.extra")


class TestParameterisedTopics:
    """Design section A.4 — the helpers that remove scattered topic literals."""

    def test_topic_and_match_round_trip(self, tmp_path: Path, param_spec: Path) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(param_spec, out))
        mod = _import_generated(out / "paramfam.py", "paramfam_topic")

        assert mod.TOPIC_ORDER_ACK == "order.ack.{gateway_id}"
        assert mod.PREFIX_ORDER_ACK == "order.ack."
        assert mod.topic_order_ack("GW1") == "order.ack.GW1"
        assert mod.match_order_ack("order.ack.GW1") == "GW1"

    def test_match_does_not_swallow_a_trailing_segment(
        self, tmp_path: Path, param_spec: Path
    ) -> None:
        """``[^.]+`` not ``.+`` — a greedy match would return 'GW1.extra'."""
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(param_spec, out))
        mod = _import_generated(out / "paramfam.py", "paramfam_greedy")

        assert mod.match_order_ack("order.ack.GW1.extra") is None
        assert mod.match_order_ack("order.fill.GW1") is None
        assert mod.match_order_ack("xorder.ack.GW1") is None

    def test_make_uses_the_parameterised_topic(
        self, tmp_path: Path, param_spec: Path
    ) -> None:
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(param_spec, out))
        mod = _import_generated(out / "paramfam.py", "paramfam_make")

        frames = mod.make_order_ack(
            gateway_id="GW1", order_id="7", status="ACCEPTED", qty=10
        )
        assert frames[0] == b"order.ack.GW1"
        assert mod.parse_order_ack(frames).reason == ""


class TestGeneratedValidationRules:
    """Every declared rule must be enforced, and only where declared."""

    @pytest.fixture
    def mod(self, tmp_path: Path, param_spec: Path) -> ModuleType:
        out = tmp_path / "generated"
        out.mkdir()
        gen.write(gen.build_artifacts(param_spec, out))
        return _import_generated(out / "paramfam.py", "paramfam_rules")

    def _base(self) -> dict[str, Any]:
        return {
            "gateway_id": "GW1",
            "order_id": "7",
            "status": "ACCEPTED",
            "qty": 10,
            "reason": "",
        }

    @pytest.mark.parametrize(
        "override, rule",
        [
            ({"qty": 0}, "gt"),
            ({"qty": 1001}, "le"),
            ({"status": "MAYBE"}, "values"),
            ({"order_id": "seven"}, "pattern"),
            ({"gateway_id": "G" * 33}, "max_len"),
            ({"reason": "r" * 129}, "max_len"),
        ],
    )
    def test_validate_rejects(
        self, mod: ModuleType, override: dict[str, Any], rule: str
    ) -> None:
        from edumatcher.models.generated._runtime import MessageValidationError

        payload = {**self._base(), **override}
        obj = mod.OrderAck.from_dict(payload)
        with pytest.raises(MessageValidationError):
            obj.validate()

    def test_validate_accepts_the_boundaries(self, mod: ModuleType) -> None:
        mod.OrderAck.from_dict({**self._base(), "qty": 1000}).validate()
        mod.OrderAck.from_dict({**self._base(), "gateway_id": "G" * 32}).validate()

    def test_from_dict_never_validates(self, mod: ModuleType) -> None:
        """Section 5.1.1: coercion and validation are different jobs."""
        obj = mod.OrderAck.from_dict({**self._base(), "qty": -5, "status": "NOPE"})
        assert obj.qty == -5
        assert obj.status == "NOPE"

    def test_make_validates(self, mod: ModuleType) -> None:
        from edumatcher.models.generated._runtime import MessageValidationError

        with pytest.raises(MessageValidationError):
            mod.make_order_ack(**{**self._base(), "qty": 0})

    def test_make_unchecked_does_not_validate(self, mod: ModuleType) -> None:
        frames = mod.make_order_ack_unchecked(**{**self._base(), "qty": 0})
        assert frames[0] == b"order.ack.GW1"

    def test_make_and_make_unchecked_agree_on_valid_input(
        self, mod: ModuleType
    ) -> None:
        """The whole justification for the unchecked variant: same bytes."""
        payload = self._base()
        assert mod.make_order_ack(**payload) == mod.make_order_ack_unchecked(**payload)

    def test_validation_error_is_a_value_error(self, mod: ModuleType) -> None:
        """Existing `except ValueError` call sites must keep working."""
        with pytest.raises(ValueError):
            mod.make_order_ack(**{**self._base(), "qty": 0})


class TestSpecErrorsSurfaceThroughTheCli:
    def test_bad_spec_exits_two(self, tmp_path: Path) -> None:
        root = tmp_path / "spec"
        (root / "messages").mkdir(parents=True)
        (root / "transports.yaml").write_text(
            (SPEC_ROOT / "transports.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (root / "messages" / "broken.yaml").write_text(
            yaml.safe_dump({"family": "broken", "version": 1, "messages": []}),
            encoding="utf-8",
        )
        assert msgen_main(["lint", "--spec", str(root)]) == 2

    def test_lint_accepts_the_committed_spec(self) -> None:
        assert msgen_main(["lint", "--spec", str(SPEC_ROOT)]) == 0
