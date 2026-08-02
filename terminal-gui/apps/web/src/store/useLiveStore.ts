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
  AuctionIndicativeFrame,
  AuctionResultFrame,
  CalfState,
  DepthFrame,
  GapFrame,
  HaltContextFrame,
  IndexFrame,
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

  /**
   * When the last market-data frame arrived, as a local epoch milliseconds.
   *
   * The status strip has always reported *connection* state, which says
   * whether the pipe is open and nothing about whether anything is coming
   * down it. "CALF connected" reads identically when frames are pouring in
   * and when the feed went silent five minutes ago -- and the second is the
   * case a reader most needs to know about, because every price on screen
   * is still sitting there looking current (§ T-M4).
   *
   * Null until the first frame: no data has arrived rather than data that
   * arrived at time zero.
   */
  lastTickAt: number | null;
  calf: CalfState;
  gateway: string | null;
  symbols: string[];
  indexes: string[];

  /** Exchange-wide session phase, from `STATE` under `SYM=*`. */
  sessionPhase: SessionPhase | null;
  /**
   * The next scheduled transition, from the exchange-wide `STATE` stream.
   *
   * Null when nothing is scheduled that the feed knows of -- after a manual
   * transition, or with no scheduler running. That is a real state and must
   * render as silence, not as a countdown to zero (T-M6).
   */
  sessionNextPhase: SessionPhase | null;
  sessionNextAt: string | null;
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

  /**
   * Where each symbol would uncross, while a call phase runs (T-M1).
   *
   * Current state per symbol rather than a log: republished on an interval
   * for the whole of an auction, so only the newest reading means anything.
   * Cleared on a session transition -- an indicative from the opening
   * auction says nothing about the closing one, and leaving it would show a
   * stale price under a live phase badge.
   */
  indicative: Record<string, AuctionIndicativeFrame>;

  /**
   * Trade-tape holes the bridge could not close, newest first (T-H4/T-H5).
   *
   * A record with an unmarked hole in it is worse than no record — people
   * quote from the tape. Kept apart from `trades` rather than spliced in
   * there, since a `GapFrame` is not a print and every reader of `trades`
   * would otherwise have to learn to skip it; `TradeTapeView` merges the two
   * back together for display, where a hole belongs.
   */
  tradeGaps: GapFrame[];

  /**
   * When each symbol last printed, as the trade frame's own timestamp.
   *
   * A grid cannot otherwise distinguish a price from ten seconds ago from one
   * from three hours ago — both render identically, and on an exchange where
   * most symbols are quiet most of the time that is the difference between a
   * live market and a stale number wearing its colour. Unbounded, unlike the
   * tape: one short string per listed symbol is flat in the symbol count, and
   * the universe is the universe.
   */
  lastTradeTs: Record<string, string>;

  /**
   * Per-symbol display precision, from CALF `REF=` via the bridge's `hello`.
   *
   * Absent for a symbol means "the gateway did not say", which is answered
   * with `DEFAULT_TICK_DECIMALS` at the point of formatting rather than by
   * back-filling here — a real 2 and an assumed 2 are different claims, and
   * only the former should be recorded as fact.
   */
  tickDecimals: Record<string, number>;

  /**
   * Latest live level and session per index, keyed by index id.
   *
   * Distinct from `indexes` above, which is the *configured* id list off the
   * SYMBOLS response — that is authoritative for what exists, this is what
   * each one is currently doing.
   */
  indexLive: Record<string, IndexFrame>;
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
  lastTickAt: null as number | null,
  calf: "DOWN" as CalfState,
  gateway: null,
  symbols: [] as string[],
  indexes: [] as string[],
  sessionPhase: null,
  sessionNextPhase: null as SessionPhase | null,
  sessionNextAt: null as string | null,
  sessionPrev: undefined,
  sessionSince: null,
  trades: [] as TradeFrame[],
  indicative: {} as Record<string, AuctionIndicativeFrame>,
  tradeGaps: [] as GapFrame[],
  lastTradeTs: {} as Record<string, string>,
  tickDecimals: {} as Record<string, number>,
  indexLive: {} as Record<string, IndexFrame>,
  halted: {} as Record<string, HaltedSymbol>,
  haltEnded: {} as Record<string, HaltContextFrame>,
  auctions: [] as AuctionResultFrame[],
  top: {} as Record<string, TopOfBook>,
  depth: null as DepthFrame | null,
  midTail: {} as Record<string, LinePoint[]>,
};

/**
 * Frame types that count as market data arriving.
 *
 * Deliberately excludes `hello`, `symbols` and `bridge_status`: those say the
 * bridge is alive and talking, which is exactly what a data-age reading must
 * not be fooled by. A gateway publishing nothing at all still sends them.
 */
const MARKET_DATA_FRAMES: ReadonlySet<ServerFrame["type"]> = new Set([
  "top",
  "trade",
  "state",
  "depth",
  "index",
  "auction_result",
  "halt_context",
  "gap",
]);

/**
 * Fold one frame into the store's state.
 *
 * Free-standing so `applyFrame` can wrap it with the bookkeeping that applies
 * to every frame, rather than every case having to remember it.
 */
function reduceFrame(s: LiveStore, frame: ServerFrame): Partial<LiveStore> {
  switch (frame.type) {
    case "hello":
      return {
        symbols: frame.symbols,
        // Merged, not replaced: a reconnect to a gateway that has lost its
        // engine config would otherwise silently drop every symbol back to
        // the default precision, which is the failure this field exists to
        // prevent.
        tickDecimals: { ...s.tickDecimals, ...frame.tickDecimals },
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

    case "auction_indicative":
      // Keyed by symbol, not appended: this is current state republished on
      // an interval, unlike an uncross result, which is a discrete event
      // worth keeping a log of. A stale reading is superseded, not stacked.
      return { indicative: { ...s.indicative, [frame.sym]: frame } };

    case "auction_result":
      return { auctions: [frame, ...s.auctions].slice(0, AUCTION_BUFFER_MAX) };

    case "depth":
      return { depth: frame };

    case "trade":
      // Newest first, bounded. The Overview still reads its last price
      // off `top` rather than from here, so a row's figures all describe
      // one moment; the tape is a separate record of individual prints.
      // Only the *time* is taken per symbol, for the same reason — it says
      // how fresh the row is without becoming a second source for its price.
      return {
        trades: [frame, ...s.trades].slice(0, TRADE_BUFFER_MAX),
        lastTradeTs: { ...s.lastTradeTs, [frame.sym]: frame.ts },
      };

    case "index":
      // Keyed by index id — an exchange may configure several, and the
      // Index View switches between them without re-subscribing each
      // time. Merged rather than replaced: like TOP, an INDEX frame is a
      // delta, and the SNAP a fresh subscription receives before
      // pm-index has published anything carries no level at all.
      return {
        indexLive: {
          ...s.indexLive,
          [frame.sym]: { ...s.indexLive[frame.sym], ...frame },
        },
      };

    case "gap":
      // The bridge reports a gap on any channel it could not repair, but
      // the Trade Tape is the only view that shows one, and it says
      // "prints were missed" — which is true of a TRADE gap and false of
      // an AUCTION one. Today AUCTION is in fact the commoner of the two
      // (TRADE gaps only reach here when a RESUME came back REPLAY_MISS),
      // so filtering is not a formality: without it most markers on the
      // tape would be describing the wrong stream. A channel is dropped
      // here rather than at the bridge so that a view for it can consume
      // the frame it already receives.
      if (frame.ch !== "TRADE") return {};
      // Newest first, bounded, same as trades — a tab left open all
      // session should not accumulate these without limit either.
      return { tradeGaps: [frame, ...s.tradeGaps].slice(0, TRADE_BUFFER_MAX) };

      // Frames no view consumes yet.
      return {};
  }
}

export const useLiveStore = create<LiveStore>((set, get) => ({
  ...initialState,

  setWsStatus: (wsStatus) => set({ wsStatus }),

  reset: () => set({ ...initialState }),

  applyFrame: (frame) =>
    set((s) => {
      const next = reduceFrame(s, frame);
      // Stamped here rather than inside each case: freshness is a property
      // of the arrival, not of any one channel's payload, and a per-case
      // version would silently stop counting whichever channel someone
      // forgot. Only real market data counts — a `bridge_status` heartbeat
      // means the bridge is alive, which is exactly the thing this is
      // supposed to distinguish itself from (§ T-M4).
      return MARKET_DATA_FRAMES.has(frame.type) ? { ...next, lastTickAt: Date.now() } : next;
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
    // Replaced wholesale, including with nothing: the gateway clears these
    // when the engine transitions without a timetable, and that clearing is
    // the signal. Merging would resurrect a target the feed has disowned.
    return {
      sessionPhase: frame.session,
      sessionPrev: frame.prev,
      sessionSince: frame.ts,
      // An indicative belongs to the call phase it was computed in. The
      // opening auction's says nothing about the closing one, and carrying
      // it across would render a stale price under a live phase badge --
      // the exact shape of wrongness this terminal keeps being reviewed for.
      // Cleared on every exchange transition, including into CONTINUOUS,
      // where there is no auction for it to describe at all.
      indicative: frame.session === s.sessionPhase ? s.indicative : {},
      sessionNextPhase: frame.nextPhase ?? null,
      sessionNextAt: frame.nextAt ?? null,
    };
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
