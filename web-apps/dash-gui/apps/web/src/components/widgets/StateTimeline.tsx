/**
 * One lane per subject over the time range (design §13, row 4): coloured
 * segments for its states, ticks for its marks (a heartbeat timeout). x is
 * linear in time across the range; a segment is cut to the range, and a
 * mark at the very edge is still drawn inside. Each segment and mark has a
 * tooltip with its state or kind and its times on the session clock, and
 * a legend names every colour, so no state is told by colour alone.
 */

import { formatTime } from "../../lib/time.js";

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

/** A segment's x and width, cut to the range; null when it lies outside. */
export function segmentBox(seg: Segment, range: TimeRangeMs, width: number): { x: number; width: number } | null {
  if (seg.to <= range.fromMs || seg.from >= range.toMs) return null;
  const x = xOf(seg.from, range, width);
  return { x, width: xOf(seg.to, range, width) - x };
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
  width: number;
  laneHeight?: number;
  labelWidth?: number;
}

export function StateTimeline({ label, lanes, range, states, marks = {}, tz, width, laneHeight = 14, labelWidth = 96 }: StateTimelineProps) {
  const plot = width - labelWidth;
  const at = (ts: number) => formatTime(ts, tz);
  const legend = [...Object.values(states), ...Object.values(marks)];

  return (
    <figure aria-label={label} className="m-0">
      <svg width={width} height={lanes.length * (laneHeight + 4)} role="img" aria-label={label}>
        {lanes.map((lane, i) => {
          const y = i * (laneHeight + 4);
          return (
            <g key={lane.id} data-lane={lane.id}>
              <text x={0} y={y + laneHeight - 3} fontSize={11} fill="var(--fg-subtle)" className="font-mono">
                {lane.id}
              </text>
              <g transform={`translate(${labelWidth} ${y})`}>
                <rect width={plot} height={laneHeight} fill="var(--bg-inset)" />
                {lane.segments.map((seg) => {
                  const box = segmentBox(seg, range, plot);
                  if (!box) return null;
                  const look = states[seg.state];
                  return (
                    <rect key={`${seg.from}-${seg.state}`} data-segment={seg.state} x={box.x} width={box.width} height={laneHeight} fill={look?.color ?? "var(--stopped)"}>
                      <title>{`${lane.id}: ${look?.label ?? seg.state} ${at(Math.max(seg.from, range.fromMs))}–${at(Math.min(seg.to, range.toMs))}`}</title>
                    </rect>
                  );
                })}
                {(lane.marks ?? [])
                  .filter((m) => m.ts >= range.fromMs && m.ts <= range.toMs)
                  .map((m) => (
                    <rect key={`${m.ts}-${m.kind}`} data-mark={m.kind} x={markX(m.ts, range, plot)} y={-2} width={MARK_WIDTH} height={laneHeight + 4} fill={marks[m.kind]?.color ?? "var(--crit)"}>
                      <title>{`${lane.id}: ${marks[m.kind]?.label ?? m.kind} at ${at(m.ts)}`}</title>
                    </rect>
                  ))}
              </g>
            </g>
          );
        })}
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-3 text-[11px] text-fg-subtle">
        {legend.map((l) => (
          <span key={l.label} className="flex items-center gap-1">
            <span aria-hidden="true" className="inline-block h-2 w-3 rounded-sm" style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
