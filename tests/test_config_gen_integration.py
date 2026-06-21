from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.commands.config_gen import main as config_gen_main
from edumatcher.engine.config_loader import load_engine_config


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv])
    config_gen_main()


def test_minimal_output_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_file = tmp_path / "engine_config.yaml"
    _run_main(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "TRADER01",
            "--output",
            str(out_file),
        ],
    )

    assert out_file.exists()
    cfg = load_engine_config(out_file)
    assert "AAPL" in cfg.symbols
    assert "TRADER01" in cfg.fix_gateways

    stderr = capsys.readouterr().err
    assert "Wrote generated config" in stderr


def test_market_maker_warns_and_stubs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_main(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "TRADER01",
            "MM01:MARKET_MAKER",
            "--dry-run",
        ],
    )

    captured = capsys.readouterr()
    assert "[WARN] MARKET_MAKER gateway MM01" in captured.err
    assert "bid_price: null" in captured.out
    assert "ask_price: null" in captured.out


def test_output_refuses_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_file = tmp_path / "engine_config.yaml"
    out_file.write_text("already here", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--output",
                str(out_file),
            ],
        )

    assert exc_info.value.code == 1


def test_post_trade_gateway_output_is_emitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_file = tmp_path / "engine_config.yaml"
    _run_main(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "TRADER01",
            "--post-trade-gateway",
            "--post-trade-bind-address",
            "127.0.0.1",
            "--post-trade-port",
            "6001",
            "--post-trade-allowed-roles",
            "CLEARING",
            "AUDIT",
            "--output",
            str(out_file),
        ],
    )

    content = out_file.read_text(encoding="utf-8")
    assert "post_trade_gateway:" in content
    assert "bind_address: 127.0.0.1" in content
    assert "port: 6001" in content
    assert "- CLEARING" in content
    assert "- AUDIT" in content


def test_market_data_gateway_output_is_emitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_file = tmp_path / "engine_config.yaml"
    _run_main(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "--gateways",
            "TRADER01",
            "--market-data-gateway",
            "--market-data-bind-address",
            "127.0.0.1",
            "--market-data-port",
            "7001",
            "--market-data-replay-window-sec",
            "120",
            "--output",
            str(out_file),
        ],
    )

    content = out_file.read_text(encoding="utf-8")
    assert "market_data_gateway:" in content
    assert "bind_address: 127.0.0.1" in content
    assert "port: 7001" in content
    assert "replay_window_sec: 120" in content
