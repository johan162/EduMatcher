/** Application shell (design §7.1): top bar + nav rail + active view. */

import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { applyTheme, getStoredTheme, type ThemePreference } from "../../lib/theme.js";
import { NavRail } from "./NavRail.js";
import { TopBar } from "./TopBar.js";

export function AppShell() {
  const [theme, setTheme] = useState<ThemePreference>(getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <div className="flex h-screen flex-col bg-bg text-fg">
      <TopBar theme={theme} onThemeChange={setTheme} />
      <div className="flex min-h-0 flex-1">
        <NavRail />
        <main className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
