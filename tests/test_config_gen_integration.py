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
    assert (
        "WARNING: pm-config-gen cannot set prices. Fill these in before starting."
        in captured.out
    )
    assert "bid_price: null" in captured.out
    assert "ask_price: null" in captured.out


def test_market_maker_seeded_quotes_are_emitted(
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
            "--seed",
            "17",
            "--seed-mm-mid-range",
            "20:21",
            "--seed-last-prices-from-mm",
            "--dry-run",
        ],
    )

    captured = capsys.readouterr()
    assert (
        "WARNING: pm-config-gen cannot set prices. Fill these in before starting."
        not in captured.out
    )
    assert "bid_price: null" not in captured.out
    assert "ask_price: null" not in captured.out
    assert "last_buy_price:" in captured.out
    assert "last_sell_price:" in captured.out
    assert "Fill all market_maker_quotes" not in captured.err


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


def test_outstanding_shares_output_is_emitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_file = tmp_path / "engine_config.yaml"
    _run_main(
        monkeypatch,
        [
            "--symbols",
            "AAPL",
            "MSFT",
            "--gateways",
            "TRADER01",
            "--outstanding-shares",
            "AAPL:15400000000",
            "--outstanding-shares",
            "MSFT:7430000000",
            "--output",
            str(out_file),
        ],
    )

    cfg = load_engine_config(out_file)
    assert cfg.symbols["AAPL"].outstanding_shares == 15_400_000_000
    assert cfg.symbols["MSFT"].outstanding_shares == 7_430_000_000


def test_outstanding_shares_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--outstanding-shares",
                "AAPL:-1",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2


def test_seed_last_prices_from_mm_requires_mid_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "MM01:MARKET_MAKER",
                "--seed-last-prices-from-mm",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2


def test_seed_mm_mid_range_requires_mm_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--seed-mm-mid-range",
                "20:30",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2

    def test_comment_default_config_fields_emits_engine_field_defaults(
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
                "--comment-default-config-fields",
                "--dry-run",
            ],
        )

        captured = capsys.readouterr()
        assert "# Defaultable engine_config fields and default values:" in captured.out
        assert (
            "sessions_enabled: false  # true lets pm-scheduler drive session transitions; false keeps the engine in continuous mode"
            in captured.out
        )
        assert (
            "snapshot_interval_sec: 0.5  # seconds between book snapshot publications for dirty books"
            in captured.out
        )
        assert "#   symbols.<SYM>.last_buy_price = null" in captured.out
        assert "#   post_trade_gateway.port = 5580" in captured.out
        assert "#   --snapshot-interval" not in captured.out
