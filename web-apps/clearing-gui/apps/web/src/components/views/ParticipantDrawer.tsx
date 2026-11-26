/**
 * One participant gateway (ADMIN drill-down), in a drawer over the
 * Participants list (CG21): its totals, and the same views a participant sees
 * of itself, here for the named gateway. Every request carries `gateway`,
 * which the API allows only for ADMIN. The tabs are routes under
 * `/participants/:gatewayId`, so each is a link that can be shared.
 */
import { NavLink, Route, Routes } from "react-router-dom";
import { Drawer } from "@/components/shared/Drawer";
import { QueryState } from "@/components/shared/QueryState";
import { Stat } from "@/components/shared/Ui";
import { HistoryView } from "@/components/views/HistoryView";
import { PositionsView } from "@/components/views/PositionsView";
import { SessionsView } from "@/components/views/SessionsView";
import { SettlementView } from "@/components/views/SettlementView";
import { TradesView } from "@/components/views/TradesView";
import { useParticipant } from "@/api/queries";
import { formatCurrency } from "@/lib/money";
import { Time } from "@/components/shared/Time";
import { participantPath } from "./GatewayId";

const TABS = [
  { to: "", label: "Positions" },
  { to: "trades", label: "Trades" },
  { to: "history", label: "History" },
  { to: "settlement", label: "Settlement" },
  { to: "sessions", label: "Sessions" },
];

export function ParticipantDrawer({ gatewayId, onClose }: { gatewayId: string; onClose: () => void }) {
  const detail = useParticipant(gatewayId);
  return (
    <Drawer kind="Participant" title={gatewayId} onClose={onClose}>
      <p className="mb-3 text-xs text-fg-dim">Current totals in display currency; the tabs read the same gateway.</p>
      <QueryState query={detail} skeletonColumns={5}>
        {(d) => (
          <div className="mb-4 flex flex-wrap gap-3">
            <Stat label="Realized P&L" value={formatCurrency(d.realized_pnl)} title="Realized P&L of all the gateway's positions, in display currency" />
            <Stat label="Unrealized P&L" value={formatCurrency(d.unrealized_pnl)} title="Unrealized P&L of its open positions at their marks, in display currency" />
            <Stat label="Total P&L" value={formatCurrency(d.total_pnl)} title="Realized + unrealized P&L, in display currency" />
            <Stat
              label="Open positions"
              value={`${d.open_position_count} of ${d.position_count}`}
              title="Positions with a non-zero quantity, of all symbols the gateway has traded"
            />
            <Stat label="Last update" value={<Time ns={d.last_update_ts_ns} />} title="When clearing last wrote any of the gateway's positions" />
            <Stat label="Latest close" value={d.latest_close_date ?? "—"} title="The latest session close with a snapshot of the gateway's positions" />
          </div>
        )}
      </QueryState>
      <nav aria-label="Participant views" className="mb-4 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={`${participantPath(gatewayId)}${t.to ? `/${t.to}` : ""}`}
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
    </Drawer>
  );
}
