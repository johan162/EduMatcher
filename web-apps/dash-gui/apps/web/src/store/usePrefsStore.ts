/**
 * Viewer preferences, persisted to localStorage (lib/storage.ts: a storage
 * that throws only means the choice is not remembered).
 *
 * Client-only: there is no account to attach them to. Font size lives in its
 * own store (useFontSizeStore), exactly as in terminal-gui and book-gui.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { prefsStorage } from "../lib/storage.js";

export type ThemePreference = "dark" | "light";

/**
 * How a stat tile shows its threshold colour (Grafana's two stat modes,
 * design §13): on the value, or as the tile's background.
 */
export type StatColorMode = "value" | "background";

interface PrefsStore {
  theme: ThemePreference;
  statColorMode: StatColorMode;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
  setStatColorMode: (mode: StatColorMode) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      statColorMode: "value",
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
      setStatColorMode: (statColorMode) => set({ statColorMode }),
    }),
    { name: "dash-prefs", storage: prefsStorage },
  ),
);

/** Reflect the theme onto <html>, which is what the CSS variables key off. */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
