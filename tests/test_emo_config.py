"""WP-OPC05: healthchecks get time to answer; process names are file names
(pm-opctl review 2026-11, C7, C8)."""

from __future__ import annotations

import os
import sys
import time

import pytest

from edumatcher.emo import cli as emo_cli


@pytest.mark.parametrize("name", ["../x", "a/b", ".hidden", "a\nb", "a\\b", "a\0b"])
def test_a_name_that_is_not_one_file_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        emo_cli.validate_processes("p", [{"name": name, "command": ["pm-x"]}])


def test_the_built_in_names_are_accepted() -> None:
    for name, processes in emo_cli.BUILTIN_PROFILES.items():
        assert emo_cli.validate_processes(name, processes)


def test_a_healthcheck_that_answers_in_three_seconds_is_running() -> None:
    """pm-monitor-cli needs start-up + a slow join + up to 1 s to the next
    snapshot; on a loaded host that could exceed the old 2 s budget."""
    process = {
        "name": "slow",
        "command": ["x"],
        "healthcheck": [sys.executable, "-c", "import time; time.sleep(3)"],
    }
    assert emo_cli.check_health(process, os.getpid())[0] == "running"


def test_a_hanging_healthcheck_is_not_responding_within_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(emo_cli, "HEALTHCHECK_TIMEOUT_SEC", 0.5)
    process = {
        "name": "hung",
        "command": ["x"],
        "healthcheck": [sys.executable, "-c", "import time; time.sleep(30)"],
    }
    started = time.monotonic()
    assert emo_cli.check_health(process, os.getpid())[0] == "not responding"
    assert time.monotonic() - started < 5
