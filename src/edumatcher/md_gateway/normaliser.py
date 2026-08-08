"""Engine-topic -> CALF payload normalization.

The normalizer accepts decoded engine PUB events and produces CALF payload
fragments (without CH/SYM/SEQ/TS, which are gateway concerns).

Keeping normalization separate from socket flow significantly improves
maintainability and unit-testability.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from edumatcher.md_gateway.protocol import iso_utc
from edumatcher.models.generated.trade import project_trade_executed_calf


@dataclass(frozen=True)
class TopOfBook:
    """Cached top-of-book state for one symbol.

    Frozen, like its ``DepthBook``/``CBStatus`` siblings, because the same
    instance is shared between ``top_cache`` and ``top_sent``: mutating one in
    place would silently reach through to the other and defeat the diff those
    two exist to separate. Update via :func:`dataclasses.replace`.
    """

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
    # ACE corridor. Part of the cached status rather than event-only: it
    # describes the halt currently in force, so a late subscriber's SNAP must
    # carry it or they cannot tell where the symbol may reopen.
    corridor_low: str = ""
    corridor_high: str = ""
    expansion: str = ""
    # What put the symbol into a halt: "CB" or "ADMIN". Not how it resumes —
    # every halt is a reopening auction call that ends in an uncross.
    source: str = ""


@dataclass
class EngineNormaliser:
    """Translate engine payloads to CALF field maps and detect top changes."""

    # Current top-of-book per symbol — what a SNAP should report right now.
    # Written by both normalise_book and normalise_trade.
    top_cache: dict[str, TopOfBook] = field(default_factory=dict)
    # What was last actually put on the wire in an MD/SNAP, which is what an
    # incremental update must diff against.
    #
    # These two were one dict, and conflating them was a bug: normalise_trade
    # writes the new last price into the cache so a SNAP is immediately
    # correct, which also made the next normalise_book see LAST as unchanged
    # and suppress it. The result was that MD never carried a new LAST after a
    # trade, so a continuously-connected client kept showing the price baked
    # into its original SNAP while a reconnecting one saw the true value —
    # two clients on the same feed, disagreeing indefinitely.
    top_sent: dict[str, TopOfBook] = field(default_factory=dict)
    session_state: str = "CONTINUOUS"
    # The next scheduled transition, as the engine reported it. Cached so a
    # client connecting mid-session gets the countdown in its SNAP rather
    # than waiting until the next transition -- which could be hours, and is
    # exactly when a countdown is most useful (T-M6).
    next_session_state: str = ""
    next_session_at: str = ""
    symbol_state: dict[str, str] = field(default_factory=dict)
    index_cache: dict[str, dict[str, str]] = field(default_factory=dict)
    depth_cache: dict[str, DepthBook] = field(default_factory=dict)
    depth_levels: int = 10
    cb_cache: dict[str, CBStatus] = field(default_factory=dict)

    def normalise_book(
        self, symbol: str, payload: dict[str, Any]
    ) -> dict[str, str] | None:
        """Return incremental ``MD`` fields when top-of-book changed.

        Returns ``None`` when the published book snapshot changes nothing that
        has not already been sent.

        The comparison is against ``top_sent`` — what this stream last put on
        the wire — rather than against ``top_cache``, which also absorbs trade
        prints and would therefore hide a genuine change from subscribers.
        """
        sym = symbol.upper()
        prev = self.top_sent.get(sym, TopOfBook())

        next_bid, next_bidsz = _extract_top(payload.get("bids"))
        next_ask, next_asksz = _extract_top(payload.get("asks"))
        next_last = _as_decimal(payload.get("last_price"))
        next_lastsz = _as_int_text(payload.get("last_qty"))

        changed: dict[str, str] = {}

        # An emptied side is published as an explicitly empty ``BID=``/``ASK=``
        # rather than by omitting the field. Omission means "unchanged" to a
        # client merging deltas, so a withdrawn side used to leave the last
        # known price on screen forever, while a client that reconnected and
        # received a fresh SNAP correctly saw no bid at all — two clients on
        # the same feed disagreeing about the book, indefinitely. See the
        # ``MD`` message definition in the CALF protocol reference.
        if next_bid != prev.bid:
            changed["BID"] = next_bid if next_bid is not None else ""
            changed["BIDSZ"] = next_bidsz if next_bidsz is not None else "0"
        elif next_bidsz != prev.bid_sz and next_bid is not None:
            changed["BIDSZ"] = next_bidsz if next_bidsz is not None else "0"

        if next_ask != prev.ask:
            changed["ASK"] = next_ask if next_ask is not None else ""
            changed["ASKSZ"] = next_asksz if next_asksz is not None else "0"
        elif next_asksz != prev.ask_sz and next_ask is not None:
            changed["ASKSZ"] = next_asksz if next_asksz is not None else "0"

        if next_last != prev.last and next_last is not None:
            changed["LAST"] = next_last
        if next_lastsz != prev.last_sz and next_lastsz is not None:
            changed["LASTSZ"] = next_lastsz

        book = TopOfBook(
            bid=next_bid,
            bid_sz=next_bidsz,
            ask=next_ask,
            ask_sz=next_asksz,
            last=next_last,
            last_sz=next_lastsz,
        )
        self.top_cache[sym] = book

        if not changed:
            return None

        # Only record what was sent once there is something to send. A book
        # republish that changes nothing must not advance the sent baseline,
        # or a field could be marked delivered without ever going out.
        self.top_sent[sym] = book
        return changed

    def normalise_trade(self, payload: dict[str, Any]) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``TRADE`` message.

        The ``{PX, QTY, SIDE}`` map is built by the generated projection, from
        ``spec/messages/trade.yaml``, rather than by a dict literal here — so
        adding a field to the public trade feed is a spec edit rather than an
        edit here that the C clients would never see. The envelope
        (``CH``/``SYM``/``SEQ``/``TS``) stays with ``_emit_stream_event``, and
        the top-of-book bookkeeping below stays hand-written: the generator owns
        the projection, not the state around it (design section 4.6, N1).

        The projection reads only the three fields this feed carries, so a
        payload need not contain the rest of the bus message — ``id``,
        ``buy_order_id`` and the other keys CALF drops are never touched.

        It does raise ``KeyError`` on a payload missing ``price`` or
        ``quantity``, where the previous dict literal substituted ``"0"``. That
        is a deliberate improvement: both are ``required`` in the spec, the
        engine always sends them, and the caller's handler logs and skips — so
        a malformed message is now dropped with a warning instead of published
        to live clients as a print of zero shares at zero price.
        """
        sym = str(payload.get("symbol", "")).upper()
        fields = project_trade_executed_calf(payload)

        # Keep the *current* top-of-book in step with trades, so a SNAP issued
        # before the next book republish already reports this price rather than
        # one up to snapshot_interval_sec old.
        #
        # Deliberately does not touch top_sent: this price has not been put on
        # the TOP channel yet. Marking it sent here is precisely what used to
        # suppress the LAST field from the following MD.
        cur = self.top_cache.get(sym, TopOfBook())
        self.top_cache[sym] = replace(cur, last=fields["PX"], last_sz=fields["QTY"])

        return sym, fields

    def normalise_session_state(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``STATE`` fields for session-wide transitions."""
        session = str(payload.get("state", "")).upper()
        prev_state = str(payload.get("prev_state", "")).upper()

        if session:
            self.session_state = session

        # Replaced wholesale, not merged: the engine clears these on any
        # transition it was not given a timetable for, and that clearing is
        # the signal. Keeping the old pair would resurrect a target the
        # engine has just disowned.
        self.next_session_state = str(payload.get("next_state", "")).upper()
        self.next_session_at = str(payload.get("next_at", ""))

        fields = {"SESSION": self.session_state}
        if prev_state:
            fields["PREV"] = prev_state
        fields.update(self._next_transition_fields())
        return "*", fields

    def _next_transition_fields(self) -> dict[str, str]:
        """``NEXTPHASE``/``NEXTAT``, or nothing when no transition is scheduled.

        Both or neither: a phase with no time cannot be counted down to, and
        a time with no phase does not say what happens when it arrives.
        Absent means "nothing scheduled that this gateway knows of", which a
        client must render as silence rather than as a countdown to zero.
        """
        if not self.next_session_state or not self.next_session_at:
            return {}
        return {
            "NEXTPHASE": self.next_session_state,
            "NEXTAT": self.next_session_at,
        }

    def apply_session_to_symbols(
        self, symbols: Iterable[str]
    ) -> list[tuple[str, dict[str, str]]]:
        """Move every non-halted symbol to the current exchange session.

        Returns one ``(symbol, fields)`` pair per symbol that actually changed,
        for the caller to publish on the per-symbol ``STATE`` stream.

        A halted symbol is left alone: its halt outlives an exchange
        transition, and the engine publishes an explicit resume when it ends.
        Symbols already in the new state are skipped so a transition does not
        emit a no-op event for every instrument.

        Without this, a symbol's cached state was written once by its first
        halt and never updated again — ``state_snapshot_fields`` falls back to
        the exchange state only for symbols absent from ``symbol_state``, so
        any symbol that had ever halted reported a stale session in every
        later ``SNAP``, for the rest of the day.
        """
        updates: list[tuple[str, dict[str, str]]] = []
        for raw in symbols:
            sym = raw.upper()
            prev = self.symbol_state.get(sym, self.session_state)
            if prev == "HALTED" or prev == self.session_state:
                self.symbol_state.setdefault(sym, self.session_state)
                continue
            self.symbol_state[sym] = self.session_state
            updates.append((sym, {"SESSION": self.session_state, "PREV": prev}))
        return updates

    def normalise_halt(self, symbol: str) -> tuple[str, dict[str, str]]:
        """Return per-symbol HALTED state fields."""
        sym = symbol.upper()
        prev = self.symbol_state.get(sym) or self.session_state
        self.symbol_state[sym] = "HALTED"
        return sym, {"SESSION": "HALTED", "PREV": prev}

    def normalise_resume(self, symbol: str) -> tuple[str, dict[str, str]]:
        """Return per-symbol resume state fields.

        A resumed symbol rejoins whatever the exchange is currently doing — it
        does not necessarily go back to trading. Circuit-breaker halts expire
        on elapsed time with no session check, so an L2 halt (15 minutes by
        default) triggered a few minutes before the close resumes into
        CLOSING_AUCTION or CLOSED. Reporting CONTINUOUS there, as this used to,
        told every client the symbol was trading on a closed exchange.
        """
        sym = symbol.upper()
        prev = self.symbol_state.get(sym, "HALTED")
        resumed_to = self.session_state
        self.symbol_state[sym] = resumed_to
        return sym, {"SESSION": resumed_to, "PREV": prev}

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
            # The exchange-wide stream is the one that carries the timetable;
            # a per-symbol STATE says whether *that instrument* is halted,
            # which has nothing to do with the session clock.
            return {"SESSION": self.session_state, **self._next_transition_fields()}
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

    def normalise_auction_indicative(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``INDIC`` message.

        Where a symbol *would* uncross if the call phase ended now, published
        repeatedly while it runs. The reasoning is the one already written
        into ``normalise_cb_halt``: an imbalance indicator is what lets
        participants supply the offsetting interest that resolves it, and
        that only works if they can see it while there is still time to act.
        The opening and closing auctions are where the largest volume of the
        day prints, and until now the terminal could show a phase badge for
        them and nothing else (T-M1).

        ``INDICPX`` is **omitted** when the book would not cross, which is a
        real state during a call phase -- no price clears yet -- and is not
        the same as a price of zero. ``INDICQTY`` and ``IMBQTY`` are always
        present: zero is a true reading for both.

        Field names are shared with the circuit-breaker path deliberately. A
        reopening auction and a scheduled one are the same mechanism, and a
        client that learned to read one should not have to learn the other.
        """
        sym = str(payload.get("symbol", "")).upper()
        fields: dict[str, str] = {
            "INDICQTY": _as_int_text(payload.get("eq_qty")) or "0",
            "IMBQTY": _as_int_text(payload.get("imbalance_qty")) or "0",
        }

        indicative = payload.get("eq_price")
        if indicative is not None:
            price_text = _as_decimal(indicative)
            if price_text is not None:
                fields["INDICPX"] = price_text

        imbalance = str(payload.get("imbalance_side", "")).upper()
        if imbalance:
            fields["IMB"] = imbalance

        phase = str(payload.get("phase", "")).upper()
        if phase:
            fields["PHASE"] = phase

        return sym, fields

    def normalise_auction_result(
        self, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``AUCTION`` message.

        Unlike ``TOP``/``DEPTH``/``INDEX``, ``AUCTION`` has no persistent
        "current state" to cache or snapshot: every ``auction.result.SYMBOL``
        engine event is forwarded as its own independent CALF event.

        ``REASON`` says which uncross this was — ``SCHEDULED`` for a session
        phase change, ``REOPEN`` for a halted symbol reopening, ``RECOVERY``
        for restored GTC orders at engine startup. Without it the three are
        indistinguishable on the wire, and a client cannot tell a circuit
        breaker reopening from the closing auction.
        """
        sym = str(payload.get("symbol", "")).upper()
        fields: dict[str, str] = {
            "EQQTY": _as_int_text(payload.get("eq_qty")) or "0",
            "TRADES": _as_int_text(payload.get("trades_count")) or "0",
            "IMBQTY": _as_int_text(payload.get("imbalance_qty")) or "0",
        }
        reason = str(payload.get("reason", "")).upper()
        if reason:
            fields["REASON"] = reason
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
            source=str(payload.get("halt_source", "")).upper(),
            corridor_low=_as_decimal(payload.get("corridor_low")) or "",
            corridor_high=_as_decimal(payload.get("corridor_high")) or "",
            expansion=_as_int_text(payload.get("expansion")) or "",
        )
        self.cb_cache[sym] = state
        return sym, _cb_fields(state)

    def normalise_cb_extend(
        self, symbol: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for an ACE corridor expansion.

        The symbol stays ``HALTED`` — an extension is a continuation of the
        same halt, not a new state — so this updates the cached corridor and
        resume time in place. Without it a client keeps a ``RESUMEAT`` that has
        already passed and reports the symbol as overdue to reopen.

        ``INDICPX``/``INDICQTY``/``IMB`` are event-only. They are computed once,
        at the moment the call phase ends, so replaying them in a later ``SNAP``
        would assert a stale price for a book that has kept moving. Publishing
        them at all mirrors the imbalance indicator real venues disseminate
        during a reopening, which is what lets participants supply the
        offsetting interest that resolves the halt.
        """
        sym = symbol.upper()
        cached = self.cb_cache.get(sym, CBStatus(status="HALTED"))
        state = replace(
            cached,
            status="HALTED",
            resume_at=_ns_to_iso(payload.get("resume_at_ns")),
            corridor_low=_as_decimal(payload.get("corridor_low")) or "",
            corridor_high=_as_decimal(payload.get("corridor_high")) or "",
            expansion=_as_int_text(payload.get("expansion")) or "",
        )
        self.cb_cache[sym] = state

        fields = _cb_fields(state)
        indicative = _as_decimal(payload.get("indicative_price"))
        if indicative:
            fields["INDICPX"] = indicative
        indicative_qty = _as_int_text(payload.get("indicative_qty"))
        if indicative_qty:
            fields["INDICQTY"] = indicative_qty
        imbalance = str(payload.get("imbalance_side", "")).upper()
        if imbalance:
            fields["IMB"] = imbalance
        return sym, fields

    def normalise_cb_resume(
        self, symbol: str, payload: dict[str, Any]
    ) -> tuple[str, dict[str, str]]:
        """Return ``(symbol, fields)`` for a CALF ``CB`` resume event.

        The engine's own resume payload only carries ``symbol`` and
        ``halt_source`` — see ``normalise_cb_halt`` for why
        ``LEVEL``/``TRIGGERPX``/``REFPX``/``RESUMEAT`` are intentionally
        absent from a resume event.
        """
        sym = symbol.upper()
        state = CBStatus(
            status="ACTIVE",
            source=str(payload.get("halt_source", "")).upper(),
        )
        self.cb_cache[sym] = state

        fields = _cb_fields(state)
        # Event-only: a resume clears the halt, so the cache is back to ACTIVE
        # and a later SNAP has nothing to say about how it ended.
        reason = str(payload.get("reason", "")).upper()
        if reason:
            fields["REASON"] = reason
        if payload.get("clamped"):
            # A forced print at the corridor boundary is not a discovered
            # price; a client showing it as one would mislead.
            fields["CLAMPED"] = "1"
        print_price = _as_decimal(payload.get("print_price"))
        if print_price:
            fields["PRINTPX"] = print_price
        return sym, fields

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
        if state.corridor_low:
            fields["CORRLO"] = state.corridor_low
        if state.corridor_high:
            fields["CORRHI"] = state.corridor_high
        if state.expansion:
            fields["EXP"] = state.expansion
    if state.source:
        fields["SRC"] = state.source
    return fields
