import { useState } from "react";
import { Outlet } from "react-router-dom";
import { useDraftStore } from "@/store/draftStore";
import { TopBar } from "./TopBar";
import { NavList } from "./NavList";
import { DiagnosticsDrawer } from "./DiagnosticsDrawer";

export function AppShell() {
  const diagnostics = useDraftStore((s) => s.diagnostics);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const counts = {
    error: diagnostics.filter((d) => d.severity === "error").length,
    warning: diagnostics.filter((d) => d.severity === "warning").length,
  };

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <div className="hidden w-60 shrink-0 overflow-y-auto border-r border-border bg-surface md:block">
          <NavList />
        </div>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>

        {drawerOpen ? (
          <div className="hidden w-80 shrink-0 lg:block">
            <DiagnosticsDrawer />
          </div>
        ) : null}

        <button
          type="button"
          onClick={() => setDrawerOpen((v) => !v)}
          className="fixed bottom-4 right-4 z-30 rounded-full border border-border bg-surface-raised px-4 py-2 text-sm shadow-lg lg:hidden"
        >
          Diagnostics
          {counts.error + counts.warning > 0 && (
            <span className="ml-2 rounded-full bg-error px-2 py-0.5 text-xs text-white">
              {counts.error + counts.warning}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
