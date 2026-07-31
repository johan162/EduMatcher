/**
 * Thin REST client for the bridge's `/api/*` proxy (design §17.2). All reads
 * are GET; nothing here mutates anything, and no credential is involved — the
 * bridge holds the only key, server-side.
 */

import type {
  DailyBar,
  IndexDailyRow,
  IndexEventRow,
  IndexSnapshotRow,
  PriceSnapshotRow,
  TradeRow,
} from "@edumatcher/terminal-types";

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

  /** Daily index bars — the 1M and longer chart presets, and the O/H/L panel. */
  indexDaily: (indexId: string, from?: string) => {
    const params = new URLSearchParams({ index_id: indexId, limit: String(MAX_LIMIT) });
    if (from) params.set("from", from);
    return getJson<{ daily: IndexDailyRow[] }>(`/api/history/index-daily?${params}`);
  },

  /**
   * Raw intraday level ticks for the 1D/5D presets.
   *
   * pm-index writes one row per `index.update`, which is already fine enough
   * to chart directly — unlike Symbol Detail's intraday view there is no
   * bucketing step (design §10.4).
   */
  indexSnapshots: (indexId: string, from?: string) => {
    const params = new URLSearchParams({ index_id: indexId, limit: String(MAX_LIMIT) });
    if (from) params.set("from", from);
    return getJson<{ snapshots: IndexSnapshotRow[] }>(
      `/api/history/index-snapshots?${params}`,
    );
  },

  /**
   * Structural changes — constituent added, delisted, corporate action.
   *
   * Fetched once per view rather than polled: these are rare, operator-driven
   * events, so a manual refresh or view re-open is enough (design §10.2).
   * Returns a bare object, not the paginated envelope the others use.
   */
  indexEvents: (indexId: string) =>
    getJson<{ events: IndexEventRow[]; count: number }>(
      `/api/history/index-events?index_id=${encodeURIComponent(indexId)}`,
    ),
};
