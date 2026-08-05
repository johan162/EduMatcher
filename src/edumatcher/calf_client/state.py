"""Optional client-side caches over the CALF frame stream.

Every consumer that renders a market screen ends up writing these, and one
of them -- the top-of-book merge -- is a correctness trap rather than a
convenience: ``MD`` messages omit sides that did not move, so treating one
as a full replacement blanks whichever side was unchanged. Keeping that in
the library means it is written once.

This layer is entirely optional. :class:`~edumatcher.calf_client.CalfClient`
maintains a :class:`MarketState` only when asked, and a caller that wants
raw frames and its own bookkeeping can ignore this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edumatcher.md_gateway.protocol import CalfFrame


@dataclass
class TopOfBook:
    """Latest known top of book for one symbol.

    Fields are the wire strings, not floats. Prices are decimal text on the
    wire and a client that wants them formatted should go through
    :class:`~edumatcher.calf_client.refdata.ReferenceData`; parsing to
    binary floating point and back is how a price picks up a rounding
    artefact it never had.
    """

    symbol: str
    bid: str | None = None
    bid_size: str | None = None
    ask: str | None = None
    ask_size: str | None = None
    last: str | None = None
    #: ``SEQ`` and ``TS`` of the message this state was last updated by.
    seq: int = 0
    ts: str = ""

    def apply(self, fields: dict[str, str]) -> None:
        """Merge one ``SNAP`` or ``MD`` payload.

        A field absent from an ``MD`` means "unchanged since the last
        message that carried it", never "now empty" -- so absent keys leave
        the cached value alone. This is the whole reason the cache exists.
        """
        self.bid = fields.get("BID", self.bid)
        self.bid_size = fields.get("BIDSZ", self.bid_size)
        self.ask = fields.get("ASK", self.ask)
        self.ask_size = fields.get("ASKSZ", self.ask_size)
        self.last = fields.get("LAST", self.last)


@dataclass
class DepthLevel:
    """One price level of the order book ladder."""

    price: str
    qty: str
    orders: str


@dataclass
class DepthBook:
    """Both sides of the Level 2 ladder for one symbol, best price first."""

    symbol: str
    bids: list[DepthLevel] = field(default_factory=list)
    asks: list[DepthLevel] = field(default_factory=list)
    seq: int = 0
    ts: str = ""


@dataclass
class HaltStatus:
    """Circuit-breaker detail for one symbol, from the ``CB`` channel.

    ``STATE`` carries a bare halted/not-halted flag; this is the operational
    detail behind it -- why, at what reference price, and whether it ends by
    itself.
    """

    symbol: str
    status: str
    level: str | None = None
    trigger_px: str | None = None
    ref_px: str | None = None
    #: Scheduled auto-resume time. A halt does not necessarily end when this
    #: arrives: an ACE reopening republishes an updated one, so a client that
    #: ignores later ``CB`` messages will show a time that has already passed.
    resume_at: str | None = None
    source: str | None = None

    @property
    def halted(self) -> bool:
        return self.status == "HALTED"


def _parse_levels(encoded: str | None) -> list[DepthLevel]:
    """Decode ``PRICE:QTY:COUNT,PRICE:QTY:COUNT,...``.

    A side is omitted from the wire entirely, not sent empty, when that
    side of the book has no resting orders.
    """
    if not encoded:
        return []
    levels: list[DepthLevel] = []
    for entry in encoded.split(","):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        levels.append(DepthLevel(price=parts[0], qty=parts[1], orders=parts[2]))
    return levels


class MarketState:
    """Everything a CALF feed says, kept current as frames arrive.

    Feed it every frame; read whichever parts matter. Nothing here decides
    what to display -- it only removes the need for each consumer to
    re-derive the same state from the same deltas.
    """

    def __init__(self) -> None:
        self._top: dict[str, TopOfBook] = {}
        self._depth: dict[str, DepthBook] = {}
        self._halts: dict[str, HaltStatus] = {}
        self._last_trade: dict[str, CalfFrame] = {}
        self._symbol_session: dict[str, str] = {}
        self._session: str | None = None
        self._session_prev: str | None = None

    # -- accessors ------------------------------------------------------

    def top(self, symbol: str) -> TopOfBook | None:
        """Merged top of book, or ``None`` before the first message."""
        return self._top.get(symbol)

    def depth(self, symbol: str) -> DepthBook | None:
        return self._depth.get(symbol)

    def halt(self, symbol: str) -> HaltStatus | None:
        """Circuit-breaker detail, present only once a ``CB`` has arrived."""
        return self._halts.get(symbol)

    def last_trade(self, symbol: str) -> CalfFrame | None:
        return self._last_trade.get(symbol)

    @property
    def session(self) -> str | None:
        """Exchange-wide session phase, from ``STATE`` with ``SYM=*``."""
        return self._session

    @property
    def session_prev(self) -> str | None:
        """The phase the exchange was in before the current one."""
        return self._session_prev

    def symbol_session(self, symbol: str) -> str | None:
        """One symbol's own state, which is not the exchange's.

        ``STATE|SYM=*`` carries session-wide transitions; ``STATE|SYM=AAPL``
        carries that symbol's halts and resumes. They are different streams
        and a symbol can be ``HALTED`` while the exchange is ``CONTINUOUS``.
        """
        return self._symbol_session.get(symbol)

    def symbols(self) -> list[str]:
        """Every symbol seen on any channel so far, sorted."""
        seen = set(self._top) | set(self._depth) | set(self._symbol_session)
        return sorted(seen)

    # -- ingestion ------------------------------------------------------

    def apply(self, frame: CalfFrame) -> None:
        """Fold one frame into the cached state. Unknown channels are ignored."""
        channel = frame.fields.get("CH", "")
        symbol = frame.fields.get("SYM", "")
        if not channel or not symbol:
            return

        try:
            seq = int(frame.fields.get("SEQ", "0"))
        except ValueError:
            seq = 0
        ts = frame.fields.get("TS", "")

        if channel == "TOP":
            book = self._top.get(symbol)
            if book is None:
                book = TopOfBook(symbol=symbol)
                self._top[symbol] = book
            book.apply(frame.fields)
            book.seq = seq
            book.ts = ts

        elif channel == "TRADE" and frame.msg_type == "TRADE":
            # Guarded on msg_type: a SNAP on TRADE carries an envelope and
            # no payload (an older gateway sends one after REPLAY_MISS), and
            # caching it would record a print of nothing at no price.
            self._last_trade[symbol] = frame

        elif channel == "STATE":
            session = frame.fields.get("SESSION")
            if session is None:
                return
            if symbol == "*":
                self._session_prev = frame.fields.get("PREV", self._session_prev)
                self._session = session
            else:
                self._symbol_session[symbol] = session

        elif channel == "DEPTH":
            self._depth[symbol] = DepthBook(
                symbol=symbol,
                bids=_parse_levels(frame.fields.get("BIDS")),
                asks=_parse_levels(frame.fields.get("ASKS")),
                seq=seq,
                ts=ts,
            )

        elif channel == "CB":
            status = frame.fields.get("STATUS")
            if status is None:
                return
            self._halts[symbol] = HaltStatus(
                symbol=symbol,
                status=status,
                level=frame.fields.get("LEVEL"),
                trigger_px=frame.fields.get("TRIGGERPX"),
                ref_px=frame.fields.get("REFPX"),
                resume_at=frame.fields.get("RESUMEAT"),
                source=frame.fields.get("SRC"),
            )
