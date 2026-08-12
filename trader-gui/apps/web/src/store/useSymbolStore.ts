import { create } from "zustand";
import type { Symbol } from "@/types/index.js";

export interface SymbolStore {
  symbols: Symbol[];
  setSymbols: (list: Symbol[]) => void;
  /** Look up a single symbol by name. */
  get: (sym: string) => Symbol | undefined;
}

export const useSymbolStore = create<SymbolStore>((set, get) => ({
  symbols: [],

  setSymbols: (list) => set({ symbols: list }),

  get: (sym) => get().symbols.find((s) => s.symbol === sym),
}));
