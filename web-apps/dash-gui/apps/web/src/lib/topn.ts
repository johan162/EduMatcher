/**
 * The N largest items, the rest summed into one "other" item -- for the
 * stacked orders/min bars (top 8 participants + other, §12.3) and the bar
 * gauges. Nothing is dropped: the parts always add up to the whole.
 */

export const OTHER = "other";

/** Items by value, largest first; beyond `n`, one `other` item with the rest's sum. */
export function topN<T extends { label: string; value: number }>(
  items: readonly T[],
  n: number,
  makeOther: (value: number, count: number) => T,
): T[] {
  const sorted = [...items].sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  if (sorted.length <= n) return sorted;
  const rest = sorted.slice(n);
  return [...sorted.slice(0, n), makeOther(rest.reduce((sum, i) => sum + i.value, 0), rest.length)];
}

export interface Series {
  label: string;
  /** `[epoch ms, value]`, oldest first. */
  points: [number, number][];
}

/**
 * Series ranked by their total over the range; beyond `n`, one `other`
 * series whose value in each bucket is the rest's sum in that bucket.
 */
export function topNSeries(series: readonly Series[], n: number): Series[] {
  const total = (s: Series) => s.points.reduce((sum, [, v]) => sum + v, 0);
  const ranked = [...series].sort((a, b) => total(b) - total(a) || a.label.localeCompare(b.label));
  if (ranked.length <= n) return ranked;
  const other = new Map<number, number>();
  for (const s of ranked.slice(n)) {
    for (const [ts, v] of s.points) other.set(ts, (other.get(ts) ?? 0) + v);
  }
  return [...ranked.slice(0, n), { label: OTHER, points: [...other.entries()].sort((a, b) => a[0] - b[0]) }];
}
