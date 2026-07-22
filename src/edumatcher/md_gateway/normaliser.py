"""Engine-topic -> CALF payload normalization.

The normalizer accepts decoded engine PUB events and produces CALF payload
fragments (without CH/SYM/SEQ/TS, which are gateway concerns).

Keeping normalization separate from socket flow significantly improves
maintainability and unit-testability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edumatcher.md_gateway.protocol import iso_utc


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


@dataclass(frozen=True)
class DepthBook:
    """Cached depth ladder for one symbol.

    ``bids``/``asks`` hold up to ``depth_levels`` ``(price, qty, count)``
    triples, best price first, mirroring the sort order already produced by
    ``OrderBook.snapshot()`` in the engine.
    """

    bids: tuple[tuple[str, str, str], ...] = ()
    asks: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class CBStatus:
    """Cached circuit-breaker status for one symbol.

    Every field except ``status`` is an empty string when not applicable —
    e.g. a fresh symbol that has never halted, or a halt/resume path (ADMIN
    halts, all resumes) that does not carry a trigger/reference price or an
    auto-resume time. An empty string is a safe "absent" sentinel here: the
    engine never publishes an empty-string ``level``, and a legitimate
    ``0``-valued price or timestamp still round-trips through
    ``_as_decimal``/``_as_int_text`` as the non-empty text ``"0"``.
    """

    status: str = "ACTIVE"  # "ACTIVE" | "HALTED"
    level: str = ""
    trigger_price: str = ""
    reference_price: str = ""
    resume_at: str = ""
    mode: str = ""


@dataclass
class EngineNormaliser:
    """Translate engine payloads to CALF field maps and detect top changes."""

    top_cache: dict[str, TopOfBook] = field(default_factory=dict)
    session_state: str = "CONTINUOUS"
    symbol_state: dict[str, str] = field(default_factory=dict)
    index_cache: dict[str, dict[str, str]] = field(default_factory=dict)
    depth_cache: dict[str, DepthBook] = field(default_factory=dict)
    depth_levels: int = 10
    cb_cache: dict[str, CBStatus] = field(default_factory=dict)

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

    def normalise_depth(
        self, symbol: str, payload: dict[str, Any]
    ) -> dict[str, str] | None:
        """Return incremental ``DEPTH`` fields when the top-N ladder changed.

        Returns ``None`` when the top ``depth_levels`` price levels on both
        sides are unchanged compared with the cached snapshot, mirroring how
        ``normalise_book`` only emits ``MD`` when the top of book changes.
        """
        sym = symbol.upper()
        prev = self.depth_cache.get(sym, DepthBook())

        next_bids = _extract_levels(payload.get("bids"), self.depth_levels)
        next_asks = _extract_levels(payload.get("asks"), self.depth_levels)

        self.depth_cache[sym] = DepthBook(bids=next_bids, asks=next_asks)

        if next_bids == prev.bids and next_asks == prev.asks:
            return None

        fields: dict[str, str] = {"LEVELS": str(self.depth_levels)}
        if next_bids:
            fields["BIDS"] = _encode_levels(next_bids)
        if next_asks:
            fields["ASKS"] = _encode_levels(next_asks)
        return fields

    def depth_snapshot_fields(self, symbol: str) -> dict[str, str]:
        """Return current cached DEPTH snapshot fields for symbol."""
        state = self.depth_cache.get(symbol.upper(), DepthBook())
        fields: dict[str, str] = {"LEVELS": str(self.depth_levels)}
        if state.bids:
            fields["BIDS"] = _encode_levels(state.bids)
        if state.asks:
            fields["ASKS"] = _encode_levels(state.asks)
        return fields

    def state_snapshot_fields(self, symbol: str) -> dict[str, str]:
        """Return current STATE snapshot fields for symbol or wildcard."""
        sym = symbol.upper()
        if sym == "*":
            return {"SESSION": self.session_state}
        return {"SESSION": self.symbol_state.get(sym, self.session_state)}

    def normalise_index_update(
        self,
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        """Map internal index.update payload to CALF INDEX fields."""
        index_id = str(payload.get("index_id", "")).upper()
        level = _as_decimal(payload.get("level")) or "0"
        fields: dict[str, str] = {
            "LEVEL": level,
            "SESSION": str(payload.get("session_state", "")).upper() or "UNKNOWN",
        }

        day_open = payload.get("day_open")
        day_high = payload.get("day_high")
        day_low = payload.get("day_low")
        if day_open is not None:
            open_text = _as_decimal(day_open)
            if open_text is not None:
                fields["OPEN"] = open_text
                try:
                    delta = float(level) - float(open_text)
                    pct = (
                        (delta / float(open_text)) * 100
                        if float(open_text) != 0.0
                        else 0.0
                    )
                    fields["CHG"] = f"{delta:+.2f}"
                    fields["PCTCHG"] = f"{pct:+.2f}"
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
        if day_high is not None:
            high_text = _as_decimal(day_high)
            if high_text is not None:
                fields["HIGH"] = high_text
        if day_low is not None:
            low_text = _as_decimal(day_low)
            if low_text is not None:
                fields["LOW"] = low_text

        agg_cap = payload.get("aggregate_cap")
        if agg_cap is not None:
            cap_text = _as_int_text(agg_cap)
            if cap_text is not None:
                fields["AGGCAP"] = cap_text

        self.index_cache[index_id] = dict(fields)
        return index_id, fields

    def index_snapshot_fields(self, index_id: str) -> dict[str, str]:
        """Return cached snapshot fields for one index stream."""
        return dict(self.index_cache.get(index_id.upper(), {}))

    def normalise_auction_result(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``AUCTION`` message.

        Unlike ``TOP``/``DEPTH``/``INDEX``, ``AUCTION`` has no persistent
        "current state" to cache or snapshot: every ``auction.result.SYMBOL``
        engine event is forwarded as its own independent CALF event.
        """
        sym = str(payload.get("symbol", "")).upper()
        fields: dict[str, str] = {
            "EQQTY": _as_int_text(payload.get("eq_qty")) or "0",
            "TRADES": _as_int_text(payload.get("trades_count")) or "0",
            "IMBQTY": _as_int_text(payload.get("imbalance_qty")) or "0",
        }
        eq_price = payload.get("eq_price")
        if eq_price is not None:
            price_text = _as_decimal(eq_price)
            if price_text is not None:
                fields["EQPX"] = price_text
        imbalance_side = str(payload.get("imbalance_side", "")).upper()
        if imbalance_side:
            fields["IMBSIDE"] = imbalance_side
        return sym, fields

    def normalise_cb_halt(
        self, symbol: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``CB`` halt event.

        Caches the resulting status so a later ``SUB|CH=CB`` on this symbol
        gets a ``SNAP`` reflecting the halt still in effect.
        """
        sym = symbol.upper()
        resume_at_ns = payload.get("resume_at_ns")
        state = CBStatus(
            status="HALTED",
            level=str(payload.get("level", "")).upper(),
            trigger_price=_as_decimal(payload.get("trigger_price")) or "",
            reference_price=_as_decimal(payload.get("reference_price")) or "",
            resume_at=_ns_to_iso(resume_at_ns),
            mode=str(payload.get("resumption_mode", "")).upper(),
        )
        self.cb_cache[sym] = state
        return sym, _cb_fields(state)

    def normalise_cb_resume(
        self, symbol: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``CB`` resume event.

        The engine's own resume payload only carries ``symbol``/``mode`` —
        see ``normalise_cb_halt`` for why ``LEVEL``/``TRIGGERPX``/``REFPX``/
        ``RESUMEAT`` are intentionally absent from a resume event.
        """
        sym = symbol.upper()
        state = CBStatus(
            status="ACTIVE",
            mode=str(payload.get("mode", "")).upper(),
        )
        self.cb_cache[sym] = state
        return sym, _cb_fields(state)

    def cb_snapshot_fields(self, symbol: str) -> dict[str, str]:
        """Return current cached CB snapshot fields for symbol."""
        state = self.cb_cache.get(symbol.upper(), CBStatus())
        return _cb_fields(state)


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


def _extract_levels(
    raw_levels: Any, max_levels: int
) -> tuple[tuple[str, str, str], ...]:
    """Extract up to ``max_levels`` ``(price, qty, count)`` triples, best-first.

    Rows with a missing price or qty are skipped rather than raising, since a
    malformed level should not take down the whole DEPTH message; ``count``
    defaults to ``"0"`` when absent.
    """
    if not isinstance(raw_levels, list):
        return ()

    out: list[tuple[str, str, str]] = []
    for lvl in raw_levels[:max_levels]:
        if not isinstance(lvl, dict):
            continue
        price = _as_decimal(lvl.get("price"))
        qty = _as_int_text(lvl.get("qty"))
        if price is None or qty is None:
            continue
        count = _as_int_text(lvl.get("count")) or "0"
        out.append((price, qty, count))
    return tuple(out)


def _encode_levels(levels: tuple[tuple[str, str, str], ...]) -> str:
    """Encode ``(price, qty, count)`` triples as ``price:qty:count,...``."""
    return ",".join(f"{px}:{qty}:{cnt}" for px, qty, cnt in levels)


def _ns_to_iso(raw_ns: Any) -> str:
    """Convert an epoch-nanoseconds value to CALF's ISO-8601 timestamp text.

    Returns ``""`` (the CBStatus "absent" sentinel) when ``raw_ns`` is
    ``None`` or not a usable number — e.g. a rest-of-day or manual halt,
    where the engine's own ``resume_at_ns`` is ``None``. Every other CALF
    timestamp field is ISO-8601 text (``TS`` via ``iso_utc``); ``RESUMEAT``
    follows that convention rather than exposing raw engine-internal
    nanosecond ticks on the wire.
    """
    if raw_ns is None:
        return ""
    try:
        return iso_utc(int(raw_ns) / 1_000_000_000)
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _cb_fields(state: CBStatus) -> dict[str, str]:
    """Return the CALF field map for a cached/just-computed CB status.

    Shared by ``normalise_cb_halt``, ``normalise_cb_resume``, and
    ``cb_snapshot_fields`` so the halt/resume event shape and the SNAP
    baseline shape can never drift apart.
    """
    fields: dict[str, str] = {"STATUS": state.status}
    if state.status == "HALTED":
        if state.level:
            fields["LEVEL"] = state.level
        if state.trigger_price:
            fields["TRIGGERPX"] = state.trigger_price
        if state.reference_price:
            fields["REFPX"] = state.reference_price
        if state.resume_at:
            fields["RESUMEAT"] = state.resume_at
    if state.mode:
        fields["MODE"] = state.mode
    return fields
