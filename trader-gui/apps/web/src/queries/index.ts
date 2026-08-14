/**
 * TanStack Query hooks (§18.2).
 * Query key conventions are documented alongside each hook.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/api/endpoints.js";
import { ApiError } from "@/api/apiFetch.js";
import { normalizeOrder } from "@/types/index.js";
import { normalizeQuoteLegRows } from "@/lib/quotes.js";
import type { ActiveQuote, DailyStat, Order, Position, QuoteLeg } from "@/types/index.js";

// ── Symbols ───────────────────────────────────────────────────────────────────
export function useSymbolsQuery() {
  return useQuery({
    queryKey: ["symbols"],
    queryFn: api.getSymbols,
    staleTime: 5 * 60_000,
  });
}

// ── Reference bundle ──────────────────────────────────────────────────────────
export function useReferenceQuery() {
  return useQuery({
    queryKey: ["reference"],
    queryFn: api.getReference,
    staleTime: 5 * 60_000,
  });
}

export function useReferenceRiskQuery() {
  return useQuery({
    queryKey: ["reference/risk"],
    queryFn: api.getReferenceRisk,
    staleTime: 5 * 60_000,
  });
}

export function useReferenceScheduleQuery() {
  return useQuery({
    queryKey: ["reference/schedule"],
    queryFn: api.getReferenceSchedule,
    staleTime: 5 * 60_000,
  });
}

// ── Session ───────────────────────────────────────────────────────────────────
export function useSessionQuery() {
  return useQuery({
    queryKey: ["session"],
    queryFn: api.getSession,
    staleTime: 10_000,
  });
}

// ── Orders ────────────────────────────────────────────────────────────────────
export function useOrdersQuery() {
  return useQuery({
    queryKey: ["orders"],
    // Both `/orders` shapes (engine OrderDisplay keyed on `id`, and the
    // timeout-fallback cache row keyed on `order_id`) are folded into the
    // canonical Order here, so consumers only ever see `order_id`.
    queryFn: () => api.getOrders().then((r) => r.orders.map(normalizeOrder)),
    staleTime: 30_000,
  });
}

export function useOrderQuery(orderId: string | null) {
  return useQuery({
    queryKey: ["orders", orderId],
    queryFn: () => api.getOrder(orderId!),
    enabled: orderId !== null,
    staleTime: 60_000,
  });
}

export function useOrderHistoryQuery(orderId: string | null) {
  return useQuery({
    queryKey: ["order-history", orderId],
    queryFn: () => api.getHistoryOrders(orderId!),
    enabled: orderId !== null,
    staleTime: 30_000,
  });
}

export function useSubmitOrderMutation() {
  return useMutation({
    mutationFn: ({ body, wait }: { body: Record<string, unknown>; wait?: "ack" }) =>
      api.submitOrder(body, wait),
  });
}

export function useCancelOrderMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.cancelOrder,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}

export function useAmendOrderMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, body }: { orderId: string; body: Record<string, unknown> }) =>
      api.amendOrder(orderId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}

export function useReplaceOrderMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ orderId, body }: { orderId: string; body: Record<string, unknown> }) =>
      api.replaceOrder(orderId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}

export function useMassCancelMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.massCancelOrders,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });
}

// ── OCO / Combo (§12.7–8, §13.3) ─────────────────────────────────────────────
export function useSubmitOcoMutation() {
  return useMutation({ mutationFn: api.submitOco });
}

export function useCancelOcoMutation() {
  return useMutation({ mutationFn: api.cancelOco });
}

export function useSubmitComboMutation() {
  return useMutation({ mutationFn: api.submitCombo });
}

export function useCancelComboMutation() {
  return useMutation({ mutationFn: api.cancelCombo });
}

// ── Positions ─────────────────────────────────────────────────────────────────
export function usePositionsQuery() {
  return useQuery({
    queryKey: ["positions"],
    queryFn: api.getPositions,
    staleTime: 30_000,
  });
}

// ── History ───────────────────────────────────────────────────────────────────
export function useHistoryFillsQuery(params?: Record<string, string>) {
  return useQuery({
    queryKey: ["history/fills", params],
    queryFn: () => api.getHistoryFills(params),
    staleTime: 60_000,
  });
}

export function useHistoryTradesQuery(symbol: string | null, limit = 50) {
  return useQuery({
    queryKey: ["history/trades", symbol, limit],
    queryFn: () => api.getHistoryTrades(symbol!, limit),
    enabled: symbol !== null,
    staleTime: 60_000,
  });
}

export function useHistoryDailyQuery(symbol?: string, date?: string) {
  return useQuery({
    queryKey: ["history/daily", symbol, date],
    queryFn: () => api.getHistoryDaily({ symbol, date }),
    staleTime: 5 * 60_000,
  });
}

/**
 * Daily candles for one symbol for the chart's 1D/All timeframes (§16.2.1).
 *
 * Omits `date`, so the gateway returns the most recent trading day it has for
 * that symbol. The keyset-paginated `/history/daily` returns one date per
 * call, so this is effectively the latest day; a multi-day backfill would
 * page backwards and is out of scope for phase 4. Disabled when `symbol` is
 * null so the query is inert on the intraday timeframes.
 */
export function useHistoryDailyChartQuery(symbol: string | null) {
  return useQuery({
    queryKey: ["history/daily", "chart", symbol],
    queryFn: () => api.getHistoryDaily({ symbol: symbol!, limit: 1000 }),
    enabled: symbol !== null,
    staleTime: 5 * 60_000,
  });
}

/** Local calendar date as YYYY-MM-DD, the venue-day approximation §10.3 uses. */
export function todayIso(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/**
 * Today's daily rollup for every symbol, keyed by symbol (§10.3).
 *
 * Supplies `open_price` for the change-% column and the day's `volume`. It is
 * polled rather than pushed — there is no daily-rollup WebSocket channel —
 * and the market-data `trade` stream tops the volume up between polls.
 *
 * A `503 STATS_DB` (no stats database yet, a normal state for a fresh
 * install) resolves to an empty map rather than an error, so the board still
 * renders live prices with the derived columns blank.
 */
export function useDailyStatsQuery() {
  const date = todayIso();
  return useQuery({
    queryKey: ["history/daily", "board", date],
    queryFn: async () => {
      try {
        const res = await api.getHistoryDaily({ date, limit: 5000 });
        if (res.has_more) {
          console.warn("[market] daily rollup truncated at 5000 rows");
        }
        const bySymbol: Record<string, DailyStat> = {};
        for (const row of res.daily) bySymbol[row.symbol] = row;
        return bySymbol;
      } catch (err) {
        if (err instanceof ApiError && err.status === 503) return {};
        throw err;
      }
    },
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

// ── Quotes (§14) ──────────────────────────────────────────────────────────────
/** Active two-sided quotes — the authoritative per-side card source (§14.1). */
export function useQuoteBootstrapQuery(enabled = true) {
  return useQuery({
    queryKey: ["quotes/bootstrap"],
    queryFn: () => api.getQuoteBootstrap().then((r) => r.quotes),
    enabled,
    staleTime: 10_000,
  });
}

/** Dual-shaped legs endpoint, normalized to display rows (§14.3). */
export function useQuoteLegsQuery(enabled = true) {
  return useQuery({
    queryKey: ["quotes/legs"],
    queryFn: () => api.getQuoteLegs().then((r) => normalizeQuoteLegRows(r.legs)),
    enabled,
    staleTime: 10_000,
  });
}

export function useSubmitQuoteMutation() {
  return useMutation({ mutationFn: api.submitQuote });
}

export function useCancelQuoteMutation() {
  return useMutation({ mutationFn: api.cancelQuote });
}

// ── Admin ─────────────────────────────────────────────────────────────────────
export function useAdminGatewaysQuery() {
  return useQuery({
    queryKey: ["admin/gateways"],
    queryFn: api.getAdminGateways,
    staleTime: 15_000,
  });
}

export function useAdminHaltsQuery() {
  return useQuery({
    queryKey: ["admin/halts"],
    queryFn: api.getAdminHalts,
    staleTime: 15_000,
  });
}

export function useAdminOrdersQuery(params?: Record<string, string>) {
  return useQuery({
    queryKey: ["admin/orders", params],
    queryFn: () => api.getAdminOrders(params),
    staleTime: 30_000,
  });
}

export function useAdminOrderDetailQuery(orderId: string | null) {
  return useQuery({
    queryKey: ["admin/order-detail", orderId],
    queryFn: () => api.getAdminOrderDetail(orderId!),
    enabled: orderId !== null,
    staleTime: 30_000,
  });
}

export function useTransitionSessionMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.transitionSession,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session"] }),
  });
}

export function useDisconnectGatewayMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) =>
      api.disconnectGateway(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin/gateways"] }),
  });
}

// Re-export some base types for convenience
export type { ActiveQuote, DailyStat, Order, Position, QuoteLeg };
