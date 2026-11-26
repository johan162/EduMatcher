/**
 * TanStack Query hooks for every clearing read, and the request policy.
 *
 * Request discipline (workplan CG5-CG9) lives here, in one place:
 *
 * - Current state (positions, participants, summary) refreshes every
 *   `POLL_CURRENT_MS` = 5 s: pm-clearing commits fills in batches at most that
 *   often, so polling faster shows nothing new. These are small aggregate
 *   tables.
 * - Health pings pm-clearing's receive loop on every call; it refreshes every
 *   `POLL_HEALTH_MS` = 30 s, not at the 5 s cadence.
 * - History (daily rows, close snapshots), trades, events, sessions and EOD
 *   data are never polled. They are fetched when a screen or filter asks and
 *   cached; `useHistoryRevalidation` refreshes daily/close data only when the
 *   current-state freshness actually moves.
 * - Reconciliation scans raw trades: it runs only when the user presses Run,
 *   and never refetches by itself.
 *
 * Every key starts with `["clearing", caller]`, so one tab never shows data
 * cached for another login, and includes the request's filters.
 *
 * A participant's hooks are called without `gateway`: the server scopes the
 * request to the caller. Only ADMIN screens pass one.
 */
import { useEffect, useRef } from "react";
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import type { z } from "zod";
import { apiFetch } from "@/api/apiFetch";
import * as S from "@/api/schemas";
import { useAuthStore } from "@/store/useAuthStore";
import { useVenueTimeZoneStore } from "@/store/useVenueTimeZoneStore";

export const POLL_CURRENT_MS = 5_000;
export const POLL_HEALTH_MS = 30_000;
/** Cached reads (history, EOD, events) count as fresh for this long. */
export const CACHE_MS = 60_000;
/** Page size of the trade audit; the API allows up to 5000. */
export const TRADE_PAGE_SIZE = 200;

export type Params = Record<string, string | number | boolean | null | undefined>;

/** `path?a=1&b=x`, leaving out empty filters and `false` flags. */
export function withQuery(path: string, params: Params = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}

function useCaller(): string {
  return useAuthStore((s) => s.gatewayId) ?? "";
}

export function clearingKey(caller: string, route: string, params: Params = {}): QueryKey {
  return ["clearing", caller, route, params];
}

interface ReadOptions {
  refetchInterval?: number | false;
  staleTime?: number;
  enabled?: boolean;
}

function useRead<T extends z.ZodType>(route: string, schema: T, params: Params, options: ReadOptions) {
  const caller = useCaller();
  return useQuery({
    queryKey: clearingKey(caller, route, params),
    queryFn: ({ signal }) => apiFetch(withQuery(route, params), schema, { signal }),
    refetchInterval: options.refetchInterval ?? false,
    staleTime: options.staleTime ?? 0,
    enabled: options.enabled ?? true,
    // No placeholderData: a new filter (another gateway, say) must show a
    // skeleton, never the previous filter's rows under the new heading.
  });
}

const current: ReadOptions = { refetchInterval: POLL_CURRENT_MS };
const cached: ReadOptions = { staleTime: CACHE_MS };

// ── Current state (polled) ─────────────────────────────────────────────────

export const usePositions = (params: Params = {}) =>
  useRead("/api/v1/clearing/positions", S.Positions, params, current);

/**
 * The venue's largest positions, as the server ranks them: gross notional
 * in display currency (each row's own precision), all gateways (ADMIN).
 */
export const useLargestPositions = () =>
  useRead("/api/v1/clearing/exposure", S.Exposure, { limit: 5, sort: "gross_notional" }, current);

/**
 * The session phase, refreshed at the health cadence (30 s) while a screen
 * shows it -- the same request the shell makes once for the timezone.
 */
export const useSession = () =>
  useRead("/api/v1/session", S.SessionInfo, {}, { refetchInterval: POLL_HEALTH_MS });

export const useParticipants = () =>
  useRead("/api/v1/clearing/participants", S.Participants, {}, current);

export const useSummary = () => useRead("/api/v1/clearing/summary", S.Summary, {}, current);

export const useHealth = () =>
  useRead("/api/v1/clearing/health", S.Health, {}, { refetchInterval: POLL_HEALTH_MS });

export function useParticipant(gatewayId: string) {
  const route = `/api/v1/clearing/participants/${encodeURIComponent(gatewayId)}`;
  return useRead(route, S.ParticipantDetail, {}, current);
}

// ── History and evidence (cached, filter-driven) ───────────────────────────

export const useDaily = (params: Params) =>
  useRead("/api/v1/clearing/daily", S.Daily, params, cached);

export const useCloseSnapshots = (params: Params) =>
  useRead("/api/v1/clearing/close-snapshots", S.CloseSnapshots, params, cached);

export const useClearingSymbols = (params: Params) =>
  useRead("/api/v1/clearing/symbols", S.ClearingSymbols, params, cached);

export const useSessionEvents = (params: Params) =>
  useRead("/api/v1/clearing/session-events", S.SessionEvents, params, cached);

export const useGatewaySessions = (params: Params) =>
  useRead("/api/v1/clearing/gateway-sessions", S.GatewaySessions, params, cached);

export const useSettlements = (params: Params) =>
  useRead("/api/v1/clearing/settlements", S.Settlements, params, cached);

export const useBalances = (params: Params) =>
  useRead("/api/v1/clearing/balances", S.Balances, params, cached);

/**
 * The venue's session timezone, from `GET /api/v1/session`, into
 * `useVenueTimeZoneStore` for every time on screen. Fetched once per login:
 * the zone is configuration and does not change while the venue runs. The
 * route asks the engine and can fail; the store then stays `null` and times
 * stay in labelled UTC.
 */
export function useVenueTimeZone(): void {
  const session = useRead("/api/v1/session", S.SessionInfo, {}, { staleTime: Number.POSITIVE_INFINITY });
  const zone = session.data?.session_timezone ?? null;
  const setTimeZone = useVenueTimeZoneStore((s) => s.setTimeZone);
  useEffect(() => setTimeZone(zone), [zone, setTimeZone]);
}

// ── Filter lists (CG22): fetched once, never polled ─────────────────────────

const NO_OPTIONS: string[] = [];

/** Every symbol of the venue, for a Symbol filter (any key may read it). */
export function useSymbolOptions(): string[] {
  const q = useRead("/api/v1/reference/symbols", S.ReferenceSymbolList, {}, { staleTime: Number.POSITIVE_INFINITY });
  return q.data ? q.data.symbols.map((s) => s.symbol).sort() : NO_OPTIONS;
}

/**
 * Every participant gateway, for a Gateway filter (ADMIN). The same request
 * as the Participants list, but cached rather than polled when only a filter
 * asks for it.
 */
export function useGatewayOptions(enabled = true): string[] {
  const q = useRead("/api/v1/clearing/participants", S.Participants, {}, { ...cached, enabled });
  return q.data ? q.data.participants.map((p) => p.gateway_id).sort() : NO_OPTIONS;
}

/**
 * Every settlement account, EXCHANGE included, for the EOD Account filter
 * (ADMIN): the venue balances reply the EOD screen already shows.
 */
export function useAccountOptions(enabled = true): string[] {
  const q = useRead("/api/v1/clearing/balances", S.Balances, {}, { ...cached, enabled });
  return q.data ? q.data.balances.map((b) => b.account).sort() : NO_OPTIONS;
}

/** The caller's own symbol settings, including market-maker obligations. */
export const useSymbolSettings = () =>
  useRead("/api/v1/symbols", S.SymbolList, {}, { staleTime: Number.POSITIVE_INFINITY });

/**
 * Raw-vs-summary reconciliation for an explicit range. `params` is `null`
 * until the user runs it; it never refetches by itself (no interval, no
 * refetch on focus), because each run scans the retained raw trades.
 */
export function useReconciliation(params: Params | null) {
  const caller = useCaller();
  return useQuery({
    queryKey: clearingKey(caller, "/api/v1/clearing/reconciliation", params ?? {}),
    queryFn: ({ signal }) =>
      apiFetch(withQuery("/api/v1/clearing/reconciliation", params ?? {}), S.Reconciliation, {
        signal,
      }),
    enabled: params !== null,
    staleTime: Number.POSITIVE_INFINITY,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

/** The retained-trade audit, newest first, one page per `fetchNextPage`. */
export function useTrades(params: Params) {
  const caller = useCaller();
  const route = "/api/v1/clearing/trades";
  return useInfiniteQuery({
    queryKey: clearingKey(caller, route, params),
    queryFn: ({ pageParam, signal }) =>
      apiFetch(withQuery(route, { ...params, limit: TRADE_PAGE_SIZE, after: pageParam }), S.TradePage, {
        signal,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    staleTime: CACHE_MS,
  });
}

/**
 * Refresh cached daily rows and close snapshots when the ledger moves.
 *
 * Polls the (small, current) positions of `gateway` -- the caller's own when
 * omitted -- and when the newest position write changes, marks this caller's
 * daily and close-snapshot queries stale. History is thus never fetched at
 * the polling cadence, only after clearing actually committed something.
 * Returns that newest write, for a freshness line.
 */
export function useHistoryRevalidation(gateway?: string): number | null {
  const client = useQueryClient();
  const caller = useCaller();
  const positions = usePositions(gateway ? { gateway } : {});
  const newest =
    positions.data?.positions.reduce<number | null>(
      (max, row) => (max === null || row.updated_ts_ns > max ? row.updated_ts_ns : max),
      null,
    ) ?? null;
  const seen = useRef<number | null>(null);
  useEffect(() => {
    if (newest === null) return;
    if (seen.current !== null && newest !== seen.current) {
      for (const route of ["/api/v1/clearing/daily", "/api/v1/clearing/close-snapshots"]) {
        void client.invalidateQueries({ queryKey: ["clearing", caller, route] });
      }
    }
    seen.current = newest;
  }, [newest, client, caller]);
  return newest;
}
