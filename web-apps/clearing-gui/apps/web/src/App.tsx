import { lazy, useEffect, type ComponentType } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { RoleGuard, landingPath } from "@/router/RoleGuard";
import { useAuthStore } from "@/store/useAuthStore";

/*
 * Routes, by role (design §7.1):
 *
 *   ADMIN                 /overview, /participants[/:gatewayId/*], /symbols,
 *                         /events, /gateway-sessions, /reconciliation, /eod
 *   TRADER, MARKET_MAKER  /me/positions, /me/trades, /me/history,
 *                         /me/settlement, /me/sessions
 *   MARKET_MAKER          /me/obligations
 *
 * Pages are lazy-loaded so the first paint carries only the shell; the chart
 * library is pulled in only by the history screens.
 */
const named = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) =>
  lazy(async () => ({ default: (await load())[name] }));

const PositionsPage = named(() => import("@/pages/me/MyPages"), "MyPositionsPage");
const TradesPage = named(() => import("@/pages/me/MyPages"), "MyTradesPage");
const HistoryPage = named(() => import("@/pages/me/MyPages"), "MyHistoryPage");
const SettlementPage = named(() => import("@/pages/me/MyPages"), "MySettlementPage");
const SessionsPage = named(() => import("@/pages/me/MyPages"), "MySessionsPage");
const ObligationsPage = named(() => import("@/pages/me/ObligationsPage"), "ObligationsPage");
const OverviewPage = named(() => import("@/pages/admin/OverviewPage"), "OverviewPage");
const ParticipantsPage = named(() => import("@/pages/admin/ParticipantsPage"), "ParticipantsPage");
const ParticipantDetailPage = named(() => import("@/pages/admin/ParticipantDetailPage"), "ParticipantDetailPage");
const SymbolsPage = named(() => import("@/pages/admin/SymbolsPage"), "SymbolsPage");
const EventsPage = named(() => import("@/pages/admin/EventsPage"), "EventsPage");
const GatewaySessionsPage = named(() => import("@/pages/admin/GatewaySessionsPage"), "GatewaySessionsPage");
const ReconciliationPage = named(() => import("@/pages/admin/ReconciliationPage"), "ReconciliationPage");
const EodPage = named(() => import("@/pages/admin/EodPage"), "EodPage");

function RoleLanding() {
  const role = useAuthStore((s) => s.role);
  return <Navigate to={landingPath(role)} replace />;
}

/**
 * On logout -- the button, or a 401 from any request -- drop every cached
 * response, so nothing of the previous login stays in memory or on screen.
 */
function useClearCacheOnLogout() {
  const client = useQueryClient();
  const loggedIn = useAuthStore((s) => s.apiKey !== null);
  useEffect(() => {
    if (!loggedIn) client.clear();
  }, [loggedIn, client]);
}

export default function App() {
  useClearCacheOnLogout();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppShell />}>
        <Route index element={<RoleLanding />} />

        <Route element={<RoleGuard roles={["ADMIN"]} />}>
          <Route path="/overview" element={<OverviewPage />} />
          <Route path="/participants" element={<ParticipantsPage />} />
          <Route path="/participants/:gatewayId/*" element={<ParticipantDetailPage />} />
          <Route path="/symbols" element={<SymbolsPage />} />
          <Route path="/events" element={<EventsPage />} />
          <Route path="/gateway-sessions" element={<GatewaySessionsPage />} />
          <Route path="/reconciliation" element={<ReconciliationPage />} />
          <Route path="/eod" element={<EodPage />} />
        </Route>

        <Route element={<RoleGuard roles={["TRADER", "MARKET_MAKER"]} />}>
          <Route path="/me/positions" element={<PositionsPage />} />
          <Route path="/me/trades" element={<TradesPage />} />
          <Route path="/me/history" element={<HistoryPage />} />
          <Route path="/me/settlement" element={<SettlementPage />} />
          <Route path="/me/sessions" element={<SessionsPage />} />
        </Route>

        <Route element={<RoleGuard roles={["MARKET_MAKER"]} />}>
          <Route path="/me/obligations" element={<ObligationsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
