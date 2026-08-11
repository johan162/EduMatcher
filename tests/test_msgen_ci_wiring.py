"""The drift check must actually run in the build.

``pm-msgen check`` working is necessary but not sufficient. The design is
explicit that the check *in CI* is the whole point:

    "Without the check, the generator is merely a scaffolder and section 1
    recurs within a release."

A check that exists but is not wired in provides no guarantee at all, and
deleting one line from a workflow file is an easy thing to do by accident
during an unrelated refactor. These tests assert the wiring itself, so that
removal is a failing test rather than a silent loss of the property the whole
design rests on.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.msgen.cli import main as msgen_main

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SPEC_ROOT = REPO_ROOT / "spec"
OUT_PYTHON = REPO_ROOT / "src" / "edumatcher" / "models" / "generated"


def _phony_targets() -> set[str]:
    """Return every target declared .PHONY, following backslash continuations."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    collected: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith(".PHONY:"):
            continue
        current = line.split(":", 1)[1]
        cursor = index
        while current.rstrip().endswith("\\"):
            current = current.rstrip().rstrip("\\")
            cursor += 1
            current += " " + lines[cursor]
        collected.extend(current.split())
    return set(collected)


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


class TestMakefileWiring:
    def test_msgen_check_target_exists(self) -> None:
        text = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^msgen-check:", text, re.M), "no msgen-check target"

    def test_msgen_check_is_part_of_the_aggregate_check(self) -> None:
        """``make check`` must run it, or nobody runs it locally."""
        text = MAKEFILE.read_text(encoding="utf-8")
        match = re.search(r"^_check:([^\n]*)", text, re.M)
        assert match is not None, "no _check target"
        assert "msgen-check" in match.group(1), (
            "_check does not depend on msgen-check; `make check` would pass "
            "with drifted generated files"
        )

    def test_msgen_check_target_is_phony(self) -> None:
        """Otherwise a stray file named `msgen-check` would silently skip it."""
        assert "msgen-check" in _phony_targets()
        assert "msgen" in _phony_targets()

    def test_a_regenerate_target_exists(self) -> None:
        """The failure message tells the user to run it, so it must be there."""
        text = MAKEFILE.read_text(encoding="utf-8")
        assert re.search(r"^msgen:", text, re.M), "no msgen target to regenerate"
        assert "pm-msgen generate" in text


class TestCiWorkflowWiring:
    def test_code_check_job_runs_the_drift_check(self) -> None:
        steps = _workflow()["jobs"]["code-check"]["steps"]
        commands = " ".join(str(step.get("run", "")) for step in steps)
        assert "msgen.cli check" in commands or "pm-msgen check" in commands, (
            "the code-check job does not run the message drift check; a spec "
            "change without a regeneration would merge"
        )

    def test_the_drift_check_does_not_rely_on_the_console_script(self) -> None:
        """The code-check job installs with --no-root, so scripts are absent.

        If someone "simplifies" the step to `poetry run pm-msgen check` it will
        fail with a confusing "command not found" rather than a drift report.
        """
        job = _workflow()["jobs"]["code-check"]
        setup = next(
            step
            for step in job["steps"]
            if "setup-python-poetry" in str(step.get("uses", ""))
        )
        installs_root = str(setup.get("with", {}).get("install-root", "true"))
        drift_step = next(
            step
            for step in job["steps"]
            if "msgen" in str(step.get("run", ""))
            or "msgen" in str(step.get("name", ""))
        )
        if installs_root != "true":
            assert "python -m edumatcher.msgen.cli" in drift_step["run"]
            assert "PYTHONPATH=src" in drift_step["run"]


class TestCheckBehavesAsABuildGate:
    """Exit codes are the contract a CI step depends on."""

    def test_clean_tree_exits_zero(self) -> None:
        assert (
            msgen_main(
                ["check", "--spec", str(SPEC_ROOT), "--out-python", str(OUT_PYTHON)]
            )
            == 0
        )

    def test_drift_exits_one(self, tmp_path: Path) -> None:
        empty = tmp_path / "generated"
        empty.mkdir()
        assert (
            msgen_main(["check", "--spec", str(SPEC_ROOT), "--out-python", str(empty)])
            == 1
        )

    def test_a_broken_spec_exits_two_not_one(self, tmp_path: Path) -> None:
        """Distinct from drift: a broken spec is a different failure."""
        root = tmp_path / "spec"
        (root / "messages").mkdir(parents=True)
        (root / "transports.yaml").write_text(
            (SPEC_ROOT / "transports.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (root / "messages" / "bad.yaml").write_text(
            "family: bad\nversion: 1\nmessages:\n  - name: x\n", encoding="utf-8"
        )
        assert (
            msgen_main(["check", "--spec", str(root), "--out-python", str(OUT_PYTHON)])
            == 2
        )

    def test_a_missing_spec_directory_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Runs in CI; a bare ENOENT costs someone a debugging round."""
        code = msgen_main(
            [
                "check",
                "--spec",
                str(tmp_path / "nope"),
                "--out-python",
                str(OUT_PYTHON),
            ]
        )
        assert code == 2
        assert "Run from the repository root" in capsys.readouterr().err


class TestGenerationIsReproducibleOnDisk:
    """Design section B.17 / risk R9, asserted end to end rather than in memory.

    ``generate`` twice into two directories must produce identical bytes. If it
    did not, ``pm-msgen check`` would fail at random and the gate would be worse
    than useless — a flaky check trains people to ignore it.
    """

    def test_two_generate_runs_produce_identical_files(self, tmp_path: Path) -> None:
        first, second = tmp_path / "a", tmp_path / "b"
        for out in (first, second):
            out.mkdir()
            assert (
                msgen_main(
                    ["generate", "--spec", str(SPEC_ROOT), "--out-python", str(out)]
                )
                == 0
            )

        names = sorted(p.name for p in first.glob("*.py"))
        assert names, "generate produced nothing"
        assert names == sorted(p.name for p in second.glob("*.py"))
        for name in names:
            assert (first / name).read_bytes() == (second / name).read_bytes(), name

    def test_regenerating_over_committed_output_changes_nothing(self) -> None:
        """The committed tree is a fixed point of the generator."""
        before = {
            p.name: p.read_bytes()
            for p in OUT_PYTHON.glob("*.py")
            if p.name != "__init__.py"
        }
        assert (
            msgen_main(
                ["generate", "--spec", str(SPEC_ROOT), "--out-python", str(OUT_PYTHON)]
            )
            == 0
        )
        after = {
            p.name: p.read_bytes()
            for p in OUT_PYTHON.glob("*.py")
            if p.name != "__init__.py"
        }
        assert before == after
