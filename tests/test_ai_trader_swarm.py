from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import pytest

import edumatcher.ai_trader.swarm as swarm_main

from edumatcher.ai_trader.swarm import (
    assign_primary_symbols,
    build_bot_command,
    build_gateway_ids,
    _load_symbols,
    _parse_profile_cycle,
)


class TestSwarmHelpers:
    def test_build_gateway_ids(self) -> None:
        ids = build_gateway_ids("AI", 1, 3)
        assert ids == ["AI01", "AI02", "AI03"]

    def test_assign_primary_symbols_round_robin(self) -> None:
        mapping = assign_primary_symbols(
            ["AI01", "AI02", "AI03", "AI04"],
            ["AAPL", "MSFT"],
        )
        assert mapping["AI01"] == "AAPL"
        assert mapping["AI02"] == "MSFT"
        assert mapping["AI03"] == "AAPL"
        assert mapping["AI04"] == "MSFT"

    def test_build_bot_command_contains_required_flags(self) -> None:
        cmd = build_bot_command(
            python_executable="python",
            gateway_id="AI01",
            profile="aggressive",
            symbol="AAPL",
            seed=42,
            duration=30.0,
            run_id="swarm-1",
            max_position=500,
            max_rejects=7,
            reject_window=8.0,
            reject_cooldown=3.0,
            stale_data=4.5,
        )
        joined = " ".join(cmd)
        assert "edumatcher.ai_trader.main" in joined
        assert "--id AI01" in joined
        assert "--profile aggressive" in joined
        assert "--symbols AAPL" in joined
        assert "--max-position 500" in joined
        assert "--stale-data 4.5" in joined

    def test_parse_profile_cycle_default(self) -> None:
        profiles = _parse_profile_cycle("")
        assert profiles

    def test_parse_profile_cycle_invalid(self) -> None:
        with pytest.raises(ValueError):
            _parse_profile_cycle("cautious,unknown")

    def test_load_symbols_direct_arg(self) -> None:
        symbols = _load_symbols("AAPL,MSFT", config_path=Path("engine_config.yaml"))
        assert symbols == ["AAPL", "MSFT"]

    def test_load_symbols_from_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Cfg:
            allowed_symbols = frozenset({"MSFT", "AAPL"})

        monkeypatch.setattr(swarm_main, "load_engine_config", lambda _path: _Cfg())
        symbols = _load_symbols("", config_path=Path("engine_config.yaml"))
        assert symbols == ["AAPL", "MSFT"]


class TestSwarmMain:
    def test_parse_args_logging_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-ai-swarm",
                "--count",
                "1",
                "-vv",
                "--quiet",
                "--log-level",
                "ERROR",
            ],
        )
        args = swarm_main._parse_args()
        assert args.count == 1
        assert args.verbose == 2
        assert args.quiet is True
        assert args.log_level == "ERROR"

    def test_main_forwards_logging_flags_to_child(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen_cmds: list[list[str]] = []

        class _Proc:
            def __init__(self, cmd: list[str]) -> None:
                seen_cmds.append(cmd)
                self._rc = 0

            def wait(self, timeout: float | None = None) -> int:
                _ = timeout
                return self._rc

            def poll(self) -> int | None:
                return self._rc

            def send_signal(self, _sig: int) -> None:
                return

            def kill(self) -> None:
                return

        monkeypatch.setattr(
            swarm_main,
            "_parse_args",
            lambda: argparse.Namespace(
                count=1,
                prefix="AI",
                start_index=1,
                profiles="aggressive",
                symbols="",
                config="engine_config.yaml",
                seed_base=1,
                duration=1.0,
                python="python",
                max_position=100,
                max_rejects=5,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
                log_level="INFO",
                verbose=2,
                quiet=True,
            ),
        )
        monkeypatch.setattr(
            swarm_main, "_load_symbols", lambda _symbols, _cfg: ["AAPL"]
        )
        monkeypatch.setattr("edumatcher.ai_trader.swarm.subprocess.Popen", _Proc)
        monkeypatch.setattr("edumatcher.ai_trader.swarm.time.sleep", lambda _s: None)

        with pytest.raises(SystemExit) as exc:
            swarm_main.main()
        assert exc.value.code == 0
        assert len(seen_cmds) == 1
        joined = " ".join(seen_cmds[0])
        assert "--log-level INFO" in joined
        assert "-vv" in joined
        assert "-q" in joined

    def test_main_count_must_be_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            swarm_main,
            "_parse_args",
            lambda: argparse.Namespace(count=0, log_level=None, verbose=0, quiet=False),
        )
        with pytest.raises(SystemExit):
            swarm_main.main()

    def test_main_no_symbols(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            swarm_main,
            "_parse_args",
            lambda: argparse.Namespace(
                count=1,
                prefix="AI",
                start_index=1,
                profiles="",
                symbols="",
                config="engine_config.yaml",
                seed_base=1,
                duration=1.0,
                python="python",
                max_position=100,
                max_rejects=5,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
                log_level=None,
                verbose=0,
                quiet=False,
            ),
        )
        monkeypatch.setattr(swarm_main, "_load_symbols", lambda _symbols, _cfg: [])
        with pytest.raises(SystemExit):
            swarm_main.main()

    def test_main_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Proc:
            def __init__(self, _cmd: list[str]) -> None:
                self._rc = 0

            def wait(self, timeout: float | None = None) -> int:
                _ = timeout
                return self._rc

            def poll(self) -> int | None:
                return self._rc

            def send_signal(self, _sig: int) -> None:
                return

            def kill(self) -> None:
                return

        monkeypatch.setattr(
            swarm_main,
            "_parse_args",
            lambda: argparse.Namespace(
                count=2,
                prefix="AI",
                start_index=1,
                profiles="aggressive,cautious",
                symbols="",
                config="engine_config.yaml",
                seed_base=1,
                duration=1.0,
                python="python",
                max_position=100,
                max_rejects=5,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
                log_level=None,
                verbose=0,
                quiet=False,
            ),
        )
        monkeypatch.setattr(
            swarm_main, "_load_symbols", lambda _symbols, _cfg: ["AAPL", "MSFT"]
        )
        monkeypatch.setattr("edumatcher.ai_trader.swarm.subprocess.Popen", _Proc)
        monkeypatch.setattr("edumatcher.ai_trader.swarm.time.sleep", lambda _s: None)

        with pytest.raises(SystemExit) as exc:
            swarm_main.main()
        assert exc.value.code == 0

    def test_main_keyboard_interrupt_cleanup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _Proc:
            def __init__(self, _cmd: list[str]) -> None:
                self.signaled = False
                self.killed = False

            def wait(self, timeout: float | None = None) -> int:
                if timeout is None:
                    raise KeyboardInterrupt()
                raise subprocess.TimeoutExpired(cmd="bot", timeout=timeout)

            def poll(self) -> int | None:
                return None

            def send_signal(self, _sig: int) -> None:
                self.signaled = True

            def kill(self) -> None:
                self.killed = True

        monkeypatch.setattr(
            swarm_main,
            "_parse_args",
            lambda: argparse.Namespace(
                count=1,
                prefix="AI",
                start_index=1,
                profiles="aggressive",
                symbols="",
                config="engine_config.yaml",
                seed_base=1,
                duration=1.0,
                python="python",
                max_position=100,
                max_rejects=5,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
                log_level=None,
                verbose=0,
                quiet=False,
            ),
        )
        monkeypatch.setattr(
            swarm_main, "_load_symbols", lambda _symbols, _cfg: ["AAPL"]
        )
        monkeypatch.setattr("edumatcher.ai_trader.swarm.subprocess.Popen", _Proc)
        monkeypatch.setattr("edumatcher.ai_trader.swarm.time.sleep", lambda _s: None)

        with pytest.raises(SystemExit) as exc:
            swarm_main.main()
        assert exc.value.code == 130
