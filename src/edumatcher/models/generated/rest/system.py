# GENERATED FROM spec/messages/system.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""REST body models for the ``system`` message family.

Family version 1. Derived from ``spec/messages/system.yaml`` by the rest emitter; edit
the spec, not this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CheckpointOrderSide = Literal["BUY", "SELL"]
CheckpointOrderOrderType = Literal[
    "MARKET",
    "LIMIT",
    "STOP",
    "STOP_LIMIT",
    "FOK",
    "ICEBERG",
    "IOC",
    "TRAILING_STOP",
]
CheckpointOrderTif = Literal["DAY", "GTC", "ATO", "ATC"]
QuoteLegLegSide = Literal["BUY", "SELL"]
BookCheckpointReason = Literal["STARTUP", "PHASE", "EOD"]
RecoveryItemKind = Literal["ORDER", "COMBO"]
RecoveryItemOutcome = Literal[
    "RESTORED",
    "DISCARDED_STALE_DAY",
    "FAILED",
    "QUOTE_REMNANT",
]
DiagnosticComponent = Literal[
    "MAINTENANCE_FLUSH",
    "DISPATCH_ERROR",
    "UNDECODABLE_MESSAGE",
    "UNROUTED_TOPIC",
]
QuoteLegsRequestShow = Literal["ACTIVE", "RECENT", "ALL"]
QuoteLegsShowRequested = Literal["ACTIVE", "RECENT", "ALL"]


class SymbolInfo(BaseModel):
    """One tradable instrument, as the engine sees it for a given caller. What used
    to be one entry of `symbols` and one entry of `symbol_meta`, which were always
    the same instrument written twice. The market-maker fields are resolved per
    caller, not per symbol: the engine layers the gateway's own policy, the global
    per-symbol policy and the gateway's per-symbol override before publishing. Two
    gateways asking at the same moment get different values for the same
    instrument, which is why they travel on this reply rather than in the
    reference bundle.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    tick_decimals: int = Field(ge=0, le=9)
    """The tick scale, as the integer exponent the engine actually holds. Same field,
    same name and same meaning as `book.tick_decimals` and `system.eod`'s. It
    replaces `tick_size`, which was this value passed through `10 ** -n` on the
    way out and `round(-log10(x))` on the way back in by two consumers, and read
    under a third spelling by a third.
    """
    enforce_mm_obligation: bool | None = Field(default=None)
    """Whether this caller carries a market-making obligation on this instrument.
    Absent when the caller is not a configured gateway -- regime 3 rather than
    `false`, because "no obligation configured" and "obligation explicitly
    disabled" are different answers and the console renders them differently.
    """
    mm_max_spread_ticks: int | None = Field(default=None, ge=0)
    """Widest quote that satisfies the obligation. Absent with it. Unit: ticks."""
    mm_min_qty: int | None = Field(default=None, ge=0)
    """Smallest quote that satisfies the obligation. Absent with it. Unit: shares."""
    prev_close: float | None = Field(default=None)
    """Previous session's closing reference price, from persisted book stats. Absent
    on an instrument that has never closed, which is a real state on the first day
    of a deployment. Unit: display_price.
    """


class Collar(BaseModel):
    """Price-band configuration. The two bands `CollarConfig` reads; a deployment
    writing other keys under `collar:` in its YAML had them carried onto the wire
    and read by nothing, and they no longer travel.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    static_band_pct: float = Field(ge=0)
    """Unit: percent."""
    dynamic_band_pct: float = Field(ge=0)
    """Unit: percent."""


class OrderLimits(BaseModel):
    """Pre-trade order-size and notional caps, as configured on a symbol. Each cap is
    independently optional: an absent cap is not enforced, the same way an absent
    `collar` leaves a symbol uncollared.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    max_order_qty: int | None = Field(default=None, gt=0)
    """Largest quantity a single order may carry. Absent when no cap is configured.
    Unit: shares.
    """
    max_order_value: float | None = Field(default=None, gt=0)
    """Largest notional (`quantity * price`) a single order may carry. Absent when no
    cap is configured, and never evaluated for an order that carries no price on
    the wire -- MARKET and IOC -- which the collar's price bands already skip for
    the same reason. Unit: money.
    """


class CircuitBreakerLevel(BaseModel):
    """One rung of a symbol's circuit-breaker ladder, as configured. `name` is the
    string `circuit_breaker.halt.level` and `admin.action.scope.level` carry
    onward, and is bounded here to match them.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str = Field(max_length=32)
    price_shift_pct: float = Field(gt=0)
    """Unit: percent."""
    halt_duration_ns: int | None = Field(ge=0)
    """How long a halt at this rung lasts; null for a rung that halts for the rest of
    the day. A duration, not an instant -- the distinction `epoch_nanos` could not
    make, and the reason the unit registry gained `duration_nanos` in this phase.
    See design section 28.7. Unit: duration_nanos.
    """


class SymbolCircuitBreaker(BaseModel):
    """A symbol's configured circuit-breaker ladder and its lookback."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    reference_window_ns: int = Field(ge=0)
    """Lookback window for the reference price. A duration. Unit: duration_nanos."""
    levels: list[CircuitBreakerLevel]


class CheckpointOrder(BaseModel):
    """One order as a book checkpoint holds it: enough to rebuild the book exactly --
    its place in the queue, hidden iceberg quantity, its stop and trailing
    triggers, and the links to its quote, OCO pair or combo.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)
    side: CheckpointOrderSide
    order_type: CheckpointOrderOrderType
    tif: CheckpointOrderTif
    quantity: int = Field(ge=0)
    """Unit: shares."""
    remaining_qty: int = Field(ge=0)
    """Hidden iceberg quantity included. Unit: shares."""
    price_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    stop_price_ticks: int | None = Field(default=None)
    """The current trigger (a trailing stop's ratcheted one). Unit: ticks."""
    trail_offset_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    visible_qty: int | None = Field(default=None)
    """An iceberg's slice size. Unit: shares."""
    displayed_qty: int | None = Field(default=None)
    """What an iceberg shows now. Unit: shares."""
    priority_seq: int | None = Field(default=None)
    """The book's arrival sequence; absent for a trailing stop (checked in list
    order).
    """
    smp_action: str | None = Field(default=None)
    oco_group_id: str | None = Field(default=None)
    quote_id: str | None = Field(default=None)
    combo_parent_id: str | None = Field(default=None)


class LoadedFile(BaseModel):
    """One persistence file the engine read at startup, identified by its bytes: a
    replay can tell which state the run started from.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str = Field(max_length=64)
    """File name in the data dir, e.g. gtc_orders.json."""
    sha256: str | None = Field(max_length=64)
    """SHA-256 of the file's bytes; null when the file did not exist."""
    entries: int = Field(ge=0)
    """Orders, combos or symbols the file holds (0 when absent)."""


class ReferenceSymbol(BaseModel):
    """One instrument's static configuration. Distinct from `SymbolInfo`, which is
    the same instrument as a *caller* sees it: this record is identical for every
    caller and changes only on reload, which is why the bundle can be cached and
    hashed and the symbols reply cannot.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    """Was the map key. Section 19.2."""
    tick_decimals: int = Field(ge=0, le=9)
    """As on `SymbolInfo`; `tick_size` is gone from here too."""
    level: str | None = Field(default=None, max_length=32)
    """Which risk-control level this symbol resolves to, naming an entry of
    `risk.levels`. Absent on a symbol with no level configured.
    """
    collar: Collar | None = Field(default=None)
    """Both bands or neither -- section 16.2's combination."""
    order_limits: OrderLimits | None = Field(default=None)
    """The symbol's order-size and notional caps. Configured per symbol and nowhere
    else -- there is no level or global default -- so an absent cap is one that is
    not enforced.
    """
    circuit_breaker: SymbolCircuitBreaker | None = Field(default=None)


class RiskLevel(BaseModel):
    """One named risk-control level. Was a map entry keyed by `name`; section 19.2's
    shape, with the key as a field.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str = Field(max_length=32)
    collar: Collar | None = Field(default=None)
    """The level's default bands, which a symbol may override. Absent when the level
    configures none -- previously an empty `collar` object, which said the same
    thing in more bytes.
    """


class ReferenceRisk(BaseModel):
    """The risk-control ladder as configured, and which rung is the default."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    default_level: str | None = Field(default=None, max_length=32)
    """Names an entry of `levels`. Absent when none is configured."""
    levels: list[RiskLevel]


class SessionTimes(BaseModel):
    """The trading day's clock, as five wall-clock times. Carried by
    `system.session_schedule` and, nested inside `ReferenceSchedule`, by
    `system.reference` -- one shape declared once rather than two declarations
    that can drift apart. The values are strings because that is what the config
    file holds and what every consumer renders. Individually nullable at the wire
    level for structural uniformity, though in practice all five are always
    populated together: `config_loader` rejects a `schedule:` day block that
    defines some of the five keys but not all.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    pre_open: str | None = Field(max_length=32)
    opening_auction_start: str | None = Field(max_length=32)
    continuous_start: str | None = Field(max_length=32)
    closing_auction_start: str | None = Field(max_length=32)
    closing_auction_end: str | None = Field(max_length=32)


class NextTransition(BaseModel):
    """The next session transition: what the session moves to, and when. The same
    record as `session`'s NextTransition, declared again because a type cannot be
    shared across families; the wire shape is identical.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    state: str = Field(max_length=32)
    at: str = Field(max_length=32)
    """UTC ISO-8601 instant of the transition."""


class Holiday(BaseModel):
    """One bank holiday in the exchange's holiday calendar."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    date: str = Field(max_length=10)
    """ISO-8601 calendar date, in the session timezone."""
    name: str = Field(max_length=64)
    """The holiday's name as python-holidays gives it."""


class WeeklySchedule(BaseModel):
    """A fully-resolved weekly session schedule: one `SessionTimes` per weekday
    (mon..sun, any of which may be null for CLOSED) plus a separate holidays
    entry, mirroring `edumatcher.engine.config_loader.ScheduleConfig`. The
    `weekdays`/ `weekend` shortcuts and per-day overrides in the YAML are already
    resolved by the time this is built -- every field here is one concrete day,
    never a shortcut. `today`/`today_is_holiday` are a server-computed
    convenience: the engine already runs the same `python-holidays` lookup for pm-
    scheduler, so it resolves "which entry applies right now" once and publishes
    the answer, rather than making every client (in particular a browser) carry
    its own holiday calendar just to answer that one question. `today` is still
    `SessionTimes | null` -- null means CLOSED today, exactly like any other day
    slot. `upcoming_holidays` answers the next question, "when is the exchange
    next on its holiday schedule", the same way. It is computed when the record is
    built and covers a year, so a client picks the first entry on or after its own
    today rather than trusting the list to start there.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    mon: SessionTimes | None
    tue: SessionTimes | None
    wed: SessionTimes | None
    thu: SessionTimes | None
    fri: SessionTimes | None
    sat: SessionTimes | None
    sun: SessionTimes | None
    holidays: SessionTimes | None
    """Applied instead of the weekday's own entry on a bank holiday. Null means
    CLOSED on holidays.
    """
    today: SessionTimes | None
    """The entry actually in effect today (holidays entry if today is a bank holiday,
    else today's weekday entry). Null means CLOSED today.
    """
    today_is_holiday: bool
    """True only when `today` came from the holidays entry rather than the weekday's
    own entry.
    """
    upcoming_holidays: list[Holiday] = Field(max_length=64)
    """Bank holidays for the configured country from the session date the record was
    built on, through the following 365 days, ascending. Each one runs on the
    `holidays` entry.
    """


class ReferenceSchedule(BaseModel):
    """The venue's calendar configuration: whether sessions run at all, which
    country's holidays they observe, and the resolved weekly clock. `schedule` is
    nested rather than flattened beside its two siblings, which is a change to
    `GET /reference/schedule`. The alternative was declaring `WeeklySchedule`'s
    fields a second time inline, and a shape described twice is the drift section
    1 is about.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    sessions_enabled: bool
    country: str | None = Field(default=None, max_length=2)
    """ISO 3166-1 alpha-2, for the holiday calendar. Absent when unset."""
    schedule: WeeklySchedule | None
    """Null when the deployment configures no `schedule:` block. Regime 2 rather than
    3: both readers pass the bundle through verbatim to a caller, and a key that
    is sometimes absent is harder to consume than one that is sometimes null.
    """


class IndexDefinition(BaseModel):
    """One index as configured -- its membership and its starting level, not its
    current one. `GET /history/index-daily` serves the live value; see
    `index.rebalance`.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=32)
    description: str = Field(max_length=128)
    base_value: float
    """Index points. `dimensionless` to match `index.yaml`."""
    constituents: list[str]


class EodBookLevel(BaseModel):
    """One aggregated price level of a closing book. The same three fields as
    `book.BookLevel`, redeclared because records are family-scoped and the IDL has
    no cross-family reference -- see design section 28.5 on why that stays a known
    duplication rather than becoming a shared-types construct on the strength of
    one instance. `price` is required here. `BookLevelPayload`, the hand-written
    dataclass this replaces, made it optional; the only producer is
    `OrderBook.snapshot()`, which has never emitted a level without one.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    price: float
    """Unit: display_price."""
    qty: int
    """Unit: shares."""
    count: int


class EodBook(BaseModel):
    """One symbol's closing book. A deliberately trimmed `book.book_snapshot`:
    `SystemEodPayload.from_dict` has always dropped `last_qty`, `last_buy_price`,
    `last_sell_price` and `recent_trades` from the snapshot it is handed, and this
    record says so rather than leaving it to a `from_dict` a reader has to go and
    find.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    tick_decimals: int = Field(ge=0, le=9)
    """The scale these display prices were produced at."""
    bids: list[EodBookLevel]
    """Descending by price."""
    asks: list[EodBookLevel]
    """Ascending by price."""
    last_price: float | None = Field(default=None)
    """Absent on an instrument that never traded. Unit: display_price."""


class HaltedSymbol(BaseModel):
    """One currently-halted instrument. The circuit-breaker detail is present only
    when a circuit breaker is what halted it: an ADMIN halt sets the flag without
    a breaker behind it, so the three fields travel together or not at all --
    section 16.2's combination, expressed as three regime-3 fields rather than a
    record because they are three independent CALF-side values and no reader holds
    them as a unit (section 26.2's reasoning, second application).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    resume_at_ns: int | None = Field(default=None)
    """When the halt lapses. Null on an indefinite halt. Unit: epoch_nanos."""
    level: str | None = Field(default=None, max_length=32)
    """The rung that triggered it. Bounded to match the ladder."""
    halt_source: str | None = Field(default=None, max_length=32)


class Position(BaseModel):
    """One instrument the gateway is not flat in. Only non-zero net positions are
    reported, so an empty list means flat everywhere.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    net_qty: int
    """Positive is long, negative is short. Never zero. Unit: shares."""
    avg_cost: float = Field(ge=0)
    """Volume-weighted entry price; 0.0 when unknown. Unit: display_price."""


class ActiveQuote(BaseModel):
    """One active two-sided quote, with both legs' live order state. What a market
    maker reads on reconnect to find out what it already has resting. A leg whose
    order is gone reports `MISSING` with zero quantities rather than being
    omitted: the quote still exists as far as the engine's index is concerned, and
    a bootstrap that silently dropped one side would let a bot re-quote into its
    own resting order.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_id: str = Field(max_length=64)
    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    state: str = Field(max_length=32)
    bid_order_id: str = Field(max_length=64)
    ask_order_id: str = Field(max_length=64)
    bid_price: float | None
    """Unit: display_price."""
    ask_price: float | None
    """Unit: display_price."""
    bid_qty: int = Field(ge=0)
    """Unit: shares."""
    ask_qty: int = Field(ge=0)
    """Unit: shares."""
    bid_remaining_qty: int = Field(ge=0)
    """Unit: shares."""
    ask_remaining_qty: int = Field(ge=0)
    """Unit: shares."""
    bid_status: str = Field(max_length=32)
    ask_status: str = Field(max_length=32)


class QuoteLeg(BaseModel):
    """One live leg of an active quote, with its order's current state."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_id: str = Field(max_length=64)
    order_id: str = Field(max_length=64)
    symbol: str = Field(max_length=16)
    leg_side: QuoteLegLegSide
    """Which side of the quote this leg is. Exactly two producers."""
    price: float | None = Field(default=None)
    """Leg limit price in display money. A quote leg is always a priced limit order;
    null only if the resting order's price is somehow unavailable. Unit:
    display_price.
    """
    qty: int = Field(ge=0)
    """Unit: shares."""
    remaining: int = Field(ge=0)
    """Unit: shares."""
    filled: int = Field(ge=0)
    """Unit: shares."""
    status: str = Field(max_length=32)
    quote_status: str = Field(max_length=32)


class QuoteLegSnapshot(BaseModel):
    """A leg as it stood when its quote left the book. No live qty/remaining here in
    the sense the name suggests -- these are the final values, recorded at
    removal, because once an order leaves the book its state is not available
    anywhere in the engine.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    order_id: str = Field(max_length=64)
    price: float | None = Field(default=None)
    """Leg limit price in display money, as it stood at removal. Mirrors
    `QuoteLeg.price` so an ACTIVE row and a RECENT row for the same leg read the
    same; null when the order's price was unavailable at snapshot time. Unit:
    display_price.
    """
    qty: int = Field(ge=0)
    """Unit: shares."""
    remaining: int = Field(ge=0)
    """Unit: shares."""
    filled: int = Field(ge=0)
    """Unit: shares."""
    status: str = Field(max_length=32)


class RecentQuote(BaseModel):
    """One recently-removed quote, from the engine's bounded per-gateway inactivation
    history. A quote-level summary rather than a per-leg one. Does not survive an
    engine restart.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_id: str = Field(max_length=64)
    symbol: str = Field(max_length=16)
    bid_order_id: str = Field(max_length=64)
    ask_order_id: str = Field(max_length=64)
    quote_status: str = Field(max_length=32)
    reason: str = Field(max_length=64)
    """Why it was removed. `quote_status` is derived from this."""
    removed_at_ns: int
    """Unit: epoch_nanos."""
    bid_leg: QuoteLegSnapshot | None
    """Null when the quote had no bid leg to record."""
    ask_leg: QuoteLegSnapshot | None


class LiveCircuitBreaker(BaseModel):
    """A symbol's circuit breaker as it stands right now. The live counterpart to
    `ReferenceSymbol.circuit_breaker`, which is the configuration.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    halted: bool
    reference_price: float | None
    """Unit: display_price."""
    trigger_price: float | None
    """Unit: display_price."""
    triggered_level: str | None = Field(max_length=32)
    expansion_index: int | None = Field(ge=0)
    corridor_low: float | None
    """Flat, and named without the `corridor.` box it used to sit in.
    `_corridor_payload` returns `{corridor_low, corridor_high, expansion}` and
    `risk_state` nested that under a key called `corridor`, so the wire read
    `corridor.corridor_low` -- the prefix and the box saying the same thing twice.
    The same helper is splatted *flat* into `circuit_breaker.halt`, so one
    producer was emitting two shapes of one value. Flat here matches the event.
    See design 29.2. Unit: display_price.
    """
    corridor_high: float | None
    """Unit: display_price."""
    corridor_expansion: int | None = Field(ge=0)
    """The ACE expansion count that goes with the bounds above. Distinct from
    `expansion_index`, which is always a real integer; this one is null exactly
    when the corridor is.
    """
    resume_at_ns: int | None
    """Unit: epoch_nanos."""


class SymbolRiskState(BaseModel):
    """One symbol's live risk state. Was a map entry keyed by symbol -- section
    19.2's shape for the twelfth time.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    collar_reference_price: float | None = Field(default=None)
    """Absent on a symbol with no collar configured. Unit: display_price."""
    circuit_breaker: LiveCircuitBreaker | None = Field(default=None)
    """Absent on a symbol with no circuit breaker configured."""


class GatewayInfo(BaseModel):
    """One configured participant, and whether it is connected right now."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    id: str = Field(max_length=32)
    role: str = Field(max_length=32)
    description: str = Field(max_length=128)
    connected: bool


class SymbolVolume(BaseModel):
    """One instrument's traded volume so far today. Was a map entry keyed by symbol;
    the key is a field now, as everywhere else in this family.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    qty: int = Field(ge=0)
    """Unit: shares."""
    value: float = Field(ge=0)
    """Traded notional, rounded to two decimals by the producer. Unit: money."""
    trades: int = Field(ge=0)


class GatewayConnect(BaseModel):
    """Gateway to engine: authenticate this participant. Sent over PUSH/PULL rather
    than the pub bus; it carries a topic so the audit log can classify it
    alongside everything else.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Who is connecting. The engine's PULL socket is a boundary of its own --
    section 22.3 -- so this is clamped on arrival.
    """


class GatewayAuth(BaseModel):
    """Engine to all subscribers: a participant's connection was accepted or
    rejected. The PUB-side answer to `system.gateway_connect`, and the widest-read
    message in this half -- five consumers structurally, and it is in
    `PRIVATE_PREFIXES`.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    accepted: bool
    reason: str = Field(max_length=512)
    """Why it was rejected; "" on acceptance. Regime 1, because
    `GatewayAuthPayload.to_dict` has always emitted the key.
    """
    description: str = Field(max_length=128)
    """The gateway's configured display name. Regime 1, as above."""


class GatewayDisconnect(BaseModel):
    """Gateway to engine: I am leaving cleanly. PUSH/PULL, like `gateway_connect`;
    the engine republishes it as `gateway_bye` so PUB subscribers hear about it at
    all.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    reason: str = Field(max_length=512)


class GatewayHeartbeat(BaseModel):
    """Gateway to engine: this participant's process is still alive. A process that
    dies without sending `gateway_disconnect` (kill -9, a crashed host, a dropped
    network) would otherwise keep its ID marked connected for ever, and the engine
    refuses a second connect for an ID that is already connected. The engine
    counts the beats it expects -- one per `interval_sec` -- and disconnects the
    session, applying its `disconnect_behaviour`, after three consecutive misses.
    Liveness is opt-in: a session that has never sent one is never timed out.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    interval_sec: int = Field(ge=1, le=3600)
    """Seconds between this sender's beats. Carried on every beat so the engine needs
    no per-client setting; the bound stops a client declaring an interval so long
    that its ID could never be reclaimed.
    """


class GatewayBye(BaseModel):
    """Engine to all subscribers: a participant has disconnected. The PUB-side
    counterpart to `gateway_auth`. The inbound `system.gateway_disconnect` is a
    PULL message and never reaches subscribers, so without this broadcast clearing
    could not close the matching session.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    reason: str = Field(max_length=512)


class Eod(BaseModel):
    """Engine to all subscribers, once, before shutdown: the closing book of every
    instrument. Four consumers -- clearing, index, stats and the RALF gateway --
    which is the widest fan-out in this half, and the reason the record is
    declared rather than left to a `from_dict`.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    books: list[EodBook]
    """One per instrument the engine had a book for, unordered."""


class BookCheckpoint(BaseModel):
    """One symbol's whole book, for the audit: every resting order in priority order
    with its hidden quantity, every armed stop with its current trigger, the last
    prices. Published for every symbol after startup (what the restore and the
    seeds made), after each session transition, and at shutdown. A replay can
    start from any of them -- an audit that begins mid-day, or continues after an
    engine restart -- and, where it already holds the book, compare order by
    order.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbol: str = Field(max_length=16)
    reason: BookCheckpointReason
    phase: str = Field(max_length=32)
    """The session state the book is in."""
    bids: list[CheckpointOrder]
    asks: list[CheckpointOrder]
    buy_stops: list[CheckpointOrder]
    sell_stops: list[CheckpointOrder]
    trailing_stops: list[CheckpointOrder]
    last_trade_price_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    last_buy_price_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    last_sell_price_ticks: int | None = Field(default=None)
    """Unit: ticks."""
    last_trade_id: str | None = Field(default=None)
    """The trade that set the last trade price."""


class Startup(BaseModel):
    """Engine to all subscribers, the first message of every start, before the
    restore: which engine, which configuration and which persisted state this run
    began from. Makes an audit trail self-describing -- a replay rebuilds the
    engine from this message alone, years later, without the data dir's
    `ref_data/` (which the next deploy overwrites) or a guess at the engine
    version. Also the marker of an engine start: every per-topic `seq` begins
    again after it.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    format_version: int = Field(ge=1)
    """Version of this message's meaning; 1 at EduMatcher 1.0."""
    engine_version: str = Field(max_length=64)
    """The installed edumatcher package version."""
    git_commit: str = Field(max_length=64)
    """`git describe --always --dirty` of the source the engine runs from; "unknown"
    for an installed wheel. The package version stays put between releases, the
    commit does not.
    """
    python_version: str = Field(max_length=32)
    run_seq: int = Field(ge=0)
    """The engine-run sequence this start took (trade id prefix)."""
    config_sha256: str | None = Field(max_length=64)
    """SHA-256 of the compiled config artifact; null when none is deployed."""
    config: str | None
    """The compiled config artifact, verbatim JSON text; null when the engine runs on
    a YAML config or none.
    """
    loaded: list[LoadedFile] = Field(max_length=8)
    """The persistence files the restore reads: orders, combos, book statistics."""


class StartupRecovery(BaseModel):
    """Engine to all subscribers, once, right after `_restore_gtc()` and before the
    config-seed step runs: how much of the previous session's resting state came
    back. Every one of these counts previously only reached `log.info`/`log.error`
    — invisible to `pm-audit`, which is a bare PUB subscriber and sees nothing
    that is not published (see ../../docs/books/operator-guide/part-6-observe-and-
    recover/020-audit-trail.md). A post-mortem investigating "why does the book
    look different after a restart" needs this the same way it needs
    `order.cancelled` for a live cancel.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    restored_orders: int = Field(ge=0)
    """GTC/same-day-DAY orders successfully restored to their book."""
    discarded_stale_day_orders: int = Field(ge=0)
    """TIF=DAY orders discarded because the business day rolled over."""
    failed_orders: int = Field(ge=0)
    """Persisted orders that raised during restore and were skipped."""
    quote_remnants_restored: int = Field(ge=0)
    """Restored quote-origin legs whose sibling did not survive, so they rest as
    plain orders rather than being rejoined into QuoteIndex.
    """
    rebuilt_quotes: int = Field(ge=0)
    """Active QuoteIndex entries rebuilt from both-legs-restored quotes."""
    restored_combos: int = Field(ge=0)
    """GTC combos restored from the previous session."""


class RecoveryItem(BaseModel):
    """Engine to all subscribers: one restored, discarded or failed entity from
    `_restore_gtc()` (AR-0.5). `startup_recovery`'s six counts say *how many*;
    this says *which ones* — "which order failed to restore?" was unanswerable
    from either the counts alone or the process log, since a post-mortem
    investigating a startup only sees what was published (see
    ../../docs/books/operator-guide/part-6-observe-and-recover/020-audit-
    trail.md). Published once per entity, before the single summary
    `startup_recovery` broadcast, so the counts there are the cross-check:
    `restored_orders + discarded_stale_day_orders + failed_orders` must equal the
    number of ORDER-kind recovery_item lines whose outcome is RESTORED,
    DISCARDED_STALE_DAY or FAILED respectively, and `restored_combos` must equal
    the number of COMBO-kind lines.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    entity_id: str = Field(max_length=64)
    """The order id (ORDER) or combo id (COMBO) this line is about."""
    kind: RecoveryItemKind
    """What restore_gtc() was processing."""
    outcome: RecoveryItemOutcome
    """RESTORED/DISCARDED_STALE_DAY/FAILED come from the main GTC-order (or GTC-
    combo) restore pass and are mutually exclusive per entity. QUOTE_REMNANT is a
    second, additional line for a RESTORED quote-origin order whose sibling leg
    did not come back — see the example_note above. COMBO-kind lines are always
    RESTORED today: `load_gtc_combos()` has no per-combo guard, so there is no
    combo failure path to report yet.
    """
    symbol: str | None = Field(default=None, max_length=16)
    """The instrument, for an ORDER-kind line. Null for COMBO, which may span more
    than one symbol across its legs and has none of its own.
    """
    detail: str | None = Field(default=None, max_length=512)
    """Free text, when there is something worth saying beyond kind and outcome — the
    exception message for a FAILED order, in particular.
    """


class Diagnostic(BaseModel):
    """Engine to all subscribers: an internal failure or anomaly that the engine
    absorbed and kept running past, so trading was not interrupted but the event
    still happened and a post-mortem needs to see it. Before this existed, a
    maintenance-flush exception, a handler crash, an undecodable inbound message,
    or a message on an unhandled topic reached only the process log — `pm-audit`'s
    bare PUB subscription on the engine's :5556 socket (see
    ../../docs/books/operator-guide/part-6-observe-and-recover/020-audit-trail.md)
    never saw any of them, so a bug that only ever showed up as "the book snapshot
    stopped updating" or "an order silently never got a reply" had no trail to
    replay. This does not replace logging (the process log keeps the full
    traceback); it is the wire-visible marker that something in `component`
    happened, with enough detail to go find the log line.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    component: DiagnosticComponent
    """Which internal area this diagnostic came from."""
    detail: str = Field(max_length=256)
    """What within component — the flush function name, the message topic, or empty
    when there is no finer-grained name (an undecodable message has no topic to
    report).
    """
    error: str = Field(max_length=512)
    """The exception text, when this diagnostic came from one."""
    count: int = Field(ge=0)
    """This component's running occurrence count for the process lifetime — the same
    counter the log line already reports, carried onto the wire so a subscriber
    can tell a first occurrence from a recurring one without correlating
    timestamps against the log.
    """


class SymbolsRequest(BaseModel):
    """Caller to engine: which instruments are tradable, and on what terms for me."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Both the correlation key for the reply topic and the identity the market-maker
    fields are resolved against.
    """


class Symbols(BaseModel):
    """Engine to caller: the tradable instruments, with the tick scale and this
    caller's market-making terms for each.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbols: list[SymbolInfo]
    """Sorted by symbol, as the engine iterates its books."""


class ReferenceRequest(BaseModel):
    """Any caller to engine: the compiled reference-data bundle. Static configuration
    only -- nothing that changes during a session.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Correlation key only. The API gateway passes an API key here for read-only
    callers, since the bundle does not vary by caller and this only has to be
    unique.
    """


class Reference(BaseModel):
    """Engine to caller: every piece of static venue configuration in one round trip
    -- tick scales, risk levels, circuit-breaker ladders, index definitions and
    the calendar -- with a hash that changes when any of it does.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbols: list[ReferenceSymbol]
    """Sorted by symbol. Was a map keyed by it."""
    risk: ReferenceRisk
    indexes: list[IndexDefinition]
    """Already a list of records before this phase."""
    schedule: ReferenceSchedule
    config_version: str | None = Field(max_length=64)
    """Truncated SHA-256 of the bundle. Null before a config is loaded, which is the
    only remaining difference between the two states the old two-shape reply used
    to distinguish. Regime 2: every consumer compares it, so the key has to be
    there to compare.
    """


class ReferenceReload(BaseModel):
    """ADMIN to engine: re-read static reference data from disk. Deliberately
    narrower than a startup load -- it never re-seeds quotes, creates or removes
    books, or touches session and halt state, so a reload that changed the symbol
    set is rejected rather than partially applied.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    command_id: str = Field(max_length=64)
    """Correlated by the ack. Read off the wire unclamped before this phase, and
    quoted straight into a bounded ack field -- section 22.3's silent non-answer,
    four reply paths.
    """


class ReferenceReloadAck(BaseModel):
    """Engine to ADMIN: the reload verdict, and the new configuration hash when it
    took.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    command_id: str = Field(max_length=64)
    accepted: bool
    config_version: str | None = Field(default=None, max_length=64)
    """Present on acceptance."""
    reason: str | None = Field(default=None, max_length=512)
    """Present on rejection."""


class SessionStateRequest(BaseModel):
    """Caller to engine: what session are we in, without advancing it. The scheduler
    is the dominant producer -- it asks rather than assuming, because it is not
    the only thing that can move the session.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class SessionStatus(BaseModel):
    """Engine to caller: the current session state, on request. The polled answer to
    the `session.state` broadcast, for a caller that has just started and missed
    the last transition.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    state: str = Field(max_length=32)
    """Same values as `session.state.state`."""
    sessions_enabled: bool
    """False when the deployment runs continuously with no session schedule at all,
    which makes `state` advisory.
    """
    next: NextTransition | None = Field(default=None)
    """The countdown target the engine holds, as `session.state.next` last carried it
    or `session.next` announced it. Lets a caller that missed the last transition
    still count down to the next one.
    """


class SessionScheduleRequest(BaseModel):
    """Operator to engine: the configured session schedule."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class SessionSchedule(BaseModel):
    """Engine to operator: the trading day's clock as configured. The same
    `SessionTimes` record `system.reference` carries, which is what forced these
    two topics into one phase.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    sessions_enabled: bool
    schedule: WeeklySchedule | None
    """Null when no `schedule:` block is configured."""


class HaltStatusRequest(BaseModel):
    """Any process to engine: which instruments are halted now."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class HaltStatus(BaseModel):
    """Engine to caller: every currently-halted instrument, with the breaker state
    behind it where a breaker is what halted it. The polled answer to the
    `circuit_breaker.halt` broadcast, for a caller that has just started and
    missed it.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    halted: list[HaltedSymbol]


class PositionRequest(BaseModel):
    """Gateway to engine: what am I holding."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    """Both the correlation key and the account being asked about. A gateway can only
    ask about itself: the handler answers from `_gateway_positions[gateway_id]`
    and nothing else.
    """


class PositionSnapshot(BaseModel):
    """Engine to gateway: per-symbol net position and average cost, for the asking
    gateway only.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    positions: list[Position]


class QuoteBootstrapRequest(BaseModel):
    """Market maker to engine, on reconnect: what quotes do I already have resting.
    Without it a bot cannot tell a fresh start from a reconnect and will quote
    into its own orders.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    """Narrows the reply to one instrument. "" means all."""


class QuoteBootstrap(BaseModel):
    """Engine to market maker: the active quotes it already holds."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    quotes: list[ActiveQuote]


class QuoteLegsRequest(BaseModel):
    """Operator or market maker to engine: the per-leg detail behind this gateway's
    quotes, live and recently removed. What `QLEGS` asks for.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)
    symbol: str = Field(max_length=16)
    """Narrows the reply to one instrument. "" means all."""
    show: QuoteLegsRequestShow
    """Which half to return. `ACTIVE` is live legs, `RECENT` is the removal history,
    `ALL` is both. Enumerated rather than a free string because the handler
    branches on exactly these three and treats anything else as `ACTIVE` -- a typo
    currently answers, quietly, with the wrong half.
    """


class QuoteLegs(BaseModel):
    """Engine to caller: live quote legs, recently-removed quotes, or both."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    legs: list[QuoteLeg]
    """Live legs. Empty unless `show` was `ACTIVE` or `ALL`."""
    show_requested: QuoteLegsShowRequested
    """Echo of the request's `show`, so replies can be told apart."""
    complete: bool
    """False when the reply could not fully answer what was asked. Always true today;
    kept because the recent-history buffer is bounded and a truncated answer needs
    a way to say so.
    """
    recent: list[RecentQuote]
    """Removal history. Empty unless `show` was `RECENT` or `ALL`."""


class RiskStateRequest(BaseModel):
    """ADMIN to engine: the live collar and circuit-breaker state of every symbol
    that has either configured, halted or not.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class RiskState(BaseModel):
    """Engine to ADMIN: live risk state per symbol. The counterpart to
    `reference.risk`, which is the static definitions, and to `halt_status`, which
    is only the symbols currently halted.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbols: list[SymbolRiskState]
    """Sorted by symbol. Was a map keyed by it."""


class GatewaysRequest(BaseModel):
    """Operator to engine: which participants exist, and who is on."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class Gateways(BaseModel):
    """Engine to operator: every configured participant with its role and current
    connection status. The polled counterpart to the `gateway_auth` /
    `gateway_bye` broadcasts.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateways: list[GatewayInfo]
    """Sorted by id. Empty when no config is loaded."""


class VolumeRequest(BaseModel):
    """Operator to engine: how much has traded today."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    gateway_id: str = Field(max_length=32)


class Volume(BaseModel):
    """Engine to operator: traded quantity, notional and trade count, per instrument
    and exchange-wide.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    symbols: list[SymbolVolume]
    """Sorted by symbol. Was a map keyed by it."""
    total_qty: int = Field(ge=0)
    """Unit: shares."""
    total_value: float = Field(ge=0)
    """Unit: money."""
    total_trades: int = Field(ge=0)
