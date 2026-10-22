/** Application shell (design §7.1): top bar + nav rail + active view. */

import { useState } from "react";
import { Outlet } from "react-router-dom";
import { applyTheme, cycleTheme, getStoredTheme, type ThemePreference } from "../../lib/theme.js";
import { NavRail } from "./NavRail.js";
import { TopBar } from "./TopBar.js";

export function AppShell() {
  const [theme, setTheme] = useState<ThemePreference>(() => {
    const initial = getStoredTheme();
    applyTheme(initial);
    return initial;
  });

  const handleThemeChange = () => {
    setTheme((prev) => {
      const next = cycleTheme(prev);
      applyTheme(next);
      return next;
    });
  };

  return (
    // Sized against CSS zoom (see useFontSizeStore) so the layout stays on screen at every font size.
    <div className="flex flex-col bg-bg text-fg" style={{ height: "calc(100vh / var(--zoom, 1))" }}>
      <TopBar theme={theme} onThemeChange={handleThemeChange} />
      <div className="flex min-h-0 flex-1">
        <NavRail />
        <main className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
