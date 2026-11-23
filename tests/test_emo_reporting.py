"""WP-OPC03: ``start`` and ``stop`` report what really happened.

``stop`` deleted the PID file of a process that ignored SIGTERM and exited 0,
so a second ``stop`` found nothing; ``start`` printed a process that died at
once as ``started`` and exited 0 (pm-opctl review 2026-11, C2, C4).

Every process is a child of the test, killed in the fixture's finalizer.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.emo import cli as emo_cli

_SLEEP = "import time; time.sleep(60)"
_STUBBORN = (
    "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
    "time.sleep(60)"
)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 1.0)
    return tmp_path


@pytest.fixture(autouse=True)
def _cleanup() -> Iterator[None]:
    yield
    for path in emo_cli.runtime_dir().glob("*.pid"):
        try:
            os.kill(int(path.read_text(encoding="ascii").split()[0]), signal.SIGKILL)
        except ValueError, IndexError, ProcessLookupError, PermissionError:
            pass


def _profile(monkeypatch: pytest.MonkeyPatch, processes: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"default": processes})


def _py(code: str, tag: str) -> list[str]:
    # Unique per call: re-adoption matches argv across xdist workers.
    return [sys.executable, "-c", code, f"{tag}-{uuid.uuid4().hex}"]


def _wait_for(pid: int, alive: bool) -> None:
    deadline = time.monotonic() + 5
    while emo_cli.is_alive(pid) != alive and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_survivor_keeps_its_pid_file_and_fails_stop(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    # The survivor is in the first wave; the later wave must still be reached.
    _profile(
        monkeypatch,
        [
            {"name": "stubborn", "command": _py(_STUBBORN, "opc-stubborn")},
            {"name": "late", "command": _py(_SLEEP, "opc-late")},
        ],
    )
    monkeypatch.setattr(
        emo_cli, "stop_wave", lambda name, programs: 0 if name == "stubborn" else 1
    )
    assert emo_cli.start_profile("default") == 0
    time.sleep(0.5)  # let the stubborn one install its handler
    stubborn, late = emo_cli.read_pid("stubborn"), emo_cli.read_pid("late")
    assert stubborn is not None and late is not None
    capsys.readouterr()

    assert emo_cli.stop_profile() == 1
    captured = capsys.readouterr()
    assert f"stubborn (pid {stubborn})" in captured.err
    assert emo_cli.pid_path("stubborn").exists()
    _wait_for(late, alive=False)
    assert not emo_cli.is_alive(late)
    assert not emo_cli.pid_path("late").exists()

    assert emo_cli.stop_profile() == 1  # tried again, still there
    assert emo_cli.is_alive(stubborn)


def test_a_clean_stop_exits_zero_and_removes_every_pid_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _profile(monkeypatch, [{"name": "a", "command": _py(_SLEEP, "opc-a")}])
    assert emo_cli.start_profile("default") == 0
    assert emo_cli.stop_profile() == 0
    assert not list(emo_cli.runtime_dir().glob("*.pid"))


def test_start_reports_a_process_that_exited_at_once(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _profile(
        monkeypatch,
        [
            {"name": "crashes", "command": _py("import sys; sys.exit(3)", "opc-x")},
            {"name": "a", "command": _py(_SLEEP, "opc-a")},
        ],
    )
    assert emo_cli.start_profile("default") == 1
    err = capsys.readouterr().err
    assert "crashes" in err and "exit code 3" in err
    assert str(emo_cli.log_path("crashes")) in err
    assert emo_cli.read_pid("a") is not None


def test_a_running_entry_is_not_reported_as_exited(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    _profile(monkeypatch, [{"name": "a", "command": _py(_SLEEP, "opc-a")}])
    assert emo_cli.start_profile("default") == 0
    assert emo_cli.start_profile("default") == 0
    assert "exited" not in capsys.readouterr().err


def test_the_container_survives_a_process_that_exits_at_start() -> None:
    """The entrypoint runs under ``set -e``: ``start`` now exits 1 when a
    process died at once (a bot that raced the engine), which must leave the
    container up for EM_RESTART_DEAD and `make status`, not end PID 1."""
    script = (
        Path(__file__).resolve().parents[1] / "deployment/docker/entrypoint.sh"
    ).read_text()
    assert "set -euo pipefail" in script
    starts = [
        line.strip()
        for line in script.splitlines()
        if "pm-opctl-cli start" in line and not line.strip().startswith("#")
    ]
    assert starts, "the entrypoint no longer starts a profile"
    for line in starts:
        assert line.startswith("if ! pm-opctl-cli start") or "||" in line, line
