/**
 * An inline trend line (stat tiles, table cells): the shape of the last few
 * values, scaled to its own min..max. Decoration beside a number, so it is
 * hidden from assistive technology; the number says the value.
 */

export interface SparklineProps {
  values: readonly number[];
  width?: number;
  height?: number;
  /** CSS colour; the current text colour by default. */
  color?: string;
}

/**
 * Polyline points for `values` in a width x height box (1 px inset). A
 * value that is not a finite number is left out (its neighbours join up);
 * a flat series is a line through the middle, not along the bottom.
 */
export function sparkPoints(values: readonly number[], width: number, height: number): string {
  const n = values.length;
  const finite = values.filter(Number.isFinite);
  if (finite.length === 0) return "";
  const lo = finite.reduce((a, b) => Math.min(a, b));
  const hi = finite.reduce((a, b) => Math.max(a, b));
  const step = n > 1 ? (width - 2) / (n - 1) : 0;
  const yOf = (v: number) => (hi > lo ? height - 1 - ((v - lo) / (hi - lo)) * (height - 2) : height / 2);
  return values
    .map((v, i) => (Number.isFinite(v) ? `${(n > 1 ? 1 + i * step : width / 2).toFixed(1)},${yOf(v).toFixed(1)}` : null))
    .filter((p): p is string => p !== null)
    .join(" ");
}

export function Sparkline({ values, width = 64, height = 16, color = "currentColor" }: SparklineProps) {
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="shrink-0">
      <polyline
        points={sparkPoints(values, width, height)}
        fill="none"
        stroke={color}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
