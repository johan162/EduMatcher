from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_gen.cli import main as config_gen_main
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


def test_api_gateway_output_generates_keys(
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
            "OPS01:ADMIN",
            "--api-gateway",
            "--api-gateway-readonly-key",
            "--api-gateway-host",
            "0.0.0.0",
            "--api-gateway-port",
            "9090",
            "--api-gateway-swagger-disabled",
            "--api-gateway-rate-limit-writes-per-second",
            "25",
            "--api-gateway-rate-limit-burst",
            "50",
            "--seed",
            "99",
            "--output",
            str(out_file),
        ],
    )

    content = out_file.read_text(encoding="utf-8")
    assert "api_gateways:" in content
    assert "default:" in content
    assert "host: 0.0.0.0" in content
    assert "port: 9090" in content
    assert "swagger_enabled: false" in content
    assert "writes_per_second: 25" in content
    assert "burst: 50" in content
    assert "gateway_id: TRADER01" in content
    assert "gateway_id: OPS01" in content
    assert "gateway_id: null" in content
    assert "api_key: key-trader01-" in content
    cfg = load_engine_config(out_file)
    assert "TRADER01" in cfg.fix_gateways


def test_api_gateway_explicit_key_output(
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
            "--api-key",
            "manual-token:TRADER01:Desk app",
            "--no-api-gateway-generate-keys",
            "--output",
            str(out_file),
        ],
    )

    content = out_file.read_text(encoding="utf-8")
    assert "api_gateways:" in content
    assert "default:" in content
    assert "api_key: manual-token" in content
    assert "gateway_id: TRADER01" in content
    assert "description: Desk app" in content
    assert "key-trader01-" not in content


def test_api_gateway_multiple_instances_output(
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
            "ALGO01",
            "--api-gateway-instance",
            "desk:TRADER01:8080",
            "--api-gateway-instance",
            "algos:ALGO01:8081",
            "--seed",
            "99",
            "--output",
            str(out_file),
        ],
    )

    content = out_file.read_text(encoding="utf-8")
    assert "api_gateways:" in content
    assert "desk:" in content
    assert "algos:" in content
    assert "port: 8081" in content
    assert "gateway_id: TRADER01" in content
    assert "gateway_id: ALGO01" in content


def test_api_gateway_multiple_instances_reject_duplicate_gateway(
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
                "--api-gateway-instance",
                "desk:TRADER01",
                "--api-gateway-instance",
                "algos:TRADER01",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2


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


def test_symbol_collar_band_flags_emit_per_symbol_override(
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
            "--symbol-static-band",
            "AAPL:0.18",
            "--symbol-dynamic-band",
            "AAPL:0.03",
            "--output",
            str(out_file),
        ],
    )

    cfg = load_engine_config(out_file)
    assert cfg.symbols["AAPL"].collar is not None
    assert cfg.symbols["AAPL"].collar.static_band_pct == pytest.approx(0.18)
    assert cfg.symbols["AAPL"].collar.dynamic_band_pct == pytest.approx(0.03)
    assert cfg.symbols["MSFT"].collar is None


def test_symbol_risk_level_flag_emits_per_symbol_level_override(
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
            "--risk-level",
            "CORE:0.18:0.02",
            "--symbol-risk-level",
            "AAPL:CORE",
            "--output",
            str(out_file),
        ],
    )

    cfg = load_engine_config(out_file)
    assert cfg.symbols["AAPL"].level == "CORE"
    assert cfg.symbols["MSFT"].level is None


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
        "# true lets pm-scheduler drive session transitions;\n# false keeps the engine in continuous mode\nsessions_enabled: false"
        in captured.out
    )
    assert (
        "# seconds between book snapshot publications for dirty books\nsnapshot_interval_sec: 0.5"
        in captured.out
    )
    # Check for circuit_breaker_defaults documentation in "Field Notes and Accepted Values" section
    assert (
        "#   reference_window_ns: 300000000000\n#     Lookback window used to compute the rolling reference price for halt triggers."
        in captured.out
    )
    # Check for symbols documentation
    assert "#   last_buy_price: null" in captured.out
    assert "#   --snapshot-interval" not in captured.out


def test_index_section_is_emitted(
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
            "TSLA",
            "--gateways",
            "TRADER01",
            "--outstanding-shares",
            "AAPL:15000000000",
            "--outstanding-shares",
            "MSFT:7400000000",
            "--outstanding-shares",
            "TSLA:3200000000",
            "--index",
            "EDU100:Broad tech benchmark",
            "--index-constituents",
            "EDU100:AAPL,MSFT,TSLA",
            "--output",
            str(out_file),
        ],
    )
    content = out_file.read_text()
    assert "indices:" in content
    assert "id: EDU100" in content
    assert "description: Broad tech benchmark" in content
    assert "AAPL" in content

    cfg = load_engine_config(out_file)
    assert len(cfg.indices) == 1
    assert cfg.indices[0].id == "EDU100"
    assert set(cfg.indices[0].constituents) == {"AAPL", "MSFT", "TSLA"}
    assert cfg.indices[0].base_value == 1000.0


def test_index_two_indices_emitted(
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
            "JPM",
            "--gateways",
            "TRADER01",
            "--outstanding-shares",
            "AAPL:15000000000",
            "--outstanding-shares",
            "MSFT:7400000000",
            "--outstanding-shares",
            "JPM:3000000000",
            "--index",
            "TECH",
            "--index-constituents",
            "TECH:AAPL,MSFT",
            "--index",
            "FIN:Financial basket",
            "--index-constituents",
            "FIN:JPM",
            "--index-base-value",
            "TECH:500.0",
            "--index-interval",
            "FIN:2.0",
            "--output",
            str(out_file),
        ],
    )
    cfg = load_engine_config(out_file)
    assert len(cfg.indices) == 2
    tech = next(i for i in cfg.indices if i.id == "TECH")
    fin = next(i for i in cfg.indices if i.id == "FIN")
    assert tech.base_value == 500.0
    assert set(tech.constituents) == {"AAPL", "MSFT"}
    assert fin.publish_interval_sec == 2.0
    assert fin.description == "Financial basket"


def test_index_custom_file_paths(
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
            "--outstanding-shares",
            "AAPL:15000000000",
            "--index",
            "IDX1",
            "--index-constituents",
            "IDX1:AAPL",
            "--index-history-file",
            "IDX1:custom/hist.jsonl",
            "--index-state-file",
            "IDX1:custom/state.json",
            "--output",
            str(out_file),
        ],
    )
    cfg = load_engine_config(out_file)
    assert cfg.indices[0].history_file == "custom/hist.jsonl"
    assert cfg.indices[0].state_file == "custom/state.json"


def test_index_default_file_paths_derived_from_id(
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
            "--outstanding-shares",
            "AAPL:15000000000",
            "--index",
            "EDU100",
            "--index-constituents",
            "EDU100:AAPL",
            "--output",
            str(out_file),
        ],
    )
    cfg = load_engine_config(out_file)
    assert cfg.indices[0].history_file == "data/indexes/EDU100_history.jsonl"
    assert cfg.indices[0].state_file == "data/indexes/EDU100_state.json"


def test_index_missing_constituents_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--index",
                "EDU100",
                # no --index-constituents
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2
    assert "no constituents" in capsys.readouterr().err


def test_index_unknown_constituent_symbol_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--index",
                "EDU100",
                "--index-constituents",
                "EDU100:AAPL,UNKNOWN",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2
    assert "UNKNOWN" in capsys.readouterr().err


def test_index_more_than_five_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc_info:
        _run_main(
            monkeypatch,
            [
                "--symbols",
                "AAPL",
                "--gateways",
                "TRADER01",
                "--index",
                "I1",
                "--index",
                "I2",
                "--index",
                "I3",
                "--index",
                "I4",
                "--index",
                "I5",
                "--index",
                "I6",
                "--dry-run",
            ],
        )
    assert exc_info.value.code == 2
    assert "maximum 5" in capsys.readouterr().err.lower()
