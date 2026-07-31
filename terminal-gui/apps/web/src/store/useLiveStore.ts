/**
 * Zustand store — synchronous, in-memory, ephemeral live state (design §16).
 *
 * Everything here is driven by bridge WS frames and is lost on reload, which
 * is correct for a viewer: the bridge re-sends a `hello` plus fresh `SNAP`
 * baselines on every reconnect, so there is nothing worth persisting. REST
 * history lives in TanStack Query instead.
 *
 * `applyFrame` is the single entry point for inbound frames, kept as a plain
 * action so it can be driven directly in tests without a socket.
 */

import { create } from "zustand";
import type {
  AuctionResultFrame,
  CalfState,
  DepthFrame,
  HaltContextFrame,
  TradeFrame,
  ServerFrame,
  SessionPhase,
  TopOfBook,
} from "@edumatcher/terminal-types";
import { midOf, type LinePoint } from "../lib/bars.js";
import type { WsStatus } from "../lib/ws.js";

/**
 * Session-scoped ring buffer for auction results (design §13.1). Bounded so a
 * long-running lobby display cannot grow without limit; this is a "what just
 * happened" board, not an audit log.
 */
const AUCTION_BUFFER_MAX = 200;
/** Design §11.1: "last ~500 prints, client-side" keeps memory flat. */
const TRADE_BUFFER_MAX = 500;

/**
 * Live midpoint points kept per symbol. At one tick per book republish this is
 * roughly an hour of tail — enough to splice onto the recorded history without
 * a long-lived tab growing without bound.
 */
const MID_TAIL_MAX = 5_000;

/** What the top bar's indicator shows (design §7.4). */
export type ConnectionState = "LIVE" | "RECONNECTING" | "OFFLINE";

export interface HaltedSymbol {
  sym: string;
  /** Phase the symbol was in before halting, from `STATE.PREV`. */
  prev?: SessionPhase;
  /** Timestamp of the `STATE` transition into `HALTED`. */
  since: string;
  /** From CALF `CB`; absent until that channel's frame arrives. */
  context?: HaltContextFrame;
}

interface LiveStore {
  wsStatus: WsStatus;
  calf: CalfState;
  gateway: string | null;
  symbols: string[];
  indexes: string[];

  /** Exchange-wide session phase, from `STATE` under `SYM=*`. */
  sessionPhase: SessionPhase | null;
  sessionPrev?: SessionPhase;
  sessionSince: string | null;

  /**
   * Cross-symbol print tape, newest first.
   *
   * Bounded rather than complete: a busy exchange prints faster than anyone
   * reads, and an unbounded array would grow without limit for a view that
   * only ever shows the most recent screenful.
   */
  trades: TradeFrame[];
  halted: Record<string, HaltedSymbol>;
  /**
   * The frame that ended each symbol's most recent halt.
   *
   * Kept because a resume is the only place the end-of-day backstop reports
   * itself — that it printed at the corridor boundary rather than at a price
   * the book discovered. The halt is gone by then, so there is nowhere in
   * `halted` for it to live, and dropping the frame would lose the one fact
   * that distinguishes an imposed close from an ordinary one.
   */
  haltEnded: Record<string, HaltContextFrame>;
  auctions: AuctionResultFrame[];
  top: Record<string, TopOfBook>;

  /**
   * Depth ladder for whichever symbol currently has the toggle on.
   *
   * One symbol, not a map: `DEPTH` costs a real per-symbol CALF subscription
   * (§14.4 — the gateway rejects `SYM=*` for it), and the bridge only holds it
   * while a tab is looking. Keeping a map would imply we retain ladders we are
   * no longer subscribed to and would show a frozen book after switching away.
   */
  depth: DepthFrame | null;

  /**
   * Live bid/ask midpoint tail per symbol, for the Symbol Detail chart (§9.3).
   *
   * Bounded: this grows on every `TOP` tick for every symbol, and an
   * unattended tab left open all session would otherwise accumulate without
   * limit.
   */
  midTail: Record<string, LinePoint[]>;

  setWsStatus: (status: WsStatus) => void;
  applyFrame: (frame: ServerFrame) => void;
  reset: () => void;

  connectionState: () => ConnectionState;
  haltedList: () => HaltedSymbol[];
}

const initialState = {
  wsStatus: "connecting" as WsStatus,
  calf: "DOWN" as CalfState,
  gateway: null,
  symbols: [] as string[],
  indexes: [] as string[],
  sessionPhase: null,
  sessionPrev: undefined,
  sessionSince: null,
  trades: [] as TradeFrame[],
  halted: {} as Record<string, HaltedSymbol>,
  haltEnded: {} as Record<string, HaltContextFrame>,
  auctions: [] as AuctionResultFrame[],
  top: {} as Record<string, TopOfBook>,
  depth: null as DepthFrame | null,
  midTail: {} as Record<string, LinePoint[]>,
};

export const useLiveStore = create<LiveStore>((set, get) => ({
  ...initialState,

  setWsStatus: (wsStatus) => set({ wsStatus }),

  reset: () => set({ ...initialState }),

  applyFrame: (frame) =>
    set((s) => {
      switch (frame.type) {
        case "hello":
          return {
            symbols: frame.symbols,
            indexes: frame.indexes,
            calf: frame.calf,
            gateway: frame.gateway,
          };

        case "symbols":
          return { symbols: frame.symbols };

        case "bridge_status":
          return { calf: frame.calf };

        case "top": {
          // The bridge already merged the CALF delta, so this is the full
          // current book for the symbol and replaces rather than merges.
          const book = frameToTop(frame);
          const patch: Partial<LiveStore> = { top: { ...s.top, [frame.sym]: book } };

          const mid = midOf(book.bid, book.ask);
          const at = Date.parse(frame.ts);
          if (mid !== undefined && !Number.isNaN(at)) {
            const point = { time: Math.floor(at / 1000), value: mid };
            const tail = [...(s.midTail[frame.sym] ?? []), point].slice(-MID_TAIL_MAX);
            patch.midTail = { ...s.midTail, [frame.sym]: tail };
          }
          return patch;
        }

        case "state":
          return applyState(s, frame);

        case "halt_context":
          return applyHaltContext(s, frame);

        case "auction_result":
          return { auctions: [frame, ...s.auctions].slice(0, AUCTION_BUFFER_MAX) };

        case "depth":
          return { depth: frame };

        case "trade":
          // Newest first, bounded. The Overview still reads its last price
          // off `top` rather than from here, so a row's figures all describe
          // one moment; the tape is a separate record of individual prints.
          return { trades: [frame, ...s.trades].slice(0, TRADE_BUFFER_MAX) };

        // Frames no view consumes yet.
        case "index":
          return {};
      }
    }),

  connectionState: () => {
    const s = get();
    // Our own socket being down outranks anything it might have told us
    // about CALF, since that information is now arbitrarily stale (§7.4).
    if (s.wsStatus !== "open") return "OFFLINE";
    return s.calf === "ACTIVE" ? "LIVE" : "RECONNECTING";
  },

  haltedList: () => sortHalted(get().halted),
}));

/**
 * Halted symbols in a stable display order.
 *
 * Free-standing rather than a store getter because it builds a new array on
 * every call: a component selecting it directly would fail Zustand's identity
 * check each render and loop forever. Components select `halted` and memoise
 * this; the store getter exists for tests and non-reactive callers.
 */
export function sortHalted(halted: Record<string, HaltedSymbol>): HaltedSymbol[] {
  return Object.values(halted).sort((a, b) => a.sym.localeCompare(b.sym));
}

function frameToTop(frame: Extract<ServerFrame, { type: "top" }>): TopOfBook {
  const { type: _type, sym: _sym, seq: _seq, ts: _ts, ...book } = frame;
  return book;
}

/**
 * A `STATE` frame is either an exchange-wide phase change (`SYM=*`) or one
 * symbol halting or resuming. The two look identical on the wire apart from
 * the symbol, which design §17.3's single example did not make obvious.
 */
function applyState(s: LiveStore, frame: Extract<ServerFrame, { type: "state" }>): Partial<LiveStore> {
  if (frame.sym === "*") {
    return { sessionPhase: frame.session, sessionPrev: frame.prev, sessionSince: frame.ts };
  }

  if (frame.session === "HALTED") {
    const existing = s.halted[frame.sym];
    // Re-halting an already-halted symbol keeps the original `since` — the
    // board should show how long it has actually been down.
    if (existing) return {};
    const entry: HaltedSymbol = { sym: frame.sym, since: frame.ts };
    if (frame.prev !== undefined) entry.prev = frame.prev;
    return { halted: { ...s.halted, [frame.sym]: entry } };
  }

  if (!(frame.sym in s.halted)) return {};
  const { [frame.sym]: _resumed, ...rest } = s.halted;
  return { halted: rest };
}

/**
 * `CB` detail is layered onto an existing halt rather than creating one:
 * `STATE` is the authority on *whether* a symbol is halted, `CB` only adds
 * why (design §9.3a). A `CB` for a symbol with no halt on record is dropped —
 * that is a resume arriving after the `STATE` that already cleared it.
 */
function applyHaltContext(s: LiveStore, frame: HaltContextFrame): Partial<LiveStore> {
  if (frame.status !== "HALTED") {
    // A resume. `halted` is cleared by the STATE frame that accompanies it,
    // so the only thing to do here is retain how the halt ended.
    return { haltEnded: { ...s.haltEnded, [frame.sym]: frame } };
  }
  const existing = s.halted[frame.sym];
  if (!existing) return {};
  // An ACE extension arrives as a further HALTED frame carrying the widened
  // corridor and a new resume time; the gateway resends the halt's own detail
  // with it, so replacing wholesale keeps the two consistent.
  return { halted: { ...s.halted, [frame.sym]: { ...existing, context: frame } } };
}
