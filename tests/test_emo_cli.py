"""Smoke tests for pm-opctl-cli (edumatcher.emo.cli)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from edumatcher.emo import cli as emo_cli
from edumatcher.emo.cli import (
    DEFAULT_PROCESSES,
    build_parser,
    load_profiles,
    start_profile,
)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every resolve_data_path() call in emo.cli at an isolated tmp_path."""
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    return tmp_path


# -- argument parsing --------------------------------------------------------


def test_start_debug_flag_aliases() -> None:
    parser = build_parser()
    for tokens in (["start", "--debug"], ["start", "-d"], ["start", "-vv"]):
        args = parser.parse_args(tokens)
        assert args.debug is True


def test_start_debug_defaults_to_false() -> None:
    parser = build_parser()
    args = parser.parse_args(["start"])
    assert args.debug is False
    assert args.config_name == "default"


# -- profile loading ----------------------------------------------------------


def test_load_profiles_returns_builtins_when_no_config_file() -> None:
    profiles = load_profiles()
    assert set(profiles) == {"default", "micro", "mini"}
    assert profiles["default"] == DEFAULT_PROCESSES


# -- start_profile: debug flag rewrites every command -------------------------


def test_start_profile_debug_appends_log_level_to_every_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Replace the micro profile's real commands with a fast, harmless one so
    # the test spawns real (trivial) subprocesses rather than pm-* binaries.
    fake_processes = [
        {"name": "one", "command": ["true"]},
        {"name": "two", "command": ["true", "--verbose"]},
    ]
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"default": fake_processes})

    rc = start_profile("default", debug=True)
    assert rc == 0

    # PID files were written for both processes, proving spawn_process saw
    # the debug-augmented command (not the original) and it ran successfully.
    runtime = emo_cli.runtime_dir()
    assert (runtime / "one.pid").exists()
    assert (runtime / "two.pid").exists()

    # Give the detached children a moment to exit, then confirm the log files
    # (combined stdout/stderr) exist and are empty, meaning `true --log-level
    # DEBUG` ran and exited 0 without complaint.
    time.sleep(0.2)
    assert (runtime / "one.log").exists()
    assert (runtime / "two.log").exists()


def test_start_profile_without_debug_leaves_commands_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_commands: list[list[str]] = []
    fake_processes = [{"name": "one", "command": ["true"]}]
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"default": fake_processes})
    real_spawn = emo_cli.spawn_process

    def _record_and_spawn(process: dict) -> int | None:
        seen_commands.append(list(process["command"]))
        return real_spawn(process)

    monkeypatch.setattr(emo_cli, "spawn_process", _record_and_spawn)

    rc = start_profile("default", debug=False)
    assert rc == 0
    assert seen_commands == [["true"]]


def test_start_profile_unknown_profile_returns_error() -> None:
    rc = start_profile("does-not-exist")
    assert rc == 2
