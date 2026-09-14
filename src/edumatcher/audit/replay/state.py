"""The four live models the reconstruction keeps while streaming (section 7.1).

These answer *"what was true at this moment?"*, which is the question a raw log
cannot. A `reject_code=CIRCUIT_BREAKER_ACTIVE` on its own says an order was
refused; with the market model beside it the tool can say the symbol had been
halted since 09:41:12 on a 5.2% move through the upper corridor, and quote the
corridor the original halt published.

Every model is fed Facts in canonical order and **never raises**. This is the
tool someone reaches for when the exchange is already misbehaving, so a
malformed line has to come out as a finding, not a traceback. Anything the
model cannot reconcile is returned as an :class:`Anomaly`; nothing is dropped.

Bounded-ness is driven from outside. Section 7.1 retires an entry once its
episode closes and falls out of the reorder window, and only the episode
assembler knows when that is -- so it calls :meth:`StateModel.retire_order`
and the model itself keeps whatever it is given. Left alone it keeps
everything, which is what makes ``FILL_AFTER_TERMINAL`` and ``ACK_DUPLICATE``
work at any distance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, ClassVar, Mapping

from edumatcher.audit.replay.anomalies import (
    ACK_DUPLICATE,
    FILL_AFTER_TERMINAL,
    ILLEGAL_STATUS_TRANSITION,
    QTY_MISMATCH,
    REMAINING_NOT_MONOTONIC,
    RESUME_WITHOUT_HALT,
    RUN_SEQ_CHANGE,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    Anomaly,
)
from edumatcher.audit.replay import kinds
from edumatcher.audit.replay.facts import Fact

# ---------------------------------------------------------------------------
# The status ladder
# ---------------------------------------------------------------------------

STATUS_NEW = "NEW"
STATUS_PARTIAL = "PARTIAL"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_REJECTED = "REJECTED"
STATUS_EXPIRED = "EXPIRED"

#: The four states an order cannot leave.
TERMINAL_STATUSES = frozenset(
    {STATUS_FILLED, STATUS_CANCELLED, STATUS_REJECTED, STATUS_EXPIRED}
)

#: ``NEW -> PARTIAL -> FILLED | CANCELLED | REJECTED | EXPIRED`` (section 7.1),
#: written out rather than derived so that what counts as legal is reviewable
#: in one place. A repeat of the current status is legal everywhere: the engine
#: restates status on every fill, and two fills of one order both say PARTIAL.
_LEGAL_TRANSITIONS: Mapping[str, frozenset[str]] = {
    STATUS_NEW: frozenset(
        {
            STATUS_NEW,
            STATUS_PARTIAL,
            STATUS_FILLED,
            STATUS_CANCELLED,
            STATUS_REJECTED,
            STATUS_EXPIRED,
        }
    ),
    STATUS_PARTIAL: frozenset(
        {
            STATUS_PARTIAL,
            STATUS_FILLED,
            STATUS_CANCELLED,
            STATUS_EXPIRED,
        }
    ),
    STATUS_FILLED: frozenset({STATUS_FILLED}),
    STATUS_CANCELLED: frozenset({STATUS_CANCELLED}),
    STATUS_REJECTED: frozenset({STATUS_REJECTED}),
    STATUS_EXPIRED: frozenset({STATUS_EXPIRED}),
}

#: ``circuit_breaker.halt.halt_source``. The spec's two values, not the two the
#: design text guessed at: a halt is either the breaker's own or an admin's,
#: and a resume names the same source so the two can be paired.
HALT_SOURCE_BREAKER = "CB"
HALT_SOURCE_ADMIN = "ADMIN"


def _int(payload: Mapping[str, Any], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _str(payload: Mapping[str, Any], name: str) -> str | None:
    value = payload.get(name)
    return value if isinstance(value, str) and value else None


# ---------------------------------------------------------------------------
# Order model
# ---------------------------------------------------------------------------


@dataclass
class OrderState:
    """One order's life, as the trail records it.

    ``quantity`` and ``remaining_qty`` come from the messages; ``filled_qty``
    is the tool's own running tally of ``fill_qty``. Keeping both is the point:
    section 12.2's ``QTY_MISMATCH`` is exactly the disagreement between them,
    and it cannot be noticed by a model that stores only one.
    """

    order_id: str
    status: str = STATUS_NEW
    symbol: str | None = None
    side: str | None = None
    order_type: str | None = None
    tif: str | None = None
    gateway_id: str | None = None
    origin: str | None = None
    quantity: int | None = None
    remaining_qty: int | None = None
    filled_qty: int = 0
    fills: int = 0
    #: Parentage, all optional: an order may be a quote leg, an OCO leg or a
    #: combo leg, and the narration reads very differently in each case.
    quote_id: str | None = None
    oco_group_id: str | None = None
    combo_parent_id: str | None = None
    leg_index: int | None = None
    client_tag: str | None = None
    arrival_seq: int | None = None
    #: Why it ended, when it did: a ``cancel_reason`` or an ack's
    #: ``reject_code``. The status alone says CANCELLED; this says by whom.
    ended_because: str | None = None
    acked: bool = False
    opened_ts: datetime | None = None
    closed_ts: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass
class RunState:
    """The engine run the window is looking at (section 5.1.3).

    Order ids are UUIDs and globally unique, but ``arrival_seq`` and the trade
    counter restart with the engine, so anything reasoning about sequence has
    to know which run it is in. A change of run is narrated as a first-class
    event rather than silently absorbed.
    """

    run_seq: int | None = None
    recovery_seen: bool = False
    recovery_counts: dict[str, int] = field(default_factory=dict)
    recovery_failures: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Market model
# ---------------------------------------------------------------------------


@dataclass
class SymbolState:
    """What was true of one instrument at a moment.

    This is the model that turns a reject code into a sentence. A halt records
    where it came from, what corridor was in force and when it was due to
    resume, because those are the three things a reader asks next.
    """

    symbol: str
    session_state: str | None = None
    halted: bool = False
    halt_source: str | None = None
    halt_level: str | None = None
    halted_since: datetime | None = None
    corridor_low: float | None = None
    corridor_high: float | None = None
    resume_at: datetime | None = None
    trigger_price: float | None = None
    reference_price: float | None = None
    last_price: float | None = None

    def describe_halt(self) -> str:
        """One clause naming why this symbol is halted, for a rejection."""
        if not self.halted:
            return "not halted"
        who = (
            "the circuit breaker"
            if self.halt_source == HALT_SOURCE_BREAKER
            else "an admin halt"
        )
        parts = [f"halted by {who}"]
        if self.halted_since is not None:
            parts.append(f"since {self.halted_since.strftime('%H:%M:%S.%f')[:-3]}")
        if self.halt_level:
            parts.append(f"at level {self.halt_level}")
        if self.corridor_low is not None and self.corridor_high is not None:
            parts.append(f"corridor {self.corridor_low:g}-{self.corridor_high:g}")
        return ", ".join(parts)


@dataclass
class GatewayState:
    """Per participant: when it was connected, and what to call it.

    ``description`` is what makes actor names readable -- "Nordic Equities
    desk" rather than TRADER01 -- and it arrives once, on
    ``system.gateway_auth``, so it has to be remembered when it does.
    """

    gateway_id: str
    description: str | None = None
    auth_accepted: bool | None = None
    auth_reason: str | None = None
    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    disconnect_reason: str | None = None
    orders: int = 0
    trades: int = 0

    @property
    def label(self) -> str:
        return (
            f"{self.gateway_id} ({self.description})"
            if self.description
            else self.gateway_id
        )


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


class StateModel:
    """All four models, fed one Fact at a time in canonical order.

    :meth:`apply` returns the findings that Fact produced and nothing else;
    the caller decides what to do with them. Returning rather than logging
    keeps the model a pure function of the stream, which is what lets a test
    assert on a single transition without capturing output.
    """

    def __init__(self) -> None:
        self.orders: dict[str, OrderState] = {}
        self.symbols: dict[str, SymbolState] = {}
        self.gateways: dict[str, GatewayState] = {}
        self.run = RunState()
        #: Market-wide, because session.state names no symbol. Held here as
        #: well as on each SymbolState so a symbol first seen after the
        #: transition still knows which session it is trading in.
        self.session_state: str | None = None

    # -- lookups the link resolver and the renderers use --------------------

    def symbol(self, name: str) -> SymbolState:
        state = self.symbols.get(name)
        if state is None:
            state = SymbolState(symbol=name, session_state=self.session_state)
            self.symbols[name] = state
        return state

    def gateway(self, name: str) -> GatewayState:
        state = self.gateways.get(name)
        if state is None:
            state = GatewayState(gateway_id=name)
            self.gateways[name] = state
        return state

    def retire_order(self, order_id: str) -> None:
        """Forget one order, once its episode has fallen out of the window.

        Section 7.1's retirement, called by the episode assembler because that
        is the only thing that knows an order's story is over. Until it runs
        the model keeps every order it has seen, which is what makes
        ``FILL_AFTER_TERMINAL`` work at any distance -- and what would make a
        day-long log unbounded.
        """
        self.orders.pop(order_id, None)

    # -- the one entry point ------------------------------------------------

    def apply(self, fact: Fact) -> tuple[Anomaly, ...]:
        found: list[Anomaly] = []
        handler = self._HANDLERS.get(fact.kind)
        if handler is not None:
            handler(self, fact, found)
        self._track_run(fact, found)
        return tuple(found)

    # -- order lifecycle ----------------------------------------------------

    def _order(self, order_id: str, fact: Fact) -> OrderState:
        state = self.orders.get(order_id)
        if state is None:
            state = OrderState(order_id=order_id, opened_ts=fact.receipt_ts)
            self.orders[order_id] = state
        return state

    def _advance(
        self, order: OrderState, to_status: str, fact: Fact, found: list[Anomaly]
    ) -> None:
        """Move an order along the ladder, reporting a step that is not on it.

        An illegal transition is recorded and **then applied**. Refusing it
        would leave the model describing a world the log does not, and the
        reader is better served by a model that matches the bytes plus a
        finding saying the bytes are wrong.
        """
        allowed = _LEGAL_TRANSITIONS.get(order.status)
        if allowed is not None and to_status not in allowed:
            found.append(
                _anomaly(
                    ILLEGAL_STATUS_TRANSITION,
                    SEVERITY_ERROR,
                    f"order {order.order_id} went {order.status} -> {to_status}, "
                    f"which is not on the ladder",
                    fact,
                )
            )
        order.status = to_status
        if to_status in TERMINAL_STATUSES:
            order.closed_ts = fact.receipt_ts

    def _on_order_new(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        order.symbol = fact.symbol or order.symbol
        order.side = _str(fact.payload, "side")
        order.order_type = _str(fact.payload, "order_type")
        order.tif = _str(fact.payload, "tif")
        order.gateway_id = _str(fact.payload, "gateway_id")
        order.origin = _str(fact.payload, "origin")
        order.quantity = _int(fact.payload, "quantity")
        order.remaining_qty = _int(fact.payload, "remaining_qty")
        order.quote_id = _str(fact.payload, "quote_id")
        order.oco_group_id = _str(fact.payload, "oco_group_id")
        order.combo_parent_id = _str(fact.payload, "combo_parent_id")
        order.leg_index = _int(fact.payload, "leg_index")
        order.client_tag = _str(fact.payload, "client_tag")
        order.arrival_seq = _int(fact.payload, "arrival_seq")
        if order.gateway_id:
            gateway = self.gateway(order.gateway_id)
            gateway.orders += 1

    def _on_order_ack(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        if order.acked:
            found.append(
                _anomaly(
                    ACK_DUPLICATE,
                    SEVERITY_ERROR,
                    f"order {order_id} was acked twice",
                    fact,
                )
            )
        order.acked = True
        order.symbol = fact.payload.get("symbol") or order.symbol
        order.side = _str(fact.payload, "side") or order.side
        order.order_type = _str(fact.payload, "order_type") or order.order_type
        order.tif = _str(fact.payload, "tif") or order.tif
        order.gateway_id = _str(fact.payload, "gateway_id") or order.gateway_id
        order.client_tag = _str(fact.payload, "client_tag") or order.client_tag
        if order.quantity is None:
            order.quantity = _int(fact.payload, "qty")
        if fact.payload.get("accepted") is False:
            order.ended_because = _str(fact.payload, "reject_code") or "REJECTED"
            self._advance(order, STATUS_REJECTED, fact, found)

    def _on_order_fill(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        if order.terminal:
            found.append(
                _anomaly(
                    FILL_AFTER_TERMINAL,
                    SEVERITY_ERROR,
                    f"order {order_id} was already {order.status} when a fill arrived",
                    fact,
                )
            )
        fill_qty = _int(fact.payload, "fill_qty")
        remaining = _int(fact.payload, "remaining_qty")
        if remaining is not None and order.remaining_qty is not None:
            if remaining > order.remaining_qty:
                found.append(
                    _anomaly(
                        REMAINING_NOT_MONOTONIC,
                        SEVERITY_ERROR,
                        f"order {order_id} remaining_qty rose "
                        f"{order.remaining_qty} -> {remaining}",
                        fact,
                    )
                )
        if fill_qty is not None:
            order.filled_qty += fill_qty
            order.fills += 1
        if remaining is not None:
            order.remaining_qty = remaining
        if order.quantity is None:
            order.quantity = _int(fact.payload, "qty")
        order.symbol = fact.payload.get("symbol") or order.symbol
        order.gateway_id = _str(fact.payload, "gateway_id") or order.gateway_id
        if order.gateway_id:
            self.gateway(order.gateway_id).trades += 1

        status = _str(fact.payload, "status")
        if status:
            self._advance(order, status, fact, found)
        # Checked after the status move so a terminal fill is reconciled too:
        # the sum of what was filled must equal what left the book.
        if order.quantity is not None and order.remaining_qty is not None:
            expected = order.quantity - order.remaining_qty
            if expected != order.filled_qty:
                found.append(
                    _anomaly(
                        QTY_MISMATCH,
                        SEVERITY_ERROR,
                        f"order {order_id} fills total {order.filled_qty} but "
                        f"quantity - remaining_qty = {expected}",
                        fact,
                    )
                )

    def _on_order_cancelled(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        order.symbol = fact.payload.get("symbol") or order.symbol
        order.ended_because = _str(fact.payload, "cancel_reason")
        self._advance(order, STATUS_CANCELLED, fact, found)

    def _on_oco_cancelled(self, fact: Fact, found: list[Anomaly]) -> None:
        """The only record that an OCO sibling ended.

        When one leg reaches a terminal state the engine cancels the other and
        publishes ``oco.cancelled`` for it -- and *not* an ``order.cancelled``
        (``engine/main.py::_check_oco_after_event``). So this is the single
        fact that ends that order, and a model that ignored it would leave the
        leg resting for the rest of the window.
        """
        order_id = _str(fact.payload, "cancelled_order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        order.ended_because = _str(fact.payload, "reason") or "OCO_SIBLING_CANCELLED"
        self._advance(order, STATUS_CANCELLED, fact, found)

    def _on_order_expired(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        order.symbol = fact.payload.get("symbol") or order.symbol
        self._advance(order, STATUS_EXPIRED, fact, found)

    def _on_order_amended(self, fact: Fact, found: list[Anomaly]) -> None:
        order_id = _str(fact.payload, "order_id")
        if order_id is None:
            return
        order = self._order(order_id, fact)
        remaining = _int(fact.payload, "remaining_qty")
        if remaining is not None:
            order.remaining_qty = remaining
        qty = _int(fact.payload, "qty")
        if qty is not None:
            # An amend restates the order's size, so the tally it is reconciled
            # against has to move with it or every later fill looks wrong.
            order.quantity = qty

    # -- market -------------------------------------------------------------

    def _on_halt(self, fact: Fact, found: list[Anomaly]) -> None:
        if fact.symbol is None:
            return
        state = self.symbol(fact.symbol)
        state.halted = True
        state.halt_source = _str(fact.payload, "halt_source")
        state.halt_level = _str(fact.payload, "level")
        state.halted_since = fact.receipt_ts
        state.corridor_low = _price(fact, "corridor_low")
        state.corridor_high = _price(fact, "corridor_high")
        state.trigger_price = _price(fact, "trigger_price")
        state.reference_price = _price(fact, "reference_price")
        resume = fact.times.get("resume_at_ns")
        state.resume_at = resume.when if resume is not None else None

    def _on_extend(self, fact: Fact, found: list[Anomaly]) -> None:
        if fact.symbol is None:
            return
        state = self.symbol(fact.symbol)
        state.corridor_low = _price(fact, "corridor_low")
        state.corridor_high = _price(fact, "corridor_high")
        resume = fact.times.get("resume_at_ns")
        state.resume_at = resume.when if resume is not None else None

    def _on_resume(self, fact: Fact, found: list[Anomaly]) -> None:
        if fact.symbol is None:
            return
        state = self.symbol(fact.symbol)
        if not state.halted:
            found.append(
                _anomaly(
                    RESUME_WITHOUT_HALT,
                    SEVERITY_WARN,
                    f"{fact.symbol} resumed with no halt on record",
                    fact,
                )
            )
        state.halted = False
        state.halt_source = None
        state.halt_level = None
        state.halted_since = None
        state.resume_at = None
        state.corridor_low = None
        state.corridor_high = None
        printed = _price(fact, "print_price")
        if printed is not None:
            state.last_price = printed

    def _on_session_state(self, fact: Fact, found: list[Anomaly]) -> None:
        state_name = _str(fact.payload, "state")
        if state_name is None:
            return
        # session.state is market-wide: it names no symbol, so it moves every
        # symbol the window has seen, and is remembered for symbols met later.
        self.session_state = state_name
        for symbol_state in self.symbols.values():
            symbol_state.session_state = state_name

    def _on_trade(self, fact: Fact, found: list[Anomaly]) -> None:
        if fact.symbol is not None:
            price = fact.prices.get("price")
            if price is not None and price.display is not None:
                self.symbol(fact.symbol).last_price = price.display

    # -- gateways -----------------------------------------------------------

    def _on_gateway_auth(self, fact: Fact, found: list[Anomaly]) -> None:
        gateway_id = _str(fact.payload, "gateway_id") or fact.actor
        if gateway_id is None:
            return
        state = self.gateway(gateway_id)
        state.description = _str(fact.payload, "description") or state.description
        accepted = fact.payload.get("accepted")
        state.auth_accepted = accepted if isinstance(accepted, bool) else None
        state.auth_reason = _str(fact.payload, "reason")
        if state.connected_at is None:
            state.connected_at = fact.receipt_ts

    def _on_gateway_connect(self, fact: Fact, found: list[Anomaly]) -> None:
        gateway_id = _str(fact.payload, "gateway_id") or fact.actor
        if gateway_id is None:
            return
        state = self.gateway(gateway_id)
        state.connected_at = fact.receipt_ts
        state.disconnected_at = None
        state.disconnect_reason = None

    def _on_gateway_gone(self, fact: Fact, found: list[Anomaly]) -> None:
        gateway_id = _str(fact.payload, "gateway_id") or fact.actor
        if gateway_id is None:
            return
        state = self.gateway(gateway_id)
        state.disconnected_at = fact.receipt_ts
        state.disconnect_reason = _str(fact.payload, "reason")

    # -- run ----------------------------------------------------------------

    def _on_startup_recovery(self, fact: Fact, found: list[Anomaly]) -> None:
        self.run.recovery_seen = True
        for name in (
            "restored_orders",
            "discarded_stale_day_orders",
            "failed_orders",
            "quote_remnants_restored",
            "rebuilt_quotes",
            "restored_combos",
        ):
            value = _int(fact.payload, name)
            if value is not None:
                self.run.recovery_counts[name] = value

    def _on_recovery_item(self, fact: Fact, found: list[Anomaly]) -> None:
        # AR-0.5 made recovery per-entity. "Which order failed to restore?" was
        # unanswerable while the trail carried only the counts above.
        if _str(fact.payload, "outcome") in ("FAILED", "DISCARDED"):
            entity = _str(fact.payload, "entity_id")
            if entity:
                self.run.recovery_failures.append(entity)

    def _track_run(self, fact: Fact, found: list[Anomaly]) -> None:
        run_seq = _int(fact.payload, "run_seq")
        if run_seq is None:
            return
        if self.run.run_seq is None:
            self.run.run_seq = run_seq
            return
        if run_seq != self.run.run_seq:
            found.append(
                _anomaly(
                    RUN_SEQ_CHANGE,
                    SEVERITY_INFO,
                    f"engine restarted (run {self.run.run_seq} -> {run_seq})",
                    fact,
                )
            )
            self.run.run_seq = run_seq
            self.run.recovery_seen = False
            self.run.recovery_counts = {}
            self.run.recovery_failures = []

    #: Dispatch by message kind. A table rather than a chain of ``if`` so that
    #: what the model reacts to is one readable list, and a topic it ignores is
    #: ignored explicitly rather than by falling off the end of a chain. In the
    #: class body rather than beside it so the handlers stay private.
    _HANDLERS: ClassVar[
        dict[str, Callable[["StateModel", Fact, list[Anomaly]], None]]
    ] = {
        kinds.ORDER_NEW: _on_order_new,
        kinds.ORDER_ACK: _on_order_ack,
        kinds.ORDER_FILL: _on_order_fill,
        kinds.ORDER_CANCELLED: _on_order_cancelled,
        kinds.OCO_CANCELLED: _on_oco_cancelled,
        kinds.ORDER_EXPIRED: _on_order_expired,
        kinds.ORDER_AMENDED: _on_order_amended,
        kinds.TRADE_EXECUTED: _on_trade,
        kinds.CIRCUIT_BREAKER_HALT: _on_halt,
        kinds.CIRCUIT_BREAKER_EXTEND: _on_extend,
        kinds.CIRCUIT_BREAKER_RESUME: _on_resume,
        kinds.SESSION_STATE: _on_session_state,
        kinds.GATEWAY_AUTH: _on_gateway_auth,
        kinds.GATEWAY_CONNECT: _on_gateway_connect,
        kinds.GATEWAY_DISCONNECT: _on_gateway_gone,
        kinds.GATEWAY_BYE: _on_gateway_gone,
        kinds.STARTUP_RECOVERY: _on_startup_recovery,
        kinds.RECOVERY_ITEM: _on_recovery_item,
    }


def _price(fact: Fact, name: str) -> float | None:
    price = fact.prices.get(name)
    return price.display if price is not None else None


def _anomaly(code: str, severity: str, detail: str, fact: Fact) -> Anomaly:
    return Anomaly(
        code=code,
        severity=severity,
        detail=detail,
        receipt_ts=fact.receipt_raw,
        file=fact.file,
        line_no=fact.line_no,
    )
