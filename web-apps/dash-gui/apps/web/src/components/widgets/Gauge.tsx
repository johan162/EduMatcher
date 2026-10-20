/**
 * A 240° gauge (design §13): CPU, memory, disk in row 1.
 *
 * Angles are SVG's: degrees clockwise from the positive x axis, y down. The
 * arc runs clockwise from 150° (lower left) over 270° (the top) to 30°
 * (lower right), so min, mid and max sit at 150°, 270° and 30°. Threshold
 * bands are drawn as a thin outer ring; the value is a filled arc (or a
 * needle) in its level's colour, the level also in words below the value.
 * A value outside min..max is shown as it is and drawn at the end it passed;
 * no value (null, or not a finite number) shows "—" and an empty arc.
 * Every text is sized or cut to its space: the value and sub-text to the
 * inside of the arc, the min/max labels to their half of the base, the
 * caption to the gauge's width.
 */

import { useId } from "react";
import { clipText, fitFontSize } from "./svgText.js";
import { NO_VALUE } from "../../lib/format.js";
import { describeThresholds, levelOf, type Level, type Thresholds } from "../../lib/thresholds.js";
import { LEVEL } from "../../lib/status.js";

export const START_DEG = 150;
export const SWEEP_DEG = 240;

/** How far along the arc `value` is, 0..1, clamped; 0 for no value or an empty scale. */
export function valueFraction(value: number | null, min: number, max: number): number {
  if (value === null || !Number.isFinite(value) || !(max > min)) return 0;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

/** The angle of `value` on the arc, in [0, 360). */
export function valueAngle(value: number | null, min: number, max: number): number {
  return (START_DEG + valueFraction(value, min, max) * SWEEP_DEG) % 360;
}

function point(cx: number, cy: number, r: number, deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

/** An SVG arc path clockwise from `fromDeg` through `sweep` degrees. */
export function arcPath(cx: number, cy: number, r: number, fromDeg: number, sweep: number): string {
  if (sweep <= 0) return "";
  const [x0, y0] = point(cx, cy, r, fromDeg);
  const [x1, y1] = point(cx, cy, r, fromDeg + sweep);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${sweep > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

/** The threshold bands as [from, to, level] over min..max, in order. */
export function bands(min: number, max: number, t: Thresholds): [number, number, Level][] {
  if (!(max > min)) return [];
  const clamp = (v: number) => Math.min(max, Math.max(min, v));
  const warn = clamp(t.warn);
  const crit = t.crit === undefined ? undefined : clamp(t.crit);
  const out: [number, number, Level][] = t.invert
    ? crit === undefined
      ? [
          [min, warn, "WARN"],
          [warn, max, "OK"],
        ]
      : [
          [min, crit, "CRIT"],
          [crit, warn, "WARN"],
          [warn, max, "OK"],
        ]
    : crit === undefined
      ? [
          [min, warn, "OK"],
          [warn, max, "WARN"],
        ]
      : [
          [min, warn, "OK"],
          [warn, crit, "WARN"],
          [crit, max, "CRIT"],
        ];
  return out.filter(([a, b]) => b > a);
}

export interface GaugeProps {
  /** null: no figure yet. */
  value: number | null;
  min?: number;
  max?: number;
  thresholds?: Thresholds;
  /** Formats the value and the min/max labels. */
  format: (v: number) => string;
  label: string;
  /** Under the value: "host", "11.3 GiB"... */
  sub?: string;
  mode?: "arc" | "needle";
  size?: number;
}

export function Gauge({ value, min = 0, max = 100, thresholds, format, label, sub, mode = "arc", size = 160 }: GaugeProps) {
  const titleId = useId();
  const c = size / 2;
  const r = size * 0.4;
  const known = value !== null && Number.isFinite(value);
  const level = known && thresholds ? levelOf(value, thresholds) : null;
  const look = LEVEL[level ?? "OK"];
  const sweep = valueFraction(value, min, max) * SWEEP_DEG;
  const span = max - min;
  const text = known ? format(value) : NO_VALUE;
  const inner = r * 1.5; // the width inside the arc at the value's height
  const valueSize = fitFontSize(text, inner, size * 0.15);
  const subSize = size * 0.075;
  const edgeSize = size * 0.065;
  const half = size / 2 - 2; // each end label owns half the base
  const angleOf = (v: number) => START_DEG + ((v - min) / span) * SWEEP_DEG;
  // The needle is the outer part of a radius, clear of the value in the centre.
  const [nx0, ny0] = point(c, c, r * 0.6, START_DEG + sweep);
  const [nx, ny] = point(c, c, r * 1.02, START_DEG + sweep);
  const definition = thresholds ? describeThresholds(thresholds, format) : undefined;

  return (
    <figure
      role="meter"
      aria-label={label}
      aria-valuenow={known ? value : undefined}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuetext={known ? `${text}${level && level !== "OK" ? `, ${level}` : ""}` : "no value"}
      aria-describedby={definition ? titleId : undefined}
      data-widget="gauge"
      className="m-0 flex flex-col items-center"
      style={{ width: size, maxWidth: "100%" }}
    >
      {/* Drawn at `size`, scaled down by its viewBox in a narrower panel. */}
      <svg viewBox={`0 0 ${size} ${size * 0.86}`} style={{ width: "100%", height: "auto" }} className="block">
        {definition && <title id={titleId}>{definition}</title>}
        <path d={arcPath(c, c, r, START_DEG, SWEEP_DEG)} fill="none" stroke="var(--bg-inset)" strokeWidth={size * 0.09} />
        {thresholds &&
          bands(min, max, thresholds).map(([from, to, l]) => (
            <path
              key={`${from}-${l}`}
              data-band={l}
              d={arcPath(c, c, r + size * 0.065, angleOf(from), ((to - from) / span) * SWEEP_DEG)}
              fill="none"
              stroke={LEVEL[l].color}
              strokeWidth={size * 0.02}
            />
          ))}
        {!known ? null : mode === "arc" ? (
          <path
            data-testid="gauge-value"
            d={arcPath(c, c, r, START_DEG, sweep)}
            fill="none"
            stroke={look.color}
            strokeWidth={size * 0.09}
          />
        ) : (
          <line
            data-testid="gauge-value"
            x1={nx0.toFixed(2)}
            y1={ny0.toFixed(2)}
            x2={nx.toFixed(2)}
            y2={ny.toFixed(2)}
            stroke={look.color}
            strokeWidth={size * 0.025}
            strokeLinecap="round"
          />
        )}
        <text x={c} y={c} textAnchor="middle" dominantBaseline="middle" className="tabular" fill={known ? "var(--fg)" : "var(--stopped)"} fontSize={valueSize} fontWeight={600}>
          {text}
        </text>
        <text x={c} y={c + size * 0.15} textAnchor="middle" fill="var(--fg-subtle)" fontSize={subSize}>
          {clipText(sub ?? "", inner, subSize)}
        </text>
        {/* Anchored inward from the arc's ends, so a wide label stays inside the gauge. */}
        <text x={2} y={size * 0.84} textAnchor="start" fill="var(--fg-faint)" fontSize={edgeSize} className="tabular">
          {clipText(format(min), half, edgeSize)}
        </text>
        <text x={size - 2} y={size * 0.84} textAnchor="end" fill="var(--fg-faint)" fontSize={edgeSize} className="tabular">
          {clipText(format(max), half, edgeSize)}
        </text>
      </svg>
      <figcaption className="mt-1 flex w-full min-w-0 items-center justify-center gap-1.5 text-xs text-fg-subtle">
        <span className="truncate font-semibold uppercase tracking-wide" title={label}>
          {label}
        </span>
        {level && level !== "OK" && (
          <span className={`shrink-0 font-semibold ${look.text}`}>
            {look.glyph} {look.label}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
