"""Advisory warning and info rules for pm-config-gen."""

from __future__ import annotations

from dataclasses import dataclass

from edumatcher.models.participant import ParticipantRole

from .builder import ConfigSpec


@dataclass(frozen=True)
class Diagnostic:
    level: str
    message: str

    def format(self) -> str:
        return f"[{self.level}] {self.message}"


_WILDCARD_BIND_ADDRESSES = frozenset({"0.0.0.0", "::"})


def _network_endpoints(spec: ConfigSpec) -> list[tuple[str, str, int]]:
    """Return (label, bind_address, port) for every network service the spec emits."""
    endpoints: list[tuple[str, str, int]] = []
    if spec.post_trade_gateway is not None:
        pt_gw = spec.post_trade_gateway
        endpoints.append(
            (f"post_trade_gateway '{pt_gw.name}'", pt_gw.bind_address, pt_gw.port)
        )
    if spec.market_data_gateway is not None and spec.market_data_gateway.enabled:
        md_gw = spec.market_data_gateway
        endpoints.append(
            (f"market_data_gateway '{md_gw.name}'", md_gw.bind_address, md_gw.port)
        )
    if spec.balf_gateway is not None:
        balf_gw = spec.balf_gateway
        endpoints.append(
            (f"balf_gateway '{balf_gw.name}'", balf_gw.bind_address, balf_gw.port)
        )
    for api_gw in spec.api_gateways:
        if api_gw.enabled:
            endpoints.append((f"api_gateway '{api_gw.name}'", api_gw.host, api_gw.port))
    return endpoints


def _addresses_collide(address_a: str, address_b: str) -> bool:
    if address_a == address_b:
        return True
    return (
        address_a in _WILDCARD_BIND_ADDRESSES or address_b in _WILDCARD_BIND_ADDRESSES
    )


def _port_collision_warnings(spec: ConfigSpec) -> list[str]:
    """Flag any two enabled network services bound to the same address:port."""
    endpoints = _network_endpoints(spec)
    warnings: list[str] = []
    for i in range(len(endpoints)):
        label_a, address_a, port_a = endpoints[i]
        for label_b, address_b, port_b in endpoints[i + 1 :]:
            if port_a == port_b and _addresses_collide(address_a, address_b):
                where = (
                    address_a if address_a == address_b else f"{address_a}/{address_b}"
                )
                warnings.append(
                    Diagnostic(
                        "WARN",
                        f"Port collision: {label_a} and {label_b} both listen on "
                        f"{where}:{port_a}. Set distinct ports or bind addresses.",
                    ).format()
                )
    return warnings


def evaluate_diagnostics(
    spec: ConfigSpec,
    parsed_symbol_option_warnings: list[str],
    raw_symbols: list[str],
    raw_gateways: list[str],
    output_exists: bool,
) -> list[str]:
    messages: list[str] = list(parsed_symbol_option_warnings)
    messages.extend(_port_collision_warnings(spec))

    mm_gateways = [g for g in spec.gateways if g.role == ParticipantRole.MARKET_MAKER]
    if mm_gateways:
        if spec.seed_mm_mid_range is None:
            for gw in mm_gateways:
                messages.append(
                    Diagnostic(
                        "WARN",
                        f"MARKET_MAKER gateway {gw.gateway_id} requires quote seeds for every "
                        "symbol. Stubs emitted - fill in prices before starting the engine.",
                    ).format()
                )
        elif not spec.seed_last_prices_from_mm:
            messages.append(
                Diagnostic(
                    "INFO",
                    "MM quotes will be seeded from the configured midpoint range. Consider "
                    "--seed-last-prices-from-mm to emit consistent last price references.",
                ).format()
            )

    if spec.sessions_enabled and spec.emit_schedule:
        messages.append(
            Diagnostic(
                "INFO",
                "sessions_enabled: true - emitting default schedule (09:00-16:05). "
                "Override with --pre-open, --opening-auction etc. if needed.",
            ).format()
        )
        messages.append(
            Diagnostic(
                "INFO",
                "sessions_enabled: true means the engine starts in CLOSED. Start "
                "pm-scheduler to drive session transitions.",
            ).format()
        )

    if not spec.enforce_collars or not spec.enforce_circuit_breakers:
        messages.append(
            Diagnostic(
                "WARN",
                "enforce_collars/enforce_circuit_breakers disabled. Suitable for "
                "tests only.",
            ).format()
        )

    if spec.tick_decimals == 0:
        messages.append(
            Diagnostic(
                "WARN",
                "tick_decimals=0 means all prices are whole numbers. Confirm this is "
                "intentional for your instruments.",
            ).format()
        )

    if len(spec.symbols) > 10:
        messages.append(
            Diagnostic(
                "INFO",
                f"Large symbol universe ({len(spec.symbols)} symbols). Consider whether "
                "all participants need all symbols.",
            ).format()
        )

    if len(spec.gateways) == 1:
        messages.append(
            Diagnostic(
                "WARN",
                "Only one gateway configured. In production, consider adding an ADMIN "
                "gateway for operational control.",
            ).format()
        )

    if not any(g.role == ParticipantRole.ADMIN for g in spec.gateways):
        messages.append(
            Diagnostic(
                "INFO",
                "No ADMIN gateway configured. Without one, exchange-wide halt/resume "
                "commands cannot be sent.",
            ).format()
        )

    if output_exists:
        messages.append("[ERROR] Output file already exists. Use --force to overwrite.")

    for symbol in raw_symbols:
        if symbol != symbol.upper():
            messages.append(
                Diagnostic(
                    "INFO",
                    f"Symbol names are uppercased by the engine loader; '{symbol}' will "
                    f"become '{symbol.upper()}'.",
                ).format()
            )

    for raw_gateway in raw_gateways:
        gateway_id = raw_gateway.split(":", 1)[0]
        if gateway_id != gateway_id.upper():
            messages.append(
                Diagnostic(
                    "INFO",
                    f"Gateway IDs are uppercased by the engine loader; '{gateway_id}' "
                    f"will become '{gateway_id.upper()}'.",
                ).format()
            )

    if (
        mm_gateways
        and spec.seed_mm_mid_range is None
        and not spec.seed_last_prices
        and not spec.seed_last_prices_from_mm
    ):
        messages.append(
            Diagnostic(
                "INFO",
                "Consider --seed-last-prices to emit placeholder "
                "last_buy_price/last_sell_price fields for viewer reference. They are "
                "required for collar initialization.",
            ).format()
        )

    defined_levels: set[str] = set(spec.risk_levels)
    if spec.static_band_pct is not None or spec.dynamic_band_pct is not None:
        defined_levels.add("DEFAULT")
    for symbol, override in spec.symbol_overrides.items():
        if override.level is not None and override.level not in defined_levels:
            messages.append(
                Diagnostic(
                    "WARN",
                    f"Symbol {symbol} references undefined risk level {override.level}. "
                    "Define it with --risk-level NAME:STATIC:DYNAMIC or the engine "
                    "will reject the config.",
                ).format()
            )

    return messages
