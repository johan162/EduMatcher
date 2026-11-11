import { Suspense } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * The chrome around every authenticated screen: top bar, role navigation and
 * the routed page. Pages are lazy-loaded (App.tsx); the Suspense fallback
 * covers their first load. The error boundary is keyed by path, so a screen
 * that crashes degrades to a message and navigating away clears it.
 */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const location = useLocation();
  if (!apiKey) return <Navigate to="/login" replace />;
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-app text-fg">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="min-h-0 flex-1 overflow-auto p-4">
          <ErrorBoundary key={location.pathname} label="This screen">
            <Suspense fallback={<TableSkeleton />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
