/**
 * TanStack Query hooks (§18.2).
 * Query key conventions are documented alongside each hook.
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "@/api/endpoints.js";
import type { Order, Position, QuoteLeg } from "@/types/index.js";

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
    queryFn: api.getOrders,
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
  return useMutation({ mutationFn: api.submitOrder });
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

export function useHistoryTradesQuery(symbol: string | null) {
  return useQuery({
    queryKey: ["history/trades", symbol],
    queryFn: () => api.getHistoryTrades(symbol!),
    enabled: symbol !== null,
    staleTime: 60_000,
  });
}

export function useHistoryDailyQuery(symbol?: string, date?: string) {
  return useQuery({
    queryKey: ["history/daily", symbol, date],
    queryFn: () => api.getHistoryDaily(symbol, date),
    staleTime: 5 * 60_000,
  });
}

// ── Quotes ────────────────────────────────────────────────────────────────────
export function useQuoteBootstrapQuery() {
  return useQuery({
    queryKey: ["quotes/bootstrap"],
    queryFn: api.getQuoteBootstrap,
    staleTime: 10_000,
  });
}

export function useQuoteLegsQuery() {
  return useQuery({
    queryKey: ["quotes/legs"],
    queryFn: () =>
      api.getQuoteLegs().then((r) => r.legs as QuoteLeg[]),
    staleTime: 10_000,
  });
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
export type { Order, Position, QuoteLeg };
