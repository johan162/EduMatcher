"""pm-scheduler's command line refuses input it cannot use (Scheduler
review 2026-11, C5): a usage error (exit 2), never a traceback or a flag
that is silently ignored."""

from __future__ import annotations

import pytest

from edumatcher.scheduler import main as sched


def _main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["pm-scheduler", *argv])
    monkeypatch.setattr(sched, "_configure_logging", lambda _a: 20)
    with pytest.raises(SystemExit) as exc:
        sched.main()
    return int(exc.value.code or 0)


@pytest.mark.parametrize("speed", ["nan", "inf", "-inf", "0", "-2"])
def test_speed_must_be_a_finite_positive_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], speed: str
) -> None:
    assert _main(monkeypatch, "--daily", "--speed", speed) == 2
    assert "--speed" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["", "   ", "pm-eod 'run"])
def test_on_close_must_be_a_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    assert _main(monkeypatch, "--daily", "--on-close", command) == 2
    assert "--on-close" in capsys.readouterr().err


@pytest.mark.parametrize("delay", ["-1", "nan", "inf"])
def test_on_close_delay_must_be_finite_and_not_negative(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], delay: str
) -> None:
    assert _main(monkeypatch, "--on-close-delay", delay) == 2
    assert "--on-close-delay" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--now", "--daily"],
        ["--now", "--daily", "--speed", "10"],
        ["--now", "--daily", "--start", "2026-11-02T08:55"],
    ],
)
def test_now_does_not_combine_with_daily_options(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    assert _main(monkeypatch, *argv) == 2
    assert "--now" in capsys.readouterr().err


def test_valid_options_still_parse() -> None:
    args = sched.build_parser().parse_args(
        [
            "--daily",
            "--speed",
            "600",
            "--on-close",
            "pm-eod run",
            "--on-close-delay",
            "0",
        ]
    )
    assert (args.speed, args.on_close, args.on_close_delay) == (
        600.0,
        "pm-eod run",
        0.0,
    )
