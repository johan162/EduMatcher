"""Quote model and quote index.

A quote is represented as two regular orders in the order book; QuoteIndex
provides O(1) lookup by (gateway_id, symbol).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from edumatcher.models.clock import now_ns


class QuoteState(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE_BID_FILLED = "INACTIVE_BID_FILLED"
    INACTIVE_ASK_FILLED = "INACTIVE_ASK_FILLED"
    CANCELLED = "CANCELLED"


class QuoteRefreshPolicy(str, Enum):
    INACTIVATE_ON_ANY_FILL = "INACTIVATE_ON_ANY_FILL"
    INACTIVATE_ON_FULL_FILL = "INACTIVATE_ON_FULL_FILL"
    NEVER_INACTIVATE = "NEVER_INACTIVATE"


@dataclass(slots=True)
class QuoteEntry:
    quote_id: str
    gateway_id: str
    symbol: str
    bid_order_id: str
    ask_order_id: str
    state: QuoteState = QuoteState.ACTIVE
    timestamp: int = field(default_factory=now_ns)

    def counterpart_order_id(self, filled_side: str) -> str:
        return self.ask_order_id if filled_side == "BUY" else self.bid_order_id


class QuoteIndex:
    def __init__(self) -> None:
        self._index: dict[tuple[str, str], QuoteEntry] = {}

    def get(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        return self._index.get((gateway_id, symbol))

    def put(self, entry: QuoteEntry) -> Optional[QuoteEntry]:
        key = (entry.gateway_id, entry.symbol)
        old = self._index.get(key)
        self._index[key] = entry
        return old

    def remove(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        return self._index.pop((gateway_id, symbol), None)

    def cancel_all_for_gateway(self, gateway_id: str) -> list[QuoteEntry]:
        keys = [k for k in self._index if k[0] == gateway_id]
        return [self._index.pop(k) for k in keys]

    def cancel_all_for_symbol(self, symbol: str) -> list[QuoteEntry]:
        keys = [k for k in self._index if k[1] == symbol]
        return [self._index.pop(k) for k in keys]

    def active_count(self) -> int:
        return len(self._index)
