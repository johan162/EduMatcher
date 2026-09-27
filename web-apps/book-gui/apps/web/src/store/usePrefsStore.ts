/**
 * Viewer preferences, persisted to localStorage (design §9.6, §9.7).
 *
 * Client-only: there is no account to attach them to. Font size lives in its
 * own store (useFontSizeStore), exactly as in terminal-gui.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { MaxLevels } from "../lib/ladder.js";

export type ThemePreference = "dark" | "light";

export const MAX_LEVELS_ORDER: MaxLevels[] = ["fit", 10, 20, 50];

interface PrefsStore {
  theme: ThemePreference;
  /** pm-viewer's `--zebra-lines`: off by default. */
  zebra: boolean;
  /** pm-viewer's `--depth`: "fit" fills the screen. */
  maxLevels: MaxLevels;
  /** Where `/` takes you. */
  lastSymbol: string | null;

  toggleTheme: () => void;
  setZebra: (zebra: boolean) => void;
  setMaxLevels: (maxLevels: MaxLevels) => void;
  setLastSymbol: (sym: string) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      zebra: false,
      maxLevels: "fit",
      lastSymbol: null,

      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
      setZebra: (zebra) => set({ zebra }),
      setMaxLevels: (maxLevels) => set({ maxLevels }),
      setLastSymbol: (lastSymbol) => set({ lastSymbol }),
    }),
    { name: "book-prefs" },
  ),
);

/** Reflect the theme onto <html>, which is what the CSS variables key off. */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
