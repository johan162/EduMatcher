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

    def test_market_maker_orders(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_orders:
              - "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=149"
        gateways:
          fix:
            - id: GW01
        """
        cfg = load_engine_config(_write_yaml(tmp_path, yaml))
        assert len(cfg.symbols["AAPL"].market_maker_orders) == 1

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
            market_maker_orders: "not-a-list"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="must be a list"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_order_not_string_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_orders:
              - 12345
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="must be a string"):
            load_engine_config(_write_yaml(tmp_path, yaml))

    def test_mm_order_missing_new_prefix_raises(self, tmp_path: Path) -> None:
        yaml = """
        symbols:
          AAPL:
            market_maker_orders:
              - "CANCEL|ID=123"
        gateways:
          fix:
            - id: GW01
        """
        with pytest.raises(ValueError, match="must start with 'NEW|'"):
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
