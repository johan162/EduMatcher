import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { useMonitorStore } from "@/store/useMonitorStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { MonitorKindBadge } from "@/components/admin/MonitorKindBadge.js";
import { AdminOrderDetailModal } from "@/components/admin/AdminOrderDetailModal.js";
import { monitorEventsToCsv } from "@/lib/monitorEvents.js";
import type { MonitorEventKind } from "@/types/index.js";

const FILTER_KINDS: (MonitorEventKind | "ALL")[] = [
  "ALL",
  "ACK",
  "FILL",
  "CANCEL",
  "AMEND",
  "REJECT",
  "EXPIRE",
  "SESSION",
  "CB",
  "ADMIN",
];

function timeLabel(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function downloadCsv(csv: string, filename: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const inputCls =
  "bg-raised border border-line rounded px-2 py-1 text-xs focus:outline-none focus:border-[#3a3a60]";

/**
 * Audit / Monitor Log Viewer (§15.9) — the ADMIN live tail of cross-gateway
 * activity from the `/admin/monitor` socket (via useMonitorStore). Filter by
 * kind/symbol/gateway, export the visible rows to CSV, and drill into an order's
 * full lifecycle from the audit trail. On reconnect a GAP row marks the boundary
 * the feed could not replay.
 */
export function AdminMonitorPage() {
  const events = useMonitorStore((s) => s.events);
  const snapshotAt = useMonitorStore((s) => s.snapshotAt);
  const health = useConnectionHealth();

  const [kind, setKind] = useState<MonitorEventKind | "ALL">("ALL");
  const [symbol, setSymbol] = useState("");
  const [gateway, setGateway] = useState("");
  const [detailId, setDetailId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const sym = symbol.trim().toUpperCase();
    const gw = gateway.trim().toUpperCase();
    return events.filter((e) => {
      if (kind !== "ALL" && e.kind !== kind && e.kind !== "GAP") return false;
      if (sym && !(e.symbol ?? "").toUpperCase().includes(sym)) return false;
      if (gw && !(e.gateway_id ?? "").toUpperCase().includes(gw)) return false;
      return true;
    });
  }, [events, kind, symbol, gateway]);

  return (
    <div className="flex flex-col gap-3 p-4 h-full">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-fg">Monitor Log</h1>
        <span className="text-[11px] text-fg-faint">
          {filtered.length} / {events.length} events
          {snapshotAt ? ` · reconciled ${new Date(snapshotAt).toLocaleTimeString("en-GB", { hour12: false })}` : ""}
        </span>
        {health.adminMonitor && health.adminMonitor !== "connected" && (
          <span className="text-[11px] text-amber-400">Feed {health.adminMonitor}</span>
        )}
        <button
          type="button"
          onClick={() => downloadCsv(monitorEventsToCsv(filtered), "monitor-log.csv")}
          disabled={filtered.length === 0}
          className="ml-auto flex items-center gap-1 rounded border border-line px-2 py-1 text-[11px] text-fg-dim hover:text-fg disabled:opacity-40"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {/* Filter bar (§15.9) */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Event Type</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as MonitorEventKind | "ALL")}
            aria-label="Filter event type"
            className={inputCls}
          >
            {FILTER_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Symbol</span>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            aria-label="Filter symbol"
            placeholder="All"
            className={`${inputCls} font-mono w-28`}
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] text-fg-faint">Gateway</span>
          <input
            value={gateway}
            onChange={(e) => setGateway(e.target.value.toUpperCase())}
            aria-label="Filter gateway"
            placeholder="All"
            className={`${inputCls} font-mono w-28`}
          />
        </label>
      </div>

      <div className="flex-1 overflow-auto rounded border border-line">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-panel text-fg-dim">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium">Time</th>
              <th className="px-2 py-1.5 text-right font-medium">Seq</th>
              <th className="px-2 py-1.5 text-left font-medium">Type</th>
              <th className="px-2 py-1.5 text-left font-medium">Order / Gateway</th>
              <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
              <th className="px-2 py-1.5 text-left font-medium">Details</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => {
              const linkable = Boolean(e.order_id);
              return (
                <tr
                  key={e.id}
                  onClick={linkable ? () => setDetailId(e.order_id!) : undefined}
                  className={`border-b border-raised ${
                    e.kind === "GAP" ? "bg-red-950/40" : linkable ? "cursor-pointer hover:bg-raised" : ""
                  }`}
                >
                  <td className="px-2 py-1 font-mono text-fg-dim whitespace-nowrap">{timeLabel(e.ts)}</td>
                  <td className="px-2 py-1 text-right font-mono text-fg-faint">{e.seq ?? "—"}</td>
                  <td className="px-2 py-1">
                    <MonitorKindBadge kind={e.kind} />
                  </td>
                  <td className="px-2 py-1 font-mono text-fg-dim">
                    {e.order_id ? (
                      <span className="text-sky-400 hover:underline">{e.order_id.slice(0, 12)}</span>
                    ) : (
                      (e.gateway_id ?? "—")
                    )}
                  </td>
                  <td className="px-2 py-1 font-mono">{e.symbol ?? "—"}</td>
                  <td className="px-2 py-1 text-fg-dim">{e.detail}</td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-2 py-8 text-center text-fg-faint">
                  {events.length === 0 ? "Waiting for cross-gateway activity…" : "No events match the filters."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {detailId && <AdminOrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}
