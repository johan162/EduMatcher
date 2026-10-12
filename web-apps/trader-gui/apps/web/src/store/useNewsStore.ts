import { create } from "zustand";
import type { NewsEvent, NewsSnapshot } from "@/types/index.js";

/** Headlines kept, like the API gateway's own buffer. */
export const NEWS_KEPT = 200;

export interface NewsStore {
  /** Newest first, at most NEWS_KEPT, one per id. */
  items: NewsEvent[];
  /** Symbol -> sector, to tell which symbols a SECTOR headline is about. */
  sectorOf: Record<string, string>;
  /** Replace everything from GET /news (bootstrap and every reconnect). */
  load: (snapshot: NewsSnapshot) => void;
  /** One live headline from the market-data socket. */
  add: (item: NewsEvent) => void;
}

export const useNewsStore = create<NewsStore>((set) => ({
  items: [],
  sectorOf: {},

  load: (snapshot) => {
    const sectorOf: Record<string, string> = {};
    for (const [sector, symbols] of Object.entries(snapshot.sectors)) {
      for (const symbol of symbols) sectorOf[symbol] = sector;
    }
    set({ items: [...snapshot.news].reverse().slice(0, NEWS_KEPT), sectorOf });
  },

  add: (item) =>
    set((s) =>
      s.items.some((n) => n.id === item.id) ? s : { items: [item, ...s.items].slice(0, NEWS_KEPT) },
    ),
}));
