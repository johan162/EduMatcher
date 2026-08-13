import { Outlet, Navigate } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore.js";
import { TopBar } from "./TopBar.js";
import { Sidebar } from "./Sidebar.js";
import { SymbolDetailPanel } from "@/components/symbol/SymbolDetailPanel.js";

/**
 * AppShell — the persistent chrome wrapping all authenticated screens.
 * Redirects to /login when unauthenticated.
 */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);

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
    </div>
  );
}
