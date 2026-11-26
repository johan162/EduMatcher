import { Suspense, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useVenueTimeZone } from "@/api/queries";
import { useAuthStore } from "@/store/useAuthStore";
import { DrawerHostContext } from "@/components/shared/Drawer";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

/**
 * The chrome around every authenticated screen: top bar, role navigation and
 * the routed page. Pages are lazy-loaded (App.tsx); the Suspense fallback
 * covers their first load. The error boundary is keyed by screen, so a screen
 * that crashes degrades to a message and navigating away clears it. Signed
 * in, it also fetches the venue's session timezone for every time shown.
 *
 * A drawer (components/shared/Drawer) is drawn into the layer beside `main`:
 * over the page, under the top bar, and not scrolling with the page.
 */
export function AppShell() {
  const apiKey = useAuthStore((s) => s.apiKey);
  const location = useLocation();
  if (!apiKey) return <Navigate to="/login" replace />;
  return <SignedInShell pathname={location.pathname} />;
}

/**
 * The error boundary's key: the screen, not the full path. A participant's
 * drawer and its tabs (`/participants/X/...`) are the Participants screen, so
 * opening or closing one does not remount the list behind it.
 */
export function screenKey(pathname: string): string {
  return pathname.startsWith("/participants/") ? "/participants" : pathname;
}

/** The shell once signed in: only then is the venue's timezone asked for. */
function SignedInShell({ pathname }: { pathname: string }) {
  useVenueTimeZone();
  const [drawerHost, setDrawerHost] = useState<HTMLDivElement | null>(null);
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-app text-fg">
      <TopBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="relative min-h-0 min-w-0 flex-1">
          <DrawerHostContext.Provider value={drawerHost}>
            <main className="h-full overflow-auto p-4">
              <ErrorBoundary key={screenKey(pathname)} label="This screen">
                <Suspense fallback={<TableSkeleton />}>
                  <Outlet />
                </Suspense>
              </ErrorBoundary>
            </main>
          </DrawerHostContext.Provider>
          <div ref={setDrawerHost} />
        </div>
      </div>
    </div>
  );
}
