/**
 * A 240° gauge (design §13): CPU, memory, disk in row 1.
 *
 * Angles are SVG's: degrees clockwise from the positive x axis, y down. The
 * arc runs clockwise from 150° (lower left) over 270° (the top) to 30°
 * (lower right), so min, mid and max sit at 150°, 270° and 30°. Threshold
 * bands are drawn as a thin outer ring; the value is a filled arc (or a
 * needle) in its level's colour, the level also in words below the value.
 * A value outside min..max is shown as it is and drawn at the end it passed.
 */

import { useId } from "react";
import { describeThresholds, levelOf, type Level, type Thresholds } from "../../lib/thresholds.js";
import { LEVEL } from "../../lib/status.js";

export const START_DEG = 150;
export const SWEEP_DEG = 240;

/** How far along the arc `value` is, 0..1, clamped. */
export function valueFraction(value: number, min: number, max: number): number {
  return max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0;
}

/** The angle of `value` on the arc, in [0, 360). */
export function valueAngle(value: number, min: number, max: number): number {
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
  value: number;
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
  const level = thresholds ? levelOf(value, thresholds) : "OK";
  const look = LEVEL[level];
  const sweep = valueFraction(value, min, max) * SWEEP_DEG;
  const span = max - min;
  const angleOf = (v: number) => START_DEG + ((v - min) / span) * SWEEP_DEG;
  // The needle is the outer part of a radius, clear of the value in the centre.
  const [nx0, ny0] = point(c, c, r * 0.6, START_DEG + sweep);
  const [nx, ny] = point(c, c, r * 1.02, START_DEG + sweep);
  const definition = thresholds ? describeThresholds(thresholds, format) : undefined;

  return (
    <figure
      role="meter"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuetext={`${format(value)}${level === "OK" ? "" : `, ${level}`}`}
      aria-describedby={definition ? titleId : undefined}
      className="m-0 flex flex-col items-center"
    >
      <svg width={size} height={size * 0.86} viewBox={`0 0 ${size} ${size * 0.86}`}>
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
        {mode === "arc" ? (
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
        <text x={c} y={c} textAnchor="middle" dominantBaseline="middle" className="tabular" fill="var(--fg)" fontSize={size * 0.15} fontWeight={600}>
          {format(value)}
        </text>
        <text x={c} y={c + size * 0.15} textAnchor="middle" fill="var(--fg-subtle)" fontSize={size * 0.075}>
          {sub ?? ""}
        </text>
        <text x={point(c, c, r, START_DEG)[0]} y={size * 0.8} textAnchor="middle" fill="var(--fg-faint)" fontSize={size * 0.065}>
          {format(min)}
        </text>
        <text x={point(c, c, r, START_DEG + SWEEP_DEG)[0]} y={size * 0.8} textAnchor="middle" fill="var(--fg-faint)" fontSize={size * 0.065}>
          {format(max)}
        </text>
      </svg>
      <figcaption className="mt-1 flex items-center gap-1.5 text-xs text-fg-subtle">
        <span className="font-semibold uppercase tracking-wide">{label}</span>
        {level !== "OK" && (
          <span className={`font-semibold ${look.text}`}>
            {look.glyph} {look.label}
          </span>
        )}
      </figcaption>
    </figure>
  );
}
