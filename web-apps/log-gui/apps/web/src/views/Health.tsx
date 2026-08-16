/** Server Health (design §13): four independently-failing components, separated. */

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { Panel } from "../components/Panel.js";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b border-border/50 py-1 text-sm last:border-0">
      <span className="text-fg-subtle">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

export function HealthView() {
  const serverState = useLiveStore((s) => s.serverState);
  const { data: summary } = useQuery({
    queryKey: ["stats", "summary"],
    queryFn: api.statsSummary,
    refetchInterval: 30_000,
  });
  const { data: bridgeStatus } = useQuery({
    queryKey: ["bridge", "status"],
    queryFn: api.bridgeStatus,
    refetchInterval: 10_000,
  });

  return (
    <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2">
      <Panel title="pm-log-srv">
        <Row label="status" value={serverState?.state === "UP" ? "● UP" : "○ unknown"} />
        <Row label="server" value={serverState?.server ?? "—"} />
        <Row label="events (lifetime)" value={summary?.server.total_log_events ?? "—"} />
        <Row label="connections (lifetime)" value={summary?.server.total_connections ?? "—"} />
        <Row label="truncated" value={summary?.server.total_truncated ?? "—"} />
        <Row label="errors sent" value={summary?.server.total_errors_sent ?? "—"} />
      </Panel>

      <Panel title="LALF-PS">
        <Row label="state" value={serverState?.state ?? "unknown"} />
        <Row label="subscribers" value={serverState?.subscribers ?? "—"} />
        <Row label="active backfills" value={serverState?.activeBackfills ?? "—"} />
        <Row label="last seq" value={serverState?.lastSeq ?? "—"} />
        <Row label="inbox dropped" value={serverState?.inboxDropped ?? 0} />
        <Row label="default lease" value={serverState ? `${serverState.defaultLeaseSec}s` : "—"} />
      </Panel>

      <Panel title="log.db">
        <Row label="path" value={summary?.dbPath ?? "—"} />
        <Row
          label="size"
          value={summary ? `${(summary.dbSizeBytes / 1_000_000).toFixed(1)} MB` : "—"}
        />
        <Row label="rows" value={summary?.totalRows ?? "—"} />
        <Row label="oldest row" value={summary?.oldestClientTs ?? "—"} />
      </Panel>

      <Panel title="Bridge">
        <Row label="ws clients" value={bridgeStatus?.wsClients ?? "—"} />
        <Row label="fingerprints indexed" value={bridgeStatus?.fingerprintsIndexed ?? "—"} />
        <Row label="acks stored" value={bridgeStatus?.acksStored ?? "—"} />
        <Row label="sub id" value={bridgeStatus?.subId ?? "—"} />
        <Row
          label="log.db reachable"
          value={bridgeStatus?.logDb.ok ? "yes" : `no — ${bridgeStatus?.logDb.detail ?? ""}`}
        />
      </Panel>
    </div>
  );
}
