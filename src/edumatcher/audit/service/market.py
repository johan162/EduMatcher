"""Market read models of one snapshot: the depth heatmap and order lifelines
(design §9.4 and §8, workplan AG3).

Both are built in one pass over the session's facts in canonical order and
kept with the session; a query only clips and bins them. Times are on the
receipt clock (pm-audit's, the only clock on every record), in epoch
nanoseconds. Prices are integer ticks; display text uses only the recorded
``tick_decimals``.

Depth heatmap
    Cells come from recorded ``book.<symbol>`` observations only (``depth.*``
    carries no price levels). An observation is valid from its receipt until
    the next one, a phase change (``session.state``), an uncross of its
    symbol (``auction.result``: the engine need not publish the book it
    leaves), a loss of records, or the end of its engine run. Nothing is
    interpolated. A loss is an
    ``ESEQ_GAP`` that the replay's ordering pass attached; it masks the time
    from the last record before it to the first after it, and that span has
    no cells. A halt (``circuit_breaker.halt`` to ``.resume``) is masked too,
    but the book observed while halted is evidence and keeps its cells. Bins
    are never finer than the median interval between observations (gate D6).
    A cell is the level's displayed quantity, weighted by the time each
    observation covered in its bin.

Order lifelines
    One per admitted order or quote leg and engine run, from its accepted
    ``order.ack`` (``request`` NEW) or ``quote.ack`` to its end. The end is
    one of:

    - ``filled``;
    - ``cancel.owner``: no ``cancel_reason``, so the owner's own cancel,
      quote cancel or OCO cancel;
    - ``cancel.system``: the engine's ``cancel_reason``, or an OCO sibling's
      ``oco.cancelled``;
    - ``expired``;
    - ``open``: still resting when its run's records end;
    - ``censored``: the window ends first.

    A segment is one (price, displayed quantity, state). An amendment, fill,
    iceberg refill or stop trigger starts a new segment; changes at the same
    instant are one segment. Iceberg slices follow the engine's rule: a fill
    uses up the shown slice, and the next one
    (``min(visible_qty, remaining)``) shows only once that slice is gone.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
from collections import Counter, defaultdict
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import islice, pairwise
from pathlib import Path
from typing import Any

from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.anomalies import ESEQ_GAP
from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.service.capabilities import Reason
from edumatcher.audit.service.errors import (
    CapabilityUnavailable,
    EmptyWindow,
    UnknownEntity,
)
from edumatcher.models.generated.order import PREFIX_ORDER_TRIGGERED
from edumatcher.models.generated.system import PREFIX_BOOK_CHECKPOINT

#: The clock every time in these models is on.
CLOCK = "receipt"
#: Lifeline segments one response may hold before they are aggregated per
#: level (design §8.1).
LIFELINE_SEGMENT_CAP = 5000
#: Heatmap bins one response may ask for.
MAX_BINS = 2000

MASK_GAP = "gap"
MASK_HALT = "halt"

END_FILLED = "filled"
END_OWNER = "cancel.owner"
END_SYSTEM = "cancel.system"
END_EXPIRED = "expired"
END_OPEN = "open"
END_CENSORED = "censored"

STATE_BOOK = "book"
STATE_STOP = "stop"
STATE_MARKET = "market"

_TRIGGERED = PREFIX_ORDER_TRIGGERED.rstrip(".")
_CHECKPOINT = PREFIX_BOOK_CHECKPOINT.rstrip(".")


def epoch_ns(when: datetime) -> int:
    """*when* in epoch nanoseconds (receipt stamps carry microseconds)."""
    return int(when.timestamp()) * 1_000_000_000 + when.microsecond * 1000


def price_text(ticks: int, decimals: int) -> str:
    """*ticks* as money at the recorded scale: ``9985``, 2 -> ``99.85``."""
    return f"{Decimal(ticks).scaleb(-decimals):.{decimals}f}"


def _ticks(price: float, decimals: int) -> int:
    """A recorded display price as integer ticks. The engine prints
    ``ticks / 10**decimals``; scaling back is off by far less than half a
    tick, so rounding recovers the ticks exactly."""
    return int(round(price * 10**decimals))


def _int(payload: Mapping[str, Any], name: str) -> int | None:
    value = payload.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class _Span:
    """A mask or a phase: ``kind`` is the mask kind or the phase (None:
    unknown)."""

    kind: str | None
    start: int
    end: int = -1
    detail: str = ""

    @property
    def open(self) -> bool:
        return self.end < 0


@dataclass
class _Observation:
    run: int
    start: int
    bids: tuple[tuple[int, int], ...]
    asks: tuple[tuple[int, int], ...]
    end: int = -1


@dataclass
class _Book:
    observations: list[_Observation] = field(default_factory=list)
    #: Each observation's start, for finding a window (set after the pass).
    starts: list[int] = field(default_factory=list)
    halts: list[_Span] = field(default_factory=list)
    tick_decimals: int | None = None
    #: Observations that could not be read as ticks (no scale recorded).
    unscaled: int = 0

    def close(self, t: int) -> None:
        if self.observations and self.observations[-1].end < 0:
            self.observations[-1].end = t


@dataclass
class _Segment:
    start: int
    price_ticks: int | None
    displayed_qty: int
    state: str
    cause: str
    end: int = -1


@dataclass
class _Life:
    order_id: str
    run: int
    gateway: str | None
    side: str | None
    order_type: str | None
    quote_id: str | None
    start: int
    limit: int | None
    visible: int | None
    remaining: int
    #: The quantity the order shows when on the book (an iceberg's slice).
    slice: int
    state: str
    segments: list[_Segment]
    filled: int = 0
    end: int | None = None
    end_kind: str | None = None
    end_reason: str | None = None
    #: The last record of the order's run, set when the run ends.
    run_end: int = -1

    def move(self, t: int, cause: str) -> None:
        price = self.segments[-1].price_ticks if self.state == STATE_STOP else None
        if self.state == STATE_BOOK:
            price = self.limit
        shown = self.slice if self.state == STATE_BOOK else 0
        current = self.segments[-1]
        if current.start == t:
            current.price_ticks, current.displayed_qty = price, shown
            current.state = self.state
            return
        current.end = t
        self.segments.append(_Segment(t, price, shown, self.state, cause))

    def finish(self, t: int, kind: str, reason: str | None = None) -> None:
        self.segments[-1].end = t
        self.end, self.end_kind, self.end_reason = t, kind, reason


class MarketModel:
    """Every symbol's book observations, masks, phases and lifelines."""

    def __init__(self, facts: Iterable[Fact]) -> None:
        self._books: dict[str, _Book] = {}
        self._symbols: set[str] = set()
        self._scales: dict[str, int] = {}
        self._gaps: list[_Span] = []
        self._phases: list[_Span] = []
        self._lives: dict[str, list[_Life]] = defaultdict(list)
        #: This run's lifelines by order id (an id may come back next run).
        self._orders: dict[str, _Life] = {}
        #: ``quote.new`` payloads by msg id, until their ``quote.ack``.
        self._quotes: dict[str, Mapping[str, Any]] = {}
        #: symbol -> (run, order id) of orders with events but no admission.
        self._unadmitted: dict[str, set[tuple[int, str]]] = defaultdict(set)
        self.first = 0
        self.last = 0
        #: A model loaded from a generation reads each symbol on first use.
        self._db: Path | None = None
        self._loaded: set[str] = set()
        run: int | None = None
        previous = 0
        for fact in facts:
            t = epoch_ns(fact.receipt_ts)
            if run != fact.publisher_run:
                if run is None:
                    self.first = t
                else:
                    self._end_run(previous)
                run = fact.publisher_run
                self._phase(t, None)
            else:
                lost = next((a for a in fact.anomalies if a.code == ESEQ_GAP), None)
                if lost is not None:
                    for book in self._books.values():
                        book.close(previous)
                    self._gaps.append(_Span(MASK_GAP, previous, t, lost.detail))
            self._apply(fact, t, fact.publisher_run)
            previous = t
        if run is not None:
            self._end_run(previous)
            self.last = previous
        for book in self._books.values():
            book.starts = [o.start for o in book.observations]

    # -- storage (the worker dumps, the API loads) ----------------------

    def dump(self, path: Path) -> None:
        """Write the model to a new SQLite file: globals, then one row per
        symbol, so a reader loads only the symbols it is asked about."""
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE symbols (symbol TEXT PRIMARY KEY, book TEXT, lives TEXT, "
                "unadmitted TEXT NOT NULL)"
            )
            meta = {
                "first": self.first,
                "last": self.last,
                "symbols": sorted(self._symbols),
                "scales": self._scales,
                "gaps": [asdict(g) for g in self._gaps],
                "phases": [asdict(p) for p in self._phases],
            }
            conn.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])  # fmt: skip
            for symbol in sorted(self._symbols):
                book = self._books.get(symbol)
                conn.execute(
                    "INSERT INTO symbols VALUES (?, ?, ?, ?)",
                    (
                        symbol,
                        json.dumps(_book_dict(book)) if book is not None else None,
                        json.dumps(
                            [_life_dict(life) for life in self._lives.get(symbol, ())]
                        ),
                        json.dumps(sorted(self._unadmitted.get(symbol, ()))),
                    ),
                )
            conn.commit()

    @classmethod
    def load(cls, path: Path) -> "MarketModel":
        """A model over a dumped file; each symbol is read on first use."""
        model = cls.__new__(cls)
        model._books = {}
        model._lives = defaultdict(list)
        model._unadmitted = defaultdict(set)
        model._orders = {}
        model._quotes = {}
        model._db = path
        model._loaded = set()
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            meta = {
                k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM meta")
            }
        model.first = int(meta["first"])
        model.last = int(meta["last"])
        model._symbols = set(meta["symbols"])
        model._scales = {str(k): int(v) for k, v in meta["scales"].items()}
        model._gaps = [_Span(**g) for g in meta["gaps"]]
        model._phases = [_Span(**p) for p in meta["phases"]]
        return model

    def _ensure(self, symbol: str) -> None:
        """Read `symbol`'s rows of a loaded model, once."""
        if self._db is None or symbol in self._loaded:
            return
        with closing(sqlite3.connect(f"file:{self._db}?mode=ro", uri=True)) as conn:
            row = conn.execute(
                "SELECT book, lives, unadmitted FROM symbols WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        if row is not None:
            book, lives, unadmitted = row
            if book is not None:
                self._books[symbol] = _book_from(json.loads(book))
            self._lives[symbol] = [_life_from(d) for d in json.loads(lives)]
            self._unadmitted[symbol] = {
                (int(r), str(o)) for r, o in json.loads(unadmitted)
            }
        self._loaded.add(symbol)

    # -- queries --------------------------------------------------------

    def heatmap(
        self, symbol: str, start: int | None, end: int | None, bins: int
    ) -> dict[str, Any]:
        """Displayed depth per level and bin of [*start*, *end*), with the
        cadence, masks and phases (see the module docstring)."""
        self._known(symbol)
        self._ensure(symbol)
        book = self._books.get(symbol, _Book())
        if not book.observations:
            if book.unscaled:
                raise CapabilityUnavailable(
                    Reason.NO_TICK_SCALE,
                    f"no book.{symbol} observation states its tick_decimals",
                )
            raise CapabilityUnavailable(
                Reason.NO_BOOK_OBSERVATIONS,
                f"no book.{symbol} observation was recorded",
            )
        start, end = self._window(start, end)
        intervals = [
            b.start - a.start for a, b in pairwise(book.observations) if a.run == b.run
        ]
        median = int(statistics.median(intervals)) if intervals else None
        width = max(math.ceil((end - start) / bins), median or 0, 1)
        columns = [
            _Column(start + i * width, min(start + (i + 1) * width, end))
            for i in range(math.ceil((end - start) / width))
        ]
        first = max(bisect_right(book.starts, start) - 1, 0)
        for obs in islice(book.observations, first, None):
            if obs.start >= end:
                break
            lo, hi = max(obs.start, start), min(obs.end, end)
            if hi <= lo:
                continue
            for i in range((lo - start) // width, (hi - 1 - start) // width + 1):
                columns[i].add(obs, lo, hi)
        masks = [m for m in (*self._gaps, *book.halts) if _overlaps(m, start, end)]
        levels = sorted({p for c in columns for p in (*c.bids, *c.asks)})
        decimals = book.tick_decimals
        return {
            "clock": CLOCK,
            "tick_decimals": decimals,
            "from_ns": start,
            "to_ns": end,
            "bin_ns": width,
            "bins": len(columns),
            "requested_bins": bins,
            "cadence": {
                "observations": len(book.observations),
                "median_interval_ns": median,
                "min_interval_ns": min(intervals) if intervals else None,
                "max_interval_ns": max(intervals) if intervals else None,
            },
            "levels": [
                {
                    "price_ticks": p,
                    "price": price_text(p, decimals) if decimals is not None else None,
                }
                for p in levels
            ],
            "columns": [c.render(masks) for c in columns],
            "masks": [
                {
                    "kind": m.kind,
                    "from_ns": max(m.start, start),
                    "to_ns": min(m.end, end),
                    "detail": m.detail,
                }
                for m in masks
            ],
            "phases": [
                {
                    "phase": p.kind,
                    "from_ns": max(p.start, start),
                    "to_ns": min(p.end, end),
                }
                for p in self._phases
                if _overlaps(p, start, end)
            ],
        }

    def lifelines(
        self, symbol: str, start: int | None, end: int | None, gateway: str | None
    ) -> dict[str, Any]:
        """The lifelines of *symbol* in [*start*, *end*), clipped to it; per
        level aggregates instead when they would exceed
        :data:`LIFELINE_SEGMENT_CAP` segments."""
        self._known(symbol)
        self._ensure(symbol)
        start, end = self._window(start, end)
        rows: list[dict[str, Any]] = []
        for life in self._lives.get(symbol, ()):
            if life.start >= end:
                break  # admitted in order: the rest start later still
            stop = life.end if life.end is not None else life.run_end
            if (gateway and life.gateway != gateway) or not (
                life.start < end and stop >= start
            ):
                continue
            segments = [
                {
                    "start_ns": max(s.start, start),
                    "end_ns": min(s.end, end),
                    "price_ticks": s.price_ticks,
                    "displayed_qty": s.displayed_qty,
                    "state": s.state,
                    "cause": s.cause,
                }
                for s in life.segments
                if s.start < end and (s.end > start or s.start == s.end >= start)
            ]
            ending: tuple[str | None, int | None, str | None]
            if life.end is not None and life.end < end:
                ending = (life.end_kind, life.end, life.end_reason)
            elif life.end is None and life.run_end < end:
                ending = (END_OPEN, None, None)
            else:
                ending = (END_CENSORED, None, None)
            rows.append(
                {
                    "order_id": life.order_id,
                    "run": life.run,
                    "gateway": life.gateway,
                    "side": life.side,
                    "order_type": life.order_type,
                    "quote_id": life.quote_id,
                    "start_ns": life.start,
                    "start_censored": life.start < start,
                    "end": ending[0],
                    "end_ns": ending[1],
                    "end_reason": ending[2],
                    "filled_qty": life.filled,
                    "segments": segments,
                }
            )
        total = sum(len(r["segments"]) for r in rows)
        aggregated = total > LIFELINE_SEGMENT_CAP
        return {
            "clock": CLOCK,
            "tick_decimals": self._scales.get(symbol),
            "from_ns": start,
            "to_ns": end,
            "gateway": gateway,
            "aggregated": aggregated,
            "segment_cap": LIFELINE_SEGMENT_CAP,
            "segments": total,
            "without_admission": len(self._unadmitted.get(symbol, ())),
            "lifelines": [] if aggregated else rows,
            "levels": _per_level(rows) if aggregated else [],
        }

    # -- the pass -------------------------------------------------------

    def _apply(self, fact: Fact, t: int, run: int) -> None:
        p = fact.payload
        symbol = fact.symbol
        if symbol:
            self._symbols.add(symbol)
            decimals = _int(p, "tick_decimals")
            if decimals is not None:
                self._scales.setdefault(symbol, decimals)
        kind = fact.kind
        if kind == kinds.BOOK and symbol:
            self._observe(symbol, p, t, run)
        elif kind == kinds.SESSION_STATE:
            state = p.get("state")
            if isinstance(state, str) and state != self._phases[-1].kind:
                for book in self._books.values():
                    book.close(t)
                self._phase(t, state)
        elif kind == kinds.AUCTION_RESULT and symbol:
            self._book(symbol).close(t)
        elif kind == _CHECKPOINT:
            # AGF1: the phase a run starts in is on its STARTUP checkpoints.
            phase = p.get("phase")
            if p.get("reason") == "STARTUP" and self._phases[-1].kind is None:
                self._phase(t, phase if isinstance(phase, str) else None)
        elif kind == kinds.CIRCUIT_BREAKER_HALT and symbol:
            halts = self._book(symbol).halts
            if not halts or not halts[-1].open:
                halts.append(_Span(MASK_HALT, t, detail=str(p.get("level") or "")))
        elif kind == kinds.CIRCUIT_BREAKER_RESUME and symbol:
            halts = self._book(symbol).halts
            if halts and halts[-1].open:
                halts[-1].end = t
        elif kind == kinds.ORDER_ACK:
            self._on_ack(fact, t, run)
        elif kind == kinds.QUOTE_NEW and fact.msg_id:
            self._quotes[fact.msg_id] = p
        elif kind == kinds.QUOTE_ACK:
            self._on_quote_ack(fact, t, run)
        elif kind in (
            kinds.ORDER_FILL,
            kinds.ORDER_AMENDED,
            kinds.ORDER_CANCELLED,
            kinds.ORDER_EXPIRED,
            _TRIGGERED,
        ):
            self._on_order_event(fact, t, run)
        elif kind == kinds.OCO_CANCELLED:
            life = self._orders.get(str(p.get("cancelled_order_id")))
            if life is not None and life.end is None:
                reason = p.get("reason") or "OCO_SIBLING_CANCELLED"
                life.finish(t, END_SYSTEM, str(reason))

    def _observe(self, symbol: str, p: Mapping[str, Any], t: int, run: int) -> None:
        book = self._book(symbol)
        book.close(t)
        decimals = _int(p, "tick_decimals")
        if decimals is None:
            decimals = self._scales.get(symbol)
        if decimals is None:
            book.unscaled += 1
            return
        if book.tick_decimals is None:
            book.tick_decimals = decimals

        def levels(side: str) -> tuple[tuple[int, int], ...]:
            return tuple(
                (_ticks(lv["price"], decimals), int(lv["qty"]))
                for lv in p.get(side) or ()
            )

        book.observations.append(_Observation(run, t, levels("bids"), levels("asks")))

    def _on_ack(self, fact: Fact, t: int, run: int) -> None:
        p = fact.payload
        order_id = p.get("order_id")
        symbol = p.get("symbol") or fact.symbol
        if (
            not isinstance(order_id, str)
            or not isinstance(symbol, str)
            or p.get("accepted") is not True
            or p.get("request", "NEW") != "NEW"
            or order_id in self._orders
        ):
            return
        self._admit(
            order_id,
            symbol,
            t,
            run,
            gateway=fact.actor,
            side=p.get("side"),
            order_type=p.get("order_type"),
            quote_id=None,
            qty=_int(p, "qty") or 0,
            limit=_int(p, "price_ticks"),
            stop=_int(p, "stop_price_ticks"),
            visible=_int(p, "visible_qty"),
        )

    def _on_quote_ack(self, fact: Fact, t: int, run: int) -> None:
        p = fact.payload
        quote = self._quotes.pop(fact.causation_id or "", None)
        if quote is None or p.get("accepted") is not True:
            return
        symbol = p.get("symbol") or quote.get("symbol")
        if not isinstance(symbol, str):
            return
        for side, leg in (("BUY", "bid"), ("SELL", "ask")):
            order_id = p.get(f"{leg}_order_id")
            qty = _int(quote, f"{leg}_qty")
            if isinstance(order_id, str) and qty:
                self._admit(
                    order_id,
                    symbol,
                    t,
                    run,
                    gateway=fact.actor,
                    side=side,
                    order_type=None,
                    quote_id=p.get("quote_id"),
                    qty=qty,
                    limit=_int(quote, f"{leg}_price_ticks"),
                    stop=None,
                    visible=None,
                )

    def _admit(
        self,
        order_id: str,
        symbol: str,
        t: int,
        run: int,
        *,
        gateway: str | None,
        side: Any,
        order_type: Any,
        quote_id: Any,
        qty: int,
        limit: int | None,
        stop: int | None,
        visible: int | None,
    ) -> None:
        if stop is not None:
            state, price = STATE_STOP, stop
        elif limit is None:
            state, price = STATE_MARKET, None
        else:
            state, price = STATE_BOOK, limit
        piece = min(visible, qty) if visible is not None else qty
        shown = piece if state == STATE_BOOK else 0
        life = _Life(
            order_id=order_id,
            run=run,
            gateway=gateway,
            side=side if isinstance(side, str) else None,
            order_type=order_type if isinstance(order_type, str) else None,
            quote_id=quote_id if isinstance(quote_id, str) else None,
            start=t,
            limit=limit,
            visible=visible,
            remaining=qty,
            slice=piece,
            state=state,
            segments=[_Segment(t, price, shown, state, "admission")],
        )
        self._orders[order_id] = life
        self._lives[symbol].append(life)

    def _on_order_event(self, fact: Fact, t: int, run: int) -> None:
        p = fact.payload
        order_id = p.get("order_id")
        if not isinstance(order_id, str):
            return
        life = self._orders.get(order_id)
        if life is None:
            symbol = p.get("symbol") or fact.symbol
            if isinstance(symbol, str):
                self._unadmitted[symbol].add((run, order_id))
            return
        if life.end is not None:
            return
        kind = fact.kind
        if kind == kinds.ORDER_FILL:
            fill = _int(p, "fill_qty") or 0
            life.filled += fill
            remaining = _int(p, "remaining_qty")
            life.remaining = life.remaining - fill if remaining is None else remaining
            if p.get("status") == "FILLED" or life.remaining <= 0:
                life.finish(t, END_FILLED)
                return
            cause = "fill"
            if life.visible is None:
                life.slice = life.remaining
            else:
                life.slice = max(0, life.slice - fill)
                if life.slice == 0:
                    life.slice = min(life.visible, life.remaining)
                    cause = "refill"
            life.move(t, cause)
        elif kind == kinds.ORDER_AMENDED:
            life.limit = _int(p, "price_ticks") or life.limit
            remaining = _int(p, "remaining_qty")
            life.remaining = life.remaining if remaining is None else remaining
            if life.visible is None:
                life.slice = life.remaining
            elif p.get("priority_reset"):
                life.slice = min(life.visible, life.remaining)
            else:
                life.slice = min(life.slice, life.remaining)
            life.move(t, "amend")
        elif kind == kinds.ORDER_CANCELLED:
            reason = p.get("cancel_reason")
            if reason:
                life.finish(t, END_SYSTEM, str(reason))
            else:
                life.finish(t, END_OWNER)
        elif kind == kinds.ORDER_EXPIRED:
            life.finish(t, END_EXPIRED)
        else:  # order.triggered
            life.state = STATE_BOOK if p.get("becomes") == "LIMIT" else STATE_MARKET
            life.move(t, "trigger")

    # -- helpers --------------------------------------------------------

    def _book(self, symbol: str) -> _Book:
        book = self._books.get(symbol)
        if book is None:
            book = self._books[symbol] = _Book()
        return book

    def _phase(self, t: int, phase: str | None) -> None:
        if self._phases and self._phases[-1].open:
            current = self._phases[-1]
            if current.start == t:
                current.kind = phase
                return
            current.end = t
        self._phases.append(_Span(phase, t))

    def _end_run(self, t: int) -> None:
        for book in self._books.values():
            book.close(t)
            if book.halts and book.halts[-1].open:
                book.halts[-1].end = t
        if self._phases and self._phases[-1].open:
            self._phases[-1].end = t
        for life in self._orders.values():
            life.run_end = t
            if life.end is None:
                life.segments[-1].end = t
        self._orders = {}
        self._quotes = {}

    def _known(self, symbol: str) -> None:
        if symbol not in self._symbols:
            raise UnknownEntity(f"no record of symbol {symbol!r} in this snapshot")

    def _window(self, start: int | None, end: int | None) -> tuple[int, int]:
        """[*start*, *end*), defaulting to the whole snapshot."""
        start = self.first if start is None else start
        end = self.last + 1 if end is None else end
        if start >= end:
            raise EmptyWindow(f"the window from {start} to {end} holds no time")
        return start, end


class _Column:
    """One heatmap bin while it is filled."""

    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end
        self.covered = 0
        self.observations = 0
        self.newest: tuple[int, int] | None = None
        #: price ticks -> quantity x nanoseconds shown.
        self.bids: Counter[int] = Counter()
        self.asks: Counter[int] = Counter()

    def add(self, obs: _Observation, lo: int, hi: int) -> None:
        lo, hi = max(lo, self.start), min(hi, self.end)
        if hi <= lo:
            return
        span = hi - lo
        self.covered += span
        self.observations += 1
        self.newest = (obs.start, hi)
        for price, qty in obs.bids:
            self.bids[price] += qty * span
        for price, qty in obs.asks:
            self.asks[price] += qty * span

    def render(self, masks: list[_Span]) -> dict[str, Any]:
        def cells(side: Counter[int]) -> list[tuple[int, float]]:
            return [(p, side[p] / self.covered) for p in sorted(side)]

        return {
            "start_ns": self.start,
            "end_ns": self.end,
            "covered_ns": self.covered,
            "observations": self.observations,
            "age_ns": self.newest[1] - self.newest[0] if self.newest else None,
            "masks": sorted(
                {str(m.kind) for m in masks if _overlaps(m, self.start, self.end)}
            ),
            "bids": cells(self.bids),
            "asks": cells(self.asks),
        }


def _book_dict(book: _Book) -> dict[str, Any]:
    return {
        "observations": [
            [o.run, o.start, o.end, o.bids, o.asks] for o in book.observations
        ],
        "halts": [asdict(h) for h in book.halts],
        "tick_decimals": book.tick_decimals,
        "unscaled": book.unscaled,
    }


def _book_from(d: dict[str, Any]) -> _Book:
    observations = [
        _Observation(
            int(run),
            int(start),
            tuple((int(p), int(q)) for p, q in bids),
            tuple((int(p), int(q)) for p, q in asks),
            int(end),
        )
        for run, start, end, bids, asks in d["observations"]
    ]
    return _Book(
        observations=observations,
        starts=[o.start for o in observations],
        halts=[_Span(**h) for h in d["halts"]],
        tick_decimals=d["tick_decimals"],
        unscaled=int(d["unscaled"]),
    )


def _life_dict(life: _Life) -> dict[str, Any]:
    return asdict(life)


def _life_from(d: dict[str, Any]) -> _Life:
    fields = dict(d)
    fields["segments"] = [_Segment(**seg) for seg in d["segments"]]
    return _Life(**fields)


def _overlaps(span: _Span, start: int, end: int) -> bool:
    """Whether *span* touches [*start*, *end*); an instant counts when it
    falls inside."""
    if span.start == span.end:
        return start <= span.start < end
    return span.start < end and span.end > start


def _per_level(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Lifeline segments summed per (side, state, price): the orders, the
    segments, the largest displayed quantity, the extent, and how the
    lifelines whose last segment is there ended."""
    levels: dict[tuple[Any, str, Any], dict[str, Any]] = {}
    for row in rows:
        for seg in row["segments"]:
            key = (row["side"], seg["state"], seg["price_ticks"])
            level = levels.get(key)
            if level is None:
                level = levels[key] = {
                    "side": row["side"],
                    "state": seg["state"],
                    "price_ticks": seg["price_ticks"],
                    "orders": set(),
                    "segments": 0,
                    "max_displayed_qty": 0,
                    "from_ns": seg["start_ns"],
                    "to_ns": seg["end_ns"],
                    "ends": Counter(),
                }
            level["orders"].add((row["run"], row["order_id"]))
            level["segments"] += 1
            level["max_displayed_qty"] = max(level["max_displayed_qty"], seg["displayed_qty"])  # fmt: skip
            level["from_ns"] = min(level["from_ns"], seg["start_ns"])
            level["to_ns"] = max(level["to_ns"], seg["end_ns"])
        if row["segments"]:
            last = row["segments"][-1]
            levels[(row["side"], last["state"], last["price_ticks"])]["ends"][row["end"]] += 1  # fmt: skip
    return [
        {**level, "orders": len(level["orders"]), "ends": dict(level["ends"])}
        for _key, level in sorted(
            levels.items(),
            key=lambda kv: (str(kv[0][0]), kv[0][1], -1 if kv[0][2] is None else kv[0][2]),  # fmt: skip
        )
    ]


__all__ = [
    "CLOCK",
    "LIFELINE_SEGMENT_CAP",
    "MAX_BINS",
    "MarketModel",
    "epoch_ns",
    "price_text",
]
