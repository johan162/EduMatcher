/**
 * Lines or stacked areas over the shared time range (design §13): CPU per
 * process, exchange memory, reject ratio.
 *
 * - Every time on it is on the session clock: the axis and the tooltip go
 *   through lib/time.ts (Recharts' own formatting would use the browser's
 *   zone).
 * - Threshold bands are tinted `ReferenceArea`s, with the level's colour;
 *   an inverted rule (low is bad) tints the bottom.
 * - Events are annotations: one thin `ReferenceLine` each, only for those
 *   inside the range.
 * - The crosshair is shared (useCrosshair): hovering one chart draws the
 *   same vertical line on every chart in view.
 */

import { useId } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Point } from "@edumatcher/dash-types";
import { AXIS_TICK, ChartBox, oneLine, seriesColor, TOOLTIP_STYLE } from "./ChartBox.js";
import type { TimeRangeMs } from "./StateTimeline.js";
import { LEVEL } from "../../lib/status.js";
import type { Thresholds } from "../../lib/thresholds.js";
import { formatAxisTime, formatDateTime } from "../../lib/time.js";
import { useCrosshair } from "../../store/useCrosshair.js";

export interface TimeSeriesLine {
  label: string;
  points: readonly Point[];
}

export interface Annotation {
  ts: number;
  label: string;
  color: string;
}

export interface TimeSeriesProps {
  label: string;
  series: readonly TimeSeriesLine[];
  range: TimeRangeMs;
  tz: string;
  format: (v: number) => string;
  annotations?: readonly Annotation[];
  thresholds?: Thresholds;
  stacked?: boolean;
  height?: number;
  /** Fixed width (tests); the panel's width otherwise. */
  width?: number;
}

type Row = Record<string, number> & { ts: number };

/** One row per timestamp, a column per series (`s0`, `s1`, ...). */
export function mergeSeries(series: readonly TimeSeriesLine[]): Row[] {
  const rows = new Map<number, Row>();
  series.forEach((s, i) => {
    for (const [ts, v] of s.points) {
      const row = rows.get(ts) ?? ({ ts } as Row);
      row[`s${i}`] = v;
      rows.set(ts, row);
    }
  });
  return [...rows.values()].sort((a, b) => a.ts - b.ts);
}

export function inRange(annotations: readonly Annotation[], range: TimeRangeMs): Annotation[] {
  return annotations.filter((a) => a.ts >= range.fromMs && a.ts <= range.toMs);
}

/** The tinted bands for `t` between `lo` and `hi` on the y axis. */
export function thresholdBands(t: Thresholds, lo: number, hi: number): { y1: number; y2: number; color: string }[] {
  const warn = LEVEL.WARN.color;
  const crit = LEVEL.CRIT.color;
  if (t.invert) {
    return t.crit === undefined
      ? [{ y1: lo, y2: t.warn, color: warn }]
      : [
          { y1: lo, y2: t.crit, color: crit },
          { y1: t.crit, y2: t.warn, color: warn },
        ];
  }
  return t.crit === undefined
    ? [{ y1: t.warn, y2: hi, color: warn }]
    : [
        { y1: t.warn, y2: t.crit, color: warn },
        { y1: t.crit, y2: hi, color: crit },
      ];
}

export function TimeSeries({
  label,
  series,
  range,
  tz,
  format,
  annotations = [],
  thresholds,
  stacked = false,
  height = 180,
  width,
}: TimeSeriesProps) {
  const id = useId();
  const crosshair = useCrosshair((s) => s.ts);
  const setCrosshair = useCrosshair((s) => s.setTs);
  const rows = mergeSeries(series);
  const span = range.toMs - range.fromMs;
  const values = stacked
    ? rows.map((r) => series.reduce((sum, _s, i) => sum + (r[`s${i}`] ?? 0), 0))
    : rows.flatMap((r) => series.map((_s, i) => r[`s${i}`]).filter((v): v is number => v !== undefined));
  const dataMax = Math.max(0, ...values);
  const lo = Math.min(0, ...values);
  const hi = thresholds ? Math.max(dataMax, thresholds.crit ?? thresholds.warn) * 1.1 : dataMax;

  const chart = (size: { width?: number; height: number }) => {
    const Chart = stacked ? AreaChart : LineChart;
    return (
      <Chart
        {...size}
        data={rows}
        margin={{ top: 10, right: 8, bottom: 0, left: 0 }}
        onMouseMove={(s) => setCrosshair(typeof s?.activeLabel === "number" ? s.activeLabel : null)}
        onMouseLeave={() => setCrosshair(null)}
      >
        <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
        <XAxis
          dataKey="ts"
          type="number"
          domain={[range.fromMs, range.toMs]}
          allowDataOverflow
          tick={AXIS_TICK}
          tickFormatter={(ts: number) => formatAxisTime(ts, tz, span)}
          stroke="var(--border)"
        />
        <YAxis
          domain={thresholds ? [lo, hi] : [lo, "auto"]}
          allowDataOverflow={Boolean(thresholds)}
          tick={AXIS_TICK}
          tickFormatter={oneLine(format)}
          width={68}
          stroke="var(--border)"
        />
        {thresholds &&
          thresholdBands(thresholds, lo, hi).map((b) => (
            <ReferenceArea key={`${b.y1}`} y1={b.y1} y2={b.y2} fill={b.color} fillOpacity={0.08} ifOverflow="hidden" />
          ))}
        <Tooltip
          contentStyle={TOOLTIP_STYLE}
          labelFormatter={(ts: number) => formatDateTime(ts, tz)}
          formatter={(v: number, key: string) => [format(v), series[Number(key.slice(1))]?.label ?? key]}
        />
        {series.map((s, i) =>
          stacked ? (
            <Area key={s.label} dataKey={`s${i}`} name={s.label} stackId={id} stroke={seriesColor(i)} fill={seriesColor(i)} fillOpacity={0.35} isAnimationActive={false} />
          ) : (
            <Line key={s.label} dataKey={`s${i}`} name={s.label} stroke={seriesColor(i)} dot={false} strokeWidth={1.5} isAnimationActive={false} />
          ),
        )}
        {inRange(annotations, range).map((a) => (
          <ReferenceLine key={`${a.ts}-${a.label}`} x={a.ts} stroke={a.color} strokeDasharray="2 2" className="annotation" />
        ))}
        {crosshair !== null && crosshair >= range.fromMs && crosshair <= range.toMs && (
          <ReferenceLine x={crosshair} stroke="var(--fg-faint)" className="crosshair" />
        )}
      </Chart>
    );
  };

  return (
    <figure aria-label={label} className="m-0">
      <ChartBox width={width} height={height}>
        {chart}
      </ChartBox>
      {series.length > 1 && (
        <figcaption className="mt-1 flex flex-wrap gap-3 text-[11px] text-fg-subtle">
          {series.map((s, i) => (
            <span key={s.label} className="flex items-center gap-1">
              <span aria-hidden="true" className="inline-block h-0.5 w-3" style={{ background: seriesColor(i) }} />
              {s.label}
            </span>
          ))}
        </figcaption>
      )}
    </figure>
  );
}
