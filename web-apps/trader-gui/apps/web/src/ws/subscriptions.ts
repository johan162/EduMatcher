/**
 * Market-data subscription planning (§17.3.1, §17.3.4).
 *
 * The gateway holds a subscription as a set of `(symbol, channel)` **pairs**,
 * not as a symbol set crossed with a channel set — "book for every symbol,
 * depth for AAPL only" is expressible only that way. This module mirrors that
 * model client-side so the UI can compute a *desired* pair set, diff it
 * against what the server has been told, and send the minimum number of
 * subscribe/unsubscribe items.
 *
 * Two items make up the plan:
 *  - the **broad** item — `*` on `book`/`trades`, feeding Market Overview
 *  - the **focus** item — the active symbol plus watchlist, on the heavy
 *    channels (`depth`/`auction`), which are full snapshots with no delta
 *    form and must never be requested with a wildcard (§17.3.4)
 *
 * When the broad item is active, the focus item deliberately carries only
 * `depth`/`auction`: `book`/`trades` are already covered by the wildcard, and
 * re-requesting them per symbol would make every focus-symbol unsubscribe
 * come back as `wildcard_still_subscribed`. With the broad item off (e.g. a
 * screen that only shows the focus set), the focus item widens to all four.
 */

export type MarketDataChannel = "book" | "trades" | "depth" | "auction";

export const WILDCARD = "*";

/** Channels the broad `*` item requests. */
export const OVERVIEW_CHANNELS: MarketDataChannel[] = ["book", "trades"];
/** Channels the focus item adds on top of the broad item. */
export const FOCUS_ONLY_CHANNELS: MarketDataChannel[] = ["depth", "auction"];
/** Channels the focus item requests when there is no broad item. */
export const FOCUS_FULL_CHANNELS: MarketDataChannel[] = ["book", "trades", "depth", "auction"];

export interface SubscriptionItem {
  symbols: string[];
  channels: MarketDataChannel[];
  /** Per-channel last-seen `seq`, replayed on reconnect (§26.3.2). */
  resume_from?: Partial<Record<MarketDataChannel, number>>;
}

export interface SubscriptionPlan {
  /** Subscribe `*` on book/trades for the overview grid. */
  overview: boolean;
  /** Focus symbols — active symbol + watchlist, already capped. */
  focus: string[];
}

/** `SYMBOL|channel` — the pair key used for diffing. */
export type PairKey = string;

export function pairKey(symbol: string, channel: MarketDataChannel): PairKey {
  return `${symbol}|${channel}`;
}

export function splitPair(key: PairKey): { symbol: string; channel: MarketDataChannel } {
  const idx = key.indexOf("|");
  return {
    symbol: key.slice(0, idx),
    channel: key.slice(idx + 1) as MarketDataChannel,
  };
}

/**
 * Normalise a symbol list: upper-cased, de-duplicated, order-preserving,
 * truncated to `max`. Truncation is caller-visible via the returned length —
 * §17.3.4 requires the heavy focus set to stay bounded.
 */
export function capSymbols(symbols: readonly string[], max: number): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of symbols) {
    const sym = raw?.trim().toUpperCase();
    if (!sym || sym === WILDCARD || seen.has(sym)) continue;
    seen.add(sym);
    out.push(sym);
    if (out.length >= max) break;
  }
  return out;
}

/** The full `(symbol, channel)` pair set a plan asks for. */
export function planPairs(plan: SubscriptionPlan): Set<PairKey> {
  const pairs = new Set<PairKey>();
  if (plan.overview) {
    for (const ch of OVERVIEW_CHANNELS) pairs.add(pairKey(WILDCARD, ch));
  }
  const focusChannels = plan.overview ? FOCUS_ONLY_CHANNELS : FOCUS_FULL_CHANNELS;
  for (const sym of plan.focus) {
    for (const ch of focusChannels) pairs.add(pairKey(sym, ch));
  }
  return pairs;
}

/**
 * Collapse pairs into wire items, grouping symbols that share an identical
 * channel set so a 25-symbol focus change is one item, not 25.
 */
export function groupPairs(pairs: Iterable<PairKey>): SubscriptionItem[] {
  const bySymbol = new Map<string, Set<MarketDataChannel>>();
  for (const key of pairs) {
    const { symbol, channel } = splitPair(key);
    let set = bySymbol.get(symbol);
    if (!set) {
      set = new Set();
      bySymbol.set(symbol, set);
    }
    set.add(channel);
  }

  const byChannels = new Map<string, { channels: MarketDataChannel[]; symbols: string[] }>();
  for (const symbol of [...bySymbol.keys()].sort()) {
    const channels = [...bySymbol.get(symbol)!].sort();
    const k = channels.join(",");
    const bucket = byChannels.get(k);
    if (bucket) bucket.symbols.push(symbol);
    else byChannels.set(k, { channels, symbols: [symbol] });
  }

  return [...byChannels.values()].map(({ channels, symbols }) => ({
    symbols,
    channels,
  }));
}

export interface SubscriptionDiff {
  subscribe: SubscriptionItem[];
  unsubscribe: SubscriptionItem[];
}

/**
 * Items needed to move the server from `applied` to `desired`.
 * Both directions are grouped; either list may be empty.
 */
export function diffPairs(
  applied: ReadonlySet<PairKey>,
  desired: ReadonlySet<PairKey>,
): SubscriptionDiff {
  const added: PairKey[] = [];
  const removed: PairKey[] = [];
  for (const key of desired) if (!applied.has(key)) added.push(key);
  for (const key of applied) if (!desired.has(key)) removed.push(key);
  return {
    subscribe: groupPairs(added),
    unsubscribe: groupPairs(removed),
  };
}

/**
 * The full item list to (re)send after a reconnect, annotated with the
 * per-channel resume points the caller has tracked. `resume_from` is only
 * honoured by the gateway for the append-only `trades` channel — the
 * snapshot channels are self-healing — so a resume point for a channel the
 * server ignores is harmless but pointless, and is dropped here.
 */
export function replayItems(
  desired: ReadonlySet<PairKey>,
  resumeFrom: (symbol: string, channel: MarketDataChannel) => number | undefined,
): SubscriptionItem[] {
  return groupPairs(desired).map((item) => {
    const resume: Partial<Record<MarketDataChannel, number>> = {};
    for (const channel of item.channels) {
      if (channel !== "trades") continue;
      for (const symbol of item.symbols) {
        const seq = resumeFrom(symbol, channel);
        if (seq !== undefined) {
          resume[channel] = seq;
          break;
        }
      }
    }
    return Object.keys(resume).length > 0 ? { ...item, resume_from: resume } : item;
  });
}
