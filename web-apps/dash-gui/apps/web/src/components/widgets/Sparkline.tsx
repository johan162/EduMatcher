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

/** Polyline points for `values` in a width x height box (1 px inset). */
export function sparkPoints(values: readonly number[], width: number, height: number): string {
  if (values.length === 0) return "";
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const step = values.length > 1 ? (width - 2) / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = values.length > 1 ? 1 + i * step : width / 2;
      const y = height - 1 - ((v - lo) / span) * (height - 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
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
