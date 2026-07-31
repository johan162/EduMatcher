/**
 * Bridge <-> browser WebSocket frame schema (design §17.3).
 *
 * One flat JSON object per CALF line, discriminated by `type`. The browser
 * never parses CALF's pipe-delimited grammar — that translation happens once,
 * server-side, in `packages/calf-protocol`.
 *
 * Two corrections to design §17.3, both verified against the shipped
 * `md_gateway` normaliser:
 *
 *   - `halt_context.resumeAt` is an ISO-8601 string, not `resumeAtNs`.
 *     `normaliser._ns_to_iso()` converts the engine's `resume_at_ns` to CALF's
 *     usual ISO text before it ever reaches the wire.
 *   - `top` frames carry the bridge's *merged* view of a symbol, not the raw
 *     CALF `MD` delta. Fields still absent from that merged view (a symbol
 *     with no trades yet, say) are omitted rather than zero-filled.
 */

import type {
  CbStatus,
  DepthLevel,
  HaltEndReason,
  ImbalanceSide,
  SessionPhase,
  TradeSide,
} from "./market.js";

/** Health of the bridge's single upstream CALF connection (design §6.6, §7.4). */
export type CalfState = "ACTIVE" | "RECONNECTING" | "DOWN";

/** Per-symbol CALF channels a browser tab can express interest in (design §6.5). */
export type WatchChannel = "DEPTH" | "CB";

export interface HelloFrame {
  type: "hello";
  /** From CALF `WELCOME|SYMBOLS=`, plus any symbol seen live since (design §6.3). */
  symbols: string[];
  /**
   * Per-symbol display precision, from CALF `REF=`.
   *
   * Static reference data, so it arrives once on the handshake rather than on
   * a market data channel — `tick_decimals` never changes for a symbol, and a
   * constant repeated on every `TOP` would be the one thing `MD`'s delta
   * encoding exists to avoid.
   *
   * Empty against a gateway that predates the field. A symbol missing from it
   * renders at `DEFAULT_TICK_DECIMALS`, which is what the rest of the exchange
   * assumes for an unregistered symbol.
   */
  tickDecimals: Record<string, number>;
  /** From bridge config — CALF has no "list the indexes" request. */
  indexes: string[];
  calf: CalfState;
  /** Gateway name from `WELCOME|GW=`, or null before the first handshake. */
  gateway: string | null;
}

export interface TopFrame {
  type: "top";
  sym: string;
  seq: number;
  ts: string;
  bid?: number;
  bidSz?: number;
  ask?: number;
  askSz?: number;
  last?: number;
  lastSz?: number;
}

export interface TradeFrame {
  type: "trade";
  sym: string;
  seq: number;
  ts: string;
  px: number;
  qty: number;
  side: TradeSide;
}

export interface StateFrame {
  type: "state";
  /**
   * `"*"` for an exchange-wide session transition, a concrete symbol for a
   * per-symbol halt/resume. Both arrive on the bridge's single
   * `SUB|CH=STATE|SYM=*` subscription — the gateway emits session-wide
   * transitions under the literal symbol `*` (`normalise_session_state`
   * returns `"*"`), which design §17.3's single worked example did not show.
   */
  sym: string;
  seq: number;
  ts: string;
  session: SessionPhase;
  prev?: SessionPhase;
}

export interface IndexFrame {
  type: "index";
  sym: string;
  seq: number;
  ts: string;
  /**
   * Absent on the `SNAP` a fresh `SUB|CH=INDEX` receives before pm-index has
   * published its first `index.update` — `index_snapshot_fields` returns an
   * empty map in that case, so the whole frame is metadata-only.
   */
  level?: number;
  chg?: number;
  pctChg?: number;
  open?: number;
  high?: number;
  low?: number;
  session?: SessionPhase;
  aggCap?: number;
}

export interface DepthFrame {
  type: "depth";
  sym: string;
  seq: number;
  ts: string;
  levels: number;
  /** Full-ladder replace per message, never a per-level diff (design §14.4). */
  bids: DepthLevel[];
  asks: DepthLevel[];
}

export type AuctionReason = "SCHEDULED" | "REOPEN" | "RECOVERY";

export type HaltSource = "CB" | "ADMIN";

export interface AuctionResultFrame {
  type: "auction_result";
  sym: string;
  seq: number;
  ts: string;
  /** Omitted on a no-cross auction (`EQPX` absent on the wire). */
  eqPrice?: number;
  eqQty: number;
  tradesCount: number;
  imbalanceSide?: string;
  imbalanceQty: number;
  /**
   * Which uncross this was. A scheduled open/close, a halted symbol
   * reopening, and the startup pass over restored GTC orders are otherwise
   * identical on the wire. Absent from a gateway that predates the field.
   */
  reason?: AuctionReason;
}

export interface HaltContextFrame {
  type: "halt_context";
  sym: string;
  seq: number;
  ts: string;
  status: CbStatus;
  /** CB ladder level, or `ADMIN_ALL`/`ADMIN_SYMBOL` for an operator halt. */
  level?: string;
  /** Absent for operator-initiated halts and for every resume. */
  triggerPrice?: number;
  referencePrice?: number;
  /** ISO-8601. Absent for manual/rest-of-day halts with no scheduled resume. */
  resumeAt?: string;
  /**
   * What halted the symbol — a circuit breaker or an operator. Not how it
   * resumes: a halt is the call phase of a reopening auction and always ends
   * in an uncross, so there is nothing to vary there.
   */
  haltSource?: HaltSource;

  // --- Automated Corridor Expansion -------------------------------------
  /**
   * Bounds the symbol is permitted to reopen inside. Part of the halt's
   * current state, so it survives into the `SNAP` a late subscriber gets.
   */
  corridorLow?: number;
  corridorHigh?: number;
  /** Extensions consumed so far; 0 on the initial halt. */
  expansion?: number;
  /**
   * Indicative uncross price at the moment a call phase ended — i.e. where
   * the symbol *would* have reopened. Present only on an extension event,
   * never in a snapshot: it is a point-in-time observation of a book that
   * keeps moving, so replaying it later would assert a stale price.
   */
  indicativePrice?: number;
  indicativeQty?: number;
  /** Which side the imbalance ran at that moment. Extension events only. */
  imbalanceSide?: ImbalanceSide;

  // --- End-of-day backstop ----------------------------------------------
  /** `CLOSING_BACKSTOP` when the trading day forced the resume. */
  reason?: HaltEndReason;
  /**
   * True when the backstop printed *at* the corridor boundary rather than at
   * the equilibrium. Such a price was imposed, not discovered, and a viewer
   * that presented it as an ordinary print would misrepresent the close.
   */
  clamped?: boolean;
  printPrice?: number;
}

/**
 * A refreshed instrument universe.
 *
 * Sent when the bridge learns of symbols after a tab's `hello` — from the
 * gateway's answer to a `SYMBOLS` request, or from a symbol first appearing on
 * the live wire. Without it a tab that connected before the gateway knew any
 * instruments would sit on an empty list indefinitely.
 */
export interface SymbolsFrame {
  type: "symbols";
  symbols: string[];
}

export interface BridgeStatusFrame {
  type: "bridge_status";
  calf: CalfState;
  since: string;
  wsClients: number;
}

export type ServerFrame =
  | HelloFrame
  | TopFrame
  | TradeFrame
  | StateFrame
  | IndexFrame
  | DepthFrame
  | AuctionResultFrame
  | HaltContextFrame
  | SymbolsFrame
  | BridgeStatusFrame;

/**
 * Browser -> bridge control frames.
 *
 * `TOP`/`TRADE`/`STATE`/`AUCTION`/`INDEX` need none of these: the bridge holds
 * them always-on and pushes them to every tab (design §6.4). Only the two
 * per-symbol channels — which CALF refuses to serve under `SYM=*` — need a tab
 * to declare interest.
 */
export type ClientFrame =
  | { t: "subscribe"; ch: WatchChannel; sym: string }
  | { t: "unsubscribe"; ch: WatchChannel; sym: string }
  /**
   * Session & Halt board open/closed. While open, this tab counts as an
   * interested party for `CB` on *every* currently halted symbol, without
   * having to name them itself (design §13.2).
   */
  | { t: "halt_board"; open: boolean }
  | { t: "ping" };
