"""pm-ai-trader command line."""

from __future__ import annotations

from pathlib import Path

import pytest

import edumatcher.ai_trader.main as main_mod
from edumatcher.ai_trader.preset import builtin_presets


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["pm-ai-trader", *argv])
    main_mod.main()


def test_list_presets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--list-presets")
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in builtin_presets():
        assert name in out


def test_id_required(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch)
    assert exc.value.code == 2


def test_preset_and_preset_file_are_exclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(
            monkeypatch,
            "--id",
            "AI001",
            "--preset",
            "scalper",
            "--preset-file",
            str(tmp_path / "x"),
        )
    assert exc.value.code == 2


def test_old_profile_flag_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--id", "AI001", "--profile", "cautious")
    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--preset-file", "/does/not/exist.yaml"], "exist.yaml"),
    ],
)
def test_bad_preset_exits_with_message(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], message: str
) -> None:
    monkeypatch.setattr(main_mod, "_configure_logging", lambda args: 0)
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--id", "AI001", *argv)
    assert message in str(exc.value.code)


def test_unknown_preset_is_an_argparse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, "--id", "AI001", "--preset", "nope")
    assert exc.value.code == 2


def test_default_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    args = main_mod.build_parser().parse_args(["--id", "AI001"])
    assert main_mod.resolve_preset(args).name == main_mod.DEFAULT_PRESET
