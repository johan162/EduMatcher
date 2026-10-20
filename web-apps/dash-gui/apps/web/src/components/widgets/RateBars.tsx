/**
 * Stacked bars per time bucket (design §13, row 3): orders per minute by
 * participant, the top `n` by their total over the range and the rest
 * summed into "other", so a bar's height is always the whole exchange's.
 * Times on the session clock (lib/time.ts).
 */

import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS_TICK, ChartBox, oneLine, seriesColor, TOOLTIP_STYLE } from "./ChartBox.js";
import { mergeSeries } from "./TimeSeries.js";
import type { TimeRangeMs } from "./StateTimeline.js";
import { formatAxisTime, formatDateTime } from "../../lib/time.js";
import { OTHER, topNSeries, type Series } from "../../lib/topn.js";

export interface RateBarsProps {
  label: string;
  series: readonly Series[];
  range: TimeRangeMs;
  tz: string;
  format: (v: number) => string;
  /** Series shown on their own; the rest are "other" (§12.3: 8). */
  n?: number;
  height?: number;
  width?: number;
}

export function RateBars({ label, series, range, tz, format, n = 8, height = 180, width }: RateBarsProps) {
  const shown = topNSeries(series, n);
  const rows = mergeSeries(shown);
  const span = range.toMs - range.fromMs;
  const color = (i: number) => (shown[i]?.label === OTHER ? "var(--stopped)" : seriesColor(i));

  return (
    <figure aria-label={label} className="m-0">
      <ChartBox width={width} height={height}>
        {(size) => (
          <BarChart {...size} data={rows} margin={{ top: 10, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
            <XAxis dataKey="ts" tick={AXIS_TICK} tickFormatter={(ts: number) => formatAxisTime(ts, tz, span)} stroke="var(--border)" />
            <YAxis tick={AXIS_TICK} tickFormatter={oneLine(format)} width={68} stroke="var(--border)" />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              cursor={{ fill: "var(--bg-inset)" }}
              labelFormatter={(ts: number) => formatDateTime(ts, tz)}
              formatter={(v: number, key: string) => [format(v), shown[Number(key.slice(1))]?.label ?? key]}
            />
            {shown.map((s, i) => (
              <Bar key={s.label} dataKey={`s${i}`} name={s.label} stackId="rate" fill={color(i)} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </ChartBox>
      <figcaption className="mt-1 flex flex-wrap gap-3 text-[11px] text-fg-subtle">
        {shown.map((s, i) => (
          <span key={s.label} className="flex items-center gap-1">
            <span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm" style={{ background: color(i) }} />
            {s.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
