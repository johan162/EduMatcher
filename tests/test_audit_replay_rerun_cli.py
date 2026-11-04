"""``pm-audit-replay rerun``: the audit's commands through a fresh engine (A4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.audit.replay.cli import main
from tests.test_sim_forensics_rerun import edit, record


def run(data: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["--log-file", str(data / "audit.log"), "rerun"])
    return code, capsys.readouterr().out


def test_a_clean_run_exits_zero_and_says_what_it_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(record(tmp_path / "data"), capsys)
    assert code == 0
    assert "8 commands" in out
    assert "hidden inputs: 0" in out
    assert "outputs: 0 differing episodes" in out
    assert "final book: 0 differences" in out


def test_a_silent_gateway_expiry_counts_as_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(record(tmp_path / "data", silent="TRADER02"), capsys)
    assert code == 0
    assert "9 commands" in out
    assert "hidden inputs: 0" in out


def test_a_difference_exits_one_and_names_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[order.ack.TRADER02]", lambda ln: [])
    code, out = run(data, capsys)
    assert code == 1
    assert "hidden inputs: 0" not in out or "outputs: 0" not in out


def test_a_trail_without_the_engine_start_is_unavailable_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[system.startup]", lambda ln: [])
    code = main(["--log-file", str(data / "audit.log"), "rerun"])
    assert code == 3
    assert "cannot re-run" in capsys.readouterr().err


def test_a_missing_book_file_is_said_not_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    (data / "gtc_orders.json").unlink()
    code, out = run(data, capsys)
    assert code == 0
    assert "final book: not checked" in out


def test_a_run_that_is_not_the_first_start_of_its_data_dir_reruns_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The engine's run sequence persists across starts (it prefixes every trade
    id and rides on every trade), so the ninth start of a data dir is the
    ordinary case, not the first.  The re-run takes it from `system.startup`."""
    code, out = run(record(tmp_path / "data", run_seq=9), capsys)
    assert code == 0, out
    assert "outputs: 0 differing episodes" in out
