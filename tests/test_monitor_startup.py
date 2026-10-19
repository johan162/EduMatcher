"""Start-up integration of pm-monitor and the bots' beacons (WP-B5)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.ai_trader.swarm import Supervisor, WorkerJob
from edumatcher.emo import cli as emo_cli
from edumatcher.health.reporter import HealthReporter
from tests.test_ai_trader_swarm import _Proc, _specs
from tests.test_mm_bot_multi import _build_bot, _queue_startup
from tests.test_service_metrics import RecordingReporter

REPO = Path(__file__).resolve().parents[1]


def _programs(profile: list[dict[str, Any]]) -> list[str]:
    return [os.path.basename(p["command"][0]) for p in profile]


# ---------------------------------------------------------------------------
# B5.1 profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(emo_cli.BUILTIN_PROFILES))
def test_every_profile_but_micro_runs_one_monitor_between_log_and_engine(
    name: str,
) -> None:
    programs = _programs(emo_cli.load_profiles()[name])
    if name == "micro":
        assert "pm-monitor" not in programs
        return
    assert programs.count("pm-monitor") == 1
    # after the log server (so it can log), before the engine (so the
    # engine's first beacons are received)
    assert programs.index("pm-log-srv") < programs.index("pm-monitor")
    assert programs.index("pm-monitor") < programs.index("pm-engine")


def test_the_monitor_entry() -> None:
    (entry,) = [p for p in emo_cli.DEFAULT_PROCESSES if p["name"] == "monitor"]
    assert entry == {
        "name": "monitor",
        "command": ["pm-monitor", "--verbose"],
        "tcp": "127.0.0.1:5610",
    }


def test_init_writes_the_monitor_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    assert emo_cli.create_config() == 0
    document = yaml.safe_load(emo_cli.config_path().read_text())
    for name, profile in document.items():
        programs = _programs(profile["processes"])
        assert programs.count("pm-monitor") == (0 if name == "micro" else 1), name


def test_start_mini_launches_the_monitor_before_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emo_cli, "resolve_data_path", lambda p: tmp_path / p)
    started: list[str] = []

    def spawn(process: dict[str, Any]) -> int | None:
        started.append(os.path.basename(process["command"][0]))
        return 4242  # recorded, not launched

    monkeypatch.setattr(emo_cli, "spawn_process", spawn)
    monkeypatch.setattr(emo_cli, "resolve_pid", lambda process, claimed: (None, False))
    assert emo_cli.start_profile("mini") == 0
    assert "pm-monitor" in started
    assert started.index("pm-monitor") < started.index("pm-engine")


# ---------------------------------------------------------------------------
# B5.3 container
# ---------------------------------------------------------------------------


def test_the_image_documents_the_monitor_ports() -> None:
    dockerfile = (REPO / "deployment/docker/Dockerfile").read_text()
    (expose,) = [line for line in dockerfile.splitlines() if line.startswith("EXPOSE ")]
    assert {"5610", "5611"} <= set(expose.split()[1:])


def test_no_compose_file_publishes_the_monitor_ports() -> None:
    for compose in (REPO / "deployment/docker").glob("compose*.yaml"):
        text = compose.read_text()
        assert ":5610" not in text and ":5611" not in text, compose.name


# ---------------------------------------------------------------------------
# B5.4 bots
# ---------------------------------------------------------------------------


def test_the_mm_bot_ticks_in_its_quoting_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _push, sub, _ = _build_bot(monkeypatch, ["AAPL"])
    _queue_startup(sub, ["AAPL"])
    reporter = RecordingReporter()
    bot.attach_reporter(reporter)  # type: ignore[arg-type]
    real_timeout = bot._poll_timeout_ms
    loops = 0

    def keep_running(active: list[str]) -> int:
        # The fake start-up poller stops the bot; the quoting loop runs on.
        bot._running = True
        return real_timeout(active)

    real_tick = bot._tick

    def tick_then_stop() -> None:
        nonlocal loops
        loops += 1
        real_tick()
        if loops >= 3:
            bot._running = False

    monkeypatch.setattr(bot, "_poll_timeout_ms", keep_running)
    monkeypatch.setattr(bot, "_tick", tick_then_stop)
    monkeypatch.setattr("edumatcher.mm_bot.bot._TICK_MIN_SEC", 0.0)
    bot.run()
    assert reporter.ticks >= 2  # once per pass of the quoting loop
    names = {s.name for s in reporter.published[0]}
    assert names == {"mmbot.msgs_out", "mmbot.msgs_in", "mmbot.symbols_active"}


def test_the_swarm_supervisor_ticks(monkeypatch: pytest.MonkeyPatch) -> None:
    job = WorkerJob("w1", _specs(3), "127.0.0.1", 5565, None, {})
    sup = Supervisor([job])

    def spawn(slot: Any, now: float) -> None:
        slot.proc = _Proc()
        slot.restart_at = None

    monkeypatch.setattr(sup, "_spawn", spawn)
    reporter = RecordingReporter()
    sup.attach_reporter(reporter)  # type: ignore[arg-type]
    sleeps = 0

    def sleep(_sec: float) -> None:
        nonlocal sleeps
        sleeps += 1
        if sleeps >= 3:
            sup.stop()

    monkeypatch.setattr("edumatcher.ai_trader.swarm.time.sleep", sleep)
    sup.run()
    assert reporter.ticks == 3
    samples = {s.name: s.value for s in reporter.published[0]}
    assert samples == {
        "swarm.workers": 1.0,
        "swarm.workers_alive": 1.0,
        "swarm.workers_gave_up": 0.0,
        "swarm.agents": 3.0,
        "swarm.worker_restarts": 0.0,
    }


def test_the_mm_bot_main_wires_and_stops_its_reporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from edumatcher.mm_bot import main as mm_main
    from edumatcher.mm_bot.bot import MMBot

    reporter = RecordingReporter()
    monkeypatch.setattr(
        HealthReporter,
        "start_from_compiled_config",
        classmethod(lambda cls, process, instance=None: reporter),
    )
    seen: dict[str, Any] = {}

    def run(self: MMBot) -> int:
        seen["reporter"] = self._reporter
        return 0

    monkeypatch.setattr(MMBot, "run", run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-mm-bot",
            "--gateway-id",
            "MM01",
            "--symbol",
            "AAPL",
            "--log-target",
            "stdout",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        mm_main.main()
    assert exc.value.code == 0
    assert seen["reporter"] is reporter
    assert getattr(reporter, "stopped", False)


def test_the_mm_bot_starts_with_monitoring_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No deployed monitor section, or monitoring off: the bot still runs."""
    from edumatcher.mm_bot import main as mm_main
    from edumatcher.mm_bot.bot import MMBot

    # the suite's guard already makes from_compiled_config return None
    assert HealthReporter.start_from_compiled_config("pm-mm-bot") is None
    monkeypatch.setattr(MMBot, "run", lambda self: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pm-mm-bot",
            "--gateway-id",
            "MM01",
            "--symbol",
            "AAPL",
            "--log-target",
            "stdout",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        mm_main.main()
    assert exc.value.code == 0
