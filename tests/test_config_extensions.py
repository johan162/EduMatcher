"""Tests for Phase 7 config extensions: collar, circuit_breaker, mm_obligations.

All YAML is written as complete, valid strings to avoid indentation errors.
"""

from __future__ import annotations

import textwrap

import pytest

from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.models.mm_obligation import MarketMakerObligation


def _write_yaml(tmp_path, content: str):
    path = tmp_path / "engine_config.yaml"
    path.write_text(textwrap.dedent(content).lstrip())
    return path


# ---------------------------------------------------------------------------
# Collar parsing
# ---------------------------------------------------------------------------


class TestCollarParsing:
    def test_no_collar_section_gives_none(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        assert cfg.symbols["AAPL"].collar is None

    def test_collar_section_parsed(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    collar:
                      static_band_pct: 0.15
                      dynamic_band_pct: 0.03
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        collar = cfg.symbols["AAPL"].collar
        assert collar is not None
        assert isinstance(collar, CollarConfig)
        assert collar.static_band_pct == pytest.approx(0.15)
        assert collar.dynamic_band_pct == pytest.approx(0.03)

    def test_collar_defaults_when_pcts_omitted(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    collar: {}
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        collar = cfg.symbols["AAPL"].collar
        assert collar is not None
        assert collar.static_band_pct == pytest.approx(0.20)
        assert collar.dynamic_band_pct == pytest.approx(0.02)

    def test_invalid_collar_static_band_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="static_band_pct"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        collar:
                          static_band_pct: 1.5
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_invalid_collar_not_dict_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="collar must be a mapping"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        collar: not_a_mapping
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )


# ---------------------------------------------------------------------------
# Circuit breaker parsing
# ---------------------------------------------------------------------------


class TestCircuitBreakerParsing:
    def test_no_cb_section_gives_none(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        assert cfg.symbols["AAPL"].circuit_breaker is None

    def test_cb_section_parsed(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    circuit_breaker:
                      reference_window_ns: 60000000000
                      levels:
                        L1:
                          price_shift_pct: 0.07
                          halt_duration_ns: 300000000000
                          resumption_mode: AUCTION
                        L2:
                          price_shift_pct: 0.13
                          halt_duration_ns: 900000000000
                          resumption_mode: CONTINUOUS
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        cb = cfg.symbols["AAPL"].circuit_breaker
        assert cb is not None
        assert isinstance(cb, CircuitBreakerConfig)
        assert cb.reference_window_ns == 60_000_000_000
        assert len(cb.levels) == 2
        assert cb.levels[0].name == "L1"
        assert cb.levels[0].price_shift_pct == pytest.approx(0.07)
        assert cb.levels[0].halt_duration_ns == 300_000_000_000
        assert cb.levels[1].name == "L2"
        assert cb.levels[1].resumption_mode == "CONTINUOUS"

    def test_cb_defaults_when_fields_omitted(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                sessions:
                  enabled: false
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    circuit_breaker: {}
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        cb = cfg.symbols["AAPL"].circuit_breaker
        assert cb is not None
        assert len(cb.levels) == 3
        assert cb.levels[0].name == "L1"
        assert cb.levels[0].price_shift_pct == pytest.approx(0.07)
        assert cb.levels[1].name == "L2"
        assert cb.levels[1].price_shift_pct == pytest.approx(0.13)
        assert cb.levels[2].name == "L3"
        assert cb.levels[2].halt_duration_ns is None

    def test_invalid_resumption_mode_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="resumption_mode"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        circuit_breaker:
                          levels:
                            L1:
                              price_shift_pct: 0.07
                              halt_duration_ns: 300000000000
                              resumption_mode: INVALID
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_invalid_price_shift_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="price_shift_pct"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        circuit_breaker:
                          levels:
                            L1:
                              price_shift_pct: 2.0
                              halt_duration_ns: 300000000000
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_cb_level_missing_price_shift_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="price_shift_pct is required"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        circuit_breaker:
                          levels:
                            L1:
                              halt_duration_ns: 300000000000
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_cb_not_dict_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="circuit_breaker must be a mapping"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    sessions:
                      enabled: false
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        circuit_breaker: bad
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )


# ---------------------------------------------------------------------------
# mm_obligations parsing
# ---------------------------------------------------------------------------


_MM_BASE = """
sessions:
  enabled: false
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 150.00
    market_maker_quotes:
      - gateway_id: MM01
        bid_price: 149.00
        ask_price: 151.00
        bid_qty: 100
        ask_qty: 100
gateways:
  alf:
    - id: MM01
      role: MARKET_MAKER
"""


class TestMMObligationsParsing:
    def test_no_mm_obligations_section_gives_empty_dict(self, tmp_path) -> None:
        cfg = load_engine_config(_write_yaml(tmp_path, _MM_BASE))
        assert cfg.fix_gateways["MM01"].mm_obligations == {}

    def test_mm_obligations_parsed(self, tmp_path) -> None:
        yaml_text = (
            _MM_BASE.rstrip()
            + "\n      mm_obligations:\n        AAPL:\n          max_spread_ticks: 5\n          min_qty: 200\n"
        )
        cfg = load_engine_config(_write_yaml(tmp_path, yaml_text))
        obligations = cfg.fix_gateways["MM01"].mm_obligations
        assert "AAPL" in obligations
        obl = obligations["AAPL"]
        assert isinstance(obl, MarketMakerObligation)
        assert obl.max_spread_ticks == 5
        assert obl.min_qty == 200

    def test_mm_obligations_defaults_from_gateway_fields(self, tmp_path) -> None:
        yaml_text = (
            _MM_BASE.rstrip()
            + "\n      mm_max_spread_ticks: 7\n      mm_min_qty: 150\n"
            + "      mm_obligations:\n        AAPL: {}\n"
        )
        cfg = load_engine_config(_write_yaml(tmp_path, yaml_text))
        obl = cfg.fix_gateways["MM01"].mm_obligations["AAPL"]
        assert obl.max_spread_ticks == 7
        assert obl.min_qty == 150

    def test_mm_obligations_not_dict_raises(self, tmp_path) -> None:
        yaml_text = _MM_BASE.rstrip() + "\n      mm_obligations: bad\n"
        with pytest.raises(ValueError, match="mm_obligations must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml_text))

    def test_mm_obligation_symbol_value_not_dict_raises(self, tmp_path) -> None:
        yaml_text = (
            _MM_BASE.rstrip() + "\n      mm_obligations:\n        AAPL: not_a_dict\n"
        )
        with pytest.raises(ValueError, match="must be a mapping"):
            load_engine_config(_write_yaml(tmp_path, yaml_text))


# ---------------------------------------------------------------------------
# global risk_controls levels
# ---------------------------------------------------------------------------


class TestGlobalRiskControlLevels:
    def test_default_level_applies_when_symbol_level_missing(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                risk_controls:
                  default_level: L2
                  levels:
                    L2:
                      collar:
                        static_band_pct: 0.18
                        dynamic_band_pct: 0.04
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        assert cfg.default_risk_level == "L2"
        assert cfg.symbols["AAPL"].level == "L2"
        collar = cfg.symbols["AAPL"].collar
        cb = cfg.symbols["AAPL"].circuit_breaker
        assert collar is not None
        assert cb is None
        assert collar.static_band_pct == pytest.approx(0.18)
        assert collar.dynamic_band_pct == pytest.approx(0.04)

    def test_symbol_level_overrides_global_default_level(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                risk_controls:
                  default_level: L2
                  levels:
                    L1:
                      collar:
                        static_band_pct: 0.30
                    L2:
                      collar:
                        static_band_pct: 0.20
                symbols:
                  AAPL:
                    tick_decimals: 2
                    level: L1
                    last_buy_price: 150.00
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        assert cfg.symbols["AAPL"].level == "L1"
        collar = cfg.symbols["AAPL"].collar
        assert collar is not None
        assert collar.static_band_pct == pytest.approx(0.30)

    def test_symbol_collar_override_beats_level_value(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                risk_controls:
                  default_level: L2
                  levels:
                    L2:
                      collar:
                        static_band_pct: 0.20
                        dynamic_band_pct: 0.02
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    collar:
                      dynamic_band_pct: 0.05
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        collar = cfg.symbols["AAPL"].collar
        assert collar is not None
        assert collar.static_band_pct == pytest.approx(0.20)
        assert collar.dynamic_band_pct == pytest.approx(0.05)

    def test_symbol_cb_override_beats_global_cb_defaults(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                circuit_breaker_defaults:
                  reference_window_ns: 300000000000
                  levels:
                    L1:
                      price_shift_pct: 0.07
                      halt_duration_ns: 300000000000
                      resumption_mode: AUCTION
                    L2:
                      price_shift_pct: 0.13
                      halt_duration_ns: 900000000000
                      resumption_mode: AUCTION
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    circuit_breaker:
                      levels:
                        L2:
                          resumption_mode: CONTINUOUS
                          halt_duration_ns: 600000000000
                gateways:
                  alf:
                    - id: TRADER01
                      role: TRADER
                """,
            )
        )
        cb = cfg.symbols["AAPL"].circuit_breaker
        assert cb is not None
        assert cb.reference_window_ns == 300_000_000_000
        assert len(cb.levels) == 2
        assert cb.levels[1].name == "L2"
        assert cb.levels[1].resumption_mode == "CONTINUOUS"
        assert cb.levels[1].halt_duration_ns == 600_000_000_000

    def test_unknown_symbol_level_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="is not defined in risk_controls.levels"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    risk_controls:
                      levels:
                        L2: {}
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                        level: L9
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_unknown_default_level_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="default_level"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    risk_controls:
                      default_level: L2
                      levels:
                        L1: {}
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_invalid_level_sections_raise(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="risk_controls.levels.L2.collar"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    risk_controls:
                      levels:
                        L2:
                          collar: bad
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )

    def test_circuit_breaker_under_risk_level_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="no longer supported"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    risk_controls:
                      levels:
                        L2:
                          circuit_breaker:
                            levels:
                              L1:
                                price_shift_pct: 0.07
                                halt_duration_ns: 300000000000
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )


class TestGlobalMMObligationPolicies:
    def test_global_defaults_applied_to_gateway_when_fields_missing(
        self, tmp_path
    ) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                mm_obligation_defaults:
                  enforce_mm_obligation: true
                  mm_max_spread_ticks: 7
                  mm_min_qty: 150
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    market_maker_quotes:
                      - gateway_id: MM01
                        bid_price: 149.00
                        ask_price: 151.00
                        bid_qty: 200
                        ask_qty: 200
                gateways:
                  alf:
                    - id: MM01
                      role: MARKET_MAKER
                """,
            )
        )
        gw = cfg.fix_gateways["MM01"]
        assert gw.enforce_mm_obligation is True
        assert gw.mm_max_spread_ticks == 7
        assert gw.mm_min_qty == 150

    def test_global_symbol_override_parsed(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                mm_obligation_defaults:
                  enforce_mm_obligation: true
                  mm_max_spread_ticks: 7
                  mm_min_qty: 150
                  symbols:
                    AAPL:
                      enforce_mm_obligation: false
                      mm_max_spread_ticks: 9
                      mm_min_qty: 220
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    market_maker_quotes:
                      - gateway_id: MM01
                        bid_price: 149.00
                        ask_price: 151.00
                        bid_qty: 220
                        ask_qty: 220
                gateways:
                  alf:
                    - id: MM01
                      role: MARKET_MAKER
                """,
            )
        )
        policy = cfg.global_symbol_mm_obligation_policies["AAPL"]
        assert policy.enforce_mm_obligation is False
        assert policy.mm_max_spread_ticks == 9
        assert policy.mm_min_qty == 220

    def test_gateway_symbol_override_includes_enforce(self, tmp_path) -> None:
        cfg = load_engine_config(
            _write_yaml(
                tmp_path,
                """
                symbols:
                  AAPL:
                    tick_decimals: 2
                    last_buy_price: 150.00
                    market_maker_quotes:
                      - gateway_id: MM01
                        bid_price: 149.00
                        ask_price: 151.00
                        bid_qty: 220
                        ask_qty: 220
                gateways:
                  alf:
                    - id: MM01
                      role: MARKET_MAKER
                      enforce_mm_obligation: false
                      mm_obligations:
                        AAPL:
                          enforce_mm_obligation: true
                          max_spread_ticks: 5
                          min_qty: 200
                """,
            )
        )
        policy = cfg.fix_gateways["MM01"].mm_obligation_policies["AAPL"]
        assert policy.enforce_mm_obligation is True
        assert policy.mm_max_spread_ticks == 5
        assert policy.mm_min_qty == 200

    def test_global_symbol_override_unknown_symbol_raises(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="references unknown symbol"):
            load_engine_config(
                _write_yaml(
                    tmp_path,
                    """
                    mm_obligation_defaults:
                      symbols:
                        UNKNOWN:
                          enforce_mm_obligation: true
                    symbols:
                      AAPL:
                        tick_decimals: 2
                        last_buy_price: 150.00
                    gateways:
                      alf:
                        - id: TRADER01
                          role: TRADER
                    """,
                )
            )
