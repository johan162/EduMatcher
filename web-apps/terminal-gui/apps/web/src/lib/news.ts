import type { NewsEvent } from "@edumatcher/terminal-types";

/**
 * Does a headline concern `filter` — a symbol or a sector name (any case)?
 * Market-wide news concerns everything; a sector headline concerns its
 * symbols, and a symbol headline its sector. An empty filter matches all.
 * (Same rule as trader-gui's lib/news.ts.)
 */
export function newsMatches(item: NewsEvent, filter: string, sectorOf: Record<string, string>): boolean {
  const f = filter.trim().toUpperCase();
  if (!f || item.scope === "MARKET") return true;
  const sectors = new Set(Object.values(sectorOf));
  if (item.scope === "SYMBOL") {
    return item.targets.includes(f) || (sectors.has(f) && item.targets.some((t) => sectorOf[t] === f));
  }
  // SECTOR
  return item.targets.includes(f) || (sectorOf[f] !== undefined && item.targets.includes(sectorOf[f]));
}

/** Rumour id -> how it ended, for the rumours that have. */
export function resolutions(items: readonly NewsEvent[]): Record<string, "CONFIRMED" | "RETRACTED"> {
  const out: Record<string, "CONFIRMED" | "RETRACTED"> = {};
  for (const n of items) {
    if (n.related_id && n.status !== "RUMOUR") out[n.related_id] = n.status;
  }
  return out;
}

/** Symbol -> sector, from the snapshot's sector -> symbols. */
export function sectorIndex(sectors: Record<string, string[]>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [sector, symbols] of Object.entries(sectors)) {
    for (const symbol of symbols) out[symbol] = sector;
  }
  return out;
}
