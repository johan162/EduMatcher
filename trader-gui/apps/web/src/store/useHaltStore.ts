import { create } from "zustand";
import type { HaltEntry } from "@/types/index.js";

export interface HaltStore {
  halts: Record<string, HaltEntry>;
  setHalt: (symbol: string, data: HaltEntry) => void;
  clearHalt: (symbol: string) => void;
  /** Bulk-load from GET /api/v1/admin/halts bootstrap. */
  setHalts: (entries: HaltEntry[]) => void;
  /** True if the symbol is currently halted. */
  isHalted: (symbol: string) => boolean;
}

export const useHaltStore = create<HaltStore>((set, get) => ({
  halts: {},

  setHalt: (symbol, data) =>
    set((s) => ({
      halts: { ...s.halts, [symbol]: data },
    })),

  clearHalt: (symbol) =>
    set((s) => {
      const next = { ...s.halts };
      delete next[symbol];
      return { halts: next };
    }),

  isHalted: (symbol) => get().halts[symbol] !== undefined,

  setHalts: (entries) => {
    const map: Record<string, HaltEntry> = {};
    for (const e of entries) {
      map[e.symbol] = e;
    }
    set({ halts: map });
  },
}));
