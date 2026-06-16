"""Build the config mapping emitted by pm-config-gen."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edumatcher.models.participant import ParticipantRole

from .cb_spec import CbSpec
from .defaults import (
    DEFAULT_CB_WINDOW_NS,
    DEFAULT_DYNAMIC_BAND_PCT,
    DEFAULT_MM_MIN_QTY,
    DEFAULT_MM_SPREAD_TICKS,
    DEFAULT_MM_STUB_QTY,
    DEFAULT_SNAPSHOT_INTERVAL_SEC,
    DEFAULT_STATIC_BAND_PCT,
    DEFAULT_TICK_DECIMALS,
)
from .gateway_spec import GatewaySpec
from .symbol_spec import SymbolOverride


@dataclass
class ConfigSpec:
    symbols: list[str]
    gateways: list[GatewaySpec]
    sessions_enabled: bool = False
    snapshot_interval_sec: float = DEFAULT_SNAPSHOT_INTERVAL_SEC
    enforce_collars: bool = True
    enforce_circuit_breakers: bool = True
    static_band_pct: float | None = None
    dynamic_band_pct: float | None = None
    risk_levels: dict[str, tuple[float, float | None]] = field(default_factory=dict)
    cb_levels: list[CbSpec] = field(default_factory=list)
    cb_window_ns: int = DEFAULT_CB_WINDOW_NS
    mm_spread_ticks: int = DEFAULT_MM_SPREAD_TICKS
    mm_min_qty: int = DEFAULT_MM_MIN_QTY
    enforce_mm_obligations: bool = False
    emit_mm_defaults: bool = False
    tick_decimals: int = DEFAULT_TICK_DECIMALS
    seed_last_prices: bool = False
    emit_schedule: bool = True
    pre_open: str = "09:00"
    opening_auction: str = "09:25"
    continuous: str = "09:30"
    closing_auction: str = "16:00"
    closing_end: str = "16:05"
    symbol_overrides: dict[str, SymbolOverride] = field(default_factory=dict)


class ConfigBuilder:
    def __init__(self, spec: ConfigSpec):
        self.spec = spec

    def build(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "sessions_enabled": self.spec.sessions_enabled,
            "enforce_collars": self.spec.enforce_collars,
            "enforce_circuit_breakers": self.spec.enforce_circuit_breakers,
            "snapshot_interval_sec": self.spec.snapshot_interval_sec,
        }

        if self._should_emit_mm_defaults():
            cfg["mm_obligation_defaults"] = self._build_mm_defaults()

        risk_controls = self._build_risk_controls()
        if risk_controls is not None:
            cfg["risk_controls"] = risk_controls

        if self.spec.cb_levels:
            cfg["circuit_breaker_defaults"] = self._build_cb_defaults()

        cfg["gateways"] = {"alf": self._build_gateways()}
        cfg["symbols"] = self._build_symbols()

        if self.spec.sessions_enabled and self.spec.emit_schedule:
            cfg["schedule"] = {
                "pre_open": self.spec.pre_open,
                "opening_auction_start": self.spec.opening_auction,
                "continuous_start": self.spec.continuous,
                "closing_auction_start": self.spec.closing_auction,
                "closing_auction_end": self.spec.closing_end,
            }

        return cfg

    def _should_emit_mm_defaults(self) -> bool:
        if self.spec.emit_mm_defaults:
            return True
        for override in self.spec.symbol_overrides.values():
            if override.mm_spread_ticks is not None or override.mm_min_qty is not None:
                return True
        return False

    def _build_mm_defaults(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enforce_mm_obligation": self.spec.enforce_mm_obligations,
            "mm_max_spread_ticks": self.spec.mm_spread_ticks,
            "mm_min_qty": self.spec.mm_min_qty,
        }

        symbol_overrides: dict[str, Any] = {}
        for symbol, override in self.spec.symbol_overrides.items():
            if override.mm_spread_ticks is None and override.mm_min_qty is None:
                continue
            symbol_overrides[symbol] = {
                "enforce_mm_obligation": self.spec.enforce_mm_obligations,
                "mm_max_spread_ticks": (
                    override.mm_spread_ticks
                    if override.mm_spread_ticks is not None
                    else self.spec.mm_spread_ticks
                ),
                "mm_min_qty": (
                    override.mm_min_qty
                    if override.mm_min_qty is not None
                    else self.spec.mm_min_qty
                ),
            }
        if symbol_overrides:
            payload["symbols"] = symbol_overrides

        return payload

    def _build_risk_controls(self) -> dict[str, Any] | None:
        levels: dict[str, Any] = {}
        default_level: str | None = None

        if (
            self.spec.static_band_pct is not None
            or self.spec.dynamic_band_pct is not None
        ):
            levels["DEFAULT"] = {
                "collar": {
                    "static_band_pct": (
                        self.spec.static_band_pct
                        if self.spec.static_band_pct is not None
                        else DEFAULT_STATIC_BAND_PCT
                    ),
                    "dynamic_band_pct": (
                        self.spec.dynamic_band_pct
                        if self.spec.dynamic_band_pct is not None
                        else DEFAULT_DYNAMIC_BAND_PCT
                    ),
                }
            }
            default_level = "DEFAULT"

        for name, (static_pct, dynamic_pct) in self.spec.risk_levels.items():
            levels[name] = {
                "collar": {
                    "static_band_pct": static_pct,
                    "dynamic_band_pct": (
                        dynamic_pct
                        if dynamic_pct is not None
                        else DEFAULT_DYNAMIC_BAND_PCT
                    ),
                }
            }

        if not levels:
            return None

        payload: dict[str, Any] = {"levels": levels}
        if default_level is not None:
            payload["default_level"] = default_level
        return payload

    def _build_cb_defaults(self) -> dict[str, Any]:
        levels: dict[str, Any] = {}
        for level in self.spec.cb_levels:
            halt_ns = None
            if level.halt_mins is not None and level.halt_mins > 0:
                halt_ns = level.halt_mins * 60 * 1_000_000_000

            levels[level.name] = {
                "price_shift_pct": level.shift_pct,
                "halt_duration_ns": halt_ns,
                "resumption_mode": "AUCTION",
            }

        return {
            "reference_window_ns": self.spec.cb_window_ns,
            "levels": levels,
        }

    def _build_gateways(self) -> list[dict[str, Any]]:
        gateways: list[dict[str, Any]] = []
        for gw in self.spec.gateways:
            payload: dict[str, Any] = {
                "id": gw.gateway_id,
                "role": gw.role.value,
                "disconnect_behaviour": gw.disconnect_behaviour.value,
            }
            if gw.role == ParticipantRole.MARKET_MAKER:
                payload["quote_refresh_policy"] = "INACTIVATE_ON_ANY_FILL"
            gateways.append(payload)
        return gateways

    def _build_symbols(self) -> dict[str, Any]:
        mm_gateways = [
            gw.gateway_id
            for gw in self.spec.gateways
            if gw.role == ParticipantRole.MARKET_MAKER
        ]

        symbols: dict[str, Any] = {}
        for symbol in self.spec.symbols:
            override = self.spec.symbol_overrides.get(symbol, SymbolOverride())
            payload: dict[str, Any] = {
                "tick_decimals": (
                    override.tick_decimals
                    if override.tick_decimals is not None
                    else self.spec.tick_decimals
                )
            }

            if override.level is not None:
                payload["level"] = override.level

            if self.spec.seed_last_prices:
                payload["last_buy_price"] = None
                payload["last_sell_price"] = None

            if (
                override.static_band_pct is not None
                or override.dynamic_band_pct is not None
            ):
                collar: dict[str, Any] = {}
                if override.static_band_pct is not None:
                    collar["static_band_pct"] = override.static_band_pct
                if override.dynamic_band_pct is not None:
                    collar["dynamic_band_pct"] = override.dynamic_band_pct
                payload["collar"] = collar

            cb_levels: dict[str, dict[str, Any]] = {}
            for level_name in sorted(
                set(override.cb_shift) | set(override.cb_halt_mins)
            ):
                level_payload: dict[str, Any] = {}
                if level_name in override.cb_shift:
                    level_payload["price_shift_pct"] = override.cb_shift[level_name]
                if level_name in override.cb_halt_mins:
                    halt_mins = override.cb_halt_mins[level_name]
                    if halt_mins is None or halt_mins == 0:
                        level_payload["halt_duration_ns"] = None
                    else:
                        level_payload["halt_duration_ns"] = (
                            halt_mins * 60 * 1_000_000_000
                        )
                cb_levels[level_name] = level_payload
            if cb_levels:
                payload["circuit_breaker"] = {"levels": cb_levels}

            if mm_gateways:
                payload["market_maker_quotes"] = [
                    {
                        "gateway_id": gateway_id,
                        "bid_price": None,
                        "ask_price": None,
                        "bid_qty": DEFAULT_MM_STUB_QTY,
                        "ask_qty": DEFAULT_MM_STUB_QTY,
                        "tif": "DAY",
                        "seed_once": True,
                    }
                    for gateway_id in mm_gateways
                ]

            symbols[symbol] = payload

        return symbols
