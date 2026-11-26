/**
 * Explain mode (CG25, D7), one choice for the whole app, persisted to
 * localStorage. On by default: the clearing GUI is a teaching tool first.
 * On, figures show how they are made (formulas, explain lines, pictures);
 * off, the screens are the compact operator view. Words beside signs and the
 * teaching empty states do not depend on it.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ExplainStore {
  explain: boolean;
  setExplain: (explain: boolean) => void;
}

export const useExplainStore = create<ExplainStore>()(
  persist(
    (set) => ({
      explain: true,
      setExplain: (explain) => set({ explain }),
    }),
    { name: "clearing-explain" },
  ),
);
