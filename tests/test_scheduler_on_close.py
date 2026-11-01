"""--on-close: a command started after the day's CLOSED transition."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from edumatcher.scheduler.main import _CloseHook, _Step, _run_transitions, build_parser


def wait_for(path: Path, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not path.exists() and time.monotonic() < end:
        time.sleep(0.02)
    assert path.exists()


def command(code: str) -> str:
    return f'{sys.executable} -c "{code}"'


class TestCloseHook:
    def test_runs_the_command(self, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        hook = _CloseHook(command(f"open('{marker}','w').write('x')"), delay_sec=0)
        hook()
        wait_for(marker)
        hook.wait()

    def test_does_not_block_the_caller(self, tmp_path: Path) -> None:
        hook = _CloseHook(command("import time; time.sleep(2)"), delay_sec=0)
        start = time.monotonic()
        hook()
        assert time.monotonic() - start < 1.0
        hook.stop()

    def test_the_delay_is_honoured(self, tmp_path: Path) -> None:
        marker = tmp_path / "ran"
        hook = _CloseHook(command(f"open('{marker}','w').write('x')"), delay_sec=0.5)
        start = time.monotonic()
        hook()
        wait_for(marker)
        assert time.monotonic() - start >= 0.5
        hook.wait()

    def test_a_second_call_while_running_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        marker = tmp_path / "count"
        code = f"open('{marker}','a').write('x'); import time; time.sleep(1)"
        hook = _CloseHook(command(code), delay_sec=0)
        hook()
        wait_for(marker)
        with caplog.at_level("WARNING"):
            hook()
            hook.wait_timers()
        hook.wait()
        assert marker.read_text() == "x"
        assert "still running" in caplog.text

    def test_a_missing_command_is_logged_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        hook = _CloseHook("/nonexistent/pm-eod run", delay_sec=0)
        with caplog.at_level("ERROR"):
            hook()
            hook.wait()
        assert "could not start" in caplog.text

    def test_a_failing_command_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        hook = _CloseHook(command("raise SystemExit(3)"), delay_sec=0)
        with caplog.at_level("WARNING"):
            hook()
            hook.wait()
        assert "exited 3" in caplog.text

    def test_it_is_runnable_again_after_the_child_finished(
        self, tmp_path: Path
    ) -> None:
        marker = tmp_path / "count"
        hook = _CloseHook(command(f"open('{marker}','a').write('x')"), delay_sec=0)
        hook()
        hook.wait()
        hook()
        hook.wait()
        assert marker.read_text() == "xx"


class TestRunTransitionsHook:
    def test_fires_after_closed_only(self) -> None:
        calls: list[str] = []
        steps = [
            _Step("PRE_OPEN", lambda: 0.0),
            _Step("CLOSED", lambda: 0.0),
        ]
        sent: list[int] = []
        push = MagicMock()
        push.send_multipart.side_effect = lambda *_a, **_k: sent.append(len(calls))
        assert _run_transitions(
            push, None, lambda: True, steps, on_closed=lambda: calls.append("hook")
        )
        assert calls == ["hook"]
        assert sent == [0, 0]  # the hook ran after both sends

    def test_no_hook_is_fine(self) -> None:
        push = MagicMock()
        assert _run_transitions(
            push, None, lambda: True, [_Step("CLOSED", lambda: 0.0)]
        )

    def test_an_interrupted_run_does_not_fire(self) -> None:
        calls: list[str] = []
        push = MagicMock()
        assert not _run_transitions(
            push,
            None,
            lambda: False,
            [_Step("CLOSED", lambda: 0.0)],
            on_closed=lambda: calls.append("x"),
        )
        assert calls == []


class TestParser:
    def test_options(self) -> None:
        args = build_parser().parse_args(
            ["--daily", "--on-close", "pm-eod run --pending"]
        )
        assert args.on_close == "pm-eod run --pending"
        assert args.on_close_delay == 30.0

    def test_default_is_off(self) -> None:
        assert build_parser().parse_args([]).on_close is None
