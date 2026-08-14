import { Outlet, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useUiStore } from "@/store/useUiStore.js";
import { TopBar } from "./TopBar.js";
import { Sidebar } from "./Sidebar.js";
import { SymbolDetailPanel } from "@/components/symbol/SymbolDetailPanel.js";
import { EventCenter } from "@/components/notifications/EventCenter.js";
import { OrderDetailDrawer } from "@/components/orders/OrderDetailDrawer.js";

/**
 * AppShell — the persistent chrome wrapping all authenticated screens.
 * Redirects to /login when unauthenticated.
 */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const eventCenterOpen = useUiStore((s) => s.eventCenterOpen);
  const orderDetailId = useUiStore((s) => s.orderDetailId);
  const closeOrderDetail = useUiStore((s) => s.closeOrderDetail);

  if (!apiKey) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0f] text-[#e8e8f0] overflow-hidden">
      {/* Fixed top bar (h-10) */}
      <TopBar />

      <div className="flex flex-1 overflow-hidden">
        {/* Persistent sidebar (w-56) */}
        <Sidebar />

        {/* Main content area */}
        <main className="flex-1 overflow-auto p-4">
          <Outlet />
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
    </div>
  );
}
