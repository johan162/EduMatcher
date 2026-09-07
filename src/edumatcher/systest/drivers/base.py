"""The ``Driver`` protocol and normalised wire dataclasses.

Defines the transport-agnostic verb set (``connect``, ``disconnect``,
``new_order``, ``cancel_order``, ``amend_order``, ``orders``, ``positions``,
``session``, ``events``, plus the Phase 2+-reserved ``quote`` and
``kill_switch`` verbs) and the normalised dataclasses each verb returns
(``NewOrderRequest``, ``OrderAmendment``, ``Ack``, ``OrderView``,
``PositionView``, ``SessionView``, ``Event``).

See design.md Components §4 (Driver Protocol) and Data Models §2 (Wire
Dataclasses).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class NewOrderRequest:
    """A new-order request, in the Driver's transport-agnostic shape.

    See design.md Data Models §2.
    """

    symbol: str
    side: Literal["BUY", "SELL"]
    order_type: Literal[
        "MARKET",
        "LIMIT",
        "STOP",
        "STOP_LIMIT",
        "FOK",
        "ICEBERG",
        "IOC",
        "TRAILING_STOP",
    ]
    quantity: int
    tif: Literal["DAY", "GTC", "ATO", "ATC"] = "DAY"
    price: float | None = None
    stop_price: float | None = None
    visible_qty: float | None = None
    smp_action: (
        Literal["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"] | None
    ) = None
    client_tag: str | None = None  # minted by the Runner, per Actor+label


@dataclass(frozen=True, slots=True)
class OrderAmendment:
    """A price/quantity amendment request, in the Driver's transport-agnostic
    shape. See design.md Data Models §2.
    """

    price: float | None = None
    quantity: int | None = None
    request_tag: str | None = None


@dataclass(frozen=True, slots=True)
class Ack:
    """The outcome of a new-order, cancel, or amend request. See design.md
    Data Models §2.
    """

    order_id: str | None
    accepted: bool
    reason: str
    reject_code: str | None  # RejectCode literal, or None on accept
    client_tag: str | None
    request_tag: str | None
    symbol: str | None = None
    side: str | None = None
    order_type: str | None = None
    tif: str | None = None
    qty: int | None = None
    price: float | None = None


@dataclass(frozen=True, slots=True)
class OrderView:
    """A normalised view of one order, as returned by the Driver's
    ``orders`` verb. See design.md Data Models §2.
    """

    id: str
    symbol: str
    side: str
    order_type: str
    tif: str
    quantity: int
    remaining_qty: int
    status: str  # NEW, PARTIAL, FILLED, CANCELLED, REJECTED, EXPIRED
    price: float | None
    stop_price: float | None
    visible_qty: int | None
    displayed_qty: int | None
    smp_action: str | None
    oco_group_id: str | None
    combo_parent_id: str | None
    leg_index: int | None
    origin: str
    quote_id: str | None
    client_tag: str | None
    arrival_seq: int
    timestamp: float  # epoch seconds, display units


@dataclass(frozen=True, slots=True)
class PositionView:
    """A normalised view of one symbol's net position. See design.md Data
    Models §2.
    """

    symbol: str
    net_qty: int  # signed; positive long, negative short
    avg_cost: float


@dataclass(frozen=True, slots=True)
class SessionView:
    """A normalised view of the engine's current session state. See
    design.md Data Models §2.
    """

    state: Literal[
        "PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED"
    ]
    sessions_enabled: bool
    prev_state: str | None = None
    next_state: str | None = None  # from NextTransition.state, when present
    next_at: str | None = None  # from NextTransition.at, when present


@dataclass(frozen=True, slots=True)
class Event:
    """One unsolicited lifecycle event: ack, fill, cancelled, amended,
    expired. See design.md Data Models §2.
    """

    kind: Literal["ack", "fill", "cancelled", "amended", "expired"]
    order_id: str | None
    gateway_id: str | None
    client_tag: str | None
    request_tag: str | None
    sequence: int | None  # WS/CALF/RALF/DC sequence number, when applicable
    # fill-specific (None on other kinds)
    fill_qty: int | None = None
    fill_price: float | None = None
    remaining_qty: int | None = None
    trade_ids: list[str] = field(default_factory=list)
    liquidity_flag: Literal["MAKER", "TAKER"] | None = None
    # cancel-specific
    cancel_reason: Literal["SELF_MATCH_PREVENTED", "INSUFFICIENT_LIQUIDITY"] | None = (
        None
    )
    # ack-specific
    accepted: bool | None = None
    reject_code: str | None = None
    reason: str | None = None
    # amend-specific
    priority_reset: bool | None = None
    price: float | None = None
    qty: int | None = None


class Driver(Protocol):
    """The transport-agnostic verb set every concrete Driver implements.

    See design.md Components §4 (Driver Protocol) and Requirement 4. A
    Scenario is written once against this Protocol and bound to whichever
    transport (ALF, REST, Admin — see design.md Components §5/§6/§7) the
    Binding under test selects, with no scenario-level branch logic.

    This is a :class:`typing.Protocol`, so it only declares structural
    shape; concrete drivers (``systest/drivers/alf.py``,
    ``systest/drivers/rest.py``, ``systest/drivers/admin.py``, per tasks
    15-17) supply the actual bodies. Not ``@runtime_checkable`` — Drivers
    are constructed explicitly by the Runner per Binding (design.md
    Components §3), never discovered via ``isinstance`` checks, so runtime
    structural checks add no value here.

    Every verb but ``connect``/``disconnect`` returns one of the normalised
    dataclasses defined above (Requirement 4.2); a wire field absent on a
    given response becomes ``None`` on the dataclass rather than a
    substituted default (Requirement 4.3) — already guaranteed by
    construction of those dataclasses, per task 4.1.
    """

    def connect(self) -> None:
        """Establish the transport connection. Returns ``None`` on success;
        raises on failure (see the transport-specific Driver's own
        connection-error type, e.g. ``DriverConnectionError``).
        """
        ...

    def disconnect(self) -> None:
        """Tear down the transport connection. Returns ``None`` on success."""
        ...

    def new_order(self, order: NewOrderRequest) -> Ack:
        """Submit a new order and return its normalised acknowledgement."""
        ...

    def cancel_order(self, order_id: str, *, request_tag: str | None = None) -> Ack:
        """Cancel an existing order by id.

        ``request_tag`` is keyword-only and optional: it carries
        request-identity correlation (as distinct from the order-identity
        ``client_tag`` minted on ``new_order``'s ``NewOrderRequest``), per
        Requirement 5.8/6.x and design.md §A.1.7. Cancel has no request
        payload dataclass of its own, so ``request_tag`` is a direct
        parameter here rather than a field on a dataclass argument — do not
        change this to accept an ``OrderAmendment``-like object.
        """
        ...

    def amend_order(self, order_id: str, amendment: OrderAmendment) -> Ack:
        """Amend an existing order's price/quantity.

        Request-identity correlation for an amend is carried on
        ``amendment.request_tag`` (see :class:`OrderAmendment`), not as a
        separate parameter — unlike ``cancel_order``, amend already has a
        request payload dataclass to carry it on.
        """
        ...

    def orders(self) -> list[OrderView]:
        """Return every known order as a normalised :class:`OrderView`.

        MUST return ``[]`` (never ``None``, and never raise) when no orders
        match, per Requirement 4.5. Every concrete Driver implementation
        (Phase 1's ALF/REST drivers, task 15/16) must honor this contract;
        the Protocol declaration itself cannot enforce it at runtime.
        """
        ...

    def positions(self) -> list[PositionView]:
        """Return every known position as a normalised :class:`PositionView`.

        MUST return ``[]`` (never ``None``, and never raise) when no
        positions match, per Requirement 4.5 — see the ``orders()`` docstring
        above for the same contract.
        """
        ...

    def session(self) -> SessionView:
        """Return the engine's current session state as a normalised
        :class:`SessionView`.
        """
        ...

    def events(self) -> list[Event]:
        """Drain and return unsolicited lifecycle events as normalised
        :class:`Event` instances, preserving arrival order.

        MUST return ``[]`` (never ``None``, and never raise) when no events
        are pending, per Requirement 4.5 — see the ``orders()`` docstring
        above for the same contract.
        """
        ...

    # Phase 2+, reserved per Requirement 4.4 — every Phase 1/2 Driver
    # implementation MUST raise NotImplementedError from these two verbs
    # (Requirement 4.6) rather than returning a normalised dataclass or
    # silently succeeding. The Protocol declaration itself cannot enforce
    # this at runtime; it is a contract each concrete Driver must honor.
    def quote(self, req: object) -> Ack:
        """Reserved for a future market-maker quote verb (Phase 2+).

        MUST raise :class:`NotImplementedError` in every Phase 1/2 Driver
        implementation, per Requirement 4.6.
        """
        ...

    def kill_switch(self, symbol: str | None) -> Ack:
        """Reserved for a future kill-switch verb (Phase 2+).

        MUST raise :class:`NotImplementedError` in every Phase 1/2 Driver
        implementation, per Requirement 4.6. (The Admin Driver's actual
        kill-switch operation, design.md Components §7, is a distinct
        `/admin/*` REST call — not this reserved verb.)
        """
        ...
