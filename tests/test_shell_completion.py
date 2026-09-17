"""Tests for tab completion of every pm-* command (bash and zsh).

The parsers are the source of truth: `tools/gen_completion.py` renders the
committed files in `src/edumatcher/completion/` from each entry point's
`build_parser()`. These tests guard the two invariants that make that safe:

1. Every entry point actually exposes the `build_parser()` contract
   (:func:`test_entry_point_exposes_build_parser`), so a new command without
   one fails here rather than silently missing completion.
2. The committed files are never allowed to drift from what the generator
   would produce right now (:func:`test_committed_completion_is_current`).

See docs-design/EduMatcher-Shell-completion.md for the full design.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gen_completion as gc  # noqa: E402

from edumatcher.pm_help import cli as pm_help_cli  # noqa: E402

ENTRY_POINTS = sorted(gc.entry_points().items())
COMPLETION_DIR = gc.OUT_DIR


@pytest.mark.parametrize("name,target", ENTRY_POINTS, ids=[n for n, _ in ENTRY_POINTS])
def test_entry_point_exposes_build_parser(name: str, target: str) -> None:
    module_name = target.split(":")[0]
    module = importlib.import_module(module_name)
    assert hasattr(module, "build_parser"), f"{module_name} has no build_parser()"

    saved = sys.argv[0]
    sys.argv[0] = name
    try:
        parser = module.build_parser()
    finally:
        sys.argv[0] = saved

    import argparse

    assert isinstance(parser, argparse.ArgumentParser)
    assert (
        parser.prog == name
    ), f"{module_name}.build_parser().prog == {parser.prog!r}, expected {name!r}"


@pytest.mark.parametrize("shell", gc.SHELLS)
def test_committed_completion_is_current(shell: str) -> None:
    # render() is called in a fresh subprocess rather than in-process: by
    # this point in the session, test_entry_point_exposes_build_parser has
    # already imported every entry-point module under tests/conftest.py's
    # EDUMATCHER_DATA_DIR (a temp dir it creates for the whole test run), so
    # those modules' DATA_DIR-derived defaults (e.g. pm-viewer's --db) are
    # already baked in and immune to any env var this test sets afterwards.
    # A fresh interpreter picks up gen_completion.render()'s own pinned
    # value before anything is imported, matching what `make completion`
    # actually produces.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'tools'); import gen_completion as gc; "
            "sys.stdout.write(gc.render(sys.argv[1]))",
            shell,
        ],
        cwd=gc.ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    current = result.stdout
    committed = (COMPLETION_DIR / f"pm-completion.{shell}").read_text(encoding="utf-8")
    assert committed == current, (
        f"src/edumatcher/completion/pm-completion.{shell} is out of date "
        "with the current parsers -- run `make completion` and commit the result."
    )


@pytest.mark.parametrize("shell", gc.SHELLS)
def test_pm_help_prints_completion(
    shell: str, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = pm_help_cli.main(["--completion", shell])
    captured = capsys.readouterr()
    expected = (COMPLETION_DIR / f"pm-completion.{shell}").read_text(encoding="utf-8")
    assert captured.out == expected
    assert exit_code == 0


def test_pm_help_completion_rejects_command() -> None:
    with pytest.raises(SystemExit) as exc:
        pm_help_cli.main(["--completion", "bash", "pm-engine"])
    assert exc.value.code == 2


def test_bash_script_parses() -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    script = COMPLETION_DIR / "pm-completion.bash"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bash_completes_subcommands() -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    script = COMPLETION_DIR / "pm-completion.bash"
    bash_script = f"""
source "{script}"
COMP_WORDS=(pm-audit-cli "")
COMP_CWORD=1
COMP_LINE="pm-audit-cli "
COMP_POINT=${{#COMP_LINE}}
func=$(complete -p pm-audit-cli | sed -n "s/.*-F \\\\([^ ]*\\\\).*/\\\\1/p")
COMPREPLY=()
"$func"
echo "${{COMPREPLY[*]}}"
"""
    result = subprocess.run(["bash", "-c", bash_script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    completions = result.stdout.split()
    assert "events" in completions
    assert "timeline" in completions


def test_zsh_eval_registers_every_command() -> None:
    if shutil.which("zsh") is None:
        pytest.skip("zsh not available")
    script = COMPLETION_DIR / "pm-completion.zsh"
    names = [name for name, _ in ENTRY_POINTS]
    zsh_script = f"""
autoload -Uz compinit
compinit -u -C
eval "$(<{script})"
missing=()
for name in {" ".join(names)}; do
  if [[ -z ${{_comps[$name]:-}} ]]; then
    missing+=("$name")
  fi
done
if (( ${{#missing[@]}} )); then
  echo "MISSING: ${{missing[*]}}"
  exit 1
fi
echo "ALL REGISTERED"
"""
    result = subprocess.run(
        ["zsh", "-f", "-c", zsh_script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL REGISTERED" in result.stdout
