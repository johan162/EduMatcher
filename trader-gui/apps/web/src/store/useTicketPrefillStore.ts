import { create } from "zustand";
import type { Side } from "@/types/index.js";

/**
 * Click-to-trade prefill intent (§11.4, §16.3).
 *
 * Clicking a depth ladder level records the price (and a suggested side) here;
 * the order ticket (phase 6) reads the latest prefill and populates its form.
 * Keeping it in a tiny dedicated store — rather than reaching into the ticket
 * component — lets the same DepthLadder feed both the Symbol Detail panel and
 * the Trading Workspace DOM without either knowing about the other.
 */
export interface TicketPrefill {
  symbol: string;
  price: number;
  /** Suggested side: clicking the bid column suggests SELL, the ask column BUY. */
  side: Side | null;
  /** Bumped on every prefill so re-clicking the same price still notifies. */
  nonce: number;
}

interface TicketPrefillStore {
  prefill: TicketPrefill | null;
  setPrefill: (p: Omit<TicketPrefill, "nonce">) => void;
  clear: () => void;
}

export const useTicketPrefillStore = create<TicketPrefillStore>((set) => ({
  prefill: null,
  setPrefill: (p) =>
    set((s) => ({ prefill: { ...p, nonce: (s.prefill?.nonce ?? 0) + 1 } })),
  clear: () => set({ prefill: null }),
}));
