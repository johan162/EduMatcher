/**
 * Typed endpoint helpers wrapping apiFetch.
 * Each function maps one logical API call to a typed return value.
 */
import { apiFetch } from "./apiFetch.js";
import type {
  CompanyProfile,
  NewsSnapshot,
  StatusResponse,
  Order,
  Position,
  QuoteBootstrapResponse,
  QuoteLegsResponse,
  SymbolInfoDTO,
  AdminGateway,
  HaltEntry,
  BootstrapTrader,
  BootstrapAdmin,
  ReferenceBundle,
  ReferenceScheduleDTO,
  SessionStatusDTO,
  DailyStatsResponse,
  HistoryTradesResponse,
  RawOrder,
  OrderAccepted,
  OrderHistoryResponse,
  HistoryFillsResponse,
  OcoPending,
  ComboPending,
  QuotePending,
  AdminOrdersResponse,
  AdminOrderLifecycleResponse,
  AdminSymbolKillSwitchResponse,
  AdminGatewayKillSwitchResponse,
  AdminGlobalKillSwitchResponse,
  RiskConfig,
  SymbolHaltAckResponse,
  SymbolResumeAckResponse,
  ReferenceIndexesResponse,
  IndexIdsResponse,
  IndexDailyResponse,
} from "@/types/index.js";

// ── Auth / status ─────────────────────────────────────────────────────────────
export const getStatus = () => apiFetch<StatusResponse>("/api/v1/status");

// ── Bootstrap (§7.2) ─────────────────────────────────────────────────────────
// One round-trip that replaces the symbols/session/positions/orders waterfall
// at login. `/trader` serves TRADER and MARKET_MAKER; ADMIN has its own.
export const getBootstrapTrader = (fillsLimit?: number) =>
  apiFetch<BootstrapTrader>(
    `/api/v1/bootstrap/trader${fillsLimit ? `?fills_limit=${fillsLimit}` : ""}`,
  );

export const getBootstrapAdmin = () => apiFetch<BootstrapAdmin>("/api/v1/bootstrap/admin");

// ── Symbols ───────────────────────────────────────────────────────────────────
export const getSymbols = () => apiFetch<{ symbols: SymbolInfoDTO[] }>("/api/v1/symbols");

// ── Reference bundle ──────────────────────────────────────────────────────────
export const getReference = () => apiFetch<ReferenceBundle>("/api/v1/reference");

export const getReferenceRisk = () => apiFetch<RiskConfig>("/api/v1/reference/risk");

export const getReferenceSchedule = () =>
  apiFetch<ReferenceScheduleDTO & { config_version: string | null }>("/api/v1/reference/schedule");

// ── Session ───────────────────────────────────────────────────────────────────
export const getSession = () => apiFetch<SessionStatusDTO>("/api/v1/session");

// ── Halts (§H4) ───────────────────────────────────────────────────────────────
// Open to every key; the market-data reconnect resync (WebSocketManager) and the
// admin circuit-breaker page both read it.
export const getHalts = () => apiFetch<{ halted: HaltEntry[] }>("/api/v1/halts");

// ── News (WP-E5) ──────────────────────────────────────────────────────────────
// pm-market-sim's latest headlines; live ones arrive on the market-data socket.
export const getNews = (limit = 200) => apiFetch<NewsSnapshot>(`/api/v1/news?limit=${limit}`);

// ── Company profiles ──────────────────────────────────────────────────────────
// pm-compdb-cli's companies.db, read by the gateway; 404 for an unknown symbol.
export const getCompany = (symbol: string) =>
  apiFetch<CompanyProfile>(`/api/v1/companies/${encodeURIComponent(symbol)}`);

// ── Orders ────────────────────────────────────────────────────────────────────
// Raw rows: the engine `OrderDisplay` (id/timestamp/client_tag); an engine
// timeout is a 503, never cached rows. Callers normalize via normalizeOrder.
export const getOrders = () => apiFetch<{ orders: RawOrder[] }>("/api/v1/orders");

export const getOrder = (orderId: string) => apiFetch<Order>(`/api/v1/orders/${orderId}`);

// `wait: "ack"` asks the gateway to fold the first `order.ack` into the HTTP
// response (§12.9) — the ticket uses this so a LIMIT submit yields a synchronous
// accepted/rejected verdict without needing the /events + PENDING-row machinery.
export const submitOrder = (body: Record<string, unknown>, wait?: "ack") =>
  apiFetch<OrderAccepted>(`/api/v1/orders${wait ? `?wait=${wait}` : ""}`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const cancelOrder = (orderId: string, requestTag?: string) => {
  const qs = requestTag ? `?${new URLSearchParams({ request_tag: requestTag }).toString()}` : "";
  return apiFetch<void>(`/api/v1/orders/${orderId}${qs}`, { method: "DELETE" });
};

export const amendOrder = (orderId: string, body: Record<string, unknown>) =>
  apiFetch<Order>(`/api/v1/orders/${orderId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });

export const replaceOrder = (orderId: string, body: Record<string, unknown>) =>
  apiFetch<{ cancelled_order_id: string; replacement_order_id: string }>(
    `/api/v1/orders/${orderId}/replace`,
    { method: "POST", body: JSON.stringify(body) },
  );

export const massCancelOrders = (body?: Record<string, unknown>) =>
  apiFetch<{ cancelled_orders: number; command_id: string }>("/api/v1/mass-cancel", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });

// ── OCO / Combo ───────────────────────────────────────────────────────────────
// Both submit endpoints answer 202 with the id you chose (`oco_id` / `combo_id`).
export const submitOco = (body: Record<string, unknown>) =>
  apiFetch<OcoPending>("/api/v1/oco", {
    method: "POST",
    body: JSON.stringify(body),
  });

// DELETE answers 202 `{ oco_id, status: "PENDING_CANCEL", ... }`; body is ignored —
// the outcome arrives on the private WebSocket as `oco.cancel_ack`.
export const cancelOco = (ocoId: string) =>
  apiFetch<{ oco_id: string; status: string }>(`/api/v1/oco/${ocoId}`, { method: "DELETE" });

export const submitCombo = (body: Record<string, unknown>) =>
  apiFetch<ComboPending>("/api/v1/combos", {
    method: "POST",
    body: JSON.stringify(body),
  });

// DELETE answers 202 `{ combo_id, status: "PENDING_CANCEL", ... }`; body is ignored —
// the outcome arrives on the private WebSocket as `combo.cancel_ack`.
export const cancelCombo = (comboId: string) =>
  apiFetch<{ combo_id: string; status: string }>(`/api/v1/combos/${comboId}`, {
    method: "DELETE",
  });

// ── Positions ─────────────────────────────────────────────────────────────────
export const getPositions = () =>
  apiFetch<{ positions: Position[] }>("/api/v1/positions").then((response) => response.positions);

// ── Quotes (§14) ──────────────────────────────────────────────────────────────
// Bootstrap is the authoritative per-side source (ActiveQuote); legs is a dual-
// shape supplement (see QuoteLegsResponse). Both require a trading key (no MM
// role gate at the gateway — the engine may still reject via quote.ack).
export const getQuoteBootstrap = () => apiFetch<QuoteBootstrapResponse>("/api/v1/quotes");

export const getQuoteLegs = () => apiFetch<QuoteLegsResponse>("/api/v1/quotes/legs");

// 202 `{ symbol, quote_id, status }` — quote_id is null when none was submitted.
export const submitQuote = (body: Record<string, unknown>) =>
  apiFetch<QuotePending>("/api/v1/quotes", {
    method: "POST",
    body: JSON.stringify(body),
  });

// Quotes are addressed by symbol for cancel (one active quote per gateway+symbol).
// DELETE answers 202 `{ symbol, status: "PENDING_CANCEL", ... }`; body is ignored —
// the outcome arrives on the private WebSocket as `quote.cancel_ack`.
export const cancelQuote = (symbol: string) =>
  apiFetch<{ symbol: string; status: string }>(
    `/api/v1/quotes/${encodeURIComponent(symbol)}`,
    { method: "DELETE" },
  );

// ── History ───────────────────────────────────────────────────────────────────
export const getHistoryOrders = (orderId: string) =>
  apiFetch<OrderHistoryResponse>(`/api/v1/history/orders/${encodeURIComponent(orderId)}`);

export const getHistoryFills = async (params?: Record<string, string>) => {
  const pageParams = new URLSearchParams(params);
  pageParams.set("limit", "5000");
  const events: HistoryFillsResponse["events"] = [];
  let nextCursor: string | null = null;
  let response: HistoryFillsResponse;

  do {
    if (nextCursor) pageParams.set("after", nextCursor);
    else pageParams.delete("after");
    response = await apiFetch<HistoryFillsResponse>(
      `/api/v1/history/fills?${pageParams.toString()}`,
    );
    events.push(...response.events);
    nextCursor = response.next_cursor;
  } while (nextCursor);

  return {
    events,
    count: events.length,
    has_more: false,
    retained_from: response.retained_from,
  };
};

export const getHistoryTrades = (symbol: string, limit = 50) =>
  apiFetch<HistoryTradesResponse>(
    `/api/v1/history/trades?symbol=${encodeURIComponent(symbol)}&limit=${limit}`,
  );

/**
 * Daily OHLC rollup. Omitting `date` returns the latest available date, which
 * would silently be *yesterday* before the first print of the session — so
 * callers computing today's change % must pass today's date explicitly and
 * accept an empty list until the first trade.
 */
export const getHistoryDaily = (params?: {
  symbol?: string;
  date?: string;
  limit?: number;
  after?: string;
}) => {
  const qs = new URLSearchParams();
  if (params?.symbol) qs.set("symbol", params.symbol);
  if (params?.date) qs.set("date", params.date);
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.after) qs.set("after", params.after);
  const suffix = qs.size ? `?${qs.toString()}` : "";
  return apiFetch<DailyStatsResponse>(`/api/v1/history/daily${suffix}`);
};

// ── Admin ─────────────────────────────────────────────────────────────────────
export const getAdminGateways = () =>
  apiFetch<{ gateways: AdminGateway[] }>("/api/v1/admin/gateways");

export const disconnectGateway = (id: string, reason?: string) =>
  apiFetch<{ gateway_id: string; status: string }>(`/api/v1/admin/gateways/${encodeURIComponent(id)}/disconnect`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });

// Halt one symbol. `level` (one of the symbol's configured CB levels) runs the
// real breaker activation with auto-resume; omitting it halts indefinitely.
// 200 SymbolHaltAck; an engine refusal is 409 HALT_REJECTED (its reason is the message).
export const triggerCircuitBreaker = (symbol: string, level?: string) =>
  apiFetch<SymbolHaltAckResponse>(`/api/v1/admin/symbols/${encodeURIComponent(symbol)}/halt`, {
    method: "POST",
    body: JSON.stringify(level ? { level } : {}),
  });

export const resumeCircuitBreaker = (symbol: string) =>
  apiFetch<SymbolResumeAckResponse>(`/api/v1/admin/symbols/${encodeURIComponent(symbol)}/resume`, {
    method: "POST",
    body: JSON.stringify({}),
  });

// ── Index administration (read-only for phase 13) ───────────────────────────
export const getReferenceIndexes = () =>
  apiFetch<ReferenceIndexesResponse>("/api/v1/reference/indexes");

export const getHistoryIndexIds = (date?: string) =>
  apiFetch<IndexIdsResponse>(`/api/v1/history/indexes${date ? `?date=${encodeURIComponent(date)}` : ""}`);

export const getHistoryIndexDaily = (params?: { index_id?: string; date?: string; limit?: number }) => {
  const qs = new URLSearchParams();
  if (params?.index_id) qs.set("index_id", params.index_id);
  if (params?.date) qs.set("date", params.date);
  if (params?.limit) qs.set("limit", String(params.limit));
  const suffix = qs.size ? `?${qs.toString()}` : "";
  return apiFetch<IndexDailyResponse>(`/api/v1/history/index-daily${suffix}`);
};

export const transitionSession = (toState: string) =>
  apiFetch<{ command_id: string; requested_state: string; status: string }>(
    "/api/v1/admin/session/transition",
    {
      method: "POST",
      body: JSON.stringify({ to_state: toState }),
    },
  );

// Current-state cross-gateway orders (bounded by order_retention_sec). Filters:
// symbol, gateway_id, status — all matched case-insensitively server-side.
export const getAdminOrders = (params?: Record<string, string>) => {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  return apiFetch<AdminOrdersResponse>(`/api/v1/admin/orders${qs}`);
};

// Full cross-gateway lifecycle from the pm-audit index (independent of cache
// retention). 503 AUDIT_INDEX_UNAVAILABLE when pm-audit isn't running; 404
// UNKNOWN_ORDER when the order has no audited events.
export const getAdminOrderDetail = (orderId: string, limit?: number) =>
  apiFetch<AdminOrderLifecycleResponse>(
    `/api/v1/admin/orders/${encodeURIComponent(orderId)}/audit${limit ? `?limit=${limit}` : ""}`,
  );

// Admin kill-switch scopes (§15.8). All 200 with the engine ack; an engine refusal
// is a 409 KILL_SWITCH_REJECTED, not an `accepted: false` body.
export const adminSymbolKillSwitch = (symbol: string, reason?: string) =>
  apiFetch<AdminSymbolKillSwitchResponse>(
    `/api/v1/admin/symbols/${encodeURIComponent(symbol)}/cancel-orders`,
    { method: "POST", body: JSON.stringify(reason ? { reason } : {}) },
  );

// Cancel every resting order/quote of one named gateway (does NOT disconnect it
// — that is the separate Kick action). The gateway is the path segment.
export const adminGatewayKillSwitch = (targetGatewayId: string, reason?: string) =>
  apiFetch<AdminGatewayKillSwitchResponse>(
    `/api/v1/admin/gateways/${encodeURIComponent(targetGatewayId)}/kill-switch`,
    { method: "POST", body: JSON.stringify(reason ? { reason } : {}) },
  );

// Full-market emergency stop: cancel every resting order/quote for every gateway.
export const adminGlobalKillSwitch = (reason?: string) =>
  apiFetch<AdminGlobalKillSwitchResponse>("/api/v1/admin/market/kill-switch", {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
