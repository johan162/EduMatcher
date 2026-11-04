"""Where an order stood in its level, and what happened to the queue (A8).

Two views over the re-run (``edumatcher.audit.replay.rerun``), which holds an
engine whose book is the live one after every command.  An observer reads that
book through ``OrderBook.checkpoint()`` -- every resting order in the engine's
own matching priority -- so iceberg slices, amends that lose priority and refills
sent to the back follow the engine's rules, not a second implementation of them.

``OrderQueue`` follows one order: its place in its level after each change, what
traded or was cancelled ahead of it, and a verdict.  A stop waits outside the
level, in the checkpoint's stop lists, until a trade fires it; the view says
when it was armed and what fired it, then follows what it became.  ``LevelQueue`` follows one
price level: who rested, traded and left, and what the level held after each
change.

Quantity "ahead" is what is *displayed*: an iceberg's reserve joins the back of
the level when its slice is refilled, so it is not ahead of anything.  The
reserve is reported only when the view is not anonymised.

Both are read-only observers and cost one ``checkpoint()`` per relevant input.
"""

from __future__ import annotations

from typing import Any

from edumatcher.audit.replay import lexicon
from edumatcher.audit.replay.rerun import Step
from edumatcher.models.generated.order import (
    PREFIX_ENGINE_TRACE,
    PREFIX_ORDER_AMENDED,
    PREFIX_ORDER_CANCELLED,
    PREFIX_ORDER_EXPIRED,
    PREFIX_ORDER_FILL,
    PREFIX_ORDER_TRIGGERED,
    TOPIC_ORDER_NEW,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.price import from_ticks, get_tick_decimals

Record = dict[str, Any]

#: How many orders ahead are listed by name before the rest are counted.
_LISTED = 5


def queued(rec: Record) -> int:
    """Shares that stand in the queue: an iceberg's displayed slice only."""
    shown = rec.get("displayed_qty")
    return int(shown if shown is not None else rec["remaining_qty"])


def shares(rec: Record, *, anonymise: bool) -> int:
    """Shares reported for an order: its reserve too, unless anonymised."""
    if anonymise:
        return queued(rec)
    return int(rec["remaining_qty"])


def _clock(ts: str) -> str:
    """``HH:MM:SS.mmm`` of an audit stamp (``start`` before any line)."""
    return ts[11:23] if len(ts) >= 23 else "start"


def _num(n: int) -> str:
    return f"{n:,}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class Labels:
    """Gateway names as shown: real, or A, B, C in order of first appearance.

    The inspected order's own gateway is never relabelled -- it is the
    reader's.
    """

    def __init__(self, own: str | None, anonymise: bool) -> None:
        self.own = own
        self.anonymise = anonymise
        self._seen: dict[str, str] = {}

    def __call__(self, gateway: str) -> str:
        if not self.anonymise or gateway == self.own:
            return gateway
        if gateway not in self._seen:
            self._seen[gateway] = f"gateway {chr(ord('A') + len(self._seen) % 26)}"
        return self._seen[gateway]


class Departure:
    """What a step did to one order: fills, and how (if) it left the book."""

    def __init__(self, step: Step, rid: str) -> None:
        self.traded = 0
        self.trades: list[str] = []
        self.left: str | None = None  # cancelled | expired
        self.reason = ""
        self.amended = False
        for topic, body in step.rerun:
            if body.get("order_id") != rid:
                continue
            if topic.startswith(PREFIX_ORDER_FILL):
                self.traded += int(body.get("fill_qty", 0))
                self.trades += [
                    str(step.ids.to_live.get(t, t)) for t in body.get("trade_ids", [])
                ]
            elif topic.startswith(PREFIX_ORDER_CANCELLED):
                self.left = "cancelled"
                why = body.get("cancel_reason")
                self.reason = lexicon.phrase("cancel_reason", why) if why else ""
            elif topic.startswith(PREFIX_ORDER_EXPIRED):
                self.left = "expired"
            elif topic.startswith(PREFIX_ORDER_AMENDED):
                self.amended = True

    def how(self) -> str:
        if self.left == "cancelled":
            return (
                f"cancelled because of {self.reason}"
                if self.reason
                else ("cancelled by its owner")
            )
        if self.left == "expired":
            return "expired"
        return "removed from the book"


def _touches(step: Step, symbol: str, rid: str | None) -> bool:
    if step.payload.get("symbol") == symbol:
        return True
    if rid is not None and step.payload.get("order_id") == rid:
        return True
    return any(body.get("symbol") == symbol for _, body in step.rerun)


def _side_key(side: str) -> str:
    return "bids" if side == "BUY" else "asks"


def _trade_ids(departures: list[Departure]) -> str:
    ids = [t for d in departures for t in d.trades]
    return (
        f" (trade {', '.join(ids[:3])}{', ...' if len(ids) > 3 else ''})" if ids else ""
    )


class OrderQueue:
    """Follow one order through its level.  Feed it to ``Rerun.observers``."""

    def __init__(self, order: str, *, anonymise: bool = False) -> None:
        self.target = order
        self.anonymise = anonymise
        self.rid: str | None = None
        self.live_id = ""
        self.symbol = ""
        self.side = ""
        self.gateway = ""
        self.quantity = 0
        self.price_ticks: int | None = None
        #: The stop price while the order waits as a stop (None otherwise).
        self._armed: int | None = None
        self.lines: list[str] = []
        self.done = False
        self._labels = Labels(None, anonymise)
        self._ahead: dict[str, tuple[str, int]] = {}
        self._seen_resting = False
        self._priority: int | None = None
        self._remaining = 0
        self._place: tuple[int, int, int] | None = None
        self._verdict = ""
        self._warned = False
        self._at_price_trades = 0
        self._at_price_qty = 0
        self._best_opposite: float | None = None
        self._filled = 0
        self._better: set[str] = set()

    # -- the observer -------------------------------------------------------

    def __call__(self, step: Step) -> None:
        if self.done:
            return
        if self.rid is None and not self._find(step):
            return
        if not _touches(step, self.symbol, self.rid):
            return
        book = step.engine.books.get(self.symbol)
        if book is None or self.rid is None:
            return
        if self.symbol in step.diverged and not self._warned:
            self._warned = True
            self.lines.append(
                f"{_clock(step.ts)}  warning: the re-run and the live engine "
                f"differ on {self.symbol} from here; positions are the re-run's"
            )
        cp = book.checkpoint()
        mine = self._tally(step, cp)
        records: list[Record] = cp[_side_key(self.side)]
        index = next(
            (i for i, r in enumerate(records) if r["order_id"] == self.rid), None
        )
        if index is None:
            stop = self._stop_record(cp)
            if stop is not None:
                self._arming(step, stop)
                return
            self._triggered(step)
            self._left_the_book(step, mine)
            return
        self._triggered(step)
        self._resting(step, records, index, mine)

    def _find(self, step: Step) -> bool:
        if step.topic != TOPIC_ORDER_NEW:
            return False
        ident = str(step.payload.get("id", ""))
        if not ident.startswith(self.target):
            return False
        self.live_id = ident
        self.rid = step.ids.to_rerun.get(ident, ident)
        self.symbol = str(step.payload["symbol"])
        self.side = str(step.payload["side"])
        self.gateway = str(step.payload["gateway_id"])
        self.quantity = int(step.payload["quantity"])
        self.price_ticks = step.payload.get("price_ticks")
        self._labels = Labels(self.gateway, self.anonymise)
        return True

    # -- a stop ---------------------------------------------------------------

    def _stop_record(self, cp: dict[str, Any]) -> Record | None:
        """The order's record if it waits as a stop (armed or trailing)."""
        stops = cp["buy_stops" if self.side == "BUY" else "sell_stops"]
        return next(
            (r for r in [*stops, *cp["trailing_stops"]] if r["order_id"] == self.rid),
            None,
        )

    def _arming(self, step: Step, rec: Record) -> None:
        if self._armed is None:
            self.lines.append(
                f"{_clock(step.ts)}  armed: a {rec['order_type']} stop at "
                f"{self._ticks(rec['stop_price_ticks'])}"
            )
        self._armed = int(rec["stop_price_ticks"])

    def _triggered(self, step: Step) -> None:
        """Say what fired the stop, if this step did."""
        if self._armed is None:
            return
        for topic, body in step.rerun:
            if (
                topic.startswith(PREFIX_ORDER_TRIGGERED)
                and body["order_id"] == self.rid
            ):
                trade = body.get("trigger_trade_id")
                self.lines.append(
                    f"{_clock(step.ts)}  triggered by a trade at "
                    f"{self._ticks(body['trigger_price_ticks'])}"
                    + (
                        f" (trade {step.ids.to_live.get(trade, trade)})"
                        if trade
                        else ""
                    )
                    + f": now a {body['becomes']} order"
                )
                self._armed = None
                return

    def _ticks(self, ticks: int) -> str:
        return f"{from_ticks(ticks, self.symbol):.{get_tick_decimals(self.symbol)}f}"

    # -- what a step did ----------------------------------------------------

    def _tally(self, step: Step, cp: dict[str, Any]) -> Departure:
        """Update the market statistics; return what happened to this order."""
        for topic, body in step.rerun:
            if topic == TOPIC_TRADE_EXECUTED and body.get("symbol") == self.symbol:
                if self._at_limit(body):
                    self._at_price_trades += 1
                    self._at_price_qty += int(body["quantity"])
        opposite = cp["asks" if self.side == "BUY" else "bids"]
        self._best_opposite = (
            from_ticks(opposite[0]["price_ticks"], self.symbol) if opposite else None
        )
        assert self.rid is not None
        return Departure(step, self.rid)

    def _at_limit(self, trade: Record) -> bool:
        if self.price_ticks is None:
            return False
        gap = abs(float(trade["price"]) - from_ticks(self.price_ticks, self.symbol))
        return bool(gap < 0.5 / (10 ** get_tick_decimals(self.symbol)))

    def _price(self) -> str:
        if self.price_ticks is None:
            return "market"
        return self._ticks(self.price_ticks)

    def _resting(
        self, step: Step, records: list[Record], index: int, mine: Departure
    ) -> None:
        me = records[index]
        at = [r for r in records if r["price_ticks"] == me["price_ticks"]]
        ahead_recs = records[:index]
        level_ahead = [r for r in ahead_recs if r["price_ticks"] == me["price_ticks"]]
        position = (len(level_ahead) + 1, len(at))
        level_qty = sum(queued(r) for r in level_ahead)
        better_qty = sum(queued(r) for r in ahead_recs) - level_qty
        now = {r["order_id"]: (r["gateway_id"], queued(r)) for r in ahead_recs}
        self._remaining = int(me["remaining_qty"])
        self._better = {
            r["order_id"] for r in ahead_recs if r["price_ticks"] != me["price_ticks"]
        }
        state = (
            f"{position[0]} of {position[1]} in its level, {_num(level_qty)} shares "
            f"ahead ({_plural(len(level_ahead), 'order')}"
            + (f"; {_num(better_qty)} more at better prices" if better_qty else "")
            + ")"
        )
        when = _clock(step.ts)
        if not self._seen_resting:
            self._seen_resting = True
            self.lines.append(
                f"{when}  rested at {self._price()}: {state}{self._named(ahead_recs)}"
            )
            self._check_trace(step, me, when)
        else:
            events = self._events(step, now, mine, me)
            if events:
                self.lines.append(f"{when}  {'; '.join(events)} -> now {state}")
        self._ahead = now
        self._priority = me.get("priority_seq")
        self._place = (position[0], position[1], level_qty)

    def _check_trace(self, step: Step, me: Record, when: str) -> None:
        """The live engine said where it queued the order (engine.trace RESTED);
        the re-run's book must agree, or the positions here are not the live ones."""
        for topic, body in step.live:
            if (
                topic.startswith(PREFIX_ENGINE_TRACE)
                and body.get("kind") == "RESTED"
                and body.get("order_id") == self.live_id
                and body.get("priority_seq") != me.get("priority_seq")
            ):
                self.lines.append(
                    f"{when}  warning: the live engine's engine.trace queued it at "
                    f"priority {body.get('priority_seq')}, the re-run at "
                    f"{me.get('priority_seq')}; this queue differs from the live one"
                )

    def _named(self, ahead: list[Record]) -> str:
        if not ahead:
            return ""
        shown = [
            f"{self._labels(r['gateway_id'])} {_num(shares(r, anonymise=self.anonymise))}"
            for r in ahead[-_LISTED:]
        ]
        more = len(ahead) - len(shown)
        head = f"{_plural(more, 'earlier order')}, then " if more > 0 else ""
        return f"; ahead of it: {head}{', '.join(shown)}"

    def _events(
        self,
        step: Step,
        now: dict[str, tuple[str, int]],
        mine: Departure,
        me: Record,
    ) -> list[str]:
        events: list[str] = []
        departures: dict[str, Departure] = {}
        for rid, (gw, qty) in self._ahead.items():
            departures[rid] = Departure(step, rid)
        traded = [d for d in departures.values() if d.traded]
        if traded:
            total = sum(d.traded for d in traded)
            who = ", ".join(
                sorted(
                    {
                        self._labels(self._ahead[r][0])
                        for r, d in departures.items()
                        if d.traded
                    }
                )
            )
            events.append(
                f"{_num(total)} shares traded ahead of it ({who}){_trade_ids(traded)}"
            )
        for rid, (gw, qty) in self._ahead.items():
            d = departures[rid]
            if rid not in now and d.left is not None:
                events.append(
                    f"{self._labels(gw)}'s order ahead ({_num(qty)} shares) was {d.how()}"
                )
            elif rid not in now and not d.traded:
                events.append(
                    f"{self._labels(gw)}'s order ahead ({_num(qty)} shares) left the queue"
                )
            elif rid in now and now[rid][1] != qty and not d.traded:
                events.append(
                    f"{self._labels(gw)}'s order ahead changed from {_num(qty)} "
                    f"to {_num(now[rid][1])} shares"
                )
        for rid, (gw, qty) in now.items():
            if rid not in self._ahead:
                kind = "better-priced order" if rid in self._better else "order"
                events.append(
                    f"{self._labels(gw)}'s {kind} ({_num(qty)} shares) is now ahead of it"
                )
        if mine.traded:
            self._filled += mine.traded
            events.append(
                f"filled {_num(mine.traded)} of {_num(self.quantity)}"
                f"{_trade_ids([mine])}, {_num(self._remaining)} left"
            )
        priority = me.get("priority_seq")
        if (
            self._priority is not None
            and priority != self._priority
            and not (mine.traded)
        ):
            events.append("its priority was reset (an amend or a refill)")
        return events

    def _left_the_book(self, step: Step, mine: Departure) -> None:
        when = _clock(step.ts)
        if mine.traded:
            self._filled += mine.traded
        if self._armed is not None:
            outcome = (
                f"{mine.how() if mine.left else 'left the book'} while armed "
                f"(its stop {self._ticks(self._armed)} was never reached)"
            )
            self.lines.append(f"{when}  {outcome}")
            self._verdict = f"verdict: it never triggered; {outcome}"
            self.done = True
            return
        if not self._seen_resting:
            outcome = (
                f"filled {_num(mine.traded)} at once"
                if mine.traded
                else (mine.how() if mine.left else "did not rest")
            )
            self.lines.append(f"{when}  never rested in the book: {outcome}")
            self._verdict = f"verdict: it never queued; {outcome}"
            self.done = True
            return
        parts = []
        if mine.traded:
            parts.append(f"filled {_num(mine.traded)}{_trade_ids([mine])}")
        if mine.left:
            parts.append(mine.how())
        self.lines.append(f"{when}  {'; '.join(parts) or 'left the book'}")
        left = self._remaining - mine.traded
        reached = (
            f"{_plural(self._at_price_trades, 'trade')} at its price "
            f"({_num(self._at_price_qty)} shares) while it rested"
        )
        if left <= 0:
            self._verdict = f"verdict: filled in full at {when}; {reached}"
        else:
            self._verdict = (
                f"verdict: {mine.how() if mine.left else 'left the book'} with "
                f"{_num(left)} of {_num(self.quantity)} shares unfilled; {reached}"
            )
            if self._place is not None:
                self._verdict += f"; at the last look {_num(self._place[2])} shares stood ahead of it"
        self.done = True

    # -- the answer ---------------------------------------------------------

    def render(self) -> str:
        if self.rid is None:
            return f"order {self.target} is not in the trail\n"
        out = [
            f"order {self.live_id[:8]}  {self.side} {_num(self.quantity)} "
            f"{self.symbol} @ {self._price()}  ({self._labels(self.gateway)})",
            *self.lines,
        ]
        verdict = self._verdict
        if not self.done and self._armed is not None:
            verdict = (
                f"verdict: still armed at the end of the trail; its stop "
                f"{self._ticks(self._armed)} was never reached"
            )
        elif not self.done:
            place = self._place
            verdict = "verdict: still resting at the end of the trail"
            if place is not None:
                verdict += (
                    f": {place[0]} of {place[1]} in its level, "
                    f"{_num(place[2])} shares ahead"
                )
            if self._at_price_trades == 0:
                best = (
                    "no opposite order"
                    if self._best_opposite is None
                    else f"best opposite {self._best_opposite:.{get_tick_decimals(self.symbol)}f}"
                )
                verdict += (
                    f"; the market never traded at its price ({best} against "
                    f"its limit {self._price()})"
                )
            else:
                verdict += (
                    f"; {_plural(self._at_price_trades, 'trade')} at its price "
                    f"({_num(self._at_price_qty)} shares) while it rested"
                )
        out.append(verdict)
        return "\n".join(out) + "\n"


class LevelQueue:
    """Follow one price level through the day.  Feed it to ``Rerun.observers``."""

    def __init__(
        self,
        symbol: str,
        price: float,
        *,
        side: str | None = None,
        anonymise: bool = False,
    ) -> None:
        self.symbol = symbol
        self.price = price
        self.side = side
        self.anonymise = anonymise
        self.lines: list[str] = []
        self._labels = Labels(None, anonymise)
        self._level: dict[str, tuple[str, str, int]] = {}
        self._started = False
        self._warned = False

    def __call__(self, step: Step) -> None:
        book = step.engine.books.get(self.symbol)
        if book is None:
            return
        if self._started and not _touches(step, self.symbol, None):
            return
        ticks = round(self.price * 10 ** get_tick_decimals(self.symbol))
        cp = book.checkpoint()
        now: dict[str, tuple[str, str, int]] = {}
        for key, name in (("bids", "BUY"), ("asks", "SELL")):
            if self.side is not None and self.side != name:
                continue
            for rec in cp[key]:
                if rec["price_ticks"] == ticks:
                    now[rec["order_id"]] = (rec["gateway_id"], name, queued(rec))
        events = self._events(step, now)
        first = not self._started
        self._started = True
        if self.symbol in step.diverged and not self._warned:
            self._warned = True
            events.insert(0, "warning: the re-run and the live engine differ here")
        if events or (first and now):
            when = "start" if first else _clock(step.ts)
            total = sum(q for _, _, q in now.values())
            self.lines.append(
                f"{when}  {'; '.join(events) or 'level holds'} -> "
                f"{_plural(len(now), 'order')}, {_num(total)} shares"
            )
        self._level = now

    def _events(self, step: Step, now: dict[str, tuple[str, str, int]]) -> list[str]:
        events: list[str] = []
        before = self._level
        for rid, (gw, side, qty) in now.items():
            if rid not in before:
                events.append(
                    f"{self._labels(gw)} rested {_num(qty)} shares ({side.lower()})"
                )
        gone = {rid: v for rid, v in before.items() if rid not in now}
        for rid, (gw, side, qty) in list(before.items()):
            d = Departure(step, rid)
            if d.traded:
                events.append(
                    f"{_num(d.traded)} shares of {self._labels(gw)}'s order traded"
                    f"{_trade_ids([d])}"
                )
            if rid in gone and d.left is not None:
                events.append(
                    f"{self._labels(gw)}'s order ({_num(qty)} shares) was {d.how()}"
                )
            elif rid in gone and not d.traded:
                events.append(
                    f"{self._labels(gw)}'s order ({_num(qty)} shares) left the level"
                )
        return events

    def render(self) -> str:
        head = f"{self.symbol} @ {self.price}" + (
            f" ({self.side.lower()})" if self.side else ""
        )
        out = [head, *self.lines]
        if not self._level:
            out.append("level now empty")
        else:
            out.append(
                f"level at the end of the trail: "
                f"{_plural(len(self._level), 'order')}, "
                f"{_num(sum(q for _, _, q in self._level.values()))} shares"
            )
        return "\n".join(out) + "\n"
