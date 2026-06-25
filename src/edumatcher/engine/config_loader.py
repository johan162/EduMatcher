"""
engine/config_loader.py — load and validate engine_config.yaml.

Returned structure:
    EngineConfig
        .symbols: dict[str, SymbolConfig]
        .market_maker_combos: list[ComboSeedConfig]

    SymbolConfig
        .name:              str
        .outstanding_shares: int | None
        .last_buy_price:    float | None
        .last_sell_price:   float | None
        .market_maker_quotes: list[MMQuoteSeed]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml

from edumatcher.models.combo import ComboLeg, ComboType
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.quote import QuoteRefreshPolicy
from edumatcher.models.order import TIF
from edumatcher.models.mm_obligation import MarketMakerObligation

if TYPE_CHECKING:
    from edumatcher.engine.collar import CollarConfig
    from edumatcher.engine.circuit_breaker import CircuitBreakerConfig

_DEFAULT_MM_MAX_SPREAD_TICKS = 10
_DEFAULT_MM_MIN_QTY = 100
_DEFAULT_SNAPSHOT_INTERVAL_SEC = 0.5
_DEFAULT_CB_LEVELS: dict[str, dict[str, Any]] = {
    "L1": {"price_shift_pct": 0.07, "halt_duration_ns": 300_000_000_000},
    "L2": {"price_shift_pct": 0.13, "halt_duration_ns": 900_000_000_000},
    "L3": {"price_shift_pct": 0.20, "halt_duration_ns": None},
}


@dataclass
class MMObligationPolicy:
    enforce_mm_obligation: bool = False
    mm_max_spread_ticks: int = _DEFAULT_MM_MAX_SPREAD_TICKS
    mm_min_qty: int = _DEFAULT_MM_MIN_QTY


@dataclass
class SymbolConfig:
    name: str
    level: str | None = None
    tick_decimals: int = 2
    outstanding_shares: int | None = None
    last_buy_price: Optional[float] = None
    last_sell_price: Optional[float] = None
    market_maker_quotes: list["MMQuoteSeed"] = field(default_factory=list)
    collar: Optional["CollarConfig"] = None  # populated by load_engine_config()
    circuit_breaker: Optional["CircuitBreakerConfig"] = (
        None  # populated by load_engine_config()
    )


@dataclass
class MMQuoteSeed:
    gateway_id: str
    bid_price: float
    ask_price: float
    bid_qty: int
    ask_qty: int
    tif: TIF = TIF.DAY
    quote_id: str | None = None
    seed_once: bool = (
        True  # if True, skip injection when book_stats already has an entry for this symbol
    )


@dataclass
class ComboSeedConfig:
    combo_id: str
    combo_type: ComboType = ComboType.AON
    tif: TIF = TIF.DAY
    legs: list[ComboLeg] = field(default_factory=list)


@dataclass
class IndexConfig:
    id: str
    description: str
    base_value: float = 1000.0
    publish_interval_sec: float = 1.0
    history_file: str = ""
    state_file: str = ""
    constituents: list[str] = field(default_factory=list)


@dataclass
class FixGatewayConfig:
    id: str
    description: str = ""
    role: ParticipantRole = ParticipantRole.TRADER
    disconnect_behaviour: DisconnectBehaviour = DisconnectBehaviour.CANCEL_QUOTES_ONLY
    quote_refresh_policy: QuoteRefreshPolicy = QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL
    enforce_mm_obligation: bool = False
    mm_max_spread_ticks: int = _DEFAULT_MM_MAX_SPREAD_TICKS
    mm_min_qty: int = _DEFAULT_MM_MIN_QTY
    # Per-symbol MM obligations — supersede the flat fields above when present.
    # Populated from the ``mm_obligations`` mapping in gateway config.
    mm_obligations: dict[str, MarketMakerObligation] = field(default_factory=dict)
    # Per-symbol MM enforcement policy used by quote checks.
    mm_obligation_policies: dict[str, MMObligationPolicy] = field(default_factory=dict)


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
    indices: list[IndexConfig] = field(default_factory=list)
    risk_control_levels: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=dict
    )
    default_risk_level: str | None = None
    global_mm_obligation_policy: MMObligationPolicy = field(
        default_factory=MMObligationPolicy
    )
    global_symbol_mm_obligation_policies: dict[str, MMObligationPolicy] = field(
        default_factory=dict
    )
    snapshot_interval_sec: float = _DEFAULT_SNAPSHOT_INTERVAL_SEC
    sessions_enabled: bool = False
    schedule: ScheduleConfig | None = None
    enforce_collars: bool = True
    enforce_circuit_breakers: bool = True

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
    alf_raw = gateways_raw.get("alf")
    if not isinstance(alf_raw, list):
        raise ValueError("Engine config must have a 'gateways.alf' list")

    cb_defaults_raw = raw.get("circuit_breaker_defaults")
    if cb_defaults_raw is not None and not isinstance(cb_defaults_raw, dict):
        raise ValueError("Engine config 'circuit_breaker_defaults' must be a mapping")

    mm_global_raw = raw.get("mm_obligation_defaults")
    mm_global_policy = MMObligationPolicy()
    mm_global_symbol_policies: dict[str, MMObligationPolicy] = {}
    if mm_global_raw is not None:
        if not isinstance(mm_global_raw, dict):
            raise ValueError("Engine config 'mm_obligation_defaults' must be a mapping")

        enforce_raw = mm_global_raw.get(
            "enforce_mm_obligation", mm_global_policy.enforce_mm_obligation
        )
        if not isinstance(enforce_raw, bool):
            raise ValueError(
                "Engine config 'mm_obligation_defaults.enforce_mm_obligation' must be a boolean"
            )
        mm_global_policy.enforce_mm_obligation = enforce_raw

        max_spread_raw = mm_global_raw.get(
            "mm_max_spread_ticks", mm_global_policy.mm_max_spread_ticks
        )
        min_qty_raw = mm_global_raw.get("mm_min_qty", mm_global_policy.mm_min_qty)
        try:
            mm_global_policy.mm_max_spread_ticks = int(max_spread_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Engine config 'mm_obligation_defaults.mm_max_spread_ticks' must be an integer"
            ) from exc
        try:
            mm_global_policy.mm_min_qty = int(min_qty_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Engine config 'mm_obligation_defaults.mm_min_qty' must be an integer"
            ) from exc
        if mm_global_policy.mm_max_spread_ticks <= 0:
            raise ValueError(
                "Engine config 'mm_obligation_defaults.mm_max_spread_ticks' must be > 0"
            )
        if mm_global_policy.mm_min_qty <= 0:
            raise ValueError(
                "Engine config 'mm_obligation_defaults.mm_min_qty' must be > 0"
            )

        mm_symbol_raw = mm_global_raw.get("symbols") or {}
        if not isinstance(mm_symbol_raw, dict):
            raise ValueError(
                "Engine config 'mm_obligation_defaults.symbols' must be a mapping"
            )
        for sym_raw, sym_cfg_raw in mm_symbol_raw.items():
            sym_name = str(sym_raw).upper()
            if not isinstance(sym_cfg_raw, dict):
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}' must be a mapping"
                )
            sym_enforce_raw = sym_cfg_raw.get(
                "enforce_mm_obligation", mm_global_policy.enforce_mm_obligation
            )
            if not isinstance(sym_enforce_raw, bool):
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}.enforce_mm_obligation' must be a boolean"
                )
            sym_max_raw = sym_cfg_raw.get(
                "mm_max_spread_ticks", mm_global_policy.mm_max_spread_ticks
            )
            sym_min_raw = sym_cfg_raw.get("mm_min_qty", mm_global_policy.mm_min_qty)
            try:
                sym_max = int(sym_max_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}.mm_max_spread_ticks' must be an integer"
                ) from exc
            try:
                sym_min = int(sym_min_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}.mm_min_qty' must be an integer"
                ) from exc
            if sym_max <= 0:
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}.mm_max_spread_ticks' must be > 0"
                )
            if sym_min <= 0:
                raise ValueError(
                    f"Engine config 'mm_obligation_defaults.symbols.{sym_name}.mm_min_qty' must be > 0"
                )
            mm_global_symbol_policies[sym_name] = MMObligationPolicy(
                enforce_mm_obligation=sym_enforce_raw,
                mm_max_spread_ticks=sym_max,
                mm_min_qty=sym_min,
            )

    risk_controls_raw = raw.get("risk_controls")
    risk_control_levels: dict[str, dict[str, Any]] = {}
    default_risk_level: str | None = None
    if risk_controls_raw is not None:
        if not isinstance(risk_controls_raw, dict):
            raise ValueError("Engine config 'risk_controls' must be a mapping")

        default_level_raw = risk_controls_raw.get("default_level")
        if default_level_raw is not None:
            if not isinstance(default_level_raw, str) or not default_level_raw.strip():
                raise ValueError(
                    "Engine config 'risk_controls.default_level' must be a non-empty string"
                )
            default_risk_level = default_level_raw.strip().upper()

        levels_raw = risk_controls_raw.get("levels") or {}
        if not isinstance(levels_raw, dict):
            raise ValueError("Engine config 'risk_controls.levels' must be a mapping")

        for level_name_raw, level_cfg_raw in levels_raw.items():
            level_name = str(level_name_raw).strip().upper()
            if not level_name:
                raise ValueError(
                    "Engine config 'risk_controls.levels' contains an empty level name"
                )
            if not isinstance(level_cfg_raw, dict):
                raise ValueError(
                    f"Engine config 'risk_controls.levels.{level_name}' must be a mapping"
                )

            level_collar_raw = level_cfg_raw.get("collar")
            if level_collar_raw is not None and not isinstance(level_collar_raw, dict):
                raise ValueError(
                    f"Engine config 'risk_controls.levels.{level_name}.collar' must be a mapping"
                )

            level_cb_raw = level_cfg_raw.get("circuit_breaker")
            if level_cb_raw is not None:
                raise ValueError(
                    f"Engine config 'risk_controls.levels.{level_name}.circuit_breaker' is no longer supported; use top-level 'circuit_breaker_defaults'"
                )

            risk_control_levels[level_name] = {
                "collar": dict(level_collar_raw or {}),
            }

        if (
            default_risk_level is not None
            and default_risk_level not in risk_control_levels
        ):
            raise ValueError(
                "Engine config 'risk_controls.default_level' must reference a key in 'risk_controls.levels'"
            )

    symbols: dict[str, SymbolConfig] = {}
    for sym, cfg in symbols_raw.items():
        sym = str(sym).upper()
        if cfg is None:
            cfg = {}
        if not isinstance(cfg, dict):
            raise ValueError(f"Config for symbol '{sym}' must be a mapping")

        level_raw = cfg.get("level")
        level: str | None
        if level_raw is not None:
            if not isinstance(level_raw, str) or not level_raw.strip():
                raise ValueError(f"Symbol '{sym}': level must be a non-empty string")
            level = level_raw.strip().upper()
        else:
            level = default_risk_level
        if level is not None and level not in risk_control_levels:
            raise ValueError(
                f"Symbol '{sym}': level '{level}' is not defined in risk_controls.levels"
            )
        level_cfg = risk_control_levels[level] if level is not None else {}

        lbp = cfg.get("last_buy_price")
        lsp = cfg.get("last_sell_price")
        tick_decimals = cfg.get("tick_decimals", 2)
        outstanding_shares_raw = cfg.get("outstanding_shares")
        mm_quotes_raw = cfg.get("market_maker_quotes") or []

        try:
            tick_decimals = int(tick_decimals)
        except (TypeError, ValueError):
            raise ValueError(f"Symbol '{sym}': tick_decimals must be an integer")
        if not (0 <= tick_decimals <= 8):
            raise ValueError(f"Symbol '{sym}': tick_decimals must be in range 0..8")

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
        outstanding_shares: int | None = None
        if outstanding_shares_raw is not None:
            try:
                outstanding_shares = int(outstanding_shares_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"Symbol '{sym}': outstanding_shares must be a positive integer"
                )
            if outstanding_shares <= 0:
                raise ValueError(f"Symbol '{sym}': outstanding_shares must be > 0")

        if not isinstance(mm_quotes_raw, list):
            raise ValueError(f"Symbol '{sym}': market_maker_quotes must be a list")

        mm_quotes: list[MMQuoteSeed] = []
        for i, quote_raw in enumerate(mm_quotes_raw):
            if not isinstance(quote_raw, dict):
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}] must be a mapping"
                )

            gateway_id_raw = quote_raw.get("gateway_id")
            if not isinstance(gateway_id_raw, str) or not gateway_id_raw.strip():
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}].gateway_id must be a non-empty string"
                )
            gateway_id = gateway_id_raw.strip().upper()

            try:
                bid_price = float(quote_raw["bid_price"])
                ask_price = float(quote_raw["ask_price"])
                bid_qty = int(quote_raw["bid_qty"])
                ask_qty = int(quote_raw["ask_qty"])
                tif = TIF(str(quote_raw.get("tif", TIF.DAY.value)).upper())
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}] is invalid"
                ) from exc

            quote_id_raw = quote_raw.get("quote_id")
            if quote_id_raw is not None and not isinstance(quote_id_raw, str):
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}].quote_id must be a string"
                )
            quote_id = quote_id_raw.strip() if isinstance(quote_id_raw, str) else None
            if quote_id == "":
                quote_id = None

            if bid_qty <= 0 or ask_qty <= 0:
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}] quantities must be positive"
                )
            if bid_price >= ask_price:
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}] requires bid_price < ask_price"
                )

            seed_once = bool(quote_raw.get("seed_once", True))

            mm_quotes.append(
                MMQuoteSeed(
                    gateway_id=gateway_id,
                    bid_price=bid_price,
                    ask_price=ask_price,
                    bid_qty=bid_qty,
                    ask_qty=ask_qty,
                    tif=tif,
                    quote_id=quote_id,
                    seed_once=seed_once,
                )
            )

        # --- Optional collar section -------------------------------------------
        collar_cfg: Optional["CollarConfig"] = None
        collar_raw = cfg.get("collar")
        if collar_raw is not None and not isinstance(collar_raw, dict):
            raise ValueError(f"Symbol '{sym}': collar must be a mapping")
        level_collar = level_cfg.get("collar")
        effective_collar_raw: dict[str, Any] | None = None
        if level_collar is not None or collar_raw is not None:
            effective_collar_raw = {}
            if isinstance(level_collar, dict):
                effective_collar_raw.update(level_collar)
            if isinstance(collar_raw, dict):
                effective_collar_raw.update(collar_raw)

        if effective_collar_raw is not None:
            from edumatcher.engine.collar import CollarConfig

            try:
                collar_cfg = CollarConfig(
                    symbol=sym,
                    reference_price=0,  # populated in Engine._load_config()
                    static_band_pct=float(
                        effective_collar_raw.get("static_band_pct", 0.20)
                    ),
                    dynamic_band_pct=float(
                        effective_collar_raw.get("dynamic_band_pct", 0.02)
                    ),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Symbol '{sym}': invalid collar configuration"
                ) from exc
            if not (0 < collar_cfg.static_band_pct < 1):
                raise ValueError(
                    f"Symbol '{sym}': collar.static_band_pct must be in (0, 1)"
                )
            if not (0 < collar_cfg.dynamic_band_pct < 1):
                raise ValueError(
                    f"Symbol '{sym}': collar.dynamic_band_pct must be in (0, 1)"
                )

        # --- Optional circuit_breaker section ---------------------------------
        cb_cfg: Optional["CircuitBreakerConfig"] = None
        cb_raw = cfg.get("circuit_breaker")
        if cb_raw is not None and not isinstance(cb_raw, dict):
            raise ValueError(f"Symbol '{sym}': circuit_breaker must be a mapping")

        effective_cb_raw: dict[str, Any] | None = None
        if cb_defaults_raw is not None or cb_raw is not None:
            effective_cb_raw = {}
            if isinstance(cb_defaults_raw, dict):
                effective_cb_raw.update(cb_defaults_raw)
            if isinstance(cb_raw, dict):
                for key, value in cb_raw.items():
                    if key != "levels":
                        effective_cb_raw[key] = value

            merged_levels: dict[str, dict[str, Any]] = {}
            defaults_levels = (
                cb_defaults_raw.get("levels")
                if isinstance(cb_defaults_raw, dict)
                else None
            )
            if defaults_levels is not None:
                if not isinstance(defaults_levels, dict):
                    raise ValueError(
                        "Engine config 'circuit_breaker_defaults.levels' must be a mapping"
                    )
                for lvl_name, lvl_cfg in defaults_levels.items():
                    if not isinstance(lvl_cfg, dict):
                        raise ValueError(
                            "Engine config 'circuit_breaker_defaults.levels' values must be mappings"
                        )
                    merged_levels[str(lvl_name).upper()] = dict(lvl_cfg)

            symbol_levels = cb_raw.get("levels") if isinstance(cb_raw, dict) else None
            if symbol_levels is not None:
                if not isinstance(symbol_levels, dict):
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels must be a mapping"
                    )
                for lvl_name, lvl_cfg in symbol_levels.items():
                    if not isinstance(lvl_cfg, dict):
                        raise ValueError(
                            f"Symbol '{sym}': circuit_breaker.levels.{lvl_name} must be a mapping"
                        )
                    key = str(lvl_name).upper()
                    merged = dict(merged_levels.get(key, {}))
                    merged.update(lvl_cfg)
                    merged_levels[key] = merged

            if not merged_levels:
                merged_levels = {k: dict(v) for k, v in _DEFAULT_CB_LEVELS.items()}
            effective_cb_raw["levels"] = merged_levels

        if effective_cb_raw is not None:
            from edumatcher.engine.circuit_breaker import (
                CircuitBreakerConfig,
                CircuitBreakerLevel,
            )

            levels_raw = effective_cb_raw.get("levels")
            if not isinstance(levels_raw, dict) or not levels_raw:
                raise ValueError(
                    f"Symbol '{sym}': circuit_breaker.levels must be a non-empty mapping"
                )

            levels: list[CircuitBreakerLevel] = []
            for level_name_raw, level_cfg_raw in levels_raw.items():
                level_name = str(level_name_raw).upper()
                if not isinstance(level_cfg_raw, dict):
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels.{level_name} must be a mapping"
                    )
                if "price_shift_pct" not in level_cfg_raw:
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels.{level_name}.price_shift_pct is required"
                    )
                try:
                    price_shift_pct = float(level_cfg_raw["price_shift_pct"])
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels.{level_name}.price_shift_pct must be numeric"
                    ) from exc
                if not (0 < price_shift_pct < 1):
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels.{level_name}.price_shift_pct must be in (0, 1)"
                    )

                halt_duration_raw = level_cfg_raw.get("halt_duration_ns")
                if halt_duration_raw is None:
                    halt_duration_ns: int | None = None
                else:
                    try:
                        halt_duration_ns = int(halt_duration_raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"Symbol '{sym}': circuit_breaker.levels.{level_name}.halt_duration_ns must be an integer or null"
                        ) from exc
                    if halt_duration_ns <= 0:
                        raise ValueError(
                            f"Symbol '{sym}': circuit_breaker.levels.{level_name}.halt_duration_ns must be > 0 when provided"
                        )

                resumption_mode = str(
                    level_cfg_raw.get("resumption_mode", "AUCTION")
                ).upper()
                if resumption_mode not in ("AUCTION", "CONTINUOUS"):
                    raise ValueError(
                        f"Symbol '{sym}': circuit_breaker.levels.{level_name}.resumption_mode must be AUCTION or CONTINUOUS"
                    )

                levels.append(
                    CircuitBreakerLevel(
                        name=level_name,
                        price_shift_pct=price_shift_pct,
                        halt_duration_ns=halt_duration_ns,
                        resumption_mode=resumption_mode,
                    )
                )

            try:
                cb_cfg = CircuitBreakerConfig(
                    symbol=sym,
                    reference_window_ns=int(
                        effective_cb_raw.get("reference_window_ns", 300_000_000_000)
                    ),
                    levels=sorted(levels, key=lambda lvl: lvl.price_shift_pct),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Symbol '{sym}': invalid circuit_breaker configuration"
                ) from exc

        symbols[sym] = SymbolConfig(
            name=sym,
            level=level,
            tick_decimals=tick_decimals,
            outstanding_shares=outstanding_shares,
            last_buy_price=lbp,
            last_sell_price=lsp,
            market_maker_quotes=mm_quotes,
            collar=collar_cfg,
            circuit_breaker=cb_cfg,
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

    indices_raw = raw.get("indices") or []
    if not isinstance(indices_raw, list):
        raise ValueError("Engine config 'indices' must be a list")
    if len(indices_raw) > 5:
        raise ValueError("Engine config supports at most 5 indices")

    indices: list[IndexConfig] = []
    seen_index_ids: set[str] = set()
    for i, idx_raw in enumerate(indices_raw):
        if not isinstance(idx_raw, dict):
            raise ValueError(f"indices[{i}] must be a mapping")

        idx_id_raw = idx_raw.get("id")
        if not isinstance(idx_id_raw, str) or not idx_id_raw.strip():
            raise ValueError(f"indices[{i}].id must be a non-empty string")
        idx_id = idx_id_raw.strip().upper()
        if not idx_id.isalnum():
            raise ValueError(f"indices[{i}].id must be alphanumeric")
        if idx_id in seen_index_ids:
            raise ValueError(f"Duplicate index id in indices: {idx_id}")
        seen_index_ids.add(idx_id)

        desc_raw = idx_raw.get("description")
        if not isinstance(desc_raw, str) or not desc_raw.strip():
            raise ValueError(f"indices[{i}].description must be a non-empty string")
        description = desc_raw.strip()

        try:
            base_value = float(idx_raw.get("base_value", 1000.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"indices[{i}].base_value must be numeric") from exc
        if base_value <= 0.0:
            raise ValueError(f"indices[{i}].base_value must be > 0")

        try:
            publish_interval_sec = float(idx_raw.get("publish_interval_sec", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"indices[{i}].publish_interval_sec must be numeric"
            ) from exc
        if publish_interval_sec <= 0.0:
            raise ValueError(f"indices[{i}].publish_interval_sec must be > 0")

        history_file_raw = idx_raw.get(
            "history_file", f"data/indexes/{idx_id}_history.jsonl"
        )
        state_file_raw = idx_raw.get("state_file", f"data/indexes/{idx_id}_state.json")
        if not isinstance(history_file_raw, str) or not history_file_raw.strip():
            raise ValueError(f"indices[{i}].history_file must be a non-empty string")
        if not isinstance(state_file_raw, str) or not state_file_raw.strip():
            raise ValueError(f"indices[{i}].state_file must be a non-empty string")

        constituents_raw = idx_raw.get("constituents")
        if not isinstance(constituents_raw, list) or not constituents_raw:
            raise ValueError(f"indices[{i}].constituents must be a non-empty list")

        constituents: list[str] = []
        seen_constituents: set[str] = set()
        for sym_raw in constituents_raw:
            sym = str(sym_raw).upper()
            if sym in seen_constituents:
                raise ValueError(
                    f"indices[{i}].constituents contains duplicate symbol '{sym}'"
                )
            if sym not in symbols:
                raise ValueError(
                    f"indices[{i}] references unknown constituent symbol '{sym}'"
                )
            if symbols[sym].outstanding_shares is None:
                raise ValueError(
                    f"indices[{i}] constituent '{sym}' requires symbols.{sym}.outstanding_shares"
                )
            seen_constituents.add(sym)
            constituents.append(sym)

        indices.append(
            IndexConfig(
                id=idx_id,
                description=description,
                base_value=base_value,
                publish_interval_sec=publish_interval_sec,
                history_file=history_file_raw.strip(),
                state_file=state_file_raw.strip(),
                constituents=constituents,
            )
        )

    fix_gateways: dict[str, FixGatewayConfig] = {}
    for i, item in enumerate(alf_raw):
        if not isinstance(item, dict):
            raise ValueError(f"gateways.alf[{i}] must be a mapping")
        gw_id_raw = item.get("id")
        if not isinstance(gw_id_raw, str) or not gw_id_raw.strip():
            raise ValueError(f"gateways.alf[{i}].id must be a non-empty string")
        gw_id = gw_id_raw.strip().upper()
        desc = item.get("description", "")
        if desc is None:
            desc = ""
        if not isinstance(desc, str):
            raise ValueError(f"gateways.alf[{i}].description must be a string")

        role_raw = str(item.get("role", ParticipantRole.TRADER.value)).upper()
        disconnect_raw = str(
            item.get(
                "disconnect_behaviour",
                DisconnectBehaviour.CANCEL_QUOTES_ONLY.value,
            )
        ).upper()
        refresh_raw = str(
            item.get(
                "quote_refresh_policy",
                QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL.value,
            )
        ).upper()
        enforce_mm_obligation = item.get(
            "enforce_mm_obligation", mm_global_policy.enforce_mm_obligation
        )
        if not isinstance(enforce_mm_obligation, bool):
            raise ValueError(
                f"gateways.alf[{i}].enforce_mm_obligation must be a boolean"
            )

        mm_max_spread_ticks_raw = item.get(
            "mm_max_spread_ticks", mm_global_policy.mm_max_spread_ticks
        )
        mm_min_qty_raw = item.get("mm_min_qty", mm_global_policy.mm_min_qty)
        try:
            mm_max_spread_ticks = int(mm_max_spread_ticks_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"gateways.alf[{i}].mm_max_spread_ticks must be an integer"
            ) from exc
        try:
            mm_min_qty = int(mm_min_qty_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"gateways.alf[{i}].mm_min_qty must be an integer"
            ) from exc
        if mm_max_spread_ticks <= 0:
            raise ValueError(f"gateways.alf[{i}].mm_max_spread_ticks must be > 0")
        if mm_min_qty <= 0:
            raise ValueError(f"gateways.alf[{i}].mm_min_qty must be > 0")

        try:
            role = ParticipantRole(role_raw)
        except ValueError as exc:
            raise ValueError(f"gateways.alf[{i}].role is invalid") from exc

        try:
            disconnect_behaviour = DisconnectBehaviour(disconnect_raw)
        except ValueError as exc:
            raise ValueError(
                f"gateways.alf[{i}].disconnect_behaviour is invalid"
            ) from exc

        try:
            quote_refresh_policy = QuoteRefreshPolicy(refresh_raw)
        except ValueError as exc:
            raise ValueError(
                f"gateways.alf[{i}].quote_refresh_policy is invalid"
            ) from exc

        # --- Optional per-symbol mm_obligations mapping -----------------------
        mm_obligations: dict[str, MarketMakerObligation] = {}
        mm_obligation_policies: dict[str, MMObligationPolicy] = {}
        mm_obligations_raw = item.get("mm_obligations") or {}
        if not isinstance(mm_obligations_raw, dict):
            raise ValueError(f"gateways.alf[{i}].mm_obligations must be a mapping")
        for obl_sym, obl_raw in mm_obligations_raw.items():
            obl_sym = str(obl_sym).upper()
            if not isinstance(obl_raw, dict):
                raise ValueError(
                    f"gateways.alf[{i}].mm_obligations.{obl_sym} must be a mapping"
                )
            obl_enforce_raw = obl_raw.get(
                "enforce_mm_obligation", enforce_mm_obligation
            )
            if not isinstance(obl_enforce_raw, bool):
                raise ValueError(
                    f"gateways.alf[{i}].mm_obligations.{obl_sym}.enforce_mm_obligation must be a boolean"
                )
            obl_max_raw = obl_raw.get("max_spread_ticks", mm_max_spread_ticks)
            obl_min_raw = obl_raw.get("min_qty", mm_min_qty)
            try:
                mm_obligations[obl_sym] = MarketMakerObligation(
                    gateway_id=gw_id,
                    symbol=obl_sym,
                    max_spread_ticks=int(obl_max_raw),
                    min_qty=int(obl_min_raw),
                )
                mm_obligation_policies[obl_sym] = MMObligationPolicy(
                    enforce_mm_obligation=obl_enforce_raw,
                    mm_max_spread_ticks=int(obl_max_raw),
                    mm_min_qty=int(obl_min_raw),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"gateways.alf[{i}].mm_obligations.{obl_sym} is invalid"
                ) from exc

        if gw_id in fix_gateways:
            raise ValueError(f"Duplicate gateway id in gateways.alf: {gw_id}")
        fix_gateways[gw_id] = FixGatewayConfig(
            id=gw_id,
            description=desc,
            role=role,
            disconnect_behaviour=disconnect_behaviour,
            quote_refresh_policy=quote_refresh_policy,
            enforce_mm_obligation=enforce_mm_obligation,
            mm_max_spread_ticks=mm_max_spread_ticks,
            mm_min_qty=mm_min_qty,
            mm_obligations=mm_obligations,
            mm_obligation_policies=mm_obligation_policies,
        )

    if not fix_gateways:
        raise ValueError("Engine config must define at least one gateways.alf entry")

    mm_gateway_ids = {
        gw_id
        for gw_id, gw_cfg in fix_gateways.items()
        if gw_cfg.role == ParticipantRole.MARKET_MAKER
    }
    for sym in mm_global_symbol_policies:
        if sym not in symbols:
            raise ValueError(
                f"Engine config 'mm_obligation_defaults.symbols.{sym}' references unknown symbol"
            )

    for sym, sym_cfg in symbols.items():
        if mm_gateway_ids and not sym_cfg.market_maker_quotes:
            raise ValueError(
                f"Symbol '{sym}': at least one market_maker_quotes entry is required when MARKET_MAKER gateways are configured"
            )
        for i, quote_seed in enumerate(sym_cfg.market_maker_quotes):
            if quote_seed.gateway_id not in fix_gateways:
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}].gateway_id references unknown gateway '{quote_seed.gateway_id}'"
                )
            if quote_seed.gateway_id not in mm_gateway_ids:
                raise ValueError(
                    f"Symbol '{sym}': market_maker_quotes[{i}].gateway_id must reference a MARKET_MAKER gateway"
                )

    sessions_enabled_raw = raw.get("sessions_enabled", True)
    if not isinstance(sessions_enabled_raw, bool):
        raise ValueError("Engine config 'sessions_enabled' must be a boolean")

    snapshot_interval_raw = raw.get(
        "snapshot_interval_sec", _DEFAULT_SNAPSHOT_INTERVAL_SEC
    )
    try:
        snapshot_interval_sec = float(snapshot_interval_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Engine config 'snapshot_interval_sec' must be numeric"
        ) from exc
    if snapshot_interval_sec <= 0:
        raise ValueError("Engine config 'snapshot_interval_sec' must be > 0")

    enforce_collars_raw = raw.get("enforce_collars", True)
    if not isinstance(enforce_collars_raw, bool):
        raise ValueError("Engine config 'enforce_collars' must be a boolean")

    enforce_cb_raw = raw.get("enforce_circuit_breakers", True)
    if not isinstance(enforce_cb_raw, bool):
        raise ValueError("Engine config 'enforce_circuit_breakers' must be a boolean")

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
        indices=indices,
        risk_control_levels=risk_control_levels,
        default_risk_level=default_risk_level,
        global_mm_obligation_policy=mm_global_policy,
        global_symbol_mm_obligation_policies=mm_global_symbol_policies,
        snapshot_interval_sec=snapshot_interval_sec,
        sessions_enabled=sessions_enabled_raw,
        schedule=schedule_cfg,
        enforce_collars=enforce_collars_raw,
        enforce_circuit_breakers=enforce_cb_raw,
    )
