import { Outlet, Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useUiStore } from "@/store/useUiStore.js";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary.js";
import { TopBar } from "./TopBar.js";
import { Sidebar } from "./Sidebar.js";
import { ConnectionBanner } from "./ConnectionBanner.js";
import { SymbolDetailPanel } from "@/components/symbol/SymbolDetailPanel.js";
import { EventCenter } from "@/components/notifications/EventCenter.js";
import { OrderDetailDrawer } from "@/components/orders/OrderDetailDrawer.js";
import { HelpDrawer } from "@/components/help/HelpDrawer.js";
import { ShortcutsDialog } from "@/components/help/ShortcutsDialog.js";
import { CommandPalette } from "@/components/command/CommandPalette.js";

/**
 * AppShell — the persistent chrome wrapping all authenticated screens.
 * Redirects to /login when unauthenticated.
 */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const eventCenterOpen = useUiStore((s) => s.eventCenterOpen);
  const orderDetailId = useUiStore((s) => s.orderDetailId);
  const closeOrderDetail = useUiStore((s) => s.closeOrderDetail);
  const helpOpen = useUiStore((s) => s.helpOpen);
  const shortcutsOpen = useUiStore((s) => s.shortcutsOpen);
  const commandPaletteOpen = useUiStore((s) => s.commandPaletteOpen);
  const location = useLocation();

  if (!apiKey) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0f] text-[#e8e8f0] overflow-hidden">
      {/* Fixed top bar (h-10) */}
      <TopBar />

      {/* App-wide degradation signal when a live socket is down (§23 phase 16). */}
      <ConnectionBanner />

      <div className="flex flex-1 overflow-hidden">
        {/* Persistent sidebar (w-56) */}
        <Sidebar />

        {/* Main content area. The route subtree is wrapped in an ErrorBoundary
            keyed by pathname so a crashing screen degrades to an inline message
            while the chrome stays usable, and navigating away clears it. */}
        <main className="flex-1 overflow-auto p-4">
          <ErrorBoundary key={location.pathname} label="This screen">
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      {/* Right-panel overlay; renders only when opened from a symbol click (§16). */}
      <SymbolDetailPanel />

      {/* App-level overlays (§20): the Event Center sheet and the shared Order
          Detail drawer, both driven by useUiStore so the blotter, Trade
          History, and Event Center all open the same single drawer. */}
      {eventCenterOpen && <EventCenter />}
      {orderDetailId && (
        <OrderDetailDrawer key={orderDetailId} orderId={orderDetailId} onClose={closeOrderDetail} />
      )}
      {helpOpen && <HelpDrawer />}
      {shortcutsOpen && <ShortcutsDialog />}
      {commandPaletteOpen && <CommandPalette />}
    </div>
  );
}
