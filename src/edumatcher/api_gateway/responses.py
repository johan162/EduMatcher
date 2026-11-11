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
from edumatcher.models.generated.rest import book as rest_book
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
    ack_timeout: bool = Field(
        description="True when `?wait=ack` gave up waiting: the amend was sent and "
        "the outcome follows on the private WebSocket."
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
# Market data (REST snapshots of the book.{symbol} stream)
# ---------------------------------------------------------------------------


class BookLevelView(rest_book.BookLevel):
    """One aggregated price level, with the price in ticks beside the display price."""

    price_ticks: int = Field(
        description="`price` in integer ticks: `price * 10**tick_decimals`."
    )


class TapeRow(rest_book.RecentTrade):
    """One print of the book's trade tape, with the price in ticks."""

    price_ticks: int = Field(
        description="`price` in integer ticks: `price * 10**tick_decimals`."
    )


class _BookStamp(BaseModel):
    symbol: str
    tick_decimals: int = Field(
        description="Price scale: 2 means prices move in 0.01 steps. Same value as "
        "`/reference/symbols`."
    )
    ts_ns: int = Field(
        description="When the engine produced this snapshot (epoch nanoseconds). "
        "The engine publishes a book when it changes, so a quiet book keeps an "
        "old stamp."
    )
    seq: int = Field(
        description="Market-data sequence of this snapshot on topic `book.{symbol}`: "
        "the `seq` the WebSocket `book` frame for the same snapshot carries. "
        "Ignore frames with `seq` at or below it."
    )


class BookView(_BookStamp):
    """The latest book snapshot for one symbol."""

    bids: list[BookLevelView] = Field(
        description="Best (highest) price first, at most `levels` entries."
    )
    asks: list[BookLevelView] = Field(
        description="Best (lowest) price first, at most `levels` entries."
    )
    last_price: float | None = Field(
        description="Last trade price; null until the symbol has traded."
    )
    last_price_ticks: int | None
    last_qty: int | None
    last_buy_price: float | None
    last_buy_price_ticks: int | None
    last_sell_price: float | None
    last_sell_price_ticks: int | None
    recent_trades: list[TapeRow] = Field(
        description="The last five prints, oldest first."
    )


class BookSummary(_BookStamp):
    """Best bid, best ask and last price of one symbol."""

    best_bid: BookLevelView | None = Field(description="Null on an empty bid side.")
    best_ask: BookLevelView | None = Field(description="Null on an empty ask side.")
    last_price: float | None = Field(
        description="Last trade price; null until the symbol has traded."
    )
    last_price_ticks: int | None


class BookSummaries(_Counted):
    books: list[BookSummary] = Field(description="Sorted by symbol.")


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


class PriceLevelView(rest_order.PriceLevelOrders, _Counted):
    """Every resting order on a symbol, optionally one price level, by arrival."""


class VolumeView(rest_system.Volume, _Counted):
    """Today's traded volume per symbol (`count` symbols) and venue totals."""


# ---------------------------------------------------------------------------
# Clearing (pm-clearing's clearing.db, pm-eod's eod.db)
#
# A money column of a clearing row comes twice: `<name>_ticks` as stored, in
# ticks of the row's `tick_decimals`, and `<name>` in display currency
# (`<name>_ticks / 10**tick_decimals`). Ticks of different symbols are
# different amounts of money, so only the display values may be added up
# across rows. Settlement amounts are a third unit: integer minor units of
# the display currency (2 decimals), named `*_minor`.
# ---------------------------------------------------------------------------


def _ticks(column: str) -> Any:
    return Field(description=f"`{column}` as stored, in ticks of `tick_decimals`.")


def _display(text: str) -> Any:
    return Field(description=f"{text}, in display currency.")


_TICK_DECIMALS = Field(
    description="Price scale of this row: its ticks are 10**-tick_decimals of the "
    "display currency."
)


class _Bounded(_Counted):
    has_more: bool = Field(
        description="More rows match than `limit` returned; narrow the filters "
        "(the date range, say) to see them."
    )


class ClearingPositionRow(BaseModel):
    gateway_id: str
    symbol: str
    net_qty: int = Field(description="Signed shares: negative is short.")
    tick_decimals: int = _TICK_DECIMALS
    avg_cost: float = _display("Volume-weighted entry price")
    avg_cost_ticks: float = _ticks("avg_cost")
    mark_price: float | None = _display(
        "Mark: the last trade price, or the end-of-day mark; null before one"
    )
    mark_price_ticks: int | None = _ticks("mark_price")
    realized_pnl: float = _display("Cumulative realized P&L")
    realized_pnl_ticks: float = _ticks("realized_pnl")
    unrealized_pnl: float = _display("Open P&L at the mark")
    unrealized_pnl_ticks: float = _ticks("unrealized_pnl")
    buy_qty: int = Field(description="Shares bought, cumulative.")
    sell_qty: int = Field(description="Shares sold, cumulative.")
    buy_notional: float = _display("Bought value, cumulative")
    buy_notional_ticks: int = _ticks("buy_notional")
    sell_notional: float = _display("Sold value, cumulative")
    sell_notional_ticks: int = _ticks("sell_notional")
    last_trade_ts_ns: int | None = Field(
        description="Exchange time of the last trade (epoch nanoseconds)."
    )
    updated_ts_ns: int = Field(
        description="When clearing last wrote the row (epoch nanoseconds)."
    )


class ClearingPositions(_Bounded):
    positions: list[ClearingPositionRow] = Field(description="By gateway, symbol.")


class ExposureRow(BaseModel):
    gateway_id: str
    symbol: str
    net_qty: int = Field(description="Signed shares: negative is short.")
    tick_decimals: int = _TICK_DECIMALS
    mark_price: float | None = _display("Mark; null before one")
    mark_price_ticks: int | None = _ticks("mark_price")
    net_notional: float | None = _display("`net_qty * mark_price`, signed")
    net_notional_ticks: int | None = _ticks("net_notional")
    gross_notional: float | None = _display("`abs(net_notional)`")
    gross_notional_ticks: int | None = _ticks("gross_notional")
    realized_pnl: float = _display("Cumulative realized P&L")
    realized_pnl_ticks: float = _ticks("realized_pnl")
    unrealized_pnl: float = _display("Open P&L at the mark")
    unrealized_pnl_ticks: float = _ticks("unrealized_pnl")
    total_pnl: float = _display("Realized plus unrealized")
    total_pnl_ticks: float = _ticks("total_pnl")


class Exposure(_Bounded):
    exposure: list[ExposureRow] = Field(
        description="Largest first by the `sort` measure, in display currency."
    )


class ClearingTradeRow(BaseModel):
    trade_id: str = Field(description="The engine's durable trade id.")
    ts_ns: int = Field(description="Exchange time of the print (epoch nanoseconds).")
    ingest_ts_ns: int = Field(
        description="When clearing wrote the trade (epoch nanoseconds); not an "
        "exchange time."
    )
    trade_date: str = Field(description="Trading day, in the session timezone.")
    symbol: str
    quantity: int
    tick_decimals: int = _TICK_DECIMALS
    price: float = _display("Trade price")
    price_ticks: int = _ticks("price")
    buy_gateway_id: str | None = Field(
        description="Null when the caller is not the buyer and not ADMIN."
    )
    sell_gateway_id: str | None = Field(
        description="Null when the caller is not the seller and not ADMIN."
    )
    buy_order_id: str | None = Field(
        description="Null with `buy_gateway_id`, or when not recorded."
    )
    sell_order_id: str | None = Field(
        description="Null with `sell_gateway_id`, or when not recorded."
    )
    aggressor_side: str | None = Field(
        description="As the engine sent it; not an aggressor signal for auctions."
    )
    match_type: str | None = Field(
        description="How the trade came about (`CONTINUOUS`, `CLOSING_AUCTION`, ...)."
    )
    msg_id: str | None = Field(
        description="The audit trail's message id of the print, when recorded."
    )


class ClearingTradePage(_Page):
    trades: list[ClearingTradeRow] = Field(description="Newest first.")
    retained_from: str | None = Field(
        description="Oldest trading day still held as raw trades (older ones are "
        "pruned; their daily rows remain); null when none are held."
    )


class ClearingDailyRow(BaseModel):
    trade_date: str
    gateway_id: str
    symbol: str
    tick_decimals: int = _TICK_DECIMALS
    traded_qty: int
    traded_notional: float = _display("Traded value")
    traded_notional_ticks: int = _ticks("traded_notional")
    buy_qty: int
    sell_qty: int
    buy_notional: float = _display("Bought value")
    buy_notional_ticks: int = _ticks("buy_notional")
    sell_notional: float = _display("Sold value")
    sell_notional_ticks: int = _ticks("sell_notional")
    net_amount: float = _display("`buy_notional - sell_notional`")
    net_amount_ticks: int = _ticks("net_amount")
    realized_pnl: float = _display("The day's realized P&L")
    realized_pnl_ticks: float = _ticks("realized_pnl")
    end_net_qty: int = Field(description="Position after the day's last trade.")
    end_avg_cost: float = _display("Average cost after the day's last trade")
    end_avg_cost_ticks: float = _ticks("end_avg_cost")
    end_unrealized_pnl: float = _display("Open P&L after the day's last trade")
    end_unrealized_pnl_ticks: float = _ticks("end_unrealized_pnl")
    last_trade_ts_ns: int | None
    updated_ts_ns: int


class ClearingDaily(_Bounded):
    daily: list[ClearingDailyRow] = Field(
        description="Newest day first, then gateway, symbol."
    )


class CloseSnapshotRow(BaseModel):
    trade_date: str = Field(description="The trading day the snapshot closed.")
    gateway_id: str
    symbol: str
    net_qty: int
    tick_decimals: int = _TICK_DECIMALS
    realized_pnl: float = _display("Cumulative realized P&L at the close")
    realized_pnl_ticks: float = _ticks("realized_pnl")
    unrealized_pnl: float = _display("Open P&L at the closing mark")
    unrealized_pnl_ticks: float = _ticks("unrealized_pnl")
    mark_price: float | None = _display("Closing mark; null before one")
    mark_price_ticks: int | None = _ticks("mark_price")


class CloseSnapshots(_Bounded):
    snapshots: list[CloseSnapshotRow] = Field(
        description="Newest close first, then gateway, symbol."
    )


class ClearingSymbolRow(BaseModel):
    symbol: str
    tick_decimals: int = Field(
        description="The symbol's finest recorded precision; every money value "
        "of the row is converted to it."
    )
    traded_qty: int = Field(
        description="Shares traded, counted once per side (a 100-share trade is 200)."
    )
    traded_notional: float = _display("Traded value, both sides")
    traded_notional_ticks: float = _ticks("traded_notional")
    realized_pnl: float = _display("Realized P&L of all gateways")
    realized_pnl_ticks: float = _ticks("realized_pnl")
    open_net_qty: int = Field(
        description="Sum of the current signed positions of all gateways; zero "
        "when every holder is a gateway. Not open interest."
    )
    open_unrealized_pnl: float = _display("Open P&L of all current positions")
    open_unrealized_pnl_ticks: float = _ticks("open_unrealized_pnl")


class ClearingSymbols(_Bounded):
    symbols: list[ClearingSymbolRow] = Field(description="By symbol.")


class ParticipantRow(BaseModel):
    gateway_id: str
    realized_pnl: float = _display(
        "Realized P&L over all symbols, each converted before the sum"
    )
    unrealized_pnl: float = _display("Open P&L over all symbols, likewise")
    total_pnl: float = _display("Realized plus unrealized")
    position_count: int = Field(description="Symbols the gateway has a row for.")
    open_position_count: int = Field(description="Of those, with `net_qty != 0`.")
    last_update_ts_ns: int | None = Field(
        description="Latest clearing write of any of its positions; null when "
        "it has none."
    )


class Participants(_Bounded):
    participants: list[ParticipantRow] = Field(description="By gateway id.")


class ParticipantLinks(BaseModel):
    """The scoped routes for the gateway's other views."""

    positions: str
    exposure: str
    trades: str
    daily: str
    close_snapshots: str
    gateway_sessions: str
    settlements: str
    balances: str


class ParticipantDetail(ParticipantRow):
    positions: list[ClearingPositionRow] = Field(description="By symbol.")
    latest_close_date: str | None = Field(
        description="Latest trading day with a close snapshot of the gateway."
    )
    links: ParticipantLinks


class GapPayload(BaseModel):
    """A jump clearing saw in the trade ids of its feed: trades it never got."""

    run_seq: int | None = Field(description="Engine run the ids belong to.")
    last_seq: int | None = Field(description="Last id sequence before the gap.")
    next_seq: int | None = Field(description="First id sequence after the gap.")
    missing_trades: int | None = Field(description="Ids skipped: trades not seen.")


class FeedGap(GapPayload):
    trade_date: str
    ts_ns: int = Field(description="Exchange time of the trade after the gap.")


class EodRunStep(BaseModel):
    step: str
    status: str
    message: str


class EodRun(BaseModel):
    trade_date: str
    status: Literal["ok", "failed", "report-failed"] = Field(
        description="`ok`: settled and reported. `failed`: not settled. "
        "`report-failed`: settled, statements not written."
    )
    started_at: str = Field(description="ISO-8601 UTC.")
    finished_at: str = Field(description="ISO-8601 UTC.")
    steps: list[EodRunStep] | None = Field(
        default=None,
        description="ADMIN only: each step's outcome and message. Omitted for a "
        "participant.",
    )


class ClearingSummary(BaseModel):
    participant_count: int = Field(description="Gateways with a position row.")
    open_position_count: int = Field(description="Position rows with `net_qty != 0`.")
    realized_pnl: float = _display(
        "Realized P&L of all gateways, each row converted before the sum"
    )
    unrealized_pnl: float = _display("Open P&L of all gateways, likewise")
    last_trade_ts_ns: int | None = Field(
        description="Exchange time of the newest trade any position records."
    )
    last_flush_ts_ns: int | None = Field(
        description="Latest clearing write of a position row: fills reach the "
        "ledger in batches, up to the flush interval (5 s by default) after the "
        "trade."
    )
    session_date: str | None = Field(
        description="Latest trading day clearing recorded a session event for."
    )
    gap_count: int = Field(description="Feed gaps clearing saw on `session_date`.")
    latest_gap: FeedGap | None = Field(description="The newest feed gap, any day.")
    eod_db_available: bool = Field(
        description="False when the `pm-eod` ledger is missing or unreadable."
    )
    last_eod_run: EodRun | None = Field(
        description="pm-eod's newest run; null when none, or the ledger is "
        "unavailable."
    )


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


class PhasePayload(BaseModel):
    state: str = Field(description="The session state entered, e.g. `CLOSED`.")
    prev_state: str | None = Field(description="The state left; null if unknown.")


class EodPayload(BaseModel):
    symbols_count: int = Field(description="Symbols the engine's EOD marked.")
    marked_symbols: list[str] = Field(description="Those symbols, sorted.")


class SessionEventRow(BaseModel):
    """One event clearing recorded; exactly one of `phase`, `gap`, `eod` is set,
    the one named by `event_type`."""

    id: int
    event_type: Literal["EOD", "PHASE", "GAP"]
    ts_ns: int = Field(
        description="When clearing observed the event (epoch nanoseconds); for a "
        "`GAP`, the exchange time of the trade after it."
    )
    trade_date: str = Field(description="Trading day, in the session timezone.")
    phase: PhasePayload | None = Field(default=None, description="`PHASE` only.")
    gap: GapPayload | None = Field(default=None, description="`GAP` only.")
    eod: EodPayload | None = Field(default=None, description="`EOD` only.")


class SessionEvents(_Bounded):
    events: list[SessionEventRow] = Field(description="Newest first.")


class GatewaySessionRow(BaseModel):
    gateway_id: str
    connected_at_ns: int = Field(
        description="When clearing saw the gateway connect (epoch nanoseconds)."
    )
    disconnected_at_ns: int | None = Field(
        description="When clearing saw it disconnect; null while connected, or "
        "when no disconnect was seen."
    )
    disconnect_reason: str | None


class GatewaySessions(_Bounded):
    sessions: list[GatewaySessionRow] = Field(description="Newest connect first.")


class ReconciliationRow(BaseModel):
    """A day, side, gateway and symbol where the raw trades and the daily row
    disagree."""

    side: Literal["BUY", "SELL"]
    trade_date: str
    gateway_id: str
    symbol: str
    raw_qty: int = Field(description="Shares counted from the raw trades.")
    summary_qty: int = Field(description="Shares on the daily row.")
    qty_diff: int = Field(description="`raw_qty - summary_qty`.")
    tick_decimals: int = _TICK_DECIMALS
    raw_notional: float = _display("Value counted from the raw trades")
    raw_notional_ticks: int = _ticks("raw_notional")
    summary_notional: float = _display("Value on the daily row")
    summary_notional_ticks: int = _ticks("summary_notional")
    notional_diff: float = _display("`raw_notional - summary_notional`")
    notional_diff_ticks: int = _ticks("notional_diff")


class Reconciliation(_Bounded):
    discrepancies: list[ReconciliationRow] = Field(
        description="Empty: no discrepancy in the compared, retained data -- not "
        "proof of a complete venue history."
    )
    retained_from: str | None = Field(
        description="Oldest trading day still held as raw trades."
    )
    compared_from: str | None = Field(
        description="First day actually compared: `from`, or `retained_from` if "
        "later. Null when no day of the range has raw trades left."
    )
    compared_to: str | None = Field(description="Last day compared; null likewise.")


class DatabaseHealth(BaseModel):
    available: bool = Field(description="Whether `clearing.db` could be read.")
    detail: str = Field(description="`readable`, or why it could not be read.")
    wal_mode: str | None = Field(description="The journal mode; `wal` expected.")
    trade_events_rows: int | None
    gateway_symbol_positions_rows: int | None
    gateway_daily_summary_rows: int | None
    last_trade_ts_ns: int | None = Field(
        description="Exchange time of the newest retained trade."
    )
    last_flush_ts_ns: int | None = Field(
        description="Latest clearing write of a daily row."
    )


class ProcessHealth(BaseModel):
    alive: bool = Field(
        description="Whether pm-clearing's receive loop answered a ping in time. "
        "A readable database alone does not prove it."
    )
    detail: str


class ClearingHealth(BaseModel):
    database: DatabaseHealth
    process: ProcessHealth


_MINOR = "integer minor units of the display currency (2 decimals: 1234 is 12.34)"


class SettlementRow(BaseModel):
    """One account's settlement for one trading day: the change in its
    close-to-close P&L, transferred. Not margin, collateral or a payment."""

    trade_date: str
    account: str = Field(
        description="A gateway id, or `EXCHANGE` (the rounding residual; ADMIN "
        "only)."
    )
    amount_minor: int = Field(
        description=f"The settlement, {_MINOR}. Positive: the exchange owes the "
        "gateway; negative: the gateway owes the exchange."
    )
    amount: str = Field(description="`amount_minor` as a signed decimal string.")
    detail: dict[str, str] = Field(
        description="Per symbol, the unrounded day P&L in display currency as a "
        "decimal string, same sign as `amount_minor`; their sum rounds to it."
    )
    run_status: Literal["ok", "failed", "report-failed"] | None = Field(
        description="pm-eod's run of `trade_date`; null if none is recorded."
    )


class Settlements(_Bounded):
    settlements: list[SettlementRow] = Field(
        description="Newest day first, then account."
    )
    runs: list[EodRun] = Field(
        description="pm-eod's runs in the date range, newest first, including "
        "days it ran but did not settle (`failed`)."
    )


class BalanceRow(BaseModel):
    """A derived balance: the roster's opening balance plus the settlement
    amounts up to `as_of`. pm-eod stores no balance; this is the sum."""

    account: str
    opening_balance_minor: int = Field(
        description=f"From pm-eod's roster, {_MINOR}; 0 when not on it."
    )
    opening_balance: str = Field(description="As a signed decimal string.")
    settlement_total_minor: int = Field(
        description=f"Sum of the account's settlements up to `as_of`, {_MINOR}."
    )
    settlement_total: str = Field(description="As a signed decimal string.")
    balance_minor: int = Field(
        description="`opening_balance_minor + settlement_total_minor`."
    )
    balance: str = Field(description="As a signed decimal string.")


class Balances(_Counted):
    balances: list[BalanceRow] = Field(description="By account.")
    as_of: str | None = Field(
        description="The date the sums stop at, as requested; null for all."
    )
    last_settled_date: str | None = Field(
        description="The latest settled day the sums include; null when none."
    )
