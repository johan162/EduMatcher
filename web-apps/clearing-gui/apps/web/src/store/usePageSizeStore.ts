/**
 * Rows per page, one choice for every table, persisted to localStorage --
 * the same sizes as dash-gui's and terminal-gui's pagers. 0 is "All".
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export const PAGE_SIZES = [10, 30, 50, 100, 0] as const;

export const DEFAULT_PAGE_SIZE = 30;

interface PageSizeStore {
  pageSize: number;
  setPageSize: (pageSize: number) => void;
}

export const usePageSizeStore = create<PageSizeStore>()(
  persist(
    (set) => ({
      pageSize: DEFAULT_PAGE_SIZE,
      setPageSize: (pageSize) => set({ pageSize }),
    }),
    { name: "clearing-page-size" },
  ),
);
