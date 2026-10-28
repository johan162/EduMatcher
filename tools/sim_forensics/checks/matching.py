"""D — matching correctness, and C7, from a replay of the audit trail.

The audit holds every engine message in publish order (see ``audit.py``),
and every message the engine sends for one inbound command carries that
command's ``chain``. One pass replays the run: each chain is one *dispatch*,
and a per-symbol book is rebuilt order by order from what the dispatch says
happened -- acks put orders in, trades take quantity out, cancels and
expiries remove them. The replay does not match; it re-derives, from its own
model of the matching rules, what each trade had to be, and flags a trade
the model would not have made:

- the aggressor of each trade is the command's order, or a stop the model's
  cascade triggered (checkpoints after each matching step, as the engine's
  ``OrderBook.process`` runs them; trailing stops ratchet at each one);
- its counterparty is the first order, in price-time priority, at the best
  opposite price -- an iceberg showing only its slice and refilling at the
  back of its level;
- an uncross prints at the volume-maximising price (ties: least surplus,
  then lowest price) and fills both sides in priority.

Orders cancelled anywhere in a dispatch (SMP, a pulled quote leg, an OCO
sibling) are left out of "who should have traded first": the stream does
not say whether the cancel came before or after a given trade.

The engine's own full-book snapshots (``book.<SYM>``) are the oracle for the
replay itself (D9): wherever replay and engine disagree, one of them is
wrong, and the first snapshot after the divergence names the place.

In a call phase the engine publishes each symbol's indicative uncross
(``auction.indicative.<SYM>``) on a timer, between dispatches; D10 compares
it with the uncross the replayed book would make at that point.
"""

from __future__ import annotations

import heapq
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import Line, audit_files, lines
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

BUY, SELL = "BUY", "SELL"
_STOP_TYPES = ("STOP", "STOP_LIMIT", "TRAILING_STOP")
#: The removal reasons that mean the engine triggered a stop (a MARKET that
#: found no liquidity, or one that met its owner's own order).
_TRIGGERED_REASONS = ("INSUFFICIENT_LIQUIDITY", "SELF_MATCH_PREVENTED")
#: Samples kept per check; the report shows fewer.
_KEEP = 50

#: Topics the replay reads, by exact topic and by prefix up to the last dot.
_EXACT = {
    "order.new": "new",
    "quote.new": "quote",
    "order.oco": "oco",
    "trade.executed": "trade",
    "session.state": "phase",
    "system.startup_recovery": "startup",
}
_PREFIX = {
    "order.ack.": "ack",
    "quote.ack.": "quote_ack",
    "oco.ack.": "oco_ack",
    "order.fill.": "fill",
    "order.cancelled.": "cancelled",
    "order.expired.": "expired",
    "oco.cancelled.": "oco_cancelled",
    "auction.result.": "auction",
    "book.": "book",
    "auction.indicative.": "indicative",
}
#: Engine features this replay does not model; a run that uses them is
#: still replayed, and the D9 note says so.
_UNMODELLED = ("order.amended.", "combo.", "circuit_breaker.")


@dataclass(slots=True)
class _Order:
    """An order as the replay holds it: resting, armed, or being matched."""

    id: str
    side: str
    kind: str  # order type; a triggered stop becomes MARKET or LIMIT
    price: int | None  # limit, in ticks
    remaining: int
    gw: str
    smp: str
    peak: int | None = None  # an iceberg's visible slice
    shown: int = 0  # what rests visibly
    stop: int | None = None
    offset: int | None = None
    seq: int = 0  # time priority
    triggered: bool = False
    armed_as: str = ""  # the stop type a triggered stop was
    traded: bool = False


class _Book:
    def __init__(self, symbol: str, td: int) -> None:
        self.symbol = symbol
        self.td = td
        #: Side → price → orders in priority order.
        self.levels: dict[str, dict[int, dict[str, _Order]]] = {BUY: {}, SELL: {}}
        #: Best-first heaps of level prices (bids negated), pruned lazily.
        self._heaps: dict[str, list[int]] = {BUY: [], SELL: []}
        self.orders: dict[str, _Order] = {}
        #: Armed STOP / STOP_LIMIT, and TRAILING_STOP in arming order (the
        #: engine's list order).
        self.stops: dict[str, _Order] = {}
        self.trailing: dict[str, _Order] = {}
        self.last: int | None = None
        self.qty = {BUY: 0, SELL: 0}
        self.count = {BUY: 0, SELL: 0}
        #: Bumped by every change to the resting orders.
        self.version = 0

    def best(self, side: str) -> int | None:
        heap, levels = self._heaps[side], self.levels[side]
        while heap:
            price = -heap[0] if side == BUY else heap[0]
            if price in levels:
                return price
            heapq.heappop(heap)
        return None

    def top(self, side: str, skip: set[str], keep: _Order) -> _Order | None:
        """First order in priority on *side*, passing over orders in *skip*
        other than *keep*."""
        best = self.best(side)
        if best is None:
            return None
        for o in self.levels[side][best].values():
            if o is keep or o.id not in skip:
                return o
        for price in sorted(self.levels[side], reverse=side == BUY):
            for o in self.levels[side][price].values():
                if o is keep or o.id not in skip:
                    return o
        return None

    def rest(self, o: _Order, seq: int) -> None:
        assert o.price is not None
        self.version += 1
        o.seq = seq
        o.shown = min(o.peak, o.remaining) if o.peak else o.remaining
        levels = self.levels[o.side]
        if o.price not in levels:
            levels[o.price] = {}
            heapq.heappush(self._heaps[o.side], -o.price if o.side == BUY else o.price)
        levels[o.price][o.id] = o
        self.orders[o.id] = o
        self.qty[o.side] += o.shown
        self.count[o.side] += 1

    def arm(self, o: _Order, seq: int) -> None:
        o.seq = seq
        (self.trailing if o.kind == "TRAILING_STOP" else self.stops)[o.id] = o

    def remove(self, order_id: str) -> _Order | None:
        o = self.orders.pop(order_id, None)
        if o is None:
            return self.stops.pop(order_id, None) or self.trailing.pop(order_id, None)
        self.version += 1
        assert o.price is not None
        level = self.levels[o.side][o.price]
        del level[order_id]
        if not level:
            del self.levels[o.side][o.price]
        self.qty[o.side] -= o.shown
        self.count[o.side] -= 1
        return o

    def fill(self, o: _Order, qty: int, seq: int) -> None:
        """A resting order trades *qty*; a used-up iceberg slice refills at
        the back of its level."""
        assert o.price is not None
        self.version += 1
        o.remaining -= qty
        o.shown -= qty
        self.qty[o.side] -= qty
        if o.remaining <= 0:
            self.remove(o.id)
        elif o.shown <= 0:
            self.qty[o.side] -= o.shown  # an over-fill (flagged by the caller)
            o.shown = min(o.peak or o.remaining, o.remaining)
            self.qty[o.side] += o.shown
            level = self.levels[o.side][o.price]
            del level[o.id]
            level[o.id] = o
            o.seq = seq

    def view(self, side: str) -> dict[int, tuple[int, int]]:
        return {
            price: (sum(o.shown for o in level.values()), len(level))
            for price, level in self.levels[side].items()
        }


@dataclass
class _Dispatch:
    chain: str
    new: dict[str, Any] | None = None
    quote: dict[str, Any] | None = None
    oco: dict[str, Any] | None = None
    acks: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    quote_ack: dict[str, Any] | None = None
    oco_ack: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    fills: list[dict[str, Any]] = field(default_factory=list)
    #: Order id → reason, for every order this dispatch cancelled or expired.
    dead: dict[str, str] = field(default_factory=dict)
    #: Symbol of each dead order the payload names.
    dead_symbol: dict[str, str] = field(default_factory=dict)
    auctions: dict[str, dict[str, Any]] = field(default_factory=dict)
    phase: str | None = None
    startup: bool = False


class _Replay:
    def __init__(self, symbols: dict[str, dict[str, Any]], smp: dict[str, str]):
        self.td = {s: int(c.get("tick_decimals", 2)) for s, c in symbols.items()}
        self.smp = smp
        self.books: dict[str, _Book] = {}
        self.counts: Counter[str] = Counter()
        self.samples: dict[str, list[Sample]] = defaultdict(list)
        self.phase: str | None = None
        self.started = False
        self.seq = 0
        self.dispatches = 0
        self.snapshots = 0
        self.snapshots_differing = 0
        self.diverged: set[str] = set()
        self.auction_self_trades = 0
        self.trades_replayed = 0
        self.stops_triggered = 0
        self.uncrosses = 0
        self.unmodelled: Counter[str] = Counter()
        self.symbol_of: dict[str, str] = {}
        self.indicatives = 0
        self.indicatives_skipped = 0
        #: Symbol → (book version, the uncross it makes).
        self._uncross_at: dict[str, tuple[int, _Uncross | None]] = {}
        # Per dispatch:
        self.chain = ""
        self.trades: list[dict[str, Any]] = []
        self.ti = 0
        self.dead: dict[str, str] = {}
        self.dead_symbol: dict[str, str] = {}
        self.triggered: list[_Order] = []
        self.remaining_after: dict[tuple[str, str], int] = {}

    # --- driving ---------------------------------------------------------

    def run(self, stream: Iterable[Line]) -> None:
        pending: list[tuple[str, str, dict[str, Any]]] = []
        chain = ""
        for topic, line_chain, body, *_ in stream:
            kind = _EXACT.get(topic) or _PREFIX.get(topic[: topic.rfind(".") + 1])
            if kind is None:
                if topic.startswith(_UNMODELLED):
                    self.unmodelled[topic[: topic.rfind(".") + 1]] += 1
                continue
            if not self.started and not pending:
                if kind != "startup":
                    raise Skipped(
                        "the audit does not reach back to the engine's start "
                        f"(first line: {topic}); the books cannot be rebuilt"
                    )
            if kind in ("book", "indicative"):
                self._flush(chain, pending)
                pending = []
                if kind == "book":
                    self._snapshot(json.loads(body))
                else:
                    self._indicative(json.loads(body))
                continue
            if line_chain != chain:
                self._flush(chain, pending)
                pending, chain = [], line_chain
            pending.append((kind, topic, json.loads(body)))
        self._flush(chain, pending)

    def _flush(self, chain: str, msgs: list[tuple[str, str, dict[str, Any]]]) -> None:
        if not msgs:
            return
        d = _Dispatch(chain)
        for kind, topic, p in msgs:
            if kind == "new":
                d.new = p
            elif kind == "quote":
                d.quote = p
            elif kind == "oco":
                d.oco = p
            elif kind == "ack":
                d.acks.append((topic.rsplit(".", 1)[1], p))
            elif kind == "quote_ack":
                d.quote_ack = p
            elif kind == "oco_ack":
                d.oco_ack = p
            elif kind == "trade":
                d.trades.append(p)
            elif kind == "fill":
                d.fills.append(p)
            elif kind in ("cancelled", "expired"):
                if kind == "expired":
                    d.dead[p["order_id"]] = "EXPIRED"
                else:
                    d.dead[p["order_id"]] = p.get("cancel_reason") or ""
                if p.get("symbol"):
                    d.dead_symbol[p["order_id"]] = p["symbol"]
            elif kind == "oco_cancelled":
                d.dead[p["cancelled_order_id"]] = "OCO_SIBLING"
            elif kind == "auction":
                d.auctions[p["symbol"]] = p
            elif kind == "phase":
                d.phase = p["state"]
            elif kind == "startup":
                d.startup = True
        if d.startup:
            if self.started:
                raise Skipped(
                    "the engine restarted during the run; replaying across a "
                    "restart (restored GTC orders) is not supported"
                )
            self.started = True
        self.dispatches += 1
        self._dispatch(d)
        if d.phase is not None:
            self.phase = d.phase

    def _dispatch(self, d: _Dispatch) -> None:
        self.chain = d.chain
        self.dead = d.dead
        self.dead_symbol = d.dead_symbol
        commands = self._commands(d)
        by_symbol: dict[str, list[_Order]] = defaultdict(list)
        for symbol, o in commands:
            by_symbol[symbol].append(o)
        trades: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in d.trades:
            trades[t["symbol"]].append(t)
        symbols = set(by_symbol) | set(trades) | set(d.auctions)
        for oid in d.dead:
            sym = self.symbol_of.get(oid) or d.dead_symbol.get(oid)
            if sym is not None:
                symbols.add(sym)
        fills: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in d.fills:
            fills[f["symbol"]].append(f)
        after = d.phase or self.phase
        for symbol in sorted(symbols):
            book = self._book(symbol)
            self._symbol_step(
                book,
                by_symbol.get(symbol, []),
                sorted(trades.get(symbol, []), key=lambda t: t["id"]),
                d.auctions.get(symbol),
                fills.get(symbol, []),
                after,
            )

    def _book(self, symbol: str) -> _Book:
        book = self.books.get(symbol)
        if book is None:
            book = self.books[symbol] = _Book(symbol, self.td.get(symbol, 2))
        return book

    def _next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def _flag(self, cid: str, **sample: object) -> None:
        self.counts[cid] += 1
        if len(self.samples[cid]) < _KEEP:
            self.samples[cid].append({**sample, "chain": self.chain})

    # --- commands --------------------------------------------------------

    def _commands(self, d: _Dispatch) -> list[tuple[str, _Order]]:
        """The orders the dispatch's command put into its book, in order."""
        out: list[tuple[str, _Order]] = []
        if d.new is not None:
            p = d.new
            ack = next((a for _, a in d.acks if a.get("order_id") == p["id"]), None)
            if ack is not None and ack.get("accepted"):
                td = int(p.get("tick_decimals") or self.td.get(p["symbol"], 2))
                stop = p.get("stop_price_ticks")
                if stop is None and ack.get("stop_price") is not None:
                    stop = _ticks(ack["stop_price"], td)
                o = _Order(
                    id=p["id"],
                    side=p["side"],
                    kind=p["order_type"],
                    price=p.get("price_ticks"),
                    remaining=int(p["quantity"]),
                    gw=p["gateway_id"],
                    smp=ack.get("smp_action") or self.smp.get(p["gateway_id"], "NONE"),
                    peak=p.get("visible_qty"),
                    stop=stop,
                    offset=p.get("trail_offset_ticks"),
                )
                out.append((p["symbol"], o))
                # An order accepted and then rejected in the same breath (X5)
                # is gone again.
                if any(
                    a.get("order_id") == o.id and not a.get("accepted")
                    for _, a in d.acks
                ):
                    self.dead.setdefault(o.id, "REJECTED")
        for gw, ack in d.acks:
            # Seed quote legs: acked at startup with no order.new.
            if ack.get("is_seed") and ack.get("accepted"):
                sym = ack["symbol"]
                o = _Order(
                    id=ack["order_id"],
                    side=ack["side"],
                    kind="LIMIT",
                    price=_ticks(ack["price"], self.td.get(sym, 2)),
                    remaining=int(ack["qty"]),
                    gw=gw,
                    smp=self.smp.get(gw, "NONE"),
                )
                out.append((sym, o))
        if (
            d.quote is not None
            and d.quote_ack is not None
            and d.quote_ack.get("accepted")
        ):
            q, a = d.quote, d.quote_ack
            smp = self.smp.get(q["gateway_id"], "NONE")
            for side, oid, price, qty in (
                (BUY, a["bid_order_id"], q["bid_price_ticks"], q["bid_qty"]),
                (SELL, a["ask_order_id"], q["ask_price_ticks"], q["ask_qty"]),
            ):
                o = _Order(oid, side, "LIMIT", price, int(qty), q["gateway_id"], smp)
                out.append((q["symbol"], o))
        if d.oco is not None and d.oco_ack is not None and d.oco_ack.get("accepted"):
            p, a = d.oco, d.oco_ack
            smp = self.smp.get(p["gateway_id"], "NONE")
            for leg, oid in (
                (p["leg1"], a["order_id_1"]),
                (p["leg2"], a["order_id_2"]),
            ):
                o = _Order(
                    id=oid,
                    side=leg["side"],
                    kind=leg["order_type"],
                    price=leg.get("price_ticks"),
                    remaining=int(p["quantity"]),
                    gw=p["gateway_id"],
                    smp=smp,
                    stop=leg.get("stop_price_ticks"),
                    offset=leg.get("trail_offset_ticks"),
                )
                out.append((p["symbol"], o))
        for symbol, o in out:
            self.symbol_of[o.id] = symbol
        return out

    # --- one symbol's part of a dispatch ---------------------------------

    def _symbol_step(
        self,
        book: _Book,
        commands: list[_Order],
        trades: list[dict[str, Any]],
        auction: dict[str, Any] | None,
        fills: list[dict[str, Any]],
        after: str | None,
    ) -> None:
        self.trades, self.ti = trades, 0
        self.triggered = []
        self.remaining_after = {}
        dying = set(self.dead)
        matching = self.phase in ("CONTINUOUS", None)
        if auction is not None or (trades and trades[0]["aggressor_side"] == "AUCTION"):
            self._uncross(book, auction, dying)
        queue = list(commands)
        while queue:
            self._process(book, self._pick(queue), matching, dying, cascade=True)
        while self.ti < len(self.trades):
            self._stray(book, dying)

        for o in self.triggered:
            if o.kind == "MARKET" and o.remaining > 0 and o.id not in self.dead:
                if not o.traded:
                    self._flag(
                        "C7",
                        error="replay triggered the stop; the engine reported nothing",
                        order_id=o.id,
                        symbol=book.symbol,
                        stop=o.stop,
                        last=book.last,
                    )
                    # The engine still holds it armed; so does the replay.
                    o.kind, o.triggered = o.armed_as, False
                    book.arm(o, o.seq)
                else:
                    self._flag(
                        "D9",
                        error="triggered stop traded part and its rest was not cancelled",
                        order_id=o.id,
                        symbol=book.symbol,
                    )
        for oid, reason in self.dead.items():
            if self.symbol_of.get(oid, self.dead_symbol.get(oid)) != book.symbol:
                continue
            armed = book.stops.get(oid) or book.trailing.get(oid)
            if armed is not None and reason in _TRIGGERED_REASONS:
                self._flag(
                    "C7",
                    error="the engine triggered the stop; the replay did not",
                    order_id=oid,
                    symbol=book.symbol,
                    stop=armed.stop,
                    last=book.last,
                    reason=reason,
                )
            book.remove(oid)
            self.symbol_of.pop(oid, None)

        for f in fills:
            tids = f.get("trade_ids") or []
            if not tids:
                continue
            mine = self.remaining_after.get((f["order_id"], tids[-1]))
            if mine is not None and mine != f["remaining_qty"]:
                self._flag(
                    "D9",
                    error="fill's remaining_qty differs from the replay's",
                    order_id=f["order_id"],
                    trade_id=tids[-1],
                    engine=f["remaining_qty"],
                    replay=mine,
                )
        for o in self.triggered:
            if o.remaining <= 0 or o.id in self.dead or o.kind == "MARKET":
                if not (o.kind in _STOP_TYPES and not o.triggered):
                    self.symbol_of.pop(o.id, None)

        if after == "CONTINUOUS":
            bid, ask = book.best(BUY), book.best(SELL)
            if bid is not None and ask is not None and bid >= ask:
                b = book.top(BUY, set(), _NOBODY)
                a = book.top(SELL, set(), _NOBODY)
                newest = max((b, a), key=lambda o: o.seq if o else 0)
                self._flag(
                    "D2",
                    symbol=book.symbol,
                    bid=bid,
                    ask=ask,
                    bid_order=b.id if b else None,
                    ask_order=a.id if a else None,
                    rested_last=newest.id if newest else None,
                )

    def _pick(self, queue: list[_Order]) -> _Order:
        """The next order the engine matched: the next trade's aggressor if
        it is queued, else the first in the queue."""
        if self.ti < len(self.trades):
            aid = _aggressor(self.trades[self.ti])
            for i, o in enumerate(queue):
                if o.id == aid:
                    return queue.pop(i)
        return queue.pop(0)

    def _process(
        self, book: _Book, o: _Order, matching: bool, dying: set[str], cascade: bool
    ) -> bool:
        """``OrderBook.process`` as the replay models it; True if it traded."""
        if not matching:
            if o.kind in _STOP_TYPES:
                book.arm(o, self._next_seq())
            elif o.kind in ("LIMIT", "ICEBERG") and o.id not in dying:
                book.rest(o, self._next_seq())
            return False
        if o.kind in _STOP_TYPES and not o.triggered:
            if book.last is None:
                # No trade yet in this replay: trust what the engine did.
                breached = (
                    self.ti < len(self.trades)
                    and _aggressor(self.trades[self.ti]) == o.id
                ) or self.dead.get(o.id) in _TRIGGERED_REASONS
            else:
                breached = _breached(o, book.last)
            if not breached:
                book.arm(o, self._next_seq())
                return False
            self._convert(book, o)
        traded = self._sweep(book, o, dying)
        if o.remaining > 0 and o.kind in ("LIMIT", "ICEBERG") and o.id not in dying:
            book.rest(o, self._next_seq())
        if traded and cascade:
            # First in, first out, as the engine runs them: a stop-limit
            # that trades nothing still rests before the next stop runs.
            pending = self._checkpoint(book)
            while pending:
                nxt = pending.pop(0)
                if self._process(book, nxt, True, dying, cascade=False):
                    pending += self._checkpoint(book)
        return traded

    def _convert(self, book: _Book, o: _Order) -> None:
        book.stops.pop(o.id, None)
        book.trailing.pop(o.id, None)
        o.triggered = True
        o.armed_as = o.kind
        self.stops_triggered += 1
        if o.kind == "STOP_LIMIT":
            o.kind = "LIMIT"
        else:
            o.kind, o.price = "MARKET", None
        self.triggered.append(o)

    def _checkpoint(self, book: _Book) -> list[_Order]:
        """The stops the engine's ``_check_stops`` + ``_check_trailing_stops``
        trigger at the book's last trade price, in the engine's order."""
        last = book.last
        if last is None:
            return []
        plain = list(book.stops.values())
        buys = sorted(
            (
                s
                for s in plain
                if s.side == BUY and s.stop is not None and last >= s.stop
            ),
            key=lambda s: (s.stop, s.seq),
        )
        sells = sorted(
            (
                s
                for s in plain
                if s.side == SELL and s.stop is not None and last <= s.stop
            ),
            key=lambda s: (-(s.stop or 0), s.seq),
        )
        trailing = []
        for s in book.trailing.values():
            if s.stop is None or s.offset is None:
                continue
            if s.side == SELL:
                s.stop = max(s.stop, last - s.offset)
                hit = last <= s.stop
            else:
                s.stop = min(s.stop, last + s.offset)
                hit = last >= s.stop
            if hit:
                trailing.append(s)
        fired = buys + sells + trailing
        for s in fired:
            self._convert(book, s)
        return fired

    def _sweep(self, book: _Book, o: _Order, dying: set[str]) -> bool:
        traded = False
        while self.ti < len(self.trades) and _aggressor(self.trades[self.ti]) == o.id:
            t = self.trades[self.ti]
            self.ti += 1
            traded = o.traded = True
            self._continuous_trade(book, t, o, dying)
        return traded

    def _continuous_trade(
        self, book: _Book, t: dict[str, Any], agg: _Order, dying: set[str]
    ) -> None:
        self.trades_replayed += 1
        price = self._price(book, t)
        qty = int(t["quantity"])
        passive_id = t["sell_order_id"] if agg.side == BUY else t["buy_order_id"]
        if t["buy_gateway_id"] == t["sell_gateway_id"] and agg.smp != "NONE":
            self._flag(
                "D7", trade_id=t["id"], gateway_id=t["buy_gateway_id"], smp=agg.smp
            )
        if agg.price is not None and (
            price > agg.price if agg.side == BUY else price < agg.price
        ):
            self._flag(
                "D3",
                trade_id=t["id"],
                order_id=agg.id,
                side=agg.side,
                limit=agg.price,
                price=price,
            )
        p = book.orders.get(passive_id)
        if p is None:
            self._flag(
                "D9",
                error="trade against an order the replayed book does not hold",
                trade_id=t["id"],
                order_id=passive_id,
                armed_stop=passive_id in book.stops or passive_id in book.trailing,
            )
        else:
            if price != p.price:
                self._flag(
                    "D4",
                    error="trade not at the resting order's price",
                    trade_id=t["id"],
                    order_id=p.id,
                    resting_price=p.price,
                    price=price,
                )
            self._priority(book, t, p, dying)
            want = min(agg.remaining, p.shown)
            if qty != want:
                self._flag(
                    "D5",
                    error="fill size is not min(aggressor left, resting shown)",
                    trade_id=t["id"],
                    order_id=p.id,
                    qty=qty,
                    expected=want,
                )
            book.fill(p, qty, self._next_seq())
            self.remaining_after[(p.id, t["id"])] = p.remaining
        agg.remaining -= qty
        self.remaining_after[(agg.id, t["id"])] = agg.remaining
        book.last = price

    def _priority(
        self, book: _Book, t: dict[str, Any], p: _Order, dying: set[str]
    ) -> None:
        first = book.top(p.side, dying, p)
        if first is None or first is p:
            return
        assert first.price is not None and p.price is not None
        better = first.price > p.price if p.side == BUY else first.price < p.price
        if better:
            self._flag(
                "D4",
                error="a better price was resting",
                trade_id=t["id"],
                order_id=p.id,
                price=p.price,
                better_order=first.id,
                better_price=first.price,
            )
        elif first.price == p.price:
            self._flag(
                "D5",
                error="an earlier order at the same price was passed over",
                trade_id=t["id"],
                order_id=p.id,
                ahead=first.id,
                price=p.price,
            )

    def _stray(self, book: _Book, dying: set[str]) -> None:
        """A trade whose aggressor the replay was not matching."""
        t = self.trades[self.ti]
        aid = _aggressor(t)
        armed = book.stops.get(aid) or book.trailing.get(aid)
        if armed is not None:
            self._flag(
                "C7",
                error="the engine traded a stop the replay had not triggered",
                order_id=aid,
                trade_id=t["id"],
                symbol=book.symbol,
                stop=armed.stop,
                last=book.last,
            )
            self._convert(book, armed)
            self._process(book, armed, True, dying, cascade=True)
            return
        self._flag(
            "D9",
            error="trade by an order the replay was not matching",
            trade_id=t["id"],
            order_id=aid,
            symbol=book.symbol,
        )
        self.ti += 1
        passive_id = (
            t["sell_order_id"] if t["aggressor_side"] == BUY else t["buy_order_id"]
        )
        p = book.orders.get(passive_id)
        if p is not None:
            book.fill(p, int(t["quantity"]), self._next_seq())
        book.last = self._price(book, t)

    # --- auctions --------------------------------------------------------

    def _uncross(
        self, book: _Book, auction: dict[str, Any] | None, dying: set[str]
    ) -> None:
        eq = _equilibrium(book)
        prints: list[dict[str, Any]] = []
        while (
            self.ti < len(self.trades)
            and self.trades[self.ti]["aggressor_side"] == "AUCTION"
        ):
            prints.append(self.trades[self.ti])
            self.ti += 1
        sym = book.symbol
        if prints:
            self.uncrosses += 1
            self.trades_replayed += len(prints)
        prices = {self._price(book, t) for t in prints}
        total = sum(int(t["quantity"]) for t in prints)
        if len(prices) > 1:
            self._flag(
                "D6",
                error="uncross printed more than one price",
                symbol=sym,
                prices=sorted(prices),
            )
        price = min(prices) if prices else None
        if (price, total) != ((eq[0], eq[1]) if eq else (None, 0)):
            self._flag(
                "D6",
                error="print differs from the replay's equilibrium",
                symbol=sym,
                printed=price,
                qty=total,
                replay=eq,
            )
        if auction is not None:
            stated = auction.get("eq_price")
            stated_ticks = _ticks(stated, book.td) if stated is not None else None
            if prints and (stated_ticks, auction.get("eq_qty")) != (price, total):
                self._flag(
                    "D6",
                    error="auction.result differs from the prints",
                    symbol=sym,
                    result=(stated_ticks, auction.get("eq_qty")),
                    printed=(price, total),
                )
        for t in prints:
            buyer = book.orders.get(t["buy_order_id"])
            seller = book.orders.get(t["sell_order_id"])
            if buyer is None or seller is None:
                self._flag(
                    "D9",
                    error="uncross print of an order the replay does not hold",
                    trade_id=t["id"],
                    buy=t["buy_order_id"],
                    sell=t["sell_order_id"],
                )
                continue
            if (
                book.top(BUY, dying, buyer) is not buyer
                or book.top(SELL, dying, seller) is not seller
            ):
                self._flag(
                    "D6", error="uncross filled out of priority", trade_id=t["id"]
                )
            qty = int(t["quantity"])
            if qty != min(buyer.shown, seller.shown):
                self._flag(
                    "D6",
                    error="uncross fill is not the smaller shown quantity",
                    trade_id=t["id"],
                    qty=qty,
                    expected=min(buyer.shown, seller.shown),
                )
            if t["buy_gateway_id"] == t["sell_gateway_id"]:
                self.auction_self_trades += 1
            book.fill(buyer, qty, self._next_seq())
            self.remaining_after[(buyer.id, t["id"])] = buyer.remaining
            book.fill(seller, qty, self._next_seq())
            self.remaining_after[(seller.id, t["id"])] = seller.remaining
        if not prints:
            return
        book.last = price
        bid, ask = book.best(BUY), book.best(SELL)
        if bid is not None and ask is not None and bid >= ask:
            self._flag(
                "D6",
                error="book still crossed after the uncross",
                symbol=sym,
                bid=bid,
                ask=ask,
            )
        # Each stop the print triggers is processed with its own cascade
        # (Engine._run_uncross calls book.process for each).
        queue = self._checkpoint(book)
        while queue:
            self._process(book, self._pick(queue), True, dying, cascade=True)

    # --- snapshots -------------------------------------------------------

    def _snapshot(self, p: dict[str, Any]) -> None:
        sym = p["symbol"]
        td = int(p.get("tick_decimals", self.td.get(sym, 2)))
        book = self._book(sym)
        bids, asks = p["bids"], p["asks"]
        self.snapshots += 1
        if (
            self.phase == "CONTINUOUS"
            and bids
            and asks
            and bids[0]["price"] >= asks[0]["price"]
        ):
            self._flag(
                "D1",
                symbol=sym,
                bid=bids[0]["price"],
                ask=asks[0]["price"],
                ts_ns=p.get("ts_ns"),
            )
        engine = {
            BUY: {_ticks(lv["price"], td): (lv["qty"], lv["count"]) for lv in bids},
            SELL: {_ticks(lv["price"], td): (lv["qty"], lv["count"]) for lv in asks},
        }
        same = all(
            _fingerprint(engine[s], s) == (book.best(s), book.qty[s], book.count[s])
            for s in (BUY, SELL)
        )
        if same:
            self.diverged.discard(sym)
            return
        self.snapshots_differing += 1
        if sym in self.diverged:
            return
        self.diverged.add(sym)
        diff = []
        for s in (BUY, SELL):
            mine = book.view(s)
            for price in sorted(set(mine) | set(engine[s]), reverse=s == BUY):
                if mine.get(price) != engine[s].get(price):
                    diff.append((s, price, engine[s].get(price), mine.get(price)))
        self._flag(
            "D9",
            error="replayed book differs from the engine's snapshot",
            symbol=sym,
            ts_ns=p.get("ts_ns"),
            levels="; ".join(
                f"{s} {price}: engine {e} replay {m}" for s, price, e, m in diff[:4]
            ),
        )

    def _indicative(self, p: dict[str, Any]) -> None:
        """D10: the engine's indicative uncross is the replayed book's."""
        sym = p["symbol"]
        if sym in self.diverged:
            self.indicatives_skipped += 1  # D9 already names the divergence
            return
        self.indicatives += 1
        book = self._book(sym)
        cached = self._uncross_at.get(sym)
        if cached is not None and cached[0] == book.version:
            mine = cached[1]
        else:
            mine = _uncross_of(book)
            self._uncross_at[sym] = (book.version, mine)
        price = p.get("eq_price")
        engine = (
            _ticks(price, book.td) if price is not None else None,
            p.get("eq_qty") or 0,
            p.get("imbalance_qty") or 0,
            p.get("imbalance_side") or "",
        )
        replay = mine if mine is not None else (None, 0, 0, "")
        if engine != replay:
            self._flag(
                "D10",
                symbol=sym,
                phase=p.get("phase"),
                engine=list(engine),
                replay=list(replay),
            )

    def _price(self, book: _Book, t: dict[str, Any]) -> int:
        td = int(t.get("tick_decimals", book.td))
        raw = float(t["price"]) * 10.0**td
        ticks = round(raw)
        if abs(raw - ticks) > 1e-6:
            self._flag("D8", trade_id=t["id"], price=t["price"], tick_decimals=td)
        return ticks


class _Nobody:
    """Stands in for "no order to keep" in ``_Book.top``."""


_NOBODY: Any = _Nobody()


def _fingerprint(
    levels: dict[int, tuple[int, int]], side: str
) -> tuple[int | None, int, int]:
    """(best price, shown quantity, order count) of one side."""
    if not levels:
        return None, 0, 0
    best = max(levels) if side == BUY else min(levels)
    return best, sum(q for q, _ in levels.values()), sum(c for _, c in levels.values())


def _ticks(price: float, td: int) -> int:
    return round(float(price) * 10.0**td)


def _aggressor(t: dict[str, Any]) -> str:
    return str(t["buy_order_id"] if t["aggressor_side"] == BUY else t["sell_order_id"])


def _breached(o: _Order, last: int) -> bool:
    if o.stop is None:
        return False
    return last >= o.stop if o.side == BUY else last <= o.stop


#: (price, executable qty, surplus, imbalance side "BUY"/"SELL"/"").
_Uncross = tuple[int, int, int, str]


def _uncross_of(book: _Book) -> _Uncross | None:
    """The uncross the book makes: the most executable quantity, then the
    least surplus, then the lowest price; hidden iceberg quantity counts."""
    bids: dict[int, int] = defaultdict(int)
    asks: dict[int, int] = defaultdict(int)
    for o in book.orders.values():
        assert o.price is not None
        (bids if o.side == BUY else asks)[o.price] += o.remaining
    if not bids or not asks:
        return None
    prices = sorted(set(bids) | set(asks))
    # buy[i]: bids at prices[i] or above; sell[i]: asks at prices[i] or below.
    buy, sell = [0] * len(prices), [0] * len(prices)
    running = 0
    for i in range(len(prices) - 1, -1, -1):
        running += bids.get(prices[i], 0)
        buy[i] = running
    running = 0
    for i, price in enumerate(prices):
        running += asks.get(price, 0)
        sell[i] = running
    i = min(
        range(len(prices)),
        key=lambda j: (-min(buy[j], sell[j]), abs(buy[j] - sell[j]), prices[j]),
    )
    qty = min(buy[i], sell[i])
    if qty == 0:
        return None
    side = "BUY" if buy[i] > sell[i] else "SELL" if sell[i] > buy[i] else ""
    return prices[i], qty, abs(buy[i] - sell[i]), side


def _equilibrium(book: _Book) -> tuple[int, int] | None:
    """(price, qty) an uncross must print."""
    u = _uncross_of(book)
    return None if u is None else (u[0], u[1])


def _replay(ds: Dataset) -> _Replay:
    cached = ds.cache.get("matching")
    if isinstance(cached, Skipped):
        raise cached
    if isinstance(cached, _Replay):
        return cached
    try:
        files = audit_files(ds.data_dir)
        if not files:
            raise Skipped("no audit.log in the data dir")
        config_path = ds.data_dir / "ref_data" / "engine_config.json"
        if not config_path.is_file():
            raise Skipped("no ref_data/engine_config.json (tick sizes, SMP modes)")
        engine = json.loads(config_path.read_text())["engine"]
        smp = {
            gw: str(c.get("smp_action") or "NONE")
            for gw, c in engine.get("fix_gateways", {}).items()
        }
        replay = _Replay(engine.get("symbols", {}), smp)
        replay.run(lines(files))
    except Skipped as exc:
        ds.cache["matching"] = exc
        raise
    ds.cache["matching"] = replay
    return replay


def _outcome(ds: Dataset, cid: str, note: str = "") -> Outcome:
    r = _replay(ds)
    return Outcome(r.counts[cid], r.samples[cid], note)


@check(
    "D1",
    "book-state",
    "The engine's book snapshots are never crossed in CONTINUOUS",
    needs=(),
)
def crossed_snapshots(ds: Dataset) -> Outcome:
    r = _replay(ds)
    return _outcome(ds, "D1", f"{r.snapshots} snapshots")


@check(
    "D2",
    "book-state",
    "No order rests marketable: after each dispatch in CONTINUOUS the replayed book is uncrossed",
    needs=(),
)
def marketable_rested(ds: Dataset) -> Outcome:
    r = _replay(ds)
    return _outcome(
        ds, "D2", f"{r.dispatches} dispatches, {r.trades_replayed} trades replayed"
    )


@check("D3", "book-state", "Every fill is at or inside the aggressor's limit", needs=())
def limits(ds: Dataset) -> Outcome:
    return _outcome(ds, "D3")


@check(
    "D4",
    "book-state",
    "Every fill is at the resting order's price, the best opposite price (no trade-through)",
    needs=(),
)
def trade_through(ds: Dataset) -> Outcome:
    return _outcome(ds, "D4")


@check(
    "D5",
    "book-state",
    "Fills follow time priority in a level, each as big as the aggressor and the shown slice allow",
    needs=(),
)
def priority(ds: Dataset) -> Outcome:
    return _outcome(ds, "D5")


@check(
    "D6",
    "book-state",
    "Each uncross prints one volume-maximising price, as auction.result says, in priority",
    needs=(),
)
def uncross(ds: Dataset) -> Outcome:
    r = _replay(ds)
    return _outcome(ds, "D6", f"{r.uncrosses} uncrosses with prints")


@check("D7", "book-state", "No continuous self-trade under SMP", needs=())
def self_trades(ds: Dataset) -> Outcome:
    r = _replay(ds)
    return _outcome(ds, "D7", f"auction self-trades (X2, Q2): {r.auction_self_trades}")


@check("D8", "book-state", "Trade prices lie on the tick grid", needs=())
def tick_grid(ds: Dataset) -> Outcome:
    return _outcome(ds, "D8", "collar / circuit-breaker bands not checked")


@check(
    "D10",
    "book-state",
    "Each indicative uncross the engine publishes in a call phase is the replayed book's",
    needs=(),
)
def indicatives(ds: Dataset) -> Outcome:
    r = _replay(ds)
    note = f"{r.indicatives} indicatives compared"
    if r.indicatives_skipped:
        note += f", {r.indicatives_skipped} skipped on symbols D9 found diverged"
    return _outcome(ds, "D10", note)


@check(
    "D9",
    "replay",
    "The replayed book equals every engine snapshot and every fill's remaining_qty",
    needs=(),
)
def replay_agrees(ds: Dataset) -> Outcome:
    r = _replay(ds)
    note = f"{r.snapshots} snapshots compared, {r.snapshots_differing} differ"
    if r.unmodelled:
        note += "; not modelled: " + ", ".join(
            f"{t}* {n}" for t, n in r.unmodelled.items()
        )
    return _outcome(ds, "D9", note)


@check(
    "C7",
    "lifecycle",
    "Stops trigger exactly when a trade reaches their (ratcheted) stop price",
    needs=(),
)
def stop_triggers(ds: Dataset) -> Outcome:
    r = _replay(ds)
    return _outcome(ds, "C7", f"{r.stops_triggered} stops triggered")
