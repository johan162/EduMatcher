/** Application shell: top bar, the book, status strip (design §9.1). */

import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { StatusStrip } from "./StatusStrip.js";
import { TopBar } from "./TopBar.js";
import { useBookStore } from "../../store/useBookStore.js";
import { applyThemeToDocument, usePrefsStore } from "../../store/usePrefsStore.js";

export function AppShell() {
  const theme = usePrefsStore((s) => s.theme);
  const connection = useBookStore((s) => s.connection());

  useEffect(() => applyThemeToDocument(theme), [theme]);

  return (
    // Sized against CSS zoom (see useFontSizeStore) so the footer stays on screen at every font size.
    <div className="flex flex-col bg-bg text-fg" style={{ height: "calc(100vh / var(--zoom, 1))" }}>
      <TopBar />

      {/* A dropped socket makes every number of unknown age: hide them rather than show them stale. */}
      {connection === "OFFLINE" ? (
        <main className="flex min-h-0 flex-1 items-center justify-center">
          <div role="alert" className="rounded border border-offline bg-bg-subtle px-8 py-6 text-center">
            <p className="text-lg font-semibold text-offline">Disconnected from pm-book-bridge</p>
            <p className="mt-2 text-sm text-fg-subtle">
              Reconnecting automatically. Values are hidden rather than shown stale.
            </p>
          </div>
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col p-4">
          <Outlet />
        </main>
      )}

      <StatusStrip />
    </div>
  );
}
