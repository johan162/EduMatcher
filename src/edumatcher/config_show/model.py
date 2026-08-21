"""Read-only view model.

``extract`` builds these from a raw YAML mapping; every renderer consumes
only these.  Doing the interesting computations once -- an effective port and
where it came from, which risk level a symbol actually inherits -- is what
keeps the terminal and PDF renderers from drifting apart, and it makes the
whole thing testable without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Listener:
    """One socket some process binds when the exchange comes up."""

    port: int
    proto: str  # "ZMQ PULL" | "ZMQ PUB" | "TCP" | "HTTP"
    process: str  # "pm-engine", "pm-md-gwy", ...
    function: str  # human sentence: "Order intake (CALF)"
    bind: str  # "127.0.0.1" / "0.0.0.0"
    origin: str  # "fixed" | "env" | "configured" | "default"
    enabled: bool = True
    section: str = ""  # yaml path that owns it, or "config.py"


@dataclass(frozen=True)
class Participant:
    gid: str
    role: str
    disconnect: str
    quote_policy: str | None
    description: str


@dataclass(frozen=True)
class Credential:
    api_key: str
    gateway_id: str | None
    description: str
    owner_gateway: str  # which api_gateways.<name> declares it
    role: str  # resolved from gateways.alf, or "READ-ONLY"


@dataclass(frozen=True)
class ApiGateway:
    name: str
    enabled: bool
    host: str
    port: int
    swagger: bool
    log_level: str
    stats_db: str
    order_retention_sec: int | None
    rate_limit: dict[str, Any] = field(default_factory=dict)
    timeouts: dict[str, Any] = field(default_factory=dict)
    credentials: tuple[Credential, ...] = ()


@dataclass(frozen=True)
class Symbol:
    name: str
    tick_decimals: int | None
    level: str | None
    last_buy: float | None
    last_sell: float | None
    outstanding: int | None
    quote_makers: tuple[str, ...] = ()
    collar_override: dict[str, Any] | None = None
    cb_override: dict[str, Any] | None = None
    mm_override: dict[str, Any] | None = None

    @property
    def n_quotes(self) -> int:
        return len(self.quote_makers)

    @property
    def price(self) -> float | None:
        return self.last_buy if self.last_buy is not None else self.last_sell

    @property
    def override_flags(self) -> str:
        """Compact marker: Collar / Breaker / Mm-obligation, dot for none."""
        return "".join(
            (
                "C" if self.collar_override else "·",
                "B" if self.cb_override else "·",
                "M" if self.mm_override else "·",
            )
        )


@dataclass(frozen=True)
class RiskLevel:
    name: str
    static_band_pct: float | None
    dynamic_band_pct: float | None
    is_default: bool = False
    n_symbols: int = 0


@dataclass(frozen=True)
class CBLevel:
    name: str
    price_shift_pct: float | None
    halt_duration_ns: int | None


@dataclass(frozen=True)
class Combo:
    combo_id: str
    combo_type: str
    tif: str
    legs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Index:
    idx_id: str
    description: str
    base_value: Any
    publish_interval_sec: Any
    constituents: tuple[str, ...] = ()


@dataclass(frozen=True)
class Schedule:
    pre_open: str | None = None
    opening_auction_start: str | None = None
    continuous_start: str | None = None
    closing_auction_start: str | None = None
    closing_auction_end: str | None = None

    @property
    def phases(self) -> tuple[tuple[str, str], ...]:
        """(label, HH:MM) for every field that is set, in session order."""
        pairs = (
            ("Pre-open", self.pre_open),
            ("Opening auction", self.opening_auction_start),
            ("Continuous", self.continuous_start),
            ("Closing auction", self.closing_auction_start),
            ("Close", self.closing_auction_end),
        )
        return tuple((a, b) for a, b in pairs if isinstance(b, str) and b)


@dataclass(frozen=True)
class Source:
    path: Path
    exists: bool
    size: int
    mtime: float
    resolved_via: str  # "--file" | "EDUMATCHER_DATA_DIR" | "data directory"


@dataclass(frozen=True)
class ConfigView:
    """Everything a renderer is allowed to know about one config file."""

    source: Source
    flags: dict[str, Any] = field(default_factory=dict)
    listeners: tuple[Listener, ...] = ()
    participants: tuple[Participant, ...] = ()
    api_gateways: tuple[ApiGateway, ...] = ()
    symbols: tuple[Symbol, ...] = ()
    risk_levels: tuple[RiskLevel, ...] = ()
    default_risk_level: str | None = None
    cb_levels: tuple[CBLevel, ...] = ()
    cb_reference_window_ns: int | None = None
    cb_reopening: dict[str, Any] = field(default_factory=dict)
    mm_defaults: dict[str, Any] = field(default_factory=dict)
    mm_symbol_overrides: dict[str, Any] = field(default_factory=dict)
    combos: tuple[Combo, ...] = ()
    indices: tuple[Index, ...] = ()
    schedule: Schedule = field(default_factory=Schedule)
    tuning: dict[str, Any] = field(default_factory=dict)
    gateway_sections: dict[str, dict[str, Any]] = field(default_factory=dict)
    unknown_keys: tuple[str, ...] = ()

    @property
    def credentials(self) -> tuple[Credential, ...]:
        return tuple(c for g in self.api_gateways for c in g.credentials)

    @property
    def port_collisions(self) -> frozenset[int]:
        """Ports claimed by more than one enabled listener (cf. cverifier M018)."""
        seen: dict[int, int] = {}
        for listener in self.listeners:
            if listener.enabled:
                seen[listener.port] = seen.get(listener.port, 0) + 1
        return frozenset(port for port, n in seen.items() if n > 1)
