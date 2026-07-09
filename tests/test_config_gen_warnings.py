from __future__ import annotations

from edumatcher.config_gen.builder import (
    ApiGatewaySpec,
    ConfigSpec,
    MarketDataGatewaySpec,
    PostTradeGatewaySpec,
)
from edumatcher.config_gen.gateway_spec import parse_gateway_spec
from edumatcher.config_gen.symbol_spec import SymbolOverride
from edumatcher.config_gen.warnings import evaluate_diagnostics


def test_warnings_for_market_maker_and_sessions() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("MM01:MARKET_MAKER")],
        sessions_enabled=True,
        emit_schedule=True,
    )

    lines = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=[],
        raw_symbols=["aapl"],
        raw_gateways=["mm01:MARKET_MAKER"],
        output_exists=False,
    )

    assert any("MARKET_MAKER gateway MM01" in line for line in lines)
    assert any("engine starts in CLOSED" in line for line in lines)
    assert any("No ADMIN gateway" in line for line in lines)


def test_warning_for_undefined_symbol_level() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        symbol_overrides={"AAPL": SymbolOverride(level="STRICT")},
    )

    lines = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=[],
        raw_symbols=["AAPL"],
        raw_gateways=["TRADER01"],
        output_exists=False,
    )

    assert any("undefined risk level STRICT" in line for line in lines)


def test_error_for_existing_output() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    lines = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=[],
        raw_symbols=["AAPL"],
        raw_gateways=["TRADER01"],
        output_exists=True,
    )
    assert any(line.startswith("[ERROR]") for line in lines)


def test_port_collision_across_auxiliary_gateways() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        post_trade_gateway=PostTradeGatewaySpec(port=5580),
        market_data_gateway=MarketDataGatewaySpec(port=5580),
    )

    lines = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=[],
        raw_symbols=["AAPL"],
        raw_gateways=["TRADER01"],
        output_exists=False,
    )

    assert any("Port collision" in line and "5580" in line for line in lines)


def test_no_port_collision_when_ports_distinct() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        post_trade_gateway=PostTradeGatewaySpec(port=5580),
        market_data_gateway=MarketDataGatewaySpec(port=5570),
        api_gateways=(ApiGatewaySpec(port=8080),),
    )

    lines = evaluate_diagnostics(
        spec=spec,
        parsed_symbol_option_warnings=[],
        raw_symbols=["AAPL"],
        raw_gateways=["TRADER01"],
        output_exists=False,
    )

    assert not any("Port collision" in line for line in lines)
