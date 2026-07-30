/**
 * Thin REST client for the bridge's `/api/*` proxy (design §17.2). All reads
 * are GET; nothing here mutates anything, and no credential is involved — the
 * bridge holds the only key, server-side.
 */

import type { DailyBar, PriceSnapshotRow, TradeRow } from "@edumatcher/terminal-types";

/** Largest page the history endpoints allow. */
const MAX_LIMIT = 5000;

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
    throw new Error(body.error?.message ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  /**
   * Today's daily rollup for every symbol, in one request.
   *
   * Design §8.5 describes polling this per visible symbol; one unfiltered call
   * returns the whole set, which is fewer requests and stays correct as the
   * grid pages. `date` is deliberately omitted rather than sent as `today`
   * (which §8.5 shows): the endpoint has no such keyword — `validate_date`
   * rejects it — and omitting it resolves to the latest available date, which
   * is what was meant.
   */
  dailyBars: () => getJson<{ daily: DailyBar[] }>(`/api/history/daily?limit=${MAX_LIMIT}`),

  /** Today's rollup for one symbol — open, prev close, VWAP, high/low, volume. */
  dailyForSymbol: (symbol: string) =>
    getJson<{ daily: DailyBar[] }>(`/api/history/daily?symbol=${encodeURIComponent(symbol)}`),

  /**
   * Daily bars across a range, for the 1M and longer chart presets.
   *
   * This needs the `from`/`to` range the endpoint only recently grew; before
   * that it resolved to a single date and a month of bars would have meant one
   * request per calendar day.
   */
  dailyRange: (symbol: string, from?: string) => {
    const params = new URLSearchParams({ symbol, limit: String(MAX_LIMIT) });
    if (from) params.set("from", from);
    return getJson<{ daily: DailyBar[] }>(`/api/history/daily?${params}`);
  },

  /** Raw prints for intraday bar bucketing. */
  trades: (symbol: string, from?: string) => {
    const params = new URLSearchParams({ symbol, limit: String(MAX_LIMIT) });
    if (from) params.set("from", from);
    return getJson<{ trades: TradeRow[] }>(`/api/history/trades?${params}`);
  },

  /** Recorded bid/ask midpoint, 15-minute cadence (design §9.3). */
  priceSnapshots: (symbol: string, from?: string) => {
    const params = new URLSearchParams({ symbol, limit: String(MAX_LIMIT) });
    if (from) params.set("from", from);
    return getJson<{ snapshots: PriceSnapshotRow[] }>(`/api/history/price-snapshots?${params}`);
  },
};
