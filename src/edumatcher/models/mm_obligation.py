"""Market maker obligations and market-maker protection runtime state."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class MarketMakerObligation:
    gateway_id: str
    symbol: str
    max_spread_ticks: int = 10
    min_qty: int = 100
    min_presence_pct: float = 0.85
    max_requote_delay_ns: int = 500_000_000
    mmp_fill_count: int = 5
    mmp_window_ns: int = 1_000_000_000


@dataclass(slots=True)
class MMPState:
    gateway_id: str
    symbol: str
    fill_times: deque[int] = field(default_factory=deque)
    mmp_active: bool = False
    mmp_triggered_at: Optional[int] = None
    requote_deadline: Optional[int] = None

    def record_fill(self, obligation: MarketMakerObligation, now: int) -> bool:
        cutoff = now - obligation.mmp_window_ns
        while self.fill_times and self.fill_times[0] < cutoff:
            self.fill_times.popleft()
        self.fill_times.append(now)
        return len(self.fill_times) >= obligation.mmp_fill_count

    def activate_mmp(self, obligation: MarketMakerObligation, now: int) -> None:
        self.mmp_active = True
        self.mmp_triggered_at = now
        self.requote_deadline = now + obligation.max_requote_delay_ns
        self.fill_times.clear()

    def reset_mmp(self) -> None:
        self.mmp_active = False
        self.mmp_triggered_at = None
        self.requote_deadline = None
