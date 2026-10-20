/** Application shell: top bar, banner, the dashboard, status strip (design §12.1-12.2). */

import clsx from "clsx";
import { useEffect } from "react";
import { Outlet, useSearchParams } from "react-router-dom";
import { DisconnectedBanner } from "./DisconnectedBanner.js";
import { StatusStrip } from "./StatusStrip.js";
import { TopBar } from "./TopBar.js";
import { DEFAULT_RANGE, rangeFromParam } from "../../lib/range.js";
import { useDashStore } from "../../store/useDashStore.js";
import { applyThemeToDocument, usePrefsStore } from "../../store/usePrefsStore.js";

export function AppShell() {
  const theme = usePrefsStore((s) => s.theme);
  const live = useDashStore((s) => s.connection() === "LIVE");
  const setRange = useDashStore((s) => s.setRange);
  const [params] = useSearchParams();
  const from = params.get("from");

  useEffect(() => applyThemeToDocument(theme), [theme]);
  // The URL is the time range's source: a pasted link, back/forward and the picker alike.
  useEffect(() => setRange(rangeFromParam(from) ?? DEFAULT_RANGE), [from, setRange]);

  return (
    // Sized against CSS zoom (see useFontSizeStore) so the footer stays on screen at every font size.
    <div className="flex flex-col bg-bg text-fg" style={{ height: "calc(100vh / var(--zoom, 1))" }}>
      <TopBar />
      <DisconnectedBanner />
      {/* Not live: the last figures stay, dimmed, under the banner that says how old they are. */}
      <main data-stale={!live} className={clsx("relative flex min-h-0 flex-1 flex-col p-4", !live && "stale")}>
        <Outlet />
      </main>
      <StatusStrip />
    </div>
  );
}
