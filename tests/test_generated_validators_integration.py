"""Integration tests for generated model validate() methods.

These tests verify that every declared constraint in the spec is enforced at
runtime.  They exercise the error paths inside each validate() body — the lines
coverage shows uncovered — and confirm the happy path passes clean.

Test intent: assert business rules, not code.  A field declared ``max_len: 32``
must reject a string longer than 32 chars; a field declared ``gt: 0`` must
reject zero.  Each class is exercised with valid construction and targeted
violations of each declared rule.
"""

from __future__ import annotations

import pytest

from edumatcher.models.generated._runtime import MessageValidationError
from edumatcher.models.generated import system as G
from edumatcher.models.generated import risk as R
from edumatcher.models.generated import log as L
from edumatcher.models.generated import order as O


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_validates(obj: object) -> None:
    """Assert that obj.validate() does not raise."""
    obj.validate()  # type: ignore[union-attr]


def _assert_rejects(obj: object, match: str) -> None:
    """Assert that obj.validate() raises MessageValidationError containing match."""
    with pytest.raises(MessageValidationError, match=match):
        obj.validate()  # type: ignore[union-attr]


# ===========================================================================
# system.py — record type validators
# ===========================================================================


class TestSymbolInfoValidation:
    """SymbolInfo: symbol max_len 16, tick_decimals 0..9, mm fields ge 0."""

    def test_valid_minimal(self) -> None:
        _assert_validates(G.SymbolInfo(symbol="AAPL", tick_decimals=2))

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            G.SymbolInfo(symbol="X" * 17, tick_decimals=2),
            "symbol",
        )

    def test_tick_decimals_below_zero(self) -> None:
        _assert_rejects(
            G.SymbolInfo(symbol="AAPL", tick_decimals=-1),
            "tick_decimals",
        )

    def test_tick_decimals_above_nine(self) -> None:
        _assert_rejects(
            G.SymbolInfo(symbol="AAPL", tick_decimals=10),
            "tick_decimals",
        )

    def test_mm_max_spread_negative(self) -> None:
        _assert_rejects(
            G.SymbolInfo(symbol="AAPL", tick_decimals=2, mm_max_spread_ticks=-1),
            "mm_max_spread_ticks",
        )

    def test_mm_min_qty_negative(self) -> None:
        _assert_rejects(
            G.SymbolInfo(symbol="AAPL", tick_decimals=2, mm_min_qty=-5),
            "mm_min_qty",
        )

    def test_mm_fields_zero_are_valid(self) -> None:
        _assert_validates(
            G.SymbolInfo(symbol="AAPL", tick_decimals=2, mm_max_spread_ticks=0, mm_min_qty=0)
        )


class TestCollarValidation:
    """Collar: both band percentages must be >= 0."""

    def test_valid(self) -> None:
        _assert_validates(G.Collar(static_band_pct=5.0, dynamic_band_pct=3.0))

    def test_static_band_negative(self) -> None:
        _assert_rejects(
            G.Collar(static_band_pct=-0.01, dynamic_band_pct=1.0),
            "static_band_pct",
        )

    def test_dynamic_band_negative(self) -> None:
        _assert_rejects(
            G.Collar(static_band_pct=1.0, dynamic_band_pct=-1.0),
            "dynamic_band_pct",
        )

    def test_zero_bands_valid(self) -> None:
        _assert_validates(G.Collar(static_band_pct=0.0, dynamic_band_pct=0.0))


class TestCircuitBreakerLevelValidation:
    """CircuitBreakerLevel: name max_len 32, price_shift_pct > 0, halt_duration_ns >= 0."""

    def test_valid(self) -> None:
        _assert_validates(
            G.CircuitBreakerLevel(name="L1", price_shift_pct=10.0, halt_duration_ns=60_000_000_000)
        )

    def test_name_too_long(self) -> None:
        _assert_rejects(
            G.CircuitBreakerLevel(name="X" * 33, price_shift_pct=5.0, halt_duration_ns=1),
            "name",
        )

    def test_price_shift_zero(self) -> None:
        _assert_rejects(
            G.CircuitBreakerLevel(name="L1", price_shift_pct=0.0, halt_duration_ns=1),
            "price_shift_pct",
        )

    def test_halt_duration_negative(self) -> None:
        _assert_rejects(
            G.CircuitBreakerLevel(name="L1", price_shift_pct=5.0, halt_duration_ns=-1),
            "halt_duration_ns",
        )


class TestGatewayAuthValidation:
    """GatewayAuth: gateway_id max_len 32, reason max_len 256, description max_len 256."""

    def test_valid_accepted(self) -> None:
        _assert_validates(G.GatewayAuth(gateway_id="GW1", accepted=True, reason="", description=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            G.GatewayAuth(gateway_id="X" * 33, accepted=True, reason="", description=""),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            G.GatewayAuth(gateway_id="GW1", accepted=False, reason="X" * 513, description=""),
            "reason",
        )

    def test_description_too_long(self) -> None:
        _assert_rejects(
            G.GatewayAuth(gateway_id="GW1", accepted=True, reason="", description="X" * 513),
            "description",
        )


class TestGatewayByeValidation:
    """GatewayBye: gateway_id max_len 32, reason max_len 256."""

    def test_valid(self) -> None:
        _assert_validates(G.GatewayBye(gateway_id="GW1", reason=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            G.GatewayBye(gateway_id="X" * 33, reason=""),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            G.GatewayBye(gateway_id="GW1", reason="X" * 513),
            "reason",
        )


class TestGatewayConnectValidation:
    def test_valid(self) -> None:
        _assert_validates(G.GatewayConnect(gateway_id="GW1"))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(G.GatewayConnect(gateway_id="X" * 33), "gateway_id")


class TestGatewayDisconnectValidation:
    def test_valid(self) -> None:
        _assert_validates(G.GatewayDisconnect(gateway_id="GW1", reason=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(G.GatewayDisconnect(gateway_id="X" * 33, reason=""), "gateway_id")

    def test_reason_too_long(self) -> None:
        _assert_rejects(G.GatewayDisconnect(gateway_id="GW1", reason="X" * 513), "reason")


class TestHaltedSymbolValidation:
    def test_valid(self) -> None:
        _assert_validates(
            G.HaltedSymbol(symbol="AAPL", resume_at_ns=0, level="", halt_source="")
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            G.HaltedSymbol(symbol="X" * 17, resume_at_ns=0, level="", halt_source=""),
            "symbol",
        )

    def test_level_too_long(self) -> None:
        _assert_rejects(
            G.HaltedSymbol(symbol="AAPL", resume_at_ns=0, level="X" * 33, halt_source=""),
            "level",
        )

    def test_halt_source_too_long(self) -> None:
        _assert_rejects(
            G.HaltedSymbol(symbol="AAPL", resume_at_ns=0, level="", halt_source="X" * 33),
            "halt_source",
        )


class TestSymbolVolumeValidation:
    def test_valid(self) -> None:
        _assert_validates(G.SymbolVolume(symbol="AAPL", qty=100, value=10000, trades=5))

    def test_symbol_too_long(self) -> None:
        _assert_rejects(G.SymbolVolume(symbol="X" * 17, qty=0, value=0, trades=0), "symbol")

    def test_qty_negative(self) -> None:
        _assert_rejects(G.SymbolVolume(symbol="AAPL", qty=-1, value=0, trades=0), "qty")

    def test_value_negative(self) -> None:
        _assert_rejects(G.SymbolVolume(symbol="AAPL", qty=0, value=-1, trades=0), "value")

    def test_trades_negative(self) -> None:
        _assert_rejects(G.SymbolVolume(symbol="AAPL", qty=0, value=0, trades=-1), "trades")


class TestSessionTimesValidation:
    """SessionTimes: all time fields are nullable strings with max_len 32."""

    def _valid(self) -> G.SessionTimes:
        return G.SessionTimes(
            pre_open="08:00",
            opening_auction_start="09:00",
            continuous_start="09:15",
            closing_auction_start="17:00",
            closing_auction_end="17:30",
        )

    def test_valid(self) -> None:
        _assert_validates(self._valid())

    def test_all_none_is_valid(self) -> None:
        _assert_validates(G.SessionTimes())

    def test_pre_open_too_long(self) -> None:
        _assert_rejects(
            G.SessionTimes(pre_open="X" * 33), "pre_open"
        )

    def test_opening_auction_too_long(self) -> None:
        _assert_rejects(
            G.SessionTimes(opening_auction_start="X" * 33), "opening_auction_start"
        )

    def test_continuous_start_too_long(self) -> None:
        _assert_rejects(
            G.SessionTimes(continuous_start="X" * 33), "continuous_start"
        )

    def test_closing_auction_start_too_long(self) -> None:
        _assert_rejects(
            G.SessionTimes(closing_auction_start="X" * 33), "closing_auction_start"
        )

    def test_closing_auction_end_too_long(self) -> None:
        _assert_rejects(
            G.SessionTimes(closing_auction_end="X" * 33), "closing_auction_end"
        )


class TestPositionValidation:
    def test_valid(self) -> None:
        _assert_validates(G.Position(symbol="AAPL", net_qty=10, avg_cost=15000))

    def test_symbol_too_long(self) -> None:
        _assert_rejects(G.Position(symbol="X" * 17, net_qty=0, avg_cost=0), "symbol")

    def test_avg_cost_negative(self) -> None:
        _assert_rejects(G.Position(symbol="AAPL", net_qty=0, avg_cost=-1), "avg_cost")


class TestEodBookValidation:
    def test_valid(self) -> None:
        _assert_validates(
            G.EodBook(symbol="AAPL", tick_decimals=2, bids=[], asks=[])
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            G.EodBook(symbol="X" * 17, tick_decimals=2, bids=[], asks=[]),
            "symbol",
        )

    def test_tick_decimals_negative(self) -> None:
        _assert_rejects(
            G.EodBook(symbol="AAPL", tick_decimals=-1, bids=[], asks=[]),
            "tick_decimals",
        )

    def test_tick_decimals_too_large(self) -> None:
        _assert_rejects(
            G.EodBook(symbol="AAPL", tick_decimals=10, bids=[], asks=[]),
            "tick_decimals",
        )


class TestReferenceSymbolValidation:
    def test_valid(self) -> None:
        _assert_validates(
            G.ReferenceSymbol(symbol="AAPL", tick_decimals=2, level="L1", collar=None)
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceSymbol(symbol="X" * 17, tick_decimals=2, level="L1", collar=None),
            "symbol",
        )

    def test_tick_decimals_below_zero(self) -> None:
        _assert_rejects(
            G.ReferenceSymbol(symbol="AAPL", tick_decimals=-1, level="L1", collar=None),
            "tick_decimals",
        )

    def test_level_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceSymbol(symbol="AAPL", tick_decimals=2, level="X" * 33, collar=None),
            "level",
        )

    def test_tick_decimals_above_nine(self) -> None:
        _assert_rejects(
            G.ReferenceSymbol(symbol="AAPL", tick_decimals=10, level="L1", collar=None),
            "tick_decimals",
        )


class TestQuoteLegsRequestValidation:
    def test_valid(self) -> None:
        _assert_validates(G.QuoteLegsRequest(gateway_id="GW1", symbol="AAPL", show="ALL"))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            G.QuoteLegsRequest(gateway_id="X" * 33, symbol="AAPL", show="ALL"),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            G.QuoteLegsRequest(gateway_id="GW1", symbol="X" * 17, show="ALL"),
            "symbol",
        )

    def test_show_too_long(self) -> None:
        _assert_rejects(
            G.QuoteLegsRequest(gateway_id="GW1", symbol="AAPL", show="X" * 33),
            "show",
        )


class TestReferenceReloadAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            G.ReferenceReloadAck(gateway_id="GW1", command_id="C1", accepted=True, config_version="")
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceReloadAck(gateway_id="X" * 33, command_id="C1", accepted=True, config_version=""),
            "gateway_id",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceReloadAck(gateway_id="GW1", command_id="X" * 65, accepted=True, config_version=""),
            "command_id",
        )

    def test_config_version_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceReloadAck(gateway_id="GW1", command_id="C1", accepted=True, config_version="X" * 65),
            "config_version",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            G.ReferenceReloadAck(
                gateway_id="GW1", command_id="C1", accepted=False,
                config_version="", reason="X" * 513
            ),
            "reason",
        )


# ===========================================================================
# risk.py — message validators
# ===========================================================================


class TestKillSwitchValidation:
    def test_valid(self) -> None:
        _assert_validates(R.KillSwitch(gateway_id="GW1", symbol="", note="", command_id=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitch(gateway_id="X" * 33, symbol="", note="", command_id=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitch(gateway_id="GW1", symbol="X" * 17, note="", command_id=""),
            "symbol",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitch(gateway_id="GW1", symbol="", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitch(gateway_id="GW1", symbol="", note="", command_id="X" * 65),
            "command_id",
        )


class TestKillSwitchAckValidation:
    def test_valid_accepted(self) -> None:
        _assert_validates(
            R.KillSwitchAck(gateway_id="GW1", accepted=True, reason="", cancelled_orders=0, cancelled_quotes=0)
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchAck(gateway_id="X" * 33, accepted=True, reason="", cancelled_orders=0, cancelled_quotes=0),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchAck(gateway_id="GW1", accepted=False, reason="X" * 513, cancelled_orders=0, cancelled_quotes=0),
            "reason",
        )

    def test_cancelled_orders_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchAck(gateway_id="GW1", accepted=True, reason="", cancelled_orders=-1, cancelled_quotes=0),
            "cancelled_orders",
        )

    def test_cancelled_quotes_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchAck(gateway_id="GW1", accepted=True, reason="", cancelled_orders=0, cancelled_quotes=-1),
            "cancelled_quotes",
        )


class TestKillSwitchGatewayValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.KillSwitchGateway(gateway_id="GW1", target_gateway_id="GW2", note="", command_id="")
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGateway(gateway_id="X" * 33, target_gateway_id="GW2", note="", command_id=""),
            "gateway_id",
        )

    def test_target_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGateway(gateway_id="GW1", target_gateway_id="X" * 33, note="", command_id=""),
            "target_gateway_id",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGateway(gateway_id="GW1", target_gateway_id="GW2", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGateway(gateway_id="GW1", target_gateway_id="GW2", note="", command_id="X" * 65),
            "command_id",
        )


class TestKillSwitchGatewayAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.KillSwitchGatewayAck(
                gateway_id="GW1", accepted=True, target_gateway_id="GW2",
                reason="", cancelled_orders=0, cancelled_quotes=0
            )
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGatewayAck(
                gateway_id="X" * 33, accepted=True, target_gateway_id="GW2",
                reason="", cancelled_orders=0, cancelled_quotes=0
            ),
            "gateway_id",
        )

    def test_target_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGatewayAck(
                gateway_id="GW1", accepted=True, target_gateway_id="X" * 33,
                reason="", cancelled_orders=0, cancelled_quotes=0
            ),
            "target_gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGatewayAck(
                gateway_id="GW1", accepted=False, target_gateway_id="GW2",
                reason="X" * 513, cancelled_orders=0, cancelled_quotes=0
            ),
            "reason",
        )

    def test_cancelled_orders_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchGatewayAck(
                gateway_id="GW1", accepted=True, target_gateway_id="GW2",
                reason="", cancelled_orders=-1, cancelled_quotes=0
            ),
            "cancelled_orders",
        )

    def test_cancelled_quotes_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchGatewayAck(
                gateway_id="GW1", accepted=True, target_gateway_id="GW2",
                reason="", cancelled_orders=0, cancelled_quotes=-1
            ),
            "cancelled_quotes",
        )


class TestKillSwitchGlobalValidation:
    def test_valid(self) -> None:
        _assert_validates(R.KillSwitchGlobal(gateway_id="GW1", note="", command_id=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobal(gateway_id="X" * 33, note="", command_id=""),
            "gateway_id",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobal(gateway_id="GW1", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobal(gateway_id="GW1", note="", command_id="X" * 65),
            "command_id",
        )


class TestKillSwitchGlobalAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.KillSwitchGlobalAck(
                gateway_id="GW1", accepted=True, reason="",
                cancelled_orders=0, cancelled_quotes=0, command_id=""
            )
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobalAck(
                gateway_id="X" * 33, accepted=True, reason="",
                cancelled_orders=0, cancelled_quotes=0, command_id=""
            ),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobalAck(
                gateway_id="GW1", accepted=False, reason="X" * 513,
                cancelled_orders=0, cancelled_quotes=0, command_id=""
            ),
            "reason",
        )

    def test_cancelled_orders_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobalAck(
                gateway_id="GW1", accepted=True, reason="",
                cancelled_orders=-1, cancelled_quotes=0, command_id=""
            ),
            "cancelled_orders",
        )

    def test_cancelled_quotes_negative(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobalAck(
                gateway_id="GW1", accepted=True, reason="",
                cancelled_orders=0, cancelled_quotes=-1, command_id=""
            ),
            "cancelled_quotes",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.KillSwitchGlobalAck(
                gateway_id="GW1", accepted=True, reason="",
                cancelled_orders=0, cancelled_quotes=0, command_id="X" * 65
            ),
            "command_id",
        )


class TestSymbolHaltValidation:
    def test_valid(self) -> None:
        _assert_validates(R.SymbolHalt(gateway_id="GW1", symbol="AAPL", level="", note="", command_id=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHalt(gateway_id="X" * 33, symbol="AAPL", level="", note="", command_id=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHalt(gateway_id="GW1", symbol="X" * 17, level="", note="", command_id=""),
            "symbol",
        )

    def test_level_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHalt(gateway_id="GW1", symbol="AAPL", level="X" * 33, note="", command_id=""),
            "level",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHalt(gateway_id="GW1", symbol="AAPL", level="", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHalt(gateway_id="GW1", symbol="AAPL", level="", note="", command_id="X" * 65),
            "command_id",
        )


class TestSymbolHaltAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.SymbolHaltAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="", command_id="")
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHaltAck(gateway_id="X" * 33, accepted=True, symbol="AAPL", reason="", command_id=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHaltAck(gateway_id="GW1", accepted=True, symbol="X" * 17, reason="", command_id=""),
            "symbol",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHaltAck(gateway_id="GW1", accepted=False, symbol="AAPL", reason="X" * 513, command_id=""),
            "reason",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolHaltAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="", command_id="X" * 65),
            "command_id",
        )


class TestSymbolResumeValidation:
    def test_valid(self) -> None:
        _assert_validates(R.SymbolResume(gateway_id="GW1", symbol="AAPL", note="", command_id=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResume(gateway_id="X" * 33, symbol="AAPL", note="", command_id=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResume(gateway_id="GW1", symbol="X" * 17, note="", command_id=""),
            "symbol",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResume(gateway_id="GW1", symbol="AAPL", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResume(gateway_id="GW1", symbol="AAPL", note="", command_id="X" * 65),
            "command_id",
        )


class TestSymbolResumeAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.SymbolResumeAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="")
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResumeAck(gateway_id="X" * 33, accepted=True, symbol="AAPL", reason=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResumeAck(gateway_id="GW1", accepted=True, symbol="X" * 17, reason=""),
            "symbol",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.SymbolResumeAck(gateway_id="GW1", accepted=False, symbol="AAPL", reason="X" * 513),
            "reason",
        )


class TestCancelSymbolValidation:
    def test_valid(self) -> None:
        _assert_validates(R.CancelSymbol(gateway_id="GW1", symbol="AAPL", note="", command_id=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbol(gateway_id="X" * 33, symbol="AAPL", note="", command_id=""),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbol(gateway_id="GW1", symbol="X" * 17, note="", command_id=""),
            "symbol",
        )

    def test_note_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbol(gateway_id="GW1", symbol="AAPL", note="X" * 257, command_id=""),
            "note",
        )

    def test_command_id_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbol(gateway_id="GW1", symbol="AAPL", note="", command_id="X" * 65),
            "command_id",
        )


class TestCancelSymbolAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.CancelSymbolAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="",
                              cancelled_orders=0, cancelled_quotes=0)
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbolAck(gateway_id="X" * 33, accepted=True, symbol="AAPL", reason="",
                              cancelled_orders=0, cancelled_quotes=0),
            "gateway_id",
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbolAck(gateway_id="GW1", accepted=True, symbol="X" * 17, reason="",
                              cancelled_orders=0, cancelled_quotes=0),
            "symbol",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.CancelSymbolAck(gateway_id="GW1", accepted=False, symbol="AAPL", reason="X" * 513,
                              cancelled_orders=0, cancelled_quotes=0),
            "reason",
        )

    def test_cancelled_orders_negative(self) -> None:
        _assert_rejects(
            R.CancelSymbolAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="",
                              cancelled_orders=-1, cancelled_quotes=0),
            "cancelled_orders",
        )

    def test_cancelled_quotes_negative(self) -> None:
        _assert_rejects(
            R.CancelSymbolAck(gateway_id="GW1", accepted=True, symbol="AAPL", reason="",
                              cancelled_orders=0, cancelled_quotes=-1),
            "cancelled_quotes",
        )


class TestCircuitBreakerHaltAllAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.CircuitBreakerHaltAllAck(gateway_id="GW1", accepted=True, reason="", halted_symbols=0)
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.CircuitBreakerHaltAllAck(gateway_id="X" * 33, accepted=True, reason="", halted_symbols=0),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.CircuitBreakerHaltAllAck(gateway_id="GW1", accepted=False, reason="X" * 513, halted_symbols=0),
            "reason",
        )

    def test_halted_symbols_negative(self) -> None:
        _assert_rejects(
            R.CircuitBreakerHaltAllAck(gateway_id="GW1", accepted=True, reason="", halted_symbols=-1),
            "halted_symbols",
        )


class TestCircuitBreakerResumeAllAckValidation:
    def test_valid(self) -> None:
        _assert_validates(
            R.CircuitBreakerResumeAllAck(gateway_id="GW1", accepted=True, reason="", resumed_symbols=0)
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            R.CircuitBreakerResumeAllAck(gateway_id="X" * 33, accepted=True, reason="", resumed_symbols=0),
            "gateway_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            R.CircuitBreakerResumeAllAck(gateway_id="GW1", accepted=False, reason="X" * 513, resumed_symbols=0),
            "reason",
        )

    def test_resumed_symbols_negative(self) -> None:
        _assert_rejects(
            R.CircuitBreakerResumeAllAck(gateway_id="GW1", accepted=True, reason="", resumed_symbols=-1),
            "resumed_symbols",
        )


# ===========================================================================
# order.py — record type validators
# ===========================================================================


class TestOrderAckValidation:
    def test_valid(self) -> None:
        _assert_validates(O.OrderAck(gateway_id="GW1", order_id="O1", accepted=True, reason=""))

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            O.OrderAck(gateway_id="X" * 33, order_id="O1", accepted=True, reason=""),
            "gateway_id",
        )

    def test_order_id_too_long(self) -> None:
        _assert_rejects(
            O.OrderAck(gateway_id="GW1", order_id="X" * 65, accepted=True, reason=""),
            "order_id",
        )

    def test_reason_too_long(self) -> None:
        _assert_rejects(
            O.OrderAck(gateway_id="GW1", order_id="O1", accepted=False, reason="X" * 257),
            "reason",
        )


class TestOrderFillValidation:
    def _valid(self) -> O.OrderFill:
        return O.OrderFill(
            gateway_id="GW1",
            order_id="O1",
            fill_qty=10,
            fill_price=100.0,
            remaining_qty=0,
            status="FILLED",
        )

    def test_valid(self) -> None:
        _assert_validates(self._valid())

    def test_gateway_id_too_long(self) -> None:
        import dataclasses
        obj = dataclasses.replace(self._valid(), gateway_id="X" * 33)
        _assert_rejects(obj, "gateway_id")

    def test_order_id_too_long(self) -> None:
        import dataclasses
        obj = dataclasses.replace(self._valid(), order_id="X" * 65)
        _assert_rejects(obj, "order_id")

    def test_status_too_long(self) -> None:
        import dataclasses
        obj = dataclasses.replace(self._valid(), status="X" * 17)
        _assert_rejects(obj, "status")

    def test_symbol_too_long(self) -> None:
        import dataclasses
        obj = dataclasses.replace(self._valid(), symbol="X" * 17)
        _assert_rejects(obj, "symbol")


class TestOrderCancelValidation:
    def test_valid(self) -> None:
        _assert_validates(O.OrderCancel(order_id="O1", gateway_id="GW1"))

    def test_order_id_too_long(self) -> None:
        _assert_rejects(
            O.OrderCancel(order_id="X" * 65, gateway_id="GW1"),
            "order_id",
        )

    def test_gateway_id_too_long(self) -> None:
        _assert_rejects(
            O.OrderCancel(order_id="O1", gateway_id="X" * 33),
            "gateway_id",
        )


class TestComboLegValidation:
    def test_valid_market(self) -> None:
        _assert_validates(
            O.ComboLeg(symbol="AAPL", side="BUY", order_type="MARKET", quantity=100)
        )

    def test_symbol_too_long(self) -> None:
        _assert_rejects(
            O.ComboLeg(symbol="X" * 17, side="BUY", order_type="MARKET", quantity=100),
            "symbol",
        )

    def test_quantity_zero(self) -> None:
        _assert_rejects(
            O.ComboLeg(symbol="AAPL", side="BUY", order_type="LIMIT", quantity=0, price=100.0),
            "quantity",
        )


# ===========================================================================
# log.py — record type validators
# ===========================================================================


class TestLogNotifyValidation:
    def test_valid(self) -> None:
        _assert_validates(
            L.LogNotify(sub_id="S1", count=5, levels=[], last_seq=1, server_last_seq=1, timestamp=1.0)
        )

    def test_sub_id_too_long(self) -> None:
        _assert_rejects(
            L.LogNotify(sub_id="X" * 65, count=0, levels=[], last_seq=0, server_last_seq=0, timestamp=0.0),
            "sub_id",
        )


class TestLevelCountValidation:
    def test_valid(self) -> None:
        _assert_validates(L.LevelCount(level="INFO", count=5))

    def test_level_too_long(self) -> None:
        _assert_rejects(L.LevelCount(level="X" * 17, count=0), "level")

    def test_count_negative(self) -> None:
        _assert_rejects(L.LevelCount(level="INFO", count=-1), "count")


class TestLogBackfillRequestValidation:
    def test_valid(self) -> None:
        _assert_validates(
            L.LogBackfillRequest(sub_id="S1", minutes=60, filter=None, max_rows=1000)
        )

    def test_sub_id_too_long(self) -> None:
        _assert_rejects(
            L.LogBackfillRequest(sub_id="X" * 65, minutes=60, filter=None, max_rows=1000),
            "sub_id",
        )

    def test_minutes_zero(self) -> None:
        _assert_rejects(
            L.LogBackfillRequest(sub_id="S1", minutes=0, filter=None, max_rows=1000),
            "minutes",
        )

    def test_sub_id_and_minutes_valid(self) -> None:
        # max_rows has no ge/gt rule in the spec; any non-negative value is valid
        _assert_validates(
            L.LogBackfillRequest(sub_id="S1", minutes=1, filter=None, max_rows=0)
        )


class TestLogFilterValidation:
    def test_valid_empty(self) -> None:
        _assert_validates(L.LogFilter())

    def test_min_level_too_long(self) -> None:
        _assert_rejects(L.LogFilter(min_level="X" * 17), "min_level")

    def test_contains_too_long(self) -> None:
        _assert_rejects(L.LogFilter(contains="X" * 257), "contains")


# ===========================================================================
# Round-trip integration: make → decode → validate for system messages
# ===========================================================================


class TestSystemMessageRoundTrips:
    """Verify that make_*() → wire frames → parse_*() → validate() is a clean
    cycle for messages that were missing coverage on their parse/validate paths.
    """

    def test_gateway_auth_round_trip(self) -> None:
        frames = G.make_gateway_auth(
            gateway_id="GW1", accepted=True, reason="", description="ok"
        )
        msg = G.parse_gateway_auth(frames)
        msg.validate()
        assert msg.gateway_id == "GW1"
        assert msg.accepted is True

    def test_gateway_bye_round_trip(self) -> None:
        frames = G.make_gateway_bye(gateway_id="GW2", reason="timeout")
        msg = G.parse_gateway_bye(frames)
        msg.validate()
        assert msg.gateway_id == "GW2"
        assert msg.reason == "timeout"

    def test_gateway_connect_round_trip(self) -> None:
        frames = G.make_gateway_connect(gateway_id="GW3")
        msg = G.parse_gateway_connect(frames)
        msg.validate()
        assert msg.gateway_id == "GW3"

    def test_gateway_disconnect_round_trip(self) -> None:
        frames = G.make_gateway_disconnect(gateway_id="GW4", reason="logout")
        msg = G.parse_gateway_disconnect(frames)
        msg.validate()
        assert msg.gateway_id == "GW4"

    def test_halt_status_request_round_trip(self) -> None:
        frames = G.make_halt_status_request(gateway_id="GW1")
        msg = G.parse_halt_status_request(frames)
        msg.validate()
        assert msg.gateway_id == "GW1"

    def test_symbols_request_round_trip(self) -> None:
        frames = G.make_symbols_request(gateway_id="GW1")
        msg = G.parse_symbols_request(frames)
        msg.validate()

    def test_symbols_round_trip_empty(self) -> None:
        frames = G.make_symbols(gateway_id="GW1", symbols=[])
        msg = G.parse_symbols(frames)
        msg.validate()
        assert msg.symbols == []

    def test_symbols_with_symbol_info(self) -> None:
        frames = G.make_symbols(
            gateway_id="GW1",
            symbols=[{"symbol": "AAPL", "tick_decimals": 2}],
        )
        msg = G.parse_symbols(frames)
        msg.validate()
        assert len(msg.symbols) == 1
        assert msg.symbols[0].symbol == "AAPL"
        assert msg.symbols[0].tick_decimals == 2

    def test_volume_request_round_trip(self) -> None:
        frames = G.make_volume_request(gateway_id="GW1")
        msg = G.parse_volume_request(frames)
        msg.validate()

    def test_volume_round_trip(self) -> None:
        frames = G.make_volume(
            gateway_id="GW1",
            symbols=[{"symbol": "AAPL", "qty": 100, "value": 15000, "trades": 5}],
            total_qty=100,
            total_value=15000,
            total_trades=5,
        )
        msg = G.parse_volume(frames)
        msg.validate()
        assert msg.total_qty == 100
        assert len(msg.symbols) == 1
        assert msg.symbols[0].symbol == "AAPL"
        assert msg.symbols[0].qty == 100

    def test_risk_state_request_round_trip(self) -> None:
        frames = G.make_risk_state_request(gateway_id="GW1")
        msg = G.parse_risk_state_request(frames)
        msg.validate()

    def test_position_request_round_trip(self) -> None:
        frames = G.make_position_request(gateway_id="GW1")
        msg = G.parse_position_request(frames)
        msg.validate()

    def test_position_snapshot_round_trip(self) -> None:
        frames = G.make_position_snapshot(gateway_id="GW1", positions=[])
        msg = G.parse_position_snapshot(frames)
        msg.validate()
        assert msg.positions == []

    def test_gateways_request_round_trip(self) -> None:
        frames = G.make_gateways_request(gateway_id="GW1")
        msg = G.parse_gateways_request(frames)
        msg.validate()

    def test_reference_request_round_trip(self) -> None:
        frames = G.make_reference_request(gateway_id="GW1")
        msg = G.parse_reference_request(frames)
        msg.validate()

    def test_reference_reload_round_trip(self) -> None:
        frames = G.make_reference_reload(gateway_id="GW1", command_id="CMD1")
        msg = G.parse_reference_reload(frames)
        msg.validate()

    def test_session_schedule_request_round_trip(self) -> None:
        frames = G.make_session_schedule_request(gateway_id="GW1")
        msg = G.parse_session_schedule_request(frames)
        msg.validate()

    def test_session_state_request_round_trip(self) -> None:
        frames = G.make_session_state_request(gateway_id="GW1")
        msg = G.parse_session_state_request(frames)
        msg.validate()

    def test_quote_bootstrap_request_round_trip(self) -> None:
        frames = G.make_quote_bootstrap_request(gateway_id="GW1", symbol="")
        msg = G.parse_quote_bootstrap_request(frames)
        msg.validate()

    def test_quote_legs_request_round_trip(self) -> None:
        frames = G.make_quote_legs_request(gateway_id="GW1", symbol="AAPL", show="ALL")
        msg = G.parse_quote_legs_request(frames)
        msg.validate()
        assert msg.symbol == "AAPL"


class TestRiskMessageRoundTrips:
    """Verify make→parse→validate cycles for risk messages."""

    def test_kill_switch_round_trip(self) -> None:
        frames = R.make_kill_switch(gateway_id="GW1", symbol="", note="", command_id="")
        msg = R.parse_kill_switch(frames)
        msg.validate()
        assert msg.gateway_id == "GW1"

    def test_kill_switch_ack_accepted_round_trip(self) -> None:
        frames = R.make_kill_switch_ack(
            gateway_id="GW1", accepted=True, reason="",
            cancelled_orders=5, cancelled_quotes=2
        )
        msg = R.parse_kill_switch_ack(frames)
        msg.validate()
        assert msg.accepted is True
        assert msg.cancelled_orders == 5

    def test_kill_switch_ack_rejected_round_trip(self) -> None:
        frames = R.make_kill_switch_ack(
            gateway_id="GW1", accepted=False, reason="not connected",
            cancelled_orders=0, cancelled_quotes=0
        )
        msg = R.parse_kill_switch_ack(frames)
        msg.validate()
        assert msg.accepted is False
        assert msg.reason == "not connected"

    def test_symbol_halt_round_trip(self) -> None:
        frames = R.make_symbol_halt(
            gateway_id="GW1", symbol="AAPL", level="L1", note="fat finger", command_id="C1"
        )
        msg = R.parse_symbol_halt(frames)
        msg.validate()
        assert msg.symbol == "AAPL"
        assert msg.level == "L1"

    def test_symbol_halt_ack_round_trip(self) -> None:
        frames = R.make_symbol_halt_ack(
            gateway_id="GW1", accepted=True, symbol="AAPL", reason="", command_id="C1"
        )
        msg = R.parse_symbol_halt_ack(frames)
        msg.validate()
        assert msg.accepted is True

    def test_symbol_resume_round_trip(self) -> None:
        frames = R.make_symbol_resume(
            gateway_id="GW1", symbol="AAPL", note="", command_id="C2"
        )
        msg = R.parse_symbol_resume(frames)
        msg.validate()
        assert msg.symbol == "AAPL"

    def test_symbol_resume_ack_round_trip(self) -> None:
        frames = R.make_symbol_resume_ack(
            gateway_id="GW1", accepted=True, symbol="AAPL", reason=""
        )
        msg = R.parse_symbol_resume_ack(frames)
        msg.validate()

    def test_cancel_symbol_round_trip(self) -> None:
        frames = R.make_cancel_symbol(
            gateway_id="GW1", symbol="AAPL", note="risk limit", command_id="C3"
        )
        msg = R.parse_cancel_symbol(frames)
        msg.validate()
        assert msg.symbol == "AAPL"
        assert msg.note == "risk limit"

    def test_cancel_symbol_ack_round_trip(self) -> None:
        frames = R.make_cancel_symbol_ack(
            gateway_id="GW1", accepted=True, symbol="AAPL", reason="",
            cancelled_orders=3, cancelled_quotes=1
        )
        msg = R.parse_cancel_symbol_ack(frames)
        msg.validate()
        assert msg.cancelled_orders == 3

    def test_circuit_breaker_halt_all_round_trip(self) -> None:
        frames = R.make_circuit_breaker_halt_all(gateway_id="GW1")
        msg = R.parse_circuit_breaker_halt_all(frames)
        msg.validate()

    def test_circuit_breaker_halt_all_ack_round_trip(self) -> None:
        frames = R.make_circuit_breaker_halt_all_ack(
            gateway_id="GW1", accepted=True, reason="", halted_symbols=5
        )
        msg = R.parse_circuit_breaker_halt_all_ack(frames)
        msg.validate()
        assert msg.halted_symbols == 5

    def test_circuit_breaker_resume_all_round_trip(self) -> None:
        frames = R.make_circuit_breaker_resume_all(gateway_id="GW1")
        msg = R.parse_circuit_breaker_resume_all(frames)
        msg.validate()

    def test_circuit_breaker_resume_all_ack_round_trip(self) -> None:
        frames = R.make_circuit_breaker_resume_all_ack(
            gateway_id="GW1", accepted=True, reason="", resumed_symbols=3
        )
        msg = R.parse_circuit_breaker_resume_all_ack(frames)
        msg.validate()
        assert msg.resumed_symbols == 3
