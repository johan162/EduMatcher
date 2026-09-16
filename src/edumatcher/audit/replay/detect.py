"""The §12 findings that need more than one message to notice.

Nineteen of section 12's codes are raised where the evidence is: a topic with
no spec entry is noticed by :mod:`~edumatcher.audit.replay.facts`, a gap in a
topic's ``seq`` by :mod:`~edumatcher.audit.replay.ordering`, an illegal status
transition by the state model. Each of those is a property of one line, or of
one line against the model the state machine already keeps.

The remaining eighteen are not. "This order was never acked" is a statement
about an order's whole life, and the moment it becomes true is the moment the
episode retires without the ack ever having arrived. "The two legs of this
trade disagree" needs both legs, which live in two different episodes. So they
are detected here, by one object fed the same stream twice over: every Fact as
it is reconstructed, and every Episode as it retires.

**Why one object.** The checks share state -- the trades seen so far, the
limit price of each live order, which orders have been acked -- and a check
that keeps its own copy of that state is a check that can come to disagree
with its neighbours about what the log said. Splitting them across the state
model and the resolver would also scatter section 12 across four files, and
the catalogue is worth reading in one place.

**Why it is bounded.** Everything this holds is keyed on an entity, and every
entity's key is dropped when its episode retires -- the same discipline
:meth:`LinkResolver.forget` follows. A day's log does not grow this.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Iterator, Mapping, Sequence

from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.anomalies import (
    ACK_MISSING,
    ARRIVAL_SEQ_GAP,
    ARRIVAL_SEQ_REUSED,
    CANCEL_UNMATCHED,
    CANCEL_UNSOLICITED,
    CLIENT_CLOCK_ABSURD,
    CLOCK_SKEW,
    COMMAND_UNACKED,
    DROP_COPY_DISAGREE,
    DROP_COPY_MISSING,
    DROP_COPY_SEQ_GAP,
    FILL_BEFORE_ACK,
    FILL_STATUS_DISAGREE,
    FILL_WITHOUT_TRADE,
    HALT_UNRESUMED,
    LEG_PRICE_DISAGREE,
    LEG_QTY_DISAGREE,
    LIQUIDITY_FLAG_DISAGREE,
    PRINT_PRICE_DISAGREE,
    PRINT_QTY_DISAGREE,
    PRICE_OUTSIDE_CORRIDOR,
    PRICE_THROUGH_LIMIT,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    TERMINAL_MISSING,
    TRADE_COUNTER_GAP,
    TRADE_LEG_MISSING,
    TRADE_LEG_UNKNOWN,
    Anomaly,
)
from edumatcher.audit.replay.episodes import (
    KIND_COMMAND,
    KIND_MARKET_PHASE,
    KIND_ORDER,
    KIND_TRADE,
    OUTCOME_OPEN,
    Episode,
)
from edumatcher.audit.replay.facts import CLOCK_CLIENT, CLOCK_ENGINE, Fact
from edumatcher.audit.replay.pipeline import Step
from edumatcher.audit.replay.state import STATUS_FILLED, StateModel

#: How far the engine's clock and ``pm-audit``'s receipt clock may differ
#: before it is worth saying so. A tenth of a second is generous for two
#: processes on one host and tight enough to catch a real drift.
DEFAULT_CLOCK_SKEW_WARN = 0.1

#: A client clock this far from receipt is not drift, it is wrong -- a machine
#: in the wrong timezone, or one that never ran ntp. Section 12.3.
_CLIENT_CLOCK_ABSURD_SECONDS = 3600.0

#: Prices are floats reconstructed from integer ticks, so an exact ``>`` would
#: report a fill *at* its limit as through it about as often as the last
#: division happens to land low. A tenth of the smallest tick anyone uses.
_PRICE_EPSILON = 1e-6

_ACK_SUFFIX = "_ack"

_SIDE_BUY = "BUY"
_SIDE_SELL = "SELL"

_MAKER = "MAKER"
_TAKER = "TAKER"
#: An uncross has no aggressor, and the engine flags both of its sides MAKER.
_AGGRESSOR_AUCTION = "AUCTION"
#: Which of the trade's two order ids the aggressor is, by side.
_AGGRESSOR_FIELD = {_SIDE_BUY: "buy_order_id", _SIDE_SELL: "sell_order_id"}


def _anomaly(code: str, severity: str, detail: str, fact: Fact) -> Anomaly:
    return Anomaly(
        code=code,
        severity=severity,
        detail=detail,
        receipt_ts=fact.receipt_raw,
        file=fact.file,
        line_no=fact.line_no,
    )


def _str(payload: Mapping[str, object], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


def _int(payload: Mapping[str, object], name: str) -> int | None:
    value = payload.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _display(fact: Fact, name: str) -> float | None:
    price = fact.prices.get(name)
    return price.display if price is not None else None


def _trade_ids(fact: Fact) -> list[str]:
    """``order.fill.trade_ids``: the trades this one fill event covers."""
    raw = fact.payload.get("trade_ids")
    return [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []


def _trade_counter(trade_id: str) -> tuple[int, int] | None:
    """``000042-000000117`` -> ``(42, 117)``, or None if it is not one.

    The id is minted as ``f"{run_seq:06d}-{trade_seq:09d}"``
    (:mod:`edumatcher.models.trade`), which is what makes a gap in the trade
    stream visible without a counter of the tool's own.
    """
    run, _, seq = trade_id.partition("-")
    if not seq or not run.isdigit() or not seq.isdigit():
        return None
    return int(run), int(seq)


@dataclass(slots=True)
class _Leg:
    """One ``order.fill`` as its trade's leg.

    ``coalesced`` marks a fill that named more than one trade -- an
    aggressor's sweep, reported once at a VWAP. Its quantity and price
    describe the sweep rather than this trade, so nothing may be compared
    against it.
    """

    order_id: str
    qty: int | None
    price: float | None
    coalesced: bool = False
    liquidity: str | None = None
    symbol: str | None = None


class Detector:
    """Section 12's cross-message findings, fed facts and then episodes.

    Reads the state model rather than duplicating it: the corridor in force
    for a symbol and the run the window is in are already there, and a second
    copy would be a second thing to keep right.
    """

    def __init__(
        self,
        state: StateModel,
        *,
        clock_skew_warn: float = DEFAULT_CLOCK_SKEW_WARN,
        strict: bool = False,
    ) -> None:
        self.state = state
        self.clock_skew_warn = clock_skew_warn
        #: ``ARRIVAL_SEQ_GAP`` fires only under ``--strict``: a window that
        #: omits another gateway's orders has gaps by construction, and a
        #: finding that is usually noise is a finding nobody reads.
        self.strict = strict
        self._submitted: set[str] = set()
        self._acked: set[str] = set()
        #: order_id -> (side, limit price in display money). Limit orders only.
        self._limits: dict[str, tuple[str, float]] = {}
        #: trade_id -> its legs, as the fills naming it are read.
        self._legs: dict[str, list[_Leg]] = {}
        #: Trade ids read so far, so a fill naming one that is not here is a
        #: fill whose trade is missing rather than merely not read yet -- the
        #: engine publishes the trade before either fill.
        self._trades: set[str] = set()
        #: Trade ids some fill has named and no ``trade.executed`` has yet
        #: accounted for. Emptied as each trade is read, so on a healthy log
        #: this holds nothing; what is left in it is what went missing.
        self._awaiting: set[str] = set()
        #: trade_id -> the orders whose drop copies named it. A set rather
        #: than a count so that two copies of one side do not pass as the two
        #: sides, and so the finding can say which side arrived.
        self._copies: dict[str, set[str]] = {}
        #: Whether this window contains a drop-copy feed at all. Without it a
        #: log from an engine with no drop-copy publisher configured would
        #: report every trade as missing both of its copies.
        self._drop_copy_seen = False
        #: The payload ``seq`` of the last drop copy read, and the run it
        #: belonged to. One counter, not one per gateway:
        #: ``engine/drop_copy.py`` counts on a module-level ``itertools.count``
        #: shared by every gateway's feed.
        self._last_drop_copy: int | None = None
        self._drop_copy_run: int | None = None
        self._last_trade_seq: dict[int, int] = {}
        self._last_arrival: int | None = None
        self._arrival_run: int | None = None

    # -- pass one: one fact at a time ---------------------------------------

    def observe(self, fact: Fact) -> tuple[Anomaly, ...]:
        """Findings this fact raises against everything read before it."""
        found: list[Anomaly] = []
        self._clocks(fact, found)
        if fact.kind == kinds.ORDER_NEW:
            self._on_order_new(fact, found)
        elif fact.kind == kinds.ORDER_ACK:
            self._acked.add(_str(fact.payload, "order_id") or "")
        elif fact.kind == kinds.ORDER_FILL:
            self._on_order_fill(fact, found)
        elif fact.kind == kinds.ORDER_AMENDED:
            self._on_order_amended(fact)
        elif fact.kind == kinds.TRADE_EXECUTED:
            self._on_trade(fact, found)
        elif fact.kind == kinds.DROP_COPY_EVENT:
            self._on_drop_copy(fact, found)
        return tuple(found)

    def _clocks(self, fact: Fact, found: list[Anomaly]) -> None:
        """The engine's and the client's clock against ``pm-audit``'s.

        Only the field that says *when this message happened*, which the Fact
        layer names: the spec has other epoch fields (``resume_at_ns`` is a
        future time, ``from_ts_ns`` a query bound) and comparing those to
        receipt would report every halt as skewed by however long it was due
        to last.

        Asked as a question about the clock rather than about a field name.
        Keying on the literal ``ts_ns`` exempted two whole streams without
        anyone noticing: ``order.fill`` declares no timestamp at all, and
        ``drop_copy`` calls its clock ``timestamp``.
        """
        stamped = next(
            (time for time in fact.times.values() if time.is_publication), None
        )
        if stamped is None:
            return
        drift = abs((stamped.when - fact.receipt_ts).total_seconds())
        if stamped.clock == CLOCK_ENGINE and drift > self.clock_skew_warn:
            found.append(
                _anomaly(
                    CLOCK_SKEW,
                    SEVERITY_WARN,
                    f"{fact.kind} engine clock is {drift:.3f}s from receipt "
                    f"(tolerance {self.clock_skew_warn:g}s)",
                    fact,
                )
            )
        elif stamped.clock == CLOCK_CLIENT and drift > _CLIENT_CLOCK_ABSURD_SECONDS:
            found.append(
                _anomaly(
                    CLIENT_CLOCK_ABSURD,
                    SEVERITY_INFO,
                    f"client clock is {drift / 3600:.1f}h from receipt; "
                    "priority used arrival_seq, not this",
                    fact,
                )
            )

    def _on_order_new(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "id")
        if order_id is None:
            return
        self._submitted.add(order_id)
        side = _str(fact.payload, "side")
        limit = _display(fact, "price_ticks")
        if side is not None and limit is not None:
            self._limits[order_id] = (side, limit)
        self._arrival(fact, found)

    def _on_order_amended(self, fact: Fact) -> None:
        """Move the limit an amendment moved.

        Without this the limit stays at whatever ``order.new`` said, and every
        fill after a repricing is measured against a price the order no longer
        has -- which reported sixty-three fills as trading through a limit
        they were comfortably inside. ``order.amended.price`` is display
        money, like ``order.amend``'s and unlike ``order.new``'s ticks.
        """
        order_id = _str(fact.payload, "order_id")
        limit = self._limits.get(order_id or "")
        if order_id is None or limit is None:
            return
        price = fact.payload.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            self._limits[order_id] = (limit[0], float(price))

    def _arrival(self, fact: Fact, found: list[Anomaly]) -> None:
        seq = _int(fact.payload, "arrival_seq")
        if not seq:
            # ``order.yaml``: "0 = unassigned". The sequence is stamped when
            # the book accepts the order, and ``order.new`` is the command as
            # the engine received it -- so on a real ``pm-audit`` trail the
            # field is 0 on every order. Comparing those reported 2854 of them
            # as claiming one queue position.
            return
        run = self.state.run.run_seq
        if run != self._arrival_run:
            # A restart restarts the counter (section 5.1.3), so nothing may
            # be compared across the boundary.
            self._arrival_run, self._last_arrival = run, seq
            return
        previous, self._last_arrival = self._last_arrival, seq
        if previous is None:
            return
        if seq <= previous:
            # Not under --strict, and an error rather than info: the counter
            # is specified as monotonic and time priority is keyed on it, so
            # two orders claiming one queue position is a priority bug. A
            # *gap* is expected whenever the window omits another gateway's
            # orders; a reuse is expected never.
            found.append(
                _anomaly(
                    ARRIVAL_SEQ_REUSED,
                    SEVERITY_ERROR,
                    f"arrival_seq {previous}->{seq}: "
                    + (
                        "two orders claim one queue position"
                        if seq == previous
                        else "the counter went backwards"
                    ),
                    fact,
                )
            )
        elif self.strict and seq > previous + 1:
            found.append(
                _anomaly(
                    ARRIVAL_SEQ_GAP,
                    SEVERITY_INFO,
                    f"arrival_seq {previous}->{seq}: "
                    f"{seq - previous - 1} submission(s) not in this window",
                    fact,
                )
            )

    def _on_order_fill(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        if order_id in self._submitted and order_id not in self._acked:
            # Guarded on having seen the submission: without it, every order
            # whose ack fell before the window would be reported as inverted.
            found.append(
                _anomaly(
                    FILL_BEFORE_ACK,
                    SEVERITY_WARN,
                    f"order {order_id} filled before it was acked",
                    fact,
                )
            )
        self._status_check(fact, order_id, found)
        self._limit_check(fact, order_id, found)
        self._legs_of(fact, order_id, found)

    def _status_check(self, fact: Fact, order_id: str, found: list[Anomaly]) -> None:
        """``status`` and ``remaining_qty`` say the same thing or the fill is
        wrong about one of them.

        ``order.yaml``: "remaining_qty reaching zero is what marks the order
        done; status FILLED says the same thing and the two must agree."
        ``QTY_MISMATCH`` cannot notice a breach, because the tally reconciles
        against ``quantity - remaining_qty`` whatever the status claims --
        the arithmetic stays self-consistent while the status does not.
        """
        status = _str(fact.payload, "status")
        remaining = _int(fact.payload, "remaining_qty")
        if status is None or remaining is None:
            return
        done = status == STATUS_FILLED
        if done == (remaining == 0):
            return
        found.append(
            _anomaly(
                FILL_STATUS_DISAGREE,
                SEVERITY_ERROR,
                f"order {order_id} fill says {status} with {remaining} "
                "remaining" + ("" if done else " and nothing left to fill"),
                fact,
            )
        )

    def _limit_check(self, fact: Fact, order_id: str, found: list[Anomaly]) -> None:
        limit = self._limits.get(order_id)
        price = _display(fact, "fill_price")
        if limit is None or price is None:
            return
        side, bound = limit
        if side == _SIDE_BUY:
            through = price > bound + _PRICE_EPSILON
        elif side == _SIDE_SELL:
            through = price < bound - _PRICE_EPSILON
        else:
            # Neither, so there is no limit to be through. Falling into the
            # sell branch for anything that is not "BUY" turned a corrupt or
            # renamed side value into a fabricated error-severity finding:
            # a `BUYY` order filling below its own buy limit was reported as
            # having traded through it. `UNKNOWN_ENUM` is where an unmapped
            # value belongs; this check has nothing to say about it.
            return
        if through:
            found.append(
                _anomaly(
                    PRICE_THROUGH_LIMIT,
                    SEVERITY_ERROR,
                    f"{side} order {order_id} filled at {price:g}, "
                    f"through its {bound:g} limit",
                    fact,
                )
            )

    def _legs_of(self, fact: Fact, order_id: str, found: list[Anomaly]) -> None:
        """Record this fill as a leg of every trade it names, and defer the
        check that those trades exist.

        A fill does not map one-to-one onto a trade. When an aggressor sweeps
        several resting orders the engine coalesces the whole sweep into a
        *single* fill carrying a VWAP price and citing every trade it touched
        (``order.fill.trade_ids`` says so, H5/H6) -- on a real run 316 of 603
        fills cited more than one. A coalesced leg's quantity and price are
        the sweep's, not any one trade's, so :meth:`_legs_agree` leaves them
        alone.

        ``FILL_WITHOUT_TRADE`` cannot be answered here: the engine publishes
        the fills *before* the trade that produced them -- the real order on
        the wire is ``order.fill, order.fill, trade.executed`` -- so at this
        moment the trade legitimately has not been read. It is answered a few
        hundred facts later, by :meth:`_resolve_named_trades`.
        """
        trade_ids = _trade_ids(fact)
        leg = _Leg(
            order_id=order_id,
            qty=_int(fact.payload, "fill_qty"),
            price=_display(fact, "fill_price"),
            coalesced=len(trade_ids) > 1,
            liquidity=_str(fact.payload, "liquidity_flag"),
            symbol=_str(fact.payload, "symbol"),
        )
        for trade_id in trade_ids:
            self._legs.setdefault(trade_id, []).append(leg)
            if trade_id not in self._trades:
                self._awaiting.add(trade_id)

    def _fills_name_their_trades(self, episode: Episode, found: list[Anomaly]) -> None:
        """Report this order's fills whose trades never arrived.

        Asked when the order's episode retires rather than when the fill is
        read, because the engine publishes a fill *before* the trade that
        produced it -- the real order on the wire is ``order.fill,
        order.fill, trade.executed``. Asking on arrival reported every fill in
        the log as missing its trade.

        The waiting set is emptied as each trade is read, so this is a lookup
        rather than a search, and a healthy log leaves nothing in it.
        """
        for event in episode.events:
            fact = event.fact
            if fact.kind != kinds.ORDER_FILL:
                continue
            missing = [t for t in _trade_ids(fact) if t in self._awaiting]
            if missing:
                found.append(
                    _anomaly(
                        FILL_WITHOUT_TRADE,
                        SEVERITY_ERROR,
                        f"fill on order {episode.anchor_key} names trade(s) "
                        f"{', '.join(missing)} that this window does not contain",
                        fact,
                    )
                )

    def _on_trade(self, fact: Fact, found: list[Anomaly]) -> None:
        trade_id = _str(fact.payload, "id")
        if trade_id is None:
            return
        self._trades.add(trade_id)
        self._awaiting.discard(trade_id)
        self._counter(fact, trade_id, found)
        self._corridor(fact, found)

    def _counter(self, fact: Fact, trade_id: str, found: list[Anomaly]) -> None:
        counter = _trade_counter(trade_id)
        if counter is None:
            return
        run, seq = counter
        previous = self._last_trade_seq.get(run)
        self._last_trade_seq[run] = seq
        if previous is not None and seq > previous + 1:
            found.append(
                _anomaly(
                    TRADE_COUNTER_GAP,
                    SEVERITY_ERROR,
                    f"run {run} trade counter {previous}->{seq}: "
                    f"{seq - previous - 1} trade(s) missing from the trail",
                    fact,
                )
            )

    def _corridor(self, fact: Fact, found: list[Anomaly]) -> None:
        symbol = self.state.symbols.get(fact.symbol or "")
        price = _display(fact, "price")
        if symbol is None or price is None:
            return
        low, high = symbol.corridor_low, symbol.corridor_high
        if low is None or high is None:
            return
        if low - _PRICE_EPSILON <= price <= high + _PRICE_EPSILON:
            return
        found.append(
            _anomaly(
                PRICE_OUTSIDE_CORRIDOR,
                SEVERITY_WARN,
                f"{fact.symbol} printed {price:g}, outside the "
                f"{low:g}-{high:g} corridor in force",
                fact,
            )
        )

    def _on_drop_copy(self, fact: Fact, found: list[Anomaly]) -> None:
        """The clearing feed, which nothing else in the tool reads.

        ``drop_copy.event`` is a *derived copy* of ``order.fill`` on a socket
        the trading gateway does not subscribe to, and it is what clearing,
        prime brokers and in-house risk reconcile on. The spec allows the two
        to differ in sequencing, buffering and the liquidity flag -- not in
        what was traded.
        """
        self._drop_copy_seen = True
        self._drop_copy_seq(fact, found)
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        for trade_id in _trade_ids(fact):
            self._copies.setdefault(trade_id, set()).add(order_id)
            self._copy_agrees(fact, trade_id, order_id, found)

    def _drop_copy_seq(self, fact: Fact, found: list[Anomaly]) -> None:
        """The feed's own counter, which is why the feed is sequenced.

        ``SEQ_GAP`` does not cover it: that reads the audit metadata's
        per-topic sequence, and this is the payload's -- one process-wide
        counter across every gateway's topic, so it is followed as one stream.
        A repeat counts as much as a gap, because a recipient "detects loss
        from a gap and a duplicate from a repeat" is the whole reason
        ``drop_copy.yaml`` gives for having it.
        """
        seq = _int(fact.payload, "seq")
        if seq is None:
            return
        run = self.state.run.run_seq
        if run != self._drop_copy_run:
            # The counter lives and dies with the engine process, so nothing
            # may be compared across a restart -- the same boundary
            # :meth:`_arrival` respects.
            self._drop_copy_run, self._last_drop_copy = run, seq
            return
        previous, self._last_drop_copy = self._last_drop_copy, seq
        if previous is None or seq == previous + 1:
            return
        if seq > previous:
            detail = f"{seq - previous - 1} event(s) missing from the feed"
        elif seq == previous:
            detail = "the feed repeated an event"
        else:
            detail = "the feed went backwards"
        found.append(
            _anomaly(
                DROP_COPY_SEQ_GAP,
                SEVERITY_ERROR,
                f"drop copy seq {previous}->{seq}: {detail}",
                fact,
            )
        )

    def _copy_agrees(
        self, fact: Fact, trade_id: str, order_id: str, found: list[Anomaly]
    ) -> None:
        """One drop copy against the private fill it copies.

        Paired by ``order_id`` within the trade both name, which is the pair
        the spec describes. A coalesced fill is exempt for the reason it is
        exempt in :meth:`_legs_match_the_print`: it reports a whole sweep at a
        VWAP while a drop copy reports this one execution, so the two *should*
        differ (H5/H6). A fill outside this window leaves nothing to compare,
        and saying nothing is the honest answer.
        """
        leg = next(
            (leg for leg in self._legs.get(trade_id, ()) if leg.order_id == order_id),
            None,
        )
        if leg is None or leg.coalesced:
            return
        qty = _int(fact.payload, "fill_qty")
        price = _display(fact, "fill_price")
        symbol = _str(fact.payload, "symbol")
        differs: list[str] = []
        if qty is not None and leg.qty is not None and qty != leg.qty:
            differs.append(f"fill_qty {qty} against {leg.qty}")
        if (
            price is not None
            and leg.price is not None
            and abs(price - leg.price) > _PRICE_EPSILON
        ):
            differs.append(f"fill_price {price:g} against {leg.price:g}")
        if symbol is not None and leg.symbol is not None and symbol != leg.symbol:
            differs.append(f"symbol {symbol} against {leg.symbol}")
        if differs:
            found.append(
                _anomaly(
                    DROP_COPY_DISAGREE,
                    SEVERITY_ERROR,
                    f"drop copy for order {order_id} on trade {trade_id} "
                    f"reports {', '.join(differs)} in the fill",
                    fact,
                )
            )

    # -- pass one, continued: one episode at a time -------------------------

    def close(self, episode: Episode) -> tuple[Anomaly, ...]:
        """Findings this episode raises now that it is complete.

        Called as the episode retires, which is the moment "it never arrived"
        stops being "it has not arrived yet". Also the moment everything held
        on the episode's behalf can be dropped.
        """
        if episode.kind == KIND_ORDER:
            return self._close_order(episode)
        if episode.kind == KIND_TRADE:
            return self._close_trade(episode)
        if episode.kind == KIND_COMMAND:
            return self._close_command(episode)
        if episode.kind == KIND_MARKET_PHASE:
            return self._close_phase(episode)
        return ()

    def _close_order(self, episode: Episode) -> tuple[Anomaly, ...]:
        found: list[Anomaly] = []
        present = {event.fact.kind for event in episode.events}
        last = episode.events[-1].fact

        if kinds.ORDER_NEW in present and kinds.ORDER_ACK not in present:
            found.append(
                _anomaly(
                    ACK_MISSING,
                    SEVERITY_WARN,
                    f"order {episode.anchor_key} was submitted but never acked",
                    episode.opened,
                )
            )
        if episode.outcome == OUTCOME_OPEN:
            found.append(
                _anomaly(
                    TERMINAL_MISSING,
                    SEVERITY_INFO,
                    f"order {episode.anchor_key} is still open at the end of "
                    "this window",
                    last,
                )
            )
        if kinds.ORDER_CANCELLED in present and kinds.ORDER_CANCEL not in present:
            cancelled = next(
                event.fact
                for event in episode.events
                if event.fact.kind == kinds.ORDER_CANCELLED
            )
            if _str(cancelled.payload, "cancel_reason") is None:
                found.append(
                    _anomaly(
                        CANCEL_UNSOLICITED,
                        SEVERITY_WARN,
                        f"order {episode.anchor_key} was cancelled with no "
                        "request in this window and no cancel_reason",
                        cancelled,
                    )
                )
        # A refusal answers the request as surely as a cancellation does --
        # section 12.1 says "no resulting order.cancelled *or rejection*", and
        # leaving the rejection out reported every properly-refused cancel
        # (ORDER_NOT_FOUND, say) as one the engine had ignored.
        refused = any(
            event.fact.kind == kinds.ORDER_ACK
            and event.fact.payload.get("accepted") is False
            for event in episode.events
        )
        if (
            kinds.ORDER_CANCEL in present
            and not refused
            and not (present & {kinds.ORDER_CANCELLED, kinds.ORDER_EXPIRED})
        ):
            found.append(
                _anomaly(
                    CANCEL_UNMATCHED,
                    SEVERITY_WARN,
                    f"cancel requested for order {episode.anchor_key} and "
                    "nothing came back",
                    last,
                )
            )

        self._fills_name_their_trades(episode, found)

        self._submitted.discard(episode.anchor_key)
        self._acked.discard(episode.anchor_key)
        self._limits.pop(episode.anchor_key, None)
        return tuple(found)

    def _close_trade(self, episode: Episode) -> tuple[Anomaly, ...]:
        found: list[Anomaly] = []
        trade_id = episode.anchor_key
        legs = self._legs.pop(trade_id, [])
        trade = episode.opened

        if len(legs) < 2:
            found.append(
                _anomaly(
                    TRADE_LEG_MISSING,
                    SEVERITY_ERROR,
                    f"trade {trade_id} has {len(legs)} fill leg(s), not 2",
                    trade,
                )
            )
        else:
            self._legs_agree(trade_id, legs, trade, found)
        self._legs_are_its_own(trade_id, legs, trade, found)
        self._legs_match_the_print(trade_id, legs, trade, found)
        self._copies_are_two(trade_id, trade, found)

        self._trades.discard(trade_id)
        return tuple(found)

    def _copies_are_two(self, trade_id: str, trade: Fact, found: list[Anomaly]) -> None:
        """Every trade produces two drop copies, one per counterparty.

        ``drop_copy.yaml`` says so outright, and the engine publishes them
        from the single trade path, so a trade with one is a clearing feed
        that told one side of a match about it. Warn rather than error for the
        reason ``TERMINAL_MISSING`` is info: a window edge cuts one off.

        Silent when the window holds no drop copies at all -- an engine
        configured without the publisher would otherwise report every trade it
        ever printed.
        """
        copies = self._copies.pop(trade_id, set())
        if not self._drop_copy_seen or len(copies) == 2:
            return
        found.append(
            _anomaly(
                DROP_COPY_MISSING,
                SEVERITY_WARN,
                f"trade {trade_id} produced {len(copies)} drop copy(ies), not 2"
                + (f": {', '.join(sorted(copies))}" if copies else ""),
                trade,
            )
        )

    def _legs_are_its_own(
        self,
        trade_id: str,
        legs: Sequence[_Leg],
        trade: Fact,
        found: list[Anomaly],
    ) -> None:
        """The legs are the two orders the trade names, and no others.

        ``TRADE_LEG_MISSING`` counts legs. Counting cannot tell a fill on the
        right order from one on an order this trade never touched, and two of
        the wrong legs count as two -- so a fill on the wrong participant's
        blotter passes, and so does a third leg on a trade that had two.

        ``buy_order_id`` and ``sell_order_id`` are both ``required: true``, so
        the comparison is always available. Run outside the ``len(legs) < 2``
        branch on purpose: a trade with one leg still wants to know that the
        one it has is not its own.
        """
        sides = {
            side
            for name in ("buy_order_id", "sell_order_id")
            if (side := _str(trade.payload, name)) is not None
        }
        if not sides:
            return
        strangers = sorted({leg.order_id for leg in legs} - sides)
        if strangers:
            found.append(
                _anomaly(
                    TRADE_LEG_UNKNOWN,
                    SEVERITY_ERROR,
                    f"trade {trade_id} was filled by {', '.join(strangers)}, "
                    f"which it does not name as either side",
                    trade,
                )
            )

    def _legs_match_the_print(
        self,
        trade_id: str,
        legs: Sequence[_Leg],
        trade: Fact,
        found: list[Anomaly],
    ) -> None:
        """Each leg against the trade, which is the third party.

        :meth:`_legs_agree` compares the legs to each other, and two equally
        wrong legs agree: a trade printing 200 whose fills both report 150 is
        a public tape and a pair of private reports telling a reader two
        different things, in silence. The print is the only account of the
        match that neither fill can argue with.

        Coalesced legs are exempt for the reason they are exempt there: a
        sweep reported once at a VWAP is not any one trade's quantity or
        price (H5/H6).
        """
        printed_qty = _int(trade.payload, "quantity")
        printed_price = _display(trade, "price")
        for leg in legs:
            if leg.coalesced:
                continue
            if printed_qty is not None and leg.qty is not None:
                if leg.qty != printed_qty:
                    found.append(
                        _anomaly(
                            PRINT_QTY_DISAGREE,
                            SEVERITY_ERROR,
                            f"trade {trade_id} printed {printed_qty} but "
                            f"{leg.order_id}'s fill reports {leg.qty}",
                            trade,
                        )
                    )
            if printed_price is not None and leg.price is not None:
                if abs(leg.price - printed_price) > _PRICE_EPSILON:
                    found.append(
                        _anomaly(
                            PRINT_PRICE_DISAGREE,
                            SEVERITY_ERROR,
                            f"trade {trade_id} printed {printed_price:g} but "
                            f"{leg.order_id}'s fill reports {leg.price:g}",
                            trade,
                        )
                    )
            self._liquidity_check(trade_id, leg, trade, found)

    def _liquidity_check(
        self,
        trade_id: str,
        leg: _Leg,
        trade: Fact,
        found: list[Anomaly],
    ) -> None:
        """MAKER and TAKER against the trade's ``aggressor_side``.

        Both specs derive the flag the same way -- the aggressing side is the
        TAKER, the resting side the MAKER, and exactly one of a trade's two
        events is TAKER. An auction print has no aggressor and the engine
        flags both sides MAKER, which is the case ``lexicon.fill_verb``
        already reasons about.

        A billing invariant: maker and taker fees invert on it, so a wrong
        flag is not a display problem.
        """
        if leg.liquidity is None:
            return
        aggressor = _str(trade.payload, "aggressor_side")
        if aggressor == _AGGRESSOR_AUCTION:
            expected = _MAKER
        elif aggressor in (_SIDE_BUY, _SIDE_SELL):
            aggressing = _str(trade.payload, _AGGRESSOR_FIELD[aggressor])
            expected = _TAKER if leg.order_id == aggressing else _MAKER
        else:
            return
        if leg.liquidity != expected:
            found.append(
                _anomaly(
                    LIQUIDITY_FLAG_DISAGREE,
                    SEVERITY_ERROR,
                    f"trade {trade_id} was aggressed {aggressor.lower()}, so "
                    f"{leg.order_id} is the {expected.lower()}; its fill says "
                    f"{leg.liquidity}",
                    trade,
                )
            )

    def _legs_agree(
        self,
        trade_id: str,
        legs: Sequence[_Leg],
        trade: Fact,
        found: list[Anomaly],
    ) -> None:
        """Compare the two sides of a trade, where they are comparable.

        Only legs that name this trade and nothing else. A coalesced leg
        reports a whole sweep, so it and a single-trade leg *should* differ,
        and saying so is noise -- it was nine hundred findings of noise.
        """
        comparable = [leg for leg in legs if not leg.coalesced]
        if len(comparable) < 2:
            return
        quantities = {leg.qty for leg in comparable}
        prices = {leg.price for leg in comparable}
        if len(quantities) > 1:
            found.append(
                _anomaly(
                    LEG_QTY_DISAGREE,
                    SEVERITY_ERROR,
                    f"trade {trade_id} legs report "
                    + ", ".join(f"{leg.order_id}={leg.qty}" for leg in comparable),
                    trade,
                )
            )
        if len(prices) > 1:
            found.append(
                _anomaly(
                    LEG_PRICE_DISAGREE,
                    SEVERITY_ERROR,
                    f"trade {trade_id} legs report "
                    + ", ".join(f"{leg.order_id}={leg.price:g}" for leg in comparable),
                    trade,
                )
            )

    def _close_command(self, episode: Episode) -> tuple[Anomaly, ...]:
        if any(event.fact.kind.endswith(_ACK_SUFFIX) for event in episode.events):
            return ()
        if not any(event.fact.kind == kinds.ADMIN_ACTION for event in episode.events):
            return (
                _anomaly(
                    COMMAND_UNACKED,
                    SEVERITY_WARN,
                    f"command {episode.anchor_key} was issued and never acked",
                    episode.opened,
                ),
            )
        return ()

    def _close_phase(self, episode: Episode) -> tuple[Anomaly, ...]:
        halts = [
            event.fact
            for event in episode.events
            if event.fact.kind == kinds.CIRCUIT_BREAKER_HALT
        ]
        if halts and episode.outcome == OUTCOME_OPEN:
            return (
                _anomaly(
                    HALT_UNRESUMED,
                    SEVERITY_INFO,
                    f"{episode.symbol} was halted at "
                    f"{_clock(halts[0].receipt_ts)} and not resumed in this "
                    "window",
                    halts[0],
                ),
            )
        return ()


def _clock(when: datetime) -> str:
    return when.strftime("%H:%M:%S.%f")[:-3]


def observed(steps: Iterable[Step], detector: Detector) -> Iterator[Step]:
    """Add :meth:`Detector.observe`'s findings to each step as it is read.

    Wraps the reconstructed stream rather than living inside
    :class:`Reconstruction`, for the same reason :func:`detected` wraps the
    assembler: this module imports ``Episode``, so nothing ``Episode`` is
    built from may import this module. Must be applied *before* the
    assembler, and after the state model -- which reconstruction has already
    applied by the time a Step exists -- because the corridor a print is
    checked against is read off that model.
    """
    for step in steps:
        found = detector.observe(step.fact)
        yield replace(step, anomalies=step.anomalies + found) if found else step


def detected(episodes: Iterable[Episode], detector: Detector) -> Iterator[Episode]:
    """Attach :meth:`Detector.close`'s findings to each episode as it retires.

    A generator rather than a hook inside the assembler, because the assembler
    would then have to import this module and this module has to import the
    assembler's :class:`Episode`. Wrapping at the call site costs one line and
    leaves the dependency pointing one way.
    """
    for episode in episodes:
        episode.anomalies = detector.close(episode)
        yield episode
