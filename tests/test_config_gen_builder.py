from __future__ import annotations

from edumatcher.config_gen.builder import (
    ConfigBuilder,
    ConfigSpec,
    PostTradeGatewaySpec,
)
from edumatcher.config_gen.cb_spec import parse_cb_spec
from edumatcher.config_gen.gateway_spec import parse_gateway_spec
from edumatcher.config_gen.symbol_spec import SymbolOverride


def test_builder_minimal() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    payload = ConfigBuilder(spec).build()

    assert payload["sessions_enabled"] is False
    assert payload["symbols"]["AAPL"]["tick_decimals"] == 2
    assert payload["gateways"]["alf"][0]["disconnect_behaviour"] == "CANCEL_ALL"
    assert "risk_controls" not in payload
    assert "circuit_breaker_defaults" not in payload


def test_builder_with_risk_level_and_symbol_level_reference() -> None:
    ov = SymbolOverride(level="STRICT")
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        static_band_pct=0.20,
        dynamic_band_pct=0.02,
        risk_levels={"STRICT": (0.12, 0.01)},
        symbol_overrides={"AAPL": ov},
    )
    payload = ConfigBuilder(spec).build()

    assert payload["risk_controls"]["default_level"] == "DEFAULT"
    assert (
        payload["risk_controls"]["levels"]["STRICT"]["collar"]["static_band_pct"]
        == 0.12
    )
    assert payload["symbols"]["AAPL"]["level"] == "STRICT"


def test_builder_with_mm_gateway_emits_stubs() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[
            parse_gateway_spec("TRADER01"),
            parse_gateway_spec("MM01:MARKET_MAKER"),
        ],
        emit_mm_defaults=True,
    )
    payload = ConfigBuilder(spec).build()

    assert "mm_obligation_defaults" in payload
    quote = payload["symbols"]["AAPL"]["market_maker_quotes"][0]
    assert quote["gateway_id"] == "MM01"
    assert quote["bid_price"] is None
    assert quote["ask_price"] is None
    assert quote["bid_qty"] == 1000
    assert quote["tif"] == "DAY"
    assert quote["seed_once"] is True


def test_builder_with_cb_defaults_and_symbol_override() -> None:
    ov = SymbolOverride()
    ov.cb_shift["L1"] = 0.10
    ov.cb_halt_mins["L1"] = 10
    spec = ConfigSpec(
        symbols=["TSLA"],
        gateways=[parse_gateway_spec("TRADER01")],
        cb_levels=[parse_cb_spec("L1:0.07:5"), parse_cb_spec("L2:0.13:15")],
        symbol_overrides={"TSLA": ov},
    )
    payload = ConfigBuilder(spec).build()

    assert (
        payload["circuit_breaker_defaults"]["levels"]["L1"]["resumption_mode"]
        == "AUCTION"
    )
    sym_l1 = payload["symbols"]["TSLA"]["circuit_breaker"]["levels"]["L1"]
    assert sym_l1["price_shift_pct"] == 0.10
    assert sym_l1["halt_duration_ns"] == 600000000000


def test_builder_with_post_trade_gateway_section() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        post_trade_gateway=PostTradeGatewaySpec(
            name="ralf-lab",
            bind_address="127.0.0.1",
            port=6001,
            allowed_roles=("CLEARING", "AUDIT"),
        ),
    )
    payload = ConfigBuilder(spec).build()

    assert payload["post_trade_gateway"]["name"] == "ralf-lab"
    assert payload["post_trade_gateway"]["bind_address"] == "127.0.0.1"
    assert payload["post_trade_gateway"]["port"] == 6001
    assert payload["post_trade_gateway"]["allowed_roles"] == ["CLEARING", "AUDIT"]
