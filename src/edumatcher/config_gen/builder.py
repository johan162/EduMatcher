"""Build the config mapping emitted by pm-config-gen."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
import random
import string
from typing import Any

from edumatcher.models.participant import ParticipantRole

from .cb_spec import CbSpec
from .defaults import (
    DEFAULT_API_GATEWAY_ENGINE_AUTH_SEC,
    DEFAULT_API_GATEWAY_ENGINE_REPLY_SEC,
    DEFAULT_API_GATEWAY_HOST,
    DEFAULT_API_GATEWAY_KEY_BYTES,
    DEFAULT_API_GATEWAY_LOG_LEVEL,
    DEFAULT_API_GATEWAY_PORT,
    DEFAULT_API_GATEWAY_RATE_LIMIT_BURST,
    DEFAULT_API_GATEWAY_RATE_LIMIT_WRITES_PER_SECOND,
    DEFAULT_API_GATEWAY_STATS_DB,
    DEFAULT_API_GATEWAY_SWAGGER_ENABLED,
    DEFAULT_API_GATEWAY_WAIT_ACK_SEC,
    DEFAULT_BALF_GATEWAY_AUTH_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_BIND_ADDRESS,
    DEFAULT_BALF_GATEWAY_DUPLICATE_SESSION_POLICY,
    DEFAULT_BALF_GATEWAY_ERROR_WINDOW_SEC,
    DEFAULT_BALF_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_BALF_GATEWAY_HEARTBEAT_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_BALF_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_BALF_GATEWAY_MAX_CONNECTIONS,
    DEFAULT_BALF_GATEWAY_MAX_ERRORS_BEFORE_DISCONNECT,
    DEFAULT_BALF_GATEWAY_MAX_MESSAGES_PER_SECOND,
    DEFAULT_BALF_GATEWAY_NAME,
    DEFAULT_BALF_GATEWAY_PORT,
    DEFAULT_INDEX_BASE_VALUE,
    DEFAULT_INDEX_DATA_DIR,
    DEFAULT_INDEX_PUBLISH_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_BIND_ADDRESS,
    DEFAULT_MARKET_DATA_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_MARKET_DATA_GATEWAY_MAX_SYMBOLS_PER_CLIENT,
    DEFAULT_MARKET_DATA_GATEWAY_NAME,
    DEFAULT_MARKET_DATA_GATEWAY_PORT,
    DEFAULT_MARKET_DATA_GATEWAY_REPLAY_WINDOW_SEC,
    DEFAULT_CB_WINDOW_NS,
    DEFAULT_DYNAMIC_BAND_PCT,
    DEFAULT_MM_MIN_QTY,
    DEFAULT_MM_SPREAD_TICKS,
    DEFAULT_MM_STUB_QTY,
    DEFAULT_POST_TRADE_GATEWAY_ALLOWED_ROLES,
    DEFAULT_POST_TRADE_GATEWAY_BIND_ADDRESS,
    DEFAULT_POST_TRADE_GATEWAY_HEARTBEAT_INTERVAL_SEC,
    DEFAULT_POST_TRADE_GATEWAY_IDLE_TIMEOUT_SEC,
    DEFAULT_POST_TRADE_GATEWAY_MAX_CLIENT_QUEUE,
    DEFAULT_POST_TRADE_GATEWAY_NAME,
    DEFAULT_POST_TRADE_GATEWAY_PORT,
    DEFAULT_POST_TRADE_GATEWAY_REPLAY_RETENTION_SEC,
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
    random_seed: int | None = None
    seed_mm_mid_range: tuple[float, float] | None = None
    seed_last_prices_from_mm: bool = False
    emit_schedule: bool = True
    pre_open: str = "09:00"
    opening_auction: str = "09:25"
    continuous: str = "09:30"
    closing_auction: str = "16:00"
    closing_end: str = "16:05"
    symbol_overrides: dict[str, SymbolOverride] = field(default_factory=dict)
    outstanding_shares: dict[str, int] = field(default_factory=dict)
    post_trade_gateway: PostTradeGatewaySpec | None = None
    market_data_gateway: MarketDataGatewaySpec | None = None
    balf_gateway: BalfGatewaySpec | None = None
    api_gateways: tuple[ApiGatewaySpec, ...] = ()
    indices: tuple[IndexSpec, ...] = ()
    combos: list[ComboSpec] = field(default_factory=list)


@dataclass(frozen=True)
class PostTradeGatewaySpec:
    name: str = DEFAULT_POST_TRADE_GATEWAY_NAME
    bind_address: str = DEFAULT_POST_TRADE_GATEWAY_BIND_ADDRESS
    port: int = DEFAULT_POST_TRADE_GATEWAY_PORT
    replay_retention_sec: int = DEFAULT_POST_TRADE_GATEWAY_REPLAY_RETENTION_SEC
    heartbeat_interval_sec: int = DEFAULT_POST_TRADE_GATEWAY_HEARTBEAT_INTERVAL_SEC
    idle_timeout_sec: int = DEFAULT_POST_TRADE_GATEWAY_IDLE_TIMEOUT_SEC
    max_client_queue: int = DEFAULT_POST_TRADE_GATEWAY_MAX_CLIENT_QUEUE
    allowed_roles: tuple[str, ...] = DEFAULT_POST_TRADE_GATEWAY_ALLOWED_ROLES


@dataclass(frozen=True)
class MarketDataGatewaySpec:
    enabled: bool = True
    name: str = DEFAULT_MARKET_DATA_GATEWAY_NAME
    bind_address: str = DEFAULT_MARKET_DATA_GATEWAY_BIND_ADDRESS
    port: int = DEFAULT_MARKET_DATA_GATEWAY_PORT
    heartbeat_interval_sec: int = DEFAULT_MARKET_DATA_GATEWAY_HEARTBEAT_INTERVAL_SEC
    idle_timeout_sec: int = DEFAULT_MARKET_DATA_GATEWAY_IDLE_TIMEOUT_SEC
    replay_window_sec: int = DEFAULT_MARKET_DATA_GATEWAY_REPLAY_WINDOW_SEC
    max_symbols_per_client: int = DEFAULT_MARKET_DATA_GATEWAY_MAX_SYMBOLS_PER_CLIENT
    max_client_queue: int = DEFAULT_MARKET_DATA_GATEWAY_MAX_CLIENT_QUEUE


@dataclass(frozen=True)
class BalfGatewaySpec:
    name: str = DEFAULT_BALF_GATEWAY_NAME
    bind_address: str = DEFAULT_BALF_GATEWAY_BIND_ADDRESS
    port: int = DEFAULT_BALF_GATEWAY_PORT
    heartbeat_interval_sec: int = DEFAULT_BALF_GATEWAY_HEARTBEAT_INTERVAL_SEC
    heartbeat_timeout_sec: int = DEFAULT_BALF_GATEWAY_HEARTBEAT_TIMEOUT_SEC
    idle_timeout_sec: int = DEFAULT_BALF_GATEWAY_IDLE_TIMEOUT_SEC
    auth_timeout_sec: int = DEFAULT_BALF_GATEWAY_AUTH_TIMEOUT_SEC
    max_connections: int = DEFAULT_BALF_GATEWAY_MAX_CONNECTIONS
    max_client_queue: int = DEFAULT_BALF_GATEWAY_MAX_CLIENT_QUEUE
    max_messages_per_second: int = DEFAULT_BALF_GATEWAY_MAX_MESSAGES_PER_SECOND
    max_errors_before_disconnect: int = (
        DEFAULT_BALF_GATEWAY_MAX_ERRORS_BEFORE_DISCONNECT
    )
    error_window_sec: int = DEFAULT_BALF_GATEWAY_ERROR_WINDOW_SEC
    duplicate_session_policy: str = DEFAULT_BALF_GATEWAY_DUPLICATE_SESSION_POLICY


@dataclass(frozen=True)
class ApiCredentialSpec:
    api_key: str
    gateway_id: str | None
    description: str = ""


@dataclass(frozen=True)
class IndexSpec:
    id: str
    description: str
    constituents: tuple[str, ...]
    base_value: float = DEFAULT_INDEX_BASE_VALUE
    publish_interval_sec: float = DEFAULT_INDEX_PUBLISH_INTERVAL_SEC
    history_file: str = ""  # empty → derived from id
    state_file: str = ""  # empty → derived from id


@dataclass(frozen=True)
class ComboLegSpec:
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: int | None = None
    stop_price: int | None = None
    smp_action: str = "NONE"


@dataclass(frozen=True)
class ComboSpec:
    combo_id: str
    combo_type: str = "AON"
    tif: str = "DAY"
    legs: tuple[ComboLegSpec, ...] = ()


@dataclass(frozen=True)
class ApiGatewaySpec:
    name: str = "default"
    enabled: bool = True
    host: str = DEFAULT_API_GATEWAY_HOST
    port: int = DEFAULT_API_GATEWAY_PORT
    swagger_enabled: bool = DEFAULT_API_GATEWAY_SWAGGER_ENABLED
    log_level: str = DEFAULT_API_GATEWAY_LOG_LEVEL
    stats_db: str = DEFAULT_API_GATEWAY_STATS_DB
    credentials: tuple[ApiCredentialSpec, ...] = ()
    gateway_ids: tuple[str, ...] = ()
    generate_keys: bool = True
    generate_readonly_key: bool = False
    rate_limit_writes_per_second: int = DEFAULT_API_GATEWAY_RATE_LIMIT_WRITES_PER_SECOND
    rate_limit_burst: int = DEFAULT_API_GATEWAY_RATE_LIMIT_BURST
    engine_auth_sec: float = DEFAULT_API_GATEWAY_ENGINE_AUTH_SEC
    engine_reply_sec: float = DEFAULT_API_GATEWAY_ENGINE_REPLY_SEC
    wait_ack_sec: float = DEFAULT_API_GATEWAY_WAIT_ACK_SEC


class ConfigBuilder:
    def __init__(self, spec: ConfigSpec):
        self.spec = spec
        self._rng = random.Random(spec.random_seed)

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
        if self.spec.post_trade_gateway is not None:
            cfg["post_trade_gateway"] = self._build_post_trade_gateway()
        if self.spec.market_data_gateway is not None:
            cfg["market_data_gateway"] = self._build_market_data_gateway()
        if self.spec.balf_gateway is not None:
            cfg["balf_gateway"] = self._build_balf_gateway()
        if self.spec.api_gateways:
            cfg["api_gateways"] = self._build_api_gateways()
        cfg["symbols"] = self._build_symbols()

        if self.spec.combos:
            cfg["market_maker_combos"] = self._build_combos()

        if self.spec.indices:
            cfg["indices"] = self._build_indices()

        if self.spec.sessions_enabled and self.spec.emit_schedule:
            cfg["schedule"] = {
                "pre_open": self.spec.pre_open,
                "opening_auction_start": self.spec.opening_auction,
                "continuous_start": self.spec.continuous,
                "closing_auction_start": self.spec.closing_auction,
                "closing_auction_end": self.spec.closing_end,
            }

        return cfg

    def _build_post_trade_gateway(self) -> dict[str, Any]:
        spec = self.spec.post_trade_gateway
        if spec is None:
            return {}

        return {
            "name": spec.name,
            "bind_address": spec.bind_address,
            "port": spec.port,
            "replay_retention_sec": spec.replay_retention_sec,
            "heartbeat_interval_sec": spec.heartbeat_interval_sec,
            "idle_timeout_sec": spec.idle_timeout_sec,
            "max_client_queue": spec.max_client_queue,
            "allowed_roles": list(spec.allowed_roles),
        }

    def _build_market_data_gateway(self) -> dict[str, Any]:
        spec = self.spec.market_data_gateway
        if spec is None:
            return {}

        return {
            "enabled": spec.enabled,
            "name": spec.name,
            "bind_address": spec.bind_address,
            "port": spec.port,
            "heartbeat_interval_sec": spec.heartbeat_interval_sec,
            "idle_timeout_sec": spec.idle_timeout_sec,
            "replay_window_sec": spec.replay_window_sec,
            "max_symbols_per_client": spec.max_symbols_per_client,
            "max_client_queue": spec.max_client_queue,
        }

    def _build_balf_gateway(self) -> dict[str, Any]:
        spec = self.spec.balf_gateway
        if spec is None:
            return {}

        return {
            "name": spec.name,
            "bind_address": spec.bind_address,
            "port": spec.port,
            "heartbeat_interval_sec": spec.heartbeat_interval_sec,
            "heartbeat_timeout_sec": spec.heartbeat_timeout_sec,
            "idle_timeout_sec": spec.idle_timeout_sec,
            "auth_timeout_sec": spec.auth_timeout_sec,
            "max_connections": spec.max_connections,
            "max_client_queue": spec.max_client_queue,
            "max_messages_per_second": spec.max_messages_per_second,
            "max_errors_before_disconnect": spec.max_errors_before_disconnect,
            "error_window_sec": spec.error_window_sec,
            "duplicate_session_policy": spec.duplicate_session_policy,
        }

    def _build_api_gateways(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        gateway_owners: dict[str, str] = {}
        for spec in self.spec.api_gateways:
            for credential in self._effective_api_credentials(spec):
                if credential.gateway_id is None:
                    continue
                existing = gateway_owners.get(credential.gateway_id)
                if existing is not None and existing != spec.name:
                    raise ValueError(
                        f"gateway_id {credential.gateway_id!r} is used by multiple "
                        f"api_gateways entries: {existing!r} and {spec.name!r}"
                    )
                gateway_owners[credential.gateway_id] = spec.name
            payload[spec.name] = self._build_api_gateway(spec)
        return payload

    def _build_api_gateway(self, spec: ApiGatewaySpec) -> dict[str, Any]:
        return {
            "enabled": spec.enabled,
            "host": spec.host,
            "port": spec.port,
            "swagger_enabled": spec.swagger_enabled,
            "log_level": spec.log_level,
            "stats_db": spec.stats_db,
            "credentials": [
                {
                    "api_key": item.api_key,
                    "gateway_id": item.gateway_id,
                    "description": item.description,
                }
                for item in self._effective_api_credentials(spec)
            ],
            "rate_limit": {
                "writes_per_second": spec.rate_limit_writes_per_second,
                "burst": spec.rate_limit_burst,
            },
            "timeouts": {
                "engine_auth_sec": spec.engine_auth_sec,
                "engine_reply_sec": spec.engine_reply_sec,
                "wait_ack_sec": spec.wait_ack_sec,
            },
        }

    def _effective_api_credentials(
        self, spec: ApiGatewaySpec
    ) -> list[ApiCredentialSpec]:
        credentials = list(spec.credentials)
        explicit_gateway_ids = {item.gateway_id for item in credentials}
        included_gateway_ids = set(spec.gateway_ids)

        if spec.generate_keys:
            for gateway in self.spec.gateways:
                if (
                    included_gateway_ids
                    and gateway.gateway_id not in included_gateway_ids
                ):
                    continue
                if gateway.gateway_id in explicit_gateway_ids:
                    continue
                credentials.append(
                    ApiCredentialSpec(
                        api_key=self._generated_api_key(gateway.gateway_id),
                        gateway_id=gateway.gateway_id,
                        description=f"Generated key for {gateway.gateway_id}",
                    )
                )
        if spec.generate_readonly_key and None not in explicit_gateway_ids:
            credentials.append(
                ApiCredentialSpec(
                    api_key=self._generated_api_key("readonly"),
                    gateway_id=None,
                    description="Generated read-only market-data key",
                )
            )

        return credentials

    def _generated_api_key(self, label: str) -> str:
        alphabet = string.ascii_lowercase + string.digits
        rng = (
            random.Random(f"api:{self.spec.random_seed}:{label}")
            if self.spec.random_seed is not None
            else self._rng
        )
        token = "".join(
            rng.choice(alphabet) for _ in range(DEFAULT_API_GATEWAY_KEY_BYTES * 2)
        )
        return f"key-{label.lower()}-{token}"

    def _should_emit_mm_defaults(self) -> bool:
        if self.spec.emit_mm_defaults:
            return True
        for override in self.spec.symbol_overrides.values():
            if (
                override.mm_spread_ticks is not None
                or override.mm_min_qty is not None
                or override.enforce_mm_obligation is not None
            ):
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
            if (
                override.mm_spread_ticks is None
                and override.mm_min_qty is None
                and override.enforce_mm_obligation is None
            ):
                continue
            symbol_enforce = (
                override.enforce_mm_obligation
                if override.enforce_mm_obligation is not None
                else self.spec.enforce_mm_obligations
            )
            symbol_overrides[symbol] = {
                "enforce_mm_obligation": symbol_enforce,
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
                "resumption_mode": level.resumption_mode,
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
            if gw.description:
                payload["description"] = gw.description
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

            seeded_midpoint = self._seeded_midpoint(self.spec.tick_decimals)

            if self.spec.seed_last_prices_from_mm and seeded_midpoint is not None:
                midpoint = float(seeded_midpoint)
                payload["last_buy_price"] = midpoint
                payload["last_sell_price"] = midpoint
            elif self.spec.seed_last_prices:
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
                set(override.cb_shift) | set(override.cb_halt_mins) | set(override.cb_resumption_mode)
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
                if level_name in override.cb_resumption_mode:
                    level_payload["resumption_mode"] = override.cb_resumption_mode[level_name]
                cb_levels[level_name] = level_payload
            if cb_levels:
                payload["circuit_breaker"] = {"levels": cb_levels}

            if mm_gateways:
                payload["market_maker_quotes"] = [
                    self._build_mm_quote_seed(
                        gateway_id=gateway_id,
                        tick_decimals=self.spec.tick_decimals,
                        seeded_midpoint=seeded_midpoint,
                    )
                    for gateway_id in mm_gateways
                ]

            outstanding = self.spec.outstanding_shares.get(symbol)
            if outstanding is not None:
                payload["outstanding_shares"] = outstanding

            symbols[symbol] = payload

        return symbols

    def _build_indices(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec in self.spec.indices:
            history_file = (
                spec.history_file or f"{DEFAULT_INDEX_DATA_DIR}/{spec.id}_history.jsonl"
            )
            state_file = (
                spec.state_file or f"{DEFAULT_INDEX_DATA_DIR}/{spec.id}_state.json"
            )
            result.append(
                {
                    "id": spec.id,
                    "description": spec.description,
                    "base_value": spec.base_value,
                    "publish_interval_sec": spec.publish_interval_sec,
                    "history_file": history_file,
                    "state_file": state_file,
                    "constituents": list(spec.constituents),
                }
            )
        return result

    def _seeded_midpoint(self, tick_decimals: int) -> Decimal | None:
        if self.spec.seed_mm_mid_range is None:
            return None

        min_price, max_price = self.spec.seed_mm_mid_range
        tick_size = Decimal(1).scaleb(-tick_decimals)
        min_steps = int(
            (Decimal(str(min_price)) / tick_size).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        max_steps = int(
            (Decimal(str(max_price)) / tick_size).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        midpoint_steps = self._rng.randint(min_steps, max_steps)
        return Decimal(midpoint_steps) * tick_size

    def _build_mm_quote_seed(
        self,
        gateway_id: str,
        tick_decimals: int,
        seeded_midpoint: Decimal | None,
    ) -> dict[str, Any]:
        if seeded_midpoint is None:
            bid_price: float | None = None
            ask_price: float | None = None
        else:
            tick_size = Decimal(1).scaleb(-tick_decimals)
            bid_price = float(seeded_midpoint - tick_size)
            ask_price = float(seeded_midpoint + tick_size)

        return {
            "gateway_id": gateway_id,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_qty": DEFAULT_MM_STUB_QTY,
            "ask_qty": DEFAULT_MM_STUB_QTY,
            "tif": "DAY",
            "seed_once": True,
        }

    def _build_combos(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for combo in self.spec.combos:
            result.append(
                {
                    "combo_id": combo.combo_id,
                    "combo_type": combo.combo_type,
                    "tif": combo.tif,
                    "legs": [
                        {
                            "symbol": leg.symbol,
                            "side": leg.side,
                            "order_type": leg.order_type,
                            "quantity": leg.quantity,
                            "price": leg.price,
                            "stop_price": leg.stop_price,
                            "smp_action": leg.smp_action,
                        }
                        for leg in combo.legs
                    ],
                }
            )
        return result
