from __future__ import annotations

from edumatcher.config_gen.builder import (
    ApiCredentialSpec,
    ApiGatewaySpec,
    ComboLegSpec,
    ComboSpec,
    ConfigBuilder,
    ConfigSpec,
    IndexSpec,
    MarketDataGatewaySpec,
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


def test_builder_with_seeded_mm_quotes_emits_prices() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[
            parse_gateway_spec("TRADER01"),
            parse_gateway_spec("MM01:MARKET_MAKER"),
        ],
        emit_mm_defaults=True,
        random_seed=7,
        seed_mm_mid_range=(20.0, 30.0),
    )
    payload = ConfigBuilder(spec).build()

    quote = payload["symbols"]["AAPL"]["market_maker_quotes"][0]
    assert quote["gateway_id"] == "MM01"
    assert quote["bid_price"] is not None
    assert quote["ask_price"] is not None
    assert quote["bid_price"] < quote["ask_price"]


def test_builder_seed_last_prices_from_mm_uses_midpoint() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[
            parse_gateway_spec("TRADER01"),
            parse_gateway_spec("MM01:MARKET_MAKER"),
        ],
        emit_mm_defaults=True,
        random_seed=11,
        seed_mm_mid_range=(20.0, 20.03),
        seed_last_prices_from_mm=True,
    )
    payload = ConfigBuilder(spec).build()

    quote = payload["symbols"]["AAPL"]["market_maker_quotes"][0]
    midpoint = (quote["bid_price"] + quote["ask_price"]) / 2
    assert payload["symbols"]["AAPL"]["last_buy_price"] == midpoint
    assert payload["symbols"]["AAPL"]["last_sell_price"] == midpoint


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


def test_builder_with_market_data_gateway_section() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        market_data_gateway=MarketDataGatewaySpec(
            enabled=True,
            name="md-lab",
            bind_address="127.0.0.1",
            port=7001,
            heartbeat_interval_sec=2,
            idle_timeout_sec=7,
            replay_window_sec=120,
            max_symbols_per_client=50,
            max_client_queue=2000,
        ),
    )
    payload = ConfigBuilder(spec).build()

    assert payload["market_data_gateway"]["enabled"] is True
    assert payload["market_data_gateway"]["name"] == "md-lab"
    assert payload["market_data_gateway"]["bind_address"] == "127.0.0.1"
    assert payload["market_data_gateway"]["port"] == 7001
    assert payload["market_data_gateway"]["max_symbols_per_client"] == 50


def test_builder_with_api_gateway_generates_credentials() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01"), parse_gateway_spec("OPS01:ADMIN")],
        random_seed=42,
        api_gateways=(ApiGatewaySpec(name="desk", generate_readonly_key=True),),
    )
    payload = ConfigBuilder(spec).build()

    api_gateway = payload["api_gateways"]["desk"]
    assert api_gateway["host"] == "127.0.0.1"
    assert api_gateway["port"] == 8080
    assert api_gateway["rate_limit"] == {"writes_per_second": 10, "burst": 20}
    assert api_gateway["timeouts"]["wait_ack_sec"] == 3.0
    assert [item["gateway_id"] for item in api_gateway["credentials"]] == [
        "TRADER01",
        "OPS01",
        None,
    ]
    assert all(
        str(item["api_key"]).startswith("key-") for item in api_gateway["credentials"]
    )


def test_builder_with_api_gateway_explicit_credentials_skip_duplicate_generation() -> (
    None
):
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01"), parse_gateway_spec("TRADER02")],
        api_gateways=(
            ApiGatewaySpec(
                name="desk",
                credentials=(
                    ApiCredentialSpec("manual-key", "TRADER01", "manual trader"),
                ),
                generate_keys=True,
            ),
        ),
    )
    payload = ConfigBuilder(spec).build()

    credentials = payload["api_gateways"]["desk"]["credentials"]
    assert credentials[0] == {
        "api_key": "manual-key",
        "gateway_id": "TRADER01",
        "description": "manual trader",
    }
    assert credentials[1]["gateway_id"] == "TRADER02"


def test_builder_with_multiple_api_gateways_filters_gateway_ids() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01"), parse_gateway_spec("TRADER02")],
        api_gateways=(
            ApiGatewaySpec(name="desk", gateway_ids=("TRADER01",)),
            ApiGatewaySpec(name="algos", port=8081, gateway_ids=("TRADER02",)),
        ),
    )
    payload = ConfigBuilder(spec).build()

    assert payload["api_gateways"]["desk"]["credentials"][0]["gateway_id"] == "TRADER01"
    assert (
        payload["api_gateways"]["algos"]["credentials"][0]["gateway_id"] == "TRADER02"
    )


def test_builder_rejects_gateway_id_in_multiple_api_gateways() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        api_gateways=(
            ApiGatewaySpec(name="desk", gateway_ids=("TRADER01",)),
            ApiGatewaySpec(name="algos", gateway_ids=("TRADER01",)),
        ),
    )

    try:
        ConfigBuilder(spec).build()
    except ValueError as exc:
        assert "multiple api_gateways" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected duplicate gateway_id rejection")


def test_builder_outstanding_shares_emitted() -> None:
    spec = ConfigSpec(
        symbols=["AAPL", "MSFT"],
        gateways=[parse_gateway_spec("TRADER01")],
        outstanding_shares={"AAPL": 15_400_000_000, "MSFT": 7_430_000_000},
    )
    payload = ConfigBuilder(spec).build()

    assert payload["symbols"]["AAPL"]["outstanding_shares"] == 15_400_000_000
    assert payload["symbols"]["MSFT"]["outstanding_shares"] == 7_430_000_000


def test_builder_outstanding_shares_omitted_when_not_set() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    payload = ConfigBuilder(spec).build()

    assert "outstanding_shares" not in payload["symbols"]["AAPL"]


def test_builder_index_section_emitted() -> None:
    spec = ConfigSpec(
        symbols=["AAPL", "MSFT", "TSLA"],
        gateways=[parse_gateway_spec("TRADER01")],
        indices=(
            IndexSpec(
                id="EDU100",
                description="Broad tech benchmark",
                constituents=("AAPL", "MSFT", "TSLA"),
            ),
        ),
    )
    payload = ConfigBuilder(spec).build()

    assert "indices" in payload
    idx = payload["indices"][0]
    assert idx["id"] == "EDU100"
    assert idx["description"] == "Broad tech benchmark"
    assert idx["base_value"] == 1000.0
    assert idx["publish_interval_sec"] == 1.0
    assert idx["history_file"] == "data/indexes/EDU100_history.jsonl"
    assert idx["state_file"] == "data/indexes/EDU100_state.json"
    assert idx["constituents"] == ["AAPL", "MSFT", "TSLA"]


def test_builder_index_custom_paths_and_overrides() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        indices=(
            IndexSpec(
                id="MYIDX",
                description="Custom index",
                constituents=("AAPL",),
                base_value=500.0,
                publish_interval_sec=2.0,
                history_file="custom/myidx_history.jsonl",
                state_file="custom/myidx_state.json",
            ),
        ),
    )
    payload = ConfigBuilder(spec).build()

    idx = payload["indices"][0]
    assert idx["base_value"] == 500.0
    assert idx["publish_interval_sec"] == 2.0
    assert idx["history_file"] == "custom/myidx_history.jsonl"
    assert idx["state_file"] == "custom/myidx_state.json"


def test_builder_no_indices_omits_section() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    payload = ConfigBuilder(spec).build()

    assert "indices" not in payload


def test_builder_combos_emitted() -> None:
    spec = ConfigSpec(
        symbols=["AAPL", "MSFT"],
        gateways=[parse_gateway_spec("TRADER01")],
        combos=[
            ComboSpec(
                combo_id="SEED-PAIR",
                combo_type="AON",
                tif="DAY",
                legs=(
                    ComboLegSpec(
                        symbol="AAPL",
                        side="BUY",
                        order_type="LIMIT",
                        quantity=100,
                        price=20950,
                    ),
                    ComboLegSpec(
                        symbol="MSFT",
                        side="SELL",
                        order_type="LIMIT",
                        quantity=50,
                        price=41550,
                    ),
                ),
            )
        ],
    )
    payload = ConfigBuilder(spec).build()

    assert "market_maker_combos" in payload
    combo = payload["market_maker_combos"][0]
    assert combo["combo_id"] == "SEED-PAIR"
    assert combo["combo_type"] == "AON"
    assert combo["tif"] == "DAY"
    assert len(combo["legs"]) == 2
    assert combo["legs"][0] == {
        "symbol": "AAPL",
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": 100,
        "price": 20950,
        "stop_price": None,
        "smp_action": "NONE",
    }
    assert combo["legs"][1]["symbol"] == "MSFT"


def test_builder_no_combos_omits_section() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    payload = ConfigBuilder(spec).build()
    assert "market_maker_combos" not in payload


def test_builder_cb_defaults_resumption_mode() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        cb_levels=[
            parse_cb_spec("L1:0.07:5:AUCTION"),
            parse_cb_spec("L2:0.13:15:CONTINUOUS"),
            parse_cb_spec("L3:0.20"),
        ],
    )
    payload = ConfigBuilder(spec).build()

    levels = payload["circuit_breaker_defaults"]["levels"]
    assert levels["L1"]["resumption_mode"] == "AUCTION"
    assert levels["L2"]["resumption_mode"] == "CONTINUOUS"
    assert levels["L3"]["resumption_mode"] == "AUCTION"


def test_builder_gateway_description_emitted() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[
            parse_gateway_spec("MM01:MARKET_MAKER:CANCEL_QUOTES_ONLY:Primary MM")
        ],
        emit_mm_defaults=True,
    )
    payload = ConfigBuilder(spec).build()
    gw = payload["gateways"]["alf"][0]
    assert gw["description"] == "Primary MM"


def test_builder_gateway_no_description_omits_key() -> None:
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
    )
    payload = ConfigBuilder(spec).build()
    gw = payload["gateways"]["alf"][0]
    assert "description" not in gw


def test_builder_per_symbol_enforce_mm_obligation() -> None:
    override = SymbolOverride(enforce_mm_obligation=True)
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        enforce_mm_obligations=False,
        symbol_overrides={"AAPL": override},
    )
    payload = ConfigBuilder(spec).build()

    assert "mm_obligation_defaults" in payload
    sym_overrides = payload["mm_obligation_defaults"]["symbols"]
    assert sym_overrides["AAPL"]["enforce_mm_obligation"] is True


def test_builder_per_symbol_cb_resumption_mode() -> None:
    override = SymbolOverride(
        cb_shift={"L2": 0.10}, cb_resumption_mode={"L2": "CONTINUOUS"}
    )
    spec = ConfigSpec(
        symbols=["AAPL"],
        gateways=[parse_gateway_spec("TRADER01")],
        symbol_overrides={"AAPL": override},
    )
    payload = ConfigBuilder(spec).build()

    cb = payload["symbols"]["AAPL"]["circuit_breaker"]["levels"]
    assert cb["L2"]["resumption_mode"] == "CONTINUOUS"
