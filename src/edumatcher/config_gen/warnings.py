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


def evaluate_diagnostics(
    spec: ConfigSpec,
    parsed_symbol_option_warnings: list[str],
    raw_symbols: list[str],
    raw_gateways: list[str],
    output_exists: bool,
) -> list[str]:
    messages: list[str] = list(parsed_symbol_option_warnings)

    mm_gateways = [g for g in spec.gateways if g.role == ParticipantRole.MARKET_MAKER]
    if mm_gateways:
        for gw in mm_gateways:
            messages.append(
                Diagnostic(
                    "WARN",
                    f"MARKET_MAKER gateway {gw.gateway_id} requires quote seeds for every "
                    "symbol. Stubs emitted - fill in prices before starting the engine.",
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

    if mm_gateways and not spec.seed_last_prices:
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
