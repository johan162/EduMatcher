"""Per-agent risk limits and the reject breaker."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

#: Reject codes that are not the agent's fault and must not trip the breaker:
#: a cancel that lost a race with a fill, and an order in flight when the
#: market closed.
BENIGN_REJECT_CODES = frozenset({"ORDER_NOT_FOUND", "MARKET_CLOSED"})


@dataclass(frozen=True)
class RiskSpec:
    max_position: int = 1000
    max_live_orders_per_symbol: int = 2
    max_order_age_sec: float = 60.0
    #: Cancel a resting order this many ticks behind its own side's touch.
    stale_price_ticks: int | None = 10
    #: none | stop | stop_limit | trailing | bracket
    protection: str = "none"
    #: Stop distance (and bracket take-profit distance) as a price fraction.
    protection_pct: float = 0.02


def allowed_qty(
    side: str, position: int, open_same_side: int, max_position: int
) -> int:
    """Largest new order on ``side`` that keeps |position| within the limit.

    Open orders on the same side count as if they had filled.
    """
    if side == "BUY":
        return max(0, max_position - position - open_same_side)
    return max(0, max_position + position - open_same_side)


class RejectBreaker:
    """Pause an agent that keeps getting orders refused."""

    def __init__(
        self, max_rejects: int = 25, window: float = 10.0, cooldown: float = 5.0
    ):
        self.max_rejects = max_rejects
        self.window = window
        self.cooldown = cooldown
        self._times: deque[float] = deque()
        self.paused_until = 0.0
        self.trips = 0

    def record(self, now: float, code: str | None) -> bool:
        """Count a reject; True when this one tripped the breaker."""
        if code in BENIGN_REJECT_CODES:
            return False
        self._times.append(now)
        while self._times and self._times[0] < now - self.window:
            self._times.popleft()
        if len(self._times) >= self.max_rejects:
            self._times.clear()
            self.paused_until = now + self.cooldown
            self.trips += 1
            return True
        return False

    def paused(self, now: float) -> bool:
        return now < self.paused_until
