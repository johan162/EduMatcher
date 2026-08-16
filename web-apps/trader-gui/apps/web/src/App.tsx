import { Routes, Route, Navigate } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell.js";
import { RoleGuard } from "@/router/RoleGuard.js";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useWebSocketManager } from "@/ws/WebSocketManager.js";
import { useMarketDataSubscription } from "@/hooks/useMarketDataSubscription.js";
import { useOrderEventNotifications } from "@/hooks/useOrderEventNotifications.js";
import { useOrderStream } from "@/hooks/useOrderStream.js";
import { useQuoteEvents } from "@/hooks/useQuoteEvents.js";
import { useHelpKeyboard } from "@/hooks/useHelpKeyboard.js";
import { useGlobalShortcuts } from "@/hooks/useGlobalShortcuts.js";

// Pages (lazy-loaded stubs for now)
import { LoginPage } from "@/pages/LoginPage.js";
import { MarketOverviewPage } from "@/pages/MarketOverviewPage.js";
import { WatchlistPage } from "@/pages/WatchlistPage.js";
import { TradingWorkspacePage } from "@/pages/TradingWorkspacePage.js";
import { OrderEntryPage } from "@/pages/OrderEntryPage.js";
import { ActiveOrdersPage } from "@/pages/ActiveOrdersPage.js";
import { TradeHistoryPage } from "@/pages/TradeHistoryPage.js";
import { PositionsPage } from "@/pages/PositionsPage.js";
import { QuoteMgmtPage } from "@/pages/QuoteMgmtPage.js";
import { QuoteBootstrapPage } from "@/pages/QuoteBootstrapPage.js";
import { AdminDashboardPage } from "@/pages/AdminDashboardPage.js";
import { AdminSymbolsPage } from "@/pages/AdminSymbolsPage.js";
import { AdminIndexesPage } from "@/pages/AdminIndexesPage.js";
import { AdminSessionPage } from "@/pages/AdminSessionPage.js";
import { AdminRiskPage } from "@/pages/AdminRiskPage.js";
import { AdminCircuitBreakersPage } from "@/pages/AdminCircuitBreakersPage.js";
import { AdminGatewaysPage } from "@/pages/AdminGatewaysPage.js";
import { AdminMonitorPage } from "@/pages/AdminMonitorPage.js";

/** Redirect to the role-appropriate landing screen after login. */
function RoleLanding() {
  const role = useAuthStore((s) => s.role);
  if (role === "TRADER") return <Navigate to="/workspace" replace />;
  if (role === "MARKET_MAKER") return <Navigate to="/quotes" replace />;
  if (role === "ADMIN") return <Navigate to="/admin/dashboard" replace />;
  return <Navigate to="/login" replace />;
}

export default function App() {
  // Connect WebSockets once the user is authenticated, and keep the
  // market-data focus subscription bound to the active symbol + watchlist.
  useWebSocketManager();
  useMarketDataSubscription();
  // Surface live fills/terminals from /events as toasts + Event Center entries
  // (TRADER/MM private stream; inert for ADMIN which has no order.* events).
  useOrderEventNotifications();
  // Keep the live order store (blotter) seeded from orders.snapshot + order.*.
  useOrderStream();
  // MARKET_MAKER quote lifecycle: fill alerts + reconcile the quote caches on
  // connect/reconnect and every quote.ack/status (inert for TRADER/ADMIN).
  useQuoteEvents();
  // Global help shortcuts: Ctrl+/ (help drawer) and ? (shortcut reference).
  useHelpKeyboard();
  // Command palette (Ctrl+K) + global navigation shortcuts (§21).
  useGlobalShortcuts();

  return (
    <Routes>
      {/* Public — no auth required */}
      <Route path="/login" element={<LoginPage />} />

      {/* Protected — all authenticated roles */}
      <Route element={<AppShell />}>
        <Route index element={<RoleLanding />} />

        {/* All roles */}
        <Route path="/market" element={<MarketOverviewPage />} />
        <Route path="/watchlist" element={<WatchlistPage />} />

        {/* TRADER only */}
        <Route element={<RoleGuard roles={["TRADER"]} />}>
          <Route path="/workspace" element={<TradingWorkspacePage />} />
          <Route path="/orders/entry" element={<OrderEntryPage />} />
          <Route path="/orders" element={<ActiveOrdersPage />} />
          <Route path="/orders/history" element={<TradeHistoryPage />} />
        </Route>

        {/* TRADER + MARKET_MAKER */}
        <Route element={<RoleGuard roles={["TRADER", "MARKET_MAKER"]} />}>
          <Route path="/positions" element={<PositionsPage />} />
        </Route>

        {/* MARKET_MAKER only */}
        <Route element={<RoleGuard roles={["MARKET_MAKER"]} />}>
          <Route path="/quotes" element={<QuoteMgmtPage />} />
          <Route path="/quotes/bootstrap" element={<QuoteBootstrapPage />} />
        </Route>

        {/* ADMIN only */}
        <Route element={<RoleGuard roles={["ADMIN"]} />}>
          <Route path="/admin/dashboard" element={<AdminDashboardPage />} />
          <Route path="/admin/symbols" element={<AdminSymbolsPage />} />
          <Route path="/admin/indexes" element={<AdminIndexesPage />} />
          <Route path="/admin/session" element={<AdminSessionPage />} />
          <Route path="/admin/risk" element={<AdminRiskPage />} />
          <Route path="/admin/circuit-breakers" element={<AdminCircuitBreakersPage />} />
          <Route path="/admin/gateways" element={<AdminGatewaysPage />} />
          <Route path="/admin/monitor" element={<AdminMonitorPage />} />
        </Route>
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
