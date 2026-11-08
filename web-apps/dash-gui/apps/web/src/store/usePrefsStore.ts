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

/** Row counts offered by the paged tables; 0 is all of them. */
export const PAGE_SIZES = [10, 30, 50, 100, 0] as const;

interface PrefsStore {
  theme: ThemePreference;
  statColorMode: StatColorMode;
  /** Books per page in the Order books table. See `PAGE_SIZES`. */
  booksPageSize: number;
  /** Participants per page in the Participants table. */
  participantsPageSize: number;
  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
  setStatColorMode: (mode: StatColorMode) => void;
  setBooksPageSize: (rows: number) => void;
  setParticipantsPageSize: (rows: number) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      statColorMode: "value",
      booksPageSize: 30,
      participantsPageSize: 30,
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
      setStatColorMode: (statColorMode) => set({ statColorMode }),
      setBooksPageSize: (booksPageSize) => set({ booksPageSize }),
      setParticipantsPageSize: (participantsPageSize) => set({ participantsPageSize }),
    }),
    { name: "dash-prefs", storage: prefsStorage },
  ),
);

/** Reflect the theme onto <html>, which is what the CSS variables key off. */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
