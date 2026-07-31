/**
 * Market-data shapes shared by the bridge and the browser (design §17.3).
 *
 * These are the *decoded* forms — numbers, not the CALF wire's text. The
 * pipe/colon/comma grammar never leaves `packages/calf-protocol`.
 */

/** One aggregated depth level: `[price, qty, orderCount]` (design §14.4). */
export type DepthLevel = [price: number, qty: number, count: number];

/** CALF `TRADE.SIDE` carries the engine's `aggressor_side`. */
export type TradeSide = "BUY" | "SELL" | "";

/**
 * Session phase as reported by CALF `STATE.SESSION`.
 *
 * Deliberately a plain `string` rather than a union: the engine's session
 * vocabulary is its own concern and this application only ever displays the
 * value, so pinning a union here would mean a terminal release for every new
 * engine phase. Known values today are CONTINUOUS, OPENING_AUCTION,
 * CLOSING_AUCTION, HALTED, CLOSED and PREOPEN.
 */
export type SessionPhase = string;

/** CALF `CB.STATUS` (`src/edumatcher/md_gateway/normaliser.py`, `CBStatus`). */
export type CbStatus = "ACTIVE" | "HALTED";

/** Side of the imbalance reported on an ACE corridor expansion. */
export type ImbalanceSide = "BUY" | "SELL";

/** Why a halt ended, when it was not simply the call phase expiring. */
export type HaltEndReason = "CLOSING_BACKSTOP";

/**
 * Top-of-book state for one symbol.
 *
 * Every field is optional because CALF `MD` messages are *deltas* — the
 * gateway's `normalise_book` only emits fields whose value changed since the
 * previous publish, and a `SNAP` for a symbol that has never traded carries
 * no `LAST`/`LASTSZ` at all. The bridge merges deltas into this shape before
 * fanning out, so a browser tab never has to (design §17.3, corrected).
 */
export interface TopOfBook {
  bid?: number;
  bidSz?: number;
  ask?: number;
  askSz?: number;
  last?: number;
  lastSz?: number;
}
