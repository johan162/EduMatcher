/**
 * A small bar chart over time, one bar per point (the book drawer's trades and
 * traded value per minute).
 *
 * A thin imperative wrapper like PriceChart: Lightweight Charts owns the
 * canvas, this creates the chart once per theme and pushes data when it
 * changes.
 */

import { HistogramSeries, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { sessionTimeOptions } from "../lib/chart-time.js";
import { useLiveStore } from "../store/useLiveStore.js";
import type { LinePoint } from "../lib/bars.js";

export interface MinuteBarsProps {
  label: string;
  points: LinePoint[];
  /** Formats the price scale and the crosshair label. */
  format: (value: number) => string;
  theme: "dark" | "light";
  height?: number;
}

function token(name: string, fallback: string): string {
  if (typeof getComputedStyle === "undefined") return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function MinuteBars({ label, points, format, theme, height = 140 }: MinuteBarsProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sessionTimezone = useLiveStore((s) => s.sessionTimezone);
  const chartRef = useRef<IChartApi | null>(null);
  const bars = useRef<ISeriesApi<"Histogram"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const fg = token("--fg-subtle", "#8792a6");
    const grid = token("--border", "#262d3a");
    const tz = sessionTimeOptions(sessionTimezone);
    const chart = createChart(container, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: fg, attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: true, secondsVisible: false, tickMarkFormatter: tz.tickMarkFormatter },
      localization: tz.localization,
    });
    chartRef.current = chart;
    bars.current = chart.addSeries(HistogramSeries, {
      color: token("--accent", "#ffa028"),
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "custom", formatter: format, minMove: 1 },
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      bars.current = null;
    };
    // `format` is a module-level function at every call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, sessionTimezone]);

  useEffect(() => {
    bars.current?.setData(points.map((p) => ({ ...p, time: p.time as Time })));
    chartRef.current?.timeScale().fitContent();
  }, [points, theme]);

  return (
    <figure aria-label={label} data-widget="minute-bars" className="m-0 min-w-0">
      <figcaption className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{label}</figcaption>
      <div style={{ height }} ref={containerRef} />
      {points.length === 0 && <p className="m-0 mt-1 text-xs text-fg-faint">No trades today</p>}
    </figure>
  );
}
