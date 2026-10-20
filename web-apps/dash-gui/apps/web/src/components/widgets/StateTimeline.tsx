/**
 * One lane per subject over the time range (design §13, row 4): coloured
 * segments for its states, ticks for its marks (a heartbeat timeout). x is
 * linear in time across the range; a segment is cut to the range, and a
 * mark at the very edge is still drawn inside. Each segment and mark has a
 * tooltip with its state or kind and its times on the session clock (with
 * the date past a day's range), and a legend names every colour, so no
 * state is told by colour alone.
 *
 * It takes its panel's width unless given one. A segment is at least 1 px
 * wide, so a short disconnect in a 7-day range still shows; one that ends
 * before it starts is not drawn. Lane ids longer than the label column are
 * cut with an ellipsis (the full id is in every tooltip).
 */

import { useRef } from "react";
import { useElementWidth } from "./ChartBox.js";
import { clipText } from "./svgText.js";
import { formatDateTime, formatTime } from "../../lib/time.js";

export interface TimeRangeMs {
  fromMs: number;
  toMs: number;
}

export interface Segment {
  from: number;
  to: number;
  state: string;
}

export interface Mark {
  ts: number;
  kind: string;
}

export interface Lane {
  id: string;
  segments: readonly Segment[];
  marks?: readonly Mark[];
}

export interface Look {
  label: string;
  color: string;
}

export const MARK_WIDTH = 2;

/** x of `ts` in a `width`-wide plot of `range`, clamped to it. */
export function xOf(ts: number, range: TimeRangeMs, width: number): number {
  const span = range.toMs - range.fromMs;
  const frac = span > 0 ? (ts - range.fromMs) / span : 0;
  return Math.min(width, Math.max(0, frac * width));
}

/** The narrowest a drawn segment gets, so a short one is still seen. */
export const MIN_SEGMENT = 1;

/**
 * A segment's x and width, cut to the range and at least MIN_SEGMENT wide
 * (kept inside the plot); null when it lies outside or ends before it starts.
 */
export function segmentBox(seg: Segment, range: TimeRangeMs, width: number): { x: number; width: number } | null {
  if (!(seg.to > seg.from) || seg.to <= range.fromMs || seg.from >= range.toMs) return null;
  const x = xOf(seg.from, range, width);
  const w = Math.max(MIN_SEGMENT, xOf(seg.to, range, width) - x);
  return { x: Math.min(x, width - w), width: w };
}

/** A mark's x, kept inside the plot even at the range's edges. */
export function markX(ts: number, range: TimeRangeMs, width: number): number {
  return Math.min(width - MARK_WIDTH, xOf(ts, range, width));
}

export interface StateTimelineProps {
  label: string;
  lanes: readonly Lane[];
  range: TimeRangeMs;
  /** Colour and name of each state and each mark kind. */
  states: Record<string, Look>;
  marks?: Record<string, Look>;
  tz: string;
  /** Fixed width (tests); the panel's width otherwise. */
  width?: number;
  laneHeight?: number;
  labelWidth?: number;
}

export function StateTimeline({ label, lanes, range, states, marks = {}, tz, width: fixed, laneHeight = 14, labelWidth = 96 }: StateTimelineProps) {
  const box = useRef<HTMLElement>(null);
  const width = useElementWidth(box, fixed);
  const plot = Math.max(0, width - labelWidth);
  const long = range.toMs - range.fromMs > 24 * 3600_000;
  const at = (ts: number) => (long ? formatDateTime(ts, tz) : formatTime(ts, tz));
  const legend = [...Object.values(states), ...Object.values(marks)];

  return (
    <figure ref={box} aria-label={label} data-widget="state-timeline" className="m-0 min-w-0">
      {lanes.length === 0 ? (
        <p className="text-xs text-fg-faint">No data</p>
      ) : width > 0 && (
      <svg width={width} height={lanes.length * (laneHeight + 4)} role="img" aria-label={label} className="block">
        {lanes.map((lane, i) => {
          const y = i * (laneHeight + 4);
          return (
            <g key={`${i}-${lane.id}`} data-lane={lane.id}>
              <text x={0} y={y + laneHeight - 3} fontSize={11} fill="var(--fg-subtle)" className="font-mono">
                {clipText(lane.id, labelWidth - 6, 11)}
                <title>{lane.id}</title>
              </text>
              <g transform={`translate(${labelWidth} ${y})`}>
                <rect width={plot} height={laneHeight} fill="var(--bg-inset)" />
                {lane.segments.map((seg, j) => {
                  const segBox = segmentBox(seg, range, plot);
                  if (!segBox) return null;
                  const look = states[seg.state];
                  return (
                    <rect key={j} data-segment={seg.state} x={segBox.x} width={segBox.width} height={laneHeight} fill={look?.color ?? "var(--stopped)"}>
                      <title>{`${lane.id}: ${look?.label ?? seg.state} ${at(Math.max(seg.from, range.fromMs))}–${at(Math.min(seg.to, range.toMs))}`}</title>
                    </rect>
                  );
                })}
                {(lane.marks ?? [])
                  .filter((m) => m.ts >= range.fromMs && m.ts <= range.toMs)
                  .map((m, j) => (
                    <rect key={j} data-mark={m.kind} x={markX(m.ts, range, plot)} y={-2} width={MARK_WIDTH} height={laneHeight + 4} fill={marks[m.kind]?.color ?? "var(--crit)"}>
                      <title>{`${lane.id}: ${marks[m.kind]?.label ?? m.kind} at ${at(m.ts)}`}</title>
                    </rect>
                  ))}
              </g>
            </g>
          );
        })}
      </svg>
      )}
      <figcaption className="mt-1 flex flex-wrap gap-3 text-[11px] text-fg-subtle">
        {legend.map((l, i) => (
          <span key={i} className="flex items-center gap-1">
            <span aria-hidden="true" className="inline-block h-2 w-3 rounded-sm" style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
