"""WP-OPC03: ``start`` and ``stop`` report what really happened.

``stop`` deleted the PID file of a process that ignored SIGTERM and exited 0,
so a second ``stop`` found nothing; ``start`` printed a process that died at
once as ``started`` and exited 0 (pm-opctl review 2026-11, C2, C4).

Every process is a child of the test, killed in the fixture's finalizer.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

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


def test_a_stop_budget_leaves_the_later_waves_their_share(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """L045: the container's grace period is a total, and each wave waited
    up to 15 s of it, so a slow early wave (the engine persisting a large
    book) used the time of the recorders and the log server and Docker
    SIGKILLed them. With a budget, a wave waits at most its share of what is
    left, and the stop ends inside the budget."""
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 15.0)
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

    began = time.monotonic()
    assert emo_cli.stop_profile(budget_sec=2.0) == 1
    elapsed = time.monotonic() - began

    assert elapsed < 3.0, f"stop overran its 2 s budget: {elapsed:.1f} s"
    assert not emo_cli.is_alive(late)  # the later wave was reached in time
    assert emo_cli.is_alive(stubborn) and emo_cli.pid_path("stubborn").exists()
    assert f"stubborn (pid {stubborn})" in capsys.readouterr().err


def test_a_fast_wave_passes_its_unused_share_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The share is of the time left, not a fixed slice: when the first wave
    exits at once, a stubborn last wave may use nearly the whole budget."""
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 15.0)
    _profile(
        monkeypatch,
        [
            {"name": "quick", "command": _py(_SLEEP, "opc-quick")},
            {"name": "stubborn", "command": _py(_STUBBORN, "opc-stubborn")},
        ],
    )
    monkeypatch.setattr(
        emo_cli, "stop_wave", lambda name, programs: 0 if name == "quick" else 1
    )
    assert emo_cli.start_profile("default") == 0
    time.sleep(0.5)

    began = time.monotonic()
    assert emo_cli.stop_profile(budget_sec=2.0) == 1
    elapsed = time.monotonic() - began

    assert 1.5 < elapsed < 3.0, f"{elapsed:.2f} s"


def test_the_container_stops_within_its_grace_period() -> None:
    """L045: the entrypoint gives ``stop`` a total budget, and every compose
    file gives the exchange container more than that before Docker's SIGKILL,
    with room for tini and the entrypoint to exit after it."""
    repo = Path(__file__).resolve().parents[1]
    script = (repo / "deployment/docker/entrypoint.sh").read_text()
    stops = [
        line.strip()
        for line in script.splitlines()
        if "pm-opctl-cli stop" in line and not line.strip().startswith("#")
    ]
    assert stops == ['pm-opctl-cli stop --timeout "${STOP_TIMEOUT}" || true']
    default = re.search(
        r'^    local value="\$\{EM_STOP_TIMEOUT:-(\d+)\}"$', script, re.M
    )
    assert default, "the entrypoint no longer defaults EM_STOP_TIMEOUT"
    budget = int(default.group(1))
    # Enough for every wave (wave 0 is everything else) at its unbudgeted
    # 15 s, so the budget only ever bites on a stop that is already slow.
    assert budget >= (len(emo_cli.STOP_WAVES) + 1) * emo_cli.STOP_WAIT_SEC

    for name in (
        "docker/compose.yaml",
        "docker/compose.ai-sim.yaml",
        "curl/compose.yaml",
        "curl/compose.ai-sim.yaml",
    ):
        services = yaml.safe_load((repo / "deployment" / name).read_text())["services"]
        graces = {
            service: str(spec["stop_grace_period"])
            for service, spec in services.items()
            if "stop_grace_period" in spec
        }
        assert list(graces) == ["edumatcher"], (name, graces)
        grace = int(graces["edumatcher"].removesuffix("s"))
        override = services["edumatcher"].get("environment", {}).get("EM_STOP_TIMEOUT")
        assert override is None, f"{name} sets EM_STOP_TIMEOUT={override!r}"
        assert grace >= budget + 10, (name, grace, budget)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", "60"),
        ("45", "45"),
        ("12.5", "12.5"),
        ("0", "60"),
        ("abc", "60"),
        ("-5", "60"),
    ],
)
def test_an_unusable_stop_budget_falls_back_to_the_default(
    value: str, expected: str
) -> None:
    """``stop --timeout abc`` is a usage error (exit 2) that signals nothing,
    and the entrypoint's ``|| true`` would hide it: the container would then
    be SIGKILLed without a clean stop at all. The entrypoint uses 60 instead."""
    script = Path(__file__).resolve().parents[1] / "deployment/docker/entrypoint.sh"
    probe = (
        "log() { :; }\n"
        f"eval \"$(sed -n '/^stop_timeout()/,/^}}/p' {script})\"\n"
        "stop_timeout\n"
    )
    env = {**os.environ, "EM_STOP_TIMEOUT": value}
    if not value:
        env.pop("EM_STOP_TIMEOUT")
    out = subprocess.run(
        ["bash", "-c", probe], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == expected


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
