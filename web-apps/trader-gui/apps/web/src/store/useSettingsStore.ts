import { create } from "zustand";
import { env } from "@/lib/env.js";

/**
 * How the Trading Workspace symbol picker chooses its widget.
 * "auto" picks based on `symbolPickerThreshold`; the other two force one
 * widget regardless of how many symbols are loaded.
 */
export type SymbolPickerMode = "auto" | "dropdown" | "search";

export interface SettingsStore {
  /**
   * When true (default), destructive actions show a confirmation dialog.
   * When false (power-user mode), reversible actions skip the dialog and show
   * an undo-toast instead. Always-confirm exceptions still confirm regardless.
   */
  confirmCancellations: boolean;
  toggleConfirmCancellations: () => void;

  /** Maximum overview symbols for the broad book/trades subscription. */
  maxOverviewSymbols: number;
  /** Maximum focus-set symbols for depth/auction subscriptions. */
  maxFocusSymbols: number;

  /** Symbol picker widget: dropdown, search, or auto (see SymbolPickerMode). */
  symbolPickerMode: SymbolPickerMode;
  setSymbolPickerMode: (mode: SymbolPickerMode) => void;

  /** In "auto" mode, symbol count at/above which the picker switches to search. */
  symbolPickerThreshold: number;
  setSymbolPickerThreshold: (threshold: number) => void;
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  confirmCancellations: true,
  toggleConfirmCancellations: () => set((s) => ({ confirmCancellations: !s.confirmCancellations })),

  maxOverviewSymbols: parseInt(env("VITE_MAX_OVERVIEW_SYMBOLS", "250"), 10),

  maxFocusSymbols: parseInt(env("VITE_MAX_FOCUS_SYMBOLS", "25"), 10),

  symbolPickerMode: "auto",
  setSymbolPickerMode: (mode) => set({ symbolPickerMode: mode }),

  symbolPickerThreshold: 20,
  setSymbolPickerThreshold: (threshold) => set({ symbolPickerThreshold: threshold }),
}));
