"""WP-OPC02: ``kill`` stops every pm-* program and nothing else.

``kill`` ran ``pkill -15 -f -i -l pm-``: procps-ng 4 rejects ``-l`` (nothing
signalled, yet every PID file deleted), and elsewhere ``-f -i pm-`` matched
any command line containing "pm-" -- npm, editors, the calling shell,
pm-opctl-cli itself (pm-opctl review 2026-11, H2).

The selection runs for real, but ``psutil.process_iter`` is narrowed to this
test's own children, so no other process on the host can ever be selected;
``subprocess.run`` fails, so the old ``pkill`` call cannot run either.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psutil
import pytest

from edumatcher.emo import cli as emo_cli

_SLEEP = "import time; time.sleep(60)\n"
_STUBBORN = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 1.0)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 2),
    )
    return tmp_path


@pytest.fixture
def procs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[subprocess.Popen[bytes]]]:
    """The test's children; the only processes psutil may iterate."""
    started: list[subprocess.Popen[bytes]] = []
    real_iter = psutil.process_iter

    def only_children(attrs: Any = None, ad_value: Any = None) -> Iterator[Any]:
        mine = {p.pid for p in started}
        for proc in real_iter(attrs, ad_value):
            if proc.pid in mine:
                yield proc

    monkeypatch.setattr(psutil, "process_iter", only_children)
    yield started
    for p in started:
        if p.poll() is None:
            p.kill()
            p.wait(5)


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return path


def _spawn(procs: list[Any], argv: list[str]) -> int:
    proc = subprocess.Popen(argv)
    procs.append(proc)
    return proc.pid


def _wait_started(pids: list[int]) -> None:
    """Until each script has been exec'd (its argv names the script)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(len(emo_cli.command_line(pid)) > 1 for pid in pids):
            return
        time.sleep(0.05)


@pytest.mark.parametrize(
    "cmdline, selected",
    [
        (["python3", "/v/bin/pm-engine", "--verbose"], True),
        (["pm-log-srv"], True),
        (["node", "/usr/lib/npm-cli.js"], False),
        (["vim", "pm-notes.md"], False),
        (["bash", "-c", "pm-opctl-cli kill"], False),
        (["rpm-ostree", "status"], False),
        (["python3", "-c", "x", "PM-ENGINE"], False),
    ],
)
def test_only_a_pm_program_is_selected(cmdline: list[str], selected: bool) -> None:
    assert emo_cli._is_pm_program(cmdline) is selected


def test_kill_signals_pm_programs_and_spares_the_rest(
    tmp_path: Path, procs: list[Any]
) -> None:
    engine = _spawn(procs, [str(_script(tmp_path, "pm-zzz-engine", _SLEEP))])
    stats = _spawn(procs, [str(_script(tmp_path, "pm-zzz-stats", _SLEEP))])
    other = _spawn(procs, [sys.executable, "-c", _SLEEP, "pm-notes.md"])
    _wait_started([engine, stats, other])
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.write_pid("engine", engine)
    emo_cli.write_active_profile("default")

    assert emo_cli.kill_all_processes() == 0
    time.sleep(0.2)
    assert not emo_cli.is_alive(engine) and not emo_cli.is_alive(stats)
    assert emo_cli.is_alive(other)
    assert not emo_cli.pid_path("engine").exists()
    assert emo_cli.read_active_profile() is None


def test_a_survivor_keeps_its_pid_file_and_fails_the_command(
    tmp_path: Path, procs: list[Any], capsys: Any
) -> None:
    stubborn = _spawn(procs, [str(_script(tmp_path, "pm-zzz-stubborn", _STUBBORN))])
    engine = _spawn(procs, [str(_script(tmp_path, "pm-zzz-engine", _SLEEP))])
    _wait_started([stubborn, engine])
    time.sleep(0.3)  # let the stubborn script install its handler
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.write_pid("stubborn", stubborn)
    emo_cli.write_pid("engine", engine)
    emo_cli.write_active_profile("default")

    assert emo_cli.kill_all_processes() == 1
    assert emo_cli.is_alive(stubborn)
    assert emo_cli.pid_path("stubborn").exists()
    assert not emo_cli.pid_path("engine").exists()
    assert emo_cli.read_active_profile() == "default"
    assert f"pid {stubborn}" in capsys.readouterr().err


def test_nothing_to_kill_is_success(procs: list[Any], capsys: Any) -> None:
    assert emo_cli.kill_all_processes() == 0
    assert "No running EduMatcher processes" in capsys.readouterr().out


def test_kill_skips_other_users_processes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, procs: list[Any]
) -> None:
    engine = _spawn(procs, [str(_script(tmp_path, "pm-zzz-engine", _SLEEP))])
    _wait_started([engine])
    monkeypatch.setattr(emo_cli, "owned_by_me", lambda pid: False)
    assert emo_cli.pm_processes() == []


def test_kill_also_stops_recorded_processes_that_are_not_pm_programs(
    procs: list[Any],
) -> None:
    """Holistic review HR3: a custom profile may run any command. Selecting
    only pm-* programs left such a process running while its PID file was
    deleted, so nothing tracked it any more."""
    other = _spawn(procs, [sys.executable, "-c", _SLEEP, "custom-entry"])
    _wait_started([other])
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.write_pid("custom", other)
    emo_cli.write_active_profile("default")

    assert emo_cli.kill_all_processes() == 0
    time.sleep(0.2)
    assert not emo_cli.is_alive(other)
    assert not emo_cli.pid_path("custom").exists()
