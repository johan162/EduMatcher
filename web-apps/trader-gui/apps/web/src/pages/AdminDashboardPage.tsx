import { useEffect, useMemo, useState } from "react";
import { useAdminGatewaysQuery, useAdminHaltsQuery, useDailyStatsQuery } from "@/queries/index.js";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { useMonitorStore, selectActiveOrderCount, selectOrderCountsBySymbol } from "@/store/useMonitorStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { MonitorKindBadge } from "@/components/admin/MonitorKindBadge.js";
import { AdminOrderDetailModal } from "@/components/admin/AdminOrderDetailModal.js";
import { buildMarketRows } from "@/lib/marketRows.js";
import { SESSION_PHASE_META } from "@/lib/sessionState.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";

function KpiCard({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded border border-[#2a2a45] bg-[#0d0d14] p-3">
      <span className="text-[10px] uppercase tracking-wide text-[#707090]">{label}</span>
      <span className={`text-lg font-semibold ${tone ?? "text-[#e8e8f0]"}`}>{value}</span>
    </div>
  );
}

/**
 * System Dashboard (§15.1) — the ADMIN landing screen. A read-only overview:
 * KPI cards, a per-symbol summary, and the recent cross-gateway event feed. The
 * orders KPI and event feed come from the admin monitor stream (useMonitorStore,
 * fed by the `/admin/monitor` socket); session/halts/books come from the shared
 * live stores; the gateway roster from `GET /admin/gateways`.
 */
export function AdminDashboardPage() {
  const phase = useSessionStore((s) => s.phase);
  const symbols = useSymbolStore((s) => s.symbols);
  const halts = useHaltStore((s) => s.halts);
  const setHalts = useHaltStore((s) => s.setHalts);
  const books = useThrottledBooks();
  const orders = useMonitorStore((s) => s.orders);
  const events = useMonitorStore((s) => s.events);
  const [detailId, setDetailId] = useState<string | null>(null);
  const health = useConnectionHealth();

  const gatewaysQuery = useAdminGatewaysQuery();
  const haltsQuery = useAdminHaltsQuery();
  const dailyQuery = useDailyStatsQuery();

  // Reconcile the halt store from the authoritative bootstrap (kept live after
  // by the market-data circuit_breaker channel).
  const haltsData = haltsQuery.data?.halted;
  useEffect(() => {
    if (haltsData) setHalts(haltsData);
  }, [haltsData, setHalts]);

  const activeOrders = selectActiveOrderCount(orders);
  const ordersBySymbol = useMemo(() => selectOrderCountsBySymbol(orders), [orders]);
  const connectedGateways = (gatewaysQuery.data?.gateways ?? []).filter((g) => g.connected).length;
  const haltCount = Object.keys(halts).length;
  const phaseMeta = SESSION_PHASE_META[phase];

  const rows = useMemo(
    () => buildMarketRows({ symbols, books, daily: dailyQuery.data ?? {}, halts, watchlist: [] }),
    [symbols, books, dailyQuery.data, halts],
  );

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-[#e8e8f0]">System Dashboard</h1>
        {health.adminMonitor && health.adminMonitor !== "connected" && (
          <span className="text-[11px] text-amber-400">Monitor feed {health.adminMonitor}</span>
        )}
      </div>

      {/* KPI cards (§15.1.1) */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Session" value={phaseMeta.label} tone={phaseMeta.textClass} />
        <KpiCard label="Active Orders (all gateways)" value={formatQty(activeOrders)} />
        <KpiCard label="Connected Gateways" value={formatQty(connectedGateways)} />
        <KpiCard
          label="Active CB Halts"
          value={formatQty(haltCount)}
          tone={haltCount > 0 ? "text-halt" : "text-[#e8e8f0]"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Per-symbol summary (§15.1.2) */}
        <section aria-label="Per-symbol summary" className="xl:col-span-2 flex flex-col gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">Symbols</h2>
          <div className="overflow-auto rounded border border-[#2a2a45]">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-[#12121a] text-[#9090b0]">
                <tr>
                  <th className="px-2 py-1.5 text-left font-medium">Symbol</th>
                  <th className="px-2 py-1.5 text-right font-medium">Bid</th>
                  <th className="px-2 py-1.5 text-right font-medium">Ask</th>
                  <th className="px-2 py-1.5 text-right font-medium">Last</th>
                  <th className="px-2 py-1.5 text-right font-medium">Volume</th>
                  <th className="px-2 py-1.5 text-right font-medium">Orders</th>
                  <th className="px-2 py-1.5 text-left font-medium">CB</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol} className="border-b border-[#1a1a28]">
                    <td className="px-2 py-1 font-mono font-medium">{r.symbol}</td>
                    <td className="px-2 py-1 text-right font-mono text-bid">
                      {formatPrice(r.bid, r.tickDecimals)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-ask">
                      {formatPrice(r.ask, r.tickDecimals)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">
                      {formatPrice(r.last, r.tickDecimals)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono text-[#9090b0]">
                      {r.volume === null ? "—" : formatQty(r.volume)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{ordersBySymbol[r.symbol] ?? 0}</td>
                    <td className="px-2 py-1">
                      {r.halted ? (
                        <span className="rounded bg-halt px-1.5 py-0.5 text-[9px] font-semibold text-black">
                          {r.haltLevel ? `HALT ${r.haltLevel}` : "HALT"}
                        </span>
                      ) : (
                        <span className="text-[10px] text-[#505070]">ok</span>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-2 py-6 text-center text-[#505070]">
                      No symbols.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Recent events feed (§15.1.3) */}
        <section aria-label="Recent events" className="flex flex-col gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-[#9090b0]">
            Recent Events
          </h2>
          <div className="overflow-auto rounded border border-[#2a2a45]">
            {events.length === 0 ? (
              <p className="p-6 text-center text-xs text-[#505070]">
                No cross-gateway activity yet.
              </p>
            ) : (
              <ol className="flex flex-col">
                {events.slice(0, 15).map((e) => {
                  const linkable = Boolean(e.order_id);
                  return (
                    <li
                      key={e.id}
                      onClick={linkable ? () => setDetailId(e.order_id!) : undefined}
                      className={`flex items-center gap-2 border-b border-[#1a1a28] px-2 py-1 ${
                        linkable ? "cursor-pointer hover:bg-[#1a1a28]" : ""
                      }`}
                    >
                      <MonitorKindBadge kind={e.kind} />
                      {e.symbol && <span className="font-mono text-[11px]">{e.symbol}</span>}
                      <span className="flex-1 truncate text-[11px] text-[#9090b0]">{e.detail}</span>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
        </section>
      </div>

      {detailId && <AdminOrderDetailModal orderId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}
