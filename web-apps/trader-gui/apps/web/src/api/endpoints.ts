/**
 * Typed endpoint helpers wrapping apiFetch.
 * Each function maps one logical API call to a typed return value.
 */
import { apiFetch } from "./apiFetch.js";
import type {
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
  PendingIdResponse,
  AdminOrdersResponse,
  AdminOrderLifecycleResponse,
  AdminSymbolKillSwitchResponse,
  AdminGatewayKillSwitchResponse,
  AdminGlobalKillSwitchResponse,
  RiskConfig,
  SymbolHaltAckResponse,
  SymbolResumeAckResponse,
  AdminIndexesResponse,
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

// ── Orders ────────────────────────────────────────────────────────────────────
// Raw rows: the engine `OrderDisplay` (id/timestamp/client_tag) or the thin
// timeout-fallback cache row (order_id). Callers normalize via normalizeOrder.
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

export const cancelOrder = (orderId: string) =>
  apiFetch<void>(`/api/v1/orders/${orderId}`, { method: "DELETE" });

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
  apiFetch<{ cancelled_orders: number; command_id: string }>("/api/v1/kill-switch", {
    method: "POST",
    body: JSON.stringify(body ?? {}),
  });

// ── OCO / Combo ───────────────────────────────────────────────────────────────
// Both submit endpoints answer 202 with PendingIdResponse — the returned key is
// `id` (equal to the submitted oco_id / combo_id), NOT `oco_id`/`combo_id`.
export const submitOco = (body: Record<string, unknown>) =>
  apiFetch<PendingIdResponse>("/api/v1/oco", {
    method: "POST",
    body: JSON.stringify(body),
  });

// DELETE answers 202 `{ oco_id, status: "PENDING_CANCEL" }`; body is ignored.
export const cancelOco = (ocoId: string) =>
  apiFetch<{ oco_id: string; status: string }>(`/api/v1/oco/${ocoId}`, { method: "DELETE" });

export const submitCombo = (body: Record<string, unknown>) =>
  apiFetch<PendingIdResponse>("/api/v1/combos", {
    method: "POST",
    body: JSON.stringify(body),
  });

// DELETE answers 202 `{ combo_id, status: "PENDING_CANCEL" }`; body is ignored.
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
export const getQuoteBootstrap = () =>
  apiFetch<QuoteBootstrapResponse>("/api/v1/quotes/bootstrap");

export const getQuoteLegs = () => apiFetch<QuoteLegsResponse>("/api/v1/quotes/legs");

// 202 PendingIdResponse — the returned key is `id` (equal to the submitted
// quote_id, or the uppercased symbol when quote_id was omitted), NOT `quote_id`.
export const submitQuote = (body: Record<string, unknown>) =>
  apiFetch<PendingIdResponse>("/api/v1/quotes", {
    method: "POST",
    body: JSON.stringify(body),
  });

// Quotes are addressed by symbol for cancel (one active quote per gateway+symbol).
// DELETE answers 202 `{ symbol, status: "PENDING_CANCEL" }`; body is ignored.
export const cancelQuote = (symbol: string) =>
  apiFetch<{ symbol: string; status: string }>(
    `/api/v1/quotes/${encodeURIComponent(symbol)}`,
    { method: "DELETE" },
  );

// ── History ───────────────────────────────────────────────────────────────────
export const getHistoryOrders = (orderId: string) =>
  apiFetch<OrderHistoryResponse>(`/api/v1/history/orders/${encodeURIComponent(orderId)}`);

export const getHistoryFills = (params?: Record<string, string>) => {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  return apiFetch<HistoryFillsResponse>(`/api/v1/history/fills${qs}`);
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
  apiFetch<{ gateway_id: string; status: string }>(`/api/v1/admin/gateways/${id}/disconnect`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });

export const getAdminHalts = () => apiFetch<{ halted: HaltEntry[] }>("/api/v1/admin/halts");

// Halt one symbol. `level` (one of the symbol's configured CB levels) runs the
// real breaker activation with auto-resume; omitting it halts indefinitely.
// 202 SymbolHaltAck; a rejection is 403 ROLE_DENIED.
export const triggerCircuitBreaker = (symbol: string, level?: string) =>
  apiFetch<SymbolHaltAckResponse>("/api/v1/admin/circuit-breaker/trigger", {
    method: "POST",
    body: JSON.stringify({ symbol, ...(level ? { level } : {}) }),
  });

export const resumeCircuitBreaker = (symbol: string) =>
  apiFetch<SymbolResumeAckResponse>("/api/v1/admin/circuit-breaker/resume", {
    method: "POST",
    body: JSON.stringify({ symbol }),
  });

// ── Index administration (read-only for phase 13) ───────────────────────────
export const getAdminIndexes = () => apiFetch<AdminIndexesResponse>("/api/v1/admin/indexes");

export const getHistoryIndexIds = (date?: string) =>
  apiFetch<IndexIdsResponse>(`/api/v1/history/index-ids${date ? `?date=${encodeURIComponent(date)}` : ""}`);

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
    `/api/v1/admin/orders/${encodeURIComponent(orderId)}${limit ? `?limit=${limit}` : ""}`,
  );

// Admin kill-switch scopes (§15.8). All 202 with an engine ack; a rejection is a
// 403 ROLE_DENIED, not an `accepted: false` body.
export const adminSymbolKillSwitch = (symbol: string, reason?: string) =>
  apiFetch<AdminSymbolKillSwitchResponse>("/api/v1/admin/kill-switch/symbol", {
    method: "POST",
    body: JSON.stringify(reason ? { symbol, reason } : { symbol }),
  });

// Cancel every resting order/quote of one named gateway (does NOT disconnect it
// — that is the separate Kick action). Body key is `target_gateway_id`.
export const adminGatewayKillSwitch = (targetGatewayId: string, reason?: string) =>
  apiFetch<AdminGatewayKillSwitchResponse>("/api/v1/admin/kill-switch/gateway", {
    method: "POST",
    body: JSON.stringify(
      reason ? { target_gateway_id: targetGatewayId, reason } : { target_gateway_id: targetGatewayId },
    ),
  });

// Full-market emergency stop: cancel every resting order/quote for every gateway.
export const adminGlobalKillSwitch = (reason?: string) =>
  apiFetch<AdminGlobalKillSwitchResponse>("/api/v1/admin/kill-switch/global", {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });
