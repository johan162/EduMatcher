/**
 * Lines or stacked areas over the shared time range (design §13): CPU per
 * process, exchange memory, reject ratio.
 *
 * Data contract: the series of one chart share one bucket grid -- fetch
 * them in one `/api/series/multi` call (by `labels=` or by `sources=`), which
 * answers every series at one resolution and the same bucket starts. Then a
 * series' missing bucket is a real gap: a line breaks there, and in a stacked
 * chart it counts as 0 (a process that was not running holds no memory), so
 * the stack above it stays whole.
 *
 * - Every time on it is on the session clock: the axis and the tooltip go
 *   through lib/time.ts (Recharts' own formatting would use the browser's
 *   zone).
 * - Threshold bands are tinted `ReferenceArea`s, with the level's colour;
 *   an inverted rule (low is bad) tints the bottom.
 * - The crosshair is shared (useCrosshair) and drawn as an overlay of its
 *   own, so a moving pointer re-renders that line, not every chart's points.
 * - Series 1-8 take the eight series colours; 9-16 repeat them dashed and
 *   17-24 dotted, so no colour ever stands for two series alone.
 * - `step` draws a count that holds until it changes (participants
 *   connected); `marks` are moments drawn as vertical lines and named in the
 *   legend (heartbeat timeouts).
 */

import { memo, useMemo } from "react";
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
import { MARK_WIDTH, type TimeRangeMs } from "./StateTimeline.js";
import { LEVEL } from "../../lib/status.js";
import type { Thresholds } from "../../lib/thresholds.js";
import { formatAxisTime, formatDateTime } from "../../lib/time.js";
import { useCrosshair } from "../../store/useCrosshair.js";
import { PanelTitle } from "./PanelTitle.js";

export interface TimeSeriesLine {
  label: string;
  points: readonly Point[];
}

/** Moments of one kind, as vertical lines in `color`, named `label` in the legend. */
export interface TimeMarks {
  ts: readonly number[];
  label: string;
  color: string;
}

export interface TimeSeriesProps {
  label: string;
  series: readonly TimeSeriesLine[];
  range: TimeRangeMs;
  tz: string;
  format: (v: number) => string;
  thresholds?: Thresholds;
  stacked?: boolean;
  /** Whole-number values (counts): no fractional axis ticks. */
  integer?: boolean;
  /** A value holds until the next point (a line chart's steps). */
  step?: boolean;
  marks?: TimeMarks;
  height?: number;
  /** Fixed width (tests); the panel's width otherwise. */
  width?: number;
}

/** Plot-area insets, shared by the chart and the crosshair overlay. */
export const Y_AXIS_WIDTH = 68;
export const MARGIN = { top: 10, right: 8, bottom: 0, left: 0 };
const X_AXIS_HEIGHT = 30;

type Row = Record<string, number> & { ts: number };

/**
 * One row per timestamp, a column per series (`s0`, `s1`, ...). With
 * `fillZero`, a series without a point at a row's timestamp counts 0 there
 * (stacking); otherwise it is absent and its line breaks.
 */
export function mergeSeries(series: readonly TimeSeriesLine[], fillZero = false): Row[] {
  const rows = new Map<number, Row>();
  series.forEach((s, i) => {
    for (const [ts, v] of s.points) {
      if (!Number.isFinite(ts)) continue;
      const row = rows.get(ts) ?? ({ ts } as Row);
      if (Number.isFinite(v)) row[`s${i}`] = v;
      rows.set(ts, row);
    }
  });
  const out = [...rows.values()].sort((a, b) => a.ts - b.ts);
  if (fillZero) {
    for (const row of out) series.forEach((_s, i) => (row[`s${i}`] ??= 0));
  }
  return out;
}

/** Series i's colour and dash: colours cycle, each cycle in a new dash. */
export function seriesStyle(i: number): { color: string; dash: string | undefined } {
  return { color: seriesColor(i), dash: [undefined, "6 3", "1 3"][Math.floor(i / 8) % 3] };
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

/** The y axis range: from min(0, data) to the data's top, or a margin above the thresholds. */
export function yDomain(rows: readonly Row[], count: number, stacked: boolean, thresholds?: Thresholds): [number, number] {
  let lo = 0;
  let hi = 0;
  for (const row of rows) {
    let sum = 0;
    for (let i = 0; i < count; i++) {
      const v = row[`s${i}`];
      if (v === undefined) continue;
      if (stacked) sum += v;
      else {
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    if (stacked) {
      lo = Math.min(lo, sum);
      hi = Math.max(hi, sum);
    }
  }
  if (thresholds) hi = Math.max(hi, thresholds.crit ?? thresholds.warn) * 1.1;
  return [lo, hi > lo ? hi : lo + 1];
}

interface BodyProps {
  rows: Row[];
  series: readonly TimeSeriesLine[];
  range: TimeRangeMs;
  tz: string;
  format: (v: number) => string;
  thresholds?: Thresholds;
  stacked: boolean;
  integer: boolean;
  step: boolean;
  marks?: TimeMarks;
  /** Injected by ResponsiveContainer (its direct child), or given in tests. */
  width?: number;
  height?: number;
}

/** The chart itself; memoised, so the crosshair's moves do not redraw it. */
const Body = memo(function Body({ rows, series, range, tz, format, thresholds, stacked, integer, step, marks, width, height }: BodyProps) {
  const setCrosshair = useCrosshair((s) => s.setTs);
  const span = range.toMs - range.fromMs;
  const [lo, hi] = yDomain(rows, series.length, stacked, thresholds);
  const Chart = stacked ? AreaChart : LineChart;
  return (
    <Chart
      width={width}
      height={height}
      data={rows}
      margin={MARGIN}
      onMouseMove={(s) => setCrosshair(typeof s?.activeLabel === "number" ? s.activeLabel : null)}
      onMouseLeave={() => setCrosshair(null)}
    >
      <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
      <XAxis
        dataKey="ts"
        type="number"
        domain={[range.fromMs, range.toMs]}
        allowDataOverflow
        height={X_AXIS_HEIGHT}
        tick={AXIS_TICK}
        tickFormatter={(ts: number) => formatAxisTime(ts, tz, span)}
        stroke="var(--border)"
      />
      <YAxis
        // Recharts rounds an "auto" top to nice ticks; a flat or empty chart
        // gets an explicit range, as "auto" would collapse to nothing.
        domain={thresholds || rows.length === 0 || hi === lo + 1 ? [lo, hi] : [lo, "auto"]}
        allowDataOverflow={Boolean(thresholds)}
        allowDecimals={!integer}
        tick={rows.length === 0 ? false : AXIS_TICK}
        tickFormatter={oneLine(format)}
        width={Y_AXIS_WIDTH}
        stroke="var(--border)"
      />
      {thresholds &&
        thresholdBands(thresholds, lo, hi).map((b, i) => (
          <ReferenceArea key={i} y1={b.y1} y2={b.y2} fill={b.color} fillOpacity={0.08} ifOverflow="hidden" />
        ))}
      {marks?.ts.map((ts, i) => <ReferenceLine key={`m${i}`} x={ts} stroke={marks.color} strokeWidth={MARK_WIDTH} ifOverflow="hidden" />)}
      <Tooltip
        contentStyle={TOOLTIP_STYLE}
        labelFormatter={(ts: number) => formatDateTime(ts, tz)}
        formatter={(v: number, name: string) => [format(v), name]}
      />
      {series.map((s, i) => {
        const { color, dash } = seriesStyle(i);
        return stacked ? (
          <Area key={i} dataKey={`s${i}`} name={s.label} stackId="stack" stroke={color} strokeDasharray={dash} fill={color} fillOpacity={0.35} isAnimationActive={false} />
        ) : (
          <Line key={i} type={step ? "stepAfter" : "linear"} dataKey={`s${i}`} name={s.label} stroke={color} strokeDasharray={dash} dot={false} strokeWidth={1.5} isAnimationActive={false} />
        );
      })}
    </Chart>
  );
});

/** The shared crosshair over the plot area, positioned by time alone. */
function Crosshair({ range, height }: { range: TimeRangeMs; height: number }) {
  const ts = useCrosshair((s) => s.ts);
  const span = range.toMs - range.fromMs;
  if (ts === null || span <= 0 || ts < range.fromMs || ts > range.toMs) return null;
  const frac = (ts - range.fromMs) / span;
  const inset = Y_AXIS_WIDTH + MARGIN.left + MARGIN.right;
  return (
    <div
      data-testid="crosshair"
      aria-hidden="true"
      className="pointer-events-none absolute w-px bg-fg-faint"
      style={{
        left: `calc(${Y_AXIS_WIDTH + MARGIN.left}px + (100% - ${inset}px) * ${frac.toFixed(5)})`,
        top: MARGIN.top,
        height: height - MARGIN.top - X_AXIS_HEIGHT,
      }}
    />
  );
}

export function TimeSeries({
  label,
  series,
  range,
  tz,
  format,
  thresholds,
  stacked = false,
  integer = false,
  step = false,
  marks,
  height = 180,
  width,
}: TimeSeriesProps) {
  const rows = useMemo(() => mergeSeries(series, stacked), [series, stacked]);

  return (
    <figure aria-label={label} data-widget="time-series" className="m-0 min-w-0">
      <PanelTitle>{label}</PanelTitle>
      {/* Clips Recharts' hidden tooltip, parked past the right edge, which would widen the page. */}
      <div className="relative overflow-hidden">
        <ChartBox width={width} height={height}>
          {(size) => (
            // ResponsiveContainer sizes its direct child through width/height props.
            <Body rows={rows} series={series} range={range} tz={tz} format={format} thresholds={thresholds} stacked={stacked} integer={integer} step={step} marks={marks} {...size} />
          )}
        </ChartBox>
        <Crosshair range={range} height={height} />
        {rows.length === 0 && (
          <p className="pointer-events-none absolute inset-0 m-0 flex items-center justify-center text-xs text-fg-faint">No data in this range</p>
        )}
      </div>
      {(series.length > 1 || marks) && (
        <figcaption className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-fg-subtle">
          {series.map((s, i) => {
            const { color, dash } = seriesStyle(i);
            return (
              <span key={i} className="flex min-w-0 max-w-full items-center gap-1">
                <svg width={12} height={4} aria-hidden="true" className="shrink-0">
                  <line x1={0} y1={2} x2={12} y2={2} stroke={color} strokeWidth={2} strokeDasharray={dash} />
                </svg>
                <span className="truncate" title={s.label}>
                  {s.label}
                </span>
              </span>
            );
          })}
          {marks && (
            <span className="flex items-center gap-1">
              <span aria-hidden="true" className="inline-block h-2 w-0.5" style={{ background: marks.color }} />
              {marks.label}
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}
