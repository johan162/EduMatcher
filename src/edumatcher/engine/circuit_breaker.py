"""Per-symbol multi-level circuit breaker runtime state.

This model implements exchange-style L1/L2/L3 (or custom) breaker levels:

- each level has a price-shift threshold
- each level has its own halt duration
- larger price shifts can trigger deeper levels with longer halts
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CircuitBreakerLevel:
    """One trigger level in a circuit-breaker ladder."""

    name: str
    price_shift_pct: float
    halt_duration_ns: int | None
    resumption_mode: str = "AUCTION"


@dataclass
class CircuitBreakerConfig:
    """Static configuration for one symbol's circuit breaker."""

    symbol: str
    reference_window_ns: int = 300_000_000_000  # 5 minutes
    levels: list[CircuitBreakerLevel] = field(default_factory=list)


@dataclass
class CircuitBreakerState:
    """Mutable runtime state for one symbol's circuit breaker."""

    symbol: str
    config: CircuitBreakerConfig
    trade_history: deque[tuple[int, int]] = field(
        default_factory=deque
    )  # (timestamp_ns, price_ticks)
    halted: bool = False
    halted_at_ns: Optional[int] = None
    resume_at_ns: Optional[int] = None
    trigger_price: Optional[int] = None
    reference_price: Optional[int] = None
    triggered_level: Optional[str] = None
    active_resumption_mode: Optional[str] = None

    def record_trade(self, price: int, now: int) -> CircuitBreakerLevel | None:
        """Record a fill and return the triggered breaker level, if any."""
        if self.halted:
            return None  # don't double-trigger an active halt

        # Trim entries older than the reference window — O(k) where k ≤ window age
        cutoff = now - self.config.reference_window_ns
        while self.trade_history and self.trade_history[0][0] < cutoff:
            self.trade_history.popleft()

        fired_level: CircuitBreakerLevel | None = None
        if self.trade_history:
            prices = [p for _, p in self.trade_history]
            ref = sum(prices) // len(prices)
            self.reference_price = ref
            shift = abs(price - ref) / ref if ref > 0 else 0.0
            for level in sorted(
                self.config.levels,
                key=lambda lvl: lvl.price_shift_pct,
            ):
                if shift >= level.price_shift_pct:
                    fired_level = level

        self.trade_history.append((now, price))
        if fired_level is not None:
            self.trigger_price = price
            self.triggered_level = fired_level.name
        return fired_level

    def activate(self, now: int, level: CircuitBreakerLevel) -> None:
        """Activate a halt at the specified triggered level."""
        self.halted = True
        self.halted_at_ns = now
        self.resume_at_ns = (
            None if level.halt_duration_ns is None else now + level.halt_duration_ns
        )
        self.active_resumption_mode = level.resumption_mode

    def should_resume(self, now: int) -> bool:
        """Return ``True`` when a timed halt duration has elapsed."""
        return (
            self.halted and self.resume_at_ns is not None and now >= self.resume_at_ns
        )

    def deactivate(self) -> None:
        """Clear the halt state."""
        self.halted = False
        self.halted_at_ns = None
        self.resume_at_ns = None
        self.trigger_price = None
        self.triggered_level = None
        self.active_resumption_mode = None
        # Keep reference_price — useful for diagnostics after resume.
