"""
Tests for engine/config_loader.py — full coverage of validation paths.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    ScheduleConfig,
    load_engine_config,
)
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.quote import QuoteRefreshPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(content))
    return p


MINIMAL_YAML = """
symbols:
  AAPL:
    last_buy_price: 150.0
    last_sell_price: 151.0
gateways:
  fix:
    - id: TRADER01
"""


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestConfigLoaderHappyPath:
    def test_minimal_config(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert isinstance(cfg, EngineConfig)
        assert "AAPL" in cfg.symbols
        sym = cfg.symbols["AAPL"]
        assert sym.last_buy_price == 150.0
        assert sym.last_sell_price == 151.0

    def test_symbol_uppercased(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          aapl:
            last_buy_price: 100.0
        gateways:
          fix:
            - id: GW01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert "AAPL" in cfg.symbols
        assert "aapl" not in cfg.symbols

    def test_null_symbol_config_allowed(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          MSFT:
        gateways:
          fix:
            - id: GW01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert "MSFT" in cfg.symbols
        assert cfg.symbols["MSFT"].last_buy_price is None

    def test_market_maker_quotes(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes:
              - gateway_id: MM01
                bid_price: 149.0
                ask_price: 150.0
                bid_qty: 100
                ask_qty: 100
        gateways:
          fix:
            - id: MM01
              role: MARKET_MAKER
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert len(cfg.symbols["AAPL"].market_maker_quotes) == 1
        assert cfg.symbols["AAPL"].market_maker_quotes[0].gateway_id == "MM01"

    def test_multiple_gateways(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              description: First gateway
            - id: GW02
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert "GW01" in cfg.fix_gateways
        assert "GW02" in cfg.fix_gateways
        assert cfg.fix_gateways["GW01"].description == "First gateway"

    def test_gateway_mm_fields(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes:
              - gateway_id: MM01
                bid_price: 100.0
                ask_price: 101.0
                bid_qty: 50
                ask_qty: 50
        gateways:
          fix:
            - id: MM01
              role: MARKET_MAKER
              disconnect_behaviour: CANCEL_ALL
              quote_refresh_policy: NEVER_INACTIVATE
              enforce_mm_obligation: true
              mm_max_spread_ticks: 8
              mm_min_qty: 50
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        gw = cfg.fix_gateways["MM01"]
        assert gw.role == ParticipantRole.MARKET_MAKER
        assert gw.disconnect_behaviour == DisconnectBehaviour.CANCEL_ALL
        assert gw.quote_refresh_policy == QuoteRefreshPolicy.NEVER_INACTIVATE
        assert gw.enforce_mm_obligation is True
        assert gw.mm_max_spread_ticks == 8
        assert gw.mm_min_qty == 50

    def test_gateway_id_uppercased(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: trader01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert "TRADER01" in cfg.fix_gateways

    def test_allowed_symbols_property(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.allowed_symbols == frozenset({"AAPL"})

    def test_allowed_fix_gateways_property(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.allowed_fix_gateways == frozenset({"TRADER01"})

    def test_schedule_section_parsed(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        schedule:
          pre_open: "08:00"
          opening_auction_start: "09:00"
          continuous_start: "09:30"
          closing_auction_start: "15:50"
          closing_auction_end: "16:00"
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.schedule is not None
        assert isinstance(cfg.schedule, ScheduleConfig)
        assert cfg.schedule.pre_open == "08:00"
        assert cfg.schedule.continuous_start == "09:30"

    def test_no_schedule_section(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.schedule is None

    def test_sessions_enabled_defaults_to_true(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.sessions_enabled is True

    def test_sessions_enabled_true(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        sessions_enabled: true
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.sessions_enabled is True

    def test_snapshot_interval_defaults_to_point_five(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.snapshot_interval_sec == pytest.approx(0.5)

    def test_snapshot_interval_custom_value(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        snapshot_interval_sec: 1.25
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.snapshot_interval_sec == pytest.approx(1.25)

    def test_market_maker_combo(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            last_buy_price: 150.0
          MSFT:
            last_buy_price: 400.0
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_id: PAIR1
            combo_type: AON
            tif: DAY
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
              - symbol: MSFT
                side: SELL
                order_type: LIMIT
                quantity: 50
                price: 400.0
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert len(cfg.market_maker_combos) == 1
        assert cfg.market_maker_combos[0].combo_id == "PAIR1"
        assert len(cfg.market_maker_combos[0].legs) == 2

    def test_price_as_string_is_coerced(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            last_buy_price: "149.50"
            last_sell_price: "150.50"
        gateways:
          fix:
            - id: GW01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.symbols["AAPL"].last_buy_price == 149.50
        assert cfg.symbols["AAPL"].last_sell_price == 150.50

    def test_gateway_null_description_allowed(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              description:
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.fix_gateways["GW01"].description == ""

    def test_tick_decimals_defaults_to_2(self, tmp_path: Path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, MINIMAL_YAML))
        assert cfg.symbols["AAPL"].tick_decimals == 2

    def test_tick_decimals_custom_value(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          EURUSD:
            tick_decimals: 4
        gateways:
          fix:
            - id: GW01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert cfg.symbols["EURUSD"].tick_decimals == 4


# ---------------------------------------------------------------------------
# File-not-found
# ---------------------------------------------------------------------------


class TestConfigLoaderFileErrors:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_engine_config(tmp_path / "nonexistent.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("- just a list\n")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_engine_config(p)

    def test_sessions_enabled_non_bool_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        sessions_enabled: "yes"
        """
        with pytest.raises(ValueError, match="sessions_enabled"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_snapshot_interval_non_numeric_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        snapshot_interval_sec: "fast"
        """
        with pytest.raises(ValueError, match="snapshot_interval_sec"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_snapshot_interval_non_positive_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        snapshot_interval_sec: 0
        """
        with pytest.raises(ValueError, match="snapshot_interval_sec"):
            load_engine_config(_write_yaml(tmp_path, yaml))


# ---------------------------------------------------------------------------
# Symbol validation errors
# ---------------------------------------------------------------------------


class TestConfigLoaderSymbolErrors:
    def test_missing_symbols_key_raises(self, tmp_path: Path) -> None:
        yaml = """
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="'symbols'"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_symbol_not_mapping_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: "not a dict"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_bad_last_buy_price_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            last_buy_price: "not-a-number"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="last_buy_price must be a number"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_bad_last_sell_price_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            last_sell_price: "bad"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="last_sell_price must be a number"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_orders_not_list_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes: "not-a-list"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="market_maker_quotes must be a list"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_quote_not_mapping_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes:
              - 12345
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_quote_invalid_payload_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes:
              - gateway_id: MM01
                bid_price: 101.0
                ask_price: 100.0
                bid_qty: 10
                ask_qty: 10
        gateways:
          fix:
            - id: MM01
              role: MARKET_MAKER
        """
        with pytest.raises(ValueError, match="requires bid_price < ask_price"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_quote_gateway_must_be_market_maker(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_quotes:
              - gateway_id: GW01
                bid_price: 100.0
                ask_price: 101.0
                bid_qty: 10
                ask_qty: 10
        gateways:
          fix:
            - id: GW01
              role: TRADER
        """
        with pytest.raises(ValueError, match="must reference a MARKET_MAKER gateway"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_tick_decimals_out_of_range_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            tick_decimals: 9
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="tick_decimals"):
            load_engine_config(_write_yaml(tmp_path, yaml))


# ---------------------------------------------------------------------------
# Gateway validation errors
# ---------------------------------------------------------------------------


class TestConfigLoaderGatewayErrors:
    def test_missing_gateways_key_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        """
        with pytest.raises(ValueError, match="'gateways'"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_missing_fix_list_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          other: {}
        """
        with pytest.raises(ValueError, match="gateways.fix"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_empty_fix_list_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix: []
        """
        with pytest.raises(ValueError, match="at least one"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_fix_entry_not_mapping_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - "just-a-string"
        """
        with pytest.raises(ValueError, match="must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_fix_entry_missing_id_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - description: "no id here"
        """
        with pytest.raises(ValueError, match=".id must be a non-empty string"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_duplicate_gateway_id_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
            - id: GW01
        """
        with pytest.raises(ValueError, match="Duplicate gateway id"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_role_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              role: INVALID
        """
        with pytest.raises(ValueError, match="role is invalid"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_disconnect_behaviour_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              disconnect_behaviour: BAD_MODE
        """
        with pytest.raises(ValueError, match="disconnect_behaviour is invalid"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_quote_refresh_policy_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              quote_refresh_policy: SOMETIMES
        """
        with pytest.raises(ValueError, match="quote_refresh_policy is invalid"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_enforce_mm_obligation_type_raises(
        self, tmp_path: Path
    ) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              enforce_mm_obligation: "yes"
        """
        with pytest.raises(ValueError, match="enforce_mm_obligation"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_mm_max_spread_ticks_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              mm_max_spread_ticks: 0
        """
        with pytest.raises(ValueError, match="mm_max_spread_ticks"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_invalid_mm_min_qty_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              mm_min_qty: -1
        """
        with pytest.raises(ValueError, match="mm_min_qty"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_gateway_description_not_string_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
              description: 12345
        """
        with pytest.raises(ValueError, match="description must be a string"):
            load_engine_config(_write_yaml(tmp_path, yaml))


# ---------------------------------------------------------------------------
# Combo validation errors
# ---------------------------------------------------------------------------


class TestConfigLoaderComboErrors:
    def test_combo_not_list_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos: "bad"
        """
        with pytest.raises(ValueError, match="must be a list"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_not_mapping_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - "just-a-string"
        """
        with pytest.raises(ValueError, match="must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_missing_id_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
          MSFT: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_type: AON
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
              - symbol: MSFT
                side: SELL
                order_type: LIMIT
                quantity: 50
                price: 400.0
        """
        with pytest.raises(ValueError, match="combo_id must be a non-empty string"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_invalid_type_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
          MSFT: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_id: PAIR1
            combo_type: INVALID
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
              - symbol: MSFT
                side: SELL
                order_type: LIMIT
                quantity: 50
                price: 400.0
        """
        with pytest.raises(ValueError, match="combo_type is invalid"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_too_few_legs_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_id: BAD
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
        """
        with pytest.raises(ValueError, match="at least 2 legs"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_duplicate_symbol_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_id: DUP
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
              - symbol: AAPL
                side: SELL
                order_type: LIMIT
                quantity: 100
                price: 155.0
        """
        with pytest.raises(ValueError, match="duplicate symbol"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_combo_unknown_symbol_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL: {}
        gateways:
          fix:
            - id: GW01
        market_maker_combos:
          - combo_id: PAIR1
            legs:
              - symbol: AAPL
                side: BUY
                order_type: LIMIT
                quantity: 100
                price: 150.0
              - symbol: UNKNOWN
                side: SELL
                order_type: LIMIT
                quantity: 100
                price: 155.0
        """
        with pytest.raises(ValueError, match="unknown symbol"):
            load_engine_config(_write_yaml(tmp_path, yaml))
