import { Suspense } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { EvidenceBanner } from "@/components/evidence/EvidenceBanner";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useAuthStore } from "@/store/useAuthStore";
import { useSnapshotStore } from "@/store/useSnapshotStore";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/** Top bar, workspaces, and the evidence banner above every workspace once a snapshot is pinned. */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const snapshotId = useSnapshotStore((s) => s.snapshotId);
  const { pathname } = useLocation();
  if (!apiKey) return <Navigate to="/login" replace />;
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-app text-fg">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          {snapshotId && <EvidenceBanner key={snapshotId} snapshotId={snapshotId} />}
          <main className="min-h-0 flex-1 overflow-auto p-4">
            <ErrorBoundary key={pathname} label="This workspace">
              <Suspense fallback={<TableSkeleton />}>
                <Outlet />
              </Suspense>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  );
}
