"""Smoke tests for pm-opctl-cli (edumatcher.emo.cli)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from edumatcher.config import ENGINE_CONFIG_FILE
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


# -- profile configuration is an operator contract ---------------------------


def test_custom_profiles_accept_shell_strings_and_backfill_default(
    _data_dir: Path,
) -> None:
    emo_cli.config_path().write_text(
        "workers:\n"
        "  processes:\n"
        "    - name: engine\n"
        "      command: 'pm-engine --verbose'\n"
        "      healthcheck: 'pm-stats-cli health -q'\n"
        "      tcp: 127.0.0.1:5555\n",
        encoding="utf-8",
    )

    profiles = load_profiles()

    assert profiles["workers"] == [
        {
            "name": "engine",
            "command": ["pm-engine", "--verbose"],
            "healthcheck": ["pm-stats-cli", "health", "-q"],
            "tcp": "127.0.0.1:5555",
        }
    ]
    assert profiles["default"] == DEFAULT_PROCESSES


@pytest.mark.parametrize(
    "document, message",
    [
        ("- not-a-mapping\n", "must contain a mapping"),
        ("'': []\n", "profile names must be non-empty"),
        ("demo: not-a-list\n", "processes must be a list"),
        ("demo: [not-a-mapping]\n", "process 0 must be a mapping"),
        ("demo: [{command: [pm-engine]}]\n", "needs a name"),
        ("demo: [{name: engine, command: []}]\n", "needs a command"),
        (
            "demo: [{name: engine, command: [pm-engine], healthcheck: []}]\n",
            "healthcheck must be a command",
        ),
        (
            "demo: [{name: engine, command: [pm-engine], tcp: localhost}]\n",
            "tcp must be host:port",
        ),
        (
            "demo: [{name: engine, command: [pm-engine], tcp: localhost:http}]\n",
            "tcp port must be numeric",
        ),
        (
            "demo:\n  - {name: engine, command: [pm-engine]}\n"
            "  - {name: engine, command: [pm-stats]}\n",
            "repeats process name",
        ),
    ],
)
def test_invalid_profile_configuration_is_rejected_before_processes_start(
    document: str, message: str
) -> None:
    emo_cli.config_path().write_text(document, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_profiles()


def test_empty_config_uses_safe_default_profile() -> None:
    emo_cli.config_path().write_text("", encoding="utf-8")
    assert load_profiles() == {"default": DEFAULT_PROCESSES}


def test_init_creates_editable_profiles_but_never_overwrites(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert emo_cli.create_config() == 0
    created = emo_cli.config_path().read_text(encoding="utf-8")
    assert set(emo_cli.load_profiles()) == {"default", "micro", "mini"}

    assert emo_cli.create_config() == 1
    assert emo_cli.config_path().read_text(encoding="utf-8") == created
    assert "Refusing to overwrite" in capsys.readouterr().err


# -- process identity and adoption -------------------------------------------


@pytest.mark.parametrize(
    "cmdline, command, expected",
    [
        ("python /venv/bin/pm-engine --verbose", ["pm-engine", "--verbose"], True),
        ("/venv/bin/pm-engine --quiet", ["pm-engine", "--verbose"], False),
        ("python pm-stats --verbose", ["pm-engine", "--verbose"], False),
        ('python "unterminated', ["pm-engine"], False),
    ],
)
def test_command_matching_requires_program_and_every_argument(
    cmdline: str, command: list[str], expected: bool
) -> None:
    assert emo_cli.matches_command(cmdline, command) is expected


def test_read_pid_distinguishes_missing_dead_and_permission_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert emo_cli.read_pid("engine") is None

    emo_cli.pid_path("engine").parent.mkdir(parents=True)
    emo_cli.pid_path("engine").write_text("123\n", encoding="ascii")
    monkeypatch.setattr(os, "kill", Mock(side_effect=ProcessLookupError))
    assert emo_cli.read_pid("engine") is None
    assert not emo_cli.pid_path("engine").exists()

    emo_cli.pid_path("engine").write_text("456\n", encoding="ascii")
    monkeypatch.setattr(os, "kill", Mock(side_effect=PermissionError))
    assert emo_cli.read_pid("engine") == 456


def test_resolve_pid_prefers_recorded_pid_and_re_adopts_matching_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = {"name": "engine", "command": ["pm-engine", "--verbose"]}
    claimed: set[int] = set()
    monkeypatch.setattr(emo_cli, "read_pid", lambda name: 101)
    discover = Mock(return_value=202)
    monkeypatch.setattr(emo_cli, "discover_pid", discover)

    assert emo_cli.resolve_pid(process, claimed) == (101, False)
    assert claimed == {101}
    discover.assert_not_called()

    monkeypatch.setattr(emo_cli, "read_pid", lambda name: None)
    assert emo_cli.resolve_pid(process, claimed) == (202, True)
    assert emo_cli.pid_path("engine").read_text(encoding="ascii") == "202\n"


def test_discovery_skips_self_and_claimed_before_matching_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = {"name": "engine", "command": ["pm-engine", "--verbose"]}
    monkeypatch.setattr(os, "getpid", lambda: 10)
    monkeypatch.setattr(emo_cli, "pgrep_pids", lambda program: [10, 20, 30, 40])
    lines = {30: "python pm-engine --quiet", 40: "python pm-engine --verbose"}
    monkeypatch.setattr(emo_cli, "command_line", lambda pid: lines[pid])

    assert emo_cli.discover_pid(process, {20}) == 40


# -- health semantics ---------------------------------------------------------


def test_healthcheck_takes_precedence_over_tcp_and_exit_code_changes_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = {
        "name": "stats",
        "command": ["pm-stats"],
        "healthcheck": ["pm-stats-cli", "health", "-q"],
        "tcp": "127.0.0.1:9999",
    }
    tcp = Mock(return_value=("running", "tcp ok"))
    monkeypatch.setattr(emo_cli, "check_tcp", tcp)
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0)),
    )
    assert emo_cli.check_health(process, 123) == ("running", "healthcheck passed")
    tcp.assert_not_called()

    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 7)),
    )
    assert emo_cli.check_health(process, 123) == (
        "not responding",
        "healthcheck exit 7",
    )


def test_health_distinguishes_dead_failed_probe_and_unchecked_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert emo_cli.check_health({"name": "engine"}, None) == (
        "dead",
        "process is not running",
    )
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("hc", 2))
    )
    state, detail = emo_cli.check_health(
        {"healthcheck": ["check"], "tcp": "ignored:1"}, 1
    )
    assert state == "not responding"
    assert "timed out" in detail
    assert emo_cli.check_health({}, 1) == (
        "running",
        "no healthcheck or tcp check configured",
    )


def test_tcp_probe_reports_acceptance_and_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(socket, "create_connection", Mock(return_value=connection))
    assert emo_cli.check_tcp("127.0.0.1:5555")[0] == "running"

    monkeypatch.setattr(
        socket, "create_connection", Mock(side_effect=ConnectionRefusedError)
    )
    assert emo_cli.check_tcp("127.0.0.1:5555")[0] == "not responding"


@pytest.mark.parametrize(
    "elapsed, expected",
    [("01:30", 1.5), ("02:01:30", 121.5), ("2-02:01:30", 3001.5)],
)
def test_elapsed_time_formats_preserve_days_hours_and_seconds(
    elapsed: str, expected: float
) -> None:
    assert emo_cli.parse_etime(elapsed) == expected


@pytest.mark.parametrize("elapsed", ["", "1", "1:xx", "x-01:02:03", "1:2:3:4"])
def test_invalid_elapsed_time_is_unknown(elapsed: str) -> None:
    assert emo_cli.parse_etime(elapsed) is None


def test_health_profile_exit_status_reflects_every_process(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    processes = [{"name": "engine"}, {"name": "stats"}]
    monkeypatch.setattr(emo_cli, "read_active_profile", lambda: "demo")
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"demo": processes})
    monkeypatch.setattr(emo_cli, "resolve_pid", lambda process, claimed: (1, False))
    states = iter([("running", "ok"), ("not responding", "timeout")])
    monkeypatch.setattr(emo_cli, "check_health", lambda process, pid: next(states))

    assert emo_cli.health_profile(quiet=False) == 1
    output = capsys.readouterr().out
    assert "engine" in output and "stats" in output
    assert "health: FAIL" in output

    states = iter([("running", "ok"), ("running", "ok")])
    monkeypatch.setattr(emo_cli, "check_health", lambda process, pid: next(states))
    assert emo_cli.health_profile(quiet=True) == 0
    assert capsys.readouterr().out == ""


def test_list_restarts_only_dead_processes_when_requested(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    processes = [{"name": "engine"}, {"name": "stats"}]
    monkeypatch.setattr(emo_cli, "read_active_profile", lambda: "demo")
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"demo": processes})
    pids = iter([(11, False), (None, False)])
    monkeypatch.setattr(emo_cli, "resolve_pid", lambda process, claimed: next(pids))
    monkeypatch.setattr(
        emo_cli,
        "check_health",
        lambda process, pid: ("running", "ok") if pid else ("dead", "gone"),
    )
    monkeypatch.setattr(emo_cli, "process_stats", lambda pid: (61.0, 12.5))
    restart = Mock()
    monkeypatch.setattr(emo_cli, "restart_dead", restart)

    assert emo_cli.list_profile(restart="always") == 0
    restart.assert_called_once_with([{"name": "stats"}], assume_yes=True)
    output = capsys.readouterr().out
    assert "01:01" in output and "12.5" in output and "gone" in output


# -- lifecycle and destructive-operation safety ------------------------------


def test_start_skips_running_process_and_stops_after_spawn_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = [
        {"name": "running", "command": ["one"]},
        {"name": "broken", "command": ["two"]},
        {"name": "never", "command": ["three"]},
    ]
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: {"demo": processes})
    existing = iter([(10, False), (None, False)])
    monkeypatch.setattr(emo_cli, "resolve_pid", lambda process, claimed: next(existing))
    spawn = Mock(return_value=None)
    monkeypatch.setattr(emo_cli, "spawn_process", spawn)

    assert emo_cli.start_profile("demo") == 1
    spawn.assert_called_once_with(processes[1])
    assert emo_cli.read_active_profile() == "demo"


def test_stop_signals_only_live_managed_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emo_cli.runtime_dir().mkdir(parents=True)
    for name in ("live", "stale"):
        emo_cli.pid_path(name).write_text("1\n", encoding="ascii")
    emo_cli.write_active_profile("demo")
    monkeypatch.setattr(
        emo_cli, "read_pid", lambda name: 101 if name == "live" else None
    )
    kill = Mock()
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    assert emo_cli.stop_profile() == 0
    kill.assert_called_once_with(101, signal.SIGTERM)
    assert not list(emo_cli.runtime_dir().glob("*.pid"))
    assert emo_cli.read_active_profile() is None


@pytest.mark.parametrize("returncode, expected", [(0, 0), (1, 0), (9, 9)])
def test_emergency_kill_translates_pkill_outcomes(
    returncode: int, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], returncode)),
    )
    assert emo_cli.kill_all_processes() == expected


def test_clear_state_preserves_logs_configuration_and_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "book_stats.json"
    state_dir = tmp_path / "indexes"
    log_file = tmp_path / "log.db"
    config_file = tmp_path / "ref_data" / "engine_config.yaml"
    state_file.write_text("state", encoding="utf-8")
    state_dir.mkdir()
    (state_dir / "levels.json").write_text("state", encoding="utf-8")
    log_file.write_text("log", encoding="utf-8")
    config_file.parent.mkdir()
    config_file.write_text("config", encoding="utf-8")
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STATE_PATHS", (state_file, state_dir))
    monkeypatch.setattr(emo_cli, "NON_STATE_PATHS", (log_file,))
    monkeypatch.setattr(emo_cli, "_running_pm_pids", lambda: [])

    assert emo_cli.clear_data(scope="state", assume_yes=True) == 0
    assert not state_file.exists() and not state_dir.exists()
    assert log_file.exists() and config_file.exists()


def test_clear_all_requires_confirmation_and_warns_about_live_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_file = tmp_path / "state"
    log_file = tmp_path / "log"
    state_file.write_text("state", encoding="utf-8")
    log_file.write_text("log", encoding="utf-8")
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STATE_PATHS", (state_file,))
    monkeypatch.setattr(emo_cli, "NON_STATE_PATHS", (log_file,))
    monkeypatch.setattr(emo_cli, "_running_pm_pids", lambda: [10, 20])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    assert emo_cli.clear_data(scope="all", assume_yes=False) == 1
    assert state_file.exists() and log_file.exists()
    captured = capsys.readouterr()
    assert "2 pm-* process(es)" in captured.out
    assert "Refusing to clear without --yes" in captured.err


def test_show_json_is_machine_readable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(emo_cli, "package_version", lambda: "9.8.7")
    assert emo_cli.show_info(json_output=True) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["version"] == "9.8.7"
    assert shown["config_source"] == str(ENGINE_CONFIG_FILE)


@pytest.mark.parametrize(
    "argv, expected_message",
    [
        (["clear", "--state", "--all"], "Only one"),
        (["clear"], "One of"),
    ],
)
def test_clear_cli_requires_exactly_one_scope(
    argv: list[str],
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-opctl-cli", *argv])
    assert emo_cli.main() == 2
    assert expected_message in capsys.readouterr().err


# -- degraded host tools and command dispatch --------------------------------


def test_process_discovery_helpers_degrade_safely_when_host_tools_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=FileNotFoundError("missing"))
    )
    assert emo_cli.pgrep_pids("pm-engine") == []
    assert emo_cli.command_line(123) == ""


def test_process_discovery_ignores_non_numeric_pgrep_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, "12\nnoise\n34\n", "")),
    )
    assert emo_cli.pgrep_pids("pm-engine") == [12, 34]


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ("01:30 2048\n", (1.5, 2.0)),
        ("01:30 unknown\n", (1.5, None)),
        ("incomplete\n", (None, None)),
    ],
)
def test_process_stats_report_only_available_metrics(
    stdout: str,
    expected: tuple[float | None, float | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, stdout, "")),
    )
    assert emo_cli.process_stats(123) == expected


def test_process_stats_are_unknown_when_ps_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        Mock(side_effect=subprocess.TimeoutExpired("ps", 2)),
    )
    assert emo_cli.process_stats(123) == (None, None)


@pytest.mark.parametrize(
    "active, profiles, expected_text",
    [
        (None, {}, "No pm-opctl profile"),
        ("removed", {"other": []}, "no longer defined"),
    ],
)
def test_list_refuses_to_invent_status_without_an_active_defined_profile(
    active: str | None,
    profiles: dict[str, list[dict]],
    expected_text: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(emo_cli, "read_active_profile", lambda: active)
    monkeypatch.setattr(emo_cli, "load_profiles", lambda: profiles)
    assert emo_cli.list_profile() == 1
    captured = capsys.readouterr()
    assert expected_text in captured.out + captured.err


@pytest.mark.parametrize("quiet", [False, True])
def test_health_without_active_profile_is_unhealthy_and_quiet_is_silent(
    quiet: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(emo_cli, "read_active_profile", lambda: None)
    assert emo_cli.health_profile(quiet=quiet) == 1
    assert bool(capsys.readouterr().err) is (not quiet)


@pytest.mark.parametrize("answer, expected_spawns", [("no", 0), ("yes", 2)])
def test_restart_dead_requires_consent_and_attempts_each_selected_process(
    answer: str,
    expected_spawns: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dead = [
        {"name": "engine", "command": ["pm-engine"]},
        {"name": "stats", "command": ["pm-stats"]},
    ]
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    spawn = Mock(side_effect=[101, None])
    monkeypatch.setattr(emo_cli, "spawn_process", spawn)

    emo_cli.restart_dead(dead, assume_yes=False)

    assert spawn.call_count == expected_spawns


def test_restart_prompt_is_skipped_for_noninteractive_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    spawn = Mock()
    monkeypatch.setattr(emo_cli, "spawn_process", spawn)
    emo_cli.restart_dead([{"name": "engine", "command": ["pm-engine"]}], False)
    spawn.assert_not_called()


def test_spawn_failure_is_reported_without_writing_pid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("denied")))
    assert emo_cli.spawn_process({"name": "engine", "command": ["pm-engine"]}) is None
    assert not emo_cli.pid_path("engine").exists()
    assert "failed to start engine" in capsys.readouterr().err


def test_stop_with_no_managed_processes_clears_stale_active_profile() -> None:
    emo_cli.runtime_dir().mkdir(parents=True)
    emo_cli.write_active_profile("demo")
    assert emo_cli.stop_profile() == 0
    assert emo_cli.read_active_profile() is None


def test_remove_path_handles_directory_file_and_absence(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    (directory / "state").write_text("x", encoding="utf-8")
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")

    assert emo_cli._remove_path(directory) is True
    assert emo_cli._remove_path(file_path) is True
    assert emo_cli._remove_path(tmp_path / "missing") is False


def test_running_process_detection_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        emo_cli, "pgrep_pids", Mock(side_effect=RuntimeError("ps failed"))
    )
    assert emo_cli._running_pm_pids() == []


@pytest.mark.parametrize(
    "answer, expected_rc, remains", [("n", 1, True), ("y", 0, False)]
)
def test_interactive_clear_respects_operator_decision(
    answer: str,
    expected_rc: int,
    remains: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state"
    state_file.write_text("state", encoding="utf-8")
    monkeypatch.setattr(emo_cli, "DATA_DIR", tmp_path)
    monkeypatch.setattr(emo_cli, "STATE_PATHS", (state_file,))
    monkeypatch.setattr(emo_cli, "NON_STATE_PATHS", ())
    monkeypatch.setattr(emo_cli, "_running_pm_pids", lambda: [])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: answer)

    assert emo_cli.clear_data(scope="state", assume_yes=False) == expected_rc
    assert state_file.exists() is remains


@pytest.mark.parametrize(
    "argv, function_name, expected_call",
    [
        (["init"], "create_config", ()),
        (["start", "micro", "--debug"], "start_profile", ("micro",)),
        (["up"], "start_profile", ("default",)),
        (["stop"], "stop_profile", ()),
        (["down"], "stop_profile", ()),
        (["kill"], "kill_all_processes", ()),
        (["list", "--no-restart"], "list_profile", ("never",)),
        (["health", "--quiet"], "health_profile", (True,)),
        (["show", "--json"], "show_info", ()),
    ],
)
def test_main_dispatches_each_operator_command(
    argv: list[str],
    function_name: str,
    expected_call: tuple[object, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function = Mock(return_value=17)
    monkeypatch.setattr(emo_cli, function_name, function)
    monkeypatch.setattr(sys, "argv", ["pm-opctl-cli", *argv])

    assert emo_cli.main() == 17
    if function_name == "start_profile":
        function.assert_called_once_with(expected_call[0], debug=argv[-1] == "--debug")
    elif function_name == "show_info":
        function.assert_called_once_with(json_output=True)
    else:
        function.assert_called_once_with(*expected_call)


@pytest.mark.parametrize(
    "argv, scope",
    [(["clear", "--state", "--yes"], "state"), (["clear", "--all"], "all")],
)
def test_main_clear_dispatches_selected_scope(
    argv: list[str], scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear = Mock(return_value=0)
    monkeypatch.setattr(emo_cli, "clear_data", clear)
    monkeypatch.setattr(sys, "argv", ["pm-opctl-cli", *argv])
    assert emo_cli.main() == 0
    clear.assert_called_once_with(scope=scope, assume_yes="--yes" in argv)


def test_main_translates_configuration_errors_to_cli_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-opctl-cli", "start"])
    monkeypatch.setattr(
        emo_cli, "start_profile", Mock(side_effect=ValueError("bad yaml"))
    )
    assert emo_cli.main() == 2
    assert "pm-opctl: bad yaml" in capsys.readouterr().err
