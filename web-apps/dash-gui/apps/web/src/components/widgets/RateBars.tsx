/**
 * Stacked bars per time bucket (design §13, row 3): orders per minute by
 * participant, the top `n` by their total over the range and the rest
 * summed into "other", so a bar's height is always the whole exchange's.
 * Times on the session clock (lib/time.ts).
 *
 * `/api/rate` returns only the buckets that had increments, so the bars are
 * laid on the full grid of `bucketMs` buckets across the range, empty ones
 * at 0: a quiet stretch shows as a gap in time, not as bars pushed together.
 */

import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS_TICK, ChartBox, oneLine, TOOLTIP_STYLE } from "./ChartBox.js";
import { mergeSeries, MARGIN, seriesStyle, Y_AXIS_WIDTH } from "./TimeSeries.js";
import type { TimeRangeMs } from "./StateTimeline.js";
import { formatAxisTime, formatDateTime } from "../../lib/time.js";
import { OTHER, topNSeries, type Series } from "../../lib/topn.js";

export interface RateBarsProps {
  label: string;
  series: readonly Series[];
  range: TimeRangeMs;
  /** The buckets the counts are in: 60 000 for /api/rate bucket=1m. */
  bucketMs: number;
  tz: string;
  format: (v: number) => string;
  /** Series shown on their own, at most 8 (one colour each); the rest are "other". */
  n?: number;
  height?: number;
  width?: number;
}

/** More buckets than this are not laid out one by one (the bridge allows 1 000). */
const MAX_BUCKETS = 2000;

/**
 * Every bucket start in the range, on the grid the data is on (`anchor`, a
 * bucket start; the range's start without data). Empty past MAX_BUCKETS.
 */
export function bucketGrid(range: TimeRangeMs, bucketMs: number, anchor: number): number[] {
  if (!(bucketMs > 0) || range.toMs <= range.fromMs) return [];
  const first = anchor + Math.floor((range.fromMs - anchor) / bucketMs) * bucketMs;
  const count = Math.ceil((range.toMs - first) / bucketMs);
  if (count > MAX_BUCKETS) return [];
  return Array.from({ length: count }, (_, i) => first + i * bucketMs);
}

/**
 * The bars' rows: every bucket of the grid, each series 0 where it had
 * nothing. A point off the grid is added to the bucket it is nearest, so
 * nothing the bridge sent is dropped.
 */
export function rateRows(series: readonly Series[], range: TimeRangeMs, bucketMs: number): Record<string, number>[] {
  const data = mergeSeries(series, true);
  const grid = bucketGrid(range, bucketMs, data[0]?.ts ?? range.fromMs);
  if (grid.length === 0) return data;
  const rows = grid.map((ts) => {
    const row: Record<string, number> = { ts };
    series.forEach((_s, i) => (row[`s${i}`] = 0));
    return row;
  });
  for (const d of data) {
    const slot = Math.round((d.ts - grid[0]!) / bucketMs);
    const row = rows[slot];
    if (!row) continue; // outside the range
    series.forEach((_s, i) => (row[`s${i}`]! += d[`s${i}`] ?? 0));
  }
  return rows;
}

export function RateBars({ label, series, range, bucketMs, tz, format, n = 8, height = 180, width }: RateBarsProps) {
  const shown = topNSeries(series, Math.min(n, 8));
  const rows = rateRows(shown, range, bucketMs);
  const span = range.toMs - range.fromMs;
  const empty = series.every((s) => s.points.length === 0);
  const color = (i: number) => (shown[i]?.label === OTHER ? "var(--stopped)" : seriesStyle(i).color);

  return (
    <figure aria-label={label} data-widget="rate-bars" className="m-0 min-w-0">
      <div className="relative">
        <ChartBox width={width} height={height}>
          {(size) => (
            <BarChart {...size} data={rows} margin={MARGIN} barCategoryGap={1}>
              <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="ts" tick={AXIS_TICK} tickFormatter={(ts: number) => formatAxisTime(ts, tz, span)} stroke="var(--border)" minTickGap={16} />
              <YAxis tick={AXIS_TICK} tickFormatter={oneLine(format)} width={Y_AXIS_WIDTH} allowDecimals={false} stroke="var(--border)" />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                cursor={{ fill: "var(--bg-inset)" }}
                labelFormatter={(ts: number) => formatDateTime(ts, tz)}
                formatter={(v: number, name: string) => [format(v), name]}
              />
              {shown.map((s, i) => (
                <Bar key={i} dataKey={`s${i}`} name={s.label} stackId="rate" fill={color(i)} isAnimationActive={false} />
              ))}
            </BarChart>
          )}
        </ChartBox>
        {empty && <p className="pointer-events-none absolute inset-0 m-0 flex items-center justify-center text-xs text-fg-faint">No data in this range</p>}
      </div>
      {!empty && (
        <figcaption className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-subtle">
          {shown.map((s, i) => (
            <span key={i} className="flex min-w-0 max-w-full items-center gap-1">
              <span aria-hidden="true" className="inline-block h-2 w-2 shrink-0 rounded-sm" style={{ background: color(i) }} />
              <span className="truncate" title={s.label}>
                {s.label}
              </span>
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  );
}
