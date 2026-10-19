"""pm-monitor's expected roster from the active emo profile (WP-B2.3, §9.3)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from edumatcher.emo import cli as emo_cli
from edumatcher.monitor.collector import Monitor
from edumatcher.monitor.config import MonitorConfig
from edumatcher.monitor.roster import (
    BEACONING_PROCESSES,
    Expected,
    Roster,
    expected_from_profile,
)
from tests.conftest import free_ports
from tests.test_monitor_main import QuietHost


def _ids(*processes: str) -> frozenset[Expected]:
    return frozenset((process, None) for process in processes)


MICRO = _ids("pm-log-srv", "pm-engine")


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """emo's runtime files under ``tmp_path`` (as tests/test_emo_cli.py does)."""
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    (tmp_path / emo_cli.RUNTIME_DIR_NAME).mkdir()
    return tmp_path


def _activate(name: str) -> None:
    emo_cli.write_active_profile(name)


def _touch_later(path: Path) -> None:
    """Make a rewrite visible to an mtime check even on a coarse clock."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


class TestExpectedFromProfile:
    def test_mini(self) -> None:
        assert expected_from_profile(emo_cli.MINI_PROCESSES) == {
            ("pm-log-srv", None),
            ("pm-stats", None),
            ("pm-engine", None),
            ("pm-scheduler", None),
            ("pm-md-gwy", None),
            ("pm-api-gwy", "desk"),
            ("pm-alf-gwy", None),
            ("pm-ralf-gwy", None),
            ("pm-dc-gwy", None),
        }

    def test_instances_are_separate(self) -> None:
        expected = expected_from_profile(emo_cli.DEFAULT_PROCESSES)
        assert {("pm-api-gwy", "desk"), ("pm-api-gwy", "dashboards")} <= expected

    def test_matches_on_the_program_not_the_display_name(self) -> None:
        entries = [
            {
                "name": "market-data-gwy (md-gwy)",
                "command": ["/opt/bin/pm-md-gwy", "-v"],
            },
            {"name": "x", "command": ["pm-api-gwy", "--instance=ops"]},
        ]
        assert expected_from_profile(entries) == {
            ("pm-md-gwy", None),
            ("pm-api-gwy", "ops"),
        }

    def test_programs_without_a_beacon_are_not_expected(self) -> None:
        entries = [
            {"name": "trader", "command": ["pm-alf-console", "--id", "T1"]},
            {"name": "bot", "command": ["pm-mm-bot", "--gateway-id", "MM01"]},
            {"name": "empty", "command": []},
        ]
        assert expected_from_profile(entries) == frozenset()

    def test_every_builtin_profile_program_is_known(self) -> None:
        """A program a built-in profile runs either beacons or is a known
        exception -- so a new process cannot silently drop off the roster."""
        not_beaconing = {"pm-mm-bot", "pm-ai-swarm"}  # B5.4
        for profile in emo_cli.BUILTIN_PROFILES.values():
            for entry in profile:
                program = os.path.basename(entry["command"][0])
                assert program in BEACONING_PROCESSES | not_beaconing, program


class TestRoster:
    def test_no_active_profile_expects_nothing(self, data_dir: Path) -> None:
        roster = Roster()
        assert roster.refresh()
        assert roster.expected is None

    def test_reads_the_active_builtin_profile(self, data_dir: Path) -> None:
        _activate("micro")
        roster = Roster()
        roster.refresh()
        assert roster.profile == "micro"
        assert roster.expected == MICRO

    def test_unchanged_files_are_not_re_read(
        self, data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _activate("micro")
        roster = Roster()
        assert roster.refresh()
        monkeypatch.setattr(emo_cli, "load_profiles", lambda: pytest.fail("re-read"))
        assert not roster.refresh()

    def test_follows_a_profile_switch_and_a_stop(self, data_dir: Path) -> None:
        _activate("micro")
        roster = Roster()
        roster.refresh()
        _activate("mini")
        _touch_later(emo_cli.active_profile_path())
        assert roster.refresh()
        assert roster.profile == "mini"
        emo_cli.active_profile_path().unlink()  # pm-opctl-cli stop
        assert roster.refresh()
        assert roster.expected is None

    def test_follows_an_edited_emo_config(self, data_dir: Path) -> None:
        config = emo_cli.config_path()
        config.write_text(
            yaml.safe_dump({"lab": [{"name": "e", "command": ["pm-engine"]}]})
        )
        _activate("lab")
        roster = Roster()
        roster.refresh()
        assert roster.expected == _ids("pm-engine")
        config.write_text(
            yaml.safe_dump(
                {"lab": [{"name": "e", "command": ["pm-engine"]},
                         {"name": "s", "command": ["pm-stats"]}]}
            )
        )  # fmt: skip
        _touch_later(config)
        assert roster.refresh()
        assert roster.expected == _ids("pm-engine", "pm-stats")

    def test_an_unknown_profile_expects_nothing(self, data_dir: Path) -> None:
        _activate("no-such-profile")
        roster = Roster()
        roster.refresh()
        assert roster.expected is None

    def test_a_broken_emo_config_keeps_the_roster(self, data_dir: Path) -> None:
        _activate("micro")
        roster = Roster()
        roster.refresh()
        config = emo_cli.config_path()
        config.write_text("lab: [unclosed\n")
        assert roster.refresh()
        assert roster.expected == MICRO


class _Clock:
    t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def monitor_with_roster(data_dir: Path) -> Iterator[tuple[Monitor, _Clock]]:
    clock = _Clock()
    pull, pub = free_ports(2)
    m = Monitor(
        MonitorConfig(pull_port=pull, pub_port=pub),
        ZoneInfo("Europe/Stockholm"),
        clock=clock,
        local_host="box",
        host_sampler=QuietHost(),
    )
    try:
        yield m, clock
    finally:
        m.close()


def test_every_mini_process_without_a_beacon_is_missing(
    monitor_with_roster: tuple[Monitor, _Clock],
) -> None:
    m, clock = monitor_with_roster
    _activate("mini")
    clock.t += 10  # past the start-up wait for MISSING
    missing = {
        (p["process"], p["instance"])
        for p in m.processes(clock.t)
        if p["state"] == "MISSING"
    }
    assert missing == expected_from_profile(emo_cli.MINI_PROCESSES)


def test_with_no_active_profile_nothing_is_missing(
    monitor_with_roster: tuple[Monitor, _Clock],
) -> None:
    m, clock = monitor_with_roster
    clock.t += 10
    assert m.processes(clock.t) == []
