/**
 * Core TypeScript types mirroring the pm-api-gwy REST shapes and pm-msgen
 * WebSocket payloads defined in Appendix A of EduMatcher-Trading-GUI.md.
 *
 * Two contracts live here:
 *  • REST resource shapes  — defined by gateway Pydantic models / OpenAPI
 *  • WS `data` payloads    — pm-msgen `to_dict()` payloads forwarded verbatim,
 *                            using ENGINE field names (qty, client_tag, …)
 */

// ── Enums ─────────────────────────────────────────────────────────────────────
export type Side = "BUY" | "SELL";

export type OrderType =
  "MARKET" | "LIMIT" | "STOP" | "STOP_LIMIT" | "FOK" | "ICEBERG" | "IOC" | "TRAILING_STOP";

export type Tif = "DAY" | "GTC" | "ATO" | "ATC";

export type SmpAction = "NONE" | "CANCEL_AGGRESSOR" | "CANCEL_RESTING" | "CANCEL_BOTH";

export type OrderStatus =
  "NEW" | "PARTIAL" | "FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED" | "PENDING"; // local-only — not yet acked

export type SessionState =
  "PRE_OPEN" | "OPENING_AUCTION" | "CONTINUOUS" | "CLOSING_AUCTION" | "CLOSED";

export type GatewayRole = "TRADER" | "MARKET_MAKER" | "ADMIN";

export type ResumptionMode = "AUCTION" | "CONTINUOUS";

// ── REST: status ──────────────────────────────────────────────────────────────
export interface StatusResponse {
  orders: number;
  quote_legs: number;
  positions: Record<string, unknown>;
  known_symbols: string[];
  gateway_role: GatewayRole;
  gateway_count?: number; // ADMIN keys only
}

// ── REST: Order ───────────────────────────────────────────────────────────────
/**
 * Canonical order shape used across the UI. It is NOT the raw wire shape:
 * `GET /orders` returns the engine's pm-msgen `OrderDisplay`, whose id key is
 * `id`, whose timestamp is `timestamp` (epoch seconds), and whose client tag
 * is `client_tag`; the timeout-fallback path returns a thinner row keyed on
 * `order_id`. `normalizeOrder()` (below) folds both into this one shape, so
 * every screen reads `order_id`/`updated_at`/`client_order_id` regardless of
 * which path served the data.
 */
export interface Order {
  order_id: string;
  client_order_id?: string | null;
  symbol: string;
  side: Side;
  order_type: OrderType;
  tif: Tif;
  quantity: number;
  remaining_qty: number;
  price: number | null;
  stop_price: number | null;
  visible_qty: number | null;
  trail_offset: number | null;
  smp_action: SmpAction | null;
  status: OrderStatus;
  oco_group_id?: string | null;
  combo_parent_id?: string | null;
  /** Present on admin cross-gateway views; absent on own-gateway /orders */
  gateway_id?: string;
  /** Epoch-seconds order timestamp, ISO-normalised for display. */
  updated_at: string | null;
}

/**
 * Response of `POST /api/v1/orders` (schemas.OrderAccepted). `202` means the
 * order reached the engine, NOT that it was accepted — that authority is the
 * `order.ack` event. Submitting with `?wait=ack` folds the first ack into this
 * response: `status` becomes `"ACKED"`, `accepted` is the ack verdict, and
 * `event` is the raw `order.ack` payload. Without `wait`, `status` is
 * `"PENDING"` and `accepted`/`event` are null. Note: under `wait=ack` an ack
 * that does not arrive in time is returned as HTTP `503 ENGINE_TIMEOUT`, NOT a
 * `PENDING` body — the order is still submitted and must be reconciled (§12.9).
 */
export interface OrderAccepted {
  order_id: string;
  client_order_id?: string | null;
  status: "PENDING" | "ACKED";
  /** null when not waited-on or the ack timed out; otherwise the ack verdict. */
  accepted: boolean | null;
  /** Raw `order.ack` payload when `wait=ack` resolved, else null. */
  event: OrderAckData | null;
}

/**
 * The two shapes `GET /orders` can return: the rich engine `OrderDisplay`
 * (id/timestamp/client_tag) and the thin gateway cache fallback that a reply
 * timeout produces (order_id, no display prices). Everything is optional so a
 * single normalizer can accept either.
 */
export interface RawOrder {
  id?: string;
  order_id?: string;
  symbol?: string;
  side?: Side;
  order_type?: OrderType;
  tif?: Tif;
  quantity?: number;
  qty?: number; // ack/fill/amend events and the /events snapshot cache use `qty`
  remaining_qty?: number;
  price?: number | null;
  stop_price?: number | null;
  visible_qty?: number | null;
  trail_offset?: number | null;
  smp_action?: SmpAction | null;
  // The gateway session cache (snapshot rows) also emits "AMENDED", which is
  // not a canonical OrderStatus — normalizeOrder folds it back to NEW/PARTIAL.
  status?: OrderStatus | "AMENDED";
  oco_group_id?: string | null;
  combo_parent_id?: string | null;
  gateway_id?: string;
  timestamp?: number | null; // OrderDisplay: epoch seconds
  client_tag?: string | null; // OrderDisplay
  client_order_id?: string | null; // thin cache fallback
  updated_at?: string | null;
}

/**
 * Fold either `/orders` shape into the canonical {@link Order}. The engine
 * `OrderDisplay` uses `id`/`timestamp`/`client_tag`; the reply-timeout cache
 * fallback uses `order_id` and omits the display fields — this reconciles both
 * so no screen has to know which one it got.
 */
export function normalizeOrder(raw: RawOrder): Order {
  const tsSec = raw.timestamp ?? null;
  const quantity = raw.quantity ?? raw.qty ?? 0;
  const remaining = raw.remaining_qty ?? quantity;
  // "AMENDED" is a cache-only marker; an amended order is still working, so
  // resolve it to PARTIAL (some already filled) or NEW from the quantities.
  const status: OrderStatus =
    raw.status === "AMENDED"
      ? remaining < quantity
        ? "PARTIAL"
        : "NEW"
      : (raw.status ?? "PENDING");
  return {
    order_id: raw.id ?? raw.order_id ?? "",
    client_order_id: raw.client_order_id ?? raw.client_tag ?? null,
    symbol: raw.symbol ?? "",
    side: raw.side ?? "BUY",
    order_type: raw.order_type ?? "LIMIT",
    tif: raw.tif ?? "DAY",
    quantity,
    remaining_qty: remaining,
    price: raw.price ?? null,
    stop_price: raw.stop_price ?? null,
    visible_qty: raw.visible_qty ?? null,
    trail_offset: raw.trail_offset ?? null,
    smp_action: raw.smp_action ?? null,
    status,
    oco_group_id: raw.oco_group_id ?? null,
    combo_parent_id: raw.combo_parent_id ?? null,
    gateway_id: raw.gateway_id,
    updated_at:
      raw.updated_at ?? (tsSec === null ? null : new Date(tsSec * 1000).toISOString()),
  };
}

/**
 * One row of `GET /api/v1/history/orders/{order_id}` — a durable `order_events`
 * record from stats.db, in chronological order. Prices are display money.
 * `event_type` is the stats vocabulary (ACK/REJECT/FILL/AMEND/CANCEL/EXPIRE and
 * combo/oco/quote variants), NOT the live OrderStatus. `priority_reset` is 0/1.
 */
export interface OrderHistoryEvent {
  seq: number;
  ts: string; // ISO-8601 UTC ms
  event_type: string;
  order_id: string;
  gateway_id: string;
  symbol: string;
  side: string | null;
  order_type: string | null;
  tif: string | null;
  price: number | null;
  quantity: number | null;
  remaining_qty: number | null;
  status: string | null;
  fill_price: number | null;
  fill_qty: number | null;
  trade_id: string | null;
  reason: string | null;
  client_order_id: string | null;
  combo_parent_id: string | null;
  oco_group_id: string | null;
  priority_reset: number | null;
}

export interface OrderHistoryResponse {
  events: OrderHistoryEvent[];
  count: number;
}

// ── REST: Fill (private order.fill event / pm-msgen OrderFill) ────────────────
export interface Fill {
  gateway_id: string;
  order_id: string;
  fill_qty: number;
  fill_price: number;
  remaining_qty: number;
  status: OrderStatus; // PARTIAL | FILLED
  /** Public trade id(s) composing this fill; [] if none. */
  trade_ids: string[];
  symbol?: string;
  side?: Side;
  order_type?: OrderType; // present when the engine had the order to hand
  tif?: Tif;
  qty?: number; // original order qty (engine name)
  price?: number;
  client_tag?: string; // engine name for client_order_id
  oco_group_id?: string;
  combo_parent_id?: string;
  quote_id?: string;
  leg_index?: number;
}

// ── REST: Trade (public print) ────────────────────────────────────────────────
export interface Trade {
  id: string;
  symbol: string;
  price: number;
  quantity: number;
  aggressor_side: Side;
  ts: string;
}

/**
 * One row of `GET /api/v1/history/trades` (stats `trade_log`, prices already
 * converted to display money). Note the id field is `trade_id`, `ts` is ISO,
 * and an auction print carries `aggressor_side: "AUCTION"`.
 */
export interface HistoryTrade {
  ts: string;
  trade_id: string;
  symbol: string;
  price: number;
  quantity: number;
  tick_decimals: number;
  aggressor_side: "BUY" | "SELL" | "AUCTION";
  buy_gateway_id?: string;
  sell_gateway_id?: string;
}

export interface HistoryTradesResponse {
  trades: HistoryTrade[];
  count: number;
  has_more: boolean;
  next_cursor?: string;
}

// ── Book / Depth / Auction (market-data) ─────────────────────────────────────
export interface BookLevel {
  price: number;
  qty: number;
  count: number;
}

export interface BookSnapshot {
  symbol: string;
  bids: BookLevel[];
  asks: BookLevel[];
  last_price: number | null;
  last_qty: number | null;
  last_buy_price?: number | null;
  last_sell_price?: number | null;
}

export interface DepthMetrics {
  symbol: string;
  mid_price: number;
  bid_depth: number;
  ask_depth: number;
  imbalance: number;
  cost_to_move: number;
}

/**
 * Final uncross result. pm-msgen carries `reason`, NOT an `indicative` flag.
 * The indicative is a separate message type (AuctionIndicative).
 * Envelope type: "auction"
 */
export type AuctionReason = "SCHEDULED" | "REOPEN" | "RECOVERY" | "BACKSTOP";

export interface AuctionResult {
  symbol: string;
  eq_price: number | null; // null if nothing crossed
  eq_qty: number;
  imbalance_side: Side | null;
  imbalance_qty: number;
  trades_count: number;
  reason: AuctionReason;
}

/**
 * Running call-phase indicative.
 * Envelope type: "auction.indicative" (same `auction` channel).
 */
export interface AuctionIndicative {
  symbol: string;
  phase: "OPENING_AUCTION" | "CLOSING_AUCTION";
  eq_price: number | null; // null if book would not cross yet
  eq_qty: number;
  imbalance_side: Side | null;
  imbalance_qty: number;
}

// ── Session event ─────────────────────────────────────────────────────────────
export interface SessionEvent {
  state: SessionState;
  prev_state?: SessionState;
  /** Present only on a scheduler-driven transition. pm-msgen NextTransition:
   * the phase moved-to is `state` (NOT `to_state`), plus an ISO `at`. */
  next?: {
    state: SessionState;
    at: string; // scheduled transition time (ISO-8601)
  };
}

// ── Circuit breaker events ────────────────────────────────────────────────────
/** Discriminate halt vs resume on the envelope `topic`, not an `action` field. */
export interface CircuitBreakerHalt {
  symbol: string;
  level: string | null; // level NAME, e.g. "L2"; null on ADMIN halt
  trigger_price: number | null; // null on non-price halt
  reference_price: number | null;
  resume_at_ns: number | null; // epoch nanoseconds; null = indefinite halt
  halt_source?: string; // "CIRCUIT_BREAKER" | "ADMIN"
  corridor_low?: number | null;
  corridor_high?: number | null;
  expansion?: number | null;
}

export interface CircuitBreakerResume {
  symbol: string;
  halt_source?: string;
  reason?: string;
  clamped?: boolean | null;
  print_price?: number | null;
}

// ── Positions ─────────────────────────────────────────────────────────────────
export interface Position {
  symbol: string;
  net_qty: number; // + long, - short
  last_price: number | null;
}

// ── MM quote legs (§14.3) ─────────────────────────────────────────────────────
/** pm-msgen QuoteLeg. leg_side is "BUY"/"SELL", not "bid"/"ask". */
export interface QuoteLeg {
  quote_id: string;
  order_id: string;
  symbol: string;
  leg_side: Side;
  price?: number | null;
  qty: number;
  remaining: number;
  filled: number;
  status: string;
  quote_status: string;
}

// ── Symbol metadata ───────────────────────────────────────────────────────────
/** Raw shape from GET /api/v1/symbols (pm-msgen SymbolInfo). */
export interface SymbolInfoDTO {
  symbol: string;
  tick_decimals: number;
  prev_close?: number | null;
  enforce_mm_obligation?: boolean | null;
  mm_max_spread_ticks?: number | null;
  mm_min_qty?: number | null;
}

/**
 * Merged view stored in useSymbolStore (§18.1.5).
 * tick_decimals/prev_close from /symbols, level from /reference (ReferenceSymbol).
 *
 * `collar_reference_price` is the live per-symbol collar anchor. It is NOT in
 * /symbols, /reference or /reference/risk (those carry no per-symbol price); it
 * is exposed ONLY on the ADMIN-only GET /api/v1/admin/risk/state as
 * `collar_reference_price`, so it stays null for TRADER/MARKET_MAKER and is
 * populated only by the ADMIN Symbol/Risk screens. Order-entry uses a live
 * price hint instead (see usePriceHint).
 */
export interface Symbol {
  symbol: string;
  tick_decimals: number;
  prev_close: number | null;
  collar_reference_price: number | null; // ADMIN-only, from /admin/risk/state
  level?: string | null; // collar profile name from /reference
}

// ── Admin types ───────────────────────────────────────────────────────────────
export interface AdminGateway {
  id: string; // pm-msgen GatewayInfo.id
  role: GatewayRole;
  connected: boolean;
  description?: string;
}

/** pm-msgen HaltedSymbol / circuit_breaker.halt broadcast. */
export interface HaltEntry {
  symbol: string;
  level?: string | null;
  resume_at_ns?: number | null;
  halt_source?: string | null;
  trigger_price?: number | null;
  reference_price?: number | null;
}

export interface MonitorEvent {
  event_type: "ACK" | "FILL" | "CANCEL" | "AMEND" | "EXPIRE" | "REJECT" | "SESSION" | "CB";
  order_id?: string;
  gateway_id?: string;
  symbol?: string;
  fill_qty?: number;
  fill_price?: number;
  remaining_qty?: number;
  liquidity?: "MAKER" | "TAKER";
}

// ── History: daily rollup (GET /history/daily) ───────────────────────────────
/**
 * One row of `daily_stats`, already converted from integer ticks to display
 * money by the gateway using the row's own `tick_decimals`.
 */
export interface DailyStat {
  date: string; // YYYY-MM-DD
  symbol: string;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  close_price: number | null;
  open_bid: number | null;
  open_ask: number | null;
  close_bid: number | null;
  close_ask: number | null;
  volume: number;
  trade_count: number;
  turnover: number;
  vwap: number | null;
  largest_trade_qty: number | null;
  largest_trade_price: number | null;
  tick_decimals: number | null;
}

/**
 * The standard paginated list envelope. Note the key is `daily`, not `stats`
 * as an earlier revision of the design document had it.
 */
export interface DailyStatsResponse {
  daily: DailyStat[];
  count: number;
  has_more: boolean;
  next_cursor?: string;
}

// ── Reference bundle (GET /reference, and `reference` inside bootstrap) ──────
/** One instrument's static configuration (pm-msgen ReferenceSymbol). */
export interface ReferenceSymbol {
  symbol: string;
  tick_decimals: number;
  level?: string | null;
  collar?: Record<string, unknown> | null;
  circuit_breaker?: Record<string, unknown> | null;
}

/** Five wall-clock times; each is individually nullable (partial config is legal). */
export interface SessionTimesDTO {
  pre_open?: string | null;
  opening_auction_start?: string | null;
  continuous_start?: string | null;
  closing_auction_start?: string | null;
  closing_auction_end?: string | null;
}

/** pm-msgen ReferenceSchedule — note `schedule` is nested, not flattened. */
export interface ReferenceScheduleDTO {
  sessions_enabled: boolean;
  country?: string | null;
  schedule?: SessionTimesDTO | null;
}

export interface ReferenceBundle {
  gateway_id?: string;
  symbols: ReferenceSymbol[];
  risk: { levels: unknown[]; default_level?: string | null };
  indexes: unknown[];
  schedule: ReferenceScheduleDTO;
  config_version: string | null;
}

/** pm-msgen SessionStatus — the polled answer to the `session.state` broadcast. */
export interface SessionStatusDTO {
  gateway_id?: string;
  state: SessionState;
  sessions_enabled: boolean;
}

export interface BootstrapCapabilities {
  sessions_enabled: boolean;
  stats_db_available: boolean;
  audit_db_available: boolean;
  index_available: boolean;
}

/** GET /api/v1/bootstrap/trader — also serves MARKET_MAKER (§7.2). */
export interface BootstrapTrader {
  ts: string;
  /** Names of optional fields whose engine query timed out; retry those. */
  incomplete: string[];
  gateway_id: string | null;
  gateway_role: GatewayRole | "READ_ONLY";
  reference: ReferenceBundle;
  session: SessionStatusDTO | null;
  positions: Position[];
  orders: { orders: Order[] };
  recent_fills: { events: unknown[]; count: number } | null;
  capabilities: BootstrapCapabilities;
}

/** GET /api/v1/bootstrap/admin. */
export interface BootstrapAdmin {
  ts: string;
  incomplete: string[];
  gateway_id: string;
  gateway_role: "ADMIN";
  reference: ReferenceBundle;
  session: SessionStatusDTO | null;
  gateways: { gateways: AdminGateway[] } | null;
  halts: { halted: HaltEntry[] } | null;
  active_order_counts: Record<string, number>;
  monitor_last_seq: Record<string, number>;
  capabilities: BootstrapCapabilities;
}

// ── Market-data subscription item ────────────────────────────────────────────
export interface MarketDataSubscriptionItem {
  symbols: string[]; // may include "*" for broad coverage
  channels: Array<"book" | "trades" | "depth" | "auction">;
}

// ── WebSocket envelope ────────────────────────────────────────────────────────
export interface WsEnvelope<T = unknown> {
  type: string;
  topic: string;
  ts: string;
  gateway_id?: string;
  seq?: number; // per-TOPIC counter (market data + admin monitor)
  stream_seq?: number; // private events only
  data: T;
}

// ── WS data payloads (pm-msgen wire) ─────────────────────────────────────────
export interface OrderAckData {
  gateway_id: string;
  order_id: string;
  accepted: boolean;
  reason: string;
  symbol?: string;
  side?: Side;
  order_type?: OrderType;
  tif?: Tif;
  qty?: number;
  price?: number;
  client_tag?: string;
  oco_group_id?: string;
  combo_parent_id?: string;
  quote_id?: string;
  leg_index?: number;
}

export interface OrderAmendedData {
  gateway_id: string;
  order_id: string;
  qty: number;
  remaining_qty: number;
  priority_reset: boolean;
  price: number | null;
}

export interface OrderTerminalData {
  gateway_id: string;
  order_id: string;
  client_tag?: string;
  oco_group_id?: string;
  combo_parent_id?: string;
  quote_id?: string;
  leg_index?: number;
}

export interface ComboAckData {
  gateway_id: string;
  combo_id: string;
  accepted: boolean;
  reason: string;
}

export interface ComboStatusData {
  gateway_id: string;
  combo_id: string;
  status: string;
  reason?: string;
}

export interface OcoAckData {
  gateway_id: string;
  oco_id: string;
  accepted: boolean;
  reason: string;
  order_id_1: string;
  order_id_2: string;
}

export interface OcoCancelledData {
  gateway_id: string;
  oco_id: string;
  cancelled_order_id: string;
  reason?: string;
}

export interface QuoteAckData {
  gateway_id: string;
  accepted: boolean;
  quote_id: string;
  reason: string;
  bid_order_id: string;
  ask_order_id: string;
}

export interface QuoteStatusData {
  gateway_id: string;
  status: string;
  quote_id: string;
  reason?: string;
}

export interface MassCancelAckData {
  gateway_id: string;
  accepted: boolean;
  reason: string;
  cancelled_orders: number;
  cancelled_quotes: number;
  command_id: string;
}

export interface RecentTrade {
  id: string;
  symbol: string;
  buy_order_id: string;
  sell_order_id: string;
  buy_gateway_id: string;
  sell_gateway_id: string;
  price: number;
  quantity: number;
  timestamp: number; // epoch seconds
}

/** Full book snapshot — includes tick_decimals and recent_trades tail. */
export interface BookData {
  symbol: string;
  tick_decimals: number;
  bids: BookLevel[];
  asks: BookLevel[];
  recent_trades: RecentTrade[];
  last_price: number | null;
  last_qty: number | null;
  last_buy_price: number | null;
  last_sell_price: number | null;
}

/** Full depth snapshot (no deltas). */
export interface DepthData {
  symbol: string;
  mid_price_ticks: number;
  mid_price: number;
  tolerance_ticks: number;
  bid_depth: number;
  ask_depth: number;
  imbalance: number; // [-1, 1]
  microprice: number;
  cost_to_move: number;
}

/** Public print (pm-msgen TradeExecuted). */
export interface TradeData {
  id: string;
  symbol: string;
  buy_order_id: string;
  sell_order_id: string;
  buy_gateway_id: string;
  sell_gateway_id: string;
  price: number;
  quantity: number;
  aggressor_side: "BUY" | "SELL" | "AUCTION";
  timestamp: number; // epoch seconds
  tick_decimals: number;
}

/**
 * The `/events` socket's first data frame on (re)connect — a point-in-time
 * snapshot of this gateway's cached orders/positions/quote legs, accurate as of
 * `stream_seq`. `orders` rows are the accreted session-cache shape (keyed
 * `order_id`, `qty`/`quantity` both possible, status incl. PENDING/AMENDED),
 * so they normalize through {@link normalizeOrder} like `GET /orders` rows.
 */
export interface OrdersSnapshotData {
  orders: RawOrder[];
  positions: Record<string, number>;
  quote_legs: unknown[];
}

/** type → data binding map. */
export interface WsDataByType {
  "orders.snapshot": OrdersSnapshotData;
  "order.ack": OrderAckData;
  "order.fill": Fill;
  "order.amended": OrderAmendedData;
  "order.cancelled": OrderTerminalData;
  "order.expired": OrderTerminalData;
  "combo.ack": ComboAckData;
  "combo.status": ComboStatusData;
  "oco.ack": OcoAckData;
  "oco.cancelled": OcoCancelledData;
  "quote.ack": QuoteAckData;
  "quote.status": QuoteStatusData;
  "mass_cancel.ack": MassCancelAckData;
  book: BookData;
  depth: DepthData;
  trade: TradeData;
  auction: AuctionResult;
  "auction.indicative": AuctionIndicative;
  session: SessionEvent;
  /** Discriminate halt vs resume on envelope `topic`. */
  circuit_breaker: CircuitBreakerHalt | CircuitBreakerResume;
}

export type WsEventType = keyof WsDataByType;
