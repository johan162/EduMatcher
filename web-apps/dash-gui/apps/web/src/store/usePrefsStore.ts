/**
 * Viewer preferences, persisted to localStorage.
 *
 * Client-only: there is no account to attach them to. Font size lives in its
 * own store (useFontSizeStore), exactly as in terminal-gui and book-gui.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "dark" | "light";

interface PrefsStore {
  theme: ThemePreference;
  toggleTheme: () => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
    }),
    { name: "dash-prefs" },
  ),
);

/** Reflect the theme onto <html>, which is what the CSS variables key off. */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
