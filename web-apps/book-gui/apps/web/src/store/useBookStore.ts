/**
 * The browser's copy of the bridge's view of the watched symbol (design §5.3).
 *
 * Frames for any other symbol are ignored: messages for the previous symbol
 * can still be in flight after a switch, and showing them under the new
 * symbol's name would be a lie (the same rule pm-viewer follows).
 */

import { create } from "zustand";
import type {
  BookFrame,
  ServerFrame,
  SessionStats,
  SymbolInfo,
  TapeTrade,
  UpstreamState,
} from "@edumatcher/book-types";

export type ConnectionState = "LIVE" | "RECONNECTING" | "OFFLINE";

/** Same as the bridge's default `TAPE_MAX`; the browser never needs more than a screenful. */
export const TAPE_MAX = 500;

interface BookStore {
  socketOpen: boolean;
  upstream: UpstreamState | null;
  source: string | null;
  symbols: SymbolInfo[];
  watched: string | null;
  book: BookFrame | null;
  stats: SessionStats | null;
  /** Oldest first. */
  tape: TapeTrade[];
  /** Browser time the last `book` arrived, for the data-age reading. */
  lastBookAt: number | null;
  error: string | null;
  /** Rows each panel currently shows, reported by the book view for the status strip. */
  capacity: number;

  connection: () => ConnectionState;
  setSocketOpen: (open: boolean) => void;
  watch: (sym: string) => void;
  setCapacity: (rows: number) => void;
  apply: (frame: ServerFrame) => void;
}

export const useBookStore = create<BookStore>()((set, get) => ({
  socketOpen: false,
  upstream: null,
  source: null,
  symbols: [],
  watched: null,
  book: null,
  stats: null,
  tape: [],
  lastBookAt: null,
  error: null,
  capacity: 0,

  connection: () => {
    const { socketOpen, upstream } = get();
    if (!socketOpen) return "OFFLINE";
    return upstream === "ACTIVE" ? "LIVE" : "RECONNECTING";
  },

  setSocketOpen: (socketOpen) => set({ socketOpen }),

  watch: (sym) => {
    if (sym === get().watched) return;
    set({ watched: sym, book: null, stats: null, tape: [], lastBookAt: null, error: null });
  },

  setCapacity: (capacity) => set({ capacity }),

  apply: (frame) => {
    const { watched } = get();
    switch (frame.type) {
      case "hello":
        return set({ symbols: frame.symbols, upstream: frame.upstream, source: frame.source });
      case "symbols":
        return set({ symbols: frame.symbols });
      case "bridge_status":
        return set({ upstream: frame.upstream });
      case "book":
        if (frame.sym === watched) set({ book: frame, lastBookAt: Date.now() });
        return;
      case "session":
        if (frame.sym === watched) set({ stats: frame.stats, tape: frame.tape.slice(-TAPE_MAX) });
        return;
      case "trade":
        if (frame.sym === watched) set({ stats: frame.stats, tape: appendById(get().tape, frame.trade) });
        return;
      case "error":
        return set({ error: frame.message });
    }
  },
}));

/** Trade ids sort in print order; a late older print goes where it belongs. */
function appendById(tape: TapeTrade[], trade: TapeTrade): TapeTrade[] {
  const next = [...tape, trade];
  const prev = tape[tape.length - 1];
  if (prev && prev.id > trade.id) next.sort((a, b) => (a.id < b.id ? -1 : 1));
  return next.slice(-TAPE_MAX);
}
