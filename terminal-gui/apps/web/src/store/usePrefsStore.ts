/**
 * Viewer preferences, persisted to localStorage (design §7.5).
 *
 * Client-only by design: there is no account to attach these to and §3.2 rules
 * out inventing one. A different browser simply starts on the defaults.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "dark" | "light";

/**
 * Information density (design §7.5). A display preference, not a mode: every
 * route and data point stays reachable at any setting, only defaults change.
 */
export type Density = "lobby" | "standard" | "dense";

export const DENSITY_ORDER: Density[] = ["lobby", "standard", "dense"];

export const DENSITY_LABEL: Record<Density, string> = {
  lobby: "Lobby",
  standard: "Standard",
  dense: "Dense",
};

/** Row padding and type scale per preset, applied to grids and tables. */
export const DENSITY_ROW_CLASS: Record<Density, string> = {
  lobby: "text-base py-2",
  standard: "text-sm py-1",
  dense: "text-xs py-0.5",
};

interface PrefsStore {
  theme: ThemePreference;
  density: Density;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
  setDensity: (density: Density) => void;
  cycleDensity: () => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      density: "standard",

      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),

      setDensity: (density) => set({ density }),
      cycleDensity: () => {
        const next = DENSITY_ORDER[(DENSITY_ORDER.indexOf(get().density) + 1) % DENSITY_ORDER.length];
        set({ density: next ?? "standard" });
      },
    }),
    { name: "terminal-prefs" },
  ),
);

/**
 * Reflect the theme onto <html>, which is what the CSS variables key off.
 *
 * Kept outside the store so the store stays a pure data container that tests
 * can drive without a DOM.
 */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
