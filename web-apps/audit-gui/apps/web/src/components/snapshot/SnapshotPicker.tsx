import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { History, Loader2 } from "lucide-react";
import { keys, useCollections, useJob, usePinSnapshot, useRetryPrepare, useSnapshot } from "@/api/queries";
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
  const [preparing, setPreparing] = useState<Preparing | null>(null);

  return (
    <div className="flex min-w-0 items-center gap-2 text-xs">
      <label htmlFor="collection" className="text-fg-dim">
        Evidence collection
      </label>
      <select
        id="collection"
        value={pin.isPending ? (pin.variables ?? "") : (collectionId ?? "")}
        disabled={pin.isPending || !collections.data}
        onChange={(e) => {
          if (!e.target.value) return;
          setPreparing(null);
          pin.mutate(e.target.value, {
            onSuccess: (snap) => {
              if (snap.generation === null && snap.prepare) {
                setPreparing({ snapshotId: snap.snapshot_id, collectionId: snap.collection_id, jobId: snap.prepare.job_id });
              }
            },
          });
        }}
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
      {preparing && <PrepareStatus preparing={preparing} onRetry={setPreparing} onDone={() => setPreparing(null)} />}
      {snapshotId && !preparing && !pin.isPending && !pin.isError && <SnapshotLabel id={snapshotId} />}
    </div>
  );
}

interface Preparing {
  snapshotId: string;
  collectionId: string;
  jobId: string;
}

/**
 * A snapshot whose read models are being built (its `prepare` job): stage
 * and measured progress while it runs; the snapshot opens when it succeeds;
 * a job that ended otherwise says why and can be queued again.
 */
function PrepareStatus({
  preparing,
  onRetry,
  onDone,
}: {
  preparing: Preparing;
  onRetry: (next: Preparing) => void;
  onDone: () => void;
}) {
  const job = useJob(preparing.jobId);
  const retry = useRetryPrepare();
  const client = useQueryClient();
  const select = useSnapshotStore((s) => s.select);
  const state = job.data?.state;

  useEffect(() => {
    if (state !== "succeeded") return;
    void client.invalidateQueries({ queryKey: keys.snapshot(preparing.snapshotId) });
    select(preparing.collectionId, preparing.snapshotId);
    onDone();
  }, [state, client, select, preparing, onDone]);

  if (job.isError) {
    return (
      <span role="alert" className="text-ask">
        {describeError(job.error)}
      </span>
    );
  }
  const data = job.data;
  if (data && (data.state === "failed" || data.state === "cancelled" || data.state === "unavailable")) {
    return (
      <span role="alert" className="flex items-center gap-2 text-ask">
        Preparing the snapshot {data.state}: {data.reason ?? "no reason given"}
        {data.detail ? ` (${data.detail})` : ""}
        <button
          type="button"
          onClick={() =>
            retry.mutate(preparing.snapshotId, {
              onSuccess: (next) => onRetry({ ...preparing, jobId: next.job_id }),
            })
          }
          className="rounded bg-elevated px-2 py-0.5 text-fg"
        >
          Retry
        </button>
      </span>
    );
  }
  const progress = data?.progress;
  return (
    <span data-testid="preparing" role="status" className="flex items-center gap-1.5 text-fg-dim">
      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
      Preparing snapshot: {data?.stage ?? data?.state ?? "queued"}
      {progress && ` ${progress.done.toLocaleString("en-US")} / ${progress.total.toLocaleString("en-US")}`}
    </span>
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
