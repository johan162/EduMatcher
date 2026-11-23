"""WP-OPC04: ``clear`` never deletes under a running process and covers every
data file (pm-opctl review 2026-11, C5, C6).

A running pm-clearing or pm-stats keeps writing to the unlinked database, and
the engine rewrites the GTC files at its next checkpoint, so a clear under a
live stack loses data and is undone. ``market_sim_state.json`` brought the
old market back after ``clear --state``.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from edumatcher import config
from edumatcher.emo import cli as emo_cli


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "clearing.db"
    state.write_text("x")
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STATE_PATHS", (state,))
    monkeypatch.setattr(emo_cli, "NON_STATE_PATHS", ())
    return state


def test_clear_refuses_while_pm_processes_run(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(emo_cli, "_running_pm_pids", lambda: ["pm-clearing (pid 7)"])
    assert emo_cli.clear_data(scope="state", assume_yes=True) == 1
    assert data.exists()
    err = capsys.readouterr().err
    assert "pm-clearing (pid 7)" in err and "--force" in err


def test_force_clears_under_running_processes(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setattr(emo_cli, "_running_pm_pids", lambda: ["pm-clearing (pid 7)"])
    assert emo_cli.clear_data(scope="state", assume_yes=True, force=True) == 0
    assert not data.exists()
    assert "pm-clearing (pid 7)" in capsys.readouterr().out


def test_force_is_a_clear_option() -> None:
    args = emo_cli.build_parser().parse_args(["clear", "--state", "--yes", "--force"])
    assert args.force is True


def test_the_cleared_paths_are_the_writers_own_paths() -> None:
    """Each file clear knows by name is the one its writer really uses."""
    from edumatcher.ai_trader import worker
    from edumatcher.market_sim import main as market_sim
    from edumatcher.market_sim import news_history

    assert market_sim.STATE_FILE in emo_cli.STATE_PATHS
    assert config.AUDIT_REPLAY_DB_FILE in emo_cli.NON_STATE_PATHS
    assert news_history.NEWS_HISTORY_DB in emo_cli.NON_STATE_PATHS
    summary_dir = inspect.signature(worker.Worker).parameters["summary_dir"]
    assert summary_dir.default == config.DATA_DIR / "ai_swarm"
    assert config.DATA_DIR / "ai_swarm" in emo_cli.NON_STATE_PATHS
    assert config.DATA_DIR / "eod" in emo_cli.NON_STATE_PATHS


def test_kept_files_are_in_neither_scope() -> None:
    every = (*emo_cli.STATE_PATHS, *emo_cli.NON_STATE_PATHS)
    assert config.RUN_SEQ_FILE not in every
    assert config.DATA_DIR / "companies.db" not in every
    assert config.REF_DATA_DIR not in every
