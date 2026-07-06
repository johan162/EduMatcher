"""Parser for circuit-breaker level specs: NAME:SHIFT_PCT[:HALT_MINS[:RESUMPTION_MODE]]."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CbSpec:
    name: str
    shift_pct: float
    halt_mins: int | None
    resumption_mode: str = "AUCTION"  # AUCTION | CONTINUOUS


def parse_cb_spec(raw: str) -> CbSpec:
    parts = [part.strip() for part in raw.split(":")]
    if len(parts) not in (2, 3, 4):
        raise ValueError(
            f"Invalid circuit-breaker spec '{raw}': expected NAME:SHIFT_PCT[:HALT_MINS[:RESUMPTION_MODE]]"
        )

    name = parts[0].upper()
    if not name:
        raise ValueError("Circuit-breaker level name cannot be empty")

    try:
        shift_pct = float(parts[1])
    except ValueError as exc:
        raise ValueError(f"Invalid shift_pct in circuit-breaker spec '{raw}'") from exc
    if not (0 < shift_pct < 1):
        raise ValueError(f"Circuit-breaker shift_pct must be in (0, 1): '{raw}'")

    halt_mins: int | None = None
    if len(parts) >= 3 and parts[2] != "":
        try:
            parsed_halt = int(parts[2])
        except ValueError as exc:
            raise ValueError(
                f"Invalid halt_mins in circuit-breaker spec '{raw}'"
            ) from exc
        if parsed_halt < 0:
            raise ValueError(f"halt_mins must be >= 0 in circuit-breaker spec '{raw}'")
        halt_mins = parsed_halt

    resumption_mode = "AUCTION"
    if len(parts) == 4 and parts[3]:
        resumption_mode = parts[3].upper()
        if resumption_mode not in ("AUCTION", "CONTINUOUS"):
            raise ValueError(
                f"Invalid resumption_mode in circuit-breaker spec '{raw}': "
                "must be AUCTION or CONTINUOUS"
            )

    return CbSpec(
        name=name,
        shift_pct=shift_pct,
        halt_mins=halt_mins,
        resumption_mode=resumption_mode,
    )
