"""
Tests for the pm-cverifier tool — covers all four layers, formatter, CLI, and
integration scenarios using fixture YAML files.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from edumatcher.cverifier import (
    layer1_yaml,
    layer2_schema,
    layer3_semantic,
    layer4_complete,
)
from edumatcher.cverifier import risk_summary as risk_summary_mod
from edumatcher.cverifier.cli import (
    _compute_exit_code,
    _compute_verdict,
    _parse_args,
    main,
    run,
)
from edumatcher.cverifier.formatter import format_json, format_text
from edumatcher.cverifier.models import (
    CheckResult,
    RiskSummary,
    Severity,
    VerificationReport,
)

FIXTURES = Path(__file__).parent / "fixtures" / "cverifier"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw(content: str) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(textwrap.dedent(content))


def _write_yaml(tmp_path: Path, content: str, name: str = "config.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


def _codes(results: list[CheckResult]) -> list[str]:
    return [r.code for r in results]


# ---------------------------------------------------------------------------
# Layer 1 — YAML syntax
# ---------------------------------------------------------------------------


class TestLayer1:
    def test_file_not_found(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.yaml"
        results = layer1_yaml.check(None, p)
        assert "Y001" in _codes(results)
        assert results[0].severity is Severity.ERROR

    def test_unreadable_file(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text("symbols: {}")
        p.chmod(0o000)
        results = layer1_yaml.check(None, p)
        # On macOS root can always read, so only check if not running as root
        if results:
            assert "Y002" in _codes(results)
        p.chmod(0o644)  # restore for cleanup

    def test_yaml_parse_error(self, tmp_path: Path) -> None:
        p = _write_yaml(tmp_path, "key: [unclosed\n")
        results = layer1_yaml.check(None, p)
        assert "Y003" in _codes(results)

    def test_top_level_not_mapping(self, tmp_path: Path) -> None:
        p = _write_yaml(tmp_path, "- item1\n- item2\n")
        results = layer1_yaml.check(None, p)
        assert "Y004" in _codes(results)

    def test_valid_yaml_no_findings(self, tmp_path: Path) -> None:
        p = _write_yaml(tmp_path, "symbols:\n  AAPL:\n    tick_decimals: 2\n")
        results = layer1_yaml.check(None, p)
        assert results == []


# ---------------------------------------------------------------------------
# Layer 2 — Schema
# ---------------------------------------------------------------------------


class TestLayer2TopLevel:
    def test_missing_symbols(self) -> None:
        raw = _raw("gateways:\n  alf:\n    - id: GW01\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S001" in _codes(results)

    def test_empty_symbols(self) -> None:
        raw = _raw("symbols: {}\ngateways:\n  alf:\n    - id: GW01\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S004" in _codes(results)

    def test_missing_gateways(self) -> None:
        raw = _raw("symbols:\n  AAPL:\n    tick_decimals: 2\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S002" in _codes(results)

    def test_gateways_not_mapping(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways: not_a_mapping\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S002" in _codes(results)

    def test_missing_alf(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways:\n  other: []\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S003" in _codes(results)

    def test_empty_alf(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways:\n  alf: []\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S005" in _codes(results)


class TestLayer2Symbols:
    def test_tick_decimals_out_of_range(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 9\ngateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S010" in _codes(results)

    def test_tick_decimals_not_int(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 'abc'\ngateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S010" in _codes(results)

    def test_last_buy_price_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 'bad'\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S011" in _codes(results)

    def test_outstanding_shares_negative(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    outstanding_shares: -5\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S012" in _codes(results)

    def test_outstanding_shares_not_int(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    outstanding_shares: bad\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S012" in _codes(results)

    def test_s013_undefined_risk_level(self) -> None:
        raw = _raw(
            "symbols:\n  TSLA:\n    tick_decimals: 2\n    level: STRICT\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    DEFAULT: {}\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S013" in _codes(results)

    def test_s013_level_set_no_risk_controls(self) -> None:
        raw = _raw(
            "symbols:\n  TSLA:\n    tick_decimals: 2\n    level: STRICT\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S013" in _codes(results)

    def test_s014_mm_quote_missing_field(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 100.0\n"
            "gateways:\n  alf:\n    - id: MM01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S014" in _codes(results)

    def test_s015_bid_gte_ask(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 155.0\n"
            "        ask_price: 154.0\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S015" in _codes(results)

    def test_s017_mm_quotes_not_list(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes: not_a_list\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S017" in _codes(results)

    def test_s018_mm_quote_item_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n      - bad\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S018" in _codes(results)

    def test_s019_mm_quote_gateway_id_blank(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: ''\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S019" in _codes(results)

    def test_symbol_entry_not_mapping_is_ignored(self) -> None:
        raw = _raw("symbols:\n  AAPL: bad\n" "gateways:\n  alf:\n    - id: GW01\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert isinstance(results, list)

    def test_s016_qty_non_integer(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: bad\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S016" in _codes(results)


class TestLayer2Gateways:
    def test_s020_missing_id(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - role: TRADER\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S020" in _codes(results)

    def test_s021_duplicate_id(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n"
            "    - id: GW01\n      role: TRADER\n"
            "    - id: GW01\n      role: ADMIN\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S021" in _codes(results)

    def test_s022_invalid_role(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n      role: INVALID\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S022" in _codes(results)

    def test_s023_invalid_disconnect(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n"
            "    - id: GW01\n      role: TRADER\n      disconnect_behaviour: NUKE_ALL\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S023" in _codes(results)

    def test_s024_invalid_quote_refresh_policy(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      quote_refresh_policy: UNKNOWN\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S024" in _codes(results)

    def test_s025_gateway_enforce_mm_not_bool(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      enforce_mm_obligation: maybe\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S025" in _codes(results)

    def test_s026_gateway_mm_limits_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      mm_max_spread_ticks: 0\n"
            "      mm_min_qty: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S026" in _codes(results)

    def test_s027_mm_obligations_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      mm_obligations: not_a_mapping\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S027" in _codes(results)

    def test_s028_mm_obligations_entry_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      mm_obligations:\n"
            "        AAPL:\n"
            "          enforce_mm_obligation: bad\n"
            "          max_spread_ticks: 0\n"
            "          min_qty: -1\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S028" in _codes(results)

    def test_gateways_non_mapping_skips_gateway_checks(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways: bad\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S002" in _codes(results)

    def test_alf_non_list_skips_gateway_checks(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways:\n  alf: bad\n")
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S003" in _codes(results)

    def test_non_mapping_gateway_entry_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n"
            "  alf:\n"
            "    - bad\n"
            "    - id: GW01\n      role: TRADER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S020" not in _codes(results)

    def test_s028_mm_obligation_symbol_value_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      mm_obligations:\n"
            "        AAPL: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S028" in _codes(results)

    def test_mm_obligation_fields_missing_are_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "      mm_obligations:\n"
            "        AAPL: {}\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S028" not in _codes(results)


class TestLayer2RuntimeAndMMDefaults:
    def test_s060_sessions_enabled_not_bool(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: maybe\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S060" in _codes(results)

    def test_s061_snapshot_interval_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "snapshot_interval_sec: 0\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S061" in _codes(results)

    def test_s062_enforce_collars_not_bool(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_collars: maybe\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S062" in _codes(results)

    def test_s063_enforce_cb_not_bool(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: maybe\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S063" in _codes(results)

    def test_s064_schedule_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "schedule: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S064" in _codes(results)

    def test_s070_mm_defaults_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S070" in _codes(results)

    def test_s071_mm_defaults_enforce_not_bool(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults:\n  enforce_mm_obligation: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S071" in _codes(results)

    def test_s072_s073_mm_defaults_invalid_limits(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults:\n"
            "  mm_max_spread_ticks: 0\n"
            "  mm_min_qty: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S072" in _codes(results)
        assert "S073" in _codes(results)

    def test_s074_mm_defaults_symbols_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults:\n"
            "  symbols: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S074" in _codes(results)

    def test_s075_s076_s077_mm_defaults_symbol_entry_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults:\n"
            "  symbols:\n"
            "    AAPL:\n"
            "      enforce_mm_obligation: bad\n"
            "      mm_max_spread_ticks: 0\n"
            "      mm_min_qty: -1\n"
            "    TSLA: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S075" in _codes(results)
        assert "S076" in _codes(results)
        assert "S077" in _codes(results)


class TestLayer2BalfGatewaySchema:
    def test_s050_balf_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "balf_gateway: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S050" in _codes(results)

    def test_s051_balf_port_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "balf_gateway:\n  port: 70000\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S051" in _codes(results)

    def test_s052_balf_positive_int_fields_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "balf_gateway:\n"
            "  max_connections: 0\n"
            "  max_client_queue: true\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S052" in _codes(results)

    def test_s053_balf_positive_float_fields_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "balf_gateway:\n"
            "  heartbeat_interval_sec: 0\n"
            "  error_window_sec: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S053" in _codes(results)

    def test_s054_balf_duplicate_policy_invalid(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "balf_gateway:\n  duplicate_session_policy: BAD\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S054" in _codes(results)


class TestLayer2CBDefaults:
    def test_s030_cb_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults: not_a_mapping\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S030" in _codes(results)

    def test_s030_levels_not_mapping(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels: not_a_mapping\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S030" in _codes(results)

    def test_s031_missing_price_shift_pct(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n      halt_duration_ns: 300000000000\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S031" in _codes(results)

    def test_s032_price_shift_pct_out_of_range(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n      price_shift_pct: 1.5\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S032" in _codes(results)

    def test_s033_halt_duration_not_int(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n"
            "      price_shift_pct: 0.07\n      halt_duration_ns: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S033" in _codes(results)

    def test_s033_halt_duration_negative(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n"
            "      price_shift_pct: 0.07\n      halt_duration_ns: -1\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S033" in _codes(results)

    def test_s034_invalid_resumption_mode(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n"
            "      price_shift_pct: 0.07\n      resumption_mode: INVALID\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S034" in _codes(results)

    def test_m014_levels_not_ascending(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n"
            "    L1:\n      price_shift_pct: 0.13\n"
            "    L2:\n      price_shift_pct: 0.07\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "M014" in _codes(results)

    def test_levels_ascending_ok(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n"
            "    L1:\n      price_shift_pct: 0.07\n"
            "    L2:\n      price_shift_pct: 0.13\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        codes = _codes(results)
        assert "M014" not in codes
        assert "S031" not in codes

    def test_levels_absent_is_accepted(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults: {}\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S030" not in _codes(results)

    def test_non_mapping_cb_level_entry_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n"
            "  levels:\n"
            "    L1: bad\n"
            "    L2:\n"
            "      price_shift_pct: 0.2\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S031" not in _codes(results)


class TestLayer2RiskControls:
    def test_s040_default_level_undefined(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  default_level: MISSING\n  levels:\n    DEFAULT: {}\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S040" in _codes(results)

    def test_s035_cb_in_risk_level(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n      circuit_breaker: {}\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S035" in _codes(results)

    def test_s041_static_band_out_of_range(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n"
            "      collar:\n        static_band_pct: 1.5\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S041" in _codes(results)

    def test_s042_dynamic_band_out_of_range(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n"
            "      collar:\n        dynamic_band_pct: 0\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S042" in _codes(results)

    def test_risk_controls_non_mapping_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S040" not in _codes(results)

    def test_risk_levels_non_mapping_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels: bad\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S040" not in _codes(results)

    def test_non_mapping_risk_level_entry_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n"
            "  levels:\n"
            "    DEFAULT: bad\n"
            "  default_level: DEFAULT\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S041" not in _codes(results)


# ---------------------------------------------------------------------------
# Layer 3 — Semantic
# ---------------------------------------------------------------------------


class TestLayer3MMSeeds:
    def test_m001_mm_gw_no_seeds(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 150.0\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M001" in _codes(results)

    def test_m002_seed_unknown_gateway(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 150.0\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: GHOST\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M002" in _codes(results)

    def test_m003_spread_too_wide(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 150.0\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 140.0\n"
            "        ask_price: 160.0\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
            "mm_obligation_defaults:\n  mm_max_spread_ticks: 10\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M003" in _codes(results)

    def test_m019_mm_defaults_unknown_symbol(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
            "mm_obligation_defaults:\n"
            "  symbols:\n"
            "    GHOST:\n"
            "      mm_max_spread_ticks: 10\n"
            "      mm_min_qty: 100\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M019" in _codes(results)

    def test_m020_seed_gateway_not_market_maker(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: TRADER01\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: TRADER01\n      role: TRADER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M020" in _codes(results)

    def test_mm_seeds_tolerates_non_mapping_gateway_and_quote_entries(self) -> None:
        raw = _raw(
            "symbols:\n"
            "  AAPL:\n"
            "    market_maker_quotes:\n"
            "      - bad\n"
            "      - gateway_id: MM01\n        bid_price: bad\n        ask_price: 150.1\n"
            "gateways:\n"
            "  alf:\n"
            "    - bad\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert isinstance(results, list)

    def test_mm_max_spread_invalid_type_uses_default_limit(self) -> None:
        raw = _raw(
            "symbols:\n"
            "  AAPL:\n"
            "    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 100\n        ask_price: 100.2\n"
            "gateways:\n"
            "  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "mm_obligation_defaults:\n"
            "  mm_max_spread_ticks: bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M003" in _codes(results)

    def test_mm_seeds_symbols_non_mapping_returns_early(self) -> None:
        raw = _raw(
            "symbols: bad\ngateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert isinstance(results, list)

    def test_mm_seeds_non_mapping_symbol_cfg_and_quotes_non_list(self) -> None:
        raw = _raw(
            "symbols:\n"
            "  AAPL: bad\n"
            "  TSLA:\n"
            "    market_maker_quotes: bad\n"
            "gateways:\n"
            "  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M001" in _codes(results)


class TestLayer3Sessions:
    def test_m004_sessions_enabled_no_schedule(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: true\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M004" in _codes(results)

    def test_m005_sessions_disabled_schedule_present(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: false\n"
            "schedule:\n  pre_open: '09:00'\n  continuous_start: '09:30'\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M005" in _codes(results)

    def test_m006_schedule_out_of_order(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: true\n"
            "schedule:\n"
            "  pre_open: '09:30'\n"
            "  opening_auction_start: '09:25'\n"
            "  continuous_start: '09:30'\n"
            "  closing_auction_start: '16:00'\n"
            "  closing_auction_end: '16:05'\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M006" in _codes(results)

    def test_schedule_in_order_ok(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: true\n"
            "schedule:\n"
            "  pre_open: '09:00'\n"
            "  opening_auction_start: '09:25'\n"
            "  continuous_start: '09:30'\n"
            "  closing_auction_start: '16:00'\n"
            "  closing_auction_end: '16:05'\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M006" not in _codes(results)

    def test_parse_hhmm_invalid_formats(self) -> None:
        assert layer3_semantic._parse_hhmm(123) is None
        assert layer3_semantic._parse_hhmm("09") is None
        assert layer3_semantic._parse_hhmm("aa:bb") is None


class TestLayer3EnforceFlags:
    def test_m007_collar_configured_not_enforced(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n      collar:\n        static_band_pct: 0.2\n"
            "enforce_collars: false\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M007" in _codes(results)

    def test_m008_cb_configured_not_enforced(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n  levels:\n    L1:\n      price_shift_pct: 0.07\n"
            "enforce_circuit_breakers: false\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M008" in _codes(results)


class TestLayer3Indices:
    def test_m009_constituent_not_in_symbols(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: EDU100\n    description: Test\n"
            "    constituents:\n      - AAPL\n      - GHOST\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M009" in _codes(results)

    def test_m010_no_outstanding_shares(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 150.0\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: EDU100\n    description: Test\n"
            "    constituents:\n      - AAPL\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M010" in _codes(results)

    def test_m011_too_many_indices(self) -> None:
        indices_yaml = "\n".join(
            f"  - id: IDX{i}\n    description: Index {i}\n    constituents: []"
            for i in range(6)
        )
        raw = _raw(
            f"symbols:\n  AAPL: {{}}\ngateways:\n  alf:\n    - id: GW01\n"
            f"indices:\n{indices_yaml}\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M011" in _codes(results)

    def test_indices_non_list_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices: bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M009" not in _codes(results)

    def test_index_item_non_mapping_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M009" not in _codes(results)

    def test_index_constituents_non_list_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n"
            "  - id: IDX1\n"
            "    constituents: bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M009" not in _codes(results)


class TestLayer3Combos:
    def test_m012_gtc_combo(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "market_maker_combos:\n  - combo_id: C1\n    tif: GTC\n    legs: []\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M012" in _codes(results)

    def test_m015_combo_leg_bad_symbol(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n"
            "market_maker_combos:\n  - combo_id: C1\n    tif: DAY\n"
            "    legs:\n      - symbol: GHOST\n        side: BUY\n        ratio: 1\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M015" in _codes(results)

    def test_combo_and_leg_non_mapping_entries_ignored(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "market_maker_combos:\n"
            "  - bad\n"
            "  - combo_id: C2\n"
            "    legs: bad\n"
            "  - combo_id: C3\n"
            "    legs:\n"
            "      - bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M015" not in _codes(results)


class TestLayer3AdminGateway:
    def test_m013_no_admin_gateway(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: TRADER01\n      role: TRADER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M013" in _codes(results)

    def test_c010_leave_all_non_admin(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n"
            "    - id: TRADER01\n      role: TRADER\n      disconnect_behaviour: LEAVE_ALL\n"
            "    - id: OPS01\n      role: ADMIN\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "C010" in _codes(results)

    def test_m016_post_trade_no_admin(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\ngateways:\n  alf:\n    - id: GW01\n      role: TRADER\n"
            "post_trade_gateway:\n  id: RALF01\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M016" in _codes(results)

    def test_admin_gateway_checks_tolerate_bad_gateway_shape(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n"
            "  alf:\n"
            "    - bad\n"
            "post_trade_gateway:\n"
            "  port: 5570\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M013" in _codes(results)
        assert "M016" in _codes(results)

    def test_admin_gateway_checks_return_on_invalid_gateway_container(self) -> None:
        raw = _raw("symbols:\n  AAPL: {}\ngateways: bad\n")
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M013" in _codes(results)


class TestLayer3BalfSemantic:
    def test_m017_balf_timeout_not_greater_than_interval(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: OPS01\n      role: ADMIN\n"
            "balf_gateway:\n"
            "  heartbeat_interval_sec: 5\n"
            "  heartbeat_timeout_sec: 5\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M017" in _codes(results)

    def test_m018_balf_port_conflict_market_data(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: OPS01\n      role: ADMIN\n"
            "balf_gateway:\n  port: 5560\n"
            "market_data_gateway:\n  port: 5560\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M018" in _codes(results)

    def test_balf_semantic_ignores_non_int_port(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: OPS01\n      role: ADMIN\n"
            "balf_gateway:\n  port: bad\n"
            "post_trade_gateway:\n  port: 5580\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M018" not in _codes(results)

    def test_balf_semantic_ignores_non_numeric_heartbeat_values(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: OPS01\n      role: ADMIN\n"
            "balf_gateway:\n"
            "  heartbeat_interval_sec: bad\n"
            "  heartbeat_timeout_sec: still_bad\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M017" not in _codes(results)


# ---------------------------------------------------------------------------
# Layer 4 — Completeness
# ---------------------------------------------------------------------------


class TestLayer4:
    def test_c001_no_reference_prices(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C001" in _codes(results)

    def test_c002_only_one_price(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    last_buy_price: 150.0\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C002" in _codes(results)

    def test_c003_enforce_collar_no_collar(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_collars: true\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C003" in _codes(results)

    def test_c003_not_fired_when_inline_collar(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    collar:\n      static_band_pct: 0.2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_collars: true\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C003" not in _codes(results)

    def test_c004_enforce_cb_no_levels(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: true\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C004" in _codes(results)

    def test_c005_mm_gw_no_obligation_defaults(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C005" in _codes(results)

    def test_c006_mm_obligation_not_enforced(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
            "mm_obligation_defaults:\n  enforce_mm_obligation: false\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C006" in _codes(results)

    def test_c007_default_snapshot_interval(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C007" in _codes(results)

    def test_c007_not_fired_custom_interval(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "snapshot_interval_sec: 1.0\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C007" not in _codes(results)

    def test_c008_index_constituent_no_price(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n    outstanding_shares: 1000\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: IDX1\n    description: Test\n    constituents:\n      - AAPL\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C008" in _codes(results)

    def test_c009_no_sessions_no_schedule(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: false\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C009" in _codes(results)

    def test_c011_unused_risk_level(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls:\n  levels:\n    UNUSED: {}\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C011" in _codes(results)

    def test_c012_many_symbols_low_interval(self) -> None:
        syms = "\n".join(f"  SYM{i}:\n    tick_decimals: 2" for i in range(25))
        raw = _raw(
            f"symbols:\n{syms}\ngateways:\n  alf:\n    - id: GW01\n"
            "snapshot_interval_sec: 0.1\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C012" in _codes(results)

    def test_c013_index_path_nonexistent_dir(self, tmp_path: Path) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: IDX1\n    description: Test\n    constituents: []\n"
            "    history_file: /nonexistent/path/idx.csv\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert "C013" in _codes(results)


class TestLayer4EdgeCases:
    def test_handles_non_mapping_symbols(self) -> None:
        raw = _raw("symbols: []\ngateways:\n  alf:\n    - id: GW01\n")
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert isinstance(results, list)

    def test_handles_non_mapping_risk_controls(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "risk_controls: bad\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert isinstance(results, list)

    def test_handles_non_mapping_index_entries(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL: {}\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - bad\n"
        )
        results = layer4_complete.check(raw, Path("x.yaml"))
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Risk summary
# ---------------------------------------------------------------------------


class TestRiskSummary:
    def test_basic(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n  MSFT:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n"
            "    - id: TRADER01\n      role: TRADER\n"
            "    - id: OPS01\n      role: ADMIN\n"
            "enforce_collars: true\n"
            "enforce_circuit_breakers: false\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "AAPL" in rs.symbols
        assert "MSFT" in rs.symbols
        assert rs.gateways["TRADER01"] == "TRADER"
        assert rs.admin_gateway == "OPS01"
        assert rs.collars_enforced is True
        assert rs.circuit_breakers_enforced is False

    def test_indices_listed(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: IDX1\n    description: Test\n    constituents: []\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "IDX1" in rs.indices

    def test_sessions_summary(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: true\n"
            "schedule:\n"
            "  pre_open: '09:00'\n"
            "  continuous_start: '09:30'\n"
            "  closing_auction_end: '16:05'\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.sessions_enabled is True
        assert "09:00" in rs.schedule_summary

    def test_collar_description_configured(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_collars: true\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n"
            "      collar:\n        static_band_pct: 0.2\n        dynamic_band_pct: 0.02\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.collars_configured is True
        assert "20%" in rs.collar_description

    def test_cb_using_defaults(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: true\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "built-in defaults" in rs.cb_description

    def test_cb_disabled(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: false\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.cb_description == "disabled"

    def test_mm_obligations_enforced(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "mm_obligation_defaults:\n  enforce_mm_obligation: true\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.mm_obligations_enforced is True

    def test_sessions_enabled_no_schedule(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "sessions_enabled: true\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "enabled (no schedule)" in rs.schedule_summary

    def test_cb_configured_description(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: true\n"
            "circuit_breaker_defaults:\n  levels:\n"
            "    L1:\n      price_shift_pct: 0.07\n      halt_duration_ns: 300000000000\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "L1" in rs.cb_description
        assert "built-in defaults" not in rs.cb_description

    def test_handles_invalid_collar_values(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_collars: true\n"
            "risk_controls:\n  levels:\n    DEFAULT:\n"
            "      collar:\n        static_band_pct: bad\n        dynamic_band_pct: also_bad\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.collars_configured is True

    def test_handles_invalid_cb_values(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "enforce_circuit_breakers: true\n"
            "circuit_breaker_defaults:\n  levels:\n"
            "    L1:\n      price_shift_pct: bad\n      halt_duration_ns: bad\n"
        )
        rs = risk_summary_mod.build(raw)
        assert "L1" in rs.cb_description

    def test_ignores_non_mapping_cb_levels(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "circuit_breaker_defaults:\n"
            "  levels:\n"
            "    BAD: oops\n"
        )
        rs = risk_summary_mod.build(raw)
        assert rs.circuit_breakers_configured is True


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def _make_report(
        self, results: list[CheckResult] | None = None
    ) -> VerificationReport:
        rs = RiskSummary(
            symbols=["AAPL"],
            gateways={"GW01": "TRADER"},
            sessions_enabled=False,
            schedule_summary="always CONTINUOUS",
            collars_enforced=False,
            collars_configured=False,
            collar_description="disabled",
            circuit_breakers_enforced=True,
            circuit_breakers_configured=False,
            cb_description="L1=7% (5 min)",
            mm_obligations_enforced=False,
            admin_gateway=None,
        )
        r = results or []
        n_errors = sum(1 for x in r if x.severity is Severity.ERROR)
        n_warns = sum(1 for x in r if x.severity is Severity.WARN)
        n_info = sum(1 for x in r if x.severity is Severity.INFO)
        verdict = "ERROR" if n_errors else "WARN" if n_warns else "OK"
        return VerificationReport(
            file="test.yaml",
            results=r,
            summary={"errors": n_errors, "warnings": n_warns, "info": n_info},
            risk_summary=rs,
            verdict=verdict,
        )

    def test_text_ok_report(self) -> None:
        report = self._make_report()
        text = format_text(report, color=False)
        assert "OK" in text
        assert "Verdict" in text
        assert "Risk Summary" in text

    def test_text_error_report(self) -> None:
        r = CheckResult(
            code="S001",
            severity=Severity.ERROR,
            message="'symbols' is required.",
            suggestion="Add symbols.",
        )
        report = self._make_report([r])
        text = format_text(report, color=False)
        assert "S001" in text
        assert "ERROR" in text
        assert "engine will not start" in text

    def test_text_warn_report(self) -> None:
        r = CheckResult(
            code="M013",
            severity=Severity.WARN,
            message="No admin gateway.",
            suggestion="Add one.",
        )
        report = self._make_report([r])
        text = format_text(report, color=False)
        assert "M013" in text
        assert "WARN" in text

    def test_text_info_report(self) -> None:
        r = CheckResult(
            code="C009",
            severity=Severity.INFO,
            message="Always CONTINUOUS.",
            suggestion="No action needed.",
        )
        report = self._make_report([r])
        text = format_text(report, color=False)
        assert "C009" in text

    def test_text_min_severity_filters(self) -> None:
        r_info = CheckResult(
            code="C009", severity=Severity.INFO, message="info msg", suggestion=""
        )
        r_warn = CheckResult(
            code="M013", severity=Severity.WARN, message="warn msg", suggestion=""
        )
        report = self._make_report([r_info, r_warn])
        text = format_text(report, color=False, min_severity=Severity.WARN)
        assert "M013" in text
        assert "C009" not in text

    def test_json_output_valid(self) -> None:
        r = CheckResult(
            code="M013",
            severity=Severity.WARN,
            message="No admin.",
            suggestion="Add admin.",
        )
        report = self._make_report([r])
        data = json.loads(format_json(report))
        assert data["verdict"] == "WARN"
        assert data["summary"]["warnings"] == 1
        assert data["checks"][0]["code"] == "M013"
        assert "risk_summary" in data

    def test_text_color_output(self) -> None:
        report = self._make_report()
        text = format_text(report, color=True)
        assert "\033[" in text  # ANSI codes present

    def test_text_color_output_for_all_severities_and_gateway_truncation(self) -> None:
        rs = RiskSummary(
            symbols=["AAPL"],
            gateways={
                "GW01": "TRADER",
                "GW02": "TRADER",
                "GW03": "TRADER",
                "GW04": "TRADER",
                "GW05": "ADMIN",
            },
            sessions_enabled=False,
            schedule_summary="always CONTINUOUS",
            collars_enforced=False,
            collars_configured=False,
            collar_description="disabled",
            circuit_breakers_enforced=False,
            circuit_breakers_configured=False,
            cb_description="disabled",
            mm_obligations_enforced=False,
            admin_gateway="GW05",
        )
        report = VerificationReport(
            file="x.yaml",
            results=[
                CheckResult(
                    code="S001", severity=Severity.ERROR, message="e", suggestion=""
                ),
                CheckResult(
                    code="M013", severity=Severity.WARN, message="w", suggestion=""
                ),
                CheckResult(
                    code="C009", severity=Severity.INFO, message="i", suggestion=""
                ),
            ],
            summary={"errors": 1, "warnings": 1, "info": 1},
            risk_summary=rs,
            verdict="ERROR",
        )
        text = format_text(report, color=True)
        assert "\033[" in text
        assert "+1 more" in text

    def test_text_many_symbols_truncated(self) -> None:
        rs = RiskSummary(
            symbols=[f"SYM{i}" for i in range(10)],
            gateways={},
            sessions_enabled=False,
            schedule_summary="always CONTINUOUS",
            collars_enforced=False,
            collars_configured=False,
            collar_description="disabled",
            circuit_breakers_enforced=False,
            circuit_breakers_configured=False,
            cb_description="disabled",
            mm_obligations_enforced=False,
            admin_gateway=None,
        )
        report = VerificationReport(
            file="x.yaml",
            results=[],
            summary={"errors": 0, "warnings": 0, "info": 0},
            risk_summary=rs,
            verdict="OK",
        )
        text = format_text(report, color=False)
        assert "more" in text

    def test_text_index_in_risk_summary(self) -> None:
        rs = RiskSummary(
            symbols=["AAPL"],
            gateways={"GW01": "TRADER"},
            sessions_enabled=False,
            schedule_summary="always CONTINUOUS",
            collars_enforced=False,
            collars_configured=False,
            collar_description="disabled",
            circuit_breakers_enforced=False,
            circuit_breakers_configured=False,
            cb_description="disabled",
            mm_obligations_enforced=False,
            admin_gateway=None,
            indices=["EDU100"],
        )
        report = VerificationReport(
            file="x.yaml",
            results=[],
            summary={"errors": 0, "warnings": 0, "info": 0},
            risk_summary=rs,
            verdict="OK",
        )
        text = format_text(report, color=False)
        assert "EDU100" in text


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


class TestCLIHelpers:
    def test_verdict_ok(self) -> None:
        assert _compute_verdict([], strict=False) == "OK"

    def test_verdict_warn(self) -> None:
        r = CheckResult(code="M013", severity=Severity.WARN, message="x", suggestion="")
        assert _compute_verdict([r], strict=False) == "WARN"

    def test_verdict_warn_strict(self) -> None:
        r = CheckResult(code="M013", severity=Severity.WARN, message="x", suggestion="")
        assert _compute_verdict([r], strict=True) == "ERROR"

    def test_verdict_error(self) -> None:
        r = CheckResult(
            code="S001", severity=Severity.ERROR, message="x", suggestion=""
        )
        assert _compute_verdict([r], strict=False) == "ERROR"

    def test_exit_code_ok(self) -> None:
        assert _compute_exit_code("OK") == 0

    def test_exit_code_warn(self) -> None:
        assert _compute_exit_code("WARN") == 1

    def test_exit_code_error(self) -> None:
        assert _compute_exit_code("ERROR") == 2

    def test_run_layer1_stops_on_error(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.yaml"
        results, raw = run(p)
        assert any(r.code == "Y001" for r in results)
        assert raw is None


# ---------------------------------------------------------------------------
# Integration tests — fixture files
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_clean_config_verdict_ok(self) -> None:
        results, raw = run(FIXTURES / "clean.yaml")
        # Clean config should have no errors; may have infos
        errors = [r for r in results if r.severity is Severity.ERROR]
        assert errors == []

    def test_no_admin_gw_m013(self) -> None:
        results, _ = run(FIXTURES / "no_admin_gw.yaml")
        assert "M013" in _codes(results)

    def test_undefined_level_s013(self) -> None:
        results, _ = run(FIXTURES / "undefined_level.yaml")
        assert "S013" in _codes(results)

    def test_bid_gte_ask_s015(self) -> None:
        results, _ = run(FIXTURES / "bid_gte_ask.yaml")
        assert "S015" in _codes(results)

    def test_sessions_no_schedule_m004(self) -> None:
        results, _ = run(FIXTURES / "sessions_no_schedule.yaml")
        assert "M004" in _codes(results)

    def test_collars_not_enforced_m007(self) -> None:
        results, _ = run(FIXTURES / "collars_not_enforced.yaml")
        assert "M007" in _codes(results)

    def test_mm_gw_no_seeds_m001(self) -> None:
        results, _ = run(FIXTURES / "mm_gw_no_seeds.yaml")
        assert "M001" in _codes(results)

    def test_index_missing_symbol_m009(self) -> None:
        results, _ = run(FIXTURES / "index_missing_symbol.yaml")
        assert "M009" in _codes(results)

    def test_index_no_shares_m010(self) -> None:
        results, _ = run(FIXTURES / "index_no_shares.yaml")
        assert "M010" in _codes(results)


# ---------------------------------------------------------------------------
# CLI main() unit tests
# ---------------------------------------------------------------------------


class TestCLIMain:
    def test_main_ok_exits_0(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([str(FIXTURES / "clean.yaml"), "--no-color", "--level", "error"])
        assert exc.value.code == 0

    def test_main_error_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([str(FIXTURES / "undefined_level.yaml"), "--no-color"])
        assert exc.value.code == 2

    def test_main_warn_exits_1(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    str(FIXTURES / "collars_not_enforced.yaml"),
                    "--no-color",
                    "--level",
                    "warn",
                ]
            )
        assert exc.value.code == 1

    def test_main_strict_promotes_warn_to_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [str(FIXTURES / "collars_not_enforced.yaml"), "--no-color", "--strict"]
            )
        assert exc.value.code == 2

    def test_main_json_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            main([str(FIXTURES / "clean.yaml"), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "verdict" in data

    def test_main_text_format_no_color(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main([str(FIXTURES / "clean.yaml"), "--no-color"])
        captured = capsys.readouterr()
        assert "Verdict" in captured.out

    def test_main_level_error_suppresses_warn(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main(
                [
                    str(FIXTURES / "collars_not_enforced.yaml"),
                    "--no-color",
                    "--level",
                    "error",
                ]
            )
        captured = capsys.readouterr()
        assert "M007" not in captured.out

    def test_main_missing_file_exits_2(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["/nonexistent/path/config.yaml", "--no-color"])
        assert exc.value.code == 2

    def test_parse_args_defaults(self) -> None:
        args = _parse_args(["myconfig.yaml"])
        assert args.config_file == "myconfig.yaml"
        assert args.output_format == "text"
        assert args.level == "info"
        assert args.no_color is False
        assert args.strict is False

    def test_parse_args_all_flags(self) -> None:
        args = _parse_args(
            [
                "cfg.yaml",
                "--format",
                "json",
                "--level",
                "error",
                "--no-color",
                "--strict",
            ]
        )
        assert args.output_format == "json"
        assert args.level == "error"
        assert args.no_color is True
        assert args.strict is True

    def test_load_raw_nonexistent(self, tmp_path: Path) -> None:
        result = layer1_yaml.load(tmp_path / "missing.yaml")[1]
        assert result is None

    def test_load_raw_invalid_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("key: [unclosed\n")
        result = layer1_yaml.load(p)[1]
        assert result is None

    def test_load_raw_non_mapping(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- item\n")
        result = layer1_yaml.load(p)[1]
        assert result is None

    def test_load_raw_valid(self, tmp_path: Path) -> None:
        p = tmp_path / "valid.yaml"
        p.write_text("symbols:\n  AAPL: {}\n")
        result = layer1_yaml.load(p)[1]
        assert result is not None
        assert "symbols" in result


# ---------------------------------------------------------------------------
# Exit code / subprocess tests
# ---------------------------------------------------------------------------


class TestExitCodes:
    def _run_cverifier(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "edumatcher.cverifier.cli", *args],
            capture_output=True,
            text=True,
        )

    def test_exit_0_clean_config(self) -> None:
        proc = self._run_cverifier(str(FIXTURES / "clean.yaml"), "--level", "warn")
        assert proc.returncode == 0

    def test_exit_1_warn_only(self) -> None:
        # collars_not_enforced has M007 (WARN) but no errors
        proc = self._run_cverifier(
            str(FIXTURES / "collars_not_enforced.yaml"), "--level", "warn"
        )
        assert proc.returncode == 1

    def test_exit_2_errors(self) -> None:
        proc = self._run_cverifier(str(FIXTURES / "undefined_level.yaml"))
        assert proc.returncode == 2

    def test_json_output_parses(self) -> None:
        proc = self._run_cverifier(str(FIXTURES / "clean.yaml"), "--format", "json")
        data = json.loads(proc.stdout)
        assert "verdict" in data
        assert "checks" in data

    def test_strict_mode_promotes_warn(self) -> None:
        proc = self._run_cverifier(str(FIXTURES / "no_admin_gw.yaml"), "--strict")
        # no_admin_gw has M001 (ERROR from MM seeds) and M013 (WARN from no admin)
        assert proc.returncode == 2

    def test_no_color_flag(self) -> None:
        proc = self._run_cverifier(str(FIXTURES / "clean.yaml"), "--no-color")
        assert "\033[" not in proc.stdout

    def test_missing_file(self) -> None:
        proc = self._run_cverifier("/nonexistent/path/config.yaml")
        assert proc.returncode == 2


# ---------------------------------------------------------------------------
# Code-review fixes
# ---------------------------------------------------------------------------


class TestMMQuoteValidity:
    def test_s016_non_positive_quantity(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 0\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S016" in _codes(results)

    def test_s016_non_numeric_price(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: abc\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S016" in _codes(results)

    def test_s016_invalid_tif(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "        tif: FOO\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S016" in _codes(results)

    def test_s016_clean_quote_no_finding(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 149.9\n"
            "        ask_price: 150.1\n        bid_qty: 100\n        ask_qty: 100\n"
            "        tif: DAY\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer2_schema.check(raw, Path("x.yaml"))
        assert "S016" not in _codes(results)


class TestIndexConstituentRobustness:
    def test_integer_constituent_does_not_crash(self) -> None:
        # A symbol keyed and referenced as an integer must not raise.
        raw = _raw(
            "symbols:\n  123:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n    - id: GW01\n"
            "indices:\n  - id: IDX1\n    constituents:\n      - 123\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        # 123 is a known symbol, so M009 must NOT be raised, and no exception.
        assert "M009" not in _codes(results)


class TestM001SinglePerSymbol:
    def test_m001_one_finding_per_symbol(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "gateways:\n  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "    - id: MM02\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        m001 = [r for r in results if r.code == "M001"]
        assert len(m001) == 1
        assert "MM01" in m001[0].message and "MM02" in m001[0].message


class TestM003Gating:
    def test_m003_not_raised_without_mm_defaults(self) -> None:
        raw = _raw(
            "symbols:\n  AAPL:\n    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 140.0\n"
            "        ask_price: 160.0\n        bid_qty: 100\n        ask_qty: 100\n"
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results = layer3_semantic.check(raw, Path("x.yaml"))
        assert "M003" not in _codes(results)


class TestLayerSkipSemantics:
    def test_schema_error_skips_later_layers(self, tmp_path: Path) -> None:
        # 'symbols' missing -> S001 error -> Semantic/Completeness skipped.
        p = _write_yaml(
            tmp_path,
            "gateways:\n  alf:\n    - id: MM01\n      role: MARKET_MAKER\n",
        )
        from edumatcher.cverifier.cli import run_layers

        layers, _ = run_layers(p)
        by_name = {lo.name: lo for lo in layers}
        assert by_name["Schema"].status == "ran"
        assert by_name["Semantic"].status == "skipped"
        assert by_name["Completeness"].status == "skipped"
        # No M-codes should leak through when schema failed.
        results, _ = run(p)
        assert not any(r.code.startswith("M") for r in results)

    def test_yaml_error_attributed_to_layer1(self, tmp_path: Path) -> None:
        p = _write_yaml(tmp_path, "key: [unclosed\n")
        from edumatcher.cverifier.cli import run_layers

        layers, _ = run_layers(p)
        by_name = {lo.name: lo for lo in layers}
        assert any(r.code == "Y003" for r in by_name["YAML syntax"].results)
        assert by_name["Schema"].status == "skipped"

    def test_text_summary_shows_yaml_error_not_schema(self, tmp_path: Path) -> None:
        from edumatcher.cverifier.cli import run_layers

        p = _write_yaml(tmp_path, "key: [unclosed\n")
        layers, _ = run_layers(p)
        report = VerificationReport(
            file=str(p),
            results=[r for lo in layers for r in lo.results],
            summary={"errors": 1, "warnings": 0, "info": 0},
            risk_summary=RiskSummary(),
            verdict="ERROR",
            layers=layers,
        )
        text = format_text(report, color=False)
        assert "YAML syntax: 1 error" in text
        assert "Schema: skipped" in text


class TestStrictVerdictMessage:
    def test_strict_promoted_message(self) -> None:
        r = CheckResult(
            code="M013", severity=Severity.WARN, message="No admin.", suggestion=""
        )
        report = VerificationReport(
            file="x.yaml",
            results=[r],
            summary={"errors": 0, "warnings": 1, "info": 0},
            risk_summary=RiskSummary(),
            verdict="ERROR",
            strict=True,
        )
        text = format_text(report, color=False)
        assert "treated as errors" in text
        assert "engine will not start" not in text


class TestJsonCBKey:
    def test_circuit_breakers_using_defaults_key(self) -> None:
        rs = RiskSummary(circuit_breakers_configured=False)
        report = VerificationReport(
            file="x.yaml",
            results=[],
            summary={"errors": 0, "warnings": 0, "info": 0},
            risk_summary=rs,
            verdict="OK",
        )
        data = json.loads(format_json(report))
        assert data["risk_summary"]["circuit_breakers_using_defaults"] is True
        assert "circuit_breakers_configured" not in data["risk_summary"]


class TestHelpers:
    def test_gateway_ids_by_role_handles_non_mapping(self) -> None:
        raw = _raw("symbols: {}\ngateways: bad\n")
        from edumatcher.cverifier.helpers import gateway_ids_by_role

        assert gateway_ids_by_role(raw, "ADMIN") == []

    def test_gateway_ids_by_role_handles_non_list_alf(self) -> None:
        raw = _raw("symbols: {}\ngateways:\n  alf: bad\n")
        from edumatcher.cverifier.helpers import gateway_ids_by_role

        assert gateway_ids_by_role(raw, "ADMIN") == []

    def test_all_gateway_ids_handles_non_mapping(self) -> None:
        raw = _raw("symbols: {}\ngateways: bad\n")
        from edumatcher.cverifier.helpers import all_gateway_ids

        assert all_gateway_ids(raw) == set()

    def test_all_gateway_ids_handles_non_list_alf(self) -> None:
        raw = _raw("symbols: {}\ngateways:\n  alf: bad\n")
        from edumatcher.cverifier.helpers import all_gateway_ids

        assert all_gateway_ids(raw) == set()

    def test_symbol_cfg_by_upper_name_handles_non_mapping(self) -> None:
        raw = _raw("symbols: bad\n")
        from edumatcher.cverifier.helpers import symbol_cfg_by_upper_name

        assert symbol_cfg_by_upper_name(raw) == {}


class TestLayer2InternalGuards:
    def test_check_symbols_returns_when_symbols_not_mapping(self) -> None:
        raw: dict[str, Any] = {"symbols": []}
        results: list[CheckResult] = []
        layer2_schema._check_symbols(raw, results)
        assert results == []

    def test_check_gateways_returns_when_gateways_not_mapping(self) -> None:
        raw: dict[str, Any] = {"gateways": []}
        results: list[CheckResult] = []
        layer2_schema._check_gateways(raw, results)
        assert results == []

    def test_check_gateways_returns_when_alf_not_list(self) -> None:
        raw = {"gateways": {"alf": "bad"}}
        results: list[CheckResult] = []
        layer2_schema._check_gateways(raw, results)
        assert results == []

    def test_mm_defaults_symbol_field_missing_is_ignored(self) -> None:
        raw = {
            "mm_obligation_defaults": {
                "symbols": {
                    "AAPL": {
                        "mm_max_spread_ticks": 10,
                    }
                }
            }
        }
        results: list[CheckResult] = []
        layer2_schema._check_mm_obligation_defaults_schema(raw, results)
        assert "S077" not in _codes(results)


class TestLayer3InternalGuards:
    def test_mm_seed_gateway_blank_id_is_skipped_in_role_map(self) -> None:
        raw = _raw(
            "symbols:\n"
            "  AAPL:\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: 100\n        ask_price: 100.1\n"
            "gateways:\n"
            "  alf:\n"
            "    - id: ''\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
        )
        results: list[CheckResult] = []
        layer3_semantic._check_mm_seeds(raw, results)
        assert "M020" not in _codes(results)

    def test_mm_seed_spread_parse_error_is_ignored(self) -> None:
        raw = _raw(
            "symbols:\n"
            "  AAPL:\n"
            "    tick_decimals: 2\n"
            "    market_maker_quotes:\n"
            "      - gateway_id: MM01\n        bid_price: bad\n        ask_price: also_bad\n"
            "gateways:\n"
            "  alf:\n"
            "    - id: MM01\n      role: MARKET_MAKER\n"
            "mm_obligation_defaults:\n"
            "  mm_max_spread_ticks: 5\n"
        )
        results: list[CheckResult] = []
        layer3_semantic._check_mm_seeds(raw, results)
        assert "M003" not in _codes(results)

    def test_admin_gateway_returns_when_alf_not_list(self) -> None:
        raw = {"gateways": {"alf": "bad"}}
        results: list[CheckResult] = []
        layer3_semantic._check_admin_gateway(raw, results)
        assert "M013" in _codes(results)


class TestLayer4InternalGuards:
    def test_reference_prices_handles_non_mapping_symbol_cfg(self) -> None:
        raw = _raw("symbols:\n  AAPL: bad\n")
        results: list[CheckResult] = []
        layer4_complete._check_reference_prices(raw, results)
        assert "C001" in _codes(results)

    def test_cb_completeness_returns_when_disabled(self) -> None:
        raw = _raw("enforce_circuit_breakers: false\n")
        results: list[CheckResult] = []
        layer4_complete._check_cb_completeness(raw, results)
        assert results == []

    def test_snapshot_interval_invalid_type_returns(self) -> None:
        raw = _raw("snapshot_interval_sec: bad\n")
        results: list[CheckResult] = []
        layer4_complete._check_snapshot_interval(raw, results)
        assert results == []

    def test_index_prices_returns_when_symbols_not_mapping(self) -> None:
        raw = _raw("indices:\n  - id: IDX1\n    constituents: [AAPL]\nsymbols: bad\n")
        results: list[CheckResult] = []
        layer4_complete._check_index_constituents_prices(raw, results)
        assert results == []

    def test_index_prices_ignores_non_list_constituents(self) -> None:
        raw = _raw(
            "indices:\n"
            "  - id: IDX1\n"
            "    constituents: bad\n"
            "symbols:\n"
            "  AAPL:\n"
            "    last_buy_price: 100\n"
        )
        results: list[CheckResult] = []
        layer4_complete._check_index_constituents_prices(raw, results)
        assert results == []

    def test_unused_levels_detects_symbol_level_usage(self) -> None:
        raw = _raw(
            "risk_controls:\n"
            "  levels:\n"
            "    DEFAULT: {}\n"
            "    ALT: {}\n"
            "symbols:\n"
            "  AAPL:\n"
            "    level: ALT\n"
        )
        results: list[CheckResult] = []
        layer4_complete._check_unused_risk_levels(raw, results)
        assert not any(r.path == "risk_controls.levels.ALT" for r in results)
