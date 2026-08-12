import { create } from "zustand";
import { env } from "@/lib/env.js";

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
}

export const useSettingsStore = create<SettingsStore>((set) => ({
  confirmCancellations: true,
  toggleConfirmCancellations: () =>
    set((s) => ({ confirmCancellations: !s.confirmCancellations })),

  maxOverviewSymbols: parseInt(env("VITE_MAX_OVERVIEW_SYMBOLS", "250"), 10),

  maxFocusSymbols: parseInt(env("VITE_MAX_FOCUS_SYMBOLS", "25"), 10),
}));
