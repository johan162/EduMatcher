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

/** Dwell time offered by the Overview's page-delay control (design §8.3). */
export const PAGE_DELAY_CHOICES = [3, 5, 8, 15, 30] as const;

/**
 * How long a symbol may go without printing before its row is faded, in
 * seconds (design §8.7, T-L3).
 *
 * Exposed rather than hardcoded because the right value is a property of the
 * exchange, not of the terminal. Five minutes is a reasonable default for a
 * liquid book and badly wrong for a thin classroom one, where it can fade
 * every row on the board permanently -- and a mark that is always on marks
 * nothing. An instructor running a quiet session can widen it; a busy desk
 * can tighten it until it discriminates again.
 *
 * `Infinity` turns the marking off, for a session so thin that no threshold
 * is informative.
 */
export const STALE_AFTER_CHOICES = [60, 300, 900, 3600, Infinity] as const;

/**
 * Default dwell per density (design §7.5): a lobby display is read from across
 * a room and needs longer on each page; a power user wants the cycle brisk.
 */
const DENSITY_PAGE_DELAY: Record<Density, number> = { lobby: 15, standard: 8, dense: 5 };

/** Which symbols the Overview grid pages through (design §8.6). */
export type OverviewFilter = "all" | "watchlist";

interface PrefsStore {
  theme: ThemePreference;
  density: Density;
  /** `null` means "follow the density default" rather than a chosen value. */
  pageDelaySec: number | null;
  /** Silence after which a row is faded. See `STALE_AFTER_CHOICES`. */
  staleAfterSec: number;
  watchlist: string[];
  overviewFilter: OverviewFilter;

  setTheme: (theme: ThemePreference) => void;
  toggleTheme: () => void;
  setDensity: (density: Density) => void;
  cycleDensity: () => void;
  setPageDelaySec: (seconds: number | null) => void;
  setStaleAfterSec: (seconds: number) => void;
  toggleWatchlist: (sym: string) => void;
  setOverviewFilter: (filter: OverviewFilter) => void;
}

export const usePrefsStore = create<PrefsStore>()(
  persist(
    (set, get) => ({
      theme: "dark",
      density: "standard",
      pageDelaySec: null,
      staleAfterSec: 300,
      watchlist: [],
      overviewFilter: "all",

      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),

      setDensity: (density) => set({ density }),
      cycleDensity: () => {
        const next = DENSITY_ORDER[(DENSITY_ORDER.indexOf(get().density) + 1) % DENSITY_ORDER.length];
        set({ density: next ?? "standard" });
      },

      setPageDelaySec: (pageDelaySec) => set({ pageDelaySec }),

      setStaleAfterSec: (staleAfterSec) => set({ staleAfterSec }),

      toggleWatchlist: (sym) => {
        const current = get().watchlist;
        set({
          watchlist: current.includes(sym) ? current.filter((entry) => entry !== sym) : [...current, sym],
        });
      },

      setOverviewFilter: (overviewFilter) => set({ overviewFilter }),
    }),
    { name: "terminal-prefs" },
  ),
);

/** The dwell actually in force: an explicit choice, else the density default. */
export function effectivePageDelaySec(pageDelaySec: number | null, density: Density): number {
  return pageDelaySec ?? DENSITY_PAGE_DELAY[density];
}

/**
 * Reflect the theme onto <html>, which is what the CSS variables key off.
 *
 * Kept outside the store so the store stays a pure data container that tests
 * can drive without a DOM.
 */
export function applyThemeToDocument(theme: ThemePreference): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}
