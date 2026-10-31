import { useEffect, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { useAdminGatewaysQuery, useAdminHaltsQuery, useDailyStatsQuery } from "@/queries/index.js";
import { useThrottledBooks } from "@/hooks/useThrottledBooks.js";
import { useMonitorStore, selectActiveOrderCount, selectOrderCountsBySymbol } from "@/store/useMonitorStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useHaltStore } from "@/store/useHaltStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { RecentEventsFeed } from "@/components/admin/RecentEventsFeed.js";
import { buildMarketRows } from "@/lib/marketRows.js";
import { SESSION_PHASE_META } from "@/lib/sessionState.js";
import { formatPrice, formatQty } from "@/lib/formatters.js";

function KpiCard({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded border border-line bg-deep p-3">
      <span className="text-[10px] uppercase tracking-wide text-fg-mute">{label}</span>
      <span className={`text-lg font-semibold ${tone ?? "text-fg"}`}>{value}</span>
    </div>
  );
}

/**
 * System Dashboard (§15.1) — the ADMIN landing screen. A read-only overview:
 * KPI cards, a per-symbol summary, and the recent cross-gateway event feed. The
 * orders KPI and event feed come from the admin monitor stream (useMonitorStore,
 * fed by the `/ws/admin/monitor` socket); session/halts/books come from the shared
 * live stores; the gateway roster from `GET /admin/gateways`.
 */
export function AdminDashboardPage() {
  const phase = useSessionStore((s) => s.phase);
  const symbols = useSymbolStore((s) => s.symbols);
  const halts = useHaltStore((s) => s.halts);
  const setHalts = useHaltStore((s) => s.setHalts);
  const books = useThrottledBooks();
  // Derived inside the selectors so the page re-renders when a count changes,
  // not on every order event.
  const activeOrders = useMonitorStore((s) => selectActiveOrderCount(s.orders));
  const ordersBySymbol = useMonitorStore(useShallow((s) => selectOrderCountsBySymbol(s.orders)));
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
        <h1 className="text-lg font-semibold text-fg">System Dashboard</h1>
        {health.adminMonitor && health.adminMonitor !== "connected" && (
          <span className="text-[11px] text-amber-400">Monitor feed {health.adminMonitor}</span>
        )}
      </div>

      {/* KPI cards (§15.1.1) */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {/* The phase's own badge: textClass is only legible on bgClass. */}
        <KpiCard
          label="Session"
          value={phaseMeta.label}
          tone={`self-start rounded px-2 ${phaseMeta.bgClass} ${phaseMeta.textClass}`}
        />
        <KpiCard label="Active Orders (all gateways)" value={formatQty(activeOrders)} />
        <KpiCard label="Connected Gateways" value={formatQty(connectedGateways)} />
        <KpiCard
          label="Active CB Halts"
          value={formatQty(haltCount)}
          tone={haltCount > 0 ? "text-halt" : "text-fg"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Per-symbol summary (§15.1.2) */}
        <section aria-label="Per-symbol summary" className="xl:col-span-2 flex flex-col gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">Symbols</h2>
          <div className="overflow-auto rounded border border-line">
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-panel text-fg-dim">
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
                  <tr key={r.symbol} className="border-b border-raised">
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
                    <td className="px-2 py-1 text-right font-mono text-fg-dim">
                      {r.volume === null ? "—" : formatQty(r.volume)}
                    </td>
                    <td className="px-2 py-1 text-right font-mono">{ordersBySymbol[r.symbol] ?? 0}</td>
                    <td className="px-2 py-1">
                      {r.halted ? (
                        <span className="rounded bg-halt px-1.5 py-0.5 text-[9px] font-semibold text-black">
                          {r.haltLevel ? `HALT ${r.haltLevel}` : "HALT"}
                        </span>
                      ) : (
                        <span className="text-[10px] text-fg-faint">ok</span>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-2 py-6 text-center text-fg-faint">
                      No symbols.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <RecentEventsFeed />
      </div>
    </div>
  );
}
