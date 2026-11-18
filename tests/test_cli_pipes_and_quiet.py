"""CLIs behave in pipes and scripts (For-Later L013, L034; WP-FL16).

L013: ``pm-stats-cli daily | head`` ended in a ``BrokenPipeError`` traceback.
Python ignores SIGPIPE, so a write into a closed pipe raises instead of
ending the process quietly. Each CLI entry point is run here with its stdout
a pipe whose reading end is already closed: the first write breaks.

L034 / Q10: every daemon's ``-q`` selects WARNING, which is the default; the
help said "Reduce output to warnings/errors" as if it changed something.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "edumatcher"

#: (entry point, module) of every CLI that prints its results to stdout.
CLIS = [
    ("pm-audit-cli", "edumatcher.audit.cli"),
    ("pm-audit-replay", "edumatcher.audit.replay.cli"),
    ("pm-sim-forensics", "edumatcher.sim_forensics.cli"),
    ("pm-clearing-cli", "edumatcher.clearing.cli"),
    ("pm-eod", "edumatcher.eod.main"),
    ("pm-stats-cli", "edumatcher.stats.cli"),
    ("pm-admin-cli", "edumatcher.commands.cli"),
    ("pm-index-cli", "edumatcher.index.cli"),
    ("pm-index-admin-cli", "edumatcher.index.admin_cli"),
    ("pm-config-gen", "edumatcher.config_gen.cli"),
    ("pm-config-deploy", "edumatcher.config_deploy"),
    ("pm-valuation", "edumatcher.valuation.main"),
    ("pm-cverifier", "edumatcher.cverifier.cli"),
    ("pm-config-show", "edumatcher.config_show.cli"),
    ("pm-msgen", "edumatcher.msgen.cli"),
    ("pm-news", "edumatcher.market_sim.news_cli"),
    ("pm-compdb-cli", "edumatcher.compdb.cli"),
    ("pm-log-cli", "edumatcher.log_cli.main"),
    ("pm-monitor-cli", "edumatcher.monitor.cli"),
    ("pm-opctl-cli", "edumatcher.emo.cli"),
    ("pm-help", "edumatcher.pm_help.cli"),
]


def _into_a_closed_pipe(
    module: str, argv: list[str]
) -> subprocess.CompletedProcess[str]:
    read_end, write_end = os.pipe()
    os.close(read_end)  # the reader (``head``) has already gone
    try:
        code = (
            "import sys; from importlib import import_module; "
            f"sys.argv = {argv!r}; import_module({module!r}).main()"
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            cwd=ROOT,
        )
    finally:
        os.close(write_end)


@pytest.mark.parametrize(("name", "module"), CLIS, ids=[n for n, _ in CLIS])
def test_help_into_a_closed_pipe_prints_no_traceback(name: str, module: str) -> None:
    done = _into_a_closed_pipe(module, [name, "--help"])
    assert "Traceback" not in done.stderr, done.stderr
    assert "BrokenPipeError" not in done.stderr, done.stderr


def test_a_table_into_a_closed_pipe_prints_no_traceback(tmp_path: Path) -> None:
    """The L013 command itself: a table from pm-stats-cli."""
    from tests.test_stats_cli import _seed_db

    db = tmp_path / "stats.db"
    _seed_db(db)
    done = _into_a_closed_pipe(
        "edumatcher.stats.cli", ["pm-stats-cli", "--db", str(db), "daily"]
    )
    assert "Traceback" not in done.stderr, done.stderr
    assert "BrokenPipeError" not in done.stderr, done.stderr


# -- -q means one thing (Q10) -------------------------------------------------

Q10 = "Explicit WARNING log level (the default)"


def _quiet_helps() -> list[tuple[str, str]]:
    """(file, help) of every ``-q/--quiet`` argument about the log level."""
    out: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and any(
                    isinstance(a, ast.Constant) and a.value == "--quiet"
                    for a in node.args
                )
            ):
                continue
            for kw in node.keywords:
                if kw.arg == "help":
                    text = ast.literal_eval(kw.value)
                    if "warning" in text.lower():
                        out.append((str(path.relative_to(SRC)), text))
    return out


def test_every_log_level_quiet_flag_says_it_is_the_default() -> None:
    helps = _quiet_helps()
    assert len(helps) >= 25, helps  # every daemon and spy has one
    # Q10's sentence first; a process may add what is particular to it.
    assert [h for h in helps if not h[1].startswith(Q10)] == []


def test_pm_help_describes_quiet_the_same_way() -> None:
    from edumatcher.pm_help import registry

    texts = {
        opt.help
        for cmd in registry.ALL_COMMANDS
        for opt in cmd.options
        if opt.flags.startswith("-q") and "warning" in opt.help.lower()
    }
    texts |= {
        opt.help for opt in registry.COMMON_LOG_OPTIONS if opt.flags.startswith("-q")
    }
    assert texts == {Q10}
