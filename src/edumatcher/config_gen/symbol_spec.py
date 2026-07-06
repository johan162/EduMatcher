"""Parser for --symbol-opts SYMBOL:KEY=VALUE[,KEY=VALUE,...]."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SymbolOverride:
    tick_decimals: int | None = None
    static_band_pct: float | None = None
    dynamic_band_pct: float | None = None
    cb_shift: dict[str, float] = field(default_factory=dict)
    cb_halt_mins: dict[str, int | None] = field(default_factory=dict)
    cb_resumption_mode: dict[str, str] = field(default_factory=dict)
    level: str | None = None
    mm_spread_ticks: int | None = None
    mm_min_qty: int | None = None
    enforce_mm_obligation: bool | None = None


_ALLOWED_KEYS = {
    "tick_decimals",
    "static_band",
    "dynamic_band",
    "cb_shift_l1",
    "cb_halt_l1",
    "cb_resumption_l1",
    "cb_shift_l2",
    "cb_halt_l2",
    "cb_resumption_l2",
    "cb_shift_l3",
    "cb_halt_l3",
    "cb_resumption_l3",
    "level",
    "mm_spread_ticks",
    "mm_min_qty",
    "enforce_mm_obligation",
}


def parse_symbol_opts(
    specs: list[str],
    allowed_symbols: set[str],
) -> tuple[dict[str, SymbolOverride], list[str]]:
    overrides: dict[str, SymbolOverride] = {}
    warnings: list[str] = []

    for raw in specs:
        symbol, csv_payload = _split_symbol_spec(raw)
        if symbol not in allowed_symbols:
            warnings.append(
                f"[WARN] --symbol-opts references unknown symbol {symbol}. "
                "Override ignored."
            )
            continue

        override = overrides.setdefault(symbol, SymbolOverride())
        for token in csv_payload.split(","):
            token = token.strip()
            if not token:
                continue
            if "=" not in token:
                warnings.append(
                    f"[WARN] Ignoring malformed symbol option '{token}' in '{raw}'."
                )
                continue

            key_raw, value_raw = token.split("=", 1)
            key = key_raw.strip().lower()
            value = value_raw.strip()
            if key not in _ALLOWED_KEYS:
                warnings.append(
                    f"[WARN] Unknown --symbol-opts key '{key_raw}' for {symbol}. "
                    "Ignored."
                )
                continue

            _apply_symbol_option(
                override=override,
                symbol=symbol,
                key=key,
                value=value,
                warnings=warnings,
            )

    return overrides, warnings


def _split_symbol_spec(raw: str) -> tuple[str, str]:
    if ":" not in raw:
        raise ValueError(
            f"Invalid --symbol-opts '{raw}': expected SYMBOL:KEY=VALUE[,KEY=VALUE]"
        )
    symbol_raw, payload = raw.split(":", 1)
    symbol = symbol_raw.strip().upper()
    if not symbol:
        raise ValueError(f"Invalid --symbol-opts '{raw}': symbol cannot be empty")
    if not payload.strip():
        raise ValueError(
            f"Invalid --symbol-opts '{raw}': KEY=VALUE payload cannot be empty"
        )
    return symbol, payload


def _apply_symbol_option(
    override: SymbolOverride,
    symbol: str,
    key: str,
    value: str,
    warnings: list[str],
) -> None:
    try:
        if key == "tick_decimals":
            parsed_int = int(value)
            if not (0 <= parsed_int <= 8):
                raise ValueError("tick_decimals must be in range 0..8")
            override.tick_decimals = parsed_int
            return

        if key == "static_band":
            parsed_float = float(value)
            if not (0 < parsed_float < 1):
                raise ValueError("static_band must be in (0, 1)")
            override.static_band_pct = parsed_float
            return

        if key == "dynamic_band":
            parsed_float = float(value)
            if not (0 < parsed_float < 1):
                raise ValueError("dynamic_band must be in (0, 1)")
            override.dynamic_band_pct = parsed_float
            return

        if key.startswith("cb_shift_l"):
            level = key.split("_")[-1].upper()
            parsed_float = float(value)
            if not (0 < parsed_float < 1):
                raise ValueError("cb_shift must be in (0, 1)")
            override.cb_shift[level] = parsed_float
            return

        if key.startswith("cb_halt_l"):
            level = key.split("_")[-1].upper()
            parsed_int = int(value)
            if parsed_int < 0:
                raise ValueError("cb_halt must be >= 0")
            override.cb_halt_mins[level] = parsed_int
            return

        if key.startswith("cb_resumption_l"):
            level = key.split("_")[-1].upper()
            parsed_mode = value.strip().upper()
            if parsed_mode not in ("AUCTION", "CONTINUOUS"):
                raise ValueError("cb_resumption must be AUCTION or CONTINUOUS")
            override.cb_resumption_mode[level] = parsed_mode
            return

        if key == "level":
            parsed_level = value.strip().upper()
            if not parsed_level:
                raise ValueError("level cannot be empty")
            override.level = parsed_level
            return

        if key == "mm_spread_ticks":
            parsed_int = int(value)
            if parsed_int <= 0:
                raise ValueError("mm_spread_ticks must be > 0")
            override.mm_spread_ticks = parsed_int
            return

        if key == "mm_min_qty":
            parsed_int = int(value)
            if parsed_int <= 0:
                raise ValueError("mm_min_qty must be > 0")
            override.mm_min_qty = parsed_int
            return

        if key == "enforce_mm_obligation":
            if value.lower() in ("true", "1", "yes"):
                override.enforce_mm_obligation = True
            elif value.lower() in ("false", "0", "no"):
                override.enforce_mm_obligation = False
            else:
                raise ValueError("enforce_mm_obligation must be true or false")
            return

    except ValueError as exc:
        warnings.append(
            f"[WARN] Invalid value for {symbol}:{key}={value} ({exc}). Ignored."
        )
