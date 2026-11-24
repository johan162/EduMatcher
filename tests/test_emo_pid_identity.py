"""WP-OPC01: a PID file names its own process, or it is not trusted.

A PID file survives every exit that is not a clean ``stop`` (a crash, a
killed container, a reboot), and its PID is later reused by another process.
pm-opctl-cli trusted any live PID: ``start`` skipped the real entry, ``list``
showed the stranger running and ``stop`` signalled it (pm-opctl review
2026-11, H1, C1). Re-adoption compared ``ps`` text, which loses the quoting
of an argument with a space (C3).

Every process here is a child of the test (a sleeping Python), killed in the
fixture's finalizer.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.emo import cli as emo_cli

_SLEEP = "import time; time.sleep(60)"


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def children() -> Iterator[list[int]]:
    """PIDs to kill after the test (strangers and profile processes)."""
    pids: list[int] = []
    yield pids
    for path in emo_cli.runtime_dir().glob("*.pid"):
        try:
            pids.append(int(path.read_text(encoding="ascii").split()[0]))
        except ValueError, IndexError:
            pass
    for pid in set(pids):
        if pid > 1:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError, PermissionError:
                pass


def _stranger(children: list[int]) -> int:
    proc = subprocess.Popen([sys.executable, "-c", _SLEEP])
    children.append(proc.pid)
    return proc.pid


def _profile(monkeypatch: pytest.MonkeyPatch, processes: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"default": processes})


def _sleeper(tag: str) -> list[str]:
    # A unique argv: re-adoption matches by command line, and another xdist
    # worker may be running the same test's sleeper at the same moment.
    return [sys.executable, "-c", _SLEEP, f"{tag}-{uuid.uuid4().hex}"]


def _alive(pid: int) -> bool:
    return emo_cli.is_alive(pid)


def test_a_reused_pid_is_not_taken_for_the_entry(
    monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    """The stale file of an earlier run holds a PID that a stranger has now."""
    stranger = _stranger(children)
    _profile(monkeypatch, [{"name": "a", "command": _sleeper("opc-a")}])
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.pid_path("a").write_text(f"{stranger}\n", encoding="ascii")
    emo_cli.write_active_profile("default")

    assert emo_cli.start_profile("default") == 0
    started = emo_cli.read_pid("a")
    assert started is not None and started != stranger

    assert emo_cli.stop_profile() == 0
    time.sleep(0.2)
    assert _alive(stranger), "stop signalled a process it never started"


def test_a_pid_file_of_another_process_start_is_stale(
    monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    stranger = _stranger(children)
    emo_cli.runtime_dir().mkdir(parents=True)
    start = emo_cli.process_start_time(stranger)
    assert start is not None
    emo_cli.pid_path("a").write_text(f"{stranger} {start - 1000.0}\n", encoding="ascii")
    assert emo_cli.read_pid("a") is None
    assert not emo_cli.pid_path("a").exists()


def test_stop_goes_on_past_a_pid_it_may_not_signal(
    monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    """PID 1 belongs to root: today's stop raised PermissionError and left
    every later entry running."""
    _profile(
        monkeypatch,
        [
            {"name": "a", "command": _sleeper("opc-a")},
            {"name": "b", "command": _sleeper("opc-b")},
        ],
    )
    assert emo_cli.start_profile("default") == 0
    b = emo_cli.read_pid("b")
    assert b is not None
    emo_cli.pid_path("a").write_text("1\n", encoding="ascii")  # a stale file

    assert emo_cli.stop_profile() == 0
    deadline = time.monotonic() + 5
    while _alive(b) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(b)


def test_a_signal_that_fails_is_reported_and_stop_goes_on(
    monkeypatch: pytest.MonkeyPatch, children: list[int], capsys: Any
) -> None:
    _profile(
        monkeypatch,
        [
            {"name": "a", "command": _sleeper("opc-a")},
            {"name": "b", "command": _sleeper("opc-b")},
        ],
    )
    assert emo_cli.start_profile("default") == 0
    a, b = emo_cli.read_pid("a"), emo_cli.read_pid("b")
    real_kill = os.kill

    def kill(pid: int, sig: int) -> None:
        if pid == a:
            raise PermissionError(1, "Operation not permitted")
        real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 0.5)
    assert emo_cli.stop_profile() == 1
    assert "a (pid" in capsys.readouterr().err
    assert b is not None
    deadline = time.monotonic() + 5
    while _alive(b) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(b)


def test_start_twice_reports_the_same_running_process(
    monkeypatch: pytest.MonkeyPatch, children: list[int], capsys: Any
) -> None:
    _profile(monkeypatch, [{"name": "a", "command": _sleeper("opc-a")}])
    assert emo_cli.start_profile("default") == 0
    first = emo_cli.read_pid("a")
    assert emo_cli.start_profile("default") == 0
    assert emo_cli.read_pid("a") == first
    assert f"already running a (pid {first})" in capsys.readouterr().out


def test_an_entry_with_a_spaced_argument_is_re_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    """The scheduler's ``--on-close "pm-eod run --pending"``: ``ps`` prints it
    as three words, so its lost PID file could never be recovered."""
    script = tmp_path / "pm-opctest-sched"
    script.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    script.chmod(0o755)
    command = [str(script), "--daily", "--on-close", "pm-eod run --pending"]
    _profile(monkeypatch, [{"name": "sched", "command": command}])
    assert emo_cli.start_profile("default") == 0
    pid = emo_cli.read_pid("sched")
    assert pid is not None
    time.sleep(0.3)  # let the interpreter exec the script
    emo_cli.pid_path("sched").unlink()

    claimed: set[int] = set()
    assert emo_cli.resolve_pid({"name": "sched", "command": command}, claimed) == (
        pid,
        True,
    )


def test_a_debug_start_is_listed_as_running(
    monkeypatch: pytest.MonkeyPatch, children: list[int], capsys: Any
) -> None:
    _profile(
        monkeypatch,
        [
            {"name": "a", "command": _sleeper("opc-a")},
            {"name": "b", "command": _sleeper("opc-b")},
        ],
    )
    assert emo_cli.start_profile("default", debug=True) == 0
    capsys.readouterr()
    assert emo_cli.list_profile("never", probe_tcp=False) == 0
    out = capsys.readouterr().out
    assert out.count("running") == 2 and "dead" not in out


def test_stop_re_adopts_an_entry_whose_pid_file_is_lost(
    monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    """A lost or stale PID file (a bare PID written by an earlier version
    included) must not leave its process running after ``stop``."""
    _profile(
        monkeypatch,
        [
            {"name": "a", "command": _sleeper("opc-a")},
            {"name": "b", "command": _sleeper("opc-b")},
        ],
    )
    assert emo_cli.start_profile("default") == 0
    a = emo_cli.read_pid("a")
    assert a is not None
    children.append(a)
    emo_cli.pid_path("a").write_text(f"{a}\n", encoding="ascii")  # no start time

    assert emo_cli.stop_profile() == 0
    deadline = time.monotonic() + 5
    while _alive(a) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(a)


def test_re_adoption_ignores_other_users_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pgrep lists every user's processes: on a shared host another
    student's identical stack must never be adopted (and later signalled)."""
    process = {"name": "engine", "command": ["pm-engine", "--verbose"]}
    monkeypatch.setattr(emo_cli, "pgrep_pids", lambda program: [30, 40])
    monkeypatch.setattr(
        emo_cli, "command_line", lambda pid: ["python", "pm-engine", "--verbose"]
    )
    monkeypatch.setattr(emo_cli, "owned_by_me", lambda pid: pid == 40)
    assert emo_cli.discover_pid(process, set()) == 40


def test_a_clock_step_does_not_orphan_a_debug_started_process(
    monkeypatch: pytest.MonkeyPatch, children: list[int]
) -> None:
    """Holistic review HR2: psutil's start time is boot time + ticks, and the
    kernel's boot time moves when the wall clock is stepped. A ``--debug``
    start (extra arguments) cannot be re-adopted by the profile's argv, so it
    must still be recognised from its own PID file."""
    _profile(monkeypatch, [{"name": "a", "command": _sleeper("opc-a")}])
    assert emo_cli.start_profile("default", debug=True) == 0
    pid = emo_cli.read_pid("a")
    assert pid is not None
    real_start = emo_cli.process_start_time
    monkeypatch.setattr(
        emo_cli, "process_start_time", lambda p: (real_start(p) or 0.0) + 37.0
    )
    assert emo_cli.read_pid("a") == pid
    assert emo_cli.stop_profile() == 0
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


def test_a_stopped_survivor_found_by_re_adoption_keeps_a_pid_file(
    monkeypatch: pytest.MonkeyPatch, children: list[int], tmp_path: Path
) -> None:
    """Holistic review HR1: ``stop`` said "PID file kept" for a survivor it
    had re-adopted, which had no PID file."""
    script = tmp_path / "pm-opctest-stubborn"
    ready = tmp_path / "stubborn.ready"
    script.write_text(
        f"#!{sys.executable}\nimport pathlib, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"pathlib.Path({str(ready)!r}).touch()\ntime.sleep(60)\n"
    )
    script.chmod(0o755)
    command = [str(script), "--tag", uuid.uuid4().hex]
    _profile(monkeypatch, [{"name": "s", "command": command}])
    monkeypatch.setattr(emo_cli, "STOP_WAIT_SEC", 0.5)
    assert emo_cli.start_profile("default") == 0
    pid = emo_cli.read_pid("s")
    assert pid is not None
    deadline = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists(), "the stubborn script never installed its handler"
    emo_cli.pid_path("s").unlink()

    assert emo_cli.stop_profile() == 1
    assert emo_cli.read_pid("s") == pid


def test_a_framework_python_matches_the_interpreter_it_was_launched_as() -> None:
    """A macOS framework Python re-executes itself as ``Python.app/.../Python``."""
    running = ["/f/Python.app/Contents/MacOS/Python", "-c", "code", "tag"]
    assert emo_cli.matches_command(running, ["/v/bin/python", "-c", "code", "tag"])
    assert not emo_cli.matches_command(running, ["/v/bin/python", "-c", "other"])
    assert not emo_cli.matches_command(running, ["/v/bin/python-tool", "-c", "code"])


def test_a_reused_pid_running_another_command_is_stale_even_with_an_argv(
    children: list[int],
) -> None:
    stranger = _stranger(children)
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.pid_path("a").write_text(
        f'{stranger} 1.0\n["pm-engine", "--verbose"]\n', encoding="ascii"
    )
    assert emo_cli.read_pid("a") is None
    assert not emo_cli.pid_path("a").exists()
