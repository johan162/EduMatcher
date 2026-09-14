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
    CANCEL_UNMATCHED,
    CANCEL_UNSOLICITED,
    CLIENT_CLOCK_ABSURD,
    CLOCK_SKEW,
    COMMAND_UNACKED,
    FILL_BEFORE_ACK,
    FILL_WITHOUT_TRADE,
    HALT_UNRESUMED,
    LEG_PRICE_DISAGREE,
    LEG_QTY_DISAGREE,
    PRICE_OUTSIDE_CORRIDOR,
    PRICE_THROUGH_LIMIT,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    TERMINAL_MISSING,
    TRADE_COUNTER_GAP,
    TRADE_LEG_MISSING,
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
from edumatcher.audit.replay.state import StateModel

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
    """One ``order.fill`` as its trade's leg."""

    order_id: str
    qty: int | None
    price: float | None


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
        elif fact.kind == kinds.TRADE_EXECUTED:
            self._on_trade(fact, found)
        return tuple(found)

    def _clocks(self, fact: Fact, found: list[Anomaly]) -> None:
        """The engine's and the client's clock against ``pm-audit``'s.

        Only ``ts_ns`` -- the field that says *when this happened*. The spec
        has other epoch fields (``resume_at_ns`` is a future time,
        ``from_ts_ns`` a query bound) and comparing those to receipt would
        report every halt as skewed by however long it was due to last.
        """
        stamped = fact.times.get("ts_ns")
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

    def _arrival(self, fact: Fact, found: list[Anomaly]) -> None:
        seq = _int(fact.payload, "arrival_seq")
        if seq is None:
            return
        run = self.state.run.run_seq
        if run != self._arrival_run:
            # A restart restarts the counter (section 5.1.3), so nothing may
            # be compared across the boundary.
            self._arrival_run, self._last_arrival = run, seq
            return
        previous, self._last_arrival = self._last_arrival, seq
        if self.strict and previous is not None and seq > previous + 1:
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
        self._limit_check(fact, order_id, found)
        self._legs_of(fact, order_id, found)

    def _limit_check(self, fact: Fact, order_id: str, found: list[Anomaly]) -> None:
        limit = self._limits.get(order_id)
        price = _display(fact, "fill_price")
        if limit is None or price is None:
            return
        side, bound = limit
        through = (
            price > bound + _PRICE_EPSILON
            if side == _SIDE_BUY
            else price < bound - _PRICE_EPSILON
        )
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
        raw = fact.payload.get("trade_ids")
        trade_ids = (
            [t for t in raw if isinstance(t, str)] if isinstance(raw, list) else []
        )
        missing = [t for t in trade_ids if t not in self._trades]
        if missing:
            found.append(
                _anomaly(
                    FILL_WITHOUT_TRADE,
                    SEVERITY_ERROR,
                    f"fill on order {order_id} names trade(s) "
                    f"{', '.join(missing)} that this window does not contain",
                    fact,
                )
            )
        leg = _Leg(
            order_id=order_id,
            qty=_int(fact.payload, "fill_qty"),
            price=_display(fact, "fill_price"),
        )
        for trade_id in trade_ids:
            self._legs.setdefault(trade_id, []).append(leg)

    def _on_trade(self, fact: Fact, found: list[Anomaly]) -> None:
        trade_id = _str(fact.payload, "id")
        if trade_id is None:
            return
        self._trades.add(trade_id)
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
        if kinds.ORDER_CANCEL in present and not (
            present & {kinds.ORDER_CANCELLED, kinds.ORDER_EXPIRED}
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

        self._trades.discard(trade_id)
        return tuple(found)

    def _legs_agree(
        self,
        trade_id: str,
        legs: Sequence[_Leg],
        trade: Fact,
        found: list[Anomaly],
    ) -> None:
        quantities = {leg.qty for leg in legs}
        prices = {leg.price for leg in legs}
        if len(quantities) > 1:
            found.append(
                _anomaly(
                    LEG_QTY_DISAGREE,
                    SEVERITY_ERROR,
                    f"trade {trade_id} legs report "
                    + ", ".join(f"{leg.order_id}={leg.qty}" for leg in legs),
                    trade,
                )
            )
        if len(prices) > 1:
            found.append(
                _anomaly(
                    LEG_PRICE_DISAGREE,
                    SEVERITY_ERROR,
                    f"trade {trade_id} legs report "
                    + ", ".join(f"{leg.order_id}={leg.price:g}" for leg in legs),
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
