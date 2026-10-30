"""Response models: the v1 contract of every REST reply.

Engine replies the gateway forwards are modelled by the msgen-generated body
models (``models/generated/rest``), so a reply and the bus payload it came from
are declared once, in ``spec/messages``. This module adds what only the gateway
knows: its own replies, the history rows it reads from pm-stats, and the
composites (bootstrap) it assembles.

Conventions (REST API review, D6):

* a collection reply is ``{"<plural>": [...], "count": n}``; a paginated one
  adds ``has_more`` and ``next_cursor`` (``null`` on the last page);
* no envelope nests inside another;
* a ``status`` field is a declared ``Literal``.

Every router serialises with ``exclude_unset`` (``routing.ContractRoute``), so a
field the engine omits stays omitted instead of becoming ``null``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from edumatcher.compdb import store as compdb
from edumatcher.models.generated.rest import index as rest_index
from edumatcher.models.generated.rest import news as rest_news
from edumatcher.models.generated.rest import order as rest_order
from edumatcher.models.generated.rest import sim as rest_sim
from edumatcher.models.generated.rest import system as rest_system


class _Counted(BaseModel):
    count: int = Field(ge=0, description="Number of items in the list.")


class _Page(_Counted):
    has_more: bool = Field(description="Whether another page follows.")
    next_cursor: str | None = Field(
        description="Pass back as `after` for the next page; null on the last page."
    )


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class AmendAccepted(BaseModel):
    order_id: str
    request_tag: str | None = Field(description="Echo of the request's `request_tag`.")
    status: Literal["PENDING_AMEND", "ACKED", "REJECTED"]
    accepted: bool | None = Field(
        description="Engine verdict; null until acknowledged."
    )
    reject_code: str | None = Field(
        description="Why the amend was refused, when it was."
    )
    event: dict[str, Any] | None = Field(
        description="The engine's `order.amended` (or reject) event, once received."
    )


class OrderList(rest_order.Orders, _Counted):
    """The caller's orders as the engine holds them."""


class CachedOrder(BaseModel):
    """The gateway's view of one order: as submitted, overlaid with every engine
    event since (ack, fills, amend, cancel), so further event fields may appear."""

    model_config = ConfigDict(extra="allow")

    order_id: str
    status: str | None = Field(
        default=None,
        description="Latest state, e.g. PENDING, NEW, PARTIAL, FILLED; absent until "
        "the gateway has seen one.",
    )
    client_tag: str | None = Field(description="Your label from submission, or null.")


class AdminCachedOrder(CachedOrder):
    gateway_id: str = Field(description="The gateway that owns the order.")


class OcoCancelPending(BaseModel):
    oco_id: str
    status: Literal["PENDING_CANCEL"]


class ComboCancelPending(BaseModel):
    combo_id: str
    status: Literal["PENDING_CANCEL"]


class QuoteCancelPending(BaseModel):
    symbol: str
    status: Literal["PENDING_CANCEL"]


# ---------------------------------------------------------------------------
# Reference and account
# ---------------------------------------------------------------------------


class ConfigVersion(BaseModel):
    config_version: str = Field(description="Content hash of the reference bundle.")


class ReferenceSymbols(_Counted):
    symbols: list[rest_system.ReferenceSymbol]
    config_version: str


class ReferenceRiskView(rest_system.ReferenceRisk):
    config_version: str


class ReferenceIndexes(_Counted):
    indexes: list[rest_system.IndexDefinition]
    config_version: str


class ReferenceScheduleView(rest_system.ReferenceSchedule):
    config_version: str


class SymbolList(rest_system.Symbols, _Counted):
    """The symbols the caller can trade, resolved for its gateway."""


class News(_Counted):
    news: list[rest_news.NewsEvent] = Field(description="Headlines, oldest first.")
    sectors: dict[str, list[str]] = Field(description="Symbols each sector holds.")


_COMPANY_TYPES = {"TEXT": str, "INTEGER": int, "REAL": float}


def _company_field(column: compdb.Column) -> Any:
    kind = _COMPANY_TYPES[column.kind]
    annotation = kind if column.name in compdb.REQUIRED else kind | None
    return (annotation, Field(description=column.description))


#: Built from compdb's own column list, so the profile and the database cannot
#: disagree about which fields exist.
Company: type[BaseModel] = create_model(
    "Company",
    __doc__="The fictional company behind a symbol, stored and derived columns.",
    **{
        c.name: _company_field(c)
        for c in (*compdb.FIELDS, *(column for column, _ in compdb.DERIVED))
    },
)


class Session(rest_system.SessionStatus):
    session_timezone: str = Field(
        description="IANA zone of every wall-clock time and history `date` filter."
    )
    session_date: str = Field(description="Today's trading date in it, YYYY-MM-DD.")


class HaltList(rest_system.HaltStatus, _Counted):
    """Currently halted symbols."""


class QuoteList(rest_system.QuoteBootstrap, _Counted):
    """The caller's active market-maker quotes."""


class QuoteLegList(rest_system.QuoteLegs, _Counted):
    """Every leg of the caller's quotes."""


class PositionRow(BaseModel):
    symbol: str
    net_qty: int = Field(description="Signed: negative is short.")
    avg_cost: float = Field(description="Volume-weighted entry price.")
    last_price: float | None = Field(description="Last trade print; null before one.")
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl_session: float | None = Field(
        description="From the clearing ledger; null when clearing is not deployed."
    )
    realized_pnl_mtd: float | None
    realized_pnl_ytd: float | None


class Positions(_Counted):
    positions: list[PositionRow] = Field(description="Sorted by symbol.")


class Status(BaseModel):
    """Who the caller is."""

    gateway_id: str
    gateway_role: str = Field(description="TRADER, MARKET_MAKER or ADMIN.")
    gateway_count: int | None = Field(
        default=None, description="ADMIN only: connected gateways."
    )


# ---------------------------------------------------------------------------
# History (pm-stats rows)
# ---------------------------------------------------------------------------


class OrderEventRow(BaseModel):
    seq: int
    ts: str = Field(description="ISO-8601 UTC.")
    event_type: str
    order_id: str
    gateway_id: str
    symbol: str
    side: str | None
    order_type: str | None
    tif: str | None
    price: float | None
    quantity: int | None
    remaining_qty: int | None
    status: str | None
    fill_price: float | None
    fill_qty: int | None
    trade_ids: str | None
    reason: str | None
    reject_code: str | None
    client_tag: str | None
    combo_parent_id: str | None
    oco_group_id: str | None
    priority_reset: int | None
    msg_id: str | None


class OrderEventPage(_Page):
    events: list[OrderEventRow]
    retained_from: str | None = Field(
        description="Where pm-stats prunes this gateway's events; null if never."
    )


class OrderTimeline(_Counted):
    events: list[OrderEventRow]
    retained_from: str | None


class TradeRow(BaseModel):
    ts: str
    trade_id: str
    symbol: str
    price: float
    quantity: int
    tick_decimals: int
    buy_gateway_id: str | None
    sell_gateway_id: str | None
    aggressor_side: str | None


class TradePage(_Page):
    trades: list[TradeRow]


class DailyRow(BaseModel):
    date: str
    symbol: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    open_bid: float | None
    open_ask: float | None
    close_bid: float | None
    close_ask: float | None
    volume: int | None
    trade_count: int | None
    turnover: float | None
    vwap: float | None
    largest_trade_qty: int | None
    largest_trade_price: float | None
    tick_decimals: int | None


class DailyPage(_Page):
    daily: list[DailyRow]


class PriceSnapshotRow(BaseModel):
    ts: str
    symbol: str
    mid_price: float | None
    best_bid: float | None
    best_ask: float | None
    pct_change: float | None
    tick_decimals: int | None


class PriceSnapshotPage(_Page):
    snapshots: list[PriceSnapshotRow]


class IndexDailyRow(BaseModel):
    date: str
    index_id: str
    open_level: float | None
    high_level: float | None
    low_level: float | None
    close_level: float | None
    close_session_state: str | None
    open_aggregate_cap: float | None
    close_aggregate_cap: float | None
    update_count: int | None


class IndexDailyPage(_Page):
    daily: list[IndexDailyRow]


class IndexSnapshotRow(BaseModel):
    ts: str
    index_id: str
    level: float | None
    aggregate_cap: float | None
    divisor: float | None
    session_state: str | None
    day_open: float | None
    day_high: float | None
    day_low: float | None


class IndexSnapshotPage(_Page):
    snapshots: list[IndexSnapshotRow]


class IndexIds(_Counted):
    index_ids: list[str]


class IndexEvents(_Counted):
    events: list[rest_index.HistoryRecord] = Field(
        description="pm-index's structural records, oldest first."
    )
    warnings: list[str] = Field(description="Anything pm-index reported; often empty.")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class TransitionApplied(BaseModel):
    requested_state: str
    status: Literal["APPLIED"]
    command_id: str


class ReloadApplied(BaseModel):
    status: Literal["RELOADED"]
    config_version: str | None


class SimSnapshot(BaseModel):
    available: bool = Field(description="False when pm-market-sim is not running.")
    state: rest_sim.SimState | None
    values: rest_sim.SimValue | None


class GatewayList(rest_system.Gateways, _Counted):
    """Every gateway the engine knows, with role and connection state."""


class DisconnectPending(BaseModel):
    gateway_id: str
    status: Literal["PENDING_DISCONNECT"]


class RiskStateView(rest_system.RiskState, _Counted):
    """Live collar and circuit-breaker state per symbol."""


class AdminOrders(_Counted):
    orders: list[AdminCachedOrder]
    retention_sec: int = Field(description="How long terminal orders stay listed.")


class AuditEvent(BaseModel):
    timestamp: str
    topic: str
    gateway_id: str | None
    symbol: str | None
    order_id: str | None
    payload: str = Field(description="The original engine message, as JSON text.")


class OrderAudit(_Counted):
    order_id: str
    events: list[AuditEvent] = Field(description="Oldest first.")


class GatewayPositions(_Counted):
    gateway_id: str
    positions: list[rest_system.Position]


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


class Capabilities(BaseModel):
    sessions_enabled: bool
    stats_db_available: bool
    audit_db_available: bool
    index_available: bool


class _Bootstrap(BaseModel):
    ts: str
    incomplete: list[str] = Field(
        description="Optional fields that came back null because their query failed."
    )
    session_timezone: str
    reference: rest_system.Reference
    session: Session | None
    halts: list[rest_system.HaltedSymbol] | None
    capabilities: Capabilities


class BootstrapTrader(_Bootstrap):
    gateway_id: str | None
    gateway_role: str = Field(description="TRADER, MARKET_MAKER, ADMIN or READ_ONLY.")
    positions: list[PositionRow]
    orders: list[rest_order.OrderDisplay]
    recent_fills: list[OrderEventRow] | None


class BootstrapMM(BootstrapTrader):
    quotes: list[rest_system.ActiveQuote] | None
    quote_legs: list[rest_system.QuoteLeg] | None


class BootstrapAdmin(_Bootstrap):
    gateway_id: str
    gateway_role: Literal["ADMIN"]
    gateways: list[rest_system.GatewayInfo] | None
    active_order_counts: dict[str, int]
    monitor_last_seq: dict[str, int]
