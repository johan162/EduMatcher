/**
 * `pm-api-gwy` `GET /api/v1/news`, passed through unmodified by the bridge:
 * pm-market-sim's headlines (WP-E5). Snake_case like the history rows.
 */

export interface NewsEvent {
  id: string;
  ts_ns: number;
  scope: "SYMBOL" | "SECTOR" | "MARKET";
  /** Symbols (SYMBOL) or sector names (SECTOR); empty for MARKET. */
  targets: string[];
  kind: string;
  status: "RUMOUR" | "CONFIRMED" | "RETRACTED";
  headline: string;
  /** Tone, -1 (bad) to 1 (good). */
  sentiment: number;
  /** Rumours only. */
  credibility?: number;
  /** The rumour a CONFIRMED or RETRACTED event resolves. */
  related_id: string;
}

/** Oldest first, plus each sector's symbols. */
export interface NewsSnapshot {
  news: NewsEvent[];
  sectors: Record<string, string[]>;
}
