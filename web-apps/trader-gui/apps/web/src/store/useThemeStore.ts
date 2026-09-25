/**
 * Viewer theme preference, persisted to localStorage.
 *
 * Client-only, like terminal-gui's: there is no account to attach it to. This
 * is display state, not credentials -- the API key still lives in memory only
 * (useAuthStore, §7.1).
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "dark" | "light";

interface ThemeStore {
  theme: ThemePreference;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
    }),
    { name: "trader-theme" },
  ),
);

/**
 * Reflect the theme onto <html>, which is what the CSS variables key off.
 * Kept outside the store so the store stays a pure data container.
 */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
