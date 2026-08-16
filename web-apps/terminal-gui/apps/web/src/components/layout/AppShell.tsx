/** Application shell (design §7.1): top bar, active view, status strip. */

import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { StatusStrip } from "./StatusStrip.js";
import { TopBar } from "./TopBar.js";
import { useLiveStore } from "../../store/useLiveStore.js";
import { applyThemeToDocument, usePrefsStore } from "../../store/usePrefsStore.js";

export function AppShell() {
  const theme = usePrefsStore((s) => s.theme);
  const connection = useLiveStore((s) => s.connectionState());

  useEffect(() => applyThemeToDocument(theme), [theme]);

  return (
    <div className="flex h-screen flex-col bg-bg text-fg">
      <TopBar />

      {/*
       * A dropped socket means every number on screen is of unknown age.
       * Design §7.4 requires that no stale data be shown at all in that
       * state, so the banner replaces the view rather than sitting above it.
       */}
      {connection === "OFFLINE" ? (
        <main className="flex min-h-0 flex-1 items-center justify-center">
          <div className="rounded border border-offline bg-bg-subtle px-8 py-6 text-center">
            <p className="text-lg font-semibold text-offline">Disconnected from pm-terminal-bridge</p>
            <p className="mt-2 text-sm text-fg-subtle">
              Reconnecting automatically. Values are hidden rather than shown stale.
            </p>
          </div>
        </main>
      ) : (
        <main className="min-h-0 flex-1 overflow-auto p-4">
          <Outlet />
        </main>
      )}

      <StatusStrip />
    </div>
  );
}
