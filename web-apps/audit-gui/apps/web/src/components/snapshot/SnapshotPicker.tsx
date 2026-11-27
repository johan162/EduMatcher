import { History, Loader2 } from "lucide-react";
import { useCollections, usePinSnapshot, useSnapshot } from "@/api/queries";
import { describeError } from "@/components/shared/QueryState";
import { receiptTime } from "@/lib/time";
import { useSnapshotStore } from "@/store/useSnapshotStore";

/**
 * The top bar's evidence selector: a configured collection, by id (the
 * browser never names a path), pinned as a snapshot when chosen. A
 * collection that cannot be read is listed but cannot be chosen, with its
 * reason. Failures are shown as errors, never as an empty list.
 */
export function SnapshotPicker() {
  const collections = useCollections();
  const pin = usePinSnapshot();
  const collectionId = useSnapshotStore((s) => s.collectionId);
  const snapshotId = useSnapshotStore((s) => s.snapshotId);

  return (
    <div className="flex min-w-0 items-center gap-2 text-xs">
      <label htmlFor="collection" className="text-fg-dim">
        Evidence collection
      </label>
      <select
        id="collection"
        value={pin.isPending ? (pin.variables ?? "") : (collectionId ?? "")}
        disabled={pin.isPending || !collections.data}
        onChange={(e) => e.target.value && pin.mutate(e.target.value)}
        className="rounded border border-line bg-raised px-1.5 py-0.5 font-mono"
      >
        <option value="" disabled>
          Choose…
        </option>
        {collections.data?.collections.map((c) => (
          <option key={c.id} value={c.id} disabled={!c.available}>
            {c.available ? c.id : `${c.id} (unavailable: ${c.reason ?? "unknown"})`}
          </option>
        ))}
      </select>
      {pin.isPending && <Loader2 size={14} className="animate-spin text-fg-dim" aria-label="Pinning" />}
      {collections.isError && (
        <span role="alert" className="text-ask">
          {describeError(collections.error)}
        </span>
      )}
      {pin.isError && (
        <span role="alert" className="text-ask">
          {describeError(pin.error)}
        </span>
      )}
      {snapshotId && !pin.isPending && !pin.isError && <SnapshotLabel id={snapshotId} />}
    </div>
  );
}

/**
 * Always "historical snapshot", never a live-looking "connected": the
 * snapshot's id, how far its records reach and when it was pinned (design
 * §9.1).
 */
function SnapshotLabel({ id }: { id: string }) {
  const snapshot = useSnapshot(id);
  const last = snapshot.data?.last_ts;
  const pinned = snapshot.data?.created_at;
  return (
    <span data-testid="snapshot-label" className="flex min-w-0 items-center gap-1.5 truncate text-fg-dim" title={id}>
      <History size={14} aria-hidden="true" className="shrink-0 text-halt" />
      <span className="font-semibold text-halt">Historical snapshot</span>
      <span className="font-mono">{id}</span>
      {last && <span>· records to {receiptTime(last)}</span>}
      {pinned && <span>· pinned {receiptTime(pinned)}</span>}
    </span>
  );
}
