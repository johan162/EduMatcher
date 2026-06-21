"""Engine-topic -> CALF payload normalization.

The normalizer accepts decoded engine PUB events and produces CALF payload
fragments (without CH/SYM/SEQ/TS, which are gateway concerns).

Keeping normalization separate from socket flow significantly improves
maintainability and unit-testability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TopOfBook:
    """Cached top-of-book state for one symbol."""

    bid: str | None = None
    bid_sz: str | None = None
    ask: str | None = None
    ask_sz: str | None = None
    last: str | None = None
    last_sz: str | None = None

    def as_snap_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        if self.bid is not None:
            fields["BID"] = self.bid
        if self.bid_sz is not None:
            fields["BIDSZ"] = self.bid_sz
        if self.ask is not None:
            fields["ASK"] = self.ask
        if self.ask_sz is not None:
            fields["ASKSZ"] = self.ask_sz
        if self.last is not None:
            fields["LAST"] = self.last
        if self.last_sz is not None:
            fields["LASTSZ"] = self.last_sz
        return fields


@dataclass
class EngineNormaliser:
    """Translate engine payloads to CALF field maps and detect top changes."""

    top_cache: dict[str, TopOfBook] = field(default_factory=dict)
    session_state: str = "CONTINUOUS"
    symbol_state: dict[str, str] = field(default_factory=dict)

    def normalise_book(
        self, symbol: str, payload: dict[str, Any]
    ) -> dict[str, str] | None:
        """Return incremental ``MD`` fields when top-of-book changed.

        Returns ``None`` when the published book snapshot does not change top
        price/size or last-trade fields compared with cache.
        """
        sym = symbol.upper()
        prev = self.top_cache.get(sym, TopOfBook())

        next_bid, next_bidsz = _extract_top(payload.get("bids"))
        next_ask, next_asksz = _extract_top(payload.get("asks"))
        next_last = _as_decimal(payload.get("last_price"))
        next_lastsz = _as_int_text(payload.get("last_qty"))

        changed: dict[str, str] = {}

        if next_bid != prev.bid:
            if next_bid is not None:
                changed["BID"] = next_bid
            changed["BIDSZ"] = next_bidsz if next_bidsz is not None else "0"
        elif next_bidsz != prev.bid_sz and next_bid is not None:
            changed["BIDSZ"] = next_bidsz if next_bidsz is not None else "0"

        if next_ask != prev.ask:
            if next_ask is not None:
                changed["ASK"] = next_ask
            changed["ASKSZ"] = next_asksz if next_asksz is not None else "0"
        elif next_asksz != prev.ask_sz and next_ask is not None:
            changed["ASKSZ"] = next_asksz if next_asksz is not None else "0"

        if next_last != prev.last and next_last is not None:
            changed["LAST"] = next_last
        if next_lastsz != prev.last_sz and next_lastsz is not None:
            changed["LASTSZ"] = next_lastsz

        self.top_cache[sym] = TopOfBook(
            bid=next_bid,
            bid_sz=next_bidsz,
            ask=next_ask,
            ask_sz=next_asksz,
            last=next_last,
            last_sz=next_lastsz,
        )

        if not changed:
            return None
        return changed

    def normalise_trade(self, payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``TRADE`` message."""
        sym = str(payload.get("symbol", "")).upper()
        fields = {
            "PX": _as_decimal(payload.get("price")) or "0",
            "QTY": _as_int_text(payload.get("quantity")) or "0",
            "SIDE": str(payload.get("aggressor_side", "")).upper(),
        }

        # Keep top cache LAST/LASTSZ synchronized with trades so future SNAP/MD
        # carries the latest trade even if no book update has arrived yet.
        cur = self.top_cache.get(sym, TopOfBook())
        cur.last = fields["PX"]
        cur.last_sz = fields["QTY"]
        self.top_cache[sym] = cur

        return sym, fields

    def normalise_session_state(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``STATE`` fields for session-wide transitions."""
        session = str(payload.get("state", "")).upper()
        prev_state = str(payload.get("prev_state", "")).upper()

        if session:
            self.session_state = session

        fields = {"SESSION": self.session_state}
        if prev_state:
            fields["PREV"] = prev_state
        return "*", fields

    def normalise_halt(self, symbol: str) -> tuple[str, dict[str, str]]:
        """Return per-symbol HALTED state fields."""
        sym = symbol.upper()
        prev = self.symbol_state.get(sym) or self.session_state
        self.symbol_state[sym] = "HALTED"
        return sym, {"SESSION": "HALTED", "PREV": prev}

    def normalise_resume(self, symbol: str) -> tuple[str, dict[str, str]]:
        """Return per-symbol resume state fields.

        Resume maps to CONTINUOUS according to CALF design in the current docs.
        """
        sym = symbol.upper()
        prev = self.symbol_state.get(sym, "HALTED")
        self.symbol_state[sym] = "CONTINUOUS"
        return sym, {"SESSION": "CONTINUOUS", "PREV": prev}

    def top_snapshot_fields(self, symbol: str) -> dict[str, str]:
        """Return current cached TOP snapshot fields for symbol."""
        state = self.top_cache.get(symbol.upper(), TopOfBook())
        return state.as_snap_fields()

    def state_snapshot_fields(self, symbol: str) -> dict[str, str]:
        """Return current STATE snapshot fields for symbol or wildcard."""
        sym = symbol.upper()
        if sym == "*":
            return {"SESSION": self.session_state}
        return {"SESSION": self.symbol_state.get(sym, self.session_state)}


def _as_decimal(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(raw)


def _as_int_text(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return None


def _extract_top(raw_levels: Any) -> tuple[str | None, str | None]:
    """Extract top price/qty from engine snapshot ``bids``/``asks`` arrays."""
    if not isinstance(raw_levels, list) or not raw_levels:
        return None, None

    top = raw_levels[0]
    if not isinstance(top, dict):
        return None, None

    price = _as_decimal(top.get("price"))
    qty = _as_int_text(top.get("qty"))
    return price, qty
