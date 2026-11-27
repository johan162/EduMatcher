/**
 * Every read of the audit GUI, as TanStack Query hooks. A pinned snapshot
 * never changes, so its reads are cached for the session (`staleTime:
 * Infinity`); only the collection list is re-asked for.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/apiFetch";
import { Collections, EventPage, FindingPage, Heatmap, Lifelines, Snapshot, Story, type SnapshotT } from "@/api/schemas";
import { toTrade, type Trade } from "@/lib/flow";
import { useSnapshotStore } from "@/store/useSnapshotStore";

const V1 = "/api/v1/audit";

export const keys = {
  collections: ["audit", "collections"] as const,
  snapshot: (id: string) => ["audit", "snapshot", id] as const,
  gaps: (id: string) => ["audit", "gaps", id] as const,
  heatmap: (id: string, symbol: string, from: string | null, to: string | null) =>
    ["audit", "heatmap", id, symbol, from, to] as const,
  lifelines: (id: string, symbol: string, from: string | null, to: string | null) =>
    ["audit", "lifelines", id, symbol, from, to] as const,
  trades: (id: string, symbol: string) => ["audit", "trades", id, symbol] as const,
  story: (id: string, order: string, run: number | null) => ["audit", "story", id, order, run] as const,
  orderEvents: (id: string, order: string) => ["audit", "order-events", id, order] as const,
};

export function useCollections() {
  return useQuery({
    queryKey: keys.collections,
    queryFn: ({ signal }) => apiFetch(`${V1}/collections`, Collections, { signal }),
  });
}

/** Pin a collection (`POST /snapshots`) and make it the current snapshot. */
export function usePinSnapshot() {
  const client = useQueryClient();
  const select = useSnapshotStore((s) => s.select);
  return useMutation({
    mutationFn: (collectionId: string) =>
      apiFetch(`${V1}/snapshots`, Snapshot, { post: { collection_id: collectionId } }),
    onSuccess: (snapshot: SnapshotT) => {
      client.setQueryData(keys.snapshot(snapshot.snapshot_id), snapshot);
      select(snapshot.collection_id, snapshot.snapshot_id);
    },
  });
}

export function useSnapshot(id: string) {
  return useQuery({
    queryKey: keys.snapshot(id),
    queryFn: ({ signal }) =>
      apiFetch(`${V1}/snapshots/${encodeURIComponent(id)}`, Snapshot, { signal }),
    staleTime: Infinity,
  });
}

/** The most `ESEQ_GAP` findings one page holds (the API's maximum). */
export const GAP_PAGE = 1000;

/**
 * Recorder gaps: the replay's own `ESEQ_GAP` findings (records lost from
 * the engine's stream), counted from one page. `lowerBound` is true when
 * more follow.
 */
export function useGapCount(id: string) {
  return useQuery({
    queryKey: keys.gaps(id),
    queryFn: async ({ signal }) => {
      const query = new URLSearchParams({ snapshot_id: id, code: "ESEQ_GAP", limit: String(GAP_PAGE) });
      const page = await apiFetch(`${V1}/findings?${query}`, FindingPage, { signal });
      return { count: page.count, lowerBound: page.has_more };
    },
    staleTime: Infinity,
  });
}

/** Heatmap bins asked for: about one per 3 px of a wide canvas. */
export const HEATMAP_BINS = 300;

function windowQuery(id: string, from: string | null, to: string | null, extra: Record<string, string> = {}) {
  const q = new URLSearchParams({ snapshot_id: id, ...extra });
  if (from) q.set("from", from);
  if (to) q.set("to", to);
  return q;
}

export function useHeatmap(id: string, symbol: string, from: string | null, to: string | null) {
  return useQuery({
    queryKey: keys.heatmap(id, symbol, from, to),
    queryFn: ({ signal }) =>
      apiFetch(
        `${V1}/market/${encodeURIComponent(symbol)}/heatmap?${windowQuery(id, from, to, { bins: String(HEATMAP_BINS) })}`,
        Heatmap,
        { signal },
      ),
    staleTime: Infinity,
  });
}

export function useLifelines(id: string, symbol: string, from: string | null, to: string | null) {
  return useQuery({
    queryKey: keys.lifelines(id, symbol, from, to),
    queryFn: ({ signal }) =>
      apiFetch(`${V1}/market/${encodeURIComponent(symbol)}/lifelines?${windowQuery(id, from, to)}`, Lifelines, { signal }),
    staleTime: Infinity,
  });
}

/** Pages of trades read at most (1,000 each); past that the layer says so. */
export const TRADE_PAGES = 5;

/**
 * The symbol's trades (`/events?topic=trade.executed`), for the trades
 * layer and the flow strip. The snapshot's, not the window's: the route has
 * no time filter, so the canvas clips them.
 */
export function useTrades(id: string, symbol: string) {
  return useQuery({
    queryKey: keys.trades(id, symbol),
    queryFn: async ({ signal }) => {
      const trades: Trade[] = [];
      let after: string | null = null;
      for (let page = 0; page < TRADE_PAGES; page++) {
        const q = new URLSearchParams({ snapshot_id: id, topic: "trade.executed", symbol, limit: "1000" });
        if (after) q.set("after", after);
        const body = await apiFetch(`${V1}/events?${q}`, EventPage, { signal });
        for (const e of body.events) {
          const t = toTrade(e);
          if (t) trades.push(t);
        }
        after = body.next_cursor;
        if (!body.has_more) return { trades, truncated: false };
      }
      return { trades, truncated: true };
    },
    staleTime: Infinity,
  });
}

export function useOrderStory(id: string, order: string, run: number | null) {
  return useQuery({
    queryKey: keys.story(id, order, run),
    queryFn: ({ signal }) => {
      const q = new URLSearchParams({ snapshot_id: id });
      if (run !== null) q.set("run_id", String(run));
      return apiFetch(`${V1}/stories/order/${encodeURIComponent(order)}?${q}`, Story, { signal });
    },
    staleTime: Infinity,
  });
}

/** The order's raw records (one bounded page). */
export function useOrderEvents(id: string, order: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.orderEvents(id, order),
    queryFn: ({ signal }) =>
      apiFetch(`${V1}/events?${new URLSearchParams({ snapshot_id: id, order_id: order, limit: "1000" })}`, EventPage, {
        signal,
      }),
    staleTime: Infinity,
    enabled,
  });
}
