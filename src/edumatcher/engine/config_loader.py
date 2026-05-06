"""
engine/config_loader.py — load and validate engine_config.yaml.

Returned structure:
    EngineConfig
        .symbols: dict[str, SymbolConfig]
        .market_maker_combos: list[ComboSeedConfig]

    SymbolConfig
        .name:              str
        .last_buy_price:    float | None
        .last_sell_price:   float | None
        .market_maker_orders: list[str]   # raw FIX-like strings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from edumatcher.models.combo import ComboLeg, ComboType
from edumatcher.models.order import TIF


@dataclass
class SymbolConfig:
    name: str
    last_buy_price: Optional[float] = None
    last_sell_price: Optional[float] = None
    market_maker_orders: list[str] = field(default_factory=list)


@dataclass
class ComboSeedConfig:
    combo_id: str
    combo_type: ComboType = ComboType.AON
    tif: TIF = TIF.DAY
    legs: list[ComboLeg] = field(default_factory=list)


@dataclass
class FixGatewayConfig:
    id: str
    description: str = ""


@dataclass
class ScheduleConfig:
    """Optional daily session schedule (HH:MM times)."""

    pre_open: str = "09:00"
    opening_auction_start: str = "09:25"
    continuous_start: str = "09:30"
    closing_auction_start: str = "16:00"
    closing_auction_end: str = "16:05"


@dataclass
class EngineConfig:
    symbols: dict[str, SymbolConfig] = field(default_factory=dict)
    fix_gateways: dict[str, FixGatewayConfig] = field(default_factory=dict)
    market_maker_combos: list[ComboSeedConfig] = field(default_factory=list)
    sessions_enabled: bool = False
    schedule: ScheduleConfig | None = None

    @property
    def allowed_symbols(self) -> frozenset[str]:
        return frozenset(self.symbols)

    @property
    def allowed_fix_gateways(self) -> frozenset[str]:
        return frozenset(self.fix_gateways)


def load_engine_config(path: Path) -> EngineConfig:
    """
    Parse *path* as YAML and return an EngineConfig.

    Raises
    ------
    FileNotFoundError  if the file does not exist.
    ValueError         if the YAML structure is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Engine config file not found: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(
            f"Engine config must be a YAML mapping, got {type(raw).__name__}"
        )

    symbols_raw = raw.get("symbols")
    if not isinstance(symbols_raw, dict):
        raise ValueError("Engine config must have a 'symbols' mapping")

    gateways_raw = raw.get("gateways")
    if not isinstance(gateways_raw, dict):
        raise ValueError("Engine config must have a 'gateways' mapping")
    fix_raw = gateways_raw.get("fix")
    if not isinstance(fix_raw, list):
        raise ValueError("Engine config must have a 'gateways.fix' list")

    symbols: dict[str, SymbolConfig] = {}
    for sym, cfg in symbols_raw.items():
        sym = str(sym).upper()
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            raise ValueError(f"Config for symbol '{sym}' must be a mapping")

        lbp = cfg.get("last_buy_price")
        lsp = cfg.get("last_sell_price")
        mm_orders = cfg.get("market_maker_orders") or []

        if lbp is not None:
            try:
                lbp = float(lbp)
            except (TypeError, ValueError):
                raise ValueError(f"Symbol '{sym}': last_buy_price must be a number")
        if lsp is not None:
            try:
                lsp = float(lsp)
            except (TypeError, ValueError):
                raise ValueError(f"Symbol '{sym}': last_sell_price must be a number")
        if not isinstance(mm_orders, list):
            raise ValueError(f"Symbol '{sym}': market_maker_orders must be a list")
        for i, line in enumerate(mm_orders):
            if not isinstance(line, str):
                raise ValueError(
                    f"Symbol '{sym}': market_maker_orders[{i}] must be a string"
                )
            if not line.upper().startswith("NEW|"):
                raise ValueError(
                    f"Symbol '{sym}': market_maker_orders[{i}] must start with 'NEW|'"
                )

        symbols[sym] = SymbolConfig(
            name=sym,
            last_buy_price=lbp,
            last_sell_price=lsp,
            market_maker_orders=list(mm_orders),
        )

    mm_combos_raw = raw.get("market_maker_combos") or []
    if not isinstance(mm_combos_raw, list):
        raise ValueError("Engine config 'market_maker_combos' must be a list")

    market_maker_combos: list[ComboSeedConfig] = []
    for i, combo_raw in enumerate(mm_combos_raw):
        if not isinstance(combo_raw, dict):
            raise ValueError(f"market_maker_combos[{i}] must be a mapping")

        combo_id_raw = combo_raw.get("combo_id")
        if not isinstance(combo_id_raw, str) or not combo_id_raw.strip():
            raise ValueError(
                f"market_maker_combos[{i}].combo_id must be a non-empty string"
            )

        try:
            combo_type = ComboType(
                str(combo_raw.get("combo_type", ComboType.AON.value)).upper()
            )
        except ValueError as exc:
            raise ValueError(f"market_maker_combos[{i}].combo_type is invalid") from exc

        try:
            tif = TIF(str(combo_raw.get("tif", TIF.DAY.value)).upper())
        except ValueError as exc:
            raise ValueError(f"market_maker_combos[{i}].tif is invalid") from exc

        legs_raw = combo_raw.get("legs")
        if not isinstance(legs_raw, list):
            raise ValueError(f"market_maker_combos[{i}].legs must be a list")
        if len(legs_raw) < 2:
            raise ValueError(f"market_maker_combos[{i}] requires at least 2 legs")
        if len(legs_raw) > 10:
            raise ValueError(f"market_maker_combos[{i}] supports at most 10 legs")

        legs: list[ComboLeg] = []
        seen_symbols: set[str] = set()
        for j, leg_raw in enumerate(legs_raw):
            if not isinstance(leg_raw, dict):
                raise ValueError(
                    f"market_maker_combos[{i}].legs[{j}] must be a mapping"
                )

            leg_payload = dict(leg_raw)
            if "symbol" in leg_payload:
                leg_payload["symbol"] = str(leg_payload["symbol"]).upper()
            if "side" in leg_payload:
                leg_payload["side"] = str(leg_payload["side"]).upper()
            if "order_type" in leg_payload:
                leg_payload["order_type"] = str(leg_payload["order_type"]).upper()
            if "smp_action" in leg_payload and leg_payload["smp_action"] is not None:
                leg_payload["smp_action"] = str(leg_payload["smp_action"]).upper()

            try:
                leg = ComboLeg.from_dict(leg_payload)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"market_maker_combos[{i}].legs[{j}] is invalid"
                ) from exc

            if leg.symbol in seen_symbols:
                raise ValueError(
                    f"market_maker_combos[{i}] contains duplicate symbol '{leg.symbol}'"
                )
            if leg.symbol not in symbols:
                raise ValueError(
                    f"market_maker_combos[{i}] references unknown symbol '{leg.symbol}'"
                )

            seen_symbols.add(leg.symbol)
            legs.append(leg)

        market_maker_combos.append(
            ComboSeedConfig(
                combo_id=combo_id_raw.strip(),
                combo_type=combo_type,
                tif=tif,
                legs=legs,
            )
        )

    fix_gateways: dict[str, FixGatewayConfig] = {}
    for i, item in enumerate(fix_raw):
        if not isinstance(item, dict):
            raise ValueError(f"gateways.fix[{i}] must be a mapping")
        gw_id_raw = item.get("id")
        if not isinstance(gw_id_raw, str) or not gw_id_raw.strip():
            raise ValueError(f"gateways.fix[{i}].id must be a non-empty string")
        gw_id = gw_id_raw.strip().upper()
        desc = item.get("description", "")
        if desc is None:
            desc = ""
        if not isinstance(desc, str):
            raise ValueError(f"gateways.fix[{i}].description must be a string")
        if gw_id in fix_gateways:
            raise ValueError(f"Duplicate gateway id in gateways.fix: {gw_id}")
        fix_gateways[gw_id] = FixGatewayConfig(id=gw_id, description=desc)

    if not fix_gateways:
        raise ValueError("Engine config must define at least one gateways.fix entry")

    sessions_enabled_raw = raw.get("sessions_enabled", True)
    if not isinstance(sessions_enabled_raw, bool):
        raise ValueError("Engine config 'sessions_enabled' must be a boolean")

    # Optional schedule section
    schedule_cfg: ScheduleConfig | None = None
    schedule_raw = raw.get("schedule")
    if isinstance(schedule_raw, dict):
        schedule_cfg = ScheduleConfig(
            pre_open=str(schedule_raw.get("pre_open", "09:00")),
            opening_auction_start=str(
                schedule_raw.get("opening_auction_start", "09:25")
            ),
            continuous_start=str(schedule_raw.get("continuous_start", "09:30")),
            closing_auction_start=str(
                schedule_raw.get("closing_auction_start", "16:00")
            ),
            closing_auction_end=str(schedule_raw.get("closing_auction_end", "16:05")),
        )

    return EngineConfig(
        symbols=symbols,
        fix_gateways=fix_gateways,
        market_maker_combos=market_maker_combos,
        sessions_enabled=sessions_enabled_raw,
        schedule=schedule_cfg,
    )
