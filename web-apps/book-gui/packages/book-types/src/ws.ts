/**
 * Bridge <-> browser WebSocket frame schema (design §8).
 *
 * One flat JSON object per frame, discriminated by `type`. Prices are display
 * money, exactly as `pm-api-gwy` sends them; times are epoch milliseconds.
 * The browser never sees `pm-api-gwy`'s envelope or its credential.
 */

/** Health of the bridge's single upstream market-data connection. */
export type UpstreamState = "ACTIVE" | "RECONNECTING" | "DOWN";

export interface SymbolInfo {
  symbol: string;
  tickDecimals: number;
}

/** One aggregated price level, best price first on each side. */
export interface Level {
  price: number;
  qty: number;
  count: number;
}

/** `AUCTION` marks an uncross print, where both sides rested. */
export type TradeSide = "BUY" | "SELL" | "AUCTION" | "";

export interface TapeTrade {
  /** Durable engine trade id; fixed-width, so it sorts in print order. */
  id: string;
  tsMs: number;
  px: number;
  qty: number;
  side: TradeSide;
}

/**
 * The session's statistics for one symbol, built from its trades.
 *
 * `partial` is true when history could not be read, so the figures cover
 * only the trades seen live since `since` — the web equivalent of pm-viewer
 * running without a stats database.
 */
export interface SessionStats {
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  prevClose?: number;
  volume: number;
  tradeCount: number;
  partial: boolean;
  since?: number;
  /** Trading date in the exchange session timezone, `YYYY-MM-DD`. */
  sessionDate?: string;
  /** IANA name of the exchange session timezone; UTC when unknown. */
  timezone: string;
}

export interface HelloFrame {
  type: "hello";
  symbols: SymbolInfo[];
  upstream: UpstreamState;
  /** `host:port` of the `pm-api-gwy` instance the bridge reads. */
  source: string;
}

export interface BookFrame {
  type: "book";
  sym: string;
  seq: number;
  tickDecimals: number;
  bids: Level[];
  asks: Level[];
  last?: number;
  lastQty?: number;
}

/** Full tape and stats for a symbol: on watch, and after every (re)seed. */
export interface SessionFrame {
  type: "session";
  sym: string;
  stats: SessionStats;
  /** Oldest first. */
  tape: TapeTrade[];
}

/** One new print, with the stats it produced. */
export interface TradeFrame {
  type: "trade";
  sym: string;
  trade: TapeTrade;
  stats: SessionStats;
}

export interface SymbolsFrame {
  type: "symbols";
  symbols: SymbolInfo[];
}

export interface BridgeStatusFrame {
  type: "bridge_status";
  upstream: UpstreamState;
  since: string;
  wsClients: number;
}

export interface ErrorFrame {
  type: "error";
  code: "UNKNOWN_SYMBOL";
  sym: string;
  message: string;
}

export type ServerFrame =
  HelloFrame | BookFrame | SessionFrame | TradeFrame | SymbolsFrame | BridgeStatusFrame | ErrorFrame;

/** One symbol per tab; a `watch` replaces the previous one. */
export type ClientFrame = { t: "watch"; sym: string } | { t: "ping" };
