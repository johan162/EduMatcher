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
        self._keys_by_gateway: dict[str, set[tuple[str, str]]] = {}
        self._keys_by_symbol: dict[str, set[tuple[str, str]]] = {}

    def _track_key(self, key: tuple[str, str]) -> None:
        gw, sym = key
        self._keys_by_gateway.setdefault(gw, set()).add(key)
        self._keys_by_symbol.setdefault(sym, set()).add(key)

    def _untrack_key(self, key: tuple[str, str]) -> None:
        gw, sym = key
        gw_keys = self._keys_by_gateway.get(gw)
        if gw_keys is not None:
            gw_keys.discard(key)
            if not gw_keys:
                self._keys_by_gateway.pop(gw, None)
        sym_keys = self._keys_by_symbol.get(sym)
        if sym_keys is not None:
            sym_keys.discard(key)
            if not sym_keys:
                self._keys_by_symbol.pop(sym, None)

    def get(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        return self._index.get((gateway_id, symbol))

    def put(self, entry: QuoteEntry) -> Optional[QuoteEntry]:
        key = (entry.gateway_id, entry.symbol)
        old = self._index.get(key)
        if old is not None:
            self._untrack_key(key)
        self._index[key] = entry
        self._track_key(key)
        return old

    def remove(self, gateway_id: str, symbol: str) -> Optional[QuoteEntry]:
        key = (gateway_id, symbol)
        old = self._index.pop(key, None)
        if old is not None:
            self._untrack_key(key)
        return old

    def cancel_all_for_gateway(self, gateway_id: str) -> list[QuoteEntry]:
        keys = list(self._keys_by_gateway.get(gateway_id, set()))
        removed: list[QuoteEntry] = []
        for key in keys:
            entry = self._index.pop(key, None)
            if entry is not None:
                self._untrack_key(key)
                removed.append(entry)
        return removed

    def cancel_all_for_symbol(self, symbol: str) -> list[QuoteEntry]:
        keys = list(self._keys_by_symbol.get(symbol, set()))
        removed: list[QuoteEntry] = []
        for key in keys:
            entry = self._index.pop(key, None)
            if entry is not None:
                self._untrack_key(key)
                removed.append(entry)
        return removed

    def has_symbol(self, symbol: str) -> bool:
        return bool(self._keys_by_symbol.get(symbol))

    def active_count(self) -> int:
        return len(self._index)
