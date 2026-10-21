/** Server Health (design §13): four independently-failing components, separated. */

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";
import { useLiveStore } from "../store/useLiveStore.js";
import { InfoTip } from "../components/InfoTip.js";
import { Panel } from "../components/Panel.js";

function Row({
  label,
  help,
  value,
}: {
  label: string;
  help: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex justify-between border-b border-border/50 py-1 text-sm last:border-0">
      <span className="flex items-center gap-1 text-fg-subtle">
        {label}
        <InfoTip label={label}>{help}</InfoTip>
      </span>
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
        <Row
          label="status"
          help="Whether pm-log-srv is alive. UP: its heartbeat arrives. DOWN: it announced a shutdown or the heartbeat stopped. Unknown: this browser has lost contact with the bridge, so nothing can be said."
          value={
            serverState
              ? serverState.state === "UP"
                ? "● UP"
                : "○ DOWN"
              : "○ unknown"
          }
        />
        <Row
          label="server"
          help="The name the log server announces for itself in its heartbeat."
          value={serverState?.server ?? "—"}
        />
        <Row
          label="events (lifetime)"
          help="Log events the server has accepted since it was first started, including those kept in older log.db files."
          value={summary?.server.total_log_events ?? "—"}
        />
        <Row
          label="connections (lifetime)"
          help="Process connections the server has accepted since it first started. Every process opens a probe connection and a logging connection, so this is about twice the number of process starts."
          value={summary?.server.total_connections ?? "—"}
        />
        <Row
          label="truncated"
          help="Events whose message was longer than the server's limit and was cut. A large number means some process logs very long lines."
          value={summary?.server.total_truncated ?? "—"}
        />
        <Row
          label="errors sent"
          help="Error replies the server has sent back to clients, for example for a malformed event. These point at a buggy or incompatible sender, not at the exchange itself."
          value={summary?.server.total_errors_sent ?? "—"}
        />
      </Panel>

      <Panel title="LALF-PS">
        <Row
          label="state"
          help="Whether the LALF-PS publish/subscribe channel (the live feed this bridge subscribes to) is running. It follows the log server."
          value={serverState?.state ?? "unknown"}
        />
        <Row
          label="subscribers"
          help="How many clients hold a live subscription to the log feed right now. The bridge is one; every browser tab shares the bridge's single subscription."
          value={serverState?.subscribers ?? "—"}
        />
        <Row
          label="active backfills"
          help="Subscribers that are currently being sent history they missed, before they switch to the live feed."
          value={serverState?.activeBackfills ?? "—"}
        />
        <Row
          label="last seq"
          help="The sequence number of the newest event the server has stored. Every event gets the next number, so gaps between this and what a client has seen mean missed events."
          value={serverState?.lastSeq ?? "—"}
        />
        <Row
          label="inbox dropped"
          help="Events the server discarded because its inbox queue was full, which only happens under overload. Should be 0; any other value means log lines were lost."
          value={serverState?.inboxDropped ?? 0}
        />
        <Row
          label="default lease"
          help="How long a subscription lives without being renewed. The bridge renews well before it ends; if renewal stops the server drops the subscriber."
          value={serverState ? `${serverState.defaultLeaseSec}s` : "—"}
        />
      </Panel>

      <Panel title="log.db">
        <Row
          label="path"
          help="Where the SQLite log database lives on the machine running the bridge."
          value={summary?.dbPath ?? "—"}
        />
        <Row
          label="size"
          help="The size of the log database file on disk. It grows with every stored event."
          value={
            summary ? `${(summary.dbSizeBytes / 1_000_000).toFixed(1)} MB` : "—"
          }
        />
        <Row
          label="rows"
          help="The number of events currently stored in log.db and available to search."
          value={summary?.totalRows ?? "—"}
        />
        <Row
          label="oldest row"
          help="Client timestamp of the oldest stored event: how far back the history reaches."
          value={summary?.oldestClientTs ?? "—"}
        />
      </Panel>

      <Panel title="Bridge">
        <Row
          label="ws clients"
          help="Browser tabs connected to the bridge over WebSocket right now."
          value={bridgeStatus?.wsClients ?? "—"}
        />
        <Row
          label="fingerprints indexed"
          help="Distinct problem signatures the bridge tracks. Similar errors (same process, same message shape) share one fingerprint, which becomes one issue in Alerts."
          value={bridgeStatus?.fingerprintsIndexed ?? "—"}
        />
        <Row
          label="acks stored"
          help="Issues that someone has acknowledged in Alerts. Acknowledgements are kept across bridge restarts."
          value={bridgeStatus?.acksStored ?? "—"}
        />
        <Row
          label="sub id"
          help="The identifier the bridge uses for its subscription to the log feed. It shows up in the server's subscriber list."
          value={bridgeStatus?.subId ?? "—"}
        />
        <Row
          label="log.db reachable"
          help="Whether the bridge can read the log database. If not, history, search and statistics are unavailable but the live feed still works."
          value={
            bridgeStatus?.logDb.ok
              ? "yes"
              : `no — ${bridgeStatus?.logDb.detail ?? ""}`
          }
        />
      </Panel>
    </div>
  );
}
