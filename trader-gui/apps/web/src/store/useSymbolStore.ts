import { create } from "zustand";
import type { Symbol, ReferenceSymbol } from "@/types/index.js";

export interface SymbolStore {
  symbols: Symbol[];
  setSymbols: (list: Symbol[]) => void;
  /**
   * Seed from the reference bundle (login bootstrap). Carries `tick_decimals`
   * and the collar `level`; `prev_close` and `reference_price` come from
   * `GET /symbols` and the live risk state respectively and are merged in
   * later by the screens that need them, so they start null rather than 0.
   */
  hydrateFromReference: (list: ReferenceSymbol[]) => void;
  /** Look up a single symbol by name. */
  get: (sym: string) => Symbol | undefined;
}

export const useSymbolStore = create<SymbolStore>((set, get) => ({
  symbols: [],

  setSymbols: (list) => set({ symbols: list }),

  hydrateFromReference: (list) =>
    set((s) => {
      const existing = new Map(s.symbols.map((e) => [e.symbol, e]));
      return {
        symbols: list.map((r) => {
          const prev = existing.get(r.symbol);
          return {
            symbol: r.symbol,
            tick_decimals: r.tick_decimals,
            prev_close: prev?.prev_close ?? null,
            reference_price: prev?.reference_price ?? null,
            level: r.level ?? null,
          };
        }),
      };
    }),

  get: (sym) => get().symbols.find((s) => s.symbol === sym),
}));
