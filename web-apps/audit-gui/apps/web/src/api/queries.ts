/**
 * Every read of the audit GUI, as TanStack Query hooks. A pinned snapshot
 * never changes, so its reads are cached for the session (`staleTime:
 * Infinity`); only the collection list is re-asked for.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/apiFetch";
import { Collections, FindingPage, Snapshot, type SnapshotT } from "@/api/schemas";
import { useSnapshotStore } from "@/store/useSnapshotStore";

const V1 = "/api/v1/audit";

export const keys = {
  collections: ["audit", "collections"] as const,
  snapshot: (id: string) => ["audit", "snapshot", id] as const,
  gaps: (id: string) => ["audit", "gaps", id] as const,
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
