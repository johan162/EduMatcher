/**
 * Translation between `pm-api-gwy`'s market-data WebSocket and `book-types`
 * (design §6, WP2).
 *
 * Pure functions only. Shapes verified against a running gateway in WP0 (the
 * captures live in `test/fixtures/`): every event is `{type, topic, seq, ts,
 * data}`; `book` carries the engine's `book.<SYMBOL>` snapshot and `trade`
 * the `trade.executed` print, both with display-money prices.
 */

import type { BookFrame, Level, TapeTrade, TradeSide } from "@edumatcher/book-types";

export interface Envelope {
  type: string;
  topic?: string;
  seq?: number;
  data: Record<string, unknown>;
}

/** A frame that is not a JSON object with a string `type` is not ours to read. */
export function parseEnvelope(raw: string): Envelope | undefined {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return undefined;
  }
  if (typeof value !== "object" || value === null) return undefined;
  const obj = value as Record<string, unknown>;
  if (typeof obj["type"] !== "string") return undefined;
  const data = obj["data"];
  return {
    type: obj["type"],
    topic: typeof obj["topic"] === "string" ? obj["topic"] : undefined,
    seq: typeof obj["seq"] === "number" ? obj["seq"] : undefined,
    data: typeof data === "object" && data !== null ? (data as Record<string, unknown>) : {},
  };
}

function num(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** Levels with a missing price or qty are skipped, not zero-filled. */
export function toLevels(raw: unknown): Level[] {
  if (!Array.isArray(raw)) return [];
  const levels: Level[] = [];
  for (const entry of raw) {
    if (typeof entry !== "object" || entry === null) continue;
    const lvl = entry as Record<string, unknown>;
    const price = num(lvl["price"]);
    const qty = num(lvl["qty"]);
    if (price === undefined || qty === undefined) continue;
    levels.push({ price, qty, count: num(lvl["count"]) ?? 0 });
  }
  return levels;
}

/** `last_price`/`last_qty` are null until a symbol first trades; absent here, never 0. */
export function toBookFrame(env: Envelope, fallbackDecimals: number): BookFrame | undefined {
  const sym = env.data["symbol"];
  if (typeof sym !== "string" || sym === "") return undefined;
  const frame: BookFrame = {
    type: "book",
    sym: sym.toUpperCase(),
    seq: env.seq ?? 0,
    tickDecimals: num(env.data["tick_decimals"]) ?? fallbackDecimals,
    bids: toLevels(env.data["bids"]),
    asks: toLevels(env.data["asks"]),
  };
  const last = num(env.data["last_price"]);
  const lastQty = num(env.data["last_qty"]);
  if (last !== undefined) frame.last = last;
  if (lastQty !== undefined) frame.lastQty = lastQty;
  return frame;
}

function side(raw: unknown): TradeSide {
  return raw === "BUY" || raw === "SELL" || raw === "AUCTION" ? raw : "";
}

/** A live `trade.executed` print. `ts_ns` exceeds 2^53, so it is only ever read to the millisecond. */
export function toLiveTrade(data: Record<string, unknown>): { sym: string; trade: TapeTrade } | undefined {
  const id = data["id"];
  const sym = data["symbol"];
  const px = num(data["price"]);
  const qty = num(data["quantity"]);
  const tsNs = num(data["ts_ns"]);
  if (typeof id !== "string" || typeof sym !== "string" || px === undefined || qty === undefined) {
    return undefined;
  }
  return {
    sym: sym.toUpperCase(),
    trade: {
      id,
      tsMs: tsNs === undefined ? 0 : Math.floor(tsNs / 1e6),
      px,
      qty,
      side: side(data["aggressor_side"]),
    },
  };
}

/** One `/history/trades` row: `trade_id`, ISO `ts`, display-money `price`. */
export function historyRowToTrade(row: Record<string, unknown>): TapeTrade | undefined {
  const id = row["trade_id"];
  const ts = row["ts"];
  const px = num(row["price"]);
  const qty = num(row["quantity"]);
  if (typeof id !== "string" || typeof ts !== "string" || px === undefined || qty === undefined) {
    return undefined;
  }
  return { id, tsMs: Date.parse(ts), px, qty, side: side(row["aggressor_side"]) };
}

export const authFrame = (apiKey: string) => JSON.stringify({ api_key: apiKey });

/**
 * One item per symbol, so a `resume_from` hint applies to that symbol alone.
 * The hint makes the gateway replay the prints after it instead of sending
 * its whole cached tail.
 */
export function subscribeFrame(sym: string, resumeFromTradeSeq?: number): string {
  const item: Record<string, unknown> = { symbols: [sym], channels: ["book", "trades"] };
  if (resumeFromTradeSeq !== undefined) item["resume_from"] = { trades: resumeFromTradeSeq };
  return JSON.stringify({ action: "subscribe", items: [item] });
}

export function unsubscribeFrame(sym: string): string {
  return JSON.stringify({ action: "unsubscribe", items: [{ symbols: [sym], channels: ["book", "trades"] }] });
}

/** `trade.executed` is not symbol-qualified, so the symbol rides in `symbols`. */
export function resumeTradesFrame(sym: string, fromSeq: number): string {
  return JSON.stringify({ action: "resume", topic: "trade.executed", symbols: [sym], from_seq: fromSeq });
}
