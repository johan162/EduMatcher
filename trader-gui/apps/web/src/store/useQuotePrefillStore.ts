import { create } from "zustand";

/**
 * Re-quote prefill intent (§14.1.2). Clicking "Re-quote" on a fill-alert toast
 * (or a card's New Quote button) records the previous quote's values here; the
 * New Quote form reads the latest prefill for its symbol and populates. A tiny
 * dedicated store — like {@link useTicketPrefillStore} — so the toast handler,
 * the card, and the form need not know about each other.
 */
export interface QuotePrefill {
  symbol: string;
  bid_price: number | null;
  bid_qty: number | null;
  ask_price: number | null;
  ask_qty: number | null;
  quote_id: string;
  /** Bumped on every prefill so re-triggering for the same symbol still fires. */
  nonce: number;
}

interface QuotePrefillStore {
  prefill: QuotePrefill | null;
  setPrefill: (p: Omit<QuotePrefill, "nonce">) => void;
  clear: () => void;
}

export const useQuotePrefillStore = create<QuotePrefillStore>((set) => ({
  prefill: null,
  setPrefill: (p) => set((s) => ({ prefill: { ...p, nonce: (s.prefill?.nonce ?? 0) + 1 } })),
  clear: () => set({ prefill: null }),
}));
