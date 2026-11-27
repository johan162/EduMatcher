import { EmptyState } from "@/components/shared/EmptyState";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import type { Workspace } from "@/lib/workspaces";

/** A workspace this release does not ship: it says so, rather than showing an empty screen. */
export function NotInRelease({ workspace }: { workspace: Workspace }) {
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">{workspace.name}</h1>
      <p className="text-sm text-fg-dim">{workspace.question}</p>
      <p className="text-sm">Not in this release.</p>
    </div>
  );
}

/** The Overview: in this release, the evidence banner above it and a prompt to pin a snapshot. */
export function OverviewPage() {
  const snapshotId = useSnapshotStore((s) => s.snapshotId);
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold">Overview</h1>
      {snapshotId ? (
        <p className="text-sm text-fg-dim">The Overview's tiles and timeline are not in this release.</p>
      ) : (
        <EmptyState
          title="No snapshot pinned"
          hint="Choose an evidence collection in the top bar: it is pinned as a snapshot, and every workspace reads that snapshot."
        />
      )}
    </div>
  );
}
