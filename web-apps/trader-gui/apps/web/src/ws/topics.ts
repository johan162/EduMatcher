/**
 * Engine topic ↔ market-data channel mapping.
 *
 * Mirrors `api_gateway/market_cache.py::channel_for_topic`. `seq` counts
 * within a **topic**, not a type — one `type: "depth"` spans `depth.AAPL`,
 * `depth.MSFT`, each with its own counter — so gap detection and the
 * `resume` verb both key on the topic string.
 */
import type { MarketDataChannel } from "./subscriptions.js";

export const TOPIC_TRADE_EXECUTED = "trade.executed";
export const TOPIC_SESSION_STATE = "session.state";
export const PREFIX_BOOK = "book.";
export const PREFIX_DEPTH = "depth.";
export const PREFIX_AUCTION_RESULT = "auction.result.";
export const PREFIX_AUCTION_INDICATIVE = "auction.indicative.";

/** Channel a topic belongs to, or null if it is not a subscribable channel. */
export function channelForTopic(topic: string): MarketDataChannel | null {
  if (topic === TOPIC_TRADE_EXECUTED) return "trades";
  if (topic.startsWith(PREFIX_AUCTION_RESULT) || topic.startsWith(PREFIX_AUCTION_INDICATIVE)) {
    return "auction";
  }
  // `auction.*` is tested first: `book.`/`depth.` cannot collide, but the
  // ordering keeps the parallel with the server-side classifier exact.
  if (topic.startsWith(PREFIX_BOOK)) return "book";
  if (topic.startsWith(PREFIX_DEPTH)) return "depth";
  return null;
}

/**
 * The topic string(s) a `(symbol, channel)` subscription pair maps to --
 * the inverse of `channelForTopic`/`symbolForTopic`. `auction` covers two
 * topics (result and indicative), each with its own independent `seq`.
 * `trades` returns none: `trade.executed` is venue-wide, shared by every
 * focus symbol, so no single symbol's pair owns it (used by L5 to reset only
 * the topics a real unsubscribe actually stops receiving).
 */
export function topicsForPair(symbol: string, channel: MarketDataChannel): string[] {
  switch (channel) {
    case "book":
      return [`${PREFIX_BOOK}${symbol}`];
    case "depth":
      return [`${PREFIX_DEPTH}${symbol}`];
    case "auction":
      return [`${PREFIX_AUCTION_RESULT}${symbol}`, `${PREFIX_AUCTION_INDICATIVE}${symbol}`];
    case "trades":
      return [];
  }
}

/**
 * Symbol a topic names, or null when the topic is venue-wide.
 * `trade.executed` is a single topic for every symbol, so its symbol comes
 * from the payload, not the topic.
 */
export function symbolForTopic(topic: string): string | null {
  for (const prefix of [
    PREFIX_AUCTION_INDICATIVE,
    PREFIX_AUCTION_RESULT,
    PREFIX_BOOK,
    PREFIX_DEPTH,
  ]) {
    if (topic.startsWith(prefix)) return topic.slice(prefix.length).toUpperCase();
  }
  return null;
}
