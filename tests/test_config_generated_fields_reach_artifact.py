"""Every field pm-config-gen can emit must survive into the compiled artifact.

Three bugs in this codebase had the same shape: a documented field that
``pm-config-gen`` wrote and ``pm-cverifier`` validated, but that no
``EngineConfig`` field captured. The compiler therefore dropped it, and the one
process that needed it re-parsed the YAML privately and became its only reader.

  * ``country`` — read by nothing but pm-scheduler
  * ``schedule`` times — the engine stored ``"570"`` for an unquoted ``9:30``
    while pm-scheduler recovered ``"09:30"``
  * index reference data — derivable from the artifact all along, but only
    reachable through a path-taking loader

This test is the invariant those three violated: a key the generator can write
must have somewhere to land, and its value must be reachable from the compiled
artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_artifact import CompiledConfig
from edumatcher.config_deploy import compile_config
from edumatcher.config_gen.builder import ConfigBuilder, ConfigSpec
from edumatcher.config_gen.cb_spec import parse_cb_spec
from edumatcher.config_gen.gateway_spec import parse_gateway_spec
from edumatcher.config_gen.renderer import render_yaml
from edumatcher.config_gen.symbol_spec import SymbolOverride
from edumatcher.config_deploy import CompileError
from edumatcher.index.config_loader import index_runtime_configs
from edumatcher.monitor.config import MonitorConfig, ThresholdBand
from edumatcher.models.order import SmpAction

# Where each generated top-level key lands in the artifact. A key with no entry
# fails the test below: either wire it into the compiled config, or record here
# why it is deliberately absent.
#
# The check is `reach(compiled) is not None`, so an entry also asserts the value
# is genuinely reachable rather than merely having a home in the schema.
KEY_LANDINGS: dict[str, object] = {
    "sessions_enabled": lambda c: c.engine.sessions_enabled,
    "locale": lambda c: c.engine.locale.country,
    "enforce_collars": lambda c: c.engine.enforce_collars,
    "enforce_circuit_breakers": lambda c: c.engine.enforce_circuit_breakers,
    "require_mm_seed_quotes": lambda c: c.engine.require_mm_seed_quotes,
    "engine_tuning": lambda c: c.engine.snapshot_interval_sec,
    "mm_obligation_defaults": lambda c: c.engine.global_mm_obligation_policy,
    "risk_controls": lambda c: c.engine.risk_control_levels,
    "circuit_breaker_defaults": lambda c: next(
        (s.circuit_breaker for s in c.engine.symbols.values()), None
    ),
    "participants": lambda c: c.engine.fix_gateways or None,
    # Resolved into each FixGatewayConfig at compile time; no field of its own.
    "participant_defaults": lambda c: c.engine.fix_gateways or None,
    "alf_gateway": lambda c: c.alf_gateway,
    "post_trade_gateway": lambda c: c.post_trade_gateway,
    "market_data_gateway": lambda c: c.market_data_gateway,
    "dc_gateway": lambda c: c.dc_gateway,
    "balf_gateway": lambda c: c.balf_gateway,
    "log_server": lambda c: c.log_server,
    # Not emitted by pm-config-gen today (the examples run on its defaults),
    # but mapped so that the day the generator learns it, it lands somewhere.
    "monitor": lambda c: c.monitor,
    "api_gateways": lambda c: c.api_gateways or None,
    "symbols": lambda c: c.engine.symbols or None,
    "market_maker_combos": lambda c: c.engine.market_maker_combos or None,
    "schedule": lambda c: c.engine.schedule,
    "indices": lambda c: c.engine.indices or None,
}


def _maximal_spec() -> ConfigSpec:
    """A spec exercising as many generated top-level keys as one config can."""
    return ConfigSpec(
        symbols=["AAPL", "MSFT"],
        gateways=[
            parse_gateway_spec("TRADER01:TRADER"),
            parse_gateway_spec("OPS01:ADMIN"),
        ],
        sessions_enabled=True,
        gateway_default_smp=SmpAction.CANCEL_AGGRESSOR,
        country="Germany",
        static_band_pct=0.20,
        dynamic_band_pct=0.02,
        cb_levels=[parse_cb_spec("L1:0.07:5"), parse_cb_spec("L2:0.13:15")],
        symbol_overrides={
            "MSFT": SymbolOverride(cb_halt_mins={"L1": 10}),
        },
        # Deliberately none of the ReopeningConfig dataclass defaults. If the
        # compiler drops the block the dataclass default fills in silently,
        # and a spec that matched those defaults would notice nothing.
        ace_initial_band_pct=0.13,
        ace_random_end_max_ns=7_000_000_000,
        ace_expansions=[(0.11, 60_000_000_000), (0.23, 180_000_000_000)],
    )


@pytest.fixture
def compiled(tmp_path: Path) -> tuple[CompiledConfig, dict[str, object]]:
    """Generate a config the way pm-config-gen does, then compile it."""
    payload = ConfigBuilder(_maximal_spec()).build()
    source = tmp_path / "generated.yaml"
    source.write_text(
        render_yaml(
            payload,
            command="pm-config-gen (test)",
            generated_version="test",
            generated_date="2026-07-30",
        ),
        encoding="utf-8",
    )
    return compile_config(source), payload


class TestGeneratedFieldsReachTheArtifact:
    def test_every_generated_key_has_a_declared_landing(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        _config, payload = compiled
        unmapped = set(payload) - set(KEY_LANDINGS)

        assert not unmapped, (
            f"pm-config-gen emits {sorted(unmapped)}, which nothing in the "
            f"compiled artifact claims. Add the field to the artifact and map "
            f"it here, or the compiler will silently drop it and whichever "
            f"process needs it will end up re-parsing the YAML."
        )

    def test_every_generated_key_is_reachable_from_the_artifact(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        config, payload = compiled

        missing = [
            key
            for key in payload
            if key in KEY_LANDINGS and KEY_LANDINGS[key](config) is None  # type: ignore[operator]
        ]

        assert not missing, (
            f"{sorted(missing)} were generated into the source but are absent "
            f"from the compiled artifact."
        )

    def test_the_generated_config_compiles_at_all(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        # pm-config-gen's own output must pass pm-cverifier; otherwise the two
        # tools disagree about what a valid configuration is.
        config, _payload = compiled
        assert sorted(config.engine.symbols) == ["AAPL", "MSFT"]

    def test_country_survives_specifically(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        # The field that prompted this test.
        config, payload = compiled
        locale = payload["locale"]
        assert isinstance(locale, dict)
        assert locale["country"] == "Germany"
        assert config.engine.locale.country == "Germany"

    def test_the_ace_reopening_block_survives_specifically(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        # `circuit_breaker_defaults` above only asserts the block is reachable,
        # which would still pass if `reopening` were silently dropped. ACE
        # governs whether a halted symbol may reopen at all, so a compiler that
        # lost it would reopen every halt uncollared without saying so.
        config, payload = compiled
        cb_defaults = payload["circuit_breaker_defaults"]
        assert isinstance(cb_defaults, dict)
        generated = cb_defaults["reopening"]
        assert isinstance(generated, dict)

        for symbol in config.engine.symbols.values():
            assert symbol.circuit_breaker is not None
            landed = symbol.circuit_breaker.reopening
            assert landed.enabled == generated["enabled"]
            assert landed.initial_band_pct == generated["initial_band_pct"]
            assert landed.random_end_max_ns == generated["random_end_max_ns"]
            assert [
                {"widen_pct": e.widen_pct, "min_duration_ns": e.min_duration_ns}
                for e in landed.expansions
            ] == generated["expansions"]

    def test_symbol_cb_halt_override_inherits_its_default_price_shift(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        config, payload = compiled
        generated_symbols = payload["symbols"]
        assert isinstance(generated_symbols, dict)
        generated_level = generated_symbols["MSFT"]["circuit_breaker"]["levels"]["L1"]
        assert generated_level == {"halt_duration_ns": 600_000_000_000}

        compiled_level = config.engine.symbols["MSFT"].circuit_breaker
        assert compiled_level is not None
        assert compiled_level.levels[0].price_shift_pct == pytest.approx(0.07)
        assert compiled_level.levels[0].halt_duration_ns == 600_000_000_000


class TestIndexReferenceDataIsDerivable:
    def test_an_index_compiles_with_its_constituent_reference_data(
        self, tmp_path: Path
    ) -> None:
        # `outstanding_shares` and `reference_prices` are not fields of their
        # own — they are gathered from the constituent symbols. This pins that
        # the artifact carries enough for pm-index to do that gathering.
        source = tmp_path / "authored.yaml"
        source.write_text("""
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 149.0
    last_sell_price: 151.0
    outstanding_shares: 15400000000
participants: [{id: TRADER01, role: TRADER}]
indices:
  - id: EDU1
    description: One-name index
    constituents: [AAPL]
""")

        runtime = index_runtime_configs(compile_config(source).engine)

        assert runtime[0].outstanding_shares == {"AAPL": 15_400_000_000}
        assert runtime[0].reference_prices == {"AAPL": 150.0}


class TestTheMonitorSectionReachesTheArtifact:
    """WP-A3: an authored monitor block survives verification and compiling."""

    def _compile(self, tmp_path: Path, monitor_yaml: str) -> CompiledConfig:
        payload = ConfigBuilder(_maximal_spec()).build()
        source = tmp_path / "engine_config.yaml"
        source.write_text(
            render_yaml(
                payload,
                command="pm-config-gen (test)",
                generated_version="test",
                generated_date="2026-10-18",
            )
            + monitor_yaml,
            encoding="utf-8",
        )
        return compile_config(source)

    def test_a_generated_config_carries_default_monitoring(
        self, compiled: tuple[CompiledConfig, dict[str, object]]
    ) -> None:
        config, payload = compiled
        assert "monitor" not in payload
        assert config.monitor == MonitorConfig()

    def test_an_authored_block_lands_in_the_artifact(self, tmp_path: Path) -> None:
        config = self._compile(
            tmp_path,
            "\nmonitor:\n"
            "  hung_after_sec: 8\n"
            "  retention: {raw_hours: 2}\n"
            "  thresholds:\n"
            "    reject_pct_5m: {warn: 5, crit: 20}\n",
        )
        assert config.monitor.hung_after_sec == 8.0
        assert config.monitor.retention.raw_hours == 2
        assert config.monitor.thresholds.reject_pct_5m == ThresholdBand(5.0, 20.0)

    def test_an_incoherent_block_is_refused_at_compile(self, tmp_path: Path) -> None:
        """M029 is an ERROR, so pm-config-deploy refuses before compiling."""
        with pytest.raises(CompileError):
            self._compile(
                tmp_path,
                "\nmonitor:\n  thresholds:\n"
                "    host_cpu_pct: {warn: 95, crit: 80}\n",
            )
