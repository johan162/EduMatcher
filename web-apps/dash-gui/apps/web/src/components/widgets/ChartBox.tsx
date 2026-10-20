/**
 * Sizes a recharts chart: the panel's width in the app, a fixed one when
 * given. jsdom has no layout, so `ResponsiveContainer` would measure zero
 * there; tests pass `width` (design D2, "Watch out for").
 */

import { useEffect, useState, type ReactElement, type RefObject } from "react";
import { ResponsiveContainer } from "recharts";

/**
 * The element's content width, followed as it resizes; `fixed` when given
 * (tests: jsdom has neither layout nor ResizeObserver). 0 until measured.
 */
export function useElementWidth(ref: RefObject<HTMLElement | null>, fixed?: number): number {
  const [width, setWidth] = useState(fixed ?? 0);
  useEffect(() => {
    if (fixed !== undefined || !ref.current || typeof ResizeObserver === "undefined") return;
    const el = ref.current;
    const observer = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    observer.observe(el);
    setWidth(Math.floor(el.clientWidth));
    return () => observer.disconnect();
  }, [ref, fixed]);
  return fixed ?? width;
}

export function ChartBox({ width, height, children }: { width?: number; height: number; children: (size: { width?: number; height: number }) => ReactElement }) {
  if (width !== undefined) return children({ width, height });
  return (
    <ResponsiveContainer width="100%" height={height}>
      {children({ height })}
    </ResponsiveContainer>
  );
}

/** The n-th categorical series colour (index.css `--series-1..8`). */
export function seriesColor(i: number): string {
  return `var(--series-${(i % 8) + 1})`;
}

export const AXIS_TICK = { fill: "var(--fg-subtle)", fontSize: 11 };

/** An axis label kept on one line: Recharts wraps tick text at spaces ("763 MiB"). */
export function oneLine(format: (v: number) => string): (v: number) => string {
  return (v) => format(v).replace(/ /g, "\u00a0");
}
export const TOOLTIP_STYLE = {
  background: "var(--bg-raised)",
  border: "1px solid var(--border)",
  borderRadius: 4,
  fontSize: 12,
  color: "var(--fg)",
};
