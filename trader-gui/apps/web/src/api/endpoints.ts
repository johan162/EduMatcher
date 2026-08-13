/**
 * Typed endpoint helpers wrapping apiFetch.
 * Each function maps one logical API call to a typed return value.
 */
import { apiFetch } from "./apiFetch.js";
import type {
  StatusResponse,
  Order,
  Position,
  QuoteLeg,
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

export const getReferenceRisk = () => apiFetch<Record<string, unknown>>("/api/v1/reference/risk");

export const getReferenceSchedule = () =>
  apiFetch<ReferenceScheduleDTO & { config_version: string | null }>("/api/v1/reference/schedule");

// ── Session ───────────────────────────────────────────────────────────────────
export const getSession = () => apiFetch<SessionStatusDTO>("/api/v1/session");

// ── Orders ────────────────────────────────────────────────────────────────────
export const getOrders = () => apiFetch<Order[]>("/api/v1/orders");

export const getOrder = (orderId: string) => apiFetch<Order>(`/api/v1/orders/${orderId}`);

export const submitOrder = (body: Record<string, unknown>) =>
  apiFetch<{ order_id: string }>("/api/v1/orders", {
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
export const submitOco = (body: Record<string, unknown>) =>
  apiFetch<{ oco_id: string }>("/api/v1/oco", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const cancelOco = (ocoId: string) =>
  apiFetch<void>(`/api/v1/oco/${ocoId}`, { method: "DELETE" });

export const submitCombo = (body: Record<string, unknown>) =>
  apiFetch<{ combo_id: string }>("/api/v1/combos", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const cancelCombo = (comboId: string) =>
  apiFetch<void>(`/api/v1/combos/${comboId}`, { method: "DELETE" });

// ── Positions ─────────────────────────────────────────────────────────────────
export const getPositions = () => apiFetch<Position[]>("/api/v1/positions");

// ── Quotes ────────────────────────────────────────────────────────────────────
export const getQuoteBootstrap = () =>
  apiFetch<Record<string, unknown>>("/api/v1/quotes/bootstrap");

export const getQuoteLegs = () => apiFetch<{ legs: QuoteLeg[] }>("/api/v1/quotes/legs");

export const submitQuote = (body: Record<string, unknown>) =>
  apiFetch<{ quote_id: string }>("/api/v1/quotes", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const cancelQuote = (symbol: string) =>
  apiFetch<void>(`/api/v1/quotes/${symbol}`, { method: "DELETE" });

// ── History ───────────────────────────────────────────────────────────────────
export const getHistoryOrders = (orderId: string) =>
  apiFetch<Record<string, unknown>>(`/api/v1/history/orders/${orderId}`);

export const getHistoryFills = (params?: Record<string, string>) => {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  return apiFetch<Record<string, unknown>>(`/api/v1/history/fills${qs}`);
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

export const triggerCircuitBreaker = (symbol: string, level?: string) =>
  apiFetch<{ symbol: string; status: string }>("/api/v1/admin/circuit-breaker/trigger", {
    method: "POST",
    body: JSON.stringify({ symbol, ...(level ? { level } : {}) }),
  });

export const resumeCircuitBreaker = (symbol: string) =>
  apiFetch<{ symbol: string; status: string }>("/api/v1/admin/circuit-breaker/resume", {
    method: "POST",
    body: JSON.stringify({ symbol }),
  });

export const transitionSession = (toState: string) =>
  apiFetch<{ command_id: string; requested_state: string; status: string }>(
    "/api/v1/admin/session/transition",
    {
      method: "POST",
      body: JSON.stringify({ to_state: toState }),
    },
  );

export const getAdminOrders = (params?: Record<string, string>) => {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  return apiFetch<Record<string, unknown>>(`/api/v1/admin/orders${qs}`);
};

export const getAdminOrderDetail = (orderId: string) =>
  apiFetch<Record<string, unknown>>(`/api/v1/admin/orders/${orderId}`);

export const adminSymbolKillSwitch = (symbol: string) =>
  apiFetch<Record<string, unknown>>("/api/v1/admin/kill-switch/symbol", {
    method: "POST",
    body: JSON.stringify({ symbol }),
  });
