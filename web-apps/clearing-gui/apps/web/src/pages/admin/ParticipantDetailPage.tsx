/**
 * One participant gateway (ADMIN drill-down): its totals, and the same
 * views a participant sees of itself, here for the named gateway. Every
 * request carries `gateway`, which the API allows only for ADMIN.
 */
import { NavLink, Route, Routes, useParams } from "react-router-dom";
import { QueryState } from "@/components/shared/QueryState";
import { PageHeader, Stat } from "@/components/shared/Ui";
import { HistoryView } from "@/components/views/HistoryView";
import { PositionsView } from "@/components/views/PositionsView";
import { SessionsView } from "@/components/views/SessionsView";
import { SettlementView } from "@/components/views/SettlementView";
import { TradesView } from "@/components/views/TradesView";
import { useParticipant } from "@/api/queries";
import { formatCurrency } from "@/lib/money";
import { formatNs } from "@/lib/time";

const TABS = [
  { to: "", label: "Positions" },
  { to: "trades", label: "Trades" },
  { to: "history", label: "History" },
  { to: "settlement", label: "Settlement" },
  { to: "sessions", label: "Sessions" },
];

export function ParticipantDetailPage() {
  const gatewayId = (useParams()["gatewayId"] ?? "").toUpperCase();
  const detail = useParticipant(gatewayId);
  return (
    <>
      <PageHeader title={`Participant ${gatewayId}`}>Current totals in display currency; the tabs read the same gateway.</PageHeader>
      <QueryState query={detail} skeletonColumns={5}>
        {(d) => (
          <div className="mb-4 flex flex-wrap gap-3">
            <Stat label="Realized P&L" value={formatCurrency(d.realized_pnl)} />
            <Stat label="Unrealized P&L" value={formatCurrency(d.unrealized_pnl)} />
            <Stat label="Total P&L" value={formatCurrency(d.total_pnl)} />
            <Stat label="Open positions" value={`${d.open_position_count} of ${d.position_count}`} />
            <Stat label="Last update" value={formatNs(d.last_update_ts_ns)} />
            <Stat label="Latest close" value={d.latest_close_date ?? "—"} />
          </div>
        )}
      </QueryState>
      <nav aria-label="Participant views" className="mb-4 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={`/participants/${encodeURIComponent(gatewayId)}${t.to ? `/${t.to}` : ""}`}
            end
            className={({ isActive }) =>
              `px-3 py-1.5 text-sm ${isActive ? "border-b-2 border-accent text-fg" : "text-fg-dim hover:text-fg"}`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<PositionsView gateway={gatewayId} label={gatewayId} />} />
        <Route path="trades" element={<TradesView gateway={gatewayId} label={gatewayId} />} />
        <Route path="history" element={<HistoryView gateway={gatewayId} />} />
        <Route path="settlement" element={<SettlementView mode="gateway" gateway={gatewayId} caption={`${gatewayId} settlements`} />} />
        <Route path="sessions" element={<SessionsView gateway={gatewayId} label={`${gatewayId} gateway sessions`} />} />
      </Routes>
    </>
  );
}
