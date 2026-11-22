/** Symbol -> sector, from the snapshot's sector -> symbols. */
export function sectorIndex(sectors: Record<string, string[]>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [sector, symbols] of Object.entries(sectors)) {
    for (const symbol of symbols) out[symbol] = sector;
  }
  return out;
}

/** How far back the News view looks; "all" is everything pm-market-sim keeps. */
export type NewsWindow = "1h" | "24h" | "7d" | "30d" | "all";

export const NEWS_WINDOW_LABEL: Record<NewsWindow, string> = {
  "1h": "Last hour",
  "24h": "Last 24 h",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  all: "All",
};

const HOUR_MS = 3_600_000;
const WINDOW_MS: Record<Exclude<NewsWindow, "all">, number> = {
  "1h": HOUR_MS,
  "24h": 24 * HOUR_MS,
  "7d": 7 * 24 * HOUR_MS,
  "30d": 30 * 24 * HOUR_MS,
};

/** The window's rolling start as an ISO time; undefined for "all". */
export function newsWindowStart(window: NewsWindow, now: number): string | undefined {
  return window === "all" ? undefined : new Date(now - WINDOW_MS[window]).toISOString();
}
