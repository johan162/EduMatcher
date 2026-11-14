"""Every pm-config-gen option takes effect or is refused.

An option that is accepted and then dropped gives the operator a file that
ignores what they asked for, with exit 0: a schedule without
``--sessions-enabled``, a corridor setting without ``--cb-levels``, an
abbreviated flag, a second ``--participants``, a bad ``--symbol-opts`` value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edumatcher.config_gen.cb_spec import parse_cb_spec
from edumatcher.config_gen.cli import main as config_gen_main

_BASE = ["--symbols", "AAPL", "--participants", "TRADER01", "OPS01:ADMIN"]


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> dict[str, object]:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv, "--output", str(out)])
    config_gen_main()
    loaded: dict[str, object] = yaml.safe_load(out.read_text())
    return loaded


def _refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> str:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv, "--output", str(out)])
    with pytest.raises(SystemExit) as exc:
        config_gen_main()
    assert exc.value.code == 2
    assert not out.exists()
    return capsys.readouterr().err


@pytest.mark.parametrize(
    "extra",
    [
        ["--schedule"],
        ["--weekend"],
        ["--holidays"],
        ["--pre-open", "08:00"],
        ["--weekend-closing-end", "15:00"],
    ],
    ids=lambda a: a[0],
)
def test_schedule_option_without_sessions_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    err = _refused(tmp_path, monkeypatch, capsys, [*_BASE, *extra])
    assert extra[0] in err
    assert "--sessions-enabled" in err


def test_schedule_option_with_no_schedule_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        [*_BASE, "--sessions-enabled", "--no-schedule", "--weekend"],
    )
    assert "--weekend" in err and "--no-schedule" in err


@pytest.mark.parametrize(
    "extra",
    [
        ["--ace-initial-band", "0.05"],
        ["--ace-expansions", "0.1:2"],
        ["--ace-random-end-ns", "0"],
        ["--ace-random-seed", "7"],
        ["--no-ace"],
        ["--cb-window-ns", "1000"],
    ],
    ids=lambda a: a[0],
)
def test_breaker_option_without_cb_levels_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    err = _refused(tmp_path, monkeypatch, capsys, [*_BASE, *extra])
    assert extra[0] in err
    assert "--cb-levels" in err


def test_breaker_options_with_cb_levels_take_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _run(
        tmp_path,
        monkeypatch,
        [
            *_BASE,
            "--cb-levels",
            "L1:0.07:5",
            "--ace-initial-band",
            "0.05",
            "--cb-window-ns",
            "1000",
        ],
    )
    cb = cfg["circuit_breaker_defaults"]
    assert isinstance(cb, dict)
    assert cb["reference_window_ns"] == 1000
    assert cb["reopening"]["initial_band_pct"] == 0.05


def test_abbreviated_option_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _refused(tmp_path, monkeypatch, capsys, [*_BASE, "--snapshot", "2.0"])


def test_repeated_list_options_extend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _run(
        tmp_path,
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--participants",
            "TRADER01",
            "--symbols",
            "MSFT",
            "--participants",
            "OPS01:ADMIN",
            "--cb-levels",
            "L1:0.07:5",
            "--cb-levels",
            "L2:0.13",
        ],
    )
    symbols = cfg["symbols"]
    assert isinstance(symbols, dict)
    assert set(symbols) == {"AAPL", "MSFT"}
    participants = cfg["participants"]
    assert isinstance(participants, list)
    assert [p["id"] for p in participants] == ["TRADER01", "OPS01"]
    cb = cfg["circuit_breaker_defaults"]
    assert isinstance(cb, dict)
    assert set(cb["levels"]) == {"L1", "L2"}


def test_duplicate_symbol_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        ["--symbols", "AAPL", "aapl", "--participants", "TRADER01", "OPS01:ADMIN"],
    )
    assert "AAPL" in err


@pytest.mark.parametrize(
    "spec",
    [
        "AAPL:tick_decimals=9",
        "MSFT:tick_decimals=3",
        "AAPL:unknown_field=1",
        "AAPL:tick_decimals",
        "AAPL:cb_shift_l1=0.05,cb_halt_l1=0",
    ],
)
def test_bad_symbol_opts_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    spec: str,
) -> None:
    err = _refused(tmp_path, monkeypatch, capsys, [*_BASE, "--symbol-opts", spec])
    assert "--symbol-opts" in err


def test_zero_halt_minutes_is_refused() -> None:
    with pytest.raises(ValueError, match="HALT_MINS"):
        parse_cb_spec("L1:0.1:0")


def test_sessions_enabled_still_writes_the_default_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _run(tmp_path, monkeypatch, [*_BASE, "--sessions-enabled"])
    schedule = cfg["schedule"]
    assert isinstance(schedule, dict)
    assert schedule["weekdays"]["pre_open"] == "09:00"
    assert "weekend" not in schedule


def test_sessions_enabled_with_weekend_and_custom_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _run(
        tmp_path,
        monkeypatch,
        [*_BASE, "--sessions-enabled", "--weekend", "--pre-open", "08:00"],
    )
    schedule = cfg["schedule"]
    assert isinstance(schedule, dict)
    assert schedule["weekdays"]["pre_open"] == "08:00"
    assert schedule["weekend"]["pre_open"] == "10:00"
