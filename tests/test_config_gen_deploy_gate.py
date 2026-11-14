"""pm-config-gen never writes a file pm-config-deploy refuses.

It validates the rendered files with the same gate the deploy uses
(``config_deploy.compile_config``: the verifier's ERRORs, then every loader),
so a participant-id prefix, a port collision or a port out of range is refused
at generation, not at deployment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_deploy import compile_config
from edumatcher.config_gen.cli import main as config_gen_main

_BASE = ["--symbols", "AAPL", "--participants", "TRADER01", "OPS01:ADMIN"]


def _run(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv])
    config_gen_main()


def _refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> str:
    out = tmp_path / "engine_config.yaml"
    with pytest.raises(SystemExit) as exc:
        _run(monkeypatch, [*argv, "--output", str(out)])
    assert exc.value.code == 2
    assert not out.exists()
    return capsys.readouterr().err


def test_prefix_participant_ids_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        ["--symbols", "AAPL", "--participants", "TRADER1", "TRADER10", "OPS:ADMIN"],
    )
    assert "S084" in err


@pytest.mark.parametrize(
    "argv",
    [
        ["--alf-gateway", "--market-data-gateway", "--alf-port", "5570"],
        ["--api-gateway", "--monitor", "--api-gateway-port", "5610"],
    ],
    ids=["alf-vs-md", "api-vs-monitor"],
)
def test_port_collision_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    err = _refused(tmp_path, monkeypatch, capsys, [*_BASE, *argv])
    assert "M018" in err


@pytest.mark.parametrize(
    "flag",
    [
        "--post-trade-port",
        "--market-data-port",
        "--api-gateway-port",
        "--alf-port",
        "--balf-port",
        "--dc-port",
        "--log-server-port",
        "--log-server-pub-port",
        "--log-server-pull-port",
        "--monitor-pull-port",
        "--monitor-pub-port",
    ],
)
def test_port_above_65535_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
) -> None:
    err = _refused(tmp_path, monkeypatch, capsys, [*_BASE, flag, "70000"])
    assert flag in err
    assert "1-65535" in err


def test_api_gateway_instance_port_above_65535_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        [*_BASE, "--api-gateway-instance", "desk:TRADER01:70000"],
    )
    assert "PORT must be in 1-65535" in err


def test_valid_run_names_the_real_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "my_exchange.yaml"
    _run(monkeypatch, [*_BASE, "--output", str(out)])
    err = capsys.readouterr().err
    assert "[INFO] Generated config passes pm-config-deploy --check." in err
    assert f"pm-cverifier {out}" in err
    assert "poetry run" not in err
    text = out.read_text()
    assert "pm-cverifier" in text
    assert "poetry run" not in text
    compile_config(out)


def test_mm_stub_template_is_written_and_says_it_will_not_deploy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "engine_config.yaml"
    _run(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--participants",
            "TRADER01",
            "MM01:MARKET_MAKER",
            "--output",
            str(out),
        ],
    )
    assert out.exists()
    err = capsys.readouterr().err
    assert "pm-config-deploy refuses the file until" in err
    assert "passes pm-config-deploy" not in err


def test_split_and_keys_file_still_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "engine_config.yaml"
    _run(
        monkeypatch,
        [
            *_BASE,
            "--api-gateway",
            "--api-keys-for",
            "TRADER01",
            "--split",
            "--seed",
            "3",
            "--output",
            str(out),
        ],
    )
    compile_config(out)
